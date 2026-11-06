"""Who is calling: turn a bearer token into a VOXORA user.

Two modes (see `Settings.uses_supabase_auth`):

* **local**: tokens are VOXORA's own HMAC tokens, issued by /api/auth/login.
* **supabase**: the browser signs in with Supabase Auth and sends Supabase's access
  token (a JWT). It is verified against the project's public signing keys (JWKS),
  or the legacy HS256 secret, and mapped to a row in `users`, created on first
  sign-in. All app data (books, audio, progress) keeps hanging off `users.id`.
"""

from __future__ import annotations

import threading

import jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AuthError, PermissionDeniedError, ProviderUnavailableError
from app.core.logging import get_logger
from app.core.security import decode_access_token
from app.models import User

log = get_logger(__name__)

_ASYMMETRIC = ["ES256", "RS256", "EdDSA"]
_jwks_lock = threading.Lock()
_jwks_client: jwt.PyJWKClient | None = None


def _jwks() -> jwt.PyJWKClient:
    global _jwks_client
    with _jwks_lock:
        if _jwks_client is None:
            url = f"{get_settings().supabase_url}/auth/v1/.well-known/jwks.json"
            # Keys are cached and refetched when an unknown key id shows up (key rotation).
            _jwks_client = jwt.PyJWKClient(url, cache_keys=True, lifespan=600, timeout=10)
        return _jwks_client


def reset_jwks_client() -> None:
    global _jwks_client
    with _jwks_lock:
        _jwks_client = None


def verify_supabase_token(token: str) -> dict:
    """Validate a Supabase access token and return its claims."""
    s = get_settings()
    try:
        alg = jwt.get_unverified_header(token).get("alg")
    except jwt.InvalidTokenError as exc:
        raise AuthError("Invalid session token. Please sign in again.") from exc
    if alg == "HS256":
        if not s.supabase_jwt_secret:
            raise AuthError("Invalid session token. Please sign in again.")
        key, algorithms = s.supabase_jwt_secret, ["HS256"]
    elif alg in _ASYMMETRIC:
        try:
            key, algorithms = _jwks().get_signing_key_from_jwt(token).key, _ASYMMETRIC
        except jwt.PyJWKClientConnectionError as exc:
            log.warning("auth.jwks_unreachable", error=str(exc))
            # 503, not 401: a Supabase hiccup must not sign everyone out.
            raise ProviderUnavailableError("supabase", "Couldn't verify your session right now. Try again in a moment.") from exc
        except jwt.PyJWKClientError as exc:
            raise AuthError("Invalid session token. Please sign in again.") from exc
    else:
        raise AuthError("Invalid session token. Please sign in again.")
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=algorithms,
            audience=s.supabase_jwt_audience,
            issuer=f"{s.supabase_url}/auth/v1",
            options={"require": ["exp", "sub", "iss", "aud"]},
            leeway=30,
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Your session has expired. Please sign in again.", code="token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("Invalid session token. Please sign in again.") from exc
    # The anon key is itself a valid JWT (role "anon"); only real signed-in users get in.
    if claims.get("role") != "authenticated" or claims.get("is_anonymous"):
        raise AuthError("Sign in to continue.")
    return claims


def _display_name(claims: dict, email: str) -> str:
    meta = claims.get("user_metadata") or {}
    for key in ("display_name", "full_name", "name"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:120]
    return (email.split("@")[0] or "Reader")[:120]


def _user_for_claims(db: Session, claims: dict) -> User:
    s = get_settings()
    subject = str(claims["sub"])
    user = db.scalar(select(User).where(User.auth_subject == subject))
    email = (claims.get("email") or "").strip().lower()
    if user is None:
        if not email:
            raise AuthError("Your account has no email address.", code="email_required")
        verified = bool((claims.get("user_metadata") or {}).get("email_verified"))
        existing = db.scalar(select(User).where(User.email == email))
        if existing is not None:
            # Attach an account that predates Supabase -- only once Supabase has proven
            # the caller owns that address, or anyone could sign up as someone else.
            if not verified:
                raise PermissionDeniedError(
                    "Confirm your email address to open your existing library.", code="email_unverified"
                )
            if existing.auth_subject and existing.auth_subject != subject:
                raise PermissionDeniedError("This email is linked to a different sign-in.", code="account_conflict")
            existing.auth_subject = subject
            user = existing
            log.info("auth.linked", user_id=user.id)
        else:
            if not s.allow_registration and not s.is_admin_email(email):
                raise PermissionDeniedError("Registration is closed on this server. Ask the admin for an account.")
            user = User(email=email, display_name=_display_name(claims, email), password_hash="", auth_subject=subject)
            db.add(user)
            log.info("auth.provisioned", email_verified=verified)
        try:
            db.commit()
        except IntegrityError:
            # Two first requests raced; the other one created the row.
            db.rollback()
            user = db.scalar(select(User).where(User.auth_subject == subject))
            if user is None:
                raise
    elif email and user.email != email:
        # Email changed in Supabase (it re-confirms changes before issuing tokens).
        clash = db.scalar(select(User).where(User.email == email, User.id != user.id))
        if clash is None:
            user.email = email
            db.commit()
    if s.is_admin_email(user.email) and not user.is_admin:
        user.is_admin = True
        db.commit()
        log.info("auth.admin_granted", user_id=user.id)
    return user


def authenticate(db: Session, token: str) -> User:
    """Resolve a bearer token to an active user, or raise AuthError."""
    if not token:
        raise AuthError("Sign in to continue.")
    if get_settings().uses_supabase_auth:
        user = _user_for_claims(db, verify_supabase_token(token))
    else:
        user = db.get(User, decode_access_token(token))
    if user is None or not user.is_active:
        raise AuthError("Your account was not found or is disabled.")
    return user
