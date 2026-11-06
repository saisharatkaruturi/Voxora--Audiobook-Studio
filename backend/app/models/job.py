from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UTCDateTime, UUIDPk


class JobStatus:
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    ACTIVE = {QUEUED, RUNNING, PAUSED}
    FINISHED = {COMPLETED, FAILED, CANCELLED}


class JobType:
    ANALYZE = "analyze"
    GENERATE_BOOK = "generate_book"
    GENERATE_CHAPTER = "generate_chapter"
    INDEX_BOOK = "index_book"
    CAST_ANALYSIS = "cast_analysis"
    INSIGHTS = "insights"
    ASK = "ask"


class GenerationJob(UUIDPk, Timestamps, Base):
    """A durable background job. The worker claims queued jobs from this table."""

    __tablename__ = "generation_jobs"
    __table_args__ = (
        Index("ix_jobs_status_created", "status", "created_at"),
        Index("ix_jobs_book_type", "book_id", "type"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    book_id: Mapped[str | None] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[str | None] = mapped_column(ForeignKey("chapters.id", ondelete="SET NULL"))
    type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.QUEUED)
    priority: Mapped[int] = mapped_column(Integer, default=0)

    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0..100, only when measurable
    stage: Mapped[str | None] = mapped_column(String(60))
    message: Mapped[str | None] = mapped_column(String(500))
    current_chapter: Mapped[int | None] = mapped_column(Integer)
    total_chapters: Mapped[int | None] = mapped_column(Integer)
    stages: Mapped[list] = mapped_column(JSON, default=list)  # [{"key","label","status"}]

    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[dict | None] = mapped_column(JSON)

    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    locked_by: Mapped[str | None] = mapped_column(String(100))
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    run_after: Mapped[datetime | None] = mapped_column(UTCDateTime)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
