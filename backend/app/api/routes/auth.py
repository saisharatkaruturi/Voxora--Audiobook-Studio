from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, rate_limit
from app.core.config import get_settings
from app.core.errors import AuthError, ConflictError, PermissionDeniedError, ValidationFailed
from app.core.logging import get_logger
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models import User
from app.schemas.common import LoginIn, ProfileIn, RegisterIn, serialize_user

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = get_logger(__name__)


@router.get("/config")
def auth_config(db: Session = Depends(get_db)) -> dict:
    s = get_settings()
    if s.uses_supabase_auth:
        # Only public values: the anon key is meant for browsers (Row Level Security
        # guards Supabase's own tables; VOXORA data is only reachable through this API).
        return {
            "provider": "supabase",
            "supabase_url": s.supabase_url,
            "supabase_anon_key": s.supabase_anon_key,
            "oauth_providers": s.supabase_oauth_providers,
            "registration_open": s.allow_registration,
            "has_users": True,
            "audio_delivery": s.audio_delivery,
        }
    users = db.scalar(select(func.count()).select_from(User)) or 0
    return {"provider": "local", "registration_open": s.allow_registration or users == 0, "has_users": users > 0, "audio_delivery": s.audio_delivery}


def _local_accounts_only() -> None:
    if get_settings().uses_supabase_auth:
        raise PermissionDeniedError("Sign in through the VOXORA sign-in page.", code="use_supabase")


@router.post("/register", dependencies=[Depends(_local_accounts_only), Depends(rate_limit("register", 5, 3600))])
def register(body: RegisterIn, db: Session = Depends(get_db)) -> dict:
    users = db.scalar(select(func.count()).select_from(User)) or 0
    if users and not get_settings().allow_registration:
        raise PermissionDeniedError("Registration is closed on this server. Ask the admin for an account.")
    email = body.email.lower().strip()
    if db.scalar(select(User).where(User.email == email)):
        raise ConflictError("An account with this email already exists. Sign in instead.", code="email_taken")
    user = User(email=email, display_name=body.display_name.strip(), password_hash=hash_password(body.password), is_admin=users == 0)
    db.add(user)
    db.commit()
    log.info("auth.registered", user_id=user.id, admin=user.is_admin)
    return {"token": create_access_token(user.id), "user": serialize_user(user)}


@router.post("/login", dependencies=[Depends(_local_accounts_only), Depends(rate_limit("login", 10, 300))])
def login(body: LoginIn, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(User.email == body.email.lower().strip()))
    if user is None or not verify_password(body.password, user.password_hash) or not user.is_active:
        raise AuthError("Incorrect email or password.", code="invalid_credentials")
    return {"token": create_access_token(user.id), "user": serialize_user(user)}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return serialize_user(user)


@router.patch("/me")
def update_me(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if body.display_name:
        user.display_name = body.display_name.strip()
    if body.new_password:
        if get_settings().uses_supabase_auth or not user.password_hash:
            raise ValidationFailed("Change your password from the sign-in provider.", code="use_supabase")
        if not body.current_password or not verify_password(body.current_password, user.password_hash):
            raise ValidationFailed("Your current password is incorrect.", code="wrong_password")
        user.password_hash = hash_password(body.new_password)
    db.add(user)
    db.commit()
    return serialize_user(user)
