"""AI Cast (experimental): find dialogue, attribute speakers, assign voices.

The story text is never changed. We only store *spans* over each paragraph
(`[{start, end, speaker}]`) marking quoted dialogue, which generation uses to
switch voices.

Attribution runs in two layers:
1. Heuristics: speech verbs next to quotes ("...," said Mara / Tomas asked, "..."),
   pronoun fallback to the most recent character of that gender, and turn-taking
   for unattributed back-and-forth dialogue.
2. Optional LLM refinement (when an LLM is configured) that re-attributes
   quotes per chapter from context. Its output is validated: it may only assign
   speakers to quotes we found, never edit text.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from sqlalchemy import delete, select, update

from app.core.logging import get_logger
from app.db.session import session_scope
from app.models import Book, CastMember, Chapter, Paragraph
from app.providers.tts import get_tts_provider

log = get_logger(__name__)

QUOTE_RE = re.compile(r"“[^”]{1,2000}”|\"[^\"]{1,2000}\"|«[^»]{1,2000}»|‘[^’]{3,2000}’(?=\s|[,.;:!?]|$)")
SAID = (
    r"said|asked|replied|answered|whispered|shouted|cried|called|muttered|murmured|added|continued|began|"
    r"exclaimed|yelled|snapped|sighed|laughed|told|insisted|protested|demanded|warned|agreed|admitted|"
    r"explained|repeated|breathed|pleaded|growled|remarked|responded|observed|declared|announced"
)
NAME = r"(?:(?:Mr|Mrs|Ms|Dr|Prof|Old|Young|Captain|Lady|Lord|Sir|Aunt|Uncle)\.?\s+)?[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?"
AFTER_NAME_VERB = re.compile(rf"^\s*[,!?]?\s*(?P<name>{NAME})\s+(?:{SAID})\b")
AFTER_VERB_NAME = re.compile(rf"^\s*[,!?]?\s*(?:{SAID})\s+(?P<name>{NAME})\b")
AFTER_PRONOUN = re.compile(rf"^\s*[,!?]?\s*(?P<pron>he|she|they)\s+(?:{SAID})\b", re.I)
BEFORE_NAME = re.compile(rf"(?P<name>{NAME})\s+(?:{SAID})(?:\s+\w+){{0,3}}\s*[,:]?\s*$")
BEFORE_PRONOUN = re.compile(rf"\b(?P<pron>He|She|They|he|she|they)\s+(?:{SAID})(?:\s+\w+){{0,3}}\s*[,:]?\s*$")
NOT_NAMES = {
    "The", "A", "An", "And", "But", "Then", "When", "If", "Yes", "No", "Oh", "Well", "It", "This", "That", "There",
    "He", "She", "They", "We", "I", "You", "His", "Her", "Their", "Chapter", "Part", "Not", "What", "Why", "How",
}
MALE = re.compile(r"\b(he|him|his|himself|Mr|Sir|Lord|Uncle|brother|father|king|man|boy)\b")
FEMALE = re.compile(r"\b(she|her|hers|herself|Mrs|Ms|Miss|Lady|Aunt|sister|mother|queen|woman|girl)\b")


def _clean_name(name: str | None) -> str | None:
    if not name:
        return None
    parts = name.split()
    if parts and parts[0] in NOT_NAMES:
        return None
    return name.strip()


def attribute_paragraphs(paragraphs: list[Paragraph]) -> tuple[dict[str, list[dict]], Counter, dict[str, Counter]]:
    """Returns ({paragraph_id: spans}, line counts, gender evidence per name)."""
    spans_by_para: dict[str, list[dict]] = {}
    lines: Counter = Counter()
    gender: dict[str, Counter] = defaultdict(Counter)
    last_named: dict[str, str] = {}  # pronoun -> last character name of that gender
    last_speakers: list[str] = []
    for p in paragraphs:
        if p.kind == "heading":
            continue
        text = p.text
        quotes = list(QUOTE_RE.finditer(text))
        if not quotes:
            # Narration mentioning a name next to a pronoun gives gender evidence.
            for m in re.finditer(NAME, text):
                n = _clean_name(m.group(0))
                if n:
                    window = text[m.end(): m.end() + 80]
                    if MALE.search(window):
                        gender[n]["male"] += 1
                    elif FEMALE.search(window):
                        gender[n]["female"] += 1
            last_speakers = last_speakers[-2:]
            continue
        speaker: str | None = None
        for q in quotes:
            after = text[q.end(): q.end() + 60]
            before = text[max(0, q.start() - 80): q.start()]
            name = None
            pron = None
            if m := AFTER_NAME_VERB.match(after):
                name = _clean_name(m.group("name"))
            elif m := AFTER_VERB_NAME.match(after):
                name = _clean_name(m.group("name"))
            elif m := BEFORE_NAME.search(before):
                name = _clean_name(m.group("name"))
            elif m := AFTER_PRONOUN.match(after):
                pron = m.group("pron").lower()
            elif m := BEFORE_PRONOUN.search(before):
                pron = m.group("pron").lower()
            if name:
                speaker = name
            elif pron in ("he", "she"):
                speaker = last_named.get(pron) or speaker
            if speaker:
                g = "male" if pron == "he" else "female" if pron == "she" else None
                if g:
                    gender[speaker][g] += 2
                context = text[max(0, q.start() - 200): q.end() + 200]
                if MALE.search(context) and not FEMALE.search(context):
                    gender[speaker]["male"] += 1
                elif FEMALE.search(context) and not MALE.search(context):
                    gender[speaker]["female"] += 1
        if speaker is None and len(last_speakers) >= 2:
            # Turn-taking: an unattributed reply goes to the other participant.
            speaker = last_speakers[-2]
        speaker = speaker or "Unknown"
        spans = [{"start": q.start(), "end": q.end(), "speaker": speaker} for q in quotes]
        spans_by_para[p.id] = spans
        lines[speaker] += len(quotes)
        if speaker != "Unknown":
            if not last_speakers or last_speakers[-1] != speaker:
                last_speakers.append(speaker)
            g = gender[speaker].most_common(1)
            if g:
                last_named["he" if g[0][0] == "male" else "she"] = speaker
    return spans_by_para, lines, gender


LLM_SYSTEM = (
    "You identify who speaks each line of quoted dialogue in a novel excerpt. You never change or rewrite text. "
    "Use only names that appear in the excerpt. If the speaker cannot be determined, use \"Unknown\"."
)
LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "quotes": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "integer"}, "speaker": {"type": "string"}}}},
        "characters": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "gender": {"type": "string", "enum": ["male", "female", "unknown"]}}}},
    },
}


def refine_with_llm(llm, paragraphs: list[Paragraph], spans_by_para: dict[str, list[dict]]) -> dict[str, str]:
    """Ask the LLM to (re)attribute quotes. Returns {name: gender}. Mutates spans in place."""
    from app.providers.llm import ChatMessage

    genders: dict[str, str] = {}
    items: list[tuple[str, int]] = []  # (paragraph id, span index)
    lines: list[str] = []
    budget = 0
    batches: list[tuple[list[tuple[str, int]], str]] = []
    for p in paragraphs:
        spans = spans_by_para.get(p.id)
        text = p.text
        if spans:
            marked = text
            for i, s in sorted(enumerate(spans), key=lambda x: -x[1]["start"]):
                items.append((p.id, i))
                marked = marked[: s["start"]] + f"[Q{len(items) - 1}]" + marked[s["start"]:]
            lines.append(marked)
        else:
            lines.append(text)
        budget += len(text)
        if budget > 9000:
            batches.append((items, "\n\n".join(lines)))
            items, lines, budget = [], [], 0
    if items:
        batches.append((items, "\n\n".join(lines)))
    for batch_items, excerpt in batches:
        prompt = (
            f"Excerpt (each quote is preceded by a marker like [Q0]):\n\n{excerpt}\n\n"
            f"For every marker Q0..Q{len(batch_items) - 1}, give the speaker's name. Also list the characters who speak, with gender if the text makes it clear."
        )
        try:
            data = llm.complete_json(LLM_SYSTEM, [ChatMessage("user", prompt)], LLM_SCHEMA, max_tokens=3000)
        except Exception as exc:
            log.warning("cast.llm_failed", error=str(exc)[:200])
            continue
        # Markers were numbered in reverse per paragraph; map ids back.
        for q in data.get("quotes", []):
            idx = q.get("id")
            name = (q.get("speaker") or "").strip()[:80]
            if isinstance(idx, int) and 0 <= idx < len(batch_items) and name:
                pid, span_i = batch_items[idx]
                spans_by_para[pid][span_i]["speaker"] = name
        for c in data.get("characters", []):
            if c.get("name") and c.get("gender") in ("male", "female"):
                genders[c["name"].strip()] = c["gender"]
    return genders


def analyze_cast(ctx) -> dict:
    """Job handler: detect dialogue across the book and build the cast."""
    use_llm = bool(ctx.payload.get("use_llm"))
    llm = None
    if use_llm:
        from app.providers.llm import get_llm_provider

        llm = get_llm_provider()
        if llm is None or not llm.is_available()[0]:
            llm = None
    with session_scope() as db:
        book = db.get(Book, ctx.book_id)
        chapter_ids = [c.id for c in book.chapters if c.include_in_audio]
        book_language = book.language
        narration = dict(book.narration or {})
    total_lines: Counter = Counter()
    evidence: dict[str, Counter] = defaultdict(Counter)
    llm_genders: dict[str, str] = {}
    for n, cid in enumerate(chapter_ids):
        ctx.check()
        ctx.update(progress=round(n / max(len(chapter_ids), 1) * 90, 1), message=f"Finding dialogue in chapter {n + 1} of {len(chapter_ids)}")
        with session_scope(write=False) as db:
            paragraphs = list(db.scalars(select(Paragraph).where(Paragraph.chapter_id == cid).order_by(Paragraph.position)))
            db.expunge_all()
        spans, lines, gender = attribute_paragraphs(paragraphs)
        if llm is not None and spans:
            llm_genders.update(refine_with_llm(llm, paragraphs, spans))
            lines = Counter(s["speaker"] for ss in spans.values() for s in ss)
        with session_scope() as db:
            for pid, pspans in ((p.id, spans.get(p.id)) for p in paragraphs):
                db.execute(update(Paragraph).where(Paragraph.id == pid).values(spans=pspans))
            total_lines.update(lines)
            for k, v in gender.items():
                evidence[k].update(v)

    # Characters with a single line are usually misattributions; fold them into Unknown.
    cast_names = [n for n, c in total_lines.most_common() if n != "Unknown" and (c >= 2 or len(total_lines) < 6)][:24]
    from app.services.narration_settings import resolve

    settings = resolve(narration, book_language)
    voices = _candidate_voices(settings["provider"], book_language)
    with session_scope() as db:
        existing = {m.name: m for m in db.scalars(select(CastMember).where(CastMember.book_id == ctx.book_id))}
        db.execute(delete(CastMember).where(CastMember.book_id == ctx.book_id, CastMember.auto_assigned.is_(True)))
        db.flush()
        used = {settings["voice_id"]}
        members = [("Narrator", "narrator", None, 0)]
        for name in cast_names:
            g = llm_genders.get(name) or (evidence[name].most_common(1)[0][0] if evidence[name] else None)
            members.append((name, "character", g, total_lines[name]))
        if total_lines.get("Unknown"):
            members.append(("Unknown", "unknown", None, total_lines["Unknown"]))
        for name, role, g, count in members:
            kept = existing.get(name)
            if kept is not None and not kept.auto_assigned:
                kept.line_count = count
                continue
            if role == "narrator":
                provider, voice = settings["provider"], settings["voice_id"]
            else:
                provider, voice = settings["provider"], _pick_voice(voices, g, used)
                used.add(voice)
            db.add(CastMember(book_id=ctx.book_id, name=name, role=role, gender_hint=g, line_count=count, provider=provider, voice_id=voice, auto_assigned=True))
    ctx.update(progress=100, message=f"Found {len(cast_names)} speaking characters")
    return {"characters": len(cast_names), "dialogue_lines": sum(total_lines.values()), "used_llm": llm is not None}


def _candidate_voices(provider: str, language: str | None) -> list:
    try:
        voices = [v for v in get_tts_provider(provider).list_voices() if v.installed]
    except Exception:
        return []
    same_lang = [v for v in voices if v.language == (language or "en")]
    return same_lang or [v for v in voices if "mul" in v.languages]


def _pick_voice(voices: list, gender: str | None, used: set[str]) -> str | None:
    if not voices:
        return None
    pools = [
        [v for v in voices if v.id not in used and gender and v.gender == gender],
        [v for v in voices if v.id not in used and (not gender or v.gender in (None, gender))],
        [v for v in voices if v.id not in used],
        voices,
    ]
    for pool in pools:
        if pool:
            return pool[0].id
    return None


def cast_summary(db, book_id: str) -> list[CastMember]:
    return list(db.scalars(select(CastMember).where(CastMember.book_id == book_id).order_by(CastMember.role.desc(), CastMember.line_count.desc())))


def dialogue_preview(db, chapter: Chapter, limit: int = 12) -> list[dict]:
    out = []
    for p in db.scalars(select(Paragraph).where(Paragraph.chapter_id == chapter.id).order_by(Paragraph.position)):
        for s in p.spans or []:
            out.append({"speaker": s["speaker"], "text": p.text[s["start"]: s["end"]], "paragraph": p.position})
            if len(out) >= limit:
                return out
    return out
