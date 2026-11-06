"""Book structure detection: title/author and chapter boundaries.

Strategies, in order of trust:
  1. `epub`     - the publisher's spine documents + table of contents
  2. `outline`  - a PDF's bookmarks/outline
  3. `headings` - chapter patterns ("Chapter 7", "CHAPTER SEVEN", "PART II",
                  "Prologue", Indic chapter words) and font/style headings
  4. `numbered` - "1. The Beginning" style titles, accepted only as a 1,2,3... sequence
  5. `length`   - fallback split at paragraph boundaries, flagged for review

Tables of contents inside the body (runs of chapter titles with no text between
them) are recognised and never used as split points.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.document_processing.base import Block, ExtractedDocument
from app.document_processing.content_modes import included
from app.document_processing.segmentation import word_count

_UNITS = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
_ORDINALS = "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth".split()
NUM_WORD = r"(?:(?:%s)(?:[-\s](?:%s))?|%s|%s)" % ("|".join(_TENS), "|".join(_UNITS[:9]), "|".join(_UNITS), "|".join(_ORDINALS))
NUMBER = rf"(?:\d{{1,3}}|[ivxlcdm]{{1,8}}|{NUM_WORD})"
CHAPTER_WORDS = (
    r"(?:chapter|chap\.?|kapitel|chapitre|cap[ií]tulo|capitolo|hoofdstuk|"
    r"అధ్యాయం|అధ్యాయము|अध्याय|அத்தியாயம்|ಅಧ್ಯಾಯ|അധ്യായം|অধ্যায়|प्रकरण|પ્રકરણ|ਅਧਿਆਇ)"
)
STRONG_CHAPTER = re.compile(rf"^\s*{CHAPTER_WORDS}\s*[-–—:.]?\s*{NUMBER}\b\s*[.:\-–—]?\s*(?P<rest>.*)$", re.I)
INDIC_NUM_CHAPTER = re.compile(rf"^\s*[\d०-९௦-௯౦-౯೦-೯൦-൯]+\s*\S{{0,3}}\s*{CHAPTER_WORDS}", re.I)
PART = re.compile(rf"^\s*(?:part|book|volume|section|భాగం|भाग)\s+{NUMBER}\b\s*[.:\-–—]?\s*(?P<rest>.*)$", re.I)
SPECIAL = re.compile(
    r"^\s*(prologue|epilogue|preface|foreword|introduction|afterword|acknowledge?ments?|dedication|"
    r"(?:table of )?contents|appendix(?:\s+[a-z0-9]{1,4})?|glossary|index|bibliography|references|endnotes|notes|"
    r"about the authors?|interlude|conclusion|postscript|author'?s note|a note on .{1,40}|copyright|epigraph)\s*[.:]?\s*(?P<rest>.*)$",
    re.I,
)
NUMBERED_TITLE = re.compile(r"^\s*(?P<num>\d{1,3})\s*[.)]\s+(?P<title>[^\W\d_][^\n]{0,80})$")
DOT_LEADER = re.compile(r"(?:\s*\.{2,}\s*|\s{3,}|\t+)\s*(\d{1,4}|[ivxlc]{1,6})\s*$", re.I)
BY_LINE = re.compile(r"^\s*by\s+(?P<name>[^\W\d_][\w.'\- ]{2,80})$", re.I)

KIND_RULES: list[tuple[re.Pattern, str, bool]] = [
    (re.compile(r"^(table of )?contents\b", re.I), "toc", False),
    (re.compile(r"^(copyright|all rights reserved)", re.I), "copyright", False),
    (re.compile(r"^title page\b", re.I), "title_page", False),
    (re.compile(r"^dedication", re.I), "dedication", True),
    (re.compile(r"^epigraph", re.I), "epigraph", True),
    (re.compile(r"^foreword", re.I), "foreword", True),
    (re.compile(r"^(preface|author'?s note|a note on)", re.I), "preface", True),
    (re.compile(r"^introduction", re.I), "introduction", True),
    (re.compile(r"^prologue", re.I), "prologue", True),
    (re.compile(r"^(epilogue|postscript|conclusion)", re.I), "epilogue", True),
    (re.compile(r"^afterword", re.I), "afterword", True),
    (re.compile(r"^appendix", re.I), "appendix", True),
    (re.compile(r"^glossary", re.I), "glossary", True),
    (re.compile(r"^(index|bibliography|references|works cited|endnotes|notes)\b", re.I), "bibliography", False),
    (re.compile(r"^((more|other) books by|also by|books by|praise for|coming soon|excerpt from)\b", re.I), "advertisement", False),
    (re.compile(r"^acknowledge?ments?", re.I), "acknowledgements", True),
    (re.compile(r"^about the authors?", re.I), "author_bio", True),
    (re.compile(r"^(part|book|volume)\b", re.I), "part", True),
]

MIN_CHAPTER_WORDS = 120  # sections smaller than this between two candidates suggest a TOC listing


@dataclass
class DetectedChapter:
    title: str
    kind: str
    blocks: list[Block]
    include_in_audio: bool = True
    detection: dict = field(default_factory=dict)

    @property
    def words(self) -> int:
        return sum(word_count(b.text) for b in self.blocks)


@dataclass
class BookStructure:
    title: str
    subtitle: str | None
    author: str | None
    chapters: list[DetectedChapter]
    method: str
    warnings: list[str] = field(default_factory=list)


def clean_title(text: str) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    t = DOT_LEADER.sub("", t).strip(" .:-–—")
    return t[:200]


def classify(title: str, blocks: list[Block] | None = None) -> tuple[str, bool]:
    t = clean_title(title)
    for pattern, kind, include in KIND_RULES:
        if pattern.match(t):
            return kind, include
    if blocks is not None:
        body = " ".join(b.text for b in blocks[:40])
        if re.search(r"all rights reserved|isbn[\s:-]*[\dx-]{10,}|copyright\s*(?:©|\(c\))", body, re.I) and word_count(body) < 400:
            return "copyright", False
    return "chapter", True


def heading_score(block: Block) -> tuple[float, str | None]:
    """How likely is this block a chapter-level heading? Returns (score, pattern)."""
    text = block.text.strip()
    if not text or len(text) > 160 or "\n" in text.strip() and len(text) > 100:
        return 0.0, None
    first_line = clean_title(text.split("\n")[0])
    standalone = block.is_heading or block.meta.get("heading_candidate") or len(text) < 90
    if not standalone:
        return 0.0, None
    if STRONG_CHAPTER.match(first_line) or INDIC_NUM_CHAPTER.match(first_line):
        return 0.95, "chapter"
    if PART.match(first_line) and len(first_line) < 80:
        return 0.9, "part"
    if SPECIAL.match(first_line) and len(first_line) < 60 and not first_line.endswith((",", ";")):
        rest = SPECIAL.match(first_line).group("rest")
        if not rest or len(rest) < 50:
            return 0.85 if block.is_heading or block.meta.get("heading_candidate") else 0.6, "special"
    if NUMBERED_TITLE.match(first_line) and not first_line.endswith("."):
        return 0.4, "numbered"
    if block.is_heading:
        if block.meta.get("weak"):
            return 0.3, "styled"
        return 0.5, "heading"
    if block.meta.get("heading_candidate") and first_line.isupper() and 3 <= len(first_line) <= 60:
        return 0.35, "caps"
    return 0.0, None


def _norm_title(block: Block) -> str:
    return re.sub(r"\W+", " ", clean_title(block.text.split("\n")[0]).lower()).strip()


_CONTENTS = re.compile(r"^\s*(table of )?contents\b", re.I)


def _toc_runs(indices: list[int], blocks: list[Block]) -> set[int]:
    """Candidate indices that belong to a table-of-contents listing.

    A run is a sequence of >= 3 heading candidates with almost no text between
    them. It is only treated as a TOC when it follows a "Contents" heading or
    most of its titles reappear later in the body. The run ends at the first
    title that repeats (that is where the body starts)."""
    runs: list[list[int]] = []
    run: list[int] = []
    for a, b in zip(indices, indices[1:]):
        gap = sum(word_count(blocks[k].text) for k in range(a + 1, b))
        if gap < 25:
            if not run:
                run.append(a)
            run.append(b)
        else:
            if len(run) >= 3:
                runs.append(run)
            run = []
    if len(run) >= 3:
        runs.append(run)

    toc: set[int] = set()
    for run in runs:
        titles = [_norm_title(blocks[i]) for i in run]
        cut = len(run)
        for k, t in enumerate(titles):
            if t and t in titles[:k]:
                cut = k
                break
        # A part heading right before the first repeated title belongs to the body.
        while 0 < cut < len(run) and PART.match(clean_title(blocks[run[cut - 1]].text)) and titles[cut - 1] not in titles[: cut - 1]:
            cut -= 1
        listing = run[:cut]
        if not listing:
            continue
        later = {_norm_title(blocks[i]) for i in indices if i > listing[-1]}
        contents_at = next((k for k, i in enumerate(listing) if _CONTENTS.match(blocks[i].text)), None)
        if contents_at is not None:
            # After a "Contents" heading, entries that reappear later are the listing.
            toc.update(i for i in listing[contents_at + 1 :] if _norm_title(blocks[i]) in later)
            continue
        repeated = sum(1 for i in listing if _norm_title(blocks[i]) in later)
        if len(listing) >= 3 and repeated >= len(listing) / 2:
            toc.update(listing)
    return toc


def _merge_title_lines(blocks: list[Block], idx: int, pattern: str | None) -> tuple[str, int]:
    """'CHAPTER ONE' + next heading 'The Beginning' -> 'Chapter One: The Beginning'.
    Returns (title, number of blocks consumed as title)."""
    title = clean_title(blocks[idx].text.replace("\n", " "))
    if pattern == "special" and len(title) > 40 and (m := SPECIAL.match(title)):
        return _titlecase(m.group(1).upper()), 0  # e.g. "Copyright © 2026 ..." -> "Copyright"
    if pattern in ("chapter", "part") and idx + 1 < len(blocks):
        m = (STRONG_CHAPTER if pattern == "chapter" else PART).match(title)
        nxt = blocks[idx + 1]
        nxt_text = clean_title(nxt.text)
        if m and not m.group("rest") and nxt_text and len(nxt_text) < 90 and not nxt_text.endswith((".", ",")) and (
            nxt.is_heading or nxt.meta.get("heading_candidate")
        ) and heading_score(nxt)[1] not in ("chapter", "part"):
            return f"{_titlecase(title)}: {nxt_text}", 2
    if title.isupper() and len(title) > 3:
        return _titlecase(title), 1
    return title, 1


def _titlecase(text: str) -> str:
    if not text.isupper():
        return text
    small = {"a", "an", "the", "of", "and", "or", "in", "on", "at", "to", "for", "by"}
    words = text.lower().split()
    out = []
    for i, w in enumerate(words):
        if re.fullmatch(r"[ivxlcdm]+", w) and len(w) <= 6:
            out.append(w.upper())
        elif i and w in small and not words[i - 1].endswith((":", "-", "—")):
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


def _split_at(blocks: list[Block], splits: list[tuple[int, str | None, str]], method: str, confidence: float) -> list[DetectedChapter]:
    chapters: list[DetectedChapter] = []
    first = splits[0][0] if splits else len(blocks)
    if first > 0:
        pre = blocks[:first]
        chapters.extend(_front_matter(pre))
    for n, (idx, pattern, _label) in enumerate(splits):
        end = splits[n + 1][0] if n + 1 < len(splits) else len(blocks)
        title, consumed = _merge_title_lines(blocks, idx, pattern)
        body = blocks[idx:end]
        for k in range(min(consumed, len(body))):
            body[k].kind = "heading"
        kind, include = classify(title, body[consumed:])
        chapters.append(DetectedChapter(title=title, kind=kind, blocks=body, include_in_audio=include, detection={"method": method, "confidence": confidence, "pattern": pattern}))
    return chapters


def _front_matter(pre: list[Block]) -> list[DetectedChapter]:
    """Content before the first chapter: split at special headings (Dedication,
    Contents, Preface...) and classify each piece."""
    special = [i for i, b in enumerate(pre) if heading_score(b)[1] == "special" and heading_score(b)[0] >= 0.6]
    if special:
        head = _front_matter_piece(pre[: special[0]])
        pieces = []
        for n, idx in enumerate(special):
            end = special[n + 1] if n + 1 < len(special) else len(pre)
            body = pre[idx:end]
            body[0].kind = "heading"
            title = clean_title(body[0].text)
            kind, include = classify(title, body[1:])
            pieces.append(DetectedChapter(_titlecase(title), kind, body, include, {"method": "front_matter", "confidence": 0.8}))
        return head + pieces
    return _front_matter_piece(pre)


def _front_matter_piece(pre: list[Block]) -> list[DetectedChapter]:
    words = sum(word_count(b.text) for b in pre)
    if not words:
        return []
    body = " ".join(b.text for b in pre)
    if re.search(r"all rights reserved|isbn|copyright|©", body, re.I) and words < 600:
        return [DetectedChapter("Title & Copyright", "copyright", pre, False, {"method": "front_matter", "confidence": 0.7})]
    if words < 40:
        return [DetectedChapter("Title Page", "title_page", pre, False, {"method": "front_matter", "confidence": 0.6})]
    return [DetectedChapter("Opening", "front_matter", pre, True, {"method": "front_matter", "confidence": 0.5})]


# --------------------------------------------------------------------------- strategies


def _from_sections(doc: ExtractedDocument) -> list[DetectedChapter]:
    chapters: list[DetectedChapter] = []
    for n, section in enumerate(doc.sections or []):
        blocks = section.blocks
        title = clean_title(section.title) if section.title else None
        if not title and chapters and sum(word_count(b.text) for b in blocks) > 0 and not any(b.is_heading for b in blocks[:3]):
            chapters[-1].blocks.extend(blocks)  # continuation file of the previous chapter
            continue
        if not title:
            heading = next((b for b in blocks[:5] if b.is_heading), None)
            title = clean_title(heading.text) if heading else f"Section {n + 1}"
        kind, include = classify(title, blocks)
        if kind == "chapter" and sum(word_count(b.text) for b in blocks) < 60 and n < 3:
            kind, include = "title_page", False
        chapters.append(DetectedChapter(title, kind, blocks, include, {"method": "epub", "confidence": 0.95}))
    return chapters


def _from_outline(doc: ExtractedDocument, blocks: list[Block]) -> list[DetectedChapter] | None:
    entries = [e for e in doc.toc if e.page]
    if not entries:
        return None
    levels = sorted({e.level for e in entries})
    chosen = [e for e in entries if e.level == levels[0]]
    if len(levels) > 1:
        parts = sum(1 for e in chosen if PART.match(e.title))
        deeper = [e for e in entries if e.level == levels[1]]
        # Top level holds Parts (or very few entries): chapters live one level down.
        if len(chosen) < 3 or parts >= len(chosen) / 2 or (len(chosen) < 5 and len(deeper) >= len(chosen)):
            chosen = [e for e in entries if e.level <= levels[1]]
    if len(chosen) < 2:
        return None
    splits: list[tuple[int, str | None, str]] = []
    used: set[int] = set()
    for entry in sorted(chosen, key=lambda e: (e.page or 0)):
        candidates = [i for i, b in enumerate(blocks) if b.page is not None and entry.page <= b.page <= entry.page + 1 and i not in used]
        if not candidates:
            continue
        target = clean_title(entry.title).lower()
        best, best_ratio = candidates[0], 0.0
        for i in candidates[:40]:
            text = clean_title(blocks[i].text).lower()
            ratio = difflib.SequenceMatcher(None, target, text[: len(target) + 20]).ratio()
            if target and (text.startswith(target) or target.startswith(text) and len(text) > 3):
                ratio = max(ratio, 0.95)
            if ratio > best_ratio:
                best, best_ratio = i, ratio
        if best_ratio < 0.6:
            # No matching heading: split at the first block of the page and use the outline title.
            best = candidates[0]
            blocks.insert(best, Block(text=entry.title, kind="heading", level=entry.level, page=entry.page, meta={"synthetic": True}))
            splits = [(i + 1 if i >= best else i, p, l) for i, p, l in splits]
            used = {u + 1 if u >= best else u for u in used}
        if splits and splits[-1][0] >= best:
            continue
        used.add(best)
        splits.append((best, "outline", entry.title))
    if len(splits) < 2:
        return None
    chapters = _split_at(blocks, splits, "outline", 0.9)
    # Prefer the outline's titles (authored) over extracted heading text.
    by_index = {id(blocks[i]): clean_title(label) for i, _p, label in splits}
    for ch in chapters:
        if ch.blocks and id(ch.blocks[0]) in by_index:
            ch.title = by_index[id(ch.blocks[0])] or ch.title
            ch.kind, ch.include_in_audio = classify(ch.title, ch.blocks[1:])
    return chapters


def _from_headings(blocks: list[Block]) -> tuple[list[DetectedChapter], str] | None:
    scored = [(i, *heading_score(b)) for i, b in enumerate(blocks)]
    strong = [i for i, s, p in scored if p in ("chapter", "part", "special") and s >= 0.6]
    toc = _toc_runs(strong, blocks)
    strong_body = [i for i in strong if i not in toc]
    # A TOC run starts with its "Contents" heading if present right before it.
    if len([i for i in strong_body if heading_score(blocks[i])[1] == "chapter"]) >= 2:
        splits = [(i, heading_score(blocks[i])[1], "") for i in strong_body]
        return _split_at(blocks, _drop_nested(splits, blocks), "headings", 0.9), "headings"

    numbered = [(i, int(NUMBERED_TITLE.match(clean_title(blocks[i].text)).group("num"))) for i, s, p in scored if p == "numbered"]
    seq = _longest_sequence(numbered)
    if len(seq) >= 3:
        gaps = [sum(word_count(blocks[k].text) for k in range(a, b)) for a, b in zip(seq, seq[1:] + [len(blocks)])]
        if sum(gaps) / len(gaps) >= 250:
            specials = [i for i in strong_body if heading_score(blocks[i])[1] in ("special", "part")]
            splits = sorted([(i, "numbered", "") for i in seq] + [(i, heading_score(blocks[i])[1], "") for i in specials])
            return _split_at(blocks, splits, "numbered", 0.7), "numbered"

    # Font/style headings: choose the most prominent level that yields real chapters.
    levels = sorted({b.level for b in blocks if b.is_heading and b.level and not b.meta.get("weak")})
    for level in levels:
        idx = [i for i, b in enumerate(blocks) if b.is_heading and b.level == level and not b.meta.get("weak")]
        idx = [i for i in idx if i not in _toc_runs(idx, blocks)]
        if len(idx) < 2:
            continue
        sizes = [sum(word_count(blocks[k].text) for k in range(a, b)) for a, b in zip(idx, idx[1:] + [len(blocks)])]
        avg = sum(sizes) / len(sizes)
        if avg >= 400 and len(idx) <= 400:
            return _split_at(blocks, [(i, "heading", "") for i in idx], "headings", 0.75), "headings"

    caps = [i for i, s, p in scored if p == "caps"]
    caps = [i for i in caps if i not in _toc_runs(caps, blocks)]
    if len(caps) >= 3:
        sizes = [sum(word_count(blocks[k].text) for k in range(a, b)) for a, b in zip(caps, caps[1:] + [len(blocks)])]
        if sum(sizes) / len(sizes) >= 500:
            return _split_at(blocks, [(i, "caps", "") for i in caps], "headings", 0.55), "headings"
    return None


def _drop_nested(splits: list[tuple[int, str | None, str]], blocks: list[Block]) -> list[tuple[int, str | None, str]]:
    """A 'PART I' immediately followed by 'Chapter 1' keeps both; a special heading
    that sits right after a chapter heading (e.g. 'Introduction' as its subtitle) is dropped."""
    out: list[tuple[int, str | None, str]] = []
    for s in splits:
        if out and s[1] == "special" and out[-1][1] == "chapter" and s[0] - out[-1][0] <= 1:
            continue
        out.append(s)
    return out


def _longest_sequence(numbered: list[tuple[int, int]]) -> list[int]:
    best: list[int] = []
    for start_pos, (i0, n0) in enumerate(numbered):
        if n0 != 1:
            continue
        seq, expect = [i0], 2
        for i, n in numbered[start_pos + 1 :]:
            if n == expect:
                seq.append(i)
                expect += 1
        if len(seq) > len(best):
            best = seq
    return best


def _length_split(blocks: list[Block], target_words: int = 4000) -> list[DetectedChapter]:
    chapters: list[DetectedChapter] = []
    current: list[Block] = []
    words = 0
    for b in blocks:
        current.append(b)
        words += word_count(b.text)
        if words >= target_words and b.text.rstrip().endswith((".", "!", "?", '"', "”")):
            chapters.append(DetectedChapter(f"Part {len(chapters) + 1}", "chapter", current, True, {"method": "length", "confidence": 0.2}))
            current, words = [], 0
    if current:
        if chapters and words < target_words * 0.25:
            chapters[-1].blocks.extend(current)
        else:
            chapters.append(DetectedChapter(f"Part {len(chapters) + 1}", "chapter", current, True, {"method": "length", "confidence": 0.2}))
    return chapters


# --------------------------------------------------------------------------- metadata


def _guess_title_author(doc: ExtractedDocument, blocks: list[Block], filename: str | None) -> tuple[str, str | None, str | None]:
    meta = doc.metadata
    title, author, subtitle = meta.title, meta.author, meta.subtitle
    early = [b for b in blocks[:60] if (b.page or 1) <= 3]
    if not title:
        headings = [b for b in early if b.is_heading and not heading_score(b)[1] in ("chapter", "part", "special")]
        if headings:
            top = min(headings, key=lambda b: (b.level or 9, -(b.font_size or 0)))
            title = clean_title(top.text.replace("\n", " "))
        else:
            first = next(
                (
                    b
                    for b in blocks[:5]
                    if b.meta.get("heading_candidate") and heading_score(b)[1] not in ("chapter", "part", "special") and not BY_LINE.match(b.text)
                ),
                None,
            )
            if first is not None and len(first.text) < 100:
                title = clean_title(first.text)
    if not author:
        for b in early:
            if m := BY_LINE.match(b.text.strip()):
                author = m.group("name").strip()
                break
    if not title and filename:
        stem = Path(filename).stem
        title = re.sub(r"[_\-]+", " ", stem).strip().title() or "Untitled Book"
    return _titlecase(title or "Untitled Book"), author, subtitle


BODY_KINDS = {"chapter", "part", "prologue", "introduction", "preface"}
MIN_NARRATED_WORDS = 20


def _skip_non_narratable(chapters: list[DetectedChapter]) -> None:
    """Keep leftovers out of the narration (they stay in the editor, switched off):
    - end-matter sections *before* the first real chapter are table-of-contents
      entries that were split off as sections ("Epilogue", "Acknowledgments"...);
    - sections too short to be real prose (a 7-word "Epilogue", a 1-word page).
    Parts and dedications are legitimately short and are left alone."""
    first_body = next((i for i, c in enumerate(chapters) if c.kind in BODY_KINDS and c.words >= MIN_NARRATED_WORDS), len(chapters))
    for i, c in enumerate(chapters):
        if not c.include_in_audio:
            continue
        if i < first_body and c.kind in ("epilogue", "afterword", "back_matter", "appendix", "glossary", "acknowledgements", "author_bio", "advertisement"):
            c.include_in_audio = False
            c.detection = {**c.detection, "skipped": "toc_leftover"}
        elif c.words < MIN_NARRATED_WORDS and c.kind not in ("part", "dedication", "epigraph", "toc", "copyright", "title_page"):
            c.include_in_audio = False
            c.detection = {**c.detection, "skipped": "too_short"}


def _prefer_filename_spelling(title: str, filename: str | None) -> str:
    """A title read from a stylized cover by OCR can lose letters ("Huntin Adelin");
    when the file name spells nearly the same title more completely, use it."""
    if not filename:
        return title
    import difflib

    stem = re.sub(r"[_\-]+", " ", Path(filename).stem).strip()
    if not stem or stem.lower() == title.lower():
        return title
    ratio = difflib.SequenceMatcher(None, re.sub(r"\W", "", title.lower()), re.sub(r"\W", "", stem.lower())).ratio()
    if ratio >= 0.8 and len(re.sub(r"\W", "", stem)) > len(re.sub(r"\W", "", title)):
        return stem.title() if stem.islower() or stem.isupper() else stem
    return title


def detect_structure(doc: ExtractedDocument, filename: str | None = None) -> BookStructure:
    warnings: list[str] = []
    method = "single"
    chapters: list[DetectedChapter] | None = None
    blocks = doc.all_blocks()

    if doc.sections is not None:
        total_words = sum(word_count(b.text) for b in blocks)
        if len(doc.sections) >= 3 or total_words < 20000:
            chapters, method = _from_sections(doc), "epub"
            if len([c for c in chapters if c.kind == "chapter"]) <= 1 and total_words > 20000:
                chapters = None
    if chapters is None and doc.toc and doc.format == "pdf":
        chapters = _from_outline(doc, blocks)
        if chapters:
            method = "outline"
    if chapters is None:
        found = _from_headings(blocks)
        if found:
            chapters, method = found
    if chapters is None:
        total = sum(word_count(b.text) for b in blocks)
        if total > 8000:
            chapters, method = _length_split(blocks), "length"
            warnings.append(
                "No chapter headings were found, so the book was split into parts of roughly equal length. Review the chapters in the editor."
            )
        else:
            chapters, method = [DetectedChapter("Full Text", "chapter", blocks, True, {"method": "single", "confidence": 0.3})], "single"

    chapters = [c for c in chapters if c.blocks]
    _skip_non_narratable(chapters)
    # Default content mode: narrative only (the user can switch to Full Book or Custom).
    for c in chapters:
        c.include_in_audio = included(c.kind, "narrative", c.detection, c.include_in_audio)
    title, author, subtitle = _guess_title_author(doc, blocks, filename)
    title = _prefer_filename_spelling(title, filename)
    if len([c for c in chapters if c.include_in_audio]) == 0 and chapters:
        for c in chapters:
            c.include_in_audio = True
    low = [c.title for c in chapters if c.detection.get("confidence", 1) < 0.5]
    if low and method not in ("length", "single"):
        warnings.append(f"{len(low)} section(s) were detected with low confidence. Check them in the editor.")
    return BookStructure(title=title, subtitle=subtitle, author=author, chapters=chapters, method=method, warnings=warnings)
