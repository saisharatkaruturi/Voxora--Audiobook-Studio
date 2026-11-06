from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def validate_key(key: str) -> str:
    """Storage keys are internal, but validate anyway: no traversal, no absolute paths."""
    if not key or not _KEY_RE.match(key) or ".." in key.split("/") or key.startswith("/"):
        raise ValueError(f"Invalid storage key: {key!r}")
    return key


class StorageProvider(ABC):
    """Blob storage for originals, covers and audio. Keys look like `books/{id}/audio/01-intro.mp3`."""

    name: str = "base"

    @abstractmethod
    def save_file(self, key: str, source: Path) -> int:
        """Copy a local file into storage. Returns size in bytes."""

    @abstractmethod
    def save_bytes(self, key: str, data: bytes) -> int: ...

    @abstractmethod
    def save_stream(self, key: str, stream: BinaryIO, max_bytes: int | None = None) -> int: ...

    @abstractmethod
    def open(self, key: str) -> BinaryIO: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def size(self, key: str) -> int: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def delete_prefix(self, prefix: str) -> int: ...

    @abstractmethod
    def list_prefix(self, prefix: str) -> Iterator[str]: ...

    @abstractmethod
    def local_path(self, key: str) -> Path:
        """A local filesystem path for the object (downloaded to a temp cache for remote stores)."""

    def presigned_url(self, key: str, ttl_seconds: int) -> str | None:
        """Direct download URL, if the backend supports it. None means: stream via the API."""
        return None

    def read_bytes(self, key: str) -> bytes:
        with self.open(key) as fh:
            return fh.read()
