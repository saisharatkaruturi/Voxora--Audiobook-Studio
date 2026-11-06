from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk


class ListeningProgress(UUIDPk, Timestamps, Base):
    __tablename__ = "listening_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "book_id", name="uq_progress_user_book"),
        Index("ix_progress_user_updated", "user_id", "updated_at"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[str | None] = mapped_column(ForeignKey("chapters.id", ondelete="SET NULL"))
    chapter_position: Mapped[int] = mapped_column(Integer, default=0)
    position_seconds: Mapped[float] = mapped_column(Float, default=0.0)  # within chapter
    book_position_seconds: Mapped[float] = mapped_column(Float, default=0.0)  # across the whole book
    playback_rate: Mapped[float] = mapped_column(Float, default=1.0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)


class Bookmark(UUIDPk, Timestamps, Base):
    __tablename__ = "bookmarks"
    __table_args__ = (Index("ix_bookmarks_user_book", "user_id", "book_id"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    chapter_id: Mapped[str | None] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    chapter_title: Mapped[str | None] = mapped_column(String(500))
    position_seconds: Mapped[float] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(Text)
