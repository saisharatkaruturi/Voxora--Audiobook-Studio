from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk


class BookEmbedding(UUIDPk, Timestamps, Base):
    """One retrievable chunk of a book. `namespace` is always `books/{book_id}`;
    every retrieval query filters on it, so books never leak into each other."""

    __tablename__ = "book_embeddings"
    __table_args__ = (Index("ix_embeddings_namespace_model", "namespace", "model"),)

    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    namespace: Mapped[str] = mapped_column(String(80))
    chapter_id: Mapped[str | None] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    chapter_position: Mapped[int] = mapped_column(Integer)
    chapter_title: Mapped[str] = mapped_column(String(500))
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(120))
    dim: Mapped[int] = mapped_column(Integer)
    vector: Mapped[bytes] = mapped_column(LargeBinary)  # float32, L2-normalized


class CastMember(UUIDPk, Timestamps, Base):
    __tablename__ = "cast_members"
    __table_args__ = (Index("ix_cast_book_name", "book_id", "name", unique=True),)

    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="character")  # narrator | character | unknown
    gender_hint: Mapped[str | None] = mapped_column(String(20))
    description: Mapped[str | None] = mapped_column(String(500))
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    provider: Mapped[str | None] = mapped_column(String(40))
    voice_id: Mapped[str | None] = mapped_column(String(200))
    auto_assigned: Mapped[bool] = mapped_column(Boolean, default=True)


class BookInsight(UUIDPk, Timestamps, Base):
    """AI-generated study material. Never modifies the source text."""

    __tablename__ = "book_insights"
    __table_args__ = (Index("ix_insights_book_kind", "book_id", "kind"),)

    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    chapter_id: Mapped[str | None] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))  # short_summary|detailed_summary|chapter_summary|characters|events|themes|glossary
    content: Mapped[dict] = mapped_column(JSON)
    model: Mapped[str | None] = mapped_column(String(120))


class ChatMessage(UUIDPk, Timestamps, Base):
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_book_user_created", "book_id", "user_id", "created_at"),)

    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list | None] = mapped_column(JSON)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
