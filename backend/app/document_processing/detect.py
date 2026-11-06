"""Identify uploaded files by content (magic bytes), never by name alone."""

from __future__ import annotations

import zipfile
from pathlib import Path

from app.core.errors import UnsupportedFileError

SUPPORTED = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "epub": "application/epub+zip",
    "txt": "text/plain",
    "png": "image/png",
    "jpg": "image/jpeg",
    "webp": "image/webp",
    "tiff": "image/tiff",
}
IMAGE_FORMATS = {"png", "jpg", "webp", "tiff"}
EXTENSIONS = {
    ".pdf": "pdf", ".docx": "docx", ".epub": "epub", ".txt": "txt", ".text": "txt", ".md": "txt",
    ".png": "png", ".jpg": "jpg", ".jpeg": "jpg", ".webp": "webp", ".tif": "tiff", ".tiff": "tiff",
}
_EXECUTABLE_MAGIC = (b"MZ", b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"#!")


def sniff(path: Path, filename: str) -> tuple[str, str]:
    """Return (format, mime). Raises UnsupportedFileError for anything else."""
    with open(path, "rb") as fh:
        head = fh.read(4096)
    if not head:
        raise UnsupportedFileError("The uploaded file is empty.", code="empty_file")
    if head.startswith(_EXECUTABLE_MAGIC):
        raise UnsupportedFileError("Executable files are not accepted.", code="executable_rejected")

    fmt: str | None = None
    if head.startswith(b"%PDF-") or b"%PDF-" in head[:1024]:
        fmt = "pdf"
    elif head.startswith(b"PK\x03\x04"):
        fmt = _sniff_zip(path)
    elif head.startswith(b"\x89PNG\r\n\x1a\n"):
        fmt = "png"
    elif head.startswith(b"\xff\xd8\xff"):
        fmt = "jpg"
    elif head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        fmt = "webp"
    elif head[:4] in (b"II*\x00", b"MM\x00*"):
        fmt = "tiff"
    elif _looks_like_text(head):
        fmt = "txt"

    ext_fmt = EXTENSIONS.get(Path(filename).suffix.lower())
    if fmt is None:
        hint = f" ({Path(filename).suffix})" if Path(filename).suffix else ""
        raise UnsupportedFileError(
            f"Unsupported file type{hint}. Upload a PDF, EPUB, DOCX, TXT, or a page image (JPG/PNG).", code="unsupported_type"
        )
    if fmt == "txt" and ext_fmt not in (None, "txt"):
        raise UnsupportedFileError(
            f"This file is named {Path(filename).suffix} but its content isn't a valid {Path(filename).suffix.lstrip('.').upper()} file.",
            code="type_mismatch",
        )
    return fmt, SUPPORTED[fmt]


def _sniff_zip(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if "mimetype" in names and zf.read("mimetype").strip() == b"application/epub+zip":
                return "epub"
            if "word/document.xml" in names:
                return "docx"
            if any(n.endswith(".opf") for n in names) and "META-INF/container.xml" in names:
                return "epub"
    except zipfile.BadZipFile:
        return None
    return None


def _looks_like_text(head: bytes) -> bool:
    if head.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        return True
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError as exc:
        if exc.start > len(head) - 4:  # multi-byte char cut at the buffer end
            return True
    control = sum(1 for b in head if b < 9 or 13 < b < 32)
    return control / len(head) < 0.01
