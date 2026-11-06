from __future__ import annotations

from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk


class AudioAsset(UUIDPk, Timestamps, Base):
    """A stored audio file.

    kind:
      segment  - cached TTS output for one chunk (keyed by `cache_key`, reusable across books)
      chapter  - encoded chapter audio, with sentence timings for synchronized reading
      full     - the complete audiobook
      preview  - a voice preview sample
    """

    __tablename__ = "audio_assets"
    __table_args__ = (Index("ix_audio_book_kind", "book_id", "kind"),)

    book_id: Mapped[str | None] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[str | None] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    cache_key: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    storage_key: Mapped[str] = mapped_column(String(500))
    format: Mapped[str] = mapped_column(String(10))
    bitrate: Mapped[str | None] = mapped_column(String(10))
    sample_rate: Mapped[int | None] = mapped_column(Integer)
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    settings_hash: Mapped[str | None] = mapped_column(String(64))
    # Sentence timings: [{"p": paragraph_position, "s": char_start, "e": char_end, "t0": sec, "t1": sec}]
    timings: Mapped[list | None] = mapped_column(JSON)
    timing_source: Mapped[str | None] = mapped_column(String(20))  # provider | approximate | mixed
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class Voice(UUIDPk, Timestamps, Base):
    """Cached voice catalog entry from a TTS provider."""

    __tablename__ = "voices"
    __table_args__ = (Index("ix_voices_provider_voice", "provider", "voice_id", unique=True),)

    provider: Mapped[str] = mapped_column(String(40), index=True)
    voice_id: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200))
    language: Mapped[str] = mapped_column(String(16), index=True)  # ISO 639-1, e.g. "te"
    locale: Mapped[str | None] = mapped_column(String(20))  # e.g. "te-IN"
    accent: Mapped[str | None] = mapped_column(String(80))
    gender: Mapped[str | None] = mapped_column(String(20))
    style: Mapped[str | None] = mapped_column(String(120))
    quality: Mapped[str | None] = mapped_column(String(20))
    installed: Mapped[bool] = mapped_column(default=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
