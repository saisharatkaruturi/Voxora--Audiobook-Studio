"""Narration Cleanup: prepares text for speech WITHOUT changing the author's words.

Only speech-affecting surface forms are normalized (abbreviations, symbols,
times, URLs, footnote markers, Roman numerals in headings). The stored book
text is never modified; this runs on the fly during generation.

The optional LLM pass (OCR repair) is guarded: its output is rejected unless it
is nearly identical to the input, so it cannot paraphrase or summarize.
"""

from __future__ import annotations

import difflib
import re

from app.core.logging import get_logger

log = get_logger(__name__)

EN_ABBREVIATIONS = [
    (r"\bDr\.(?=\s+[A-Z])", "Doctor"),
    (r"\bMr\.(?=\s)", "Mister"),
    (r"\bMrs\.(?=\s)", "Missus"),
    (r"\bMs\.(?=\s)", "Miz"),
    (r"\bProf\.(?=\s+[A-Z])", "Professor"),
    (r"\bSt\.(?=\s+[A-Z][a-z])", "Saint"),
    (r"\bMt\.(?=\s+[A-Z])", "Mount"),
    (r"\bCapt\.(?=\s+[A-Z])", "Captain"),
    (r"\bLt\.(?=\s+[A-Z])", "Lieutenant"),
    (r"\bSgt\.(?=\s+[A-Z])", "Sergeant"),
    (r"\bGen\.(?=\s+[A-Z])", "General"),
    (r"\bJr\.", "Junior"),
    (r"\bSr\.(?=\s|,|$)", "Senior"),
    (r"\be\.g\.,?", "for example,"),
    (r"\bi\.e\.,?", "that is,"),
    (r"\betc\.", "et cetera."),
    (r"\bvs\.?(?=\s)", "versus"),
    (r"\bapprox\.", "approximately"),
    (r"\bNo\.(?=\s*\d)", "number"),
    (r"\bVol\.(?=\s*\d)", "volume"),
    (r"\bCh\.(?=\s*\d)", "chapter"),
    (r"\bpp?\.(?=\s*\d)", "page"),
]
_EN_ABBR = [(re.compile(p), r) for p, r in EN_ABBREVIATIONS]
_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s?m\.?(?=\W|$)", re.I)
_URL = re.compile(r"\b(?:https?://)?(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)(/[^\s)]*)?", re.I)
_EMAIL = re.compile(r"\b([\w.+-]+)@([\w-]+(?:\.[\w-]+)+)\b")
_FOOTNOTE = re.compile(r"(?<=[\w.,;:!?\"”’)])(\[\d{1,3}\]|[¹²³⁴⁵⁶⁷⁸⁹⁰]+|\*{1,3}|†|‡)(?=\s|$|[.,;:])")
_ROMAN_HEADING = re.compile(r"\b(Chapter|Part|Book|Volume|Section|Act|Scene)\s+([IVXLCDM]{1,7})\b(?![a-z])")
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}

SYMBOLS = [
    (re.compile(r"\s*&\s*"), " and "),
    (re.compile(r"(\d)\s*%"), r"\1 percent"),
    (re.compile(r"§\s*"), "section "),
    (re.compile(r"°\s*C\b"), " degrees Celsius"),
    (re.compile(r"°\s*F\b"), " degrees Fahrenheit"),
    (re.compile(r"(\d)\s*°"), r"\1 degrees"),
    (re.compile(r"\s*[—–]\s*"), ", "),  # dashes read as a short pause
    (re.compile(r"(?<!\w)[#*_~^|]+|[#*_~^|]+(?!\w)"), " "),
    (re.compile(r"\s*/\s*(?=[A-Za-z])"), " or "),
]


def roman_to_int(s: str) -> int | None:
    total, prev = 0, 0
    for ch in reversed(s.upper()):
        v = _ROMAN_VALUES.get(ch)
        if v is None:
            return None
        total = total - v if v < prev else total + v
        prev = max(prev, v)
    return total


def _time(m: re.Match) -> str:
    hour, minute, ampm = m.group(1), m.group(2), m.group(3).upper()
    if minute and minute != "00":
        return f"{hour}:{minute} {ampm}M"
    return f"{hour} {ampm}M"


def _url(m: re.Match) -> str:
    domain = m.group(1)
    if not re.search(r"\.(com|org|net|io|ai|dev|edu|gov|in|co|uk|app|info)$", domain, re.I):
        return m.group(0)  # probably not a URL ("e.g" leftovers, decimals)
    spoken = domain.replace(".", " dot ")
    return spoken


def normalize_for_speech(text: str, language: str | None = "en") -> str:
    t = text
    t = _FOOTNOTE.sub("", t)
    t = _EMAIL.sub(lambda m: f"{m.group(1)} at {m.group(2).replace('.', ' dot ')}", t)
    t = _URL.sub(_url, t)
    if (language or "en") == "en":
        for pattern, repl in _EN_ABBR:
            t = pattern.sub(repl, t)
        t = _TIME.sub(_time, t)
        t = _ROMAN_HEADING.sub(lambda m: f"{m.group(1)} {roman_to_int(m.group(2)) or m.group(2)}", t)
    for pattern, repl in SYMBOLS:
        t = pattern.sub(repl, t)
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    t = re.sub(r",\s*,", ",", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t or text


OCR_FIX_SYSTEM = (
    "You repair OCR errors in book text for audiobook narration. Fix only obvious character-recognition "
    "mistakes (e.g. 'tbe' -> 'the', 'rn' misread as 'm', broken words). Do NOT rephrase, summarize, reorder, "
    "add, or remove content. Keep punctuation and wording identical wherever it is not an OCR error. "
    "Return only the corrected text."
)


def llm_ocr_repair(text: str, llm) -> str:
    """Ask the LLM to fix OCR errors; keep the result only if it is a near-identical edit."""
    from app.providers.llm import ChatMessage

    try:
        fixed = llm.complete(OCR_FIX_SYSTEM, [ChatMessage("user", text)], max_tokens=len(text) // 2 + 200).strip()
    except Exception as exc:
        log.warning("narration.ocr_repair_failed", error=str(exc))
        return text
    ratio = difflib.SequenceMatcher(None, text, fixed).ratio()
    length_ok = 0.93 <= len(fixed) / max(len(text), 1) <= 1.07
    if ratio >= 0.92 and length_ok:
        return fixed
    log.info("narration.ocr_repair_rejected", similarity=round(ratio, 3))
    return text
