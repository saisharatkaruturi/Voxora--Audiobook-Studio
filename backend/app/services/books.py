"""Book and chapter persistence and editing."""

from __future__ import annotations

import hashlib
import re
from collections import Counter

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, PermissionDeniedError, ValidationFailed
from app.core.logging import get_logger
from app.core.security import slugify
from app.document_processing.cleaning import split_plain_paragraphs
from app.document_processing.language import detect_language, summarize_languages
from app.document_processing.pipeline import AnalysisResult
from app.document_processing.segmentation import word_count
from app.models import AudioAsset, Book, BookFile, Chapter, ChapterStatus, Paragraph, User
from app.providers.storage import get_storage

log = get_logger(__name__)


# --------------------------------------------------------------------------- access


def get_book_for(db: Session, book_id: str, user: User) -> Book:
    book = db.get(Book, book_id)
    if book is None:
        raise NotFoundError("Book not found.")
    if book.owner_id != user.id and not user.is_admin:
        raise PermissionDeniedError("You don't have access to this book.")
    return book


def get_chapter_for(db: Session, chapter_id: str, user: User) -> Chapter:
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise NotFoundError("Chapter not found.")
    get_book_for(db, chapter.book_id, user)
    return chapter


def book_prefix(book_id: str) -> str:
    return f"books/{book_id}"


# --------------------------------------------------------------------------- analysis results


def persist_analysis(db: Session, book: Book, result: AnalysisResult) -> None:
    """Replace the book's chapters with a fresh analysis."""
    structure = result.structure
    doc = result.document
    db.execute(delete(Chapter).where(Chapter.book_id == book.id))
    db.flush()

    if not book.metadata_locked:
        book.title = structure.title[:500]
        book.subtitle = structure.subtitle
        book.author = structure.author or book.author
    book.description = book.description or doc.metadata.description
    book.year = book.year or doc.metadata.year
    book.genre = book.genre or doc.metadata.genre
    book.language = result.primary_language or book.language or "en"
    book.languages = result.languages
    book.page_count = doc.page_count
    book.sort_title = sort_key(book.title)
    if doc.ocr:
        book.ocr_used = doc.ocr.pages_ocrd > 0
        book.ocr_engine = doc.ocr.engine
        book.ocr_confidence = doc.ocr.mean_confidence
    warnings = list(dict.fromkeys(doc.warnings + structure.warnings))
    if doc.ocr and doc.ocr.low_confidence_pages:
        pages = doc.ocr.low_confidence_pages
        shown = ", ".join(map(str, pages[:10])) + ("..." if len(pages) > 10 else "")
        warnings.append(f"OCR quality is low on {len(pages)} page(s) ({shown}). Review those chapters in the editor.")
    book.warnings = warnings

    total_words = total_chars = 0
    for position, detected in enumerate(structure.chapters):
        chapter = Chapter(
            book_id=book.id,
            position=position,
            title=detected.title[:500] or f"Section {position + 1}",
            kind=detected.kind,
            include_in_audio=detected.include_in_audio,
            detection=detected.detection,
            source_pages=sorted({b.page for b in detected.blocks if b.page})[:2000],
        )
        db.add(chapter)
        db.flush()
        langs: Counter[str] = Counter()
        words = chars = 0
        for i, block in enumerate(detected.blocks):
            lang = block.meta.get("language") or book.language
            db.add(
                Paragraph(
                    chapter_id=chapter.id,
                    position=i,
                    text=block.text,
                    kind="heading" if block.is_heading else "text",
                    language=lang,
                    page=block.page,
                )
            )
            langs[lang] += len(block.text)
            words += word_count(block.text)
            chars += len(block.text)
        chapter.word_count, chapter.char_count = words, chars
        chapter.language = langs.most_common(1)[0][0] if langs else book.language
        total_words += words
        total_chars += chars
    book.word_count, book.char_count = total_words, total_chars
    db.flush()


def sort_key(title: str) -> str:
    return re.sub(r"^(the|a|an)\s+", "", (title or "").strip().lower())


# --------------------------------------------------------------------------- chapter text


def chapter_paragraphs(db: Session, chapter_id: str) -> list[Paragraph]:
    return list(db.scalars(select(Paragraph).where(Paragraph.chapter_id == chapter_id).order_by(Paragraph.position)))


