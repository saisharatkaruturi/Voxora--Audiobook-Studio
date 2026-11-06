"""Ask the Book: retrieval-augmented answers grounded in one book.

Every chunk is stored under the namespace `books/{book_id}` and every query
filters on it, so books never leak into each other. Retrieval is hybrid:
dense vectors (embedding provider) + a lexical BM25 score, which keeps names
and rare words findable even with small embedding models.
"""

from __future__ import annotations

import math
import re
import threading
from collections import Counter, OrderedDict
from dataclasses import dataclass

import numpy as np
from sqlalchemy import delete, select

from app.core.errors import StudioError
from app.core.logging import get_logger
from app.db.session import session_scope
from app.models import Book, BookEmbedding, Chapter, ChatMessage, ListeningProgress, Paragraph
from app.providers.embeddings import EmbeddingProvider, HashingEmbeddings, embedder_for, get_embedding_provider
from app.providers.rerank import get_reranker

log = get_logger(__name__)

CHUNK_WORDS = 170
OVERLAP_WORDS = 35


def namespace(book_id: str) -> str:
    return f"books/{book_id}"


def chunk_chapter(paragraphs: list[str]) -> list[str]:
    """~170-word windows that respect paragraph boundaries where possible."""
    chunks: list[str] = []
    current: list[str] = []
    count = 0
    for para in paragraphs:
        words = para.split()
        if count + len(words) > CHUNK_WORDS and current:
            chunks.append(" ".join(current))
            tail = " ".join(current).split()[-OVERLAP_WORDS:]
            current, count = [" ".join(tail)], len(tail)
        if len(words) > CHUNK_WORDS * 2:
            for i in range(0, len(words), CHUNK_WORDS - OVERLAP_WORDS):
                chunks.append(" ".join(words[i : i + CHUNK_WORDS]))
            current, count = [], 0
            continue
        current.append(para)
        count += len(words)
    if current and count > 15:
        chunks.append(" ".join(current))
    return chunks


def index_book(ctx) -> dict:
    """Job handler: (re)build the retrieval index for one book."""
    with session_scope(write=False) as db:
        book = db.get(Book, ctx.book_id)
        embedder = get_embedding_provider(language=book.language)
        chapters = [(c.id, c.position, c.title) for c in book.chapters if c.kind not in ("toc", "copyright")]
    rows: list[dict] = []
    for cid, pos, title in chapters:
        with session_scope() as db:
            paras = [p.text for p in db.scalars(select(Paragraph).where(Paragraph.chapter_id == cid).order_by(Paragraph.position))]
        for i, text in enumerate(chunk_chapter(paras)):
            rows.append({"chapter_id": cid, "chapter_position": pos, "chapter_title": title, "chunk_index": i, "text": text})
    if not rows:
        raise StudioError("This book has no text to index.", code="empty_book", retryable=False)
    vectors: list[np.ndarray] = []
    batch = 64
    try:
        for i in range(0, len(rows), batch):
            ctx.check()
            ctx.update(progress=round(i / len(rows) * 95, 1), message=f"Indexing passages {i + 1}-{min(i + batch, len(rows))} of {len(rows)}")
            vectors.append(embedder.embed([r["text"] for r in rows[i : i + batch]]))
    except StudioError as exc:
        if isinstance(embedder, HashingEmbeddings):
            raise
        log.warning("rag.embedder_fallback", error=exc.message)
        embedder = HashingEmbeddings()
        vectors = [embedder.embed([r["text"] for r in rows[i : i + batch]]) for i in range(0, len(rows), batch)]
    matrix = np.vstack(vectors).astype(np.float32)
    ns = namespace(ctx.book_id)
    with session_scope() as db:
        db.execute(delete(BookEmbedding).where(BookEmbedding.namespace == ns))
        for r, vec in zip(rows, matrix):
            db.add(BookEmbedding(book_id=ctx.book_id, namespace=ns, model=embedder.model_id, dim=len(vec), vector=vec.tobytes(), **r))
    _cache.pop(ctx.book_id, None)
    ctx.update(progress=100, message=f"Indexed {len(rows)} passages")
    return {"chunks": len(rows), "model": embedder.model_id}


