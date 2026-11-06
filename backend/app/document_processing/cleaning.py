"""Text cleaning engine.

Fixes extraction artifacts (line wrapping, hyphenation, page numbers, repeated
headers/footers, spacing, OCR debris) while preserving real paragraph
boundaries. Operates on `Block`s and never rewrites the author's wording.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

from app.document_processing.base import Block

LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
}
INVISIBLE = dict.fromkeys(map(ord, "­​‎‏﻿⁠"), None)  # soft hyphen, zero-width, BOM
SPACES = re.compile(r"[  -   　\t]")

TERMINAL = tuple('.!?"”’\')]:;…।॥')
ROMAN = re.compile(r"^(?=[MDCLXVI])M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$", re.I)
PAGE_NUMBER = re.compile(
    r"^\s*(?:[-–—]\s*)?(?:page\s+)?(\d{1,4}|[ivxlcdm]{1,7})(?:\s*(?:of|/)\s*\d{1,4})?(?:\s*[-–—])?\s*$", re.I
)
WORD_CHAR = re.compile(r"\w", re.UNICODE)


def normalize_unicode(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    for lig, rep in LIGATURES.items():
        text = text.replace(lig, rep)
    text = text.translate(INVISIBLE)
    text = SPACES.sub(" ", text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def is_page_number(text: str) -> bool:
    t = text.strip()
    if not t or len(t) > 20:
        return False
    m = PAGE_NUMBER.match(t)
    if not m:
        return False
    token = m.group(1)
    return token.isdigit() or bool(ROMAN.match(token))


def _is_lower_start(s: str) -> bool:
    s = s.lstrip("\"'“‘(")
    return bool(s) and s[0].islower()


class Dehyphenator:
    """Decides whether `foo-` + `bar` is a line-break hyphenation or a real compound.

    Uses the document's own vocabulary: if "foobar" appears elsewhere unbroken,
    the hyphen was a line break; if "foo-bar" appears elsewhere, keep it.
    """

    def __init__(self, corpus: str = ""):
        words = re.findall(r"[^\W\d_]+(?:-[^\W\d_]+)*", corpus.lower())
        self.vocab = Counter(words)

    def join(self, left: str, right: str) -> str:
        m_left = re.search(r"([^\W\d_]+)-$", left)
        m_right = re.match(r"([^\W\d_]+)", right)
        if not m_left or not m_right:
            return left + right
        a, b = m_left.group(1), m_right.group(1)
        joined, compound = (a + b).lower(), f"{a}-{b}".lower()
        both_upper = a.isupper() and b.isupper()
        if self.vocab.get(compound, 0) > self.vocab.get(joined, 0) and not both_upper:
            return left + right  # keep the hyphen: real compound word
        if b[0].islower() or both_upper or self.vocab.get(joined):
            return left[:-1] + right  # line-break hyphenation
        return left + right


def unwrap_lines(text: str, dehyphenator: Dehyphenator | None = None) -> str:
    """Join hard-wrapped lines inside one paragraph block."""
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    if not lines:
        return ""
    dh = dehyphenator or Dehyphenator()
    out = lines[0]
    for line in lines[1:]:
        if re.search(r"[^\W\d_]-$", out) and (line[:1].isalpha()):
            out = dh.join(out, line)
        elif out.endswith(("—", "–", "/")):
            out = out + line
        else:
            out = out + " " + line
    return out


_PUNCT_FIXES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"[ ]+([,.;:!?%)\]}»”’])(?=\s|$)"), r"\1"),  # space before punctuation
    (re.compile(r"([(\[{«“])[ ]+"), r"\1"),  # space after opening bracket/quote
    (re.compile(r"(?<=[a-z]{2})([.!?])(?=[A-Z][a-z])"), r"\1 "),  # "end.Next" -> "end. Next"
    (re.compile(r"(?<=[a-zA-Z]),(?=[A-Za-z]{2})"), ", "),  # "word,word" -> "word, word"
    (re.compile(r"\.{4,}"), "..."),
    (re.compile(r" {2,}"), " "),
]


def fix_spacing(text: str) -> str:
    for pattern, repl in _PUNCT_FIXES:
        text = pattern.sub(repl, text)
    return text.strip()


_OCR_PIPE_AS_I = re.compile(r"(?<=\s)\|(?=\s+[a-z])|^\|(?=\s+[a-z])")
_OCR_JUNK_LINE = re.compile(r"^[\W_]{1,6}$")


def fix_ocr_artifacts(text: str) -> str:
    text = _OCR_PIPE_AS_I.sub("I", text)
    text = re.sub(r"(?<=\w)[ ]?¬[ ]?(?=\w)", "", text)  # stray negation used as hyphen
    text = re.sub(r"[~`^]{2,}", "", text)
    return text


def alpha_ratio(text: str) -> float:
    if not text:
        return 0.0
    return sum(1 for ch in text if ch.isalpha()) / len(text)


def is_junk(text: str, ocr: bool = False) -> bool:
    t = text.strip()
    if not t:
        return True
    if _OCR_JUNK_LINE.match(t):
        return True
    if ocr and len(t) < 12 and alpha_ratio(t) < 0.4:
        return True
    if len(t) < 60 and not WORD_CHAR.search(t):
        return True
    return False


def _normalized_edge_key(text: str) -> str:
    return re.sub(r"\d+", "#", text.strip().lower())[:80]


def remove_repeated_lines(blocks: list[Block], min_pages: int = 3, ratio: float = 0.25) -> list[Block]:
    """Drop short blocks repeated on many pages (running headers/footers).

    Extractors that know page geometry mark candidates with meta["edge"]=True;
    for those we're more aggressive. Chapter headings are never removed.
    """
    pages = {b.page for b in blocks if b.page is not None}
    if len(pages) < min_pages:
        return blocks
    counts: Counter[str] = Counter()
    seen_on: dict[str, set[int]] = {}
    for b in blocks:
        if b.page is None or len(b.text) > 120:
            continue
        key = _normalized_edge_key(b.text)
        if key and b.page not in seen_on.setdefault(key, set()):
            seen_on[key].add(b.page)
            counts[key] += 1
    threshold = max(min_pages, int(len(pages) * ratio))
    repeated = {k for k, c in counts.items() if c >= threshold}
    edge_repeated = {k for k, c in counts.items() if c >= min_pages}
    result = []
    for b in blocks:
        key = _normalized_edge_key(b.text)
        if key in repeated or (b.meta.get("edge") and key in edge_repeated):
            continue
        result.append(b)
    return result


def merge_continuations(blocks: list[Block]) -> list[Block]:
    """Merge paragraphs split across pages/columns: a block that ends mid-sentence
    followed by a block starting in lowercase."""
    out: list[Block] = []
    dh = Dehyphenator(" ".join(b.text for b in blocks[:4000]))
    for b in blocks:
        if out and not b.is_heading and not out[-1].is_heading:
            prev = out[-1]
            prev_text = prev.text.rstrip()
            if (
                prev_text
                and not prev_text.endswith(TERMINAL)
                and _is_lower_start(b.text)
                and not b.meta.get("list_item")
                and not (prev.meta.get("heading_candidate") and len(prev_text) < 100)
                and not (b.meta.get("heading_candidate") and len(b.text) < 100)
            ):
                if prev_text.endswith("-") and re.search(r"[^\W\d_]-$", prev_text):
                    prev.text = dh.join(prev_text, b.text.lstrip())
                else:
                    prev.text = prev_text + " " + b.text.lstrip()
                continue
        out.append(b)
    return out


def clean_blocks(blocks: list[Block], *, ocr: bool = False, remove_page_numbers: bool = True) -> list[Block]:
    """Full cleaning pipeline over a list of blocks (in reading order)."""
    corpus = "\n".join(normalize_unicode(b.text) for b in blocks[:5000])
    dh = Dehyphenator(corpus)
    cleaned: list[Block] = []
    for b in blocks:
        text = normalize_unicode(b.text)
        if ocr:
            text = fix_ocr_artifacts(text)
        if b.meta.get("preformatted"):
            text = "\n".join(ln.rstrip() for ln in text.split("\n")).strip()
        else:
            text = unwrap_lines(text, dh)
        text = fix_spacing(text)
        if remove_page_numbers and is_page_number(text) and not (b.is_heading and not b.meta.get("edge")):
            continue
        if is_junk(text, ocr=ocr):
            continue
        b.text = text
        cleaned.append(b)
    cleaned = remove_repeated_lines(cleaned)
    cleaned = merge_continuations(cleaned)
    return cleaned


def split_plain_paragraphs(text: str) -> list[str]:
    """Split raw text (TXT or editor input) into paragraphs.

    Blank lines separate paragraphs. If the text has no blank lines at all but
    uses indentation, indented lines start new paragraphs.
    """
    text = normalize_unicode(text)
    if re.search(r"\n\s*\n", text):
        parts = re.split(r"\n\s*\n+", text)
    else:
        lines = text.split("\n")
        indented = sum(1 for ln in lines if re.match(r"^( {2,}|\t)\S", ln))
        if indented >= max(3, len(lines) // 20):
            parts, cur = [], []
            for ln in lines:
                if re.match(r"^( {2,}|\t)\S", ln) and cur:
                    parts.append("\n".join(cur))
                    cur = []
                cur.append(ln)
            if cur:
                parts.append("\n".join(cur))
        else:
            parts = lines
    return [p.strip("\n") for p in parts if p.strip()]