def chapter_text(db: Session, chapter: Chapter) -> str:
    return "\n\n".join(p.text for p in chapter_paragraphs(db, chapter.id))


def _recount(chapter: Chapter, paragraphs: list[Paragraph], default_lang: str | None) -> None:
    chapter.word_count = sum(word_count(p.text) for p in paragraphs)
    chapter.char_count = sum(len(p.text) for p in paragraphs)
    langs: Counter[str] = Counter()
    for p in paragraphs:
        langs[p.language or default_lang or "en"] += len(p.text)
    chapter.language = langs.most_common(1)[0][0] if langs else default_lang


def set_chapter_text(db: Session, chapter: Chapter, text: str) -> None:
    """Replace a chapter's text from the editor. Blank lines separate paragraphs;
    a first paragraph equal to the chapter title stays a heading."""
    book = db.get(Book, chapter.book_id)
    old = chapter_paragraphs(db, chapter.id)
    old_headings = {p.text.strip() for p in old if p.kind == "heading"}
    old_by_text = {p.text: p for p in old}
    paragraphs_text = [p.strip() for p in split_plain_paragraphs(text) if p.strip()]
    if len(text) > 5_000_000:
        raise ValidationFailed("Chapter text is too long (5 MB limit per chapter). Split the chapter first.")
    db.execute(delete(Paragraph).where(Paragraph.chapter_id == chapter.id))
    db.flush()
    new: list[Paragraph] = []
    last_lang = book.language if book else None
    for i, t in enumerate(paragraphs_text):
        prev = old_by_text.get(t)
        kind = "heading" if (t in old_headings or (i == 0 and t.strip() == chapter.title.strip())) else "text"
        lang = prev.language if prev else detect_language(t, default=last_lang)
        last_lang = lang or last_lang
        p = Paragraph(chapter_id=chapter.id, position=i, text=t, kind=kind, language=lang, page=prev.page if prev else None, spans=prev.spans if prev else None)
        db.add(p)
        new.append(p)
    chapter.text_version += 1
    _recount(chapter, new, book.language if book else None)
    _refresh_book_counts(db, chapter.book_id)


def _refresh_book_counts(db: Session, book_id: str) -> None:
    book = db.get(Book, book_id)
    if book is None:
        return
    db.flush()
    words, chars = db.execute(
        select(func.coalesce(func.sum(Chapter.word_count), 0), func.coalesce(func.sum(Chapter.char_count), 0)).where(Chapter.book_id == book_id)
    ).one()
    book.word_count, book.char_count = int(words), int(chars)
    langs = Counter(dict(db.execute(select(Paragraph.language, func.sum(func.length(Paragraph.text))).join(Chapter).where(Chapter.book_id == book_id).group_by(Paragraph.language)).all()))
    book.languages = summarize_languages(Counter({k: int(v) for k, v in langs.items() if k}))


def reorder_chapters(db: Session, book: Book, ordered_ids: list[str]) -> None:
    chapters = {c.id: c for c in db.scalars(select(Chapter).where(Chapter.book_id == book.id))}
    if set(ordered_ids) != set(chapters):
        raise ValidationFailed("The new order must list every chapter of the book exactly once.")
    # Two passes to avoid transient duplicate positions.
    for i, cid in enumerate(ordered_ids):
        chapters[cid].position = 100000 + i
    db.flush()
    for i, cid in enumerate(ordered_ids):
        chapters[cid].position = i


def delete_chapter(db: Session, chapter: Chapter) -> None:
    book_id = chapter.book_id
    _delete_chapter_audio(db, chapter)
    db.delete(chapter)
    db.flush()
    _renumber(db, book_id)
    _refresh_book_counts(db, book_id)


def _renumber(db: Session, book_id: str) -> None:
    chapters = list(db.scalars(select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.position)))
    for i, c in enumerate(chapters):
        c.position = 100000 + i
    db.flush()
    for i, c in enumerate(chapters):
        c.position = i


