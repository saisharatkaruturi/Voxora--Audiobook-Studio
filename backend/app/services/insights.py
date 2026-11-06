"""Book insights: summaries, characters, events, themes, glossary.

Map-reduce over chapters: each chapter is summarized (long chapters in parts),
then book-level insights are derived from the chapter summaries. Results are
stored separately and never modify the book's text.
"""

from __future__ import annotations

from sqlalchemy import delete, select

from app.core.errors import ProviderUnavailableError, StudioError
from app.db.session import session_scope
from app.models import Book, BookInsight, Paragraph
from app.providers.llm import ChatMessage, get_llm_provider

KINDS = ["chapter_summary", "short_summary", "detailed_summary", "characters", "events", "themes", "glossary"]
MAX_CHARS = 14000

SYSTEM = (
    "You are a careful literary assistant. Work only from the text you are given. Do not add facts, "
    "events, or characters that are not in the text. Write in the language of the text."
)

SCHEMAS = {
    "characters": {"type": "object", "properties": {"characters": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "description": {"type": "string"}, "role": {"type": "string"}}}}}},
    "events": {"type": "object", "properties": {"events": {"type": "array", "items": {"type": "object", "properties": {"chapter": {"type": "string"}, "event": {"type": "string"}}}}}},
    "themes": {"type": "object", "properties": {"themes": {"type": "array", "items": {"type": "object", "properties": {"theme": {"type": "string"}, "explanation": {"type": "string"}}}}}},
    "glossary": {"type": "object", "properties": {"terms": {"type": "array", "items": {"type": "object", "properties": {"term": {"type": "string"}, "definition": {"type": "string"}}}}}},
}


def _llm():
    llm = get_llm_provider()
    if llm is None:
        raise ProviderUnavailableError("llm", "Insights need an AI model. Set LLM_PROVIDER (e.g. ollama) in the backend .env.", retryable=False)
    ok, reason = llm.is_available()
    if not ok:
        raise ProviderUnavailableError(llm.name, reason or "The AI model is unavailable.", retryable=False)
    return llm


def _summarize(llm, title: str, text: str) -> str:
    if len(text) <= MAX_CHARS:
        return llm.complete(SYSTEM, [ChatMessage("user", f"Summarize this chapter ('{title}') in 4-7 sentences. Name the key characters and events.\n\n{text}")], max_tokens=600).strip()
    parts = [text[i : i + MAX_CHARS] for i in range(0, len(text), MAX_CHARS)]
    partials = [
        llm.complete(SYSTEM, [ChatMessage("user", f"Summarize part {n + 1} of {len(parts)} of the chapter '{title}' in 3-5 sentences.\n\n{p}")], max_tokens=400).strip()
        for n, p in enumerate(parts)
    ]
    return llm.complete(SYSTEM, [ChatMessage("user", f"Combine these partial summaries of the chapter '{title}' into one 4-7 sentence summary:\n\n" + "\n\n".join(partials))], max_tokens=600).strip()


def generate_insights(ctx) -> dict:
    llm = _llm()
    kinds = [k for k in (ctx.payload.get("kinds") or KINDS) if k in KINDS]
    with session_scope() as db:
        book = db.get(Book, ctx.book_id)
        chapters = [(c.id, c.title) for c in book.chapters if c.kind not in ("toc", "copyright", "title_page", "back_matter")]
        existing = {i.chapter_id: i.content.get("summary") for i in db.scalars(select(BookInsight).where(BookInsight.book_id == ctx.book_id, BookInsight.kind == "chapter_summary"))}
        book_title = book.title
    summaries: list[tuple[str, str, str]] = []
    for n, (cid, title) in enumerate(chapters):
        ctx.check()
        ctx.update(progress=round(n / max(len(chapters), 1) * 70, 1), message=f"Summarizing {title} ({n + 1}/{len(chapters)})")
        if cid in existing and existing[cid] and "chapter_summary" not in (ctx.payload.get("refresh") or []):
            summaries.append((cid, title, existing[cid]))
            continue
        with session_scope() as db:
            text = "\n\n".join(p.text for p in db.scalars(select(Paragraph).where(Paragraph.chapter_id == cid).order_by(Paragraph.position)))
        if len(text.split()) < 40:
            continue
        summary = _summarize(llm, title, text)
        summaries.append((cid, title, summary))
        with session_scope() as db:
            db.execute(delete(BookInsight).where(BookInsight.book_id == ctx.book_id, BookInsight.chapter_id == cid, BookInsight.kind == "chapter_summary"))
            db.add(BookInsight(book_id=ctx.book_id, chapter_id=cid, kind="chapter_summary", content={"title": title, "summary": summary}, model=f"{llm.name}:{llm.model}"))
    if not summaries:
        raise StudioError("There isn't enough text in this book to summarize.", code="empty_book", retryable=False)

    digest = "\n\n".join(f"{t}:\n{s}" for _cid, t, s in summaries)
    if len(digest) > 60000:
        digest = digest[:60000]
    jobs = [k for k in kinds if k != "chapter_summary"]
    results = {}
    for n, kind in enumerate(jobs):
        ctx.check()
        ctx.update(progress=round(70 + n / max(len(jobs), 1) * 30, 1), message=f"Writing {kind.replace('_', ' ')}")
        base = f"Book: {book_title}\n\nChapter summaries:\n\n{digest}\n\n"
        if kind == "short_summary":
            content = {"text": llm.complete(SYSTEM, [ChatMessage("user", base + "Write a spoiler-light summary of the book in one paragraph (4-6 sentences).")], max_tokens=500).strip()}
        elif kind == "detailed_summary":
            content = {"text": llm.complete(SYSTEM, [ChatMessage("user", base + "Write a detailed summary of the whole book in 4-6 paragraphs, following the order of events.")], max_tokens=1600).strip()}
        else:
            prompts = {
                "characters": "List the characters with a one-sentence description and their role (protagonist, antagonist, supporting...).",
                "events": "List the most important events in order, each with the chapter it happens in.",
                "themes": "Identify 3-6 central themes, each with a short explanation grounded in the summaries.",
                "glossary": "List unusual terms, places, or concepts a reader may need explained, with short definitions. Empty list if none.",
            }
            content = llm.complete_json(SYSTEM, [ChatMessage("user", base + prompts[kind])], SCHEMAS[kind], max_tokens=2000)
        results[kind] = content
        with session_scope() as db:
            db.execute(delete(BookInsight).where(BookInsight.book_id == ctx.book_id, BookInsight.kind == kind))
            db.add(BookInsight(book_id=ctx.book_id, kind=kind, content=content, model=f"{llm.name}:{llm.model}"))
    ctx.update(progress=100, message="Insights ready")
    return {"kinds": list(results) + (["chapter_summary"] if summaries else [])}
