from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.errors import AuthError
from app.core.ratelimit import limiter
from app.db.session import get_db
from app.models import User
from app.services.auth import authenticate


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise AuthError("Sign in to continue.")
    user = authenticate(db, auth[7:].strip())
    request.state.user_id = user.id
    return user


def client_key(request: Request) -> str:
    return getattr(request.state, "user_id", None) or (request.client.host if request.client else "anon")


def rate_limit(name: str, capacity: int, per_seconds: float):
    def dep(request: Request) -> None:
        limiter.check(f"{name}:{client_key(request)}", capacity=capacity, per_seconds=per_seconds)

    return dep
