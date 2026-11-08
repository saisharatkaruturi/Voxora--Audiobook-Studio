"""API schemas (request bodies) and serializers (responses).

Responses are built by small `serialize_*` functions rather than ORM-mode models
so that signed media URLs and computed fields stay in one place.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import sign_media_path
from app.document_processing.content_modes import section_group
from app.models import Book, Bookmark, Chapter, GenerationJob, ListeningProgress, User


def media_url(storage_key: str | None, ttl: int | None = None) -> str | None:
    if not storage_key:
        return None
    return sign_media_path(f"/media/{storage_key}", ttl)


# --------------------------------------------------------------------------- auth


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)


class ProfileIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    current_password: str | None = None
    new_password: str | None = Field(default=None, min_length=8, max_length=200)


def serialize_user(u: User) -> dict:
    return {"id": u.id, "email": u.email, "display_name": u.display_name, "is_admin": u.is_admin, "created_at": u.created_at.isoformat()}


# --------------------------------------------------------------------------- books


class NarrationIn(BaseModel):
    provider: str | None = None
    voice_id: str | None = None
    language_voices: dict[str, dict] | None = None
    speed: float | None = Field(default=None, ge=0.5, le=2.0)
    pitch: float | None = Field(default=None, ge=-10, le=10)
    volume: float | None = Field(default=None, ge=0, le=2)
    sentence_pause_ms: int | None = Field(default=None, ge=0, le=5000)
    paragraph_pause_ms: int | None = Field(default=None, ge=0, le=10000)
    heading_pause_ms: int | None = Field(default=None, ge=0, le=10000)
    chapter_pause_ms: int | None = Field(default=None, ge=0, le=10000)
    narration_cleanup: bool | None = None
    ai_ocr_repair: bool | None = None
    cast_mode: bool | None = None
    announce_chapter_titles: bool | None = None
    format: Literal["mp3", "m4a", "wav"] | None = None
    bitrate: Literal["48k", "64k", "96k", "128k", "160k", "192k"] | None = None
    normalize: bool | None = None
    compress: bool | None = None
    shorten_long_pauses: bool | None = None
    build_full_audiobook: bool | None = None
    content_mode: Literal["narrative", "full", "custom"] | None = None


class BookUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    subtitle: str | None = Field(default=None, max_length=500)
    author: str | None = Field(default=None, max_length=300)
    narrator: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    genre: str | None = Field(default=None, max_length=120)
    year: str | None = Field(default=None, max_length=16)
    language: str | None = Field(default=None, max_length=16)
    narration: NarrationIn | None = None


class AnalyzeIn(BaseModel):
    ocr_mode: Literal["auto", "force", "off"] = "auto"
    languages: list[str] = Field(default_factory=list, max_length=5)
    ocr_provider: str | None = None


class GenerateIn(BaseModel):
    chapter_ids: list[str] | None = None
    force: bool = False


def serialize_job(j: GenerationJob | None) -> dict | None:
    if j is None:
        return None
    return {
        "id": j.id,
        "type": j.type,
        "status": j.status,
        "book_id": j.book_id,
        "chapter_id": j.chapter_id,
        "progress": round(j.progress or 0, 1),
        "stage": j.stage,
        "message": j.message,
        "current_chapter": j.current_chapter,
        "total_chapters": j.total_chapters,
        "stages": j.stages or [],
        "result": j.result,
        "error": j.error,
        "attempts": j.attempts,
        "max_attempts": j.max_attempts,
        "created_at": j.created_at.isoformat(),
        "started_at": j.started_at.isoformat() if j.started_at else None,
        "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        "run_after": j.run_after.isoformat() if j.run_after else None,
    }


def serialize_progress(p: ListeningProgress | None) -> dict | None:
    if p is None:
        return None
    return {
        "chapter_id": p.chapter_id,
        "chapter_position": p.chapter_position,
        "position_seconds": round(p.position_seconds, 2),
        "book_position_seconds": round(p.book_position_seconds, 2),
        "playback_rate": p.playback_rate,
        "completed": p.completed,
        "updated_at": p.updated_at.isoformat(),
    }


def serialize_book(b: Book, *, progress: ListeningProgress | None = None, job: GenerationJob | None = None, counts: dict | None = None, narration: dict | None = None) -> dict:
    counts = counts or {}
    return {
        "id": b.id,
        "title": b.title,
        "subtitle": b.subtitle,
        "author": b.author,
        "narrator": b.narrator,
        "description": b.description,
        "genre": b.genre,
        "genres": b.genres or ([b.genre] if b.genre else []),
        "series": b.series,
        "series_index": b.series_index,
        "about": (b.book_info or {}).get("about"),
        "ratings": (b.book_info or {}).get("ratings"),
        "classified_at": b.classified_at,
        "year": b.year,
        "language": b.language,
        "languages": b.languages or [],
        "status": b.status,
        "source_format": b.source_format,
        "page_count": b.page_count,
        "word_count": b.word_count,
        "char_count": b.char_count,
        "ocr_used": b.ocr_used,
        "ocr_engine": b.ocr_engine,
        "ocr_confidence": b.ocr_confidence,
        "warnings": b.warnings or [],
        "cover_url": media_url(b.cover_key) + f"&v={int(b.updated_at.timestamp())}" if b.cover_key else None,
        "cover_source": b.cover_source,
        "narration": narration if narration is not None else (b.narration or {}),
        "total_duration": b.total_duration,
        "error": b.error,
        "chapter_count": counts.get("chapters"),
        "chapters_with_audio": counts.get("with_audio"),
        "narrated_chapters": counts.get("narrated"),
        "progress": serialize_progress(progress),
        "active_job": serialize_job(job),
        "created_at": b.created_at.isoformat(),
        "updated_at": b.updated_at.isoformat(),
    }


# --------------------------------------------------------------------------- chapters


class ChapterUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    kind: str | None = Field(default=None, max_length=30)
    include_in_audio: bool | None = None
    text: str | None = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        allowed = {
            "front_matter", "title_page", "copyright", "toc", "dedication", "epigraph", "foreword", "preface", "introduction",
            "acknowledgements", "prologue", "chapter", "part", "epilogue", "afterword", "appendix", "glossary", "bibliography",
            "author_bio", "advertisement", "back_matter",
        }
        if v is not None and v not in allowed:
            raise ValueError(f"kind must be one of {sorted(allowed)}")
        return v


class ContentModeIn(BaseModel):
    mode: Literal["narrative", "full", "custom"]


class ChapterCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1)
    after_position: int | None = None


class ReorderIn(BaseModel):
    chapter_ids: list[str]


class MergeIn(BaseModel):
    chapter_ids: list[str] = Field(min_length=2)


class SplitIn(BaseModel):
    paragraph_index: int = Field(ge=1)
    title: str | None = Field(default=None, max_length=500)


def serialize_chapter(c: Chapter, *, stale: bool = False, audio: dict | None = None) -> dict:
    return {
        "id": c.id,
        "book_id": c.book_id,
        "position": c.position,
        "title": c.title,
        "kind": c.kind,
        "include_in_audio": c.include_in_audio,
        "word_count": c.word_count,
        "char_count": c.char_count,
        "language": c.language,
        "audio_status": c.audio_status,
        "audio_progress": c.audio_progress,
        "audio_error": c.audio_error,
        "duration": c.duration,
        "stale": stale,
        "detection": c.detection or {},
        "group": section_group(c.kind),
        "pages": [c.source_pages[0], c.source_pages[-1]] if c.source_pages else None,
        "text_version": c.text_version,
        "audio": audio,
    }


# --------------------------------------------------------------------------- listening


class ProgressIn(BaseModel):
    chapter_id: str | None = None
    position_seconds: float = Field(ge=0)
    playback_rate: float = Field(default=1.0, ge=0.5, le=3.0)
    completed: bool = False


class BookmarkIn(BaseModel):
    chapter_id: str | None = None
    position_seconds: float = Field(ge=0)
    note: str | None = Field(default=None, max_length=2000)


class BookmarkUpdateIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


def serialize_bookmark(b: Bookmark) -> dict:
    return {
        "id": b.id,
        "book_id": b.book_id,
        "chapter_id": b.chapter_id,
        "chapter_title": b.chapter_title,
        "position_seconds": round(b.position_seconds, 2),
        "note": b.note,
        "created_at": b.created_at.isoformat(),
    }


# --------------------------------------------------------------------------- voices / cast / ai


class PreviewIn(BaseModel):
    provider: str
    voice_id: str = Field(max_length=300)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    pitch: float = Field(default=0.0, ge=-10, le=10)
    text: str | None = Field(default=None, max_length=400)
    language: str | None = None
    book_id: str | None = None


class InstallVoiceIn(BaseModel):
    voice: str = Field(max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")


class CastAnalyzeIn(BaseModel):
    use_llm: bool = False


class CastUpdateIn(BaseModel):
    provider: str | None = None
    voice_id: str | None = Field(default=None, max_length=300)
    gender_hint: Literal["male", "female", "unknown"] | None = None


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    spoiler_safe: bool = False


class InsightsIn(BaseModel):
    kinds: list[str] | None = None
    refresh: list[str] | None = None


class PreferencesIn(BaseModel):
    model_config = {"extra": "allow"}