# --------------------------------------------------------------------------- retrieval


@dataclass
class Passage:
    id: str
    chapter_id: str | None
    chapter_position: int
    chapter_title: str
    chunk_index: int
    text: str
    score: float


class _BookIndex:
    def __init__(self, rows: list[BookEmbedding]):
        self.rows = rows
        self.model = rows[0].model if rows else ""
        self.matrix = np.vstack([np.frombuffer(r.vector, dtype=np.float32) for r in rows]) if rows else np.zeros((0, 1))
        self.tokens = [_tokens(r.text) for r in rows]
        self.df = Counter(t for toks in self.tokens for t in set(toks))
        self.avg_len = (sum(len(t) for t in self.tokens) / len(self.tokens)) if self.tokens else 1


_cache: OrderedDict[str, tuple[int, _BookIndex]] = OrderedDict()
_cache_lock = threading.Lock()


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _load_index(book_id: str) -> _BookIndex:
    ns = namespace(book_id)
    with session_scope() as db:
        rows = list(db.scalars(select(BookEmbedding).where(BookEmbedding.namespace == ns).order_by(BookEmbedding.chapter_position, BookEmbedding.chunk_index)))
        for r in rows:
            db.expunge(r)
    with _cache_lock:
        cached = _cache.get(book_id)
        if cached and cached[0] == len(rows):
            return cached[1]
        index = _BookIndex(rows)
        _cache[book_id] = (len(rows), index)
        while len(_cache) > 8:
            _cache.popitem(last=False)
        return index


def _bm25(index: _BookIndex, query: str) -> np.ndarray:
    q = [t for t in _tokens(query) if len(t) > 2]
    n = len(index.tokens)
    scores = np.zeros(n, dtype=np.float32)
    if not q or not n:
        return scores
    for i, toks in enumerate(index.tokens):
        tf = Counter(toks)
        s = 0.0
        for t in q:
            if t in tf:
                idf = math.log(1 + (n - index.df[t] + 0.5) / (index.df[t] + 0.5))
                s += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(toks) / index.avg_len))
        scores[i] = s
    return scores


_CHAPTER_REF = re.compile(r"\bchapter\s+(\d{1,3}|[ivxlc]{1,6}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b", re.I)
_WORDNUM = {w: i + 1 for i, w in enumerate("one two three four five six seven eight nine ten eleven twelve".split())}


def referenced_chapter(db, book_id: str, question: str) -> Chapter | None:
    m = _CHAPTER_REF.search(question)
    if not m:
        return None
    token = m.group(1).lower()
    if token.isdigit():
        n = int(token)
    elif token in _WORDNUM:
        n = _WORDNUM[token]
    else:
        from app.ai.narration import roman_to_int

        n = roman_to_int(token.upper()) or 0
    chapters = list(db.scalars(select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.position)))
    pattern = re.compile(rf"^\s*(chapter|chap\.?)\s+({n}|{_roman(n)}|{_word(n)})\b", re.I)
    for c in chapters:
        if pattern.match(c.title):
            return c
    numbered = [c for c in chapters if c.kind == "chapter"]
    return numbered[n - 1] if 0 < n <= len(numbered) else None


def _roman(n: int) -> str:
    vals = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out or "0"


def _word(n: int) -> str:
    return next((w for w, i in _WORDNUM.items() if i == n), str(n))


