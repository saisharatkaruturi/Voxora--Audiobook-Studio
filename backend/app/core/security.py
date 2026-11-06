"""Password hashing, access tokens and signed media URLs.

Uses only the standard library (scrypt + HMAC-SHA256) so there are no native
dependencies to break on upgrade.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import unicodedata

from app.core.config import get_settings
from app.core.errors import AuthError

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        candidate = hashlib.scrypt(
            password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=len(_unb64(digest))
        )
        return hmac.compare_digest(candidate, _unb64(digest))
    except (ValueError, TypeError):
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _sign(payload: bytes, purpose: str) -> str:
    key = hashlib.sha256((get_settings().secret_key + ":" + purpose).encode()).digest()
    return _b64(hmac.new(key, payload, hashlib.sha256).digest())


def create_access_token(user_id: str, ttl_minutes: int | None = None) -> str:
    ttl = ttl_minutes or get_settings().access_token_ttl_minutes
    body = _b64(json.dumps({"sub": user_id, "exp": int(time.time()) + ttl * 60}).encode())
    return f"{body}.{_sign(body.encode(), 'access')}"


def decode_access_token(token: str) -> str:
    try:
        body, sig = token.split(".", 1)
    except ValueError as exc:
        raise AuthError("Invalid session token. Please sign in again.") from exc
    if not hmac.compare_digest(sig, _sign(body.encode(), "access")):
        raise AuthError("Invalid session token. Please sign in again.")
    data = json.loads(_unb64(body))
    if data.get("exp", 0) < time.time():
        raise AuthError("Your session has expired. Please sign in again.", code="token_expired")
    return data["sub"]


def sign_media_path(path: str, ttl_seconds: int | None = None) -> str:
    """Return `path?exp=..&sig=..` granting temporary access to a media file.

    Used for <audio> sources and downloads, where the browser can't attach an
    Authorization header. Mirrors how presigned URLs work for S3 storage.
    """
    exp = int(time.time()) + (ttl_seconds or get_settings().media_url_ttl_seconds)
    sig = _sign(f"{path}|{exp}".encode(), "media")
    sep = "&" if "?" in path else "?"
    return f"{path}{sep}exp={exp}&sig={sig}"


def verify_media_signature(path: str, exp: int, sig: str) -> bool:
    if exp < time.time():
        return False
    return hmac.compare_digest(sig, _sign(f"{path}|{exp}".encode(), "media"))


_UNSAFE = re.compile(r"[^A-Za-z0-9._ -]+")


def safe_filename(name: str, default: str = "file", max_length: int = 120) -> str:
    """Reduce an untrusted filename to a safe basename (no paths, no control chars)."""
    name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    name = name.replace("\\", "/").split("/")[-1]
    name = _UNSAFE.sub("_", name).strip(" ._")
    if not name:
        return default
    stem, dot, ext = name.rpartition(".")
    if dot and len(ext) <= 10:
        return f"{stem[: max_length - len(ext) - 1]}.{ext}"
    return name[:max_length]


def slugify(text: str, max_length: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:max_length].strip("-") or "untitled"
