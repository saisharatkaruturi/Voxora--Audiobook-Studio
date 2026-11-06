"""Upload handling and the `analyze` job (extraction -> OCR -> cleaning -> structure)."""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from pathlib import Path
from typing import BinaryIO

from sqlalchemy.orm import Session

from app.audio.cover import generate_cover, normalize_cover
from app.core.config import get_settings
from app.core.errors import StudioError, ValidationFailed
from app.core.logging import get_logger
from app.core.security import safe_filename, slugify
from app.db.session import session_scope
from app.document_processing.detect import IMAGE_FORMATS, sniff
from app.document_processing.pipeline import AnalyzeOptions, analyze
from app.models import Book, BookFile, BookStatus, JobType, User
from app.providers.storage import get_storage
from app.services.books import book_prefix, persist_analysis, sort_key
from app.services.generation import tmp_dir
from app.workers import queue

log = get_logger(__name__)

ANALYZE_STAGES = [
    {"key": "upload", "label": "Book imported", "status": "done"},
    {"key": "extract", "label": "Text extracted", "status": "pending"},
    {"key": "ocr", "label": "Scanned pages read", "status": "pending"},
    {"key": "clean", "label": "Text cleaned", "status": "pending"},
    {"key": "structure", "label": "Chapters detected", "status": "pending"},
    {"key": "cover", "label": "Cover prepared", "status": "pending"},
]


def create_book_from_upload(db: Session, user: User, stream: BinaryIO, filename: str) -> Book:
    settings = get_settings()
    name = safe_filename(filename, default="upload")
    fd, tmp_name = tempfile.mkstemp(dir=tmp_dir(), prefix="upload-")
    os.close(fd)  # Windows can't delete a file while a handle is open
    tmp = Path(tmp_name)
    try:
        size = 0
        sha = hashlib.sha256()
        with open(tmp, "wb") as out:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_file_size_bytes:
                    raise ValidationFailed(
                        f"This file is larger than the {settings.max_file_size_mb} MB upload limit.", code="file_too_large"
                    )
                sha.update(chunk)
                out.write(chunk)
        fmt, mime = sniff(tmp, name)
        stem = " ".join(Path(name).stem.replace("_", " ").replace("-", " ").split()) or "Untitled Book"
        book = Book(owner_id=user.id, title=stem.title()[:500], source_format=fmt, status=BookStatus.UPLOADED, sort_title=sort_key(stem))
        db.add(book)
        db.flush()
        ext = {"jpg": "jpg", "tiff": "tif"}.get(fmt, fmt)
        # Storage names are slugs ("the-chase-elle-kennedy.pdf"); the real file name is kept in BookFile.filename.
        key = f"{book_prefix(book.id)}/original/{slugify(Path(name).stem, 80) or 'book'}.{ext}"
        get_storage().save_file(key, tmp)
        db.add(BookFile(book_id=book.id, kind="original", storage_key=key, filename=name, mime_type=mime, size_bytes=size, sha256=sha.hexdigest()))
        db.commit()
        log.info("book.uploaded", book_id=book.id, format=fmt, size=size)
        return book
    finally:
        tmp.unlink(missing_ok=True)


def enqueue_analysis(db: Session, book: Book, user_id: str, options: dict | None = None):
    book.status = BookStatus.ANALYZING
    book.error = None
    db.commit()
    stages = [dict(s) for s in ANALYZE_STAGES]
    if book.source_format in IMAGE_FORMATS:
        stages[1]["status"] = "skipped"
    return queue.enqueue(
        db, type=JobType.ANALYZE, user_id=user_id, book_id=book.id, payload=options or {}, stages=stages,
        priority=10, exclusive_types={JobType.ANALYZE, JobType.GENERATE_BOOK},
    )


