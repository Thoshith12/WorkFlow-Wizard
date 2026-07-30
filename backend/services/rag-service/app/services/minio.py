"""
app.services.minio — MinIO S3 Object Storage client.

Provides an asynchronous wrapper around the official MinIO Python SDK.
Offloads blocking I/O calls (bucket creation, object uploads) to worker threads
to keep the FastAPI asyncio event loop non-blocking and highly responsive.

Key Features:
  - Automatic bucket initialization on startup or upload (`rag-documents`).
  - Thread-pool offloading via `asyncio.to_thread`.
  - Content stream uploading with length and MIME type metadata.

Usage:
    from app.services.minio import minio_client
    path = await minio_client.upload(data_source_id, filename, content_bytes, content_type)
"""
import asyncio
import io
import logging
from typing import Optional
from uuid import UUID

from minio import Minio
from minio.error import S3Error

from shared.config.settings import settings

logger = logging.getLogger(__name__)


class MinioStorageClient:
    """Async wrapper client for MinIO Object Storage operations."""

    def __init__(self) -> None:
        self._client: Optional[Minio] = None
        self._bucket_initialized = False

    def _get_client(self) -> Minio:
        """Lazily initialize the sync MinIO SDK client."""
        if self._client is None:
            endpoint = settings.MINIO_ENDPOINT.replace("http://", "").replace("https://", "")
            logger.info("Initializing MinIO client targeting endpoint: %s", endpoint)
            self._client = Minio(
                endpoint=endpoint,
                access_key=settings.MINIO_ROOT_USER,
                secret_key=settings.MINIO_ROOT_PASSWORD,
                secure=settings.MINIO_SECURE,
            )
        return self._client

    def _ensure_bucket_sync(self, bucket_name: str) -> None:
        """Synchronous helper to check and create bucket if missing."""
        client = self._get_client()
        try:
            if not client.bucket_exists(bucket_name):
                logger.info("MinIO bucket '%s' does not exist. Creating...", bucket_name)
                client.make_bucket(bucket_name)
                logger.info("MinIO bucket '%s' created successfully.", bucket_name)
        except S3Error as exc:
            logger.error("MinIO S3Error during bucket initialization: %s", exc)
            raise

    async def ensure_bucket(self, bucket_name: Optional[str] = None) -> None:
        """Asynchronously ensure target bucket exists."""
        target_bucket = bucket_name or settings.MINIO_BUCKET
        if not self._bucket_initialized:
            await asyncio.to_thread(self._ensure_bucket_sync, target_bucket)
            self._bucket_initialized = True

    def _upload_sync(
        self,
        bucket_name: str,
        object_name: str,
        content: bytes,
        content_type: str,
    ) -> str:
        """Synchronous helper for uploading object bytes."""
        client = self._get_client()
        data_stream = io.BytesIO(content)
        data_len = len(content)

        client.put_object(
            bucket_name=bucket_name,
            object_name=object_name,
            data=data_stream,
            length=data_len,
            content_type=content_type,
        )
        return f"{bucket_name}/{object_name}"

    async def upload(
        self,
        data_source_id: UUID,
        filename: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """
        Upload object to MinIO under key {data_source_id}/{filename}.

        Args:
            data_source_id: Data source UUID.
            filename:       Original filename.
            content:        Raw file bytes.
            content_type:   MIME type.

        Returns:
            The storage object key path in bucket (e.g. "rag-documents/uuid/file.pdf").
        """
        target_bucket = settings.MINIO_BUCKET
        await self.ensure_bucket(target_bucket)

        object_name = f"{data_source_id}/{filename}"
        logger.info(
            "Uploading to MinIO bucket '%s': %s (%d bytes)",
            target_bucket, object_name, len(content),
        )

        storage_path = await asyncio.to_thread(
            self._upload_sync,
            target_bucket,
            object_name,
            content,
            content_type,
        )

        logger.info("MinIO upload complete: %s", storage_path)
        return storage_path

    def _get_object_sync(self, bucket_name: str, object_name: str) -> bytes:
        """Synchronous helper for downloading object bytes."""
        client = self._get_client()
        response = None
        try:
            response = client.get_object(bucket_name, object_name)
            return response.read()
        finally:
            if response:
                response.close()
                response.release_conn()

    async def get_file(self, object_name: str) -> bytes:
        """
        Download object bytes from MinIO bucket.

        Args:
            object_name: Key of the object in the bucket (e.g. "uuid/file.pdf").

        Returns:
            The raw file bytes.
        """
        target_bucket = settings.MINIO_BUCKET
        await self.ensure_bucket(target_bucket)
        
        logger.info(
            "Downloading from MinIO bucket '%s': %s",
            target_bucket, object_name,
        )
        
        content = await asyncio.to_thread(
            self._get_object_sync,
            target_bucket,
            object_name,
        )
        return content

    def _delete_data_source_objects_sync(self, bucket_name: str, prefix: str) -> int:
        """Synchronous helper to list and remove all objects matching prefix."""
        client = self._get_client()
        count = 0
        try:
            if not client.bucket_exists(bucket_name):
                return 0
            objects = client.list_objects(bucket_name, prefix=prefix, recursive=True)
            for obj in objects:
                logger.info("Removing MinIO object '%s' from bucket '%s'", obj.object_name, bucket_name)
                client.remove_object(bucket_name, obj.object_name)
                count += 1
        except S3Error as exc:
            logger.error("MinIO S3Error during object deletion for prefix '%s': %s", prefix, exc)
            raise
        return count

    async def delete_data_source_objects(self, data_source_id: UUID) -> int:
        """
        Asynchronously delete all MinIO stored files associated with data_source_id.

        Args:
            data_source_id: Data source UUID.

        Returns:
            Number of deleted MinIO objects.
        """
        target_bucket = settings.MINIO_BUCKET
        prefix = f"{data_source_id}/"
        logger.info("Deleting all MinIO objects under bucket '%s' prefix '%s'", target_bucket, prefix)
        return await asyncio.to_thread(self._delete_data_source_objects_sync, target_bucket, prefix)


# Module-level singleton instance
minio_client = MinioStorageClient()

