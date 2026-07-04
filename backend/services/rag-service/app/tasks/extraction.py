"""
app.tasks.extraction — Celery tasks for parallel page-level document extraction.

Architecture:
  - extract_document_orchestrator_task: entry point, dispatches one batch task
    per page range for each document in a data source.
  - extract_page_batch_task: worker task, downloads the file from MinIO, extracts
    only the requested page range using the appropriate loader (pypdf for PDFs,
    Docx2txt for Word, TextLoader for plain text), and writes the result
    atomically to a per-document Redis Hash via a Lua script.

When all batches complete (counter hits 0), this task dispatches
  app.tasks.preprocessing.orchestrate (defined in app/tasks/preprocessing.py)
to continue the pipeline.
"""
import json
import logging
import os
import tempfile
import uuid
import asyncio
from contextlib import asynccontextmanager

import redis as redis_lib
from sqlalchemy import select, update

from app.core.celery_app import celery_app
from shared.config.settings import settings
from shared.database import server_manager
from shared.database.adapters import PostgresAdapter, RedisAdapter, QdrantAdapter
from app.core.lifespan import lifespan_handler
from app.services.minio import minio_client
from app.models.document import Document
from app.models.data_source import DataSource

logger = logging.getLogger(__name__)

# ── Sync Redis client (required inside Celery tasks) ─────────────────────────
sync_redis = redis_lib.Redis.from_url(settings.redis_url, decode_responses=True)

PAGE_BATCH_SIZE = 10

# ── Lua Scripts ───────────────────────────────────────────────────────────────

LUA_STORE_BATCH = """
    local current_run = redis.call('GET', KEYS[5])
    if current_run ~= ARGV[2] then
        return "STALE"
    end
    for i = 3, #ARGV, 2 do
        redis.call('HSET', KEYS[1], ARGV[i], ARGV[i+1])
    end
    redis.call('EXPIRE', KEYS[1], 86400)
    local is_new = redis.call('SADD', KEYS[2], ARGV[1])
    redis.call('EXPIRE', KEYS[2], 86400)
    redis.call('EXPIRE', KEYS[5], 86400)
    redis.call('EXPIRE', KEYS[4], 300)
    if is_new == 1 then
        local remaining = redis.call('DECR', KEYS[3])
        redis.call('EXPIRE', KEYS[3], 86400)
        return remaining
    else
        return tonumber(redis.call('GET', KEYS[3]) or '0')
    end
"""

store_batch_script = sync_redis.register_script(LUA_STORE_BATCH)


# ── Database Lifespan Context Helper ─────────────────────────────────────────

@asynccontextmanager
async def lifespan_context():
    """Ensure database adapters are registered and connected for the duration of the task event loop."""
    lifespan_handler._register_adapters()
    await server_manager.startup()
    try:
        yield
    finally:
        await server_manager.shutdown()


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _download_to_tempfile(storage_path: str, file_name: str, doc_id: uuid.UUID, data_source_id: uuid.UUID) -> str:
    """Download a file from MinIO to a local temp file; return the path."""
    parts = storage_path.split("/")
    object_name = "/".join(parts[1:]) if len(parts) > 1 else storage_path

    logger.debug(
        "Extraction pipeline downloading object",
        extra={
            "event": "extraction_download_started",
            "data_source_id": str(data_source_id),
            "document_id": str(doc_id),
            "object_name": object_name,
        },
    )

    file_bytes = await minio_client.get_file(object_name)
    ext = os.path.splitext(file_name)[1].lower()
    fd, tmp_path = tempfile.mkstemp(suffix=ext)
    with os.fdopen(fd, "wb") as f:
        f.write(file_bytes)
    return tmp_path


def _get_page_count(tmp_path: str, ext: str) -> int:
    """Return the total number of pages/sections in the file."""
    if ext == ".pdf":
        from pypdf import PdfReader
        return len(PdfReader(tmp_path).pages)
    elif ext in (".doc", ".docx"):
        from langchain_community.document_loaders import Docx2txtLoader
        return len(Docx2txtLoader(tmp_path).load())
    elif ext == ".txt":
        from langchain_community.document_loaders import TextLoader
        return len(TextLoader(tmp_path, encoding="utf-8").load())
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def _extract_page_range(tmp_path: str, ext: str, start_page: int, end_page: int) -> list[dict]:
    """Extract only the requested page range from the file."""
    pages_data = []
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(tmp_path)
        for idx in range(start_page - 1, min(end_page, len(reader.pages))):
            text = reader.pages[idx].extract_text() or ""
            pages_data.append({
                "page_number": idx + 1,
                "page_content": text,
                "metadata": {"page": idx},
            })
    elif ext in (".doc", ".docx"):
        from langchain_community.document_loaders import Docx2txtLoader
        docs = Docx2txtLoader(tmp_path).load()
        for item in docs:
            page_num = item.metadata.get("page", 0) + 1
            if start_page <= page_num <= end_page:
                pages_data.append({
                    "page_number": page_num,
                    "page_content": item.page_content,
                    "metadata": item.metadata,
                })
    elif ext == ".txt":
        from langchain_community.document_loaders import TextLoader
        docs = TextLoader(tmp_path, encoding="utf-8").load()
        for item in docs:
            page_num = item.metadata.get("page", 0) + 1
            if start_page <= page_num <= end_page:
                pages_data.append({
                    "page_number": page_num,
                    "page_content": item.page_content,
                    "metadata": item.metadata,
                })
    return pages_data


