"""Signed media delivery (audio streaming with Range support, covers, downloads).

<audio> elements can't send Authorization headers, so media URLs carry an
expiring HMAC signature instead, like presigned S3 URLs.
"""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, RedirectResponse

from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.security import safe_filename, verify_media_signature
from app.providers.storage import get_storage
from app.providers.storage.base import validate_key

router = APIRouter(tags=["media"])
MIME = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".m4b": "audio/mp4", ".wav": "audio/wav", ".flac": "audio/flac", ".jpg": "image/jpeg", ".txt": "text/plain; charset=utf-8"}


@router.get("/media/{key:path}")
def media(key: str, exp: int = Query(...), sig: str = Query(...), download: str | None = Query(None, max_length=200)):
    try:
        validate_key(key)
    except ValueError as exc:
        raise NotFoundError("File not found.") from exc
    if not verify_media_signature(f"/media/{key}", exp, sig):
        raise PermissionDeniedError("This link has expired. Reload the page to get a fresh one.", code="link_expired")
    storage = get_storage()
    if not storage.exists(key):
        raise NotFoundError("File not found. It may have been deleted.")
    presigned = storage.presigned_url(key, 600)
    if presigned:
        return RedirectResponse(presigned)
    ext = "." + key.rsplit(".", 1)[-1].lower() if "." in key else ""
    media_type = MIME.get(ext) or mimetypes.guess_type(key)[0] or "application/octet-stream"
    headers = {"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"}
    return FileResponse(
        storage.local_path(key),
        media_type=media_type,
        headers=headers,
        filename=safe_filename(download) if download else None,
        content_disposition_type="attachment" if download else "inline",
    )
