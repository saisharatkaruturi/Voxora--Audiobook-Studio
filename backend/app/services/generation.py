"""Audiobook generation.

Book -> chapters -> paragraphs -> sentence chunks -> TTS -> segment cache
-> chapter audio (+ sentence timings) -> full audiobook.

- Every TTS chunk is cached by a content hash (text + voice + settings), so
  re-running a chapter, resuming after a failure, or regenerating after a small
  edit only synthesizes what changed.
- Chapter audio is assembled as raw PCM on disk (constant memory for long chapters).
- Sentence timestamps come from the provider when available, otherwise are
  approximated from character counts, and are adjusted for every trim.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from sqlalchemy import select, update

from app.ai.narration import llm_ocr_repair, normalize_for_speech
from app.audio.ffmpeg import decode_to_pcm16, flac_to_pcm, pcm_to_flac
from app.audio.metadata import ChapterMark, TagInfo, write_tags
from app.audio.mp3join import join_mp3
from app.audio.mp3pass import Mp3Format, silence as mp3_silence, split_frames
from app.audio.processing import MIME, concat_files, encode_raw, remap_time, shorten_long_pauses, silence, trim_edges
from app.core.config import BACKEND_DIR, get_settings
from app.services.handoff import device_mode, on_device
from app.core.errors import JobCancelled, ProviderError, ProviderTimeoutError, StudioError, UnsupportedLanguageError
from app.core.logging import get_logger
from app.db.session import best_effort_write, session_scope
from app.document_processing.segmentation import Sentence, split_long, split_sentences
from app.models import AudioAsset, Book, BookStatus, CastMember, Chapter, ChapterStatus, Paragraph
from app.providers.storage import get_storage
from app.providers.tts import SynthesisOptions, get_tts_provider
from app.providers.tts.timing import approximate_sentence_times
from app.services import narration_settings
from app.services.books import book_prefix, content_hash, new_storage_name

log = get_logger(__name__)


@dataclass
class Voice:
    provider: str
    voice_id: str


@dataclass
class Chunk:
    paragraph: int  # paragraph position
    voice: Voice
    language: str | None
    sentences: list[tuple[str, int, int]]  # (text to speak, char start, char end in paragraph)
    pause_before_ms: int
    heading: bool = False
    speaker: str | None = None

    @property
    def chars(self) -> int:
        return sum(len(s[0]) for s in self.sentences)


@dataclass
class ChapterPlan:
    chunks: list[Chunk] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return sum(c.chars for c in self.chunks)


def tmp_dir() -> Path:
    d = BACKEND_DIR / "data" / "tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------- planning


def _voice_for(settings: dict, language: str | None, book_language: str | None, warnings: list[str], voice_cache: dict) -> Voice:
    lang = language or book_language or "en"
    mapped = (settings.get("language_voices") or {}).get(lang)
    if mapped and mapped.get("voice_id"):
        return Voice(mapped.get("provider") or settings["provider"], mapped["voice_id"])
    if lang == (book_language or lang) or not language:
        return Voice(settings["provider"], settings["voice_id"])
    # A paragraph in another language: pick a voice for it from the same provider if one exists.
    key = (settings["provider"], lang)
    if key not in voice_cache:
        voice_cache[key] = narration_settings.default_voice_for(settings["provider"], lang) if _provider_has_language(settings["provider"], lang) else None
        if voice_cache[key] is None:
            warnings.append(
                f"No {settings['provider']} voice for language '{lang}'; those paragraphs use the main narrator. Pick a voice for it in Voice Studio."
            )
    vid = voice_cache[key]
    return Voice(settings["provider"], vid) if vid else Voice(settings["provider"], settings["voice_id"])


def _provider_has_language(provider: str, lang: str) -> bool:
    try:
        return any(v.language == lang and v.installed for v in get_tts_provider(provider).list_voices())
    except Exception:
        return False


def plan_chapter(chapter: Chapter, paragraphs: list[Paragraph], settings: dict, book: Book, cast: dict[str, Voice] | None = None) -> ChapterPlan:
    plan = ChapterPlan()
    voice_cache: dict = {}
    first = True
    for p in paragraphs:
        text = p.text.strip()
        if not text:
            continue
        if p.kind == "heading" and not settings["announce_chapter_titles"]:
            continue
        pause = 0 if first else (settings["heading_pause_ms"] if p.kind == "heading" else settings["paragraph_pause_ms"])
        narrator = _voice_for(settings, p.language, book.language, plan.warnings, voice_cache)
        # Split the paragraph into narrator / dialogue segments when AI Cast is on.
        segments: list[tuple[int, int, str | None]] = [(0, len(p.text), None)]
        if settings["cast_mode"] and cast and p.spans:
            segments = []
            cursor = 0
            for span in sorted(p.spans, key=lambda s: s["start"]):
                if span["start"] > cursor:
                    segments.append((cursor, span["start"], None))
                segments.append((span["start"], span["end"], span.get("speaker")))
                cursor = span["end"]
            if cursor < len(p.text):
                segments.append((cursor, len(p.text), None))
        for seg_start, seg_end, speaker in segments:
            seg_text = p.text[seg_start:seg_end]
            if not seg_text.strip() or not any(ch.isalnum() for ch in seg_text):
                continue
            voice = cast.get(speaker) if (speaker and cast and cast.get(speaker)) else (cast.get("Narrator") if cast and cast.get("Narrator") and settings["cast_mode"] else narrator)
            provider = get_tts_provider(voice.provider)
            sentences: list[tuple[str, int, int]] = []
            for s in split_sentences(seg_text):
                for part in split_long(Sentence(s.text, s.start + seg_start, s.end + seg_start), min(provider.max_chunk_chars, 600)):
                    spoken = normalize_for_speech(part.text, p.language or book.language) if settings["narration_cleanup"] else part.text
                    if any(ch.isalnum() for ch in spoken):
                        sentences.append((spoken, part.start, part.end))
            # Group sentences into provider-sized chunks.
            batch: list[tuple[str, int, int]] = []
            for s in sentences:
                if batch and sum(len(x[0]) for x in batch) + len(s[0]) > provider.max_chunk_chars:
                    plan.chunks.append(Chunk(p.position, voice, p.language, batch, pause, p.kind == "heading", speaker))
                    batch, pause = [], settings["sentence_pause_ms"]
                batch.append(s)
            if batch:
                plan.chunks.append(Chunk(p.position, voice, p.language, batch, pause, p.kind == "heading", speaker))
                pause = settings["sentence_pause_ms"] // 2
        first = False
    return plan


def load_cast(db, book_id: str) -> dict[str, Voice]:
    members = db.scalars(select(CastMember).where(CastMember.book_id == book_id)).all()
    return {m.name: Voice(m.provider, m.voice_id) for m in members if m.voice_id and m.provider}


def chapter_audio_hash(paragraphs: list[Paragraph], settings: dict, title: str, cast: dict[str, Voice] | None) -> str:
    parts = [json.dumps(narration_settings.audio_signature(settings), sort_keys=True), title]
    for p in paragraphs:
        parts.append(f"{p.kind}|{p.language}|{p.text}")
        if settings.get("cast_mode"):
            parts.append(json.dumps(p.spans or [], sort_keys=True))
    if settings.get("cast_mode") and cast:
        parts.append(json.dumps({k: [v.provider, v.voice_id] for k, v in sorted(cast.items())}))
    return content_hash(*parts)


# --------------------------------------------------------------------------- synthesis with cache


def _segment_key(chunk: Chunk, settings: dict) -> str:
    provider = get_tts_provider(chunk.voice.provider)
    return content_hash(
        provider.signature(chunk.voice.voice_id),
        json.dumps([settings["speed"], settings["pitch"], settings["volume"], settings["sentence_pause_ms"]]),
        *[s[0] for s in chunk.sentences],
    )


def _synthesis_options(chunk: Chunk, settings: dict) -> SynthesisOptions:
    return SynthesisOptions(
        voice_id=chunk.voice.voice_id,
        speed=settings["speed"],
        pitch=settings["pitch"],
        volume=settings["volume"],
        language=chunk.language,
        sentence_pause_ms=settings["sentence_pause_ms"],
    )


def _synthesize_with_retries(provider, texts: list[str], options: SynthesisOptions, check=None):
    attempts = get_settings().tts_max_retries
    for attempt in range(attempts):
        try:
            return provider.synthesize(texts, options)
        except ProviderError as exc:
            if not exc.retryable or attempt == attempts - 1:
                raise
            # A stalled request is simply re-sent (the provider's limiter already eased
            # off); other transient errors back off exponentially.
            delay = 1 if isinstance(exc, ProviderTimeoutError) else min(30, 2 ** (attempt + 1))
            log.warning("tts.retry", provider=provider.name, attempt=attempt + 1, delay=delay, error=exc.message)
            for _ in range(delay):
                if check:
                    check()
                time.sleep(1)


def synthesize_chunk_mp3(chunk: Chunk, settings: dict, check=None) -> tuple[bytes, int, Mp3Format, list[tuple[float, float]], str, bool]:
    """MP3 passthrough: the provider's own frames, untouched. Returns (frames, frame count,
    format, sentence times relative to the chunk start, timing source, from_cache)."""
    storage = get_storage()
    key = content_hash(_segment_key(chunk, settings), "mp3-frames")
    use_cache = get_settings().tts_segment_cache
    with session_scope(write=False) as db:
        cached = db.scalar(select(AudioAsset).where(AudioAsset.cache_key == key)) if use_cache else None
        if cached and storage.exists(cached.storage_key):
            frames, count, fmt = split_frames(storage.read_bytes(cached.storage_key))
            return frames, count, fmt, [tuple(t) for t in cached.timings or []], cached.timing_source or "approximate", True
    provider = get_tts_provider(chunk.voice.provider)
    texts = [s[0] for s in chunk.sentences]
    result = _synthesize_with_retries(provider, texts, _synthesis_options(chunk, settings), check)
    frames, count, fmt = split_frames(result.audio)
    duration = count * fmt.frame_seconds
    if result.sentence_times and len(result.sentence_times) == len(texts):
        times = [(max(0.0, min(a, duration)), max(0.0, min(b, duration))) for a, b in result.sentence_times]
        source = "provider"
    else:
        times = approximate_sentence_times(texts, duration, settings["sentence_pause_ms"] / 1000 if len(texts) > 1 else 0)
        source = "approximate"
    if not use_cache:
        return frames, count, fmt, times, source, False
    storage_key = f"cache/tts/{key[:2]}/{key}.mp3"
    size = storage.save_bytes(storage_key, frames)

    def remember(db) -> None:
        if db.scalar(select(AudioAsset.id).where(AudioAsset.cache_key == key)) is None:
            db.add(
                AudioAsset(
                    kind="segment", cache_key=key, storage_key=storage_key, format="mp3", sample_rate=fmt.rate,
                    duration=duration, size_bytes=size, timings=[list(t) for t in times], timing_source=source,
                    meta={"provider": provider.name, "voice": chunk.voice.voice_id, "passthrough": True},
                )
            )

    best_effort_write(remember)
    return frames, count, fmt, times, source, False


def mp3_passthrough(plan: "ChapterPlan", settings: dict) -> bool:
    """Chapters narrated only by a provider that returns CBR MP3 are assembled from
    its frames directly (no decode/re-encode) unless an audio effect needs PCM."""
    if settings["format"] != "mp3" or settings.get("compress") or not plan.chunks:
        return False
    return all(getattr(get_tts_provider(p), "mp3_passthrough", False) for p in {c.voice.provider for c in plan.chunks})


def synthesize_chunk(chunk: Chunk, settings: dict, rate: int, check=None) -> tuple[np.ndarray, list[tuple[float, float]], str, bool]:
    """Returns (pcm int16 @ rate, sentence times, timing source, from_cache)."""
    storage = get_storage()
    key = _segment_key(chunk, settings)
    use_cache = get_settings().tts_segment_cache
    with session_scope(write=False) as db:
        cached = db.scalar(select(AudioAsset).where(AudioAsset.cache_key == key)) if use_cache else None
        if cached and cached.sample_rate == rate and storage.exists(cached.storage_key):
            pcm = flac_to_pcm(storage.read_bytes(cached.storage_key), rate)
            return pcm, [tuple(t) for t in cached.timings or []], cached.timing_source or "approximate", True

    provider = get_tts_provider(chunk.voice.provider)
    ok, reason = provider.is_available()
    if not ok:
        raise ProviderError(provider.name, reason or f"{provider.display_name} is unavailable.", retryable=False, code="provider_unavailable")
    texts = [s[0] for s in chunk.sentences]
    result = _synthesize_with_retries(provider, texts, _synthesis_options(chunk, settings), check)
    pcm = decode_to_pcm16(result.audio, result.format, result.sample_rate, rate)
    duration = len(pcm) / rate
    if result.sentence_times and len(result.sentence_times) == len(texts):
        times = [(max(0.0, min(a, duration)), max(0.0, min(b, duration))) for a, b in result.sentence_times]
        source = "provider"
    else:
        times = approximate_sentence_times(texts, duration, settings["sentence_pause_ms"] / 1000 if len(texts) > 1 else 0)
        source = "approximate"
    # Trim edge silence and shorten unnaturally long internal pauses, keeping timings aligned.
    pcm, lead = trim_edges(pcm, rate)
    shift = lead / rate
    times = [(max(0.0, a - shift), max(0.0, b - shift)) for a, b in times]
    if settings.get("shorten_long_pauses"):
        pcm, cuts = shorten_long_pauses(pcm, rate)
        if cuts:
            times = [(remap_time(a, cuts), remap_time(b, cuts)) for a, b in times]
    duration = len(pcm) / rate
    times = [(min(a, duration), min(b, duration)) for a, b in times]
    if times:
        times[-1] = (times[-1][0], duration)

    if not use_cache:
        return pcm, times, source, False
    storage_key = f"cache/tts/{key[:2]}/{key}.flac"
    size = storage.save_bytes(storage_key, pcm_to_flac(pcm, rate))

    def remember(db) -> None:
        if db.scalar(select(AudioAsset.id).where(AudioAsset.cache_key == key)) is None:
            db.add(
                AudioAsset(
                    kind="segment", cache_key=key, storage_key=storage_key, format="flac", sample_rate=rate,
                    duration=duration, size_bytes=size, timings=[list(t) for t in times], timing_source=source,
                    meta={"provider": provider.name, "voice": chunk.voice.voice_id},
                )
            )

    # The cache only speeds up regeneration; never fail a chapter over it.
    best_effort_write(remember)
    return pcm, times, source, False


# --------------------------------------------------------------------------- chapters


def encode_parallelism(cloud_voice: bool = False) -> int:
    """Chapters encoded at once. With a cloud voice the CPU is otherwise idle, so
    encoding gets up to half the cores; a local engine keeps most for synthesis."""
    configured = get_settings().encode_concurrency
    if configured > 0:
        return configured
    cores = os.cpu_count() or 4
    return max(2, min(6, cores // 2)) if cloud_voice else max(2, min(4, cores // 4))


def chunk_parallelism(plan: "ChapterPlan") -> int:
    """How many chunks to synthesize at once: the TTS_CONCURRENCY override, else the
    most conservative limit among the providers this chapter uses."""
    override = get_settings().tts_concurrency
    if override > 0:
        return override
    limits = [get_tts_provider(p).max_chunk_parallelism for p in {c.voice.provider for c in plan.chunks}] or [1]
    return max(1, min(limits))


def chapter_parallelism(settings: dict, chapters: int) -> int:
    """How many chapters synthesize at once (CHAPTER_CONCURRENCY override, else the
    narrator provider's limit; cast voices from other providers are covered by their
    own per-request limits)."""
    override = get_settings().chapter_concurrency
    limit = override if override > 0 else get_tts_provider(settings["provider"]).max_chapter_parallelism
    return max(1, min(limit, chapters or 1))


class ChapterFailed(StudioError):
    code = "chapter_failed"
    status_code = 500


def generate_chapter(chapter_id: str, settings: dict, check=None, on_progress=None, finisher: ThreadPoolExecutor | None = None):
    """Generate one chapter's audio. `check()` raises JobCancelled on pause/cancel.
    `on_progress(done_chars, total_chars)`. With `finisher`, encoding runs there and a
    Future of the result is returned, so the next chapter can start synthesizing."""
    s = get_settings()
    rate = s.audio_sample_rate
    storage = get_storage()
    with session_scope() as db:
        chapter = db.get(Chapter, chapter_id)
        book = db.get(Book, chapter.book_id)
        paragraphs = list(db.scalars(select(Paragraph).where(Paragraph.chapter_id == chapter_id).order_by(Paragraph.position)))
        cast = load_cast(db, book.id) if settings.get("cast_mode") else None
        plan = plan_chapter(chapter, paragraphs, settings, book, cast)
        audio_hash = chapter_audio_hash(paragraphs, settings, chapter.title, cast)
        title, position, book_id = chapter.title, chapter.position, book.id
        tag_base = {
            "album": book.title, "author": book.author, "narrator": book.narrator or _narrator_label(settings),
            "year": book.year, "language": book.language, "genre": book.genre or "Audiobook",
        }
        total_tracks = sum(1 for c in book.chapters if c.include_in_audio)
        track = sum(1 for c in book.chapters if c.include_in_audio and c.position <= position)
        cover = storage.read_bytes(book.cover_key) if book.cover_key and storage.exists(book.cover_key) else None
        chapter.audio_status = ChapterStatus.GENERATING
        chapter.audio_progress = 0.0
        chapter.audio_error = None

    if not plan.chunks:
        raise ChapterFailed(f"'{title}' has no readable text to narrate. Edit or exclude it in the Book Editor.", retryable=False)

    ocr_llm = None
    if settings.get("ai_ocr_repair"):
        from app.providers.llm import get_llm_provider

        ocr_llm = get_llm_provider()
        if ocr_llm and not ocr_llm.is_available()[0]:
            ocr_llm = None

    total = plan.chars
    done = 0
    timings: list[list] = []
    sources: set[str] = set()
    cursor = 0  # samples written
    started = time.monotonic()
    workers = chunk_parallelism(plan)
    work = Path(tempfile.mkdtemp(dir=tmp_dir(), prefix="chapter-"))
    raw = work / "chapter.raw"
    # Cloud MP3 voices: keep the provider's frames (no decode/re-encode) -- see mp3pass.
    passthrough = mp3_passthrough(plan, settings)
    mp3_out = work / "chapter.mp3"
    mp3_fmt: Mp3Format | None = None
    frames_written = 0

    def synth(chunk: Chunk):
        if ocr_llm is not None:
            chunk.sentences = [(llm_ocr_repair(t, ocr_llm), a, b) for t, a, b in chunk.sentences]
        if passthrough:
            return synthesize_chunk_mp3(chunk, settings, check)
        return synthesize_chunk(chunk, settings, rate, check)

    cached_chunks = 0
    try:
        # Chunks are synthesized concurrently (bounded window) but written strictly in
        # sequence order, so completion order never matters and memory stays flat.
        with open(mp3_out if passthrough else raw, "wb") as out, ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tts") as pool:
            if not passthrough:
                lead = silence(rate, 500)
                out.write(lead.tobytes())
                cursor += len(lead)
            prev_tail = 0.5  # the chapter opens with half a second of silence
            pending: deque = deque()
            chunks = iter(plan.chunks)

            def submit_next() -> None:
                chunk = next(chunks, None)
                if chunk is not None:
                    pending.append((chunk, pool.submit(synth, chunk)))

            for _ in range(workers * 2):
                submit_next()
            try:
                last_report = 0.0
                while pending:
                    chunk, future = pending.popleft()
                    submit_next()
                    # Status/progress writes at most ~once a second (chunks can finish
                    # dozens of times per second with fast cloud voices).
                    report = not pending or time.monotonic() - last_report >= 1.0
                    if check and report:
                        check()
                    if passthrough:
                        frames, count, fmt, times, source, was_cached = future.result()
                        if mp3_fmt is None:
                            mp3_fmt = fmt
                            lead_frames, n = mp3_silence(fmt, 0.5)
                            out.write(lead_frames)
                            frames_written += n
                        elif fmt != mp3_fmt:
                            raise ChapterFailed(f"'{title}': the voice service changed audio format mid-chapter. Retry this chapter.", retryable=True)
                        cached_chunks += int(was_cached)
                        sources.add(source)
                        # The provider's audio already starts/ends with some silence; only
                        # add what's missing to reach the intended pause.
                        duration = count * fmt.frame_seconds
                        lead_in = times[0][0] if source == "provider" and times else 0.0
                        gap_frames, n = mp3_silence(fmt, max(0.0, chunk.pause_before_ms / 1000 - prev_tail - lead_in))
                        out.write(gap_frames)
                        frames_written += n
                        offset = frames_written * fmt.frame_seconds
                        for (spoken, start, end), (t0, t1) in zip(chunk.sentences, times):
                            timings.append([chunk.paragraph, start, end, round(offset + t0, 3), round(offset + t1, 3)])
                        out.write(frames)
                        frames_written += count
                        prev_tail = max(0.0, duration - times[-1][1]) if source == "provider" and times else 0.0
                    else:
                        pcm, times, source, was_cached = future.result()
                        cached_chunks += int(was_cached)
                        sources.add(source)
                        gap = silence(rate, chunk.pause_before_ms)
                        out.write(gap.tobytes())
                        cursor += len(gap)
                        offset = cursor / rate
                        for (spoken, start, end), (t0, t1) in zip(chunk.sentences, times):
                            timings.append([chunk.paragraph, start, end, round(offset + t0, 3), round(offset + t1, 3)])
                        out.write(pcm.tobytes())
                        cursor += len(pcm)
                    done += chunk.chars
                    if report:
                        last_report = time.monotonic()
                        if on_progress:
                            on_progress(done, total)
                        best_effort_write(
                            lambda db: db.execute(update(Chapter).where(Chapter.id == chapter_id).values(audio_progress=round(done / total * 100, 1)))
                        )
            except BaseException:
                pool.shutdown(wait=True, cancel_futures=True)
                raise
            if passthrough and mp3_fmt is not None:
                tail_frames, n = mp3_silence(mp3_fmt, max(0.0, settings["chapter_pause_ms"] / 1000 - prev_tail))
                out.write(tail_frames)
                frames_written += n
            elif not passthrough:
                tail = silence(rate, settings["chapter_pause_ms"])
                out.write(tail.tobytes())
                cursor += len(tail)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    tts_seconds = time.monotonic() - started

    def finalize() -> dict:
        """Encode, tag, store and publish the chapter (can overlap the next chapter's synthesis)."""
        t0 = time.monotonic()
        fmt, bitrate = settings["format"], settings["bitrate"]
        try:
            if passthrough:
                # Already a finished MP3: just tag it.
                encoded = mp3_out
                duration = frames_written * mp3_fmt.frame_seconds
                bitrate = f"{mp3_fmt.bitrate_kbps}k"
            else:
                encoded = work / f"chapter.{fmt}"
                encode_raw(raw, rate, encoded, fmt, bitrate, normalize=settings["normalize"], target_lufs=s.audio_target_lufs, compress=settings["compress"])
                duration = cursor / rate
            write_tags(encoded, fmt, TagInfo(title=title, track=track, track_total=total_tracks, cover=cover, **tag_base))
            key = f"{book_prefix(book_id)}/audio/{new_storage_name(title, position, fmt)}"
            size = storage.save_file(key, encoded)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        timing_source = sources.pop() if len(sources) == 1 else "mixed"
        with session_scope() as db:
            for old in db.scalars(select(AudioAsset).where(AudioAsset.chapter_id == chapter_id, AudioAsset.kind == "chapter")):
                if old.storage_key != key:
                    storage.delete(old.storage_key)
                db.delete(old)
            db.flush()
            db.add(
                AudioAsset(
                    book_id=book_id, chapter_id=chapter_id, kind="chapter", storage_key=key, format=fmt, bitrate=bitrate,
                    sample_rate=mp3_fmt.rate if passthrough else rate, duration=duration, size_bytes=size, settings_hash=audio_hash, timings=timings,
                    timing_source=timing_source,
                    # handoff: made for a listener's device; the server may sweep it if never collected
                    meta={"mime": MIME[fmt], "warnings": plan.warnings, "passthrough": passthrough, "handoff": device_mode()},
                )
            )
            ch = db.get(Chapter, chapter_id)
            ch.audio_status = ChapterStatus.DONE
            ch.audio_progress = 100.0
            ch.audio_hash = audio_hash
            ch.duration = duration
            ch.audio_error = None
        encode_seconds = time.monotonic() - t0
        log.info(
            "chapter.completed", chapter_id=chapter_id, tts_seconds=round(tts_seconds, 1), encode_seconds=round(encode_seconds, 1),
            audio_seconds=round(duration, 1), chars=total, chunks=len(plan.chunks), cached_chunks=cached_chunks, workers=workers,
        )
        return {
            "duration": duration, "chars": total, "warnings": plan.warnings, "tts_seconds": tts_seconds,
            "encode_seconds": encode_seconds, "chunks": len(plan.chunks), "cached_chunks": cached_chunks, "workers": workers,
        }

    if finisher is not None:
        return finisher.submit(finalize)
    return finalize()



_AUTO_NARRATOR = re.compile(r"^.+ \((?:piper|sapi|edge|openai|elevenlabs|Piper|Windows voices|Microsoft Edge voices|OpenAI TTS|ElevenLabs)\)$")


def _is_auto_narrator(narrator: str | None) -> bool:
    """True when the credit is empty or one we generated (so a new voice updates it); a name the user typed is kept."""
    return not narrator or narrator == "AI narrator" or bool(_AUTO_NARRATOR.match(narrator))


def _narrator_label(settings: dict) -> str:
    """Human-readable narrator credit, e.g. "Lessac (Piper)"."""
    if not settings.get("voice_id"):
        return "AI narrator"
    try:
        provider = get_tts_provider(settings["provider"])
        engine = provider.display_name.split(" (")[0]
        voice = next((v for v in provider.list_voices() if v.id == settings["voice_id"]), None)
        if voice:
            return f"{voice.name} ({engine})"
        return f"{settings['voice_id']} ({engine})"
    except Exception:
        return settings["voice_id"]


# --------------------------------------------------------------------------- whole book


def chapter_is_current(db, chapter: Chapter, settings: dict) -> bool:
    if chapter.audio_status != ChapterStatus.DONE or not chapter.audio_hash:
        return False
    paragraphs = list(db.scalars(select(Paragraph).where(Paragraph.chapter_id == chapter.id).order_by(Paragraph.position)))
    cast = load_cast(db, chapter.book_id) if settings.get("cast_mode") else None
    if chapter_audio_hash(paragraphs, settings, chapter.title, cast) != chapter.audio_hash:
        return False
    asset = db.scalar(select(AudioAsset).where(AudioAsset.chapter_id == chapter.id, AudioAsset.kind == "chapter"))
    if asset is None:
        return False
    # Handed to the listener's device (and deleted here): still current, don't re-narrate.
    return on_device(asset) or get_storage().exists(asset.storage_key)


def generate_book(ctx) -> dict:
    """Job handler: generate every included chapter that isn't already current, then build the full audiobook."""
    payload = ctx.payload
    only = set(payload.get("chapter_ids") or [])
    force = bool(payload.get("force"))
    with session_scope() as db:
        book = db.get(Book, ctx.book_id)
        settings = narration_settings.resolve(book.narration, book.language)
        if not settings.get("voice_id"):
            raise StudioError("No narrator voice is selected. Choose a voice in Voice Studio first.", code="no_voice", retryable=False)
        _validate_voice(settings)
        chapters = [c for c in book.chapters if c.include_in_audio and (not only or c.id in only)]
        targets: list[tuple[str, str, int, int]] = []
        for c in chapters:
            if not force and chapter_is_current(db, c, settings):
                continue
            c.audio_status = ChapterStatus.QUEUED
            c.audio_progress = 0
            targets.append((c.id, c.title, c.position, c.char_count))
        book.status = BookStatus.GENERATING
        book.error = None
        all_positions = [c.position for c in chapters]

    total_chars = sum(t[3] for t in targets) or 1
    ctx.update(stage="generating", total_chapters=len(targets), progress=0.0, message=f"{len(targets)} chapter(s) to generate")
    ctx.set_stage("prepare", "done")
    ctx.set_stage("chapters", "active")
    done_chars = 0
    failures: list[dict] = []
    started = time.monotonic()
    telemetry = {"chars": 0, "audio_seconds": 0.0, "tts_seconds": 0.0, "encode_seconds": 0.0, "chunks": 0, "cached_chunks": 0, "workers": 0}
    finishing: list[tuple[str, str, Future]] = []

    def fail_chapter(chapter_id: str, title: str, exc: StudioError) -> None:
        message = f"VOXORA couldn't generate {title}: {exc.message}"
        if exc.retryable:
            message += f" Your previous chapters are safe; generation will resume from {title}."
        else:
            message += f" Your previous chapters are safe. You can retry {title} without starting over."
        with session_scope() as db:
            ch = db.get(Chapter, chapter_id)
            ch.audio_status = ChapterStatus.FAILED
            ch.audio_error = {**exc.to_dict(), "message": message}
        if exc.retryable:
            raise _with_message(exc, message)
        failures.append({"chapter_id": chapter_id, "title": title, "error": message})

    def collect(entry: tuple[str, str, Future]) -> None:
        chapter_id, title, future = entry
        try:
            r = future.result()
        except StudioError as exc:
            fail_chapter(chapter_id, title, exc)
            return
        for k in ("chars", "tts_seconds", "encode_seconds", "chunks", "cached_chunks"):
            telemetry[k] += r.get(k, 0)
        telemetry["audio_seconds"] += r.get("duration", 0.0)
        telemetry["workers"] = max(telemetry["workers"], r.get("workers", 0))

    # Several chapters synthesize at once for cloud voices (their requests share the
    # provider's adaptive limiter, so the service always has work queued even across
    # chapter boundaries); local engines stay one chapter at a time, since they
    # already use every core. Finished chapters encode in the background while the
    # next ones synthesize.
    chapter_workers = chapter_parallelism(settings, len(targets))
    partial: dict[str, float] = {}
    progress_lock = threading.Lock()
    started_count = 0

    def progress_for(chapter_id: str, chars: int):
        def progress(done: int, total: int) -> None:
            with progress_lock:
                partial[chapter_id] = chars * done / max(total, 1)
                fraction = min(1.0, (done_chars + sum(partial.values())) / total_chars)
            elapsed = time.monotonic() - started
            eta = int(elapsed / fraction * (1 - fraction)) if fraction > 0.03 and elapsed > 20 else None
            ctx.update(progress=round(fraction * 100, 1), result={"eta_seconds": eta, "telemetry": telemetry, "chapter_workers": chapter_workers})

        return progress

    def run_one(chapter_id: str, title: str, chars: int) -> Future:
        nonlocal started_count
        ctx.check()
        with progress_lock:
            started_count += 1
            n = started_count
        ctx.update(current_chapter=n, message=f"Generating {title}")
        log.info("chapter.started", book_id=ctx.book_id, chapter_id=chapter_id, title=title)
        return generate_chapter(chapter_id, settings, check=ctx.check, on_progress=progress_for(chapter_id, chars), finisher=finisher)

    with ThreadPoolExecutor(max_workers=encode_parallelism(not get_tts_provider(settings["provider"]).is_local), thread_name_prefix="encode") as finisher:
        chapters_pool = ThreadPoolExecutor(max_workers=chapter_workers, thread_name_prefix="chapter")
        try:
            running = [(chapter_id, title, chars, chapters_pool.submit(run_one, chapter_id, title, chars)) for chapter_id, title, _pos, chars in targets]
            # Consume in book order: bookkeeping stays sequential and deterministic.
            for chapter_id, title, chars, fut in running:
                try:
                    finishing.append((chapter_id, title, fut.result()))
                except StudioError as exc:
                    fail_chapter(chapter_id, title, exc)
                with progress_lock:
                    partial.pop(chapter_id, None)
                    done_chars += chars
                    fraction = min(1.0, (done_chars + sum(partial.values())) / total_chars)
                # Collect chapters whose encoding already finished (keeps errors timely).
                while finishing and finishing[0][2].done():
                    collect(finishing.pop(0))
                ctx.update(progress=round(fraction * 100, 1))
        except BaseException as exc:
            # Stop starting chapters; let running ones notice the pause/failure and stop.
            chapters_pool.shutdown(wait=True, cancel_futures=True)
            if isinstance(exc, JobCancelled):
                with session_scope() as db:
                    for ch in db.scalars(select(Chapter).where(Chapter.book_id == ctx.book_id, Chapter.audio_status == ChapterStatus.GENERATING)):
                        ch.audio_status = ChapterStatus.PENDING
                _reset_queued(ctx.book_id)
            raise
        finally:
            chapters_pool.shutdown(wait=True, cancel_futures=True)
            # Always let in-flight encodes finish so finished chapters are published.
            pending, finishing[:] = list(finishing), []
            for entry in pending:
                try:
                    collect(entry)
                except StudioError:
                    pass
    wall = time.monotonic() - started
    telemetry.update(
        wall_seconds=round(wall, 1),
        realtime_factor=round(telemetry["audio_seconds"] / wall, 2) if wall > 0 else None,
        chars_per_second=round(telemetry["chars"] / wall, 1) if wall > 0 else None,
        provider=settings["provider"],
        voice=settings["voice_id"],
    )
    log.info("generation.telemetry", book_id=ctx.book_id, **{k: (round(v, 1) if isinstance(v, float) else v) for k, v in telemetry.items()})

    ctx.set_stage("chapters", "failed" if failures and len(failures) == len(targets) else "done")
    ctx.set_stage("build", "active")
    full = None
    # In device mode the listener's browser assembles the full book from its chapters.
    if settings.get("build_full_audiobook") and not device_mode():
        ctx.update(stage="building", message="Building the complete audiobook")
        full = build_full_audiobook(ctx.book_id, settings)
    ctx.set_stage("build", "done")

    with session_scope() as db:
        book = db.get(Book, ctx.book_id)
        durations = [c.duration or 0 for c in book.chapters if c.include_in_audio and c.audio_status == ChapterStatus.DONE]
        book.total_duration = sum(durations) or None
        if _is_auto_narrator(book.narrator):
            book.narrator = _narrator_label(settings)
        if failures:
            book.error = {"code": "chapters_failed", "message": f"{len(failures)} chapter(s) failed. Retry them from the book page.", "details": failures}
        book.status = BookStatus.READY if durations else BookStatus.FAILED
    if failures and not full and not durations:
        raise StudioError(failures[0]["error"], code="chapters_failed", retryable=False)
    generated = len(targets) - len(failures)
    ctx.update(
        message=(f"{generated} chapter(s) generated, {len(failures)} failed." if failures else f"{generated} chapter(s) generated." if generated else "Everything was already up to date; nothing needed regenerating.")
    )
    return {"chapters_generated": len(targets) - len(failures), "failures": failures, "full_audiobook": bool(full), "positions": all_positions, "telemetry": telemetry}


def _with_message(exc: StudioError, message: str) -> StudioError:
    exc.message = message
    exc.args = (message,)
    return exc


def _reset_queued(book_id: str) -> None:
    with session_scope() as db:
        for c in db.scalars(select(Chapter).where(Chapter.book_id == book_id, Chapter.audio_status == ChapterStatus.QUEUED)):
            c.audio_status = ChapterStatus.PENDING


def _validate_voice(settings: dict) -> None:
    provider = get_tts_provider(settings["provider"])
    ok, reason = provider.is_available()
    if not ok:
        raise ProviderError(provider.name, reason or f"{provider.display_name} is unavailable.", retryable=False, code="provider_unavailable")
    if settings["provider"] == "piper" and not any(v.id == settings["voice_id"] for v in provider.list_voices()):
        raise UnsupportedLanguageError(f"The Piper voice '{settings['voice_id']}' is not installed. Install it in Voice Studio.")


def assemble_full_audiobook(book_id: str, settings: dict, out: Path) -> tuple[float, list[ChapterMark]] | None:
    """Join every included chapter into one tagged file with chapter markers at `out`.
    None until every included chapter has audio (or formats differ). Frame-level MP3
    joins take seconds, so this also serves on-demand downloads."""
    storage = get_storage()
    with session_scope(write=False) as db:
        book = db.get(Book, book_id)
        rows = []
        for c in book.chapters:
            if not c.include_in_audio:
                continue
            asset = db.scalar(select(AudioAsset).where(AudioAsset.chapter_id == c.id, AudioAsset.kind == "chapter"))
            if asset is None or not storage.exists(asset.storage_key):
                return None
            rows.append((c.title, asset.storage_key, asset.duration, asset.format))
        if not rows:
            return None
        info = TagInfo(
            title=book.title, album=book.title, author=book.author, narrator=book.narrator or _narrator_label(settings),
            year=book.year, language=book.language, genre=book.genre or "Audiobook",
            cover=storage.read_bytes(book.cover_key) if book.cover_key and storage.exists(book.cover_key) else None,
        )
    fmt = rows[0][3]
    if any(r[3] != fmt for r in rows):
        return None
    inputs = [storage.local_path(r[1]) for r in rows]
    durations = [r[2] for r in rows]
    if fmt == "mp3":
        # Frame-level join: seconds instead of minutes, with exact chapter offsets.
        try:
            durations = join_mp3(inputs, out)
        except ValueError as exc:
            log.warning("full_audiobook.fast_join_unavailable", book_id=book_id, reason=str(exc))
            concat_files(inputs, out, fmt, settings["bitrate"])
    else:
        concat_files(inputs, out, fmt, settings["bitrate"])
    marks, t = [], 0.0
    for (title, _key, _duration, _fmt), duration in zip(rows, durations):
        marks.append(ChapterMark(title, t, t + duration))
        t += duration
    write_tags(out, fmt, info, marks)
    return t, marks


def build_full_audiobook(book_id: str, settings: dict) -> str | None:
    """Store a permanent complete-audiobook file (opt-in: it duplicates the chapter
    audio; the download endpoint otherwise assembles one on demand)."""
    storage = get_storage()
    work = Path(tempfile.mkdtemp(dir=tmp_dir(), prefix="full-"))
    try:
        out = work / f"full.{settings['format']}"
        built = assemble_full_audiobook(book_id, settings, out)
        if built is None:
            return None
        t, marks = built
        fmt = out.suffix.lstrip(".")
        key = f"{book_prefix(book_id)}/audio/full-audiobook.{fmt}"
        size = storage.save_file(key, out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    with session_scope() as db:
        for old in db.scalars(select(AudioAsset).where(AudioAsset.book_id == book_id, AudioAsset.kind == "full")):
            if old.storage_key != key:
                storage.delete(old.storage_key)
            db.delete(old)
        db.flush()
        db.add(AudioAsset(book_id=book_id, kind="full", storage_key=key, format=fmt, bitrate=settings["bitrate"], duration=t, size_bytes=size, meta={"chapters": [[m.title, m.start, m.end] for m in marks]}))
    return key


def estimate(book: Book, settings: dict, chapter_ids: list[str] | None = None) -> dict:
    chars = sum(c.char_count for c in book.chapters if c.include_in_audio and (not chapter_ids or c.id in chapter_ids))
    provider = get_tts_provider(settings["provider"])
    words = chars / 5.7
    return {
        "characters": chars,
        "estimated_audio_minutes": round(words / (155 * settings["speed"]), 1),
        "provider": provider.name,
        "is_local": provider.is_local,
        "cost": provider.estimate_cost(chars),
        "privacy_note": provider.privacy_note,
    }


def export_m4b(ctx) -> dict:
    """Job handler: build an M4B audiobook (AAC, chapter markers, cover, tags) from the chapter files."""
    storage = get_storage()
    with session_scope() as db:
        book = db.get(Book, ctx.book_id)
        settings = narration_settings.resolve(book.narration, book.language)
        rows = []
        for c in book.chapters:
            if not c.include_in_audio:
                continue
            asset = db.scalar(select(AudioAsset).where(AudioAsset.chapter_id == c.id, AudioAsset.kind == "chapter"))
            if asset and storage.exists(asset.storage_key):
                rows.append((c.title, asset.storage_key, asset.duration))
        if not rows:
            raise StudioError("There's no chapter audio yet. Create the audiobook first.", code="no_audio", retryable=False)
        info = TagInfo(
            title=book.title, album=book.title, author=book.author, narrator=book.narrator or _narrator_label(settings),
            year=book.year, language=book.language, genre=book.genre or "Audiobook",
            cover=storage.read_bytes(book.cover_key) if book.cover_key and storage.exists(book.cover_key) else None,
        )
        slug = new_storage_name(book.title, 0, "m4b").split("-", 1)[-1]
    ctx.update(stage="encoding", message=f"Encoding {len(rows)} chapters to M4B", progress=5.0)
    started = time.monotonic()
    work = Path(tempfile.mkdtemp(dir=tmp_dir(), prefix="m4b-"))
    try:
        out = work / "book.m4a"
        concat_files([storage.local_path(r[1]) for r in rows], out, "m4a", settings["bitrate"] if settings["bitrate"] != "48k" else "64k")
        ctx.update(progress=85.0, message="Adding chapter markers and cover")
        marks, t = [], 0.0
        for title, _key, duration in rows:
            marks.append(ChapterMark(title, t, t + duration))
            t += duration
        write_tags(out, "m4a", info, marks)
        key = f"{book_prefix(ctx.book_id)}/audio/{slug}"
        size = storage.save_file(key, out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    with session_scope() as db:
        for old in db.scalars(select(AudioAsset).where(AudioAsset.book_id == ctx.book_id, AudioAsset.kind == "m4b")):
            if old.storage_key != key:
                storage.delete(old.storage_key)
            db.delete(old)
        db.flush()
        db.add(AudioAsset(book_id=ctx.book_id, kind="m4b", storage_key=key, format="m4b", bitrate=settings["bitrate"], duration=t, size_bytes=size, meta={"chapters": [[m.title, m.start, m.end] for m in marks]}))
    seconds = round(time.monotonic() - started, 1)
    log.info("m4b.built", book_id=ctx.book_id, chapters=len(rows), audio_seconds=round(t), seconds=seconds, bytes=size)
    return {"chapters": len(rows), "duration": t, "size": size, "seconds": seconds}