def retrieve(book_id: str, query: str, k: int = 6, max_chapter_position: int | None = None, chapter_id: str | None = None) -> list[Passage]:
    index = _load_index(book_id)
    if not index.rows:
        return []
    mask = np.ones(len(index.rows), dtype=bool)
    if max_chapter_position is not None:
        mask &= np.array([r.chapter_position <= max_chapter_position for r in index.rows])
    if chapter_id is not None:
        in_chapter = np.array([r.chapter_id == chapter_id for r in index.rows])
        if in_chapter.any():
            # Chapter-specific questions (e.g. "summarize chapter 5"): take the chapter in reading order.
            idx = [i for i in np.nonzero(in_chapter & mask)[0]]
            if len(idx) > k * 2:
                step = len(idx) / (k * 2)
                idx = [idx[int(j * step)] for j in range(k * 2)]
            return [_passage(index.rows[i], 1.0) for i in idx]
    embedder = embedder_for(index.model)
    try:
        qv = embedder.embed([query], query=True)[0]
        dense = index.matrix @ qv if index.matrix.shape[1] == len(qv) else np.zeros(len(index.rows))
    except Exception:
        dense = np.zeros(len(index.rows))
    lexical = _bm25(index, query)
    if lexical.max() > 0:
        lexical = lexical / lexical.max()
    score = 0.65 * dense + 0.35 * lexical
    score[~mask] = -1e9
    candidates = [int(i) for i in np.argsort(-score)[: max(k * 4, 24)] if score[i] > -1e8]
    reranker = get_reranker(_book_language(book_id))
    if reranker is not None and len(candidates) > k:
        rr = reranker.score(query, [index.rows[i].text for i in candidates])
        if rr is not None:
            # Cross-encoder decides the order; the hybrid score breaks near-ties.
            blended = rr + 0.15 * np.array([score[i] for i in candidates])
            candidates = [candidates[j] for j in np.argsort(-blended)]
    top = candidates[:k]
    passages = [_passage(index.rows[i], float(score[i])) for i in top]
    return sorted(passages, key=lambda p: (p.chapter_position, p.chunk_index))


def _book_language(book_id: str) -> str | None:
    with session_scope() as db:
        return db.scalar(select(Book.language).where(Book.id == book_id))


def _passage(row: BookEmbedding, score: float) -> Passage:
    return Passage(row.id, row.chapter_id, row.chapter_position, row.chapter_title, row.chunk_index, row.text, score)


# --------------------------------------------------------------------------- answering


ANSWER_SYSTEM = """You answer questions about one specific book using ONLY the numbered excerpts provided.

Rules:
- "from_book": what the excerpts explicitly state. Cite excerpts inline like [2] or [1][4].
- "inference": your own interpretation or reasoning beyond what is stated, clearly as inference. Empty string if none.
- If the excerpts don't contain the answer, set "found" to false and say so in "from_book". Do not use outside knowledge of this or any other book.
- Be concise and specific. Never invent quotes."""

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "from_book": {"type": "string"},
        "inference": {"type": "string"},
        "cited": {"type": "array", "items": {"type": "integer"}},
    },
}


