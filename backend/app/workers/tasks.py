"""Job type -> handler mapping, plus failure hooks that update book state."""

from __future__ import annotations

from app.core.errors import StudioError
from app.db.session import session_scope
from app.workers import queue
from app.models import Book, BookStatus, Chapter, ChapterStatus, JobType


def _generate_chapter(ctx) -> dict:
    ctx.payload = {**ctx.payload, "chapter_ids": [ctx.chapter_id]}
    from app.services.generation import generate_book

    return generate_book(ctx)


def _analyze(ctx):
    from app.services.ingest import run_analysis

    return run_analysis(ctx)


def _generate_book(ctx):
    from app.services.generation import generate_book

    return generate_book(ctx)


def _index(ctx):
    from app.services.rag import index_book

    return index_book(ctx)


def _cast(ctx):
    from app.services.cast import analyze_cast

    return analyze_cast(ctx)


def _insights(ctx):
    from app.services.insights import generate_insights

    return generate_insights(ctx)


def _ask(ctx):
    from app.services.rag import ask

    ctx.update(stage="thinking", message="Reading the relevant passages...")
    answer = ask(ctx.user_id, ctx.book_id, ctx.payload["question"], bool(ctx.payload.get("spoiler_safe")))
    return {"message_id": answer["id"], "mode": answer["mode"]}


def _export_m4b(ctx):
    from app.services.generation import export_m4b

    return export_m4b(ctx)


def _install_voice(ctx):
    from app.services.voices import install_piper_voice

    return install_piper_voice(ctx)


def _classify(ctx):
    """Tidy title/author and add genres + series for one book, or a list of books."""
    from sqlalchemy import select

    from app.services.classify import classify_books

    ids = ctx.payload.get("book_ids")
    if not ids:
        with session_scope(write=False) as db:
            q = select(Book.id).where(Book.owner_id == ctx.user_id)
            if not ctx.payload.get("all"):
                q = q.where(Book.classified_at.is_(None))
            ids = list(db.scalars(q))
    ctx.update(message=f"Classifying {len(ids)} book(s) by genre, author and series")
    done = classify_books(ids)
    ctx.update(progress=100, message=f"Classified {len(done)} book(s)")
    return {"classified": len(done)}


HANDLERS = {
    JobType.ANALYZE: _analyze,
    JobType.GENERATE_BOOK: _generate_book,
    JobType.GENERATE_CHAPTER: _generate_chapter,
    JobType.INDEX_BOOK: _index,
    JobType.CAST_ANALYSIS: _cast,
    JobType.INSIGHTS: _insights,
    JobType.ASK: _ask,
    "install_voice": _install_voice,
    "export_m4b": _export_m4b,
    "classify": _classify,
}


def on_job_failed(ctx, exc: BaseException) -> None:
    """Final (non-retried) failure: reflect it on the book so the UI can explain it."""
    if not ctx.book_id:
        return
    error = queue.describe_error(exc)
    with session_scope() as db:
        book = db.get(Book, ctx.book_id)
        if book is None:
            return
        if ctx.type == JobType.ANALYZE:
            book.status = BookStatus.FAILED
            book.error = {**error, "stage": "analysis"}
        elif ctx.type in (JobType.GENERATE_BOOK, JobType.GENERATE_CHAPTER):
            for c in book.chapters:
                if c.audio_status in (ChapterStatus.QUEUED, ChapterStatus.GENERATING):
                    c.audio_status = ChapterStatus.PENDING
            has_audio = any(c.audio_status == ChapterStatus.DONE for c in book.chapters)
            book.status = BookStatus.READY if has_audio else BookStatus.REVIEW
            book.error = {**error, "stage": "generation"}