async def _mark_document_failed(doc_id: uuid.UUID, error_msg: str) -> None:
    postgres = server_manager.get("postgres")
    async with postgres.session_factory() as session:
        async with session.begin():
            await session.execute(
                update(Document)
                .where(Document.id == doc_id)
                .values(pipeline_status="failed", errors={"extraction_error": error_msg})
            )


async def _fetch_documents(data_source_id: uuid.UUID) -> list[Document]:
    postgres = server_manager.get("postgres")
    async with postgres.session_factory() as session:
        async with session.begin():
            await session.execute(
                update(DataSource)
                .where(DataSource.id == data_source_id)
                .values(status="extraction initiated", error=None)
                )
            await session.execute(
                update(Document)
                .where(Document.data_source_id == data_source_id)
                .values(pipeline_status="extraction initiated")
            )
        result = await session.execute(
            select(Document).where(Document.data_source_id == data_source_id)
        )
        return list(result.scalars().all())


# ── Async Task Implementations ───────────────────────────────────────────────

async def _extract_document_orchestrator_task_async(data_source_id_str: str) -> None:
    async with lifespan_context():
        data_source_id = uuid.UUID(data_source_id_str)

        logger.info(
            "Extraction pipeline started",
            extra={"event": "extraction_started", "data_source_id": str(data_source_id)},
        )

        documents = await _fetch_documents(data_source_id)

        for doc in documents:
            jobid    = str(doc.id)
            lock_key = f"lock_{jobid}"

            logger.info(
                "Extraction pipeline processing document",
                extra={
                    "event": "extraction_doc_started",
                    "data_source_id": str(data_source_id),
                    "document_id": str(doc.id),
                    "file_name": doc.file_name,
                },
            )

            acquired = sync_redis.set(lock_key, "1", nx=True, ex=300)
            if not acquired:
                logger.warning("Doc %s already in flight, skipping.", doc.id)
                continue

            tmp_path = None
            try:
                run_id = str(uuid.uuid4())

                # Clean stale keys from any previous run
                sync_redis.delete(
                    f"extracted_text_{jobid}",
                    f"processed_batches_{jobid}",
                    f"counter_{jobid}",
                    f"expected_pages_{jobid}",
                    f"status_{jobid}",
                )
                sync_redis.set(f"current_run_{jobid}", run_id, ex=86400)

                # Determine file info
                storage_path = doc.config.get("storage_path", "")
                file_name    = doc.file_name
                ext          = os.path.splitext(file_name)[1].lower()

                tmp_path   = await _download_to_tempfile(storage_path, file_name, doc.id, data_source_id)
                page_count = _get_page_count(tmp_path, ext)

                batches = [
                    (start, min(start + PAGE_BATCH_SIZE - 1, page_count))
                    for start in range(1, page_count + 1, PAGE_BATCH_SIZE)
                ]
                total_batches = len(batches)

                # Zero-page guard
                if total_batches == 0:
                    logger.warning("Doc %s has 0 pages, routing directly to preprocessing.", doc.id)
                    celery_app.send_task(
                        "app.tasks.preprocessing.orchestrate",
                        kwargs={
                            "document_id_str": jobid,
                            "run_id": run_id,
                            "data_source_id_str": data_source_id_str,
                        },
                    )
                    continue

                sync_redis.set(f"expected_pages_{jobid}", page_count, ex=86400)
                sync_redis.set(f"counter_{jobid}", total_batches, ex=86400)

                for idx, (start_page, end_page) in enumerate(batches):
                    extract_page_batch_task.delay(
                        document_id_str=jobid,
                        run_id=run_id,
                        batch_id=f"batch_{idx}",
                        start_page=start_page,
                        end_page=end_page,
                        storage_path=storage_path,
                        file_name=file_name,
                        data_source_id_str=data_source_id_str,
                    )

            except Exception:
                sync_redis.delete(lock_key)
                raise
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)