def ask(user_id: str, book_id: str, question: str, spoiler_safe: bool = False) -> dict:
    from app.providers.llm import ChatMessage as LLMMessage
    from app.providers.llm import get_llm_provider

    question = question.strip()[:2000]
    with session_scope() as db:
        already = db.scalar(select(ChatMessage).where(ChatMessage.book_id == book_id, ChatMessage.user_id == user_id, ChatMessage.role == "user").order_by(ChatMessage.created_at.desc()))
        max_pos = None
        if spoiler_safe:
            progress = db.scalar(select(ListeningProgress).where(ListeningProgress.user_id == user_id, ListeningProgress.book_id == book_id))
            max_pos = progress.chapter_position if progress else 0
        chapter = referenced_chapter(db, book_id, question)
        chapter_id = chapter.id if chapter else None
        if chapter and max_pos is not None and chapter.position > max_pos:
            chapter_id = None
        history = list(db.scalars(select(ChatMessage).where(ChatMessage.book_id == book_id, ChatMessage.user_id == user_id).order_by(ChatMessage.created_at.desc()).limit(4)))[::-1]
        if not (already and already.content == question and not _answered(db, already)):
            db.add(ChatMessage(book_id=book_id, user_id=user_id, role="user", content=question, meta={"spoiler_safe": spoiler_safe}))

    passages = retrieve(book_id, question, k=5, max_chapter_position=max_pos, chapter_id=chapter_id)
    if not passages:
        answer = {
            "found": False,
            "from_book": "This book hasn't been indexed yet, or no passage matched your question.",
            "inference": "",
            "mode": "none",
        }
        return _save_answer(user_id, book_id, answer, [])
    citations = [
        {"n": i + 1, "chapter_id": p.chapter_id, "chapter_title": p.chapter_title, "chapter_position": p.chapter_position, "excerpt": p.text[:600]}
        for i, p in enumerate(passages)
    ]
    llm = get_llm_provider()
    available, reason = (llm.is_available() if llm else (False, "No LLM is configured (LLM_PROVIDER=none)."))
    if not available:
        answer = {
            "found": True,
            "from_book": "No AI model is available, so here are the passages that best match your question.",
            "inference": "",
            "mode": "passages_only",
            "notice": reason,
        }
        return _save_answer(user_id, book_id, answer, citations)

    excerpts = "\n\n".join(f"[{c['n']}] ({c['chapter_title']})\n{p.text}" for c, p in zip(citations, passages))
    convo = "\n".join(f"{m.role}: {m.content[:400]}" for m in history)
    prompt = (
        (f"Earlier conversation:\n{convo}\n\n" if convo else "")
        + f"Excerpts from the book:\n\n{excerpts}\n\nQuestion: {question}"
        + ("\n\nThe reader asked to avoid spoilers beyond their current chapter." if spoiler_safe else "")
    )
    try:
        data = llm.complete_json(ANSWER_SYSTEM, [LLMMessage("user", prompt)], ANSWER_SCHEMA, max_tokens=1200)
    except Exception as exc:
        message = getattr(exc, "message", str(exc))
        answer = {"found": True, "from_book": f"The AI model failed to answer ({message}). Here are the most relevant passages.", "inference": "", "mode": "passages_only"}
        return _save_answer(user_id, book_id, answer, citations)
    cited = {int(n) for n in data.get("cited", []) if isinstance(n, (int, float))} | {int(n) for n in re.findall(r"\[(\d+)\]", data.get("from_book", ""))}
    answer = {
        "found": bool(data.get("found", True)),
        "from_book": str(data.get("from_book", "")).strip(),
        "inference": str(data.get("inference", "")).strip(),
        "mode": "llm",
        "model": f"{llm.name}:{llm.model}",
        "is_local": llm.is_local,
    }
    kept = [c for c in citations if c["n"] in cited] or citations[:3]
    return _save_answer(user_id, book_id, answer, kept)


def _answered(db, question_msg: ChatMessage) -> bool:
    """Has this question message already received an answer? (retried jobs must not duplicate it)"""
    later = db.scalar(select(ChatMessage).where(ChatMessage.book_id == question_msg.book_id, ChatMessage.user_id == question_msg.user_id, ChatMessage.created_at > question_msg.created_at))
    return later is not None


def _save_answer(user_id: str, book_id: str, answer: dict, citations: list[dict]) -> dict:
    content = answer["from_book"] + (f"\n\nInference: {answer['inference']}" if answer.get("inference") else "")
    with session_scope() as db:
        msg = ChatMessage(book_id=book_id, user_id=user_id, role="assistant", content=content, citations=citations, meta=answer)
        db.add(msg)
        db.flush()
        return {"id": msg.id, **answer, "citations": citations, "created_at": msg.created_at.isoformat()}


def is_indexed(db, book_id: str) -> int:
    from sqlalchemy import func

    return db.scalar(select(func.count()).select_from(BookEmbedding).where(BookEmbedding.namespace == namespace(book_id))) or 0