def merge_chapters(db: Session, book: Book, chapter_ids: list[str]) -> Chapter:
    chapters = sorted(
        (c for c in db.scalars(select(Chapter).where(Chapter.book_id == book.id, Chapter.id.in_(chapter_ids)))), key=lambda c: c.position
    )
    if len(chapters) < 2 or len(chapters) != len(set(chapter_ids)):
        raise ValidationFailed("Select at least two chapters of this book to merge.")
    target = chapters[0]
    next_pos = len(chapter_paragraphs(db, target.id))
    for other in chapters[1:]:
        for p in chapter_paragraphs(db, other.id):
            p.chapter_id = target.id
            p.position = next_pos
            next_pos += 1
        db.flush()
        _delete_chapter_audio(db, other)
        db.delete(other)
    db.flush()
    target.text_version += 1
    target.source_pages = sorted({*target.source_pages, *[pg for c in chapters[1:] for pg in c.source_pages]})
    _recount(target, chapter_paragraphs(db, target.id), book.language)
    _renumber(db, book.id)
    return target


def split_chapter(db: Session, chapter: Chapter, paragraph_index: int, new_title: str | None) -> Chapter:
    paragraphs = chapter_paragraphs(db, chapter.id)
    if not 0 < paragraph_index < len(paragraphs):
        raise ValidationFailed("Choose a paragraph inside the chapter (not the first) to split at.")
    book = db.get(Book, chapter.book_id)
    # Make room after the current chapter.
    later = list(db.scalars(select(Chapter).where(Chapter.book_id == chapter.book_id, Chapter.position > chapter.position).order_by(Chapter.position.desc())))
    for c in later:
        c.position += 1
        db.flush()
    moved = paragraphs[paragraph_index:]
    title = (new_title or "").strip() or (moved[0].text[:80] if moved[0].kind == "heading" else f"{chapter.title} (continued)")
    new_chapter = Chapter(book_id=chapter.book_id, position=chapter.position + 1, title=title[:500], kind=chapter.kind, include_in_audio=chapter.include_in_audio, detection={"method": "manual", "confidence": 1.0})
    db.add(new_chapter)
    db.flush()
    for i, p in enumerate(moved):
        p.chapter_id = new_chapter.id
        p.position = i
    db.flush()
    chapter.text_version += 1
    _recount(chapter, paragraphs[:paragraph_index], book.language if book else None)
    _recount(new_chapter, moved, book.language if book else None)
    return new_chapter


def create_chapter(db: Session, book: Book, title: str, text: str, after_position: int | None) -> Chapter:
    position = (after_position + 1) if after_position is not None else len(book.chapters)
    for c in db.scalars(select(Chapter).where(Chapter.book_id == book.id, Chapter.position >= position).order_by(Chapter.position.desc())):
        c.position += 1
        db.flush()
    chapter = Chapter(book_id=book.id, position=position, title=title[:500], detection={"method": "manual", "confidence": 1.0})
    db.add(chapter)
    db.flush()
    set_chapter_text(db, chapter, text)
    return chapter


# --------------------------------------------------------------------------- audio cleanup


def _delete_chapter_audio(db: Session, chapter: Chapter) -> None:
    storage = get_storage()
    for asset in db.scalars(select(AudioAsset).where(AudioAsset.chapter_id == chapter.id, AudioAsset.kind == "chapter")):
        storage.delete(asset.storage_key)
        db.delete(asset)


def delete_book_audio(db: Session, book: Book) -> int:
    storage = get_storage()
    assets = list(db.scalars(select(AudioAsset).where(AudioAsset.book_id == book.id, AudioAsset.kind.in_(["chapter", "full"]))))
    for a in assets:
        storage.delete(a.storage_key)
        db.delete(a)
    for c in book.chapters:
        c.audio_status = ChapterStatus.PENDING
        c.audio_hash = None
        c.duration = None
        c.audio_progress = 0
        c.audio_error = None
    book.total_duration = None
    return len(assets)


def delete_original(db: Session, book: Book) -> bool:
    storage = get_storage()
    removed = False
    for f in list(book.files):
        if f.kind == "original":
            storage.delete(f.storage_key)
            db.delete(f)
            removed = True
    return removed


def delete_book(db: Session, book: Book) -> None:
    storage = get_storage()
    storage.delete_prefix(book_prefix(book.id))
    db.delete(book)


def content_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def new_storage_name(title: str, position: int, ext: str) -> str:
    return f"{position + 1:02d}-{slugify(title, 50)}.{ext}"


def get_file(book: Book, kind: str) -> BookFile | None:
    return next((f for f in book.files if f.kind == kind), None)
