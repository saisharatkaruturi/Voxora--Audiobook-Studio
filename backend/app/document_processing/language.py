"""Language detection per paragraph.

Indic and other non-Latin scripts are identified by Unicode block (very reliable).
Latin script and Devanagari (Hindi vs Marathi vs Nepali) fall back to
`langdetect` when the text is long enough to be trustworthy.
"""

from __future__ import annotations

import re
from collections import Counter

SCRIPT_RANGES: list[tuple[int, int, str]] = [
    (0x0900, 0x097F, "deva"),
    (0x0980, 0x09FF, "bn"),
    (0x0A00, 0x0A7F, "pa"),
    (0x0A80, 0x0AFF, "gu"),
    (0x0B00, 0x0B7F, "or"),
    (0x0B80, 0x0BFF, "ta"),
    (0x0C00, 0x0C7F, "te"),
    (0x0C80, 0x0CFF, "kn"),
    (0x0D00, 0x0D7F, "ml"),
    (0x0D80, 0x0DFF, "si"),
    (0x0E00, 0x0E7F, "th"),
    (0x0600, 0x06FF, "arab"),
    (0x0590, 0x05FF, "he"),
    (0x0400, 0x04FF, "cyrl"),
    (0x0370, 0x03FF, "el"),
    (0x3040, 0x30FF, "ja"),
    (0xAC00, 0xD7AF, "ko"),
    (0x4E00, 0x9FFF, "han"),
]

LANGUAGE_NAMES = {
    "en": "English", "hi": "Hindi", "te": "Telugu", "ta": "Tamil", "kn": "Kannada", "ml": "Malayalam", "bn": "Bengali",
    "mr": "Marathi", "gu": "Gujarati", "pa": "Punjabi", "or": "Odia", "ur": "Urdu", "ne": "Nepali", "si": "Sinhala",
    "fr": "French", "de": "German", "es": "Spanish", "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "ru": "Russian",
    "ar": "Arabic", "he": "Hebrew", "el": "Greek", "th": "Thai", "ja": "Japanese", "ko": "Korean", "zh": "Chinese",
    "sa": "Sanskrit", "fa": "Persian", "tr": "Turkish", "pl": "Polish", "uk": "Ukrainian", "sv": "Swedish",
}


def script_of(ch: str) -> str | None:
    cp = ord(ch)
    if cp < 0x0250:
        return "latn" if ch.isalpha() else None
    for lo, hi, name in SCRIPT_RANGES:
        if lo <= cp <= hi:
            return name
    return None


def dominant_script(text: str) -> tuple[str | None, float]:
    counts = Counter(s for ch in text if (s := script_of(ch)))
    total = sum(counts.values())
    if not total:
        return None, 0.0
    script, n = counts.most_common(1)[0]
    return script, n / total


def _langdetect(text: str, allowed: set[str] | None = None) -> str | None:
    try:
        from langdetect import DetectorFactory, detect_langs

        DetectorFactory.seed = 0
        results = detect_langs(text[:3000])
    except Exception:
        return None
    for r in results:
        code = r.lang.split("-")[0]
        if r.prob >= 0.80 and (allowed is None or code in allowed):
            return code
    return None


# Function words that are frequent in one Latin-script language and rare in the
# others. A clear stopword winner settles most paragraphs in microseconds; only
# ambiguous ones pay for langdetect (which costs ~35 ms per paragraph).
_STOPWORDS: dict[str, frozenset[str]] = {
    "en": frozenset("the and of to was that with his her had for you not but they she have this from what were would been their which there could i my me it's i'm don't just at he we your our are is it be so if me him them".split()),
    "fr": frozenset("le la les des est une dans que qui pour pas sur au avec il elle nous vous mais ont été cette sont aux du".split()),
    "de": frozenset("der die das und ist nicht ein eine ich sie mit sich auf dem den des auch war wie noch nach wird oder".split()),
    "es": frozenset("el los las que del por una con para como pero más sus fue muy este esta también cuando está hay".split()),
    "it": frozenset("il di che è per una della non sono gli con del nel alla anche come più questo ma delle hanno".split()),
    "pt": frozenset("não uma com os das dos para que por mais como mas foi ao ele ela são também seu sua pelo".split()),
    "nl": frozenset("het een van en ik niet dat zijn op te maar met voor ook als bij er nog naar hij wat".split()),
}
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def _stopword_scores(text: str) -> tuple[dict[str, int], int]:
    words = [w.lower() for w in _WORD.findall(text[:1500].replace("’", "'"))]
    return {lang: sum(1 for w in words if w in sw) for lang, sw in _STOPWORDS.items()}, len(words)


def _stopword_language(text: str) -> str | None:
    scores, n = _stopword_scores(text)
    if n < 6:
        return None
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (best, top), (_, second) = ranked[0], ranked[1]
    if top >= 3 and top >= 2.5 * max(second, 1) and top / n >= 0.1:
        return best
    return None


def detect_language(text: str, default: str | None = None) -> str | None:
    """Best-effort ISO 639-1 code for a paragraph; `default` when unsure."""
    script, share = dominant_script(text)
    if script is None or share < 0.5:
        return default
    if script == "latn":
        if len(text) < 40:
            return default
        found = _stopword_language(text)
        if found:
            return found
        if default in _STOPWORDS:
            # No clear winner, but also no real evidence of another language:
            # stay with the surrounding language (short dialogue lines, names...).
            scores, _ = _stopword_scores(text)
            if max(v for k, v in scores.items() if k != default) < 2:
                return default
        return _langdetect(text) or default
    if script == "deva":
        return _langdetect(text, {"hi", "mr", "ne"}) or (default if default in {"hi", "mr", "ne", "sa"} else "hi")
    if script == "arab":
        return _langdetect(text, {"ar", "ur", "fa"}) or "ar"
    if script == "cyrl":
        return _langdetect(text, {"ru", "uk", "bg"}) or "ru"
    if script == "han":
        return "zh"
    return script


def summarize_languages(counts: Counter[str], min_share: float = 0.03) -> list[str]:
    total = sum(counts.values()) or 1
    return [lang for lang, n in counts.most_common() if n / total >= min_share]
