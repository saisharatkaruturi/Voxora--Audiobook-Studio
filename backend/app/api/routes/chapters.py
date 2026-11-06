from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.errors import ValidationFailed
from app.db.session import get_db
from app.models import AudioAsset, Book, Chapter, ChapterStatus, JobType, Paragraph, User
from app.schemas.common import (
    ChapterCreateIn,
    ContentModeIn,
    ChapterUpdateIn,
    MergeIn,
    ReorderIn,
    SplitIn,
    media_url,
    serialize_chapter,
    serialize_job,
)
from app.document_processing.content_modes import included
from app.services import books as book_service
from app.services import narration_settings
from app.services.books import chapter_paragraphs, get_book_for, get_chapter_for
from app.services.generation import chapter_audio_hash, load_cast, plan_chapter
from app.workers import queue

router = APIRouter(prefix="/api", tags=["chapters"])


def _audio_info(db: Session, chapter: Chapter) -> dict | None:
    asset = db.scalar(select(AudioAsset).where(AudioAsset.chapter_id == chapter.id, AudioAsset.kind == "chapter"))
    if asset is None:
        return None
    return {"url": media_url(asset.storage_key), "duration": asset.duration, "format": asset.format, "size": asset.size_bytes, "timing_source": asset.timing_source}


def _stale_map(db: Session, book: Book) -> dict[str, bool]:
    settings = narration_settings.resolve(book.narration, book.language)
    cast = load_cast(db, book.id) if settings.get("cast_mode") else None
    out = {}
    for c in book.chapters:
        if c.audio_status == ChapterStatus.DONE and c.audio_hash:
            out[c.id] = chapter_audio_hash(chapter_paragraphs(db, c.id), settings, c.title, cast) != c.audio_hash
        else:
            out[c.id] = False
    return out


def list_payload(db: Session, book: Book) -> list[dict]:
    stale = _stale_map(db, book)
    return [serialize_chapter(c, stale=stale.get(c.id, False), audio=_audio_info(db, c)) for c in book.chapters]


