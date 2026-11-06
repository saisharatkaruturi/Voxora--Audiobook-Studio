"""Map provider timing marks (word/char boundaries) onto our sentences."""

from __future__ import annotations

from bisect import bisect_right


def join_sentences(sentences: list[str]) -> tuple[str, list[tuple[int, int]]]:
    spans: list[tuple[int, int]] = []
    parts: list[str] = []
    pos = 0
    for i, s in enumerate(sentences):
        if i:
            parts.append(" ")
            pos += 1
        spans.append((pos, pos + len(s)))
        parts.append(s)
        pos += len(s)
    return "".join(parts), spans


def sentence_times_from_marks(
    text: str, spans: list[tuple[int, int]], marks: list[tuple[str, float, float]]
) -> list[tuple[float, float]] | None:
    """`marks` are (token_text, start_sec, end_sec) in spoken order. Tokens are
    located in `text` sequentially; sentence start/end times are interpolated."""
    anchors: list[tuple[int, float]] = []  # (char position, time)
    cursor = 0
    for token, t0, t1 in marks:
        token = token.strip()
        if not token:
            continue
        idx = text.find(token, cursor)
        if idx < 0 or idx - cursor > 200:
            continue
        anchors.append((idx, t0))
        anchors.append((idx + len(token), t1))
        cursor = idx + len(token)
    if len(anchors) < 2:
        return None
    positions = [a[0] for a in anchors]

    def time_at(char: int) -> float:
        k = bisect_right(positions, char)
        if k == 0:
            return anchors[0][1]
        if k >= len(anchors):
            return anchors[-1][1]
        (p0, t0), (p1, t1) = anchors[k - 1], anchors[k]
        if p1 == p0:
            return t0
        return t0 + (t1 - t0) * (char - p0) / (p1 - p0)

    return [(time_at(a), time_at(b)) for a, b in spans]


def approximate_sentence_times(sentences: list[str], duration: float, pause: float = 0.0) -> list[tuple[float, float]]:
    """Fallback when a provider gives no timings: split duration by character share."""
    weights = [max(len(s), 1) for s in sentences]
    speech = max(duration - pause * (len(sentences) - 1), 0.0)
    total = sum(weights)
    times = []
    t = 0.0
    for i, w in enumerate(weights):
        d = speech * w / total
        times.append((t, t + d))
        t += d + (pause if i < len(sentences) - 1 else 0.0)
    return times
