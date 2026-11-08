from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, rate_limit
from app.core.config import get_settings
from app.core.errors import ValidationFailed
from app.core.logging import get_logger
from app.core.security import safe_filename, slugify
from app.db.session import get_db
from app.models import (
    AudioAsset,
    Book,
    BookStatus,
    Chapter,
    ChapterStatus,
    GenerationJob,
    JobStatus,
    JobType,
    ListeningProgress,
    User,
)
from app.providers.storage import get_storage
from app.schemas.common import AnalyzeIn, BookUpdateIn, GenerateIn, media_url, serialize_book, serialize_job
from app.services import books as book_service
from app.services import export, generation, ingest, narration_settings
from app.services.books import get_book_for, sort_key
from app.services.handoff import device_mode
from app.workers import queue

router = APIRouter(prefix="/api/books", tags=["books"])
log = get_logger(__name__)


def active_job(db: Session, book_id: str, types: set[str] | None = None) -> GenerationJob | None:
    stmt = select(GenerationJob).where(GenerationJob.book_id == book_id, GenerationJob.status.in_(list(JobStatus.ACTIVE)))
    if types:
        stmt = stmt.where(GenerationJob.type.in_(types))
    return db.scalars(stmt.order_by(GenerationJob.created_at.desc())).first()


def latest_job(db: Session, book_id: str) -> GenerationJob | None:
    return db.scalars(
        select(GenerationJob)
        .where(GenerationJob.book_id == book_id, GenerationJob.type.in_([JobType.ANALYZE, JobType.GENERATE_BOOK, JobType.GENERATE_CHAPTER]))
        .order_by(GenerationJob.created_at.desc())
    ).first()


def chapter_counts(db: Session, book_ids: list[str]) -> dict[str, dict]:
    rows = db.execute(
        select(
            Chapter.book_id,
            func.count(Chapter.id),
            func.sum(case((Chapter.include_in_audio.is_(True), 1), else_=0)),
            func.sum(case((Chapter.audio_status == ChapterStatus.DONE, 1), else_=0)),
        )
        .where(Chapter.book_id.in_(book_ids))
        .group_by(Chapter.book_id)
    ).all()
    return {bid: {"chapters": n, "narrated": int(narrated or 0), "with_audio": int(done or 0)} for bid, n, narrated, done in rows}


def book_payload(db: Session, book: Book, user: User) -> dict:
    progress = db.scalar(select(ListeningProgress).where(ListeningProgress.user_id == user.id, ListeningProgress.book_id == book.id))
    job = active_job(db, book.id) or latest_job(db, book.id)
    return serialize_book(
        book,
        progress=progress,
        job=job,
        counts=chapter_counts(db, [book.id]).get(book.id),
        narration=narration_settings.resolve(book.narration, book.language),
    )


