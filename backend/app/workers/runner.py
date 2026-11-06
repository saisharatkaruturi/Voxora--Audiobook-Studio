"""Worker process.

Run standalone:            python -m app.workers.runner
Or embedded in the API:    RUN_WORKER_IN_PROCESS=true (default for local use)
"""

from __future__ import annotations

import threading
import time

from app.core.config import get_settings
from app.core.errors import JobCancelled
from app.core.logging import configure_logging, get_logger
from app.models import JobType
from app.workers import queue

log = get_logger(__name__)


class WorkerPool:
    def __init__(self, concurrency: int | None = None, poll_interval: float | None = None):
        s = get_settings()
        self.concurrency = concurrency or s.worker_concurrency
        self.background = s.background_workers
        self.poll_interval = poll_interval or s.worker_poll_interval
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        queue.recover_stale_jobs()
        # Pipeline lane (uploads, narration) + background lane (indexing, cast, exports).
        # Pipeline workers alternate a preference: reading new books (CPU-bound) and
        # narrating (mostly waiting on the speech service) then overlap, instead of a
        # big import analysing every book before the first one starts narrating.
        narrate = frozenset({JobType.GENERATE_BOOK, JobType.GENERATE_CHAPTER})
        analyze = frozenset({JobType.ANALYZE})
        lanes = [(f"worker-{i}", True, narrate if i % 2 else analyze) for i in range(self.concurrency)]
        lanes += [(f"background-{i}", False, None) for i in range(self.background)]
        if not self.background:
            lanes = [(name, None, prefer) for name, _, prefer in lanes]
        for name, pipeline, prefer in lanes:
            t = threading.Thread(target=self._loop, args=(pipeline, prefer), name=name, daemon=True)
            t.start()
            self._threads.append(t)
        threading.Thread(target=self._janitor, name="worker-janitor", daemon=True).start()
        log.info("worker.started", concurrency=self.concurrency, background=self.background, worker=queue.WORKER_ID)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=timeout)

    def _janitor(self) -> None:
        while not self._stop.wait(60):
            try:
                queue.recover_stale_jobs()
                from app.services.maintenance import cleanup_temp_files

                cleanup_temp_files()
            except Exception:
                log.exception("worker.janitor_failed")

    def _loop(self, pipeline: bool | None = None, prefer: frozenset[str] | None = None) -> None:
        from app.workers.tasks import HANDLERS

        while not self._stop.is_set():
            try:
                job_id = queue.claim_next(pipeline=pipeline, prefer=prefer)
            except Exception:
                log.exception("worker.claim_failed")
                job_id = None
            if job_id is None:
                self._stop.wait(self.poll_interval)
                continue
            run_job(job_id, HANDLERS)


def _heartbeat(job_id: str, stop: threading.Event) -> None:
    """Keep the job's heartbeat fresh while a handler blocks in a long call
    (LLM request, big TTS chunk), so it isn't mistaken for a crashed worker."""
    from sqlalchemy import update

    from app.db.base import utcnow
    from app.db.session import best_effort_write
    from app.models import GenerationJob, JobStatus

    while not stop.wait(20):
        try:
            best_effort_write(
                lambda db: db.execute(
                    update(GenerationJob)
                    .where(GenerationJob.id == job_id, GenerationJob.status == JobStatus.RUNNING)
                    .values(heartbeat_at=utcnow())
                )
            )
        except Exception:
            log.warning("job.heartbeat_failed", job_id=job_id)


def run_job(job_id: str, handlers: dict) -> None:
    ctx = queue.JobContext(job_id)
    handler = handlers.get(ctx.type)
    started = time.monotonic()
    log.info("job.started", job_id=job_id, type=ctx.type, book_id=ctx.book_id, attempt=ctx.attempt)
    stop = threading.Event()
    threading.Thread(target=_heartbeat, args=(job_id, stop), name=f"heartbeat-{job_id[:8]}", daemon=True).start()
    try:
        if handler is None:
            raise RuntimeError(f"No handler for job type {ctx.type!r}")
        result = handler(ctx)
        queue.finish(job_id, result=result)
        log.info("job.completed", job_id=job_id, type=ctx.type, seconds=round(time.monotonic() - started, 1))
    except JobCancelled as exc:
        queue.mark_paused(job_id)
        log.info("job.paused" if exc.paused else "job.cancelled", job_id=job_id)
    except Exception as exc:
        retried = queue.fail(job_id, exc)
        log.error("job.failed", exc_info=not retried, job_id=job_id, type=ctx.type, retrying=retried, error=str(exc)[:300])
        try:
            from app.workers.tasks import on_job_failed

            if not retried:
                on_job_failed(ctx, exc)
        except Exception:
            log.exception("job.failure_hook_failed", job_id=job_id)
    finally:
        stop.set()


def main() -> None:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    from app.db.init import init_db

    init_db()
    pool = WorkerPool()
    pool.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pool.stop()


if __name__ == "__main__":
    main()
