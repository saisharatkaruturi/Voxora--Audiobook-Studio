"""Device delivery (AUDIO_DELIVERY=device): the server converts, the listener keeps.

A finished chapter's audio waits in storage only until the listener's browser has
downloaded it and confirmed (``mark_received``). Then the file is deleted and only
its metadata stays (duration, sentence timings, the content hash the browser files
it under), so the player, progress and read-along keep working. Audio nobody
collects is swept after DEVICE_HANDOFF_TTL_HOURS.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models import AudioAsset, Book, BookStatus, Chapter, ChapterStatus
from app.providers.storage import get_storage

log = get_logger(__name__)


def device_mode() -> bool:
    return get_settings().audio_delivery == "device"


def on_device(asset: AudioAsset | None) -> bool:
    return bool(asset is not None and (asset.meta or {}).get("on_device"))


def mark_received(db: Session, chapter: Chapter, audio_hash: str) -> AudioAsset:
    """The browser stored this chapter's audio: delete the server copy."""
    asset = db.scalar(select(AudioAsset).where(AudioAsset.chapter_id == chapter.id, AudioAsset.kind == "chapter"))
    if asset is None:
        raise NotFoundError("This chapter has no audio yet.")
    if asset.settings_hash != audio_hash:
        # The chapter was re-narrated after the browser fetched it: keep the new audio.
        raise ConflictError("This chapter was re-narrated; download the new audio.", code="audio_changed")
    if not on_device(asset):
        # Record the delivery first: if the commit fails the file is still there to retry with.
        asset.meta = {**(asset.meta or {}), "on_device": True, "delivered_at": utcnow().isoformat()}
        asset.size_bytes = 0
        db.commit()
        get_storage().delete(asset.storage_key)
        log.info("handoff.delivered", chapter_id=chapter.id)
    return asset


def sweep_undelivered(db: Session) -> int:
    """Delete chapter audio that waited longer than the hand-off window."""
    cutoff = utcnow() - timedelta(hours=get_settings().device_handoff_ttl_hours)
    # Only audio made for hand-off: a library generated before device mode keeps its files.
    stale = [
        a
        for a in db.scalars(select(AudioAsset).where(AudioAsset.kind == "chapter", AudioAsset.created_at < cutoff))
        if (a.meta or {}).get("handoff") and not on_device(a)
    ]
    books = {a.book_id for a in stale if a.book_id}
    storage = get_storage()
    for asset in stale:
        storage.delete(asset.storage_key)
        chapter = db.get(Chapter, asset.chapter_id) if asset.chapter_id else None
        if chapter is not None:
            chapter.audio_status = ChapterStatus.PENDING
            chapter.audio_hash = None
            chapter.duration = None
            chapter.audio_progress = 0
        db.delete(asset)
    if stale:
        db.flush()
        for book_id in books:
            book = db.get(Book, book_id)
            if book is None:
                continue
            done = [c.duration or 0 for c in book.chapters if c.include_in_audio and c.audio_status == ChapterStatus.DONE]
            book.total_duration = sum(done) or None
            if book.status == BookStatus.READY and len(done) < sum(1 for c in book.chapters if c.include_in_audio):
                book.status = BookStatus.REVIEW  # some chapters need narrating again
        db.commit()
        log.info("handoff.swept", chapters=len(stale))
    return len(stale)
