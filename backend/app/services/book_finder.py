"""Book finder for the search bar: a title, author, character or topic goes in;
the matching published book(s), what they're about, real reader ratings, and
recommendations come out.

The AI model identifies books and writes the descriptions; ratings and covers come
from Open Library (never from the model). Answers are cached in memory for a day.
"""

from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.core.errors import ProviderError, ProviderUnavailableError
from app.core.logging import get_logger
from app.providers.llm import ChatMessage, get_llm_provider, parse_json
from app.services import ratings

log = get_logger(__name__)

SYSTEM = (
    "You are a well-read librarian helping a reader find books. The reader typed a search: it may be a book title "
    "(possibly misspelled or partial), an author, a character's name, a series, or a topic/mood. Work out what they "
    "mean and answer with real, published books only; never invent a book, author or character.\n"
    "- matches: up to 3 books that ARE what the reader is looking for. For a title, the book itself (and, for a "
    "series, its first book). For a character, the book(s) that character appears in, and say who the character is "
    "in match_note. For an author, their best-known books. For a topic, the best books on it. If nothing real "
    "matches, return an empty list.\n"
    "- recommendations: 4-6 other real books a reader of the matches would enjoy, each with a one-sentence why. Do "
    "not repeat the matches.\n"
    "- about: spoiler-free, 2-3 sentences, like a back cover.\n"
    "- matched_on: one of title, author, character, series, topic.\n"
    "- interpretation: one short sentence saying how you read the search (e.g. 'Theo Faber is the narrator of The "
    "Silent Patient')."
)

_BOOK = {
    "title": {"type": "string"},
    "author": {"type": "string"},
    "year": {"type": ["integer", "null"]},
    "genres": {"type": "array", "items": {"type": "string"}},
    "about": {"type": "string"},
}
SCHEMA = {
    "type": "object",
    "properties": {
        "interpretation": {"type": "string"},
        "matches": {
            "type": "array",
            "items": {"type": "object", "properties": {**_BOOK, "matched_on": {"type": "string"}, "match_note": {"type": "string"}}, "required": [*_BOOK, "matched_on", "match_note"]},
        },
        "recommendations": {
            "type": "array",
            "items": {"type": "object", "properties": {**_BOOK, "why": {"type": "string"}}, "required": [*_BOOK, "why"]},
        },
    },
    "required": ["interpretation", "matches", "recommendations"],
}

TTL = 24 * 3600
_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="ratings")


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip().lower())


def _clean_book(item: dict, extra: tuple[str, ...]) -> dict | None:
    title = str(item.get("title") or "").strip()
    if not title:
        return None
    out = {
        "title": title[:300],
        "author": str(item.get("author") or "").strip()[:200] or None,
        "year": item.get("year") if isinstance(item.get("year"), int) else None,
        "genres": [g.strip() for g in item.get("genres") or [] if isinstance(g, str) and g.strip()][:3],
        "about": str(item.get("about") or "").strip()[:1200],
    }
    for k in extra:
        out[k] = str(item.get(k) or "").strip()[:400] or None
    return out


def _with_ratings(books: list[dict]) -> list[dict]:
    found = list(_pool.map(lambda b: ratings.lookup(b["title"], b["author"]), books))
    for book, r in zip(books, found):
        book["ratings"] = {k: r[k] for k in ("average", "count", "source", "url")} if r and r.get("count") else None
        book["cover_url"] = r.get("cover_url") if r else None
        book["year"] = book["year"] or (r.get("year") if r else None)
    return books


def find(query: str) -> dict:
    q = _norm(query)[:200]
    with _lock:
        hit = _cache.get(q)
        if hit and time.time() - hit[0] < TTL:
            return hit[1]
    llm = get_llm_provider()
    if llm is None:
        raise ProviderUnavailableError("llm", "The book finder needs an AI model. Set LLM_PROVIDER (or GEMINI_API_KEY) in the backend .env.", retryable=False)
    ok, reason = llm.is_available()
    if not ok:
        raise ProviderUnavailableError(llm.name, reason or "The AI model is unavailable.", retryable=False)
    try:
        messages = [ChatMessage("user", f"Search: {query.strip()[:200]}")]
        if llm.name == "gemini":  # interactive: prefer the fast models
            answer = parse_json(llm.complete(SYSTEM, messages, max_tokens=3000, json_schema=SCHEMA, prefer_fast=True))
        else:
            answer = llm.complete_json(SYSTEM, messages, SCHEMA, max_tokens=3000)
    except ProviderError:
        raise
    except Exception as exc:  # malformed JSON from the model
        log.warning("book_finder.bad_answer", error=type(exc).__name__)
        raise ProviderUnavailableError(llm.name, "The AI model gave an answer I couldn't read. Try again.", retryable=True) from exc
    matches = [b for b in (_clean_book(m, ("matched_on", "match_note")) for m in answer.get("matches") or []) if b][:3]
    seen = {_norm(m["title"]) for m in matches}
    recs = [b for b in (_clean_book(r, ("why",)) for r in answer.get("recommendations") or []) if b and _norm(b["title"]) not in seen][:6]
    result = {
        "query": query.strip(),
        "interpretation": str(answer.get("interpretation") or "").strip()[:300] or None,
        "matches": _with_ratings(matches),
        "recommendations": _with_ratings(recs),
        "model": f"{llm.name}:{llm.model}",
    }
    with _lock:
        if len(_cache) > 300:
            _cache.clear()
        _cache[q] = (time.time(), result)
    return result
