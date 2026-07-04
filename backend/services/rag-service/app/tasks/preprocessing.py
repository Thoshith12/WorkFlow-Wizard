"""
app.tasks.preprocessing — Celery tasks for parallel page-level document preprocessing.

Architecture:
  - preprocess_document_orchestrator_task: checks extraction completeness and
    dispatches parallel preprocessing batch tasks.
  - preprocess_page_batch_task: worker task, loads raw pages from Redis, cleans
    and quality filters them, and writes the results atomically to Redis.
  - finalize_preprocessing_task: callback task, runs language detection over
    all preprocessed pages, saves final output, updates Postgres status,
    and cleans up all transient Redis keys.
"""
import json
import logging
import uuid
import asyncio
from contextlib import asynccontextmanager

import redis as redis_lib
from sqlalchemy import update

from app.core.celery_app import celery_app
from shared.config.settings import settings
from shared.database import server_manager
from shared.database.adapters import PostgresAdapter, RedisAdapter, QdrantAdapter
from app.core.lifespan import lifespan_handler
from app.models.document import Document
from app.pipeline.preprocessing.steps import (
    fix_encoding,
    normalize_unicode,
    collapse_whitespace,
    passes_quality,
    detect_languages,
)

logger = logging.getLogger(__name__)

sync_redis = redis_lib.Redis.from_url(settings.redis_url, decode_responses=True)

PAGE_BATCH_SIZE = 10
_PREPROCESSED_TTL = 36 * 3600  # 36 hours

# ── Lua Scripts ───────────────────────────────────────────────────────────────

LUA_PREPROCESS_ORCHESTRATE = """
    local current_run = redis.call('GET', KEYS[1])
    if current_run ~= ARGV[1] then
        return "STALE"
    end
    local expected = tonumber(redis.call('GET', KEYS[2]) or '0')
    local actual   = redis.call('HLEN', KEYS[3])
    if expected ~= actual then
        return "MISMATCH"
    end
    redis.call('SET', KEYS[4], ARGV[2], 'EX', 86400)
    return "OK"
"""

LUA_STORE_PREP_BATCH = """
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

LUA_FINALIZATION = """
    local current_run = redis.call('GET', KEYS[1])
    if current_run ~= ARGV[1] then
        return "STALE"
    end
    return redis.call('HGETALL', KEYS[2])
