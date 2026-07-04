"""
app.pipeline.preprocessing.service — Pre-Processing Pipeline.

Reads raw extracted pages from Redis, applies cleaning + quality filtering,
detects languages, writes cleaned pages back to Redis, and deletes the raw key.

Redis key conventions:
  Input:  {data_source_id}_{document_id}_extracted_text     (written by extraction)
  Output: {data_source_id}_{document_id}_preprocessed_text  (consumed by chunking)

Preprocessed payload format:
  [{"page_number": 1, "content": "cleaned text..."}]
  Only quality-passing pages are included.

pipeline_status transitions:
  preprocessing initiated → preprocessing completed | rejected | failed

errors JSONB:
  {"preprocessing_error": [{"page_number": N, "reason": "rejected by quality filter"}]}
"""
import json
import logging
from uuid import UUID

from sqlalchemy import select, update

from shared.database import server_manager
from app.models.document import Document
from app.models.data_source import DataSource
from app.pipeline.preprocessing.steps import (
    fix_encoding,
    normalize_unicode,
    collapse_whitespace,
    passes_quality,
    detect_languages,
)

logger = logging.getLogger(__name__)

_REDIS_TTL_SECONDS = 36 * 3600


async def run_preprocessing_pipeline(data_source_id: UUID) -> None:
    """
    Run preprocessing for all documents of a given DataSource.
    Triggered by the extraction pipeline after all documents are extracted.
    """
    logger.info(
        "Preprocessing pipeline started",
        extra={"event": "preprocessing_started", "data_source_id": str(data_source_id)},
    )

    postgres = server_manager.get("postgres")
    redis_adapter = server_manager.get("redis")
    redis_client = redis_adapter.client

    # Mark all docs as preprocessing initiated
    try:
        async with postgres.session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(DataSource)
                    .where(DataSource.id == data_source_id)
                    .values(status="preprocessing initiated", error=None)
                )
                await session.execute(
                    update(Document)
                    .where(Document.data_source_id == data_source_id)
                    .values(pipeline_status="preprocessing initiated")
                )
    except Exception as exc:
        logger.exception(
            "Preprocessing pipeline failed to update initial status",
            extra={"event": "preprocessing_status_update_failed", "data_source_id": str(data_source_id), "error": str(exc)},
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
            "Preprocessing pipeline failed to fetch documents",
            extra={"event": "preprocessing_fetch_failed", "data_source_id": str(data_source_id), "error": str(exc)},
        )
        async with postgres.session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(DataSource)
                    .where(DataSource.id == data_source_id)
                    .values(status="failed", error=f"Failed to fetch documents: {exc}")
                )
        return

    has_errors = False

    for doc in documents:
        doc_id = doc.id
        file_name = doc.file_name
        extracted_key = f"{data_source_id}_{doc_id}_extracted_text"
        preprocessed_key = f"{data_source_id}_{doc_id}_preprocessed_text"

        logger.info(
            "Preprocessing pipeline processing document",
            extra={
                "event": "preprocessing_doc_started",
                "data_source_id": str(data_source_id),
                "document_id": str(doc_id),
                "file_name": file_name,
            },
        )

        try:
            # 1. Load extracted pages from Redis
            raw = await redis_client.get(extracted_key)
            if raw is None:
                raise ValueError(f"Extracted text not found in Redis for key '{extracted_key}'")
            pages_data = json.loads(raw)

            # 2. Clean + quality-filter each page
            kept_pages = []
            rejected_entries = []

            for page in pages_data:
                page_num = page.get("page_number", 0)
                raw_content = page.get("page_content", "")
                
                # Run the 3 cleaning steps sequentially
                cleaned = fix_encoding(raw_content)
                cleaned = normalize_unicode(cleaned)
                cleaned = collapse_whitespace(cleaned)

                if passes_quality(cleaned):
                    kept_pages.append({"page_number": page_num, "content": cleaned})
                else:
                    rejected_entries.append({
                        "page_number": page_num,
                        "reason": "rejected by quality filter",
                    })

            total = len(pages_data)
            kept = len(kept_pages)
            rejected = len(rejected_entries)

            logger.info(
                "Preprocessing pipeline quality filter applied",
                extra={
                    "event": "preprocessing_quality_filter_done",
                    "data_source_id": str(data_source_id),
                    "document_id": str(doc_id),
                    "file_name": file_name,
                    "total_pages": total,
                    "pages_kept": kept,
                    "pages_rejected": rejected,
                    "rejected_page_numbers": [e["page_number"] for e in rejected_entries],
                },
            )

            # Build errors blob (only if pages were rejected)
            errors_blob = {}
            if rejected_entries:
                errors_blob["preprocessing_error"] = rejected_entries

            # 3. Handle fully-rejected document
            if not kept_pages:
                logger.warning(
                    "Preprocessing pipeline rejected all pages",
                    extra={
                        "event": "preprocessing_doc_rejected",
                        "data_source_id": str(data_source_id),
                        "document_id": str(doc_id),
                        "file_name": file_name,
                        "total_pages": total,
                        "pipeline_status": "rejected",
                    },
                )
                await redis_client.delete(extracted_key)
                async with postgres.session_factory() as session:
                    async with session.begin():
                        await session.execute(
                            update(Document)
                            .where(Document.id == doc_id)
                            .values(pipeline_status="rejected", language_detected=[], errors=errors_blob)
                        )
                has_errors = True
                continue

            # 4. Detect languages
            detected_langs = detect_languages(kept_pages)
            logger.info(
                "Preprocessing pipeline language detection completed",
                extra={
                    "event": "preprocessing_lang_detected",
                    "data_source_id": str(data_source_id),
                    "document_id": str(doc_id),
                    "file_name": file_name,
                    "languages": detected_langs,
                    "sample_count": 3,
                },
            )

            # 5. Write preprocessed pages to Redis
            serialized = json.dumps(kept_pages)
            await redis_client.set(preprocessed_key, serialized, ex=_REDIS_TTL_SECONDS)
            logger.info(
                "Preprocessing pipeline saved preprocessed text to Redis",
                extra={
                    "event": "preprocessing_redis_saved",
                    "data_source_id": str(data_source_id),
                    "document_id": str(doc_id),
                    "file_name": file_name,
                    "redis_key": preprocessed_key,
                    "pages_stored": kept,
                },
            )

            # Print cleaned pages to stdout for human readability
            separator = "=" * 60
            print(f"\n{separator}", flush=True)
            print(f"PREPROCESSED TEXT — {file_name}  ({kept} kept / {total} total page(s))", flush=True)
            print(separator, flush=True)
            for page in kept_pages:
                print(f"\n[Page {page['page_number']}]\n{page['content']}", flush=True)
            print(f"{separator}\n", flush=True)

            # 6. Delete raw extracted text from Redis
            await redis_client.delete(extracted_key)
            logger.info(
                "Preprocessing pipeline deleted raw extracted text from Redis",
                extra={
                    "event": "preprocessing_redis_cleaned",
                    "data_source_id": str(data_source_id),
                    "document_id": str(doc_id),
                    "file_name": file_name,
                    "deleted_key": extracted_key,
                },
            )

            # 7. Update Document in DB
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
                    "file_name": file_name,
                    "languages": detected_langs,
                    "pages_kept": kept,
                    "pages_rejected": rejected,
                    "pipeline_status": "preprocessing completed",
                },
            )

        except Exception as exc:
            logger.exception(
                "Preprocessing pipeline document failed",
                extra={
                    "event": "preprocessing_doc_failed",
                    "data_source_id": str(data_source_id),
                    "document_id": str(doc_id),
                    "file_name": file_name,
                    "error": str(exc),
                },
            )
            has_errors = True
            async with postgres.session_factory() as session:
                async with session.begin():
                    await session.execute(
                        update(Document)
                        .where(Document.id == doc_id)
                        .values(
                            pipeline_status="failed",
                            errors={"preprocessing_error": str(exc)},
                        )
                    )
            try:
                await redis_client.delete(extracted_key)
            except Exception:
                pass

    # Update DataSource final status
    try:
        async with postgres.session_factory() as session:
            async with session.begin():
                if has_errors:
                    await session.execute(
                        update(DataSource)
                        .where(DataSource.id == data_source_id)
                        .values(
                            status="failed",
                            error="One or more documents failed or were rejected during preprocessing",
                        )
                    )
                    logger.warning(
                        "Preprocessing pipeline completed with issues",
                        extra={"event": "preprocessing_completed_with_errors", "data_source_id": str(data_source_id)},
                    )
                else:
                    await session.execute(
                        update(DataSource)
                        .where(DataSource.id == data_source_id)
                        .values(status="preprocessing completed", error=None)
                    )
                    logger.info(
                        "Preprocessing pipeline completed successfully",
                        extra={"event": "preprocessing_completed", "data_source_id": str(data_source_id)},
                    )
    except Exception as exc:
        logger.exception(
            "Preprocessing pipeline failed to update final DataSource status",
            extra={"event": "preprocessing_final_status_failed", "data_source_id": str(data_source_id), "error": str(exc)},
        )
