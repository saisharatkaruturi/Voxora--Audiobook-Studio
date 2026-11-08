from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, rate_limit
from app.core.config import get_settings
from app.core.errors import PermissionDeniedError
from app.db.session import get_db
from app.document_processing.language import LANGUAGE_NAMES
from app.models import AudioAsset, Book, Chapter, User
from app.providers.embeddings import get_embedding_provider
from app.providers.llm import get_llm_provider
from app.providers.ocr import list_ocr_providers
from app.providers.tts import list_tts_providers
from app.schemas.common import PreferencesIn
from app.services import user_settings
from app.services.maintenance import clear_tts_cache

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    db.execute(select(1))
    return {"status": "ok", "app": get_settings().app_name}


@router.get("/system/status")
def status(user: User = Depends(current_user)) -> dict:
    """Which engines are available and where data goes: the source of the Privacy panel."""
    s = get_settings()
    llm = get_llm_provider()
    emb = get_embedding_provider()
    usage = shutil.disk_usage(s.storage_path)
    return {
        "tts": [p.describe() for p in list_tts_providers()],
        "default_tts": s.tts_provider,
        "ocr": [p.describe() for p in list_ocr_providers()],
        "ocr_mode": s.ocr_provider,
        "llm": llm.describe() if llm else {"name": "none", "available": False, "is_local": True, "reason": "No LLM configured"},
        "embeddings": {"model": emb.model_id, "is_local": emb.is_local},
        "storage": {"provider": s.storage_provider, "free_bytes": usage.free, "local": s.storage_provider == "local"},
        "limits": {"max_file_size_mb": s.max_file_size_mb, "max_pages": s.max_pages},
        "privacy": {
            "analytics": s.analytics_enabled,
            "temp_file_ttl_hours": s.temp_file_ttl_hours,
            "retention": "Uploaded files, extracted text and generated audio are kept until you delete them.",
        },
        "languages": [{"code": k, "name": v} for k, v in sorted(LANGUAGE_NAMES.items(), key=lambda kv: kv[1])],
    }


@router.get("/settings")
def get_preferences(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return user_settings.get_preferences(db, user.id)


@router.put("/settings")
def put_preferences(body: PreferencesIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return user_settings.update_preferences(db, user.id, body.model_dump())


@router.get("/storage")
def storage_usage(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    books = db.scalar(select(func.count()).select_from(Book).where(Book.owner_id == user.id)) or 0
    audio = db.scalar(select(func.coalesce(func.sum(AudioAsset.size_bytes), 0)).join(Book, Book.id == AudioAsset.book_id).where(Book.owner_id == user.id)) or 0
    cache = db.scalar(select(func.coalesce(func.sum(AudioAsset.size_bytes), 0)).where(AudioAsset.kind == "segment")) or 0
    return {"books": books, "audio_bytes": int(audio), "tts_cache_bytes": int(cache)}


@router.delete("/storage/tts-cache")
def delete_cache(user: User = Depends(current_user)) -> dict:
    if not user.is_admin:
        raise PermissionDeniedError("Only the admin can clear the shared TTS cache.")
    return clear_tts_cache()


@router.get("/search")
def search(q: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    like = f"%{q.strip()[:100]}%"
    books = db.scalars(select(Book).where(Book.owner_id == user.id, (Book.title.ilike(like)) | (Book.author.ilike(like))).limit(10))
    chapters = db.execute(
        select(Chapter.id, Chapter.title, Chapter.book_id, Book.title).join(Book).where(Book.owner_id == user.id, Chapter.title.ilike(like)).limit(15)
    ).all()
    return {
        "books": [{"id": b.id, "title": b.title, "author": b.author} for b in books],
        "chapters": [{"id": cid, "title": t, "book_id": bid, "book_title": bt} for cid, t, bid, bt in chapters],
    }


@router.get("/search/books", dependencies=[Depends(rate_limit("book_finder", 20, 60))])
def find_books(q: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Search bar book finder: a title, author or character -> matching books, what they're
    about, reader ratings and recommendations. Books already in the library link to it."""
    import re

    from app.core.errors import ValidationFailed
    from app.services.book_finder import find

    if len(q.strip()) < 2:
        raise ValidationFailed("Type at least 2 characters.")
    result = find(q)
    squash = lambda t: re.sub(r"[^a-z0-9]", "", (t or "").lower())  # noqa: E731
    mine = {squash(t): bid for bid, t in db.execute(select(Book.id, Book.title).where(Book.owner_id == user.id)).all()}
    tag = lambda b: {**b, "library_book_id": mine.get(squash(b["title"]))}  # noqa: E731
    return {**result, "matches": [tag(b) for b in result["matches"]], "recommendations": [tag(b) for b in result["recommendations"]]}
