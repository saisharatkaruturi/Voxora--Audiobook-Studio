from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    # Empty for accounts that sign in through Supabase (they have no local password).
    password_hash: Mapped[str] = mapped_column(String(255))
    # Supabase Auth user id (the token's `sub`); set once the account signs in through Supabase.
    auth_subject: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    settings: Mapped[UserSettings | None] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")


class UserSettings(UUIDPk, Timestamps, Base):
    """Per-user preferences: default narration settings, playback prefs, privacy choices."""

    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)

    user: Mapped[User] = relationship(back_populates="settings")
