from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, rate_limit
from app.core.errors import PermissionDeniedError, ValidationFailed
from app.db.session import get_db
from app.document_processing.language import LANGUAGE_NAMES
from app.models import Paragraph, User
from app.providers.tts import get_tts_provider, list_tts_providers
from app.schemas.common import InstallVoiceIn, PreviewIn, media_url, serialize_job
from app.services import voices as voice_service
from app.services.books import get_book_for
from app.workers import queue

router = APIRouter(prefix="/api", tags=["voices"])


@router.get("/tts/providers")
def providers(user: User = Depends(current_user)) -> dict:
    return {"items": [p.describe() for p in list_tts_providers()]}


@router.get("/voices")
def voices(
    provider: str | None = None,
    language: str | None = Query(None, max_length=16),
    include_catalog: bool = False,
    user: User = Depends(current_user),
) -> dict:
    items = voice_service.list_voices(provider, language, include_catalog)
    langs = sorted({v["language"] for v in items if v["language"] != "mul"})
    return {"items": items, "languages": [{"code": l, "name": LANGUAGE_NAMES.get(l, l)} for l in langs]}


@router.post("/voices/preview", dependencies=[Depends(rate_limit("preview", 30, 60))])
def preview(body: PreviewIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    text = body.text
    language = body.language
    if body.book_id and not text:
        book = get_book_for(db, body.book_id, user)
        language = language or book.language
        # Preview with a passage from the user's own book.
        for c in book.chapters:
            if c.include_in_audio and c.kind == "chapter":
                para = db.scalar(select(Paragraph).where(Paragraph.chapter_id == c.id, Paragraph.kind == "text").order_by(Paragraph.position))
                if para:
                    text = para.text[:380]
                    break
    key = voice_service.preview(body.provider, body.voice_id, speed=body.speed, pitch=body.pitch, text=text, language=language)
    return {"url": media_url(key)}


@router.post("/voices/piper/install")
def install_piper(body: InstallVoiceIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    catalog = get_tts_provider("piper").catalog()  # type: ignore[attr-defined]
    if catalog and body.voice not in catalog:
        raise ValidationFailed(f"'{body.voice}' is not in the Piper voice catalog.")
    job = queue.enqueue(db, type="install_voice", user_id=user.id, payload={"voice": body.voice}, priority=20)
    return serialize_job(job)


@router.delete("/voices/piper/{voice_key}", status_code=204)
def remove_piper(voice_key: str, user: User = Depends(current_user)) -> None:
    if not user.is_admin:
        raise PermissionDeniedError("Only the admin can remove installed voices.")
    if not voice_key.replace("-", "").replace("_", "").isalnum():
        raise ValidationFailed("Invalid voice name.")
    get_tts_provider("piper").remove_voice(voice_key)  # type: ignore[attr-defined]
    voice_service.invalidate_voice_cache()
