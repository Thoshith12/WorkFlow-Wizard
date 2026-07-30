"""
app.tasks.chunking — Celery tasks for the chunking & embedding pipeline.

Architecture (mirrors extraction.py / preprocessing.py patterns):

  chunking_orchestrator_task          (entry point per data_source)
    └─ chunk_page_batch_task × N      (parallel, per page-batch per document)
         └─ finalize_chunking_task    (when all doc batches complete)
              └─ Celery chord:
                   header: embed_chunk_batch_task × M   (parallel, per chunk batch)
                   callback: finalize_embedding_task    (when all embed batches done)

Redis coordination:
  - Lua scripts provide atomic counter decrement + fencing (same pattern as
    extraction.py) to avoid race conditions across parallel workers.
  - Fencing token (run_id) prevents stale batches from a previous aborted
    run from corrupting a new run.

On-demand model lifecycle:
  - Models are loaded from HF disk cache inside embed_chunk_batch_task.
  - Models are unloaded (+ VRAM cleared) inside finalize_embedding_task.
"""
import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from uuid import UUID

import redis as redis_lib
from celery import chord
from sqlalchemy import select, update

from app.core.celery_app import celery_app
from shared.config.settings import settings
from shared.database import server_manager
from shared.database.adapters import PostgresAdapter, RedisAdapter, QdrantAdapter
from app.core.lifespan import lifespan_handler
from app.models.data_source import DataSource
from app.models.document import Document
from app.models.chunk import Chunk
from app.models.enums.chunking import ChunkStatus, EmbeddingMode
from app.pipeline.chunking.service import (
    get_preprocessed_pages,
    apply_chunking_strategy,
    assign_global_indices,
    resolve_chunk_language,
)
from app.pipeline.chunking.embedding_adapter import (
    embed_texts,
    get_model_config,
    get_supported_languages,
    unload_models,
)
from app.config.language_map import LANGUAGE_MAP

logger = logging.getLogger(__name__)

# ── Sync Redis client (required inside Celery tasks) ─────────────────────────
sync_redis = redis_lib.Redis.from_url(settings.redis_url, decode_responses=True)

# ── Lua Scripts ───────────────────────────────────────────────────────────────

