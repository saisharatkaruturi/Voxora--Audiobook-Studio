"""Durable, database-backed job queue.

Why not Redis/Celery? The app is local-first (one command to run, no services to
install) and Celery/RQ don't run reliably on Windows. Jobs live in the
`generation_jobs` table, so they survive restarts, can be inspected, paused,
resumed and retried, and the API and worker processes coordinate only through
the database. `JobQueue` is the seam where a Redis-backed queue can be added.
"""

from __future__ import annotations

import os
import socket
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ConflictError, JobCancelled, StudioError
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.session import best_effort_write, is_lock_error, session_scope
from app.models import GenerationJob, JobStatus, JobType

log = get_logger(__name__)

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


def enqueue(
    db: Session,
    *,
    type: str,
    user_id: str,
    book_id: str | None = None,
    chapter_id: str | None = None,
    payload: dict | None = None,
    stages: list[dict] | None = None,
    priority: int = 0,
    exclusive_types: set[str] | None = None,
) -> GenerationJob:
    """Create a queued job. `exclusive_types`: refuse if the book already has an
    active job of one of these types (prevents two generations of one book)."""
    if book_id and exclusive_types:
        active = db.scalar(
            select(GenerationJob).where(
                GenerationJob.book_id == book_id,
                GenerationJob.type.in_(exclusive_types),
                GenerationJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
            )
        )
        if active:
            raise ConflictError(
                "This book already has a job in progress. Pause or cancel it first.",
                code="job_in_progress",
                details={"job_id": active.id},
            )
    job = GenerationJob(
        type=type,
        user_id=user_id,
        book_id=book_id,
        chapter_id=chapter_id,
        payload=payload or {},
        stages=stages or [],
        priority=priority,
        max_attempts=get_settings().job_max_attempts,
        stage="queued",
        message="Waiting for a worker",
    )
    db.add(job)
    db.commit()
    log.info("job.enqueued", job_id=job.id, type=type, book_id=book_id)
    return job


# The user is waiting on these: they get their own worker lane, so an upload or a
# narration never queues behind background work (search indexing, cast analysis...).
PIPELINE_JOB_TYPES = frozenset({JobType.ANALYZE, JobType.GENERATE_BOOK, JobType.GENERATE_CHAPTER})


def claim_next(worker_id: str = WORKER_ID, *, pipeline: bool | None = None, prefer: frozenset[str] | None = None) -> str | None:
    """Claim the next due job. pipeline=True only takes PIPELINE_JOB_TYPES,
    pipeline=False only the rest, None takes anything. `prefer`: try those job
    types first, then anything else in the lane (so no worker sits idle)."""
    if prefer:
        return _claim(worker_id, pipeline, prefer) or _claim(worker_id, pipeline, None)
    return _claim(worker_id, pipeline, None)


def _claim(worker_id: str, pipeline: bool | None, only: frozenset[str] | None) -> str | None:
    now = utcnow()
    lane = []
    if pipeline is True:
        lane.append(GenerationJob.type.in_(PIPELINE_JOB_TYPES))
    elif pipeline is False:
        lane.append(GenerationJob.type.not_in(PIPELINE_JOB_TYPES))
    if only:
        lane.append(GenerationJob.type.in_(only))
    with session_scope() as db:
        candidates = db.scalars(
            select(GenerationJob.id)
            .where(
                GenerationJob.status == JobStatus.QUEUED,
                or_(GenerationJob.run_after.is_(None), GenerationJob.run_after <= now),
                *lane,
            )
            .order_by(GenerationJob.priority.desc(), GenerationJob.created_at)
            .limit(5)
        ).all()
        for job_id in candidates:
            result = db.execute(
                update(GenerationJob)
                .where(GenerationJob.id == job_id, GenerationJob.status == JobStatus.QUEUED)
                .values(status=JobStatus.RUNNING, locked_by=worker_id, heartbeat_at=now, started_at=now, error=None)
            )
            if result.rowcount == 1:
                return job_id
    return None


def _pid_alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _dead_local_workers(db) -> list[str]:
    """Workers on this machine whose process is gone (e.g. the server restarted):
    their jobs can resume at once instead of waiting out the heartbeat timeout."""
    host = socket.gethostname()
    dead = []
    for (locked_by,) in db.execute(select(GenerationJob.locked_by).where(GenerationJob.status == JobStatus.RUNNING).distinct()):
        name, _, pid = (locked_by or "").rpartition(":")
        if name == host and pid.isdigit() and not _pid_alive(int(pid)):
            dead.append(locked_by)
    return dead