async def _extract_page_batch_task_async(
    self,
    document_id_str: str,
    run_id: str,
    batch_id: str,
    start_page: int,
    end_page: int,
    storage_path: str,
    file_name: str,
    data_source_id_str: str,
) -> None:
    jobid  = document_id_str
    doc_id = uuid.UUID(document_id_str)
    ext    = os.path.splitext(file_name)[1].lower()

    # Cheap early staleness check before doing expensive extraction
    if sync_redis.get(f"current_run_{jobid}") != run_id:
        logger.warning("Stale batch %s for doc %s — discarded before extraction.", batch_id, jobid)
        return

    tmp_path = None
    try:
        tmp_path   = await _download_to_tempfile(storage_path, file_name, doc_id, uuid.UUID(data_source_id_str))
        pages_list = _extract_page_range(tmp_path, ext, start_page, end_page)

        # Log extracted batch text as a structured JSON object log for human readability
        batch_text = "\n".join([f"[Page {p['page_number']}]\n{p['page_content']}" for p in pages_list])
        logger.info(
            f"EXTRACTED TEXT BATCH — {file_name} (Pages {start_page} to {end_page})\n{batch_text}",
            extra={
                "event": "extraction_batch_text",
                "data_source_id": data_source_id_str,
                "document_id": document_id_str,
                "batch_id": batch_id,
                "start_page": start_page,
                "end_page": end_page,
            }
        )

        argv = [batch_id, run_id]
        for page in pages_list:
            argv.extend([str(page["page_number"]), json.dumps(page)])

        # Atomic Lua: fencing check + HSET + SADD + lock heartbeat + DECR
        remaining = store_batch_script(
            keys=[
                f"extracted_text_{jobid}",
                f"processed_batches_{jobid}",
                f"counter_{jobid}",
                f"lock_{jobid}",
                f"current_run_{jobid}",
            ],
            args=argv,
        )

        if remaining in ("STALE", b"STALE"):
            logger.warning("Stale batch %s for doc %s — discarded atomically.", batch_id, jobid)
            return

        # Belt-and-suspenders: if a sibling batch permanently failed, stop here.
        if sync_redis.get(f"status_{jobid}") == "failed":
            return

        if remaining == 0:
            logger.info(
                "Extraction pipeline document completed",
                extra={
                    "event": "extraction_doc_completed",
                    "data_source_id": data_source_id_str,
                    "document_id": document_id_str,
                    "file_name": file_name,
                    "file_type": ext,
                    "pages_extracted": len(pages_list),  # pages in last batch (non-trivial sum omitted)
                    "redis_key": f"extracted_text_{jobid}",
                },
            )

            # Dispatch the preprocessing orchestrator task (defined in app/tasks/preprocessing.py)
            # using send_task to avoid a circular import.
            celery_app.send_task(
                "app.tasks.preprocessing.orchestrate",
                kwargs={
                    "document_id_str": document_id_str,
                    "run_id": run_id,
                    "data_source_id_str": data_source_id_str,
                },
            )

    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=10 * (2 ** self.request.retries))

        # First permanent failure marks the document and releases the lock.
        was_first = sync_redis.set(f"status_{jobid}", "failed", nx=True, ex=86400)
        if was_first:
            logger.error("Doc %s batch %s permanently failed: %s", doc_id, batch_id, exc)
            async with lifespan_context():
                await _mark_document_failed(doc_id, f"Batch {batch_id} failed: {exc}")
        sync_redis.delete(f"lock_{jobid}")

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


# ── Celery Tasks ──────────────────────────────────────────────────────────────

@celery_app.task(bind=True, name="app.tasks.extraction.orchestrate")
def extract_document_orchestrator_task(self, data_source_id_str: str) -> None:
    """
    Orchestrator: fetches all documents for the data source, acquires a
    per-document lock, generates a fencing token (run_id), computes the page
    count, and dispatches one extract_page_batch_task per page batch.
    """
    asyncio.run(_extract_document_orchestrator_task_async(data_source_id_str))


@celery_app.task(bind=True, name="app.tasks.extraction.extract_batch", max_retries=3)
def extract_page_batch_task(
    self,
    document_id_str: str,
    run_id: str,
    batch_id: str,
    start_page: int,
    end_page: int,
    storage_path: str,
    file_name: str,
    data_source_id_str: str,
) -> None:
    """
    Worker task: downloads the file, extracts the given page range using the
    appropriate loader, and writes results atomically to Redis via Lua.
    """
    asyncio.run(
        _extract_page_batch_task_async(
            self,
            document_id_str,
            run_id,
            batch_id,
            start_page,
            end_page,
            storage_path,
            file_name,
            data_source_id_str,
        )
    )
