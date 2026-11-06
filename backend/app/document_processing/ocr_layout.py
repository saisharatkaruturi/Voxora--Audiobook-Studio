"""Turn OCR line boxes into paragraphs and headings, preserving reading order."""

from __future__ import annotations

from statistics import median

from app.document_processing.base import Block
from app.providers.ocr.base import OcrLine, OcrPage


def _columns(lines: list[OcrLine], page_width: float) -> list[list[OcrLine]]:
    """Split lines into columns when the page is clearly multi-column."""
    if not lines or page_width <= 0:
        return [lines]
    mid = page_width / 2
    left = [ln for ln in lines if ln.bbox[2] < mid + page_width * 0.02]
    right = [ln for ln in lines if ln.bbox[0] > mid - page_width * 0.02]
    spanning = [ln for ln in lines if ln not in left and ln not in right]
    if len(left) >= 5 and len(right) >= 5 and len(spanning) <= max(2, len(lines) // 10):
        # Spanning lines (titles) go first when above both columns, else last.
        top = min(min(ln.bbox[1] for ln in left), min(ln.bbox[1] for ln in right))
        head = [ln for ln in spanning if ln.bbox[1] <= top]
        tail = [ln for ln in spanning if ln.bbox[1] > top]
        return [c for c in (head, left, right, tail) if c]
    return [lines]


def ocr_page_to_blocks(page: OcrPage, page_number: int) -> list[Block]:
    lines = [ln for ln in page.lines if ln.text.strip()]
    if not lines:
        return []
    heights = [ln.bbox[3] - ln.bbox[1] for ln in lines]
    med_h = median(heights) or 1.0
    blocks: list[Block] = []
    for column in _columns(lines, page.width):
        column.sort(key=lambda ln: (round(ln.bbox[1] / (med_h * 0.5)), ln.bbox[0]))
        col_left = median([ln.bbox[0] for ln in column])
        col_right = max(ln.bbox[2] for ln in column)
        col_width = max(col_right - col_left, 1.0)
        current: list[OcrLine] = []

        def flush() -> None:
            if not current:
                return
            text = "\n".join(ln.text for ln in current)
            h = median([ln.bbox[3] - ln.bbox[1] for ln in current])
            confs = [ln.confidence for ln in current if ln.confidence is not None]
            is_heading = len(current) <= 2 and h > med_h * 1.35 and len(text) < 120
            blocks.append(
                Block(
                    text=text,
                    kind="heading" if is_heading else "text",
                    level=1 if is_heading else None,
                    page=page_number,
                    font_size=h,
                    ocr_confidence=(sum(confs) / len(confs)) if confs else None,
                    meta={"edge": _in_edge_zone(current, page.height)},
                )
            )
            current.clear()

        # Typical spacing between lines of the same paragraph, to spot paragraph gaps adaptively.
        gaps = [b.bbox[1] - a.bbox[3] for a, b in zip(column, column[1:]) if 0 <= b.bbox[1] - a.bbox[3] < med_h * 3]
        line_gap = median(gaps) if gaps else med_h * 0.4
        prev: OcrLine | None = None
        for ln in column:
            if prev is not None:
                gap = ln.bbox[1] - prev.bbox[3]
                indent = ln.bbox[0] - col_left
                ends_sentence = prev.text.rstrip().endswith((".", "!", "?", '"', "”", "’", "।", ":"))
                prev_short = (prev.bbox[2] - col_left) < col_width * 0.8 and ends_sentence
                size_jump = abs((ln.bbox[3] - ln.bbox[1]) - (prev.bbox[3] - prev.bbox[1])) > med_h * 0.4
                new_block = (
                    gap > line_gap + med_h * 0.35
                    or (ln.block_id is not None and prev.block_id is not None and ln.block_id != prev.block_id)
                    or (indent > med_h * 0.8 and indent < col_width * 0.3 and ends_sentence)
                    or prev_short
                    or size_jump
                )
                if new_block:
                    flush()
            current.append(ln)
            prev = ln
        flush()
    return blocks


def _in_edge_zone(lines: list[OcrLine], page_height: float) -> bool:
    """Header/footer zone candidate (top or bottom 8% of the page)."""
    if not page_height or len(lines) > 2:
        return False
    top = min(ln.bbox[1] for ln in lines)
    bottom = max(ln.bbox[3] for ln in lines)
    return top < page_height * 0.08 or bottom > page_height * 0.92
