from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.errors import NotFoundError, ValidationFailed
from app.db.session import get_db
from app.models import Book, BookStatus, Chapter, ChapterStatus, GenerationJob, JobStatus, JobType, User
from app.schemas.common import serialize_job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def get_job_for(db: Session, job_id: str, user: User) -> GenerationJob:
    job = db.get(GenerationJob, job_id)
    if job is None or (job.user_id != user.id and not user.is_admin):
        raise NotFoundError("Job not found.")
    return job


@router.get("")
def list_jobs(book_id: str | None = None, active: bool = False, limit: int = Query(20, le=100), user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    stmt = select(GenerationJob).where(GenerationJob.user_id == user.id)
    if book_id:
        stmt = stmt.where(GenerationJob.book_id == book_id)
    if active:
        stmt = stmt.where(GenerationJob.status.in_(list(JobStatus.ACTIVE)))
    return {"items": [serialize_job(j) for j in db.scalars(stmt.order_by(GenerationJob.created_at.desc()).limit(limit))]}


@router.get("/{job_id}")
def get_job(job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return serialize_job(get_job_for(db, job_id, user))


@router.post("/{job_id}/pause")
def pause(job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    job = get_job_for(db, job_id, user)
    if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
        raise ValidationFailed(f"A {job.status} job can't be paused.")
    job.status = JobStatus.PAUSED
    job.message = "Pausing after the current chunk..." if job.locked_by else "Paused."
    _settle_book(db, job)
    db.commit()
    return serialize_job(job)


@router.post("/{job_id}/resume")
def resume(job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    job = get_job_for(db, job_id, user)
    if job.status not in (JobStatus.PAUSED, JobStatus.FAILED):
        raise ValidationFailed(f"A {job.status} job can't be resumed.")
    if job.status == JobStatus.FAILED:
        job.attempts = 0
    job.status = JobStatus.QUEUED
    job.run_after = None
    job.error = None
    job.completed_at = None
    job.message = "Resuming. Completed chapters are kept."
    if job.book_id and job.type in (JobType.GENERATE_BOOK, JobType.GENERATE_CHAPTER):
        book = db.get(Book, job.book_id)
        book.status = BookStatus.GENERATING
        book.error = None
    elif job.book_id and job.type == JobType.ANALYZE:
        db.get(Book, job.book_id).status = BookStatus.ANALYZING
    db.commit()
    return serialize_job(job)


@router.post("/{job_id}/retry")
def retry(job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    job = get_job_for(db, job_id, user)
    if job.status != JobStatus.FAILED:
        raise ValidationFailed("Only failed jobs can be retried.")
    job.attempts = 0
    return resume(job_id, user, db)


@router.post("/{job_id}/cancel")
def cancel(job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    job = get_job_for(db, job_id, user)
    if job.status in JobStatus.FINISHED:
        raise ValidationFailed(f"This job is already {job.status}.")
    job.status = JobStatus.CANCELLED
    job.message = "Cancelled."
    _settle_book(db, job)
    db.commit()
    return serialize_job(job)


def _settle_book(db: Session, job: GenerationJob) -> None:
    """Give the book a sensible status once its job stops."""
    if not job.book_id:
        return
    book = db.get(Book, job.book_id)
    if book is None:
        return
    if job.type == JobType.ANALYZE:
        if job.status == JobStatus.CANCELLED:
            book.status = BookStatus.REVIEW if book.chapters else BookStatus.UPLOADED
        return
    if not job.locked_by:
        for c in db.scalars(select(Chapter).where(Chapter.book_id == book.id, Chapter.audio_status == ChapterStatus.QUEUED)):
            c.audio_status = ChapterStatus.PENDING
    has_audio = any(c.audio_status == ChapterStatus.DONE for c in book.chapters)
    book.status = BookStatus.READY if has_audio else BookStatus.REVIEW
