from __future__ import annotations

import os
import time
import uuid
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from app.core.errors import InsufficientStorageError, ValidationFailed
from app.providers.storage.base import StorageProvider, validate_key


class LocalStorage(StorageProvider):
    name = "local"

    def __init__(self, root: Path, min_free_bytes: int = 0):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.min_free_bytes = min_free_bytes

    def _path(self, key: str) -> Path:
        validate_key(key)
        # Pure path normalisation, no filesystem query: resolve() on a file another
        # thread is replacing can transiently return a different path form on Windows.
        path = Path(os.path.normpath(self.root / key))
        if self.root != path and self.root not in path.parents:
            raise ValueError("Storage key escapes storage root")
        return path

    def _ensure_space(self, needed: int = 0) -> None:
        free = shutil.disk_usage(self.root).free
        if free - needed < self.min_free_bytes:
            raise InsufficientStorageError(
                f"Not enough disk space: {free // (1024 * 1024)} MB free. Free up space or delete old audiobooks and try again."
            )

    def save_file(self, key: str, source: Path) -> int:
        size = source.stat().st_size
        self._ensure_space(size)
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = _tmp_for(dest)
        shutil.copyfile(source, tmp)
        _publish(tmp, dest)
        return size

    def save_bytes(self, key: str, data: bytes) -> int:
        self._ensure_space(len(data))
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = _tmp_for(dest)
        tmp.write_bytes(data)
        _publish(tmp, dest)
        return len(data)

    def save_stream(self, key: str, stream: BinaryIO, max_bytes: int | None = None) -> int:
        self._ensure_space()
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = _tmp_for(dest)
        written = 0
        try:
            with open(tmp, "wb") as out:
                while chunk := stream.read(1024 * 1024):
                    written += len(chunk)
                    if max_bytes is not None and written > max_bytes:
                        raise ValidationFailed(
                            f"File is larger than the {max_bytes // (1024 * 1024)} MB limit.", code="file_too_large"
                        )
                    out.write(chunk)
            _publish(tmp, dest)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return written

    def open(self, key: str) -> BinaryIO:
        return open(self._path(key), "rb")

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def size(self, key: str) -> int:
        return self._path(key).stat().st_size

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> int:
        path = self._path(prefix.rstrip("/"))
        if not path.exists():
            return 0
        if path.is_file():
            path.unlink()
            return 1
        count = sum(1 for p in path.rglob("*") if p.is_file())
        shutil.rmtree(path, ignore_errors=True)
        return count

    def list_prefix(self, prefix: str) -> Iterator[str]:
        path = self._path(prefix.rstrip("/"))
        if not path.exists():
            return
        for p in path.rglob("*"):
            if p.is_file():
                yield p.relative_to(self.root).as_posix()

    def local_path(self, key: str) -> Path:
        return self._path(key)


def _tmp_for(dest: Path) -> Path:
    """A private temp name: concurrent writers of the same key (e.g. two chapters
    caching an identical line) must never share a temp file."""
    return dest.with_name(f"{dest.name}.{uuid.uuid4().hex[:12]}.part")


def _publish(tmp: Path, dest: Path) -> None:
    """Atomically move tmp into place. On Windows a reader holding dest open blocks
    the replace briefly; retry, and if another writer already published it, keep theirs."""
    for attempt in range(5):
        try:
            os.replace(tmp, dest)
            return
        except PermissionError:
            if attempt == 4:
                if dest.exists():
                    tmp.unlink(missing_ok=True)
                    return
                raise
            time.sleep(0.1 * (attempt + 1))
