"""S3-compatible storage (AWS S3, Cloudflare R2, MinIO, Backblaze B2...).

Requires `boto3` (optional dependency). When a filesystem path is needed (e.g.
for ffmpeg) the object is downloaded into a scratch cache that housekeeping
empties after TEMP_FILE_TTL_HOURS, so nothing accumulates on the machine.

Supabase Storage: S3_ENDPOINT_URL=https://<ref>.storage.supabase.co/storage/v1/s3
"""

from __future__ import annotations

import io
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from app.core.errors import ProviderUnavailableError, ValidationFailed
from app.providers.storage.base import StorageProvider, validate_key


class S3Storage(StorageProvider):
    name = "s3"

    def __init__(self, bucket: str, *, endpoint_url=None, region=None, access_key=None, secret_key=None, cache_dir: Path):
        try:
            import boto3  # type: ignore
            from botocore.config import Config  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional
            raise ProviderUnavailableError("s3", "STORAGE_PROVIDER=s3 requires the 'boto3' package (pip install boto3).") from exc
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            # Path-style URLs (endpoint/bucket/key): what Supabase Storage, MinIO and R2 expect.
            config=Config(signature_version="s3v4", s3={"addressing_style": "path" if endpoint_url else "auto"}),
        )
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def save_file(self, key: str, source: Path) -> int:
        self.client.upload_file(str(source), self.bucket, validate_key(key))
        return source.stat().st_size

    def save_bytes(self, key: str, data: bytes) -> int:
        self.client.put_object(Bucket=self.bucket, Key=validate_key(key), Body=data)
        return len(data)

    def save_stream(self, key: str, stream: BinaryIO, max_bytes: int | None = None) -> int:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            written = 0
            while chunk := stream.read(1024 * 1024):
                written += len(chunk)
                if max_bytes is not None and written > max_bytes:
                    Path(tmp.name).unlink(missing_ok=True)
                    raise ValidationFailed("File is too large.", code="file_too_large")
                tmp.write(chunk)
        try:
            self.save_file(key, Path(tmp.name))
        finally:
            Path(tmp.name).unlink(missing_ok=True)
        return written

    def open(self, key: str) -> BinaryIO:
        obj = self.client.get_object(Bucket=self.bucket, Key=validate_key(key))
        return io.BytesIO(obj["Body"].read())

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=validate_key(key))
            return True
        except Exception:
            return False

    def size(self, key: str) -> int:
        return int(self.client.head_object(Bucket=self.bucket, Key=validate_key(key))["ContentLength"])

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=validate_key(key))
        (self.cache_dir / key).unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> int:
        keys = list(self.list_prefix(prefix))
        for i in range(0, len(keys), 1000):
            self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": [{"Key": k} for k in keys[i : i + 1000]]})
        return len(keys)

    def list_prefix(self, prefix: str) -> Iterator[str]:
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=validate_key(prefix.rstrip("/")) + "/"):
            for item in page.get("Contents", []):
                yield item["Key"]

    def local_path(self, key: str) -> Path:
        dest = (self.cache_dir / validate_key(key)).resolve()
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            self.client.download_file(self.bucket, key, str(dest))
        return dest

    def presigned_url(self, key: str, ttl_seconds: int) -> str | None:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": validate_key(key)}, ExpiresIn=ttl_seconds
        )