"""

preprocess_orchestrate_script = sync_redis.register_script(LUA_PREPROCESS_ORCHESTRATE)
store_prep_batch_script       = sync_redis.register_script(LUA_STORE_PREP_BATCH)
lua_finalization_script       = sync_redis.register_script(LUA_FINALIZATION)


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

async def _mark_document_failed(doc_id: uuid.UUID, error_msg: str) -> None:
    postgres = server_manager.get("postgres")
    async with postgres.session_factory() as session:
        async with session.begin():
            await session.execute(
                update(Document)
                .where(Document.id == doc_id)
                .values(pipeline_status="failed", errors={"preprocessing_error": error_msg})
            )


# ── Async Task Implementations ───────────────────────────────────────────────

async def _preprocess_document_orchestrator_task_async(document_id_str: str, run_id: str, data_source_id_str: str) -> None:
    jobid  = document_id_str
    doc_id = uuid.UUID(document_id_str)

    logger.info(
        "Preprocessing pipeline started",
        extra={"event": "preprocessing_started", "data_source_id": data_source_id_str},
    )

    # Atomic Lua validation and initialization
    status = preprocess_orchestrate_script(
        keys=[
            f"current_run_{jobid}",
            f"expected_pages_{jobid}",
            f"extracted_text_{jobid}",
            f"prep_counter_{jobid}",
        ],
        args=[run_id, "0"],  # will overwrite with total batches below
    )

    if status in ("STALE", b"STALE"):
        logger.warning("Stale preprocess orchestration for doc %s — discarded.", jobid)
        return

    if status in ("MISMATCH", b"MISMATCH"):
        logger.error("Completeness check failed for doc %s — marking failed.", jobid)
        was_first = sync_redis.set(f"status_{jobid}", "failed", nx=True, ex=86400)
        if was_first:
            async with lifespan_context():
                await _mark_document_failed(doc_id, "Page count mismatch after extraction.")
        sync_redis.delete(f"lock_{jobid}")
        return

    logger.info(
        "Preprocessing pipeline processing document",
        extra={
            "event": "preprocessing_doc_started",
            "data_source_id": data_source_id_str,
            "document_id": document_id_str,
        },
    )

    try:
        expected_pages = int(sync_redis.get(f"expected_pages_{jobid}") or 0)
        batches = [
            (start, min(start + PAGE_BATCH_SIZE - 1, expected_pages))
            for start in range(1, expected_pages + 1, PAGE_BATCH_SIZE)
        ]
        total_batches = len(batches)

        # Set the correct count of preprocessing batches
        sync_redis.set(f"prep_counter_{jobid}", total_batches, ex=86400)

        for idx, (start_page, end_page) in enumerate(batches):
            preprocess_page_batch_task.delay(
                document_id_str=jobid,
                run_id=run_id,
                batch_id=f"prep_batch_{idx}",
                start_page=start_page,
                end_page=end_page,
                data_source_id_str=data_source_id_str,
            )

    except Exception as exc:
        logger.exception("Failed during preprocessing orchestration for doc %s: %s", jobid, exc)
        was_first = sync_redis.set(f"status_{jobid}", "failed", nx=True, ex=86400)
        if was_first:
            async with lifespan_context():
                await _mark_document_failed(doc_id, f"Preprocessing orchestration failed: {exc}")
        sync_redis.delete(f"lock_{jobid}")
        raise


async def _preprocess_page_batch_task_async(
    self,
    document_id_str: str,
    run_id: str,
    batch_id: str,
    start_page: int,
    end_page: int,
    data_source_id_str: str,
) -> None:
    jobid = document_id_str

    if sync_redis.get(f"current_run_{jobid}") != run_id:
        logger.warning("Stale preprocessing batch %s for doc %s — discarded before processing.", batch_id, jobid)
        return

    try:
        # Fetch the specific pages in this batch from the Redis Hash
        fields    = [str(p) for p in range(start_page, end_page + 1)]
        raw_pages = sync_redis.hmget(f"extracted_text_{jobid}", fields)

        pages_list = []
        for raw in raw_pages:
            if raw:
                pages_list.append(json.loads(raw))

        # Run preprocessing steps on this batch of pages
        preprocessed_pages = []
        for page in pages_list:
            page_num    = page.get("page_number", 0)
            raw_content = page.get("page_content", "")

            cleaned = fix_encoding(raw_content)
            cleaned = normalize_unicode(cleaned)
            cleaned = collapse_whitespace(cleaned)

            if passes_quality(cleaned):
                preprocessed_pages.append({
                    "page_number": page_num,
                    "content": cleaned,
                })

        total = len(pages_list)
        kept = len(preprocessed_pages)
        rejected = total - kept

        logger.info(
            "Preprocessing pipeline quality filter applied",
            extra={
                "event": "preprocessing_quality_filter_done",
                "data_source_id": data_source_id_str,
                "document_id": document_id_str,
                "total_pages": total,
                "pages_kept": kept,
                "pages_rejected": rejected,
                "rejected_page_numbers": [
                    p["page_number"] for p in pages_list 
                    if p["page_number"] not in [k["page_number"] for k in preprocessed_pages]
                ],
            },
        )

        # Log preprocessed batch text as a structured JSON object log for human readability
        batch_text = "\n".join([f"[Page {p['page_number']}]\n{p['content']}" for p in preprocessed_pages])
        logger.info(
            f"PREPROCESSED TEXT BATCH — Doc {jobid} (Pages {start_page} to {end_page})\n{batch_text}",
            extra={
                "event": "preprocessing_batch_text",
                "data_source_id": data_source_id_str,
                "document_id": document_id_str,
                "batch_id": batch_id,
                "start_page": start_page,
                "end_page": end_page,
            }
        )

        argv = [batch_id, run_id]
        for page in preprocessed_pages:
            argv.extend([str(page["page_number"]), json.dumps(page)])

        # Atomic Lua: fencing check + HSET + SADD + lock heartbeat + DECR prep counter
        remaining = store_prep_batch_script(
            keys=[
                f"preprocessed_hash_{jobid}",
                f"prep_processed_batches_{jobid}",
                f"prep_counter_{jobid}",
                f"lock_{jobid}",
                f"current_run_{jobid}",
            ],
            args=argv,
        )

        if remaining in ("STALE", b"STALE"):
            logger.warning("Stale preprocessing batch %s for doc %s — discarded atomically.", batch_id, jobid)
            return

        if sync_redis.get(f"status_{jobid}") == "failed":
            return

        if remaining == 0:
            finalize_preprocessing_task.delay(
                document_id_str=document_id_str,
                run_id=run_id,
                data_source_id_str=data_source_id_str,
            )

    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=10 * (2 ** self.request.retries))

        was_first = sync_redis.set(f"status_{jobid}", "failed", nx=True, ex=86400)
        if was_first:
            logger.error("Doc %s preprocessing batch %s permanently failed: %s", jobid, batch_id, exc)
            async with lifespan_context():
                await _mark_document_failed(uuid.UUID(jobid), f"Preprocessing batch {batch_id} failed: {exc}")
        sync_redis.delete(f"lock_{jobid}")


async def _finalize_preprocessing_task_async(document_id_str: str, run_id: str, data_source_id_str: str) -> None:
    jobid          = document_id_str
    doc_id         = uuid.UUID(document_id_str)
    data_source_id = uuid.UUID(data_source_id_str)

    # Atomic Lua: verify run_id and fetch all preprocessed pages
    result = lua_finalization_script(
        keys=[
            f"current_run_{jobid}",
            f"preprocessed_hash_{jobid}",
        ],
        args=[run_id],
    )

    if result in ("STALE", b"STALE"):
        logger.warning("Stale finalize task for doc %s — discarded.", jobid)
        return

    # result is a flat HGETALL list: [field1, val1, field2, val2, ...]
    pages_clean = sorted(
        [json.loads(result[i]) for i in range(1, len(result), 2)],
        key=lambda p: p["page_number"],
    )

    errors_blob = {}

    async def _write() -> None:
        postgres      = server_manager.get("postgres")
        redis_adapter = server_manager.get("redis")
        if not pages_clean:
            logger.warning("Doc %s: all pages rejected by quality filter.", doc_id)
            async with postgres.session_factory() as session:
                async with session.begin():
                    await session.execute(
                        update(Document)
                        .where(Document.id == doc_id)
                        .values(pipeline_status="rejected", language_detected=[], errors=errors_blob)
                    )
            return

        # Run language detection over the sorted clean pages
        detected_langs   = detect_languages(pages_clean)

        logger.info(
            "Preprocessing pipeline language detection completed",
            extra={
                "event": "preprocessing_lang_detected",
                "data_source_id": str(data_source_id),
                "document_id": str(doc_id),
                "languages": detected_langs,
            },
        )

        preprocessed_key = f"{data_source_id}_{doc_id}_preprocessed_text"

        await redis_adapter.client.set(
            preprocessed_key, json.dumps(pages_clean), ex=_PREPROCESSED_TTL
        )

        logger.info(
            "Preprocessing pipeline saved preprocessed text to Redis",
            extra={
                "event": "preprocessing_redis_saved",
                "data_source_id": str(data_source_id),
                "document_id": str(doc_id),
                "redis_key": preprocessed_key,
                "pages_stored": len(pages_clean),
            },
        )

        async with postgres.session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(Document)
                    .where(Document.id == doc_id)
                    .values(
                        pipeline_status="preprocessing completed",
                        language_detected=detected_langs,
                        errors=errors_blob,
                    )
                )

        logger.info(
            "Preprocessing pipeline document completed",
            extra={
                "event": "preprocessing_doc_completed",
                "data_source_id": str(data_source_id),
                "document_id": str(doc_id),
                "languages": detected_langs,
                "pages_kept": len(pages_clean),
                "pipeline_status": "preprocessing completed",
            },
        )

    async with lifespan_context():
        await _write()

    # Delete all transient keys (extraction + preprocessing keys)
    sync_redis.delete(
        f"extracted_text_{jobid}",
        f"processed_batches_{jobid}",
        f"expected_pages_{jobid}",
        f"counter_{jobid}",
        f"preprocessed_hash_{jobid}",
        f"prep_processed_batches_{jobid}",
        f"prep_counter_{jobid}",
        f"status_{jobid}",
        f"lock_{jobid}",
        f"current_run_{jobid}",
    )


# ── Celery Tasks ──────────────────────────────────────────────────────────────

@celery_app.task(name="app.tasks.preprocessing.orchestrate")
def preprocess_document_orchestrator_task(document_id_str: str, run_id: str, data_source_id_str: str) -> None:
    """
    Orchestrates batched preprocessing by verifying extraction completeness
    and dispatching parallel preprocess_page_batch_task tasks.
    """
    asyncio.run(_preprocess_document_orchestrator_task_async(document_id_str, run_id, data_source_id_str))


@celery_app.task(bind=True, name="app.tasks.preprocessing.preprocess_batch", max_retries=3)
def preprocess_page_batch_task(
    self,
    document_id_str: str,
    run_id: str,
    batch_id: str,
    start_page: int,
    end_page: int,
    data_source_id_str: str,
) -> None:
    """
    Worker task: loads a slice of extracted pages from Redis, cleans and filters them,
    and stores them atomically in the preprocessed hash via Lua.
    """
    asyncio.run(
        _preprocess_page_batch_task_async(
            self,
            document_id_str,
            run_id,
            batch_id,
            start_page,
            end_page,
            data_source_id_str,
        )
    )


@celery_app.task(name="app.tasks.preprocessing.finalize")
def finalize_preprocessing_task(document_id_str: str, run_id: str, data_source_id_str: str) -> None:
    """
    Callback task: runs language detection over all preprocessed pages, saves
    the final document-wide preprocessed payload to Redis, updates Postgres,
    and deletes all transient extraction & preprocessing keys.
    """
    asyncio.run(_finalize_preprocessing_task_async(document_id_str, run_id, data_source_id_str))