def recover_stale_jobs() -> int:
    """Requeue jobs whose worker died: no heartbeat within the timeout, or owned by
    a worker process on this machine that no longer exists."""
    cutoff = utcnow() - timedelta(seconds=get_settings().job_heartbeat_timeout)
    with session_scope() as db:
        dead = _dead_local_workers(db)
        result = db.execute(
            update(GenerationJob)
            .where(
                GenerationJob.status == JobStatus.RUNNING,
                or_(GenerationJob.heartbeat_at.is_(None), GenerationJob.heartbeat_at < cutoff, GenerationJob.locked_by.in_(dead)),
            )
            .values(status=JobStatus.QUEUED, locked_by=None, message="Resuming after an interrupted run")
        )
        count = result.rowcount or 0
    if count:
        log.warning("job.recovered_stale", count=count)
    return count


class JobContext:
    """Handed to task handlers: progress reporting plus pause/cancel checks."""

    def __init__(self, job_id: str):
        self.job_id = job_id
        with session_scope() as db:
            job = db.get(GenerationJob, job_id)
            assert job is not None
            self.type = job.type
            self.user_id = job.user_id
            self.book_id = job.book_id
            self.chapter_id = job.chapter_id
            self.payload = dict(job.payload or {})
            self.attempt = job.attempts + 1

    def update(self, **fields) -> None:
        """Persist progress fields (progress, stage, message, current_chapter, total_chapters, stages, result)."""
        fields["heartbeat_at"] = utcnow()
        best_effort_write(lambda db: db.execute(update(GenerationJob).where(GenerationJob.id == self.job_id).values(**fields)))

    def set_stage(self, key: str, status: str, label: str | None = None) -> None:
        best_effort_write(lambda db: self._set_stage(db, key, status, label))

    def _set_stage(self, db, key: str, status: str, label: str | None) -> None:
        job = db.get(GenerationJob, self.job_id)
        if job is None:
            return  # the book (and its job) was deleted meanwhile
        stages = [dict(s) for s in (job.stages or [])]
        for s in stages:
            if s["key"] == key:
                s["status"] = status
                if label:
                    s["label"] = label
                break
        else:
            stages.append({"key": key, "label": label or key, "status": status})
        job.stages = stages
        job.heartbeat_at = utcnow()

    def check(self) -> None:
        """Raise JobCancelled if the user paused or cancelled this job."""
        with session_scope(write=False) as db:
            status = db.scalar(select(GenerationJob.status).where(GenerationJob.id == self.job_id))
        best_effort_write(lambda db: db.execute(update(GenerationJob).where(GenerationJob.id == self.job_id).values(heartbeat_at=utcnow())))
        if status == JobStatus.PAUSED:
            raise JobCancelled(paused=True)
        if status is None or status == JobStatus.CANCELLED:  # None: the book was deleted
            raise JobCancelled(paused=False)


def finish(job_id: str, *, result: dict | None = None) -> None:
    with session_scope() as db:
        job = db.get(GenerationJob, job_id)
        if job and job.status == JobStatus.RUNNING:
            job.status = JobStatus.COMPLETED
            job.progress = 100.0
            job.completed_at = utcnow()
            job.locked_by = None
            job.stage = "completed"
            if result is not None:
                job.result = result


def describe_error(exc: BaseException) -> dict:
    """A user-facing error: never raw SQL or tracebacks (those go to the server log)."""
    if isinstance(exc, StudioError):
        return exc.to_dict()
    if is_lock_error(exc):
        return {"code": "storage_busy", "message": "VOXORA was busy saving your progress and paused for a moment. It picks up where it left off.", "retryable": True}
    return {"code": "internal_error", "message": f"Something unexpected went wrong ({type(exc).__name__}). Completed chapters are saved; try again.", "retryable": False}


def fail(job_id: str, exc: BaseException) -> bool:
    """Record a failure. Returns True if the job was re-queued for retry."""
    error = describe_error(exc)
    retryable = bool(error.get("retryable"))
    with session_scope() as db:
        job = db.get(GenerationJob, job_id)
        if job is None:
            return False
        job.attempts += 1
        job.locked_by = None
        job.error = error
        if retryable and job.attempts < job.max_attempts:
            delay = min(300, 5 * 2**job.attempts)
            job.status = JobStatus.QUEUED
            job.run_after = datetime.now(timezone.utc) + timedelta(seconds=delay)
            job.message = f"{error['message']} Retrying in {delay}s (attempt {job.attempts + 1} of {job.max_attempts})."
            log.warning("job.retry_scheduled", job_id=job_id, attempt=job.attempts, delay=delay, error=error["code"])
            return True
        job.status = JobStatus.FAILED
        job.completed_at = utcnow()
        job.message = error["message"]
        return False


def mark_paused(job_id: str) -> None:
    with session_scope() as db:
        job = db.get(GenerationJob, job_id)
        if job:
            job.locked_by = None
            if job.status == JobStatus.PAUSED:
                job.message = "Paused. Completed chapters are saved; resume any time."
            elif job.status == JobStatus.CANCELLED:
                job.completed_at = utcnow()
                job.message = "Cancelled."
