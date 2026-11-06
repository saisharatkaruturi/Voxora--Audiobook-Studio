from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.models import AudioAsset, Bookmark, Chapter, ListeningProgress, User
from app.schemas.common import BookmarkIn, BookmarkUpdateIn, ProgressIn, media_url, serialize_bookmark, serialize_progress
from app.services.books import get_book_for
from app.services.handoff import device_mode, mark_received, on_device

router = APIRouter(prefix="/api", tags=["player"])


@router.get("/books/{book_id}/playback")
def playback(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Everything the player needs: playable chapters (signed URLs), progress, bookmarks."""
    book = get_book_for(db, book_id, user)
    assets = {a.chapter_id: a for a in db.scalars(select(AudioAsset).where(AudioAsset.book_id == book.id, AudioAsset.kind == "chapter"))}
    tracks = []
    offset = 0.0
    for c in book.chapters:
        a = assets.get(c.id)
        if not c.include_in_audio or a is None:
            continue
        delivered = on_device(a)
        tracks.append({
            "chapter_id": c.id, "position": c.position, "title": c.title, "kind": c.kind,
            # Once handed to the listener's device the server no longer has the file.
            "url": None if delivered else media_url(a.storage_key), "duration": a.duration, "offset": round(offset, 3),
            "timing_source": a.timing_source,
            "audio_hash": a.settings_hash, "audio_id": a.id, "format": a.format, "on_device": delivered,
        })
        offset += a.duration
    progress = db.scalar(select(ListeningProgress).where(ListeningProgress.user_id == user.id, ListeningProgress.book_id == book.id))
    bookmarks = db.scalars(select(Bookmark).where(Bookmark.user_id == user.id, Bookmark.book_id == book.id).order_by(Bookmark.created_at.desc()))
    return {
        "book": {"id": book.id, "title": book.title, "author": book.author, "narrator": book.narrator, "cover_url": media_url(book.cover_key), "language": book.language},
        "tracks": tracks,
        "total_duration": round(offset, 3),
        "progress": serialize_progress(progress),
        "bookmarks": [serialize_bookmark(b) for b in bookmarks],
        "audio_delivery": get_settings().audio_delivery,
    }


class ReceivedIn(BaseModel):
    audio_hash: str = Field(min_length=8, max_length=64)


@router.post("/books/{book_id}/chapters/{chapter_id}/audio/received")
def audio_received(book_id: str, chapter_id: str, body: ReceivedIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """The listener's browser has stored this chapter: the server drops its copy (device mode)."""
    book = get_book_for(db, book_id, user)
    chapter = next((c for c in book.chapters if c.id == chapter_id), None)
    if chapter is None:
        raise NotFoundError("Chapter not found.")
    # Only the owner's own device takes the audio (an admin viewing a book must not).
    if not device_mode() or book.owner_id != user.id:
        return {"on_device": False}
    mark_received(db, chapter, body.audio_hash)
    return {"on_device": True}


@router.put("/books/{book_id}/progress")
def save_progress(book_id: str, body: ProgressIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    book = get_book_for(db, book_id, user)
    chapter = db.get(Chapter, body.chapter_id) if body.chapter_id else None
    if chapter is not None and chapter.book_id != book.id:
        raise NotFoundError("Chapter not found in this book.")
    progress = db.scalar(select(ListeningProgress).where(ListeningProgress.user_id == user.id, ListeningProgress.book_id == book.id))
    if progress is None:
        progress = ListeningProgress(user_id=user.id, book_id=book.id)
        db.add(progress)
    before = 0.0
    if chapter is not None:
        before = sum(c.duration or 0 for c in book.chapters if c.include_in_audio and c.position < chapter.position and c.duration)
    progress.chapter_id = chapter.id if chapter else None
    progress.chapter_position = chapter.position if chapter else 0
    progress.position_seconds = body.position_seconds
    progress.book_position_seconds = before + body.position_seconds
    progress.playback_rate = body.playback_rate
    progress.completed = body.completed
    db.commit()
    return serialize_progress(progress)


@router.get("/books/{book_id}/bookmarks")
def list_bookmarks(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    get_book_for(db, book_id, user)
    rows = db.scalars(select(Bookmark).where(Bookmark.user_id == user.id, Bookmark.book_id == book_id).order_by(Bookmark.created_at.desc()))
    return {"items": [serialize_bookmark(b) for b in rows]}


@router.post("/books/{book_id}/bookmarks", status_code=201)
def add_bookmark(book_id: str, body: BookmarkIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    book = get_book_for(db, book_id, user)
    chapter = db.get(Chapter, body.chapter_id) if body.chapter_id else None
    if chapter is not None and chapter.book_id != book.id:
        raise NotFoundError("Chapter not found in this book.")
    bm = Bookmark(user_id=user.id, book_id=book.id, chapter_id=chapter.id if chapter else None, chapter_title=chapter.title if chapter else None, position_seconds=body.position_seconds, note=(body.note or "").strip() or None)
    db.add(bm)
    db.commit()
    return serialize_bookmark(bm)


def _bookmark(db: Session, bookmark_id: str, user: User) -> Bookmark:
    bm = db.get(Bookmark, bookmark_id)
    if bm is None or bm.user_id != user.id:
        raise NotFoundError("Bookmark not found.")
    return bm


@router.patch("/bookmarks/{bookmark_id}")
def update_bookmark(bookmark_id: str, body: BookmarkUpdateIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    bm = _bookmark(db, bookmark_id, user)
    bm.note = (body.note or "").strip() or None
    db.commit()
    return serialize_bookmark(bm)


@router.delete("/bookmarks/{bookmark_id}", status_code=204)
def delete_bookmark(bookmark_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    db.delete(_bookmark(db, bookmark_id, user))
    db.commit()
