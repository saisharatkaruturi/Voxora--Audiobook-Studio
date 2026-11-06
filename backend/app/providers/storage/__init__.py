from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.providers.storage.base import StorageProvider


@lru_cache
def get_storage() -> StorageProvider:
    settings = get_settings()
    if settings.storage_provider == "s3":
        from app.providers.storage.s3 import S3Storage

        if not settings.s3_bucket:
            raise RuntimeError("STORAGE_PROVIDER=s3 requires S3_BUCKET")
        return S3Storage(
            settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url,
            region=settings.s3_region,
            access_key=settings.s3_access_key_id,
            secret_key=settings.s3_secret_access_key,
            cache_dir=settings.storage_path / "_s3cache",
        )
    from app.providers.storage.local import LocalStorage

    return LocalStorage(settings.storage_path, min_free_bytes=settings.min_free_disk_mb * 1024 * 1024)


__all__ = ["StorageProvider", "get_storage"]