@router.get("/books/{book_id}/chapters")
def list_chapters(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    book = get_book_for(db, book_id, user)
    return {"items": list_payload(db, book)}


@router.post("/books/{book_id}/chapters", status_code=201)
def create_chapter(book_id: str, body: ChapterCreateIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    book = get_book_for(db, book_id, user)
    chapter = book_service.create_chapter(db, book, body.title, body.text, body.after_position)
    db.commit()
    return serialize_chapter(chapter)


@router.post("/books/{book_id}/content-mode")
def set_content_mode(book_id: str, body: ContentModeIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Narrative Only / Full Book / Custom: switch which sections are narrated in one step."""
    book = get_book_for(db, book_id, user)
    for c in book.chapters:
        c.include_in_audio = included(c.kind, body.mode, c.detection, c.include_in_audio)
    book.narration = {**(book.narration or {}), "content_mode": body.mode}
    db.commit()
    db.refresh(book)
    return {"mode": body.mode, "items": list_payload(db, book)}


@router.get("/chapters/{chapter_id}")
def get_chapter(chapter_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    chapter = get_chapter_for(db, chapter_id, user)
    book = db.get(Book, chapter.book_id)
    data = serialize_chapter(chapter, stale=_stale_map(db, book).get(chapter.id, False), audio=_audio_info(db, chapter))
    data["paragraphs"] = [
        {"id": p.id, "position": p.position, "text": p.text, "kind": p.kind, "language": p.language, "page": p.page, "spans": p.spans}
        for p in chapter_paragraphs(db, chapter.id)
    ]
    return data


@router.patch("/chapters/{chapter_id}")
def update_chapter(chapter_id: str, body: ChapterUpdateIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    chapter = get_chapter_for(db, chapter_id, user)
    if body.title is not None:
        chapter.title = body.title.strip()
    if body.kind is not None:
        chapter.kind = body.kind
    if body.include_in_audio is not None:
        chapter.include_in_audio = body.include_in_audio
        book = db.get(Book, chapter.book_id)
        book.narration = {**(book.narration or {}), "content_mode": "custom"}
    if body.text is not None:
        if not body.text.strip():
            raise ValidationFailed("Chapter text can't be empty. Delete the chapter instead.")
        book_service.set_chapter_text(db, chapter, body.text)
    db.commit()
    return get_chapter(chapter_id, user, db)


@router.delete("/chapters/{chapter_id}", status_code=204)
def delete_chapter(chapter_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    chapter = get_chapter_for(db, chapter_id, user)
    book_service.delete_chapter(db, chapter)
    db.commit()


@router.post("/books/{book_id}/chapters/reorder")
def reorder(book_id: str, body: ReorderIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    book = get_book_for(db, book_id, user)
    book_service.reorder_chapters(db, book, body.chapter_ids)
    db.commit()
    db.refresh(book)
    return {"items": list_payload(db, book)}


@router.post("/books/{book_id}/chapters/merge")
def merge(book_id: str, body: MergeIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    book = get_book_for(db, book_id, user)
    target = book_service.merge_chapters(db, book, body.chapter_ids)
    db.commit()
    return {"chapter_id": target.id}


@router.post("/chapters/{chapter_id}/split")
def split(chapter_id: str, body: SplitIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    chapter = get_chapter_for(db, chapter_id, user)
    new = book_service.split_chapter(db, chapter, body.paragraph_index, body.title)
    db.commit()
    return {"chapter_id": new.id}


@router.post("/chapters/{chapter_id}/generate")
def generate_chapter(chapter_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    chapter = get_chapter_for(db, chapter_id, user)
    if not chapter.include_in_audio:
        chapter.include_in_audio = True
    job = queue.enqueue(
        db,
        type=JobType.GENERATE_CHAPTER,
        user_id=user.id,
        book_id=chapter.book_id,
        chapter_id=chapter.id,
        payload={"force": True},
        stages=[{"key": "prepare", "label": "Voice being created", "status": "active"}, {"key": "build", "label": "Ready to listen", "status": "pending"}],
        exclusive_types={JobType.ANALYZE, JobType.GENERATE_BOOK, JobType.GENERATE_CHAPTER},
    )
    chapter.audio_status = ChapterStatus.QUEUED
    chapter.audio_error = None
    db.commit()
    return serialize_job(job)


@router.get("/chapters/{chapter_id}/timings")
def timings(chapter_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    chapter = get_chapter_for(db, chapter_id, user)
    asset = db.scalar(select(AudioAsset).where(AudioAsset.chapter_id == chapter.id, AudioAsset.kind == "chapter"))
    paragraphs = chapter_paragraphs(db, chapter.id)
    return {
        "chapter_id": chapter.id,
        "timing_source": asset.timing_source if asset else None,
        # [paragraph_position, char_start, char_end, t0, t1]
        "sentences": asset.timings if asset else [],
        "paragraphs": [{"position": p.position, "text": p.text, "kind": p.kind} for p in paragraphs],
    }


@router.get("/chapters/{chapter_id}/narration-preview")
def narration_preview(chapter_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Show exactly what will be spoken (after Narration Cleanup), chunk by chunk."""
    chapter = get_chapter_for(db, chapter_id, user)
    book = db.get(Book, chapter.book_id)
    settings = narration_settings.resolve(book.narration, book.language)
    cast = load_cast(db, book.id) if settings.get("cast_mode") else None
    paragraphs = list(db.scalars(select(Paragraph).where(Paragraph.chapter_id == chapter.id).order_by(Paragraph.position)))
    plan = plan_chapter(chapter, paragraphs, settings, book, cast)
    return {
        "chunks": [
            {"paragraph": c.paragraph, "voice": c.voice.voice_id, "provider": c.voice.provider, "speaker": c.speaker, "text": " ".join(s[0] for s in c.sentences)}
            for c in plan.chunks[:400]
        ],
        "warnings": plan.warnings,
        "characters": plan.chars,
    }