def run_analysis(ctx) -> dict:
    storage = get_storage()
    settings = get_settings()
    with session_scope() as db:
        book = db.get(Book, ctx.book_id)
        original = next((f for f in book.files if f.kind == "original"), None)
        if original is None:
            raise StudioError("The original file was deleted, so this book can't be re-analyzed.", code="original_missing", retryable=False)
        fmt, filename, key = book.source_format, original.filename, original.storage_key
    options = AnalyzeOptions(
        ocr_mode=ctx.payload.get("ocr_mode", "auto"),
        languages=[l for l in ctx.payload.get("languages", []) if l and l != "auto"],
        ocr_provider=ctx.payload.get("ocr_provider"),
        ocr_dpi=settings.ocr_dpi,
        max_pages=settings.max_pages,
    )
    ocr_started: dict = {}
    extract_start = time.monotonic()
    marks: dict[str, float] = {"extract": extract_start}

    def progress(message: str, fraction: float | None) -> None:
        if "OCR" in message:
            if not ocr_started:
                ocr_started["t"] = time.monotonic()
                marks.setdefault("ocr", ocr_started["t"])
                ctx.set_stage("extract", "done")
                ctx.set_stage("ocr", "active")
            ocr_started["n"] = ocr_started.get("n", 0) + 1
        elif message.startswith("Cleaning"):
            marks.setdefault("clean", time.monotonic())
            ctx.set_stage("extract", "done")
            ctx.set_stage("ocr", "done" if ocr_started else "skipped")
            ctx.set_stage("clean", "active")
        elif message.startswith("Detecting chapters"):
            marks.setdefault("structure", time.monotonic())
            ctx.set_stage("clean", "done")
            ctx.set_stage("structure", "active")
        fields = {"message": message, "stage": "analyzing"}
        if fraction is not None:
            fields["progress"] = round(fraction * 90, 1)
            # ETA only once OCR speed has been measured over several pages.
            if ocr_started.get("n", 0) >= 3 and fraction > 0.35:
                elapsed = time.monotonic() - ocr_started["t"]
                done = (fraction - 0.3) / 0.6
                fields["result"] = {"eta_seconds": int(elapsed / max(done, 1e-3) * (1 - done))}
        ctx.update(**fields)
        ctx.check()

    ctx.set_stage("extract", "active")
    ctx.update(stage="analyzing", message="Analyzing document", progress=1.0)
    result = analyze(storage.local_path(key), fmt, filename, options, progress)
    ctx.set_stage("structure", "done")
    ctx.set_stage("cover", "active")
    marks["save"] = time.monotonic()

    with session_scope() as db:
        book = db.get(Book, ctx.book_id)
        persist_analysis(db, book, result)
        # Raw extracted text (before editing) for download.
        raw = "\n\n".join(b.text for b in result.document.all_blocks())
        text_key = f"{book_prefix(book.id)}/text/extracted.txt"
        size = storage.save_bytes(text_key, raw.encode("utf-8"))
        for f in [f for f in book.files if f.kind == "extracted_text"]:
            db.delete(f)
        db.add(BookFile(book_id=book.id, kind="extracted_text", storage_key=text_key, filename="extracted.txt", mime_type="text/plain", size_bytes=size))
        # Cover: extracted > existing uploaded > generated.
        if book.cover_source != "uploaded":
            cover_bytes, source = None, None
            if result.document.cover_image:
                try:
                    cover_bytes, source = normalize_cover(result.document.cover_image), "extracted"
                except Exception:
                    log.warning("cover.extracted_invalid", book_id=book.id)
            if cover_bytes is None:
                cover_bytes, source = generate_cover(book.title, book.author), "generated"
            book.cover_key = f"{book_prefix(book.id)}/cover.jpg"
            storage.save_bytes(book.cover_key, cover_bytes)
            book.cover_source = source
        if not book.narration:
            from app.services.user_settings import default_narration_for

            book.narration = default_narration_for(db, book.owner_id, book.language)
        book.status = BookStatus.REVIEW
        chapters = len(result.structure.chapters)
        summary = {
            "chapters": chapters,
            "method": result.structure.method,
            "words": book.word_count,
            "languages": book.languages,
            "ocr_used": book.ocr_used,
            "seconds": round(time.monotonic() - extract_start, 1),
            "telemetry": _stage_telemetry(marks, time.monotonic(), pages=book.page_count, words=book.word_count),
            "sections": {
                "narrated": sum(1 for c in book.chapters if c.include_in_audio),
                "chapters": sum(1 for c in book.chapters if c.kind == "chapter"),
                "optional": sum(1 for c in book.chapters if not c.include_in_audio),
            },
        }
    ctx.set_stage("cover", "done")
    ctx.update(progress=100.0, message=f"Found {chapters} chapters", result=summary)
    log.info("analysis.telemetry", book_id=ctx.book_id, **summary["telemetry"])
    _detect_characters(ctx)
    try:
        with session_scope() as db:
            queue.enqueue(db, type="classify", user_id=ctx.user_id, book_id=ctx.book_id, payload={"book_ids": [ctx.book_id]}, priority=-4, exclusive_types={"classify"})
    except Exception:
        log.warning("classify.auto_enqueue_failed", book_id=ctx.book_id)
    return summary


def _stage_telemetry(marks: dict[str, float], end: float, *, pages: int | None, words: int) -> dict:
    """Seconds spent per analysis stage, from the first time each stage was reported."""
    order = [k for k in ("extract", "ocr", "clean", "structure", "save") if k in marks]
    out: dict = {}
    for i, k in enumerate(order):
        nxt = marks[order[i + 1]] if i + 1 < len(order) else end
        out[f"{k}_seconds"] = round(max(0.0, nxt - marks[k]), 2)
    total = end - marks["extract"]
    out.update(total_seconds=round(total, 2), pages=pages, words=words, pages_per_minute=round((pages or 0) / total * 60, 1) if total > 0 else None)
    return out


def _detect_characters(ctx) -> None:
    """Queue a fast, heuristic (no LLM) dialogue/character pass so Voice Studio and
    AI Cast know the characters. Skipped quietly if one is already running."""
    from app.core.errors import ConflictError

    try:
        with session_scope() as db:
            queue.enqueue(db, type=JobType.CAST_ANALYSIS, user_id=ctx.user_id, book_id=ctx.book_id, payload={"use_llm": False}, priority=-5, exclusive_types={JobType.CAST_ANALYSIS, JobType.GENERATE_BOOK})
    except ConflictError:
        pass
    except Exception:
        log.warning("cast.auto_enqueue_failed", book_id=ctx.book_id)


def set_cover(db: Session, book: Book, data: bytes) -> None:
    try:
        cover = normalize_cover(data)
    except Exception as exc:
        raise ValidationFailed("That image couldn't be read. Upload a JPG or PNG.", code="invalid_image") from exc
    book.cover_key = f"{book_prefix(book.id)}/cover.jpg"
    get_storage().save_bytes(book.cover_key, cover)
    book.cover_source = "uploaded"


def regenerate_cover(db: Session, book: Book) -> None:
    book.cover_key = f"{book_prefix(book.id)}/cover.jpg"
    get_storage().save_bytes(book.cover_key, generate_cover(book.title, book.author))
    book.cover_source = "generated"