# Atomic: fencing check + write to hash + SADD (dedup) + DECR counter
LUA_STORE_CHUNK_BATCH = """
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

store_chunk_batch_script = sync_redis.register_script(LUA_STORE_CHUNK_BATCH)


# ── Database Lifespan Context ─────────────────────────────────────────────────

@asynccontextmanager
async def lifespan_context():
    """Connect all adapters for the duration of one async task event loop."""
    lifespan_handler._register_adapters()
    await server_manager.startup()
    try:
        yield
    finally:
        await server_manager.shutdown()


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _fetch_documents(data_source_id: UUID) -> List[Document]:
    postgres = server_manager.get("postgres")
    async with postgres.session_factory() as session:
        result = await session.execute(
            select(Document).where(Document.data_source_id == data_source_id)
        )
        return list(result.scalars().all())


async def _mark_data_source_status(data_source_id: UUID, status: str, error: Optional[str] = None) -> None:
    postgres = server_manager.get("postgres")
    async with postgres.session_factory() as session:
        async with session.begin():
            values: Dict[str, Any] = {"status": status}
            if error is not None:
                values["error"] = error
            await session.execute(
                update(DataSource).where(DataSource.id == data_source_id).values(**values)
            )


# ── Async Implementations ─────────────────────────────────────────────────────

async def _chunking_orchestrator_async(data_source_id_str: str, config_json: str) -> None:
    """
    Main orchestrator: for each document in the data source, dispatch
    chunk_page_batch_task workers one-per-page-batch using Redis atomic counters.
    """
    async with lifespan_context():
        try:
            config = json.loads(config_json) if config_json else {}
        except Exception:
            config = {}

        if "chunking_strategy" not in config:
            config["chunking_strategy"] = "recursive"
        if "recursive_config" not in config:
            config["recursive_config"] = {"chunk_size": 512, "chunk_overlap": 50}
        if "embedding_models" not in config:
            config["embedding_models"] = ["sentence-transformers/all-MiniLM-L6-v2"]
        if "embedding_mode" not in config:
            config["embedding_mode"] = "dense"

        config_json = json.dumps(config)
        data_source_id = UUID(data_source_id_str)
        job_id = data_source_id_str
        pages_per_batch: int = config.get("pages_per_batch", 10)

        logger.info(
            "Chunking pipeline started",
            extra={"event": "chunking_started", "data_source_id": data_source_id_str},
        )

        # Mark data source as chunking initiated
        await _mark_data_source_status(data_source_id, "chunking initiated")

        documents = await _fetch_documents(data_source_id)

        # One shared run_id for the whole data-source job
        run_id = str(uuid.uuid4())

        # Clean any stale keys from a previous run
        sync_redis.delete(
            f"chunk_run_{job_id}",
            f"chunk_counter_{job_id}",
            f"chunk_processed_batches_{job_id}",
            f"chunked_data_{job_id}",
            f"chunk_status_{job_id}",
        )
        sync_redis.set(f"chunk_run_{job_id}", run_id, ex=86400)

        # Total batches = sum of page batches across all documents
        total_batches = 0

        for doc in documents:
            redis_adapter = server_manager.get("redis")
            redis_client = redis_adapter.client

            pages = await get_preprocessed_pages(redis_client, data_source_id, doc.id)
            if not pages:
                logger.warning(
                    "Chunking: no preprocessed pages for doc %s — skipping.", doc.id
                )
                continue

            page_count = len(pages)
            batches = [
                pages[start: start + pages_per_batch]
                for start in range(0, page_count, pages_per_batch)
            ]
            total_batches += len(batches)

            for batch_idx, batch_pages in enumerate(batches):
                chunk_page_batch_task.delay(
                    data_source_id_str=data_source_id_str,
                    document_id_str=str(doc.id),
                    run_id=run_id,
                    batch_id=f"chunk_batch_{str(doc.id)}_{batch_idx}",
                    pages_json=json.dumps(batch_pages),
                    config_json=config_json,
                )

        if total_batches == 0:
            logger.warning("Chunking: zero page batches dispatched for ds=%s.", job_id)
            await _mark_data_source_status(data_source_id, "failed", "No preprocessed pages found.")
            return

        sync_redis.set(f"chunk_counter_{job_id}", total_batches, ex=86400)
        logger.info(
            "Chunking orchestrator dispatched %d batches for ds=%s run=%s",
            total_batches, job_id, run_id,
        )


async def _chunk_page_batch_async(
    self,
    data_source_id_str: str,
    document_id_str: str,
    run_id: str,
    batch_id: str,
    pages_json: str,
    config_json: str,
) -> None:
    """
    Worker: apply the chunking strategy to one page batch and write results
    to the Redis chunked_data hash. When the last batch completes (counter=0),
    dispatch finalize_chunking_task.
    """
    job_id = data_source_id_str

    if sync_redis.get(f"chunk_run_{job_id}") != run_id:
        logger.warning("Stale chunk batch %s — discarded.", batch_id)
        return

    if sync_redis.get(f"chunk_status_{job_id}") == "failed":
        return

    try:
        pages = json.loads(pages_json)
        try:
            config = json.loads(config_json) if config_json else {}
        except Exception:
            config = {}

        strategy = config.get("chunking_strategy", "recursive")
        strategy_config_key = f"{strategy}_config"
        strategy_config = config.get(strategy_config_key, {
            "chunk_size": 512,
            "chunk_overlap": 50,
        })

        from app.models.enums.chunking import ChunkingStrategy
        chunks = apply_chunking_strategy(
            pages=pages,
            strategy=ChunkingStrategy(strategy),
            config=strategy_config,
        )

        # Build Lua args: [batch_id, run_id, key1, val1, key2, val2, ...]
        argv = [batch_id, run_id]
        for cr in chunks:
            field_key = f"{document_id_str}_{cr.local_index}"
            field_val = json.dumps({
                "chunk_text":   cr.chunk_text,
                "page_number":  cr.page_number,
                "local_index":  cr.local_index,
                "is_parent":    cr.is_parent,
                "parent_index": cr.parent_index,
                "document_id":  document_id_str,
            })
            argv.extend([field_key, field_val])

        remaining = store_chunk_batch_script(
            keys=[
                f"chunked_data_{job_id}",
                f"chunk_processed_batches_{job_id}",
                f"chunk_counter_{job_id}",
                f"chunk_lock_{job_id}",
                f"chunk_run_{job_id}",
            ],
            args=argv,
        )

        if remaining in ("STALE", b"STALE"):
            logger.warning("Stale chunk batch %s (Lua atomic check) — discarded.", batch_id)
            return

        logger.debug(
            "Chunk batch %s complete: %d chunks, %s batches remaining.",
            batch_id, len(chunks), remaining,
        )

        if remaining == 0:
            logger.info(
                "All chunk batches complete for ds=%s. Dispatching finalize_chunking_task.",
                job_id,
            )
            finalize_chunking_task.delay(
                data_source_id_str=data_source_id_str,
                run_id=run_id,
                config_json=config_json,
            )

    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=10 * (2 ** self.request.retries))

        was_first = sync_redis.set(f"chunk_status_{job_id}", "failed", nx=True, ex=86400)
        if was_first:
            logger.error("Chunk batch %s permanently failed: %s", batch_id, exc)
            async with lifespan_context():
                await _mark_data_source_status(UUID(job_id), "failed", f"Chunk batch {batch_id}: {exc}")


async def _finalize_chunking_async(
    data_source_id_str: str,
    run_id: str,
    config_json: str,
) -> None:
    """
    Collect all chunks from Redis, bulk-insert into chunk_registry,
    then launch a Celery chord to embed them in parallel.
    """
    job_id = data_source_id_str
    config = json.loads(config_json)

    if sync_redis.get(f"chunk_run_{job_id}") != run_id:
        logger.warning("Stale finalize_chunking for job %s — discarded.", job_id)
        return

    # Collect all chunk entries from Redis hash
    raw_entries = sync_redis.hgetall(f"chunked_data_{job_id}")
    if not raw_entries:
        logger.error("finalize_chunking: no chunks found in Redis for job %s.", job_id)
        async with lifespan_context():
            await _mark_data_source_status(UUID(job_id), "failed", "No chunks produced.")
        return

    # Parse and group by document_id to resolve language
    chunks_per_doc: Dict[str, List] = {}
    for field_key, field_val in raw_entries.items():
        cr_data = json.loads(field_val)
        doc_id = cr_data["document_id"]
        chunks_per_doc.setdefault(doc_id, []).append(cr_data)

    # Sort each doc's chunks by local_index
    for doc_id in chunks_per_doc:
        chunks_per_doc[doc_id].sort(key=lambda x: x["local_index"])

    # Assign global indices and flatten
    global_idx = 0
    flat_chunks = []  # List of (doc_id_str, cr_data_dict)
    for doc_id_str, cr_list in chunks_per_doc.items():
        for cr_data in cr_list:
            cr_data["global_index"] = global_idx
            flat_chunks.append((doc_id_str, cr_data))
            global_idx += 1

    # Compute vector collection name
    primary_model = config["embedding_models"][0]
    model_cfg = get_model_config(primary_model)
    short_name = model_cfg["short_name"]
    dims = model_cfg["dimensions"]
    vector_collection = f"{data_source_id_str}_{short_name}_{dims}"

    # Build config snapshot to store in each chunk row
    config_snapshot = {
        "chunking_strategy":  config["chunking_strategy"],
        "embedding_mode":     config["embedding_mode"],
        "embedding_models":   config["embedding_models"],
        "vector_collection":  vector_collection,
    }

    async with lifespan_context():
        postgres = server_manager.get("postgres")
        redis_adapter = server_manager.get("redis")
        redis_client = redis_adapter.client

        # Fetch doc → language_detected map from DB
        data_source_id = UUID(data_source_id_str)
        docs = await _fetch_documents(data_source_id)
        doc_lang_map = {str(doc.id): doc.language_detected or [] for doc in docs}

        # Build chunk DB rows
        chunk_rows = []
        for doc_id_str, cr_data in flat_chunks:
            lang_list = doc_lang_map.get(doc_id_str, [])
            chunk_language = resolve_chunk_language(lang_list)

            chunk_rows.append({
                "job_id":           data_source_id,
                "data_source_id":   data_source_id,
                "document_id":      UUID(doc_id_str),
                "chunk_text":       cr_data["chunk_text"],
                "chunk_index":      cr_data["global_index"],
                "chunk_language":   chunk_language,
                "page_number":      cr_data.get("page_number"),
                "config":           config_snapshot,
                "status":           ChunkStatus.INITIATED.value,
                "vector_collection": vector_collection,
            })

        # Bulk insert chunk_registry rows
        from app.repositories.chunk import bulk_create_chunks
        async with postgres.session_factory() as session:
            async with session.begin():
                created_chunks = await bulk_create_chunks(session, chunk_rows)

        logger.info(
            "finalize_chunking: inserted %d chunks into chunk_registry for job=%s.",
            len(created_chunks), job_id,
        )

        # ── Update document_registry: mark all docs as 'chunking completed' ───
        doc_ids_chunked = list(chunks_per_doc.keys())
        async with postgres.session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(Document)
                    .where(Document.id.in_([UUID(d) for d in doc_ids_chunked]))
                    .values(pipeline_status="chunking completed")
                )
        logger.info(
            "finalize_chunking: marked %d documents as 'chunking completed' for job=%s.",
            len(doc_ids_chunked), job_id,
        )

        # Store chunk id + text + language in Redis for embedding tasks
        embed_data = {}
        for chunk in created_chunks:
            embed_data[str(chunk.id)] = json.dumps({
                "chunk_id":       str(chunk.id),
                "chunk_text":     chunk.chunk_text,
                "chunk_language": chunk.chunk_language,
                "chunk_index":    chunk.chunk_index,
            })
        await redis_client.hset(f"embed_queue_{job_id}", mapping=embed_data)
        await redis_client.expire(f"embed_queue_{job_id}", 86400)

    # Build Celery chord: embed batches → finalize_embedding callback
    chunks_per_batch: int = config.get("chunks_per_batch", 50)
    all_chunk_ids = list(embed_data.keys())
    batches = [
        all_chunk_ids[i: i + chunks_per_batch]
        for i in range(0, len(all_chunk_ids), chunks_per_batch)
    ]

    embed_tasks = [
        embed_chunk_batch_task.s(
            data_source_id_str=data_source_id_str,
            batch_id=f"embed_batch_{idx}",
            chunk_ids_json=json.dumps(batch),
            config_json=config_json,
            vector_collection=vector_collection,
        )
        for idx, batch in enumerate(batches)
    ]

    chord(embed_tasks)(
        finalize_embedding_task.s(
            data_source_id_str=data_source_id_str,
            config_json=config_json,
            vector_collection=vector_collection,
        )
    )

    logger.info(
        "finalize_chunking: launched %d embedding batches for job=%s.",
        len(batches), job_id,
    )


async def _embed_chunk_batch_async(
    self,
    data_source_id_str: str,
    batch_id: str,
    chunk_ids_json: str,
    config_json: str,
    vector_collection: str,
) -> Dict[str, Any]:
    """
    Embed a batch of chunks using the language-aware fallback model selection.
    Returns a dict mapping chunk_id → vector list (passed to chord callback).
    """
    config = json.loads(config_json)
    embedding_models: List[str] = config["embedding_models"]
    chunk_ids: List[str] = json.loads(chunk_ids_json)

    async with lifespan_context():
        postgres = server_manager.get("postgres")
        redis_adapter = server_manager.get("redis")
        redis_client = redis_adapter.client

        # Load chunk metadata from Redis embed_queue
        job_id = data_source_id_str
        fields_raw = await redis_client.hmget(f"embed_queue_{job_id}", chunk_ids)
        chunks_meta = []
        for raw in fields_raw:
            if raw:
                chunks_meta.append(json.loads(raw))

        if not chunks_meta:
            logger.warning("embed_chunk_batch %s: no chunk metadata found.", batch_id)
            return {}

        # Group chunks by the model that will embed them (language fallback)
        model_groups: Dict[str, List[Dict]] = {}  # model_name → [chunk_meta]
        failed_chunks: List[Dict] = []

        for meta in chunks_meta:
            lang = meta.get("chunk_language", "en")
            selected_model = None
            for model_name in embedding_models:
                supported = get_supported_languages(model_name)
                if "*" in supported or lang in supported:
                    selected_model = model_name
                    break

            if selected_model is None:
                lang_name = LANGUAGE_MAP.get(lang, lang)
                meta["_error"] = (
                    f"language '{lang}' ({lang_name}) not supported by any selected embedding model"
                )
                failed_chunks.append(meta)
            else:
                model_groups.setdefault(selected_model, []).append(meta)

        # Update failed chunks in DB
        if failed_chunks:
            failed_ids = [UUID(m["chunk_id"]) for m in failed_chunks]
            from app.repositories.chunk import bulk_update_chunk_status
            async with postgres.session_factory() as session:
                async with session.begin():
                    for meta in failed_chunks:
                        await bulk_update_chunk_status(
                            session,
                            [UUID(meta["chunk_id"])],
                            status=ChunkStatus.FAILED.value,
                            error=meta["_error"],
                        )
            logger.warning(
                "embed_chunk_batch %s: %d chunks marked FAILED (unsupported language).",
                batch_id, len(failed_chunks),
            )

        # Embed per model group
        result_vectors: Dict[str, Any] = {}

        for model_name, group in model_groups.items():
            texts = [m["chunk_text"] for m in group]
            try:
                # Update status → EMBEDDING
                from app.repositories.chunk import bulk_update_chunk_status
                group_ids = [UUID(m["chunk_id"]) for m in group]
                async with postgres.session_factory() as session:
                    async with session.begin():
                        await bulk_update_chunk_status(
                            session, group_ids, status=ChunkStatus.EMBEDDING.value
                        )

                vectors = embed_texts(texts, model_name, is_query=False)

                # Update status → EMBEDDINGS_GENERATED
                async with postgres.session_factory() as session:
                    async with session.begin():
                        await bulk_update_chunk_status(
                            session,
                            group_ids,
                            status=ChunkStatus.EMBEDDINGS_GENERATED.value,
                            embedding_model=model_name,
                        )

                for meta, vec in zip(group, vectors):
                    result_vectors[meta["chunk_id"]] = {
                        "vector":         vec,
                        "chunk_index":    meta["chunk_index"],
                        "chunk_text":     meta["chunk_text"],
                        "chunk_language": meta["chunk_language"],
                        "embedding_model": model_name,
                    }

                logger.info(
                    "embed_chunk_batch %s: embedded %d chunks with model=%s",
                    batch_id, len(group), model_name,
                )

            except Exception as exc:
                logger.error(
                    "embed_chunk_batch %s: embedding failed for model=%s: %s",
                    batch_id, model_name, exc,
                )
                from app.repositories.chunk import bulk_update_chunk_status
                group_ids = [UUID(m["chunk_id"]) for m in group]
                async with postgres.session_factory() as session:
                    async with session.begin():
                        await bulk_update_chunk_status(
                            session, group_ids,
                            status=ChunkStatus.FAILED.value,
                            error=f"Embedding error ({model_name}): {exc}",
                        )
                raise self.retry(exc=exc, countdown=10 * (2 ** self.request.retries))

    return result_vectors


async def _finalize_embedding_async(
    results: List[Dict[str, Any]],
    data_source_id_str: str,
    config_json: str,
    vector_collection: str,
) -> None:
    """
    Chord callback: create/verify the Qdrant collection, upsert all vectors,
    update chunk_registry to VECTOR_STORE_SUCCESSFUL, update the DataSource
    status, unload embedding models from VRAM, and clean up Redis keys.
    """
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        PointStruct,
        VectorParams,
        SparseVectorParams,
        SparseIndexParams,
    )

    config = json.loads(config_json)
    data_source_id = UUID(data_source_id_str)
    embedding_models: List[str] = config["embedding_models"]
    embedding_mode: str = config["embedding_mode"]
    job_id = data_source_id_str

    # Merge all batch results (chord header passes list of dicts)
    merged_vectors: Dict[str, Any] = {}
    for batch_result in results:
        if isinstance(batch_result, dict):
            merged_vectors.update(batch_result)

    if not merged_vectors:
        logger.warning("finalize_embedding: no vectors to upsert for job=%s.", job_id)
        async with lifespan_context():
            await _mark_data_source_status(data_source_id, "failed", "No vectors produced.")
        unload_models(embedding_models)
        return

    # Determine vector dimensions from primary model
    primary_model = embedding_models[0]
    model_cfg = get_model_config(primary_model)
    dims = model_cfg["dimensions"]

    async with lifespan_context():
        postgres = server_manager.get("postgres")

        # ── Create / verify Qdrant collection ────────────────────────────────
        qdrant = QdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
        )

        existing = [c.name for c in qdrant.get_collections().collections]
        if vector_collection not in existing:
            vectors_config = {}
            sparse_vectors_config = {}

            if embedding_mode in (EmbeddingMode.DENSE.value, EmbeddingMode.HYBRID.value):
                vectors_config["dense"] = VectorParams(
                    size=dims,
                    distance=Distance.COSINE,
                )

            if embedding_mode in (EmbeddingMode.HYBRID.value, EmbeddingMode.SPARSE.value):
                sparse_vectors_config["sparse"] = SparseVectorParams(
                    index=SparseIndexParams(on_disk=False)
                )

            qdrant.create_collection(
                collection_name=vector_collection,
                vectors_config=vectors_config if vectors_config else VectorParams(
                    size=dims, distance=Distance.COSINE
                ),
                sparse_vectors_config=sparse_vectors_config if sparse_vectors_config else None,
            )
            logger.info(
                "finalize_embedding: created Qdrant collection '%s' (dims=%d, mode=%s).",
                vector_collection, dims, embedding_mode,
            )
        else:
            logger.info(
                "finalize_embedding: Qdrant collection '%s' already exists — reusing.",
                vector_collection,
            )

        # ── Upsert vectors to Qdrant ──────────────────────────────────────────
        points = []
        successful_chunk_ids: List[UUID] = []

        for chunk_id_str, vdata in merged_vectors.items():
            vector = vdata["vector"]
            payload = {
                "chunk_index":    vdata["chunk_index"],
                "chunk_text":     vdata["chunk_text"],
                "chunk_language": vdata["chunk_language"],
                "embedding_model": vdata["embedding_model"],
                "job_id":         job_id,
                "data_source_id": data_source_id_str,
                "vector_collection": vector_collection,
            }

            if embedding_mode == EmbeddingMode.DENSE.value:
                vec_field = {"dense": vector}
            elif embedding_mode == EmbeddingMode.SPARSE.value:
                vec_field = {}  # BM25 sparse handled by Qdrant internally
            else:  # hybrid
                vec_field = {"dense": vector}

            points.append(
                PointStruct(
                    id=chunk_id_str,
                    vector=vec_field,
                    payload=payload,
                )
            )
            successful_chunk_ids.append(UUID(chunk_id_str))

        if points:
            qdrant.upsert(collection_name=vector_collection, points=points)
            logger.info(
                "finalize_embedding: upserted %d vectors to '%s'.",
                len(points), vector_collection,
            )

        # ── Update chunk_registry status ──────────────────────────────────────
        from app.repositories.chunk import bulk_update_chunk_status
        if successful_chunk_ids:
            async with postgres.session_factory() as session:
                async with session.begin():
                    await bulk_update_chunk_status(
                        session,
                        successful_chunk_ids,
                        status=ChunkStatus.VECTOR_STORE_SUCCESSFUL.value,
                        vector_collection=vector_collection,
                    )

        # ── Update document_registry: mark all docs as 'vector_store_successful' ─
        docs_in_job = await _fetch_documents(data_source_id)
        async with postgres.session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(Document)
                    .where(Document.data_source_id == data_source_id)
                    .values(pipeline_status="vector_store_successful")
                )
        logger.info(
            "finalize_embedding: marked %d documents as 'vector_store_successful' for job=%s.",
            len(docs_in_job), job_id,
        )

        # ── Update DataSource final status ────────────────────────────────────
        await _mark_data_source_status(data_source_id, "vector_store_successful")

        logger.info(
            "finalize_embedding: job=%s complete. %d vectors in Qdrant collection='%s'.",
            job_id, len(points), vector_collection,
        )

    # ── On-demand model unloading — free VRAM/RAM ─────────────────────────────
    unload_models(embedding_models)
    logger.info(
        "finalize_embedding: unloaded models %s for job=%s.",
        embedding_models, job_id,
    )

    # ── Redis cleanup ─────────────────────────────────────────────────────────
    sync_redis.delete(
        f"chunk_run_{job_id}",
        f"chunk_counter_{job_id}",
        f"chunk_processed_batches_{job_id}",
        f"chunked_data_{job_id}",
        f"chunk_status_{job_id}",
        f"chunk_lock_{job_id}",
        f"embed_queue_{job_id}",
    )
    logger.info("finalize_embedding: Redis keys cleaned for job=%s.", job_id)


# ── Celery Tasks ──────────────────────────────────────────────────────────────

@celery_app.task(bind=True, name="app.tasks.chunking.orchestrate")
def chunking_orchestrator_task(self, data_source_id_str: str, config_json: str) -> None:
    """
    Entry point: dispatches page-batch chunking tasks for all documents in
    a data source. Uses a shared run_id as a fencing token.
    """
    asyncio.run(_chunking_orchestrator_async(data_source_id_str, config_json))


@celery_app.task(bind=True, name="app.tasks.chunking.chunk_batch", max_retries=3)
def chunk_page_batch_task(
    self,
    data_source_id_str: str,
    document_id_str: str,
    run_id: str,
    batch_id: str,
    pages_json: str,
    config_json: str,
) -> None:
    """
    Worker: chunks one page-batch and writes results to Redis.
    Triggers finalize_chunking_task when the last batch completes.
    """
    asyncio.run(
        _chunk_page_batch_async(
            self,
            data_source_id_str,
            document_id_str,
            run_id,
            batch_id,
            pages_json,
            config_json,
        )
    )


@celery_app.task(name="app.tasks.chunking.finalize_chunking")
def finalize_chunking_task(data_source_id_str: str, run_id: str, config_json: str) -> None:
    """
    Finalizer: collects all chunks from Redis, bulk-inserts chunk_registry
    rows, then launches the embedding chord.
    """
    asyncio.run(_finalize_chunking_async(data_source_id_str, run_id, config_json))


@celery_app.task(bind=True, name="app.tasks.chunking.embed_batch", max_retries=3)
def embed_chunk_batch_task(
    self,
    data_source_id_str: str,
    batch_id: str,
    chunk_ids_json: str,
    config_json: str,
    vector_collection: str,
) -> Dict[str, Any]:
    """
    Chord member: embeds one batch of chunks using the language-aware model
    fallback. Returns a dict of chunk_id → vector data for the chord callback.
    """
    return asyncio.run(
        _embed_chunk_batch_async(
            self,
            data_source_id_str,
            batch_id,
            chunk_ids_json,
            config_json,
            vector_collection,
        )
    )


@celery_app.task(name="app.tasks.chunking.finalize_embedding")
def finalize_embedding_task(
    results: List[Dict[str, Any]],
    data_source_id_str: str,
    config_json: str,
    vector_collection: str,
) -> None:
    """
    Chord callback: creates/verifies the Qdrant collection, upserts all
    embedding vectors, marks chunks as VECTOR_STORE_SUCCESSFUL, unloads
    embedding models from VRAM, and cleans up Redis.
    """
    asyncio.run(
        _finalize_embedding_async(
            results,
            data_source_id_str,
            config_json,
            vector_collection,
        )
    )
