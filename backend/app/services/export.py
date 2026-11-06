"""Downloads: chapter audio, full audiobook, text exports and a ZIP package."""

from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.narration import normalize_for_speech
from app.core.security import slugify
from app.models import AudioAsset, Book, Paragraph
from app.providers.storage import get_storage
from app.services.books import book_prefix
from app.services.generation import tmp_dir


def processed_text(db: Session, book: Book, narration_ready: bool = False) -> str:
    parts = [book.title + (f"\nby {book.author}" if book.author else ""), ""]
    for c in book.chapters:
        paras = db.scalars(select(Paragraph).where(Paragraph.chapter_id == c.id).order_by(Paragraph.position))
        body = []
        for p in paras:
            body.append(normalize_for_speech(p.text, p.language or book.language) if narration_ready else p.text)
        marker = "" if c.include_in_audio else " [not narrated]"
        parts.append(f"\n\n=== {c.title}{marker} ===\n\n" + "\n\n".join(body))
    return "\n".join(parts).strip() + "\n"


def metadata(db: Session, book: Book) -> dict:
    chapters = []
    for c in book.chapters:
        asset = db.scalar(select(AudioAsset).where(AudioAsset.chapter_id == c.id, AudioAsset.kind == "chapter"))
        chapters.append(
            {
                "position": c.position + 1,
                "title": c.title,
                "kind": c.kind,
                "narrated": c.include_in_audio,
                "words": c.word_count,
                "duration_seconds": round(asset.duration, 2) if asset else None,
                "file": Path(asset.storage_key).name if asset else None,
            }
        )
    return {
        "title": book.title,
        "subtitle": book.subtitle,
        "author": book.author,
        "narrator": book.narrator,
        "language": book.language,
        "languages": book.languages,
        "genre": book.genre,
        "year": book.year,
        "total_duration_seconds": book.total_duration,
        "chapters": chapters,
        "generated_by": "VOXORA",
    }


def build_zip(db: Session, book: Book) -> Path:
    """Package metadata, cover, chapter audio, full audiobook and text into a ZIP (temp file)."""
    storage = get_storage()
    root = slugify(book.title, 60)
    fd, name = tempfile.mkstemp(dir=tmp_dir(), prefix="export-", suffix=".zip")
    import os

    os.close(fd)
    path = Path(name)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr(f"{root}/metadata.json", json.dumps(metadata(db, book), indent=2, ensure_ascii=False))
        zf.writestr(f"{root}/text/book.txt", processed_text(db, book).encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
        if book.cover_key and storage.exists(book.cover_key):
            zf.write(storage.local_path(book.cover_key), f"{root}/cover.jpg")
        for asset in db.scalars(select(AudioAsset).where(AudioAsset.book_id == book.id, AudioAsset.kind.in_(["chapter", "full"]))):
            if storage.exists(asset.storage_key):
                folder = "chapters" if asset.kind == "chapter" else ""
                arc = f"{root}/{folder}/{Path(asset.storage_key).name}".replace("//", "/")
                zf.write(storage.local_path(asset.storage_key), arc)
    return path


def text_export_key(book: Book, kind: str) -> str:
    return f"{book_prefix(book.id)}/text/{kind}.txt"
