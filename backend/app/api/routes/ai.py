from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, rate_limit
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.models import BookInsight, CastMember, ChatMessage, GenerationJob, JobType, User
from app.schemas.common import AskIn, CastAnalyzeIn, CastUpdateIn, InsightsIn, serialize_job
from app.services import rag
from app.services.books import get_book_for, get_chapter_for
from app.services.cast import dialogue_preview
from app.workers import queue

router = APIRouter(prefix="/api", tags=["ai"])

ROLE_ORDER = {"narrator": 0, "character": 1, "unknown": 2}


def _member(m: CastMember) -> dict:
    return {
        "id": m.id, "name": m.name, "role": m.role, "gender_hint": m.gender_hint, "line_count": m.line_count,
        "provider": m.provider, "voice_id": m.voice_id, "auto_assigned": m.auto_assigned,
    }


# --------------------------------------------------------------------------- cast


@router.get("/books/{book_id}/cast")
def get_cast(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    book = get_book_for(db, book_id, user)
    members = sorted(db.scalars(select(CastMember).where(CastMember.book_id == book.id)), key=lambda m: (ROLE_ORDER.get(m.role, 3), -m.line_count))
    sample = []
    for c in book.chapters:
        if c.include_in_audio:
            sample = dialogue_preview(db, c)
            if sample:
                break
    return {"items": [_member(m) for m in members], "enabled": bool((book.narration or {}).get("cast_mode")), "sample": sample}


@router.post("/books/{book_id}/cast/analyze")
def analyze_cast(book_id: str, body: CastAnalyzeIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    book = get_book_for(db, book_id, user)
    job = queue.enqueue(db, type=JobType.CAST_ANALYSIS, user_id=user.id, book_id=book.id, payload=body.model_dump(), exclusive_types={JobType.CAST_ANALYSIS, JobType.GENERATE_BOOK})
    return serialize_job(job)


@router.patch("/cast/{member_id}")
def update_cast(member_id: str, body: CastUpdateIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    member = db.get(CastMember, member_id)
    if member is None:
        raise NotFoundError("Cast member not found.")
    get_book_for(db, member.book_id, user)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(member, k, v)
    member.auto_assigned = False
    db.commit()
    return _member(member)


@router.get("/chapters/{chapter_id}/dialogue")
def chapter_dialogue(chapter_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    chapter = get_chapter_for(db, chapter_id, user)
    return {"items": dialogue_preview(db, chapter, limit=200)}


# --------------------------------------------------------------------------- ask the book


@router.get("/books/{book_id}/ask/status")
def ask_status(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    from app.providers.embeddings import get_embedding_provider
    from app.providers.llm import get_llm_provider

    book = get_book_for(db, book_id, user)
    llm = get_llm_provider()
    llm_info = llm.describe() if llm else {"available": False, "reason": "LLM_PROVIDER=none", "is_local": True}
    index_job = db.scalars(select(GenerationJob).where(GenerationJob.book_id == book.id, GenerationJob.type == JobType.INDEX_BOOK).order_by(GenerationJob.created_at.desc())).first()
    return {"indexed_chunks": rag.is_indexed(db, book.id), "index_job": serialize_job(index_job), "llm": llm_info, "embeddings": get_embedding_provider().model_id}


@router.post("/books/{book_id}/index")
def index_book(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    book = get_book_for(db, book_id, user)
    job = queue.enqueue(db, type=JobType.INDEX_BOOK, user_id=user.id, book_id=book.id, priority=5, exclusive_types={JobType.INDEX_BOOK})
    return serialize_job(job)


@router.post("/books/{book_id}/ask", dependencies=[Depends(rate_limit("ask", 30, 60))])
def ask(book_id: str, body: AskIn, sync: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Questions run as a background job (local models can take minutes on CPU);
    watch the job over /ws/jobs/{id}. `sync=true` answers inline (scripts/tests)."""
    book = get_book_for(db, book_id, user)
    if sync:
        db.close()
        return rag.ask(user.id, book.id, body.question, body.spoiler_safe)
    job = queue.enqueue(db, type=JobType.ASK, user_id=user.id, book_id=book.id, payload=body.model_dump(), priority=30)
    return {"job": serialize_job(job)}


@router.get("/books/{book_id}/chat")
def chat_history(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    get_book_for(db, book_id, user)
    rows = db.scalars(select(ChatMessage).where(ChatMessage.book_id == book_id, ChatMessage.user_id == user.id).order_by(ChatMessage.created_at).limit(200))
    return {"items": [{"id": m.id, "role": m.role, "content": m.content, "citations": m.citations or [], "meta": m.meta or {}, "created_at": m.created_at.isoformat()} for m in rows]}


@router.delete("/books/{book_id}/chat", status_code=204)
def clear_chat(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    get_book_for(db, book_id, user)
    db.execute(delete(ChatMessage).where(ChatMessage.book_id == book_id, ChatMessage.user_id == user.id))
    db.commit()


# --------------------------------------------------------------------------- insights


@router.get("/books/{book_id}/insights")
def get_insights(book_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    book = get_book_for(db, book_id, user)
    rows = db.scalars(select(BookInsight).where(BookInsight.book_id == book.id))
    positions = {c.id: c.position for c in book.chapters}
    out: dict = {"chapter_summaries": []}
    for r in rows:
        if r.kind == "chapter_summary":
            out["chapter_summaries"].append({"chapter_id": r.chapter_id, "position": positions.get(r.chapter_id, 0), **r.content})
        else:
            out[r.kind] = {**r.content, "model": r.model, "created_at": r.created_at.isoformat()}
    out["chapter_summaries"].sort(key=lambda x: x["position"])
    return out


@router.post("/books/{book_id}/insights")
def create_insights(book_id: str, body: InsightsIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    book = get_book_for(db, book_id, user)
    job = queue.enqueue(db, type=JobType.INSIGHTS, user_id=user.id, book_id=book.id, payload=body.model_dump(), exclusive_types={JobType.INSIGHTS})
    return serialize_job(job)
