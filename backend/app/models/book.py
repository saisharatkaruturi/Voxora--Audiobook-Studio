from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk


class BookStatus:
    UPLOADED = "uploaded"  # file stored, not analyzed yet
    ANALYZING = "analyzing"  # extraction / OCR / structure detection running
    REVIEW = "review"  # analyzed; user can edit chapters and choose a voice
    GENERATING = "generating"  # audio generation running
    READY = "ready"  # audiobook available
    FAILED = "failed"

    PROCESSING = {ANALYZING, GENERATING}


class Book(UUIDPk, Timestamps, Base):
    __tablename__ = "books"
    __table_args__ = (Index("ix_books_owner_created", "owner_id", "created_at"),)

    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    subtitle: Mapped[str | None] = mapped_column(String(500))
    author: Mapped[str | None] = mapped_column(String(300), index=True)
    narrator: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    genre: Mapped[str | None] = mapped_column(String(120))
    genres: Mapped[list | None] = mapped_column(JSON)  # all genres, most specific first
    series: Mapped[str | None] = mapped_column(String(300), index=True)
    series_index: Mapped[float | None] = mapped_column(Float)  # 1, 2, 2.5 (novella)...
    classified_at: Mapped[str | None] = mapped_column(String(40))  # when title/author/genre/series were tidied
    book_info: Mapped[dict | None] = mapped_column(JSON)  # {"about": ..., "ratings": {...}} from classification + Open Library
    year: Mapped[str | None] = mapped_column(String(16))
    language: Mapped[str | None] = mapped_column(String(16))
    languages: Mapped[list] = mapped_column(JSON, default=list)  # all detected languages

    status: Mapped[str] = mapped_column(String(20), default=BookStatus.UPLOADED, index=True)
    source_format: Mapped[str] = mapped_column(String(10))
    page_count: Mapped[int | None] = mapped_column(Integer)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    char_count: Mapped[int] = mapped_column(Integer, default=0)

    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False)
    ocr_engine: Mapped[str | None] = mapped_column(String(40))
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    warnings: Mapped[list] = mapped_column(JSON, default=list)

    cover_key: Mapped[str | None] = mapped_column(String(500))
    cover_source: Mapped[str | None] = mapped_column(String(20))  # extracted | generated | uploaded

    narration: Mapped[dict] = mapped_column(JSON, default=dict)  # voice + audio settings
    total_duration: Mapped[float | None] = mapped_column(Float)
    error: Mapped[dict | None] = mapped_column(JSON)
    sort_title: Mapped[str] = mapped_column(String(500), default="", index=True)
    metadata_locked: Mapped[bool] = mapped_column(Boolean, default=False)  # user edited title/author

    files: Mapped[list[BookFile]] = relationship(back_populates="book", cascade="all, delete-orphan")
    chapters: Mapped[list[Chapter]] = relationship(
        back_populates="book", cascade="all, delete-orphan", order_by="Chapter.position"
    )


class BookFile(UUIDPk, Timestamps, Base):
    __tablename__ = "book_files"

    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # original | extracted_text | processed_text | export_zip
    storage_key: Mapped[str] = mapped_column(String(500))
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64))

    book: Mapped[Book] = relationship(back_populates="files")


class ChapterStatus:
    PENDING = "pending"
    QUEUED = "queued"
    GENERATING = "generating"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class Chapter(UUIDPk, Timestamps, Base):
    __tablename__ = "chapters"
    __table_args__ = (Index("ix_chapters_book_position", "book_id", "position"),)

    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(30), default="chapter")  # front_matter|toc|chapter|part|epilogue|appendix|...
    include_in_audio: Mapped[bool] = mapped_column(Boolean, default=True)
    detection: Mapped[dict] = mapped_column(JSON, default=dict)  # how it was detected + confidence
    source_pages: Mapped[list] = mapped_column(JSON, default=list)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    language: Mapped[str | None] = mapped_column(String(16))
    text_version: Mapped[int] = mapped_column(Integer, default=1)

    audio_status: Mapped[str] = mapped_column(String(20), default=ChapterStatus.PENDING)
    audio_progress: Mapped[float] = mapped_column(Float, default=0.0)
    audio_hash: Mapped[str | None] = mapped_column(String(64))  # hash of text+voice settings of current audio
    audio_error: Mapped[dict | None] = mapped_column(JSON)
    duration: Mapped[float | None] = mapped_column(Float)

    book: Mapped[Book] = relationship(back_populates="chapters")
    paragraphs: Mapped[list[Paragraph]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan", order_by="Paragraph.position"
    )


class Paragraph(UUIDPk, Base):
    __tablename__ = "paragraphs"
    __table_args__ = (UniqueConstraint("chapter_id", "position", name="uq_paragraph_position"),)

    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20), default="text")  # text | heading
    language: Mapped[str | None] = mapped_column(String(16))
    page: Mapped[int | None] = mapped_column(Integer)
    spans: Mapped[list | None] = mapped_column(JSON)  # AI Cast: [{start, end, speaker}] over text

    chapter: Mapped[Chapter] = relationship(back_populates="paragraphs")
