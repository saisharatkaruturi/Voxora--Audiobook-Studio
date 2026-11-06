"""Tidy a book's catalogue data: clean title, one canonical author spelling, genres,
and series with reading order.

File names and PDF metadata are messy ("Hoover, Colleen, author", "001 - The Graham
Effect", "... Durjoy Datt"). An LLM that knows published books reads the title,
author, file name and the opening text and returns the canonical record. Anything
the user edited by hand (metadata_locked) keeps its title and author.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.session import session_scope
from app.models import Book, BookFile, Chapter, Paragraph

log = get_logger(__name__)

SYSTEM = (
    "You are a meticulous librarian cataloguing books for an audiobook library. Identify the real, published book. "
    "Return its canonical English title (no series name, no 'A Novel', no author name, no file-name junk; for a "
    "translated edition give the original English title), the author's name as normally printed on covers "
    "('Colleen Hoover', not 'Hoover, Colleen'), one primary genre, 1-4 genres from most to least specific, and the "
    "series it belongs to with its number in reading order (use decimals for novellas, e.g. 2.5). If the book is a "
    "standalone, series and series_index are null. Only name a series you are confident about. Use common genre "
    "labels such as: Romance, Contemporary Romance, New Adult Romance, Sports Romance, Dark Romance, Romantic "
    "Suspense, Psychological Thriller, Young Adult, Indian Fiction, Literary Fiction."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "author": {"type": "string"},
        "genre": {"type": "string"},
        "genres": {"type": "array", "items": {"type": "string"}},
        "series": {"type": ["string", "null"]},
        "series_index": {"type": ["number", "null"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["title", "author", "genre", "genres", "series", "series_index", "confidence"],
}


def _opening_text(db, book: Book, limit: int = 2500) -> str:
    out, size = [], 0
    chapters = db.scalars(select(Chapter).where(Chapter.book_id == book.id).order_by(Chapter.position).limit(6)).all()
    for c in chapters:
        for p in db.scalars(select(Paragraph).where(Paragraph.chapter_id == c.id).order_by(Paragraph.position).limit(40)):
            out.append(p.text)
            size += len(p.text)
            if size > limit:
                return "\n".join(out)[:limit]
    return "\n".join(out)[:limit]


def _describe(db, book: Book, snippet: int) -> str:
    original = db.scalar(select(BookFile.filename).where(BookFile.book_id == book.id, BookFile.kind == "original"))
    lines = [
        f"Current title: {book.title}",
        f"Current author: {book.author or 'unknown'}",
        f"File name: {original or 'unknown'}",
        f"Detected language: {book.language}; pages {book.page_count}; words {book.word_count}",
        f"Opening text: {_opening_text(db, book, snippet)}",
    ]
    return "\n".join(lines)


def _llm():
    from app.providers.llm import get_llm_provider

    llm = get_llm_provider()
    return llm if llm is not None and llm.is_available()[0] else None


def _ask(llm, prompt: str, schema: dict, max_tokens: int) -> dict:
    """complete_json with patience for free-tier rate limits."""
    import time

    from app.core.errors import ProviderError
    from app.providers.llm.base import ChatMessage

    for attempt in range(6):
        try:
            return llm.complete_json(SYSTEM, [ChatMessage("user", prompt)], schema, max_tokens=max_tokens)
        except ProviderError as exc:  # quota / overloaded models: wait and try again
            if not exc.retryable or attempt == 5:
                raise
            time.sleep(20 * (attempt + 1))
    raise AssertionError("unreachable")


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _tidied_title(new: str, old: str, filename: str | None) -> str | None:
    """Accept a cleaned-up title only if every word in it already appears in the old
    title or the file name: junk can be dropped ("ARC", "001 -", the author's name),
    but words can't be invented and editions aren't renamed or translated."""
    source = _squash(old) + _squash(filename or "")
    words = [w for w in re.split(r"[\s:,.!?()\-]+", new or "") if _squash(w)]
    if not words or not all(_squash(w) in source for w in words):
        return None
    return new.strip()[:500]


def _apply(book_id: str, result: dict) -> dict | None:
    genres = [g.strip() for g in (result.get("genres") or []) if isinstance(g, str) and g.strip()][:4]
    series = (result.get("series") or "").strip() or None
    index = result.get("series_index")
    with session_scope() as db:
        book = db.get(Book, book_id)
        if book is None:
            return None
        if not book.metadata_locked:  # the user's own edits win
            filename = db.scalar(select(BookFile.filename).where(BookFile.book_id == book.id, BookFile.kind == "original"))
            title = _tidied_title(result.get("title") or "", book.title, filename)
            if title and title != book.title:
                from app.services.books import sort_key

                book.title = title
                book.sort_title = sort_key(book.title)
            if (result.get("author") or "").strip():
                book.author = result["author"].strip()[:300]
        book.genre = (result.get("genre") or "").strip()[:120] or (genres[0] if genres else None)
        book.genres = genres or ([book.genre] if book.genre else None)
        book.series = series[:300] if series else None
        book.series_index = float(index) if series and isinstance(index, (int, float)) else None
        book.classified_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        saved = {"title": book.title, "author": book.author, "genre": book.genre, "genres": book.genres, "series": book.series, "series_index": book.series_index}
    log.info("book.classified", book_id=book_id, confidence=result.get("confidence"), **saved)
    return saved


def classify_book(book_id: str, llm=None) -> dict | None:
    """Classify one book (new uploads); None when no LLM is configured."""
    llm = llm or _llm()
    if llm is None:
        return None
    with session_scope(write=False) as db:
        book = db.get(Book, book_id)
        if book is None:
            return None
        prompt = _describe(db, book, 2500)
    return _apply(book_id, _ask(llm, prompt, SCHEMA, 800))


BATCH_SCHEMA = {
    "type": "object",
    "properties": {"books": {"type": "array", "items": {**SCHEMA, "properties": {"id": {"type": "string"}, **SCHEMA["properties"]}, "required": ["id", *SCHEMA["required"]]}}},
    "required": ["books"],
}


def classify_books(book_ids: list[str], llm=None, batch: int = 60) -> dict[str, dict]:
    """Classify many books in few requests (seeing a whole series at once also keeps
    its numbering consistent). Returns {book_id: saved fields}."""
    llm = llm or _llm()
    if llm is None:
        return {}
    done: dict[str, dict] = {}
    for start in range(0, len(book_ids), batch):
        ids = book_ids[start : start + batch]
        with session_scope(write=False) as db:
            parts = [f"### id: {bid}\n{_describe(db, db.get(Book, bid), 350)}" for bid in ids if db.get(Book, bid)]
        prompt = "Catalogue each of these books. Answer with one entry per id.\n\n" + "\n\n".join(parts)
        answer = _ask(llm, prompt, BATCH_SCHEMA, 700 * len(ids))
        for item in answer.get("books") or []:
            if item.get("id") in ids:
                saved = _apply(item["id"], item)
                if saved:
                    done[item["id"]] = saved
    _fix_series_numbers(llm, done)
    return done


SERIES_SCHEMA = {
    "type": "object",
    "properties": {"books": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}, "series_index": {"type": ["number", "null"]}}, "required": ["id", "series_index"]}}},
    "required": ["books"],
}


def _fix_series_numbers(llm, done: dict[str, dict]) -> None:
    """If two books got the same number in one series, ask again about just that series."""
    from collections import defaultdict

    by_series: dict[str, list[str]] = defaultdict(list)
    for bid, v in done.items():
        if v.get("series"):
            by_series[v["series"]].append(bid)
    for series, ids in by_series.items():
        numbers = [done[i].get("series_index") for i in ids]
        if len(ids) < 2 or len(set(numbers)) == len(numbers):
            continue
        listing = "\n".join(f"- id {i}: {done[i]['title']} by {done[i]['author']}" for i in ids)
        prompt = (
            f"These books were all placed in the series '{series}'. Give each its number in the series' official reading "
            f"order (decimals for novellas). If a book is not actually part of this series, give null.\n{listing}"
        )
        answer = _ask(llm, prompt, SERIES_SCHEMA, 400)
        with session_scope() as db:
            for item in answer.get("books") or []:
                if item.get("id") in ids:
                    book = db.get(Book, item["id"])
                    idx = item.get("series_index")
                    if isinstance(idx, (int, float)):
                        book.series_index = float(idx)
                    else:
                        book.series, book.series_index = None, None
                    done[item["id"]].update(series=book.series, series_index=book.series_index)
