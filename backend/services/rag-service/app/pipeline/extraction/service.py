import json
import logging
import os
import tempfile
from uuid import UUID
from sqlalchemy import select, update
from shared.database import server_manager
from app.services.minio import minio_client
from app.models.document import Document
from app.models.data_source import DataSource

logger = logging.getLogger(__name__)

async def run_extraction_pipeline(data_source_id: UUID) -> None:
    """
    Asynchronously extracts text from all documents associated with the given data source.
    On completion triggers the preprocessing pipeline.
    """
    logger.info(
        "Extraction pipeline started",
        extra={"event": "extraction_started", "data_source_id": str(data_source_id)},
    )

    postgres = server_manager.get("postgres")
    redis_adapter = server_manager.get("redis")
    redis_client = redis_adapter.client

    # 1. Update DataSource and all Documents to "extraction initiated"
    try:
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
    except Exception as exc:
        logger.exception(
            "Extraction pipeline failed to update initial status",
            extra={"event": "extraction_status_update_failed", "data_source_id": str(data_source_id), "error": str(exc)},
        )
        return

    # Fetch documents
    documents = []
    try:
        async with postgres.session_factory() as session:
            result = await session.execute(
                select(Document).where(Document.data_source_id == data_source_id)
            )
            documents = list(result.scalars().all())
    except Exception as exc:
        logger.exception(
            "Extraction pipeline failed to fetch documents",
            extra={"event": "extraction_fetch_failed", "data_source_id": str(data_source_id), "error": str(exc)},
        )
        async with postgres.session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(DataSource)
                    .where(DataSource.id == data_source_id)
                    .values(status="failed", error=f"Failed to fetch documents: {exc}")
                )
        return

    # 2. Extract text for each document
    has_errors = False
    for doc in documents:
        doc_id = doc.id
        file_name = doc.file_name
        storage_path = doc.config.get("storage_path")

        logger.info(
            "Extraction pipeline processing document",
            extra={
                "event": "extraction_doc_started",
                "data_source_id": str(data_source_id),
                "document_id": str(doc_id),
                "file_name": file_name,
            },
        )

        if not storage_path:
            err_msg = "Storage path not found in document config"
            logger.error(
                "Extraction pipeline document missing storage path",
                extra={
                    "event": "extraction_doc_failed",
                    "data_source_id": str(data_source_id),
                    "document_id": str(doc_id),
                    "file_name": file_name,
                    "error": err_msg,
                },
            )
            async with postgres.session_factory() as session:
                async with session.begin():
                    await session.execute(
                        update(Document)
                        .where(Document.id == doc_id)
                        .values(
                            pipeline_status="failed",
                            errors={"extraction_error": err_msg},
                        )
                    )
            has_errors = True
            continue

        try:
            # 2a. Download from MinIO
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

            # 2b. Extract text based on file format
            ext = os.path.splitext(file_name)[1].lower()

            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp_file:
                tmp_file.write(file_bytes)
                tmp_file_path = tmp_file.name

            try:
                pages_data = []
                if ext == ".pdf":
                    from langchain_community.document_loaders import PyPDFLoader
                    loader = PyPDFLoader(tmp_file_path)
                    docs = loader.load()
                    for item in docs:
                        pages_data.append({
                            "page_number": item.metadata.get("page", 0) + 1,
                            "page_content": item.page_content,
                            "metadata": item.metadata,
                        })
                elif ext in (".doc", ".docx"):
                    from langchain_community.document_loaders import Docx2txtLoader
                    loader = Docx2txtLoader(tmp_file_path)
                    docs = loader.load()
                    for idx, item in enumerate(docs):
                        pages_data.append({
                            "page_number": item.metadata.get("page", 0) + 1,
                            "page_content": item.page_content,
                            "metadata": item.metadata,
                        })
                elif ext == ".txt":
                    from langchain_community.document_loaders import TextLoader
                    loader = TextLoader(tmp_file_path, encoding="utf-8")
                    docs = loader.load()
                    for idx, item in enumerate(docs):
                        pages_data.append({
                            "page_number": item.metadata.get("page", 0) + 1,
                            "page_content": item.page_content,
                            "metadata": item.metadata,
                        })
                else:
                    raise ValueError(f"Unsupported file type: {ext}")
            finally:
                if os.path.exists(tmp_file_path):
                    os.remove(tmp_file_path)

            # 2c. Store extracted pages in Redis
            redis_key = f"{data_source_id}_{doc_id}_extracted_text"
            serialized_data = json.dumps(pages_data)
            await redis_client.set(redis_key, serialized_data, ex=129600)

            total_chars = sum(len(p["page_content"]) for p in pages_data)
            logger.info(
                "Extraction pipeline document completed",
                extra={
                    "event": "extraction_doc_completed",
                    "data_source_id": str(data_source_id),
                    "document_id": str(doc_id),
                    "file_name": file_name,
                    "file_type": ext,
                    "pages_extracted": len(pages_data),
                    "total_chars": total_chars,
                    "redis_key": redis_key,
                },
            )

            # Print pages to stdout for human readability (not logged as JSON)
            separator = "=" * 60
            print(f"\n{separator}", flush=True)
            print(f"EXTRACTED TEXT — {file_name}  ({len(pages_data)} page(s))", flush=True)
            print(separator, flush=True)
            for page in pages_data:
                print(f"\n[Page {page['page_number']}]\n{page['page_content']}", flush=True)
            print(f"{separator}\n", flush=True)

            # 2d. Update Document status
            async with postgres.session_factory() as session:
                async with session.begin():
                    await session.execute(
                        update(Document)
                        .where(Document.id == doc_id)
                        .values(
                            pipeline_status="extraction completed",
                        )
                    )

        except Exception as exc:
            logger.exception(
                "Extraction pipeline document failed",
                extra={
                    "event": "extraction_doc_failed",
                    "data_source_id": str(data_source_id),
                    "document_id": str(doc_id),
                    "file_name": file_name,
                    "error": str(exc),
                },
            )
            has_errors = True
            err_msg = str(exc)
            async with postgres.session_factory() as session:
                async with session.begin():
                    await session.execute(
                        update(Document)
                        .where(Document.id == doc_id)
                        .values(
                            pipeline_status="failed",
                            errors={"extraction_error": err_msg},
                        )
                    )

    # 3. Update DataSource final status
    try:
        async with postgres.session_factory() as session:
            async with session.begin():
                if has_errors:
                    await session.execute(
                        update(DataSource)
                        .where(DataSource.id == data_source_id)
                        .values(status="failed", error="One or more documents failed during text extraction")
                    )
                    logger.warning(
                        "Extraction pipeline completed with failures",
                        extra={"event": "extraction_completed_with_errors", "data_source_id": str(data_source_id)},
                    )
                else:
                    await session.execute(
                        update(DataSource)
                        .where(DataSource.id == data_source_id)
                        .values(status="extraction completed", error=None)
                    )
                    logger.info(
                        "Extraction pipeline completed successfully",
                        extra={"event": "extraction_completed", "data_source_id": str(data_source_id)},
                    )
    except Exception as exc:
        logger.exception(
            "Extraction pipeline failed to update final DataSource status",
            extra={"event": "extraction_final_status_failed", "data_source_id": str(data_source_id), "error": str(exc)},
        )

    # 4. Hand off to preprocessing pipeline
    logger.info(
        "Handing off to preprocessing pipeline",
        extra={"event": "preprocessing_handoff", "data_source_id": str(data_source_id)},
    )
    from app.pipeline.preprocessing import run_preprocessing_pipeline
    await run_preprocessing_pipeline(data_source_id)
