"""WebSockets for live progress.

/ws/jobs/{job_id}?token=...    job snapshots
/ws/books/{book_id}?token=...  book status + active job + per-chapter audio status

The worker may be another process, so updates are read from the database
(cheap indexed reads every 0.5s) and pushed only when something changed.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.errors import StudioError
from app.db.session import SessionLocal, session_scope
from app.models import Book, Chapter, GenerationJob, JobStatus, JobType
from app.schemas.common import serialize_job
from app.services.auth import authenticate

router = APIRouter()
POLL = 0.5
PIPELINE_TYPES = [JobType.ANALYZE, JobType.GENERATE_BOOK, JobType.GENERATE_CHAPTER]


def _auth(token: str | None) -> str | None:
    if not token:
        return None
    db = SessionLocal()
    try:
        return authenticate(db, token).id
    except StudioError:
        return None
    finally:
        db.close()


async def _stream(ws: WebSocket, snapshot) -> None:
    last = None
    idle = 0
    try:
        while True:
            data = await asyncio.to_thread(snapshot)
            if data is None:
                await ws.send_json({"type": "error", "message": "Not found"})
                break
            encoded = json.dumps(data, sort_keys=True, default=str)
            if encoded != last:
                await ws.send_text(encoded)
                last = encoded
                idle = 0
            else:
                idle += 1
            # Slow down once nothing is running.
            finished = data.get("finished")
            await asyncio.sleep(POLL if not finished else 3.0)
            if finished and idle > 200:
                break
    except (WebSocketDisconnect, RuntimeError):
        return
    finally:
        try:
            await ws.close()
        except (WebSocketDisconnect, RuntimeError):
            pass  # the tab already went away


@router.websocket("/ws/jobs/{job_id}")
async def job_socket(ws: WebSocket, job_id: str, token: str | None = None):
    user_id = await asyncio.to_thread(_auth, token)
    await ws.accept()
    if not user_id:
        await ws.send_json({"type": "error", "message": "Unauthorized"})
        await ws.close(code=4401)
        return

    def snapshot():
        with session_scope(write=False) as db:
            job = db.get(GenerationJob, job_id)
            if job is None or job.user_id != user_id:
                return None
            data = serialize_job(job)
            return {"type": "job", "job": data, "finished": job.status in JobStatus.FINISHED}

    await _stream(ws, snapshot)


@router.websocket("/ws/books/{book_id}")
async def book_socket(ws: WebSocket, book_id: str, token: str | None = None):
    user_id = await asyncio.to_thread(_auth, token)
    await ws.accept()
    if not user_id:
        await ws.send_json({"type": "error", "message": "Unauthorized"})
        await ws.close(code=4401)
        return

    def snapshot():
        with session_scope(write=False) as db:
            book = db.get(Book, book_id)
            if book is None or book.owner_id != user_id:
                return None
            # The book's pipeline job (analysis / generation): the active one, else the most recent.
            pipeline = select(GenerationJob).where(GenerationJob.book_id == book_id, GenerationJob.type.in_(PIPELINE_TYPES))
            job = db.scalars(pipeline.where(GenerationJob.status.in_(list(JobStatus.ACTIVE))).order_by(GenerationJob.created_at.desc())).first()
            if job is None:
                job = db.scalars(pipeline.order_by(GenerationJob.created_at.desc())).first()
            chapters = db.execute(
                select(Chapter.id, Chapter.position, Chapter.title, Chapter.audio_status, Chapter.audio_progress, Chapter.duration, Chapter.audio_error, Chapter.include_in_audio)
                .where(Chapter.book_id == book_id)
                .order_by(Chapter.position)
            ).all()
            return {
                "type": "book",
                "book": {"id": book.id, "status": book.status, "title": book.title, "error": book.error, "total_duration": book.total_duration},
                "job": serialize_job(job),
                "chapters": [
                    {"id": c[0], "position": c[1], "title": c[2], "audio_status": c[3], "audio_progress": c[4], "duration": c[5], "audio_error": c[6], "include_in_audio": c[7]}
                    for c in chapters
                ],
                "finished": job is None or job.status in JobStatus.FINISHED or job.status == JobStatus.PAUSED,
            }

    await _stream(ws, snapshot)