@router.post("", status_code=201, dependencies=[Depends(rate_limit("upload", get_settings().upload_rate_limit_per_hour, 3600))])
def upload_book(
    file: UploadFile = File(...),
    auto_analyze: bool = Form(True),
    language: str = Form("auto"),
    ocr_mode: str = Form("auto"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    if ocr_mode not in ("auto", "force", "off"):
        raise ValidationFailed("ocr_mode must be auto, force or off.")
    book = ingest.create_book_from_upload(db, user, file.file, file.filename or "upload")
    job = None
    if auto_analyze:
        job = ingest.enqueue_analysis(db, book, user.id, {"ocr_mode": ocr_mode, "languages": [] if language == "auto" else [language[:8]]})
    db.refresh(book)
    return {"book": book_payload(db, book, user), "job": serialize_job(job)}


@router.get("")
def list_books(
    q: str | None = Query(None, max_length=200),
    status: str | None = Query(None, pattern="^(all|in_progress|completed|processing|ready|failed|uploaded|review)$"),
    sort: str = Query("recent", pattern="^(recent|title|author|progress|listened)$"),
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Book).where(Book.owner_id == user.id)
    progress_join = select(ListeningProgress).where(ListeningProgress.user_id == user.id).subquery()
    stmt = stmt.outerjoin(progress_join, progress_join.c.book_id == Book.id)
    if q:
        like = f"%{q.strip()}%"
        chapter_match = select(Chapter.book_id).where(Chapter.title.ilike(like))
        stmt = stmt.where(or_(Book.title.ilike(like), Book.author.ilike(like), Book.id.in_(chapter_match)))
    if status == "processing":
        stmt = stmt.where(Book.status.in_(list(BookStatus.PROCESSING)))
    elif status in ("ready", "failed", "uploaded", "review"):
        stmt = stmt.where(Book.status == status)
    elif status == "in_progress":
        stmt = stmt.where(progress_join.c.id.is_not(None), progress_join.c.completed.is_(False))
    elif status == "completed":
        stmt = stmt.where(progress_join.c.completed.is_(True))
    order = {
        "recent": [Book.created_at.desc()],
        "title": [Book.sort_title.asc()],
        "author": [func.lower(func.coalesce(Book.author, "~")).asc(), Book.sort_title],
        "progress": [func.coalesce(progress_join.c.book_position_seconds / func.nullif(Book.total_duration, 0), -1).desc()],
        "listened": [func.coalesce(progress_join.c.updated_at, Book.created_at).desc()],
    }[sort]
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    books = list(db.scalars(stmt.order_by(*order).limit(limit).offset(offset)))
    ids = [b.id for b in books]
    progress = {p.book_id: p for p in db.scalars(select(ListeningProgress).where(ListeningProgress.user_id == user.id, ListeningProgress.book_id.in_(ids)))}
    jobs: dict[str, GenerationJob] = {}
    for j in db.scalars(select(GenerationJob).where(GenerationJob.book_id.in_(ids), GenerationJob.status.in_(list(JobStatus.ACTIVE))).order_by(GenerationJob.created_at)):
        jobs[j.book_id] = j
    counts = chapter_counts(db, ids)
    return {
        "items": [serialize_book(b, progress=progress.get(b.id), job=jobs.get(b.id), counts=counts.get(b.id)) for b in books],
        "total": total,
    }


@router.get("/continue")
def continue_listening(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(ListeningProgress, Book)
        .join(Book, Book.id == ListeningProgress.book_id)
        .where(ListeningProgress.user_id == user.id, ListeningProgress.completed.is_(False), Book.status == BookStatus.READY)
        .order_by(ListeningProgress.updated_at.desc())
        .limit(6)
    ).all()
    items = []
    for p, b in rows:
        chapter = db.get(Chapter, p.chapter_id) if p.chapter_id else None
        item = serialize_book(b, progress=p)
        item["current_chapter"] = {"id": chapter.id, "title": chapter.title, "duration": chapter.duration} if chapter else None
        items.append(item)
    return {"items": items}


@router.get("/{book_id}")
def get_book(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return book_payload(db, get_book_for(db, book_id, user), user)


@router.patch("/{book_id}")
def update_book(book_id: str, body: BookUpdateIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    book = get_book_for(db, book_id, user)
    data = body.model_dump(exclude_unset=True, exclude={"narration"})
    for field, value in data.items():
        setattr(book, field, value.strip() if isinstance(value, str) else value)
    if {"title", "author", "subtitle"} & set(data):
        book.metadata_locked = True
        book.sort_title = sort_key(book.title)
        if book.cover_source == "generated":
            ingest.regenerate_cover(db, book)
    if body.narration is not None:
        changes = body.narration.model_dump(exclude_unset=True)
        narration = {**(book.narration or {}), **changes}
        if "provider" in changes and "voice_id" not in changes:
            narration["voice_id"] = narration_settings.default_voice_for(changes["provider"], book.language)
        book.narration = narration
    db.commit()
    db.refresh(book)
    return book_payload(db, book, user)


@router.delete("/{book_id}", status_code=204)
def delete_book(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    book = get_book_for(db, book_id, user)
    for job in db.scalars(select(GenerationJob).where(GenerationJob.book_id == book.id, GenerationJob.status.in_(list(JobStatus.ACTIVE)))):
        job.status = JobStatus.CANCELLED
    db.flush()
    book_service.delete_book(db, book)
    db.commit()
    log.info("book.deleted", book_id=book_id)


@router.delete("/{book_id}/audio")
def delete_audio(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    book = get_book_for(db, book_id, user)
    if active_job(db, book.id, {JobType.GENERATE_BOOK, JobType.GENERATE_CHAPTER}):
        raise ValidationFailed("Stop the running generation before deleting audio.", code="job_in_progress")
    removed = book_service.delete_book_audio(db, book)
    if book.status == BookStatus.READY:
        book.status = BookStatus.REVIEW
    db.commit()
    return {"removed_files": removed}


@router.delete("/{book_id}/original")
def delete_original(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    book = get_book_for(db, book_id, user)
    removed = book_service.delete_original(db, book)
    db.commit()
    return {"removed": removed}


@router.post("/{book_id}/analyze")
def analyze_book(book_id: str, body: AnalyzeIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    book = get_book_for(db, book_id, user)
    job = ingest.enqueue_analysis(db, book, user.id, body.model_dump())
    return serialize_job(job)


@router.post("/{book_id}/cover")
async def upload_cover(book_id: str, file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    book = get_book_for(db, book_id, user)
    data = await file.read(15 * 1024 * 1024 + 1)
    if len(data) > 15 * 1024 * 1024:
        raise ValidationFailed("Cover images must be under 15 MB.")
    ingest.set_cover(db, book, data)
    db.commit()
    db.refresh(book)
    return book_payload(db, book, user)


@router.post("/{book_id}/cover/generate")
def generate_cover(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    book = get_book_for(db, book_id, user)
    ingest.regenerate_cover(db, book)
    db.commit()
    db.refresh(book)
    return book_payload(db, book, user)


# --------------------------------------------------------------------------- generation


@router.get("/{book_id}/estimate")
def estimate(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    book = get_book_for(db, book_id, user)
    settings = narration_settings.resolve(book.narration, book.language)
    return generation.estimate(book, settings)


@router.post("/{book_id}/generate")
def generate(book_id: str, body: GenerateIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    book = get_book_for(db, book_id, user)
    if book.status in (BookStatus.UPLOADED, BookStatus.ANALYZING):
        raise ValidationFailed("Analyze the book before generating audio.", code="not_analyzed")
    included = [c for c in book.chapters if c.include_in_audio]
    if not included:
        raise ValidationFailed("No chapters are selected for narration. Include at least one chapter in the editor.", code="no_chapters")
    paused = active_job(db, book.id, {JobType.GENERATE_BOOK})
    if paused and paused.status == JobStatus.PAUSED:
        paused.status = JobStatus.CANCELLED
        paused.completed_at = paused.updated_at
        db.commit()
    job = queue.enqueue(
        db,
        type=JobType.GENERATE_BOOK,
        user_id=user.id,
        book_id=book.id,
        payload=body.model_dump(),
        stages=[
            {"key": "prepare", "label": "Voice being created", "status": "active"},
            {"key": "chapters", "label": "Audiobook processing", "status": "pending"},
            {"key": "build", "label": "Ready to listen", "status": "pending"},
        ],
        # Once the analysis is saved (review/ready), a still-finishing analysis job
        # (queuing cast detection, telemetry) must not block pressing Generate.
        exclusive_types={JobType.GENERATE_BOOK, JobType.GENERATE_CHAPTER}
        | (set() if book.status in (BookStatus.REVIEW, BookStatus.READY) else {JobType.ANALYZE}),
    )
    book.status = BookStatus.GENERATING
    for c in included:
        if not body.chapter_ids or c.id in body.chapter_ids:
            if c.audio_status != ChapterStatus.DONE or body.force:
                c.audio_status = ChapterStatus.QUEUED
    db.commit()
    return serialize_job(job)


# --------------------------------------------------------------------------- downloads


@router.get("/{book_id}/downloads")
def downloads(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    book = get_book_for(db, book_id, user)
    storage = get_storage()
    base = slugify(book.title, 60)
    items = []
    # Device delivery: audio lives on the listener's device (saved there as one file), so
    # the server offers no audiobook builds -- they'd need audio it no longer keeps.
    device = device_mode()
    full = db.scalar(select(AudioAsset).where(AudioAsset.book_id == book.id, AudioAsset.kind == "full"))
    if full and storage.exists(full.storage_key):
        items.append({"kind": "full", "label": "Complete audiobook", "size": full.size_bytes, "duration": full.duration, "url": media_url(full.storage_key) + f"&download={base}.{full.format}"})
    elif not device and book.status == BookStatus.READY and all(c.audio_status == ChapterStatus.DONE for c in book.chapters if c.include_in_audio):
        # Joined on demand when downloaded (seconds), instead of storing a second copy.
        items.append({"kind": "full", "label": "Complete audiobook", "duration": book.total_duration, "url": f"/api/books/{book.id}/export/full"})
    for c in book.chapters:
        asset = db.scalar(select(AudioAsset).where(AudioAsset.chapter_id == c.id, AudioAsset.kind == "chapter"))
        if asset and storage.exists(asset.storage_key):
            name = asset.storage_key.rsplit("/", 1)[-1]
            items.append({"kind": "chapter", "chapter_id": c.id, "label": c.title, "size": asset.size_bytes, "duration": asset.duration, "url": media_url(asset.storage_key) + f"&download={name}"})
    m4b = db.scalar(select(AudioAsset).where(AudioAsset.book_id == book.id, AudioAsset.kind == "m4b"))
    if m4b and storage.exists(m4b.storage_key):
        items.append({"kind": "m4b", "label": "M4B audiobook (chapters, cover)", "size": m4b.size_bytes, "duration": m4b.duration, "url": media_url(m4b.storage_key) + f"&download={base}.m4b"})
    elif not device and any(i["kind"] == "chapter" for i in items):
        items.append({"kind": "m4b", "label": "M4B audiobook (chapters, cover)", "url": None, "buildable": True})
    extracted = book_service.get_file(book, "extracted_text")
    if extracted:
        items.append({"kind": "extracted_text", "label": "Original extracted text", "size": extracted.size_bytes, "url": media_url(extracted.storage_key) + f"&download={base}-extracted.txt"})
    original = book_service.get_file(book, "original")
    if original:
        items.append({"kind": "original", "label": f"Original file ({original.filename})", "size": original.size_bytes, "url": media_url(original.storage_key) + f"&download={safe_filename(original.filename)}"})
    items.append({"kind": "processed_text", "label": "Processed text (as edited)", "url": f"/api/books/{book.id}/export/text"})
    items.append({"kind": "narration_text", "label": "Narration script (as spoken)", "url": f"/api/books/{book.id}/export/text?narration=true"})
    items.append({"kind": "zip", "label": "ZIP package (cover, metadata, text)" if device else "ZIP package (audio, cover, metadata, text)", "url": f"/api/books/{book.id}/export/zip"})
    return {"items": items}


@router.post("/classify")
def classify_library(everything: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Classify the library by genre, author and series (unclassified books, or all)."""
    job = queue.enqueue(db, type="classify", user_id=user.id, book_id=None, payload={"all": everything}, priority=-4)
    return serialize_job(job)


@router.post("/{book_id}/info", dependencies=[Depends(rate_limit("book_info", 20, 3600))])
def refresh_book_info(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Re-detect one book's genre and 'about' summary, and refresh its reader ratings."""
    book = get_book_for(db, book_id, user)
    running = db.scalar(select(GenerationJob).where(GenerationJob.book_id == book.id, GenerationJob.type == "classify", GenerationJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING])))
    job = running or queue.enqueue(db, type="classify", user_id=user.id, book_id=book.id, payload={"book_ids": [book.id]}, priority=2)
    return serialize_job(job)


@router.post("/{book_id}/export/m4b")
def build_m4b(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    book = get_book_for(db, book_id, user)
    if device_mode():
        raise ValidationFailed("Audiobooks are kept on your device. Save one from the book page instead.", code="device_delivery")
    job = queue.enqueue(db, type="export_m4b", user_id=user.id, book_id=book.id, priority=5, exclusive_types={"export_m4b"})
    return serialize_job(job)


@router.get("/{book_id}/export/text")
def export_text(book_id: str, narration: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from fastapi.responses import Response

    book = get_book_for(db, book_id, user)
    text = export.processed_text(db, book, narration_ready=narration)
    name = f"{slugify(book.title, 60)}-{'narration' if narration else 'processed'}.txt"
    return Response(text.encode("utf-8"), media_type="text/plain; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/{book_id}/export/full")
def export_full(book_id: str, background: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if device_mode():
        raise ValidationFailed("Audiobooks are kept on your device. Save one from the book page instead.", code="device_delivery")
    """The complete audiobook as one file with chapter markers, joined on request."""
    import shutil
    import tempfile

    book = get_book_for(db, book_id, user)
    settings = narration_settings.resolve(book.narration, book.language)
    work = Path(tempfile.mkdtemp(dir=generation.tmp_dir(), prefix="full-dl-"))
    out = work / "full.mp3"
    try:
        built = generation.assemble_full_audiobook(book.id, settings, out)
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise
    if built is None:
        shutil.rmtree(work, ignore_errors=True)
        raise ValidationFailed("Every narrated chapter needs audio before the complete audiobook can be downloaded.", code="audiobook_incomplete")
    background.add_task(lambda: shutil.rmtree(work, ignore_errors=True))
    return FileResponse(out, media_type="audio/mpeg", filename=f"{slugify(book.title, 60)}.mp3")


@router.get("/{book_id}/export/zip")
def export_zip(book_id: str, background: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = get_book_for(db, book_id, user)
    path = export.build_zip(db, book)
    background.add_task(lambda: path.unlink(missing_ok=True))
    return FileResponse(path, media_type="application/zip", filename=f"{slugify(book.title, 60)}.zip")
