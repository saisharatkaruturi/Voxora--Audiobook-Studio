"""Sentence segmentation and TTS chunking.

Sentences carry character offsets into the original paragraph so timestamps can
be mapped back to the text for synchronized reading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "mt", "ft", "vs", "etc", "inc", "ltd", "co", "corp", "no",
    "vol", "ch", "chap", "fig", "pp", "p", "ed", "eds", "rev", "gen", "col", "capt", "lt", "sgt", "gov", "sen",
    "rep", "hon", "messrs", "mme", "mlle", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct",
    "nov", "dec", "approx", "dept", "est", "e.g", "i.e", "cf", "al", "viz", "a.m", "p.m", "u.s", "u.k", "ph.d",
}

_BOUNDARY = re.compile(r"([.!?…।॥]+)([\"'”’»)\]]*)(\s+|$)")


@dataclass
class Sentence:
    text: str
    start: int  # char offset in the paragraph
    end: int


def _is_abbreviation(text: str, dot_index: int) -> bool:
    """Is the '.' at text[dot_index] part of an abbreviation, initial or number?"""
    m = re.search(r"([A-Za-z][A-Za-z.]*)$", text[:dot_index])
    if not m:
        # "3.5" decimals are not matched by _BOUNDARY (needs whitespace), so any other case is a boundary
        return False
    word = m.group(1).lower().rstrip(".")
    if word in ABBREVIATIONS:
        return True
    if len(word) == 1 and word.isalpha():  # initials: "J. K. Rowling"
        return True
    if re.fullmatch(r"(?:[a-z]\.)+[a-z]", word):  # "u.s.a"
        return True
    return False


def split_sentences(text: str) -> list[Sentence]:
    sentences: list[Sentence] = []
    start = 0
    for m in _BOUNDARY.finditer(text):
        punct_start = m.start(1)
        end = m.end(2)
        if m.group(1) == "." and _is_abbreviation(text, punct_start):
            continue
        following = text[m.end():m.end() + 2]
        # Lowercase continuation after '...' or a quote usually means the sentence continues ("Wait!" she said).
        if following[:1].islower() and (m.group(2) or m.group(1) in ("...", "…")):
            continue
        chunk = text[start:end]
        if chunk.strip():
            lead = len(chunk) - len(chunk.lstrip())
            sentences.append(Sentence(chunk.strip(), start + lead, end))
        start = m.end()
    if start < len(text) and text[start:].strip():
        chunk = text[start:]
        lead = len(chunk) - len(chunk.lstrip())
        sentences.append(Sentence(chunk.strip(), start + lead, len(text.rstrip())))
    return sentences


def split_long(sentence: Sentence, max_chars: int) -> list[Sentence]:
    """Split an over-long sentence at clause boundaries (, ; : —), then at spaces."""
    if len(sentence.text) <= max_chars:
        return [sentence]
    parts: list[Sentence] = []
    text, base = sentence.text, sentence.start
    pos = 0
    while len(text) - pos > max_chars:
        window = text[pos : pos + max_chars]
        cut = max(window.rfind(sep) for sep in (", ", "; ", ": ", " — ", " – "))
        if cut < max_chars * 0.3:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = max_chars - 1
        cut += 1
        piece = text[pos : pos + cut]
        parts.append(Sentence(piece.strip(), base + pos, base + pos + len(piece.rstrip())))
        pos += cut
        while pos < len(text) and text[pos] == " ":
            pos += 1
    if pos < len(text):
        parts.append(Sentence(text[pos:].strip(), base + pos, sentence.end))
    return parts


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text))
