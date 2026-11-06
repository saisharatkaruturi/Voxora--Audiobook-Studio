"""PDF extraction with PyMuPDF.

- Text PDFs: reads spans with font sizes, detects headings from font size/weight,
  orders multi-column layouts, flags header/footer zones.
- Scanned pages (no text layer but images): rendered and sent to OCR, page by page,
  so mixed PDFs (some scanned pages) work too.
"""

from __future__ import annotations

import re
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import median

from app.core.errors import CorruptedFileError, ProviderUnavailableError, UnsupportedFileError
from app.core.logging import get_logger
from app.document_processing.base import Block, DocMetadata, ExtractedDocument, OcrReport, ProgressCallback, TocEntry
from app.document_processing.ocr_layout import ocr_page_to_blocks

log = get_logger(__name__)

MIN_TEXT_CHARS = 25  # below this a page with images is treated as scanned
EDGE_ZONE = 0.07


def _junk_meta(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip()
    if len(v) < 2 or re.search(r"\.(docx?|pdf|indd|tex|rtf)$", v, re.I) or re.match(r"^(microsoft word|untitled|unknown|anonymous)\b", v, re.I):
        return None
    return v


def _block_info(block: dict) -> dict | None:
    lines_text: list[str] = []
    sizes: Counter[float] = Counter()
    bold_chars = total_chars = 0
    line_boxes = []
    for line in block.get("lines", []):
        spans = line.get("spans", [])
        text = "".join(s.get("text", "") for s in spans)
        if not text.strip():
            continue
        lines_text.append(text)
        line_boxes.append(line.get("bbox"))
        for s in spans:
            n = len(s.get("text", "").strip())
            if not n:
                continue
            sizes[round(s.get("size", 0) * 2) / 2] += n
            total_chars += n
            if s.get("flags", 0) & 16 or "bold" in s.get("font", "").lower():
                bold_chars += n
    if not lines_text:
        return None
    return {
        "lines": lines_text,
        "line_boxes": line_boxes,
        "bbox": block["bbox"],
        "size": sizes.most_common(1)[0][0] if sizes else 0,
        "sizes": sizes,
        "bold": total_chars > 0 and bold_chars / total_chars > 0.8,
        "chars": total_chars,
    }


def _order_columns(infos: list[dict], page_width: float) -> list[dict]:
    """Reading order for 1- or 2-column pages. Full-width blocks split the page
    into horizontal bands; inside a band, the left column is read before the right."""
    if len(infos) < 4:
        return sorted(infos, key=lambda b: (b["bbox"][1], b["bbox"][0]))
    mid = page_width / 2
    tol = page_width * 0.03

    def side(b: dict) -> str:
        x0, _, x1, _ = b["bbox"]
        if x1 <= mid + tol:
            return "L"
        if x0 >= mid - tol:
            return "R"
        return "F"

    sides = [side(b) for b in infos]
    if sides.count("L") < 2 or sides.count("R") < 2:
        return sorted(infos, key=lambda b: (b["bbox"][1], b["bbox"][0]))
    ordered: list[dict] = []
    band: list[dict] = []
    for b in sorted(infos, key=lambda b: b["bbox"][1]):
        if side(b) == "F":
            ordered.extend(sorted(band, key=lambda x: (side(x) != "L", x["bbox"][1])))
            band = []
            ordered.append(b)
        else:
            band.append(b)
    ordered.extend(sorted(band, key=lambda x: (side(x) != "L", x["bbox"][1])))
    return ordered


def _split_paragraphs(info: dict) -> list[list[str]]:
    """PyMuPDF blocks may hold several paragraphs; split on first-line indents."""
    lines, boxes = info["lines"], info["line_boxes"]
    if len(lines) < 3:
        return [lines]
    left = median(b[0] for b in boxes)
    right = max(b[2] for b in boxes)
    width = max(right - left, 1)
    groups: list[list[str]] = [[lines[0]]]
    for i in range(1, len(lines)):
        prev_box, box = boxes[i - 1], boxes[i]
        indented = box[0] - left > width * 0.03 and box[0] - left < width * 0.25
        prev_short = prev_box[2] < right - width * 0.15
        prev_ends = lines[i - 1].rstrip().endswith((".", "!", "?", '"', "”", "’", ":"))
        if (indented and prev_ends) or (prev_short and prev_ends):
            groups.append([lines[i]])
        else:
            groups[-1].append(lines[i])
    return groups


class PdfExtractor:
    def __init__(self, ocr_mode: str = "auto", languages: list[str] | None = None, ocr_provider: str | None = None, dpi: int = 300, max_pages: int = 5000):
        self.ocr_mode = ocr_mode  # auto | force | off
        self.languages = languages or ["en"]
        self.ocr_provider_name = ocr_provider
        self.dpi = dpi
        self.max_pages = max_pages

    def extract(self, path: Path, progress: ProgressCallback | None = None) -> ExtractedDocument:
        import pymupdf

        try:
            doc = pymupdf.open(path)
        except Exception as exc:
            raise CorruptedFileError(f"This PDF could not be opened. It may be corrupted or not a real PDF ({exc}).") from exc
        if doc.needs_pass:
            raise UnsupportedFileError(
                "This PDF is password-protected or DRM-encrypted. VOXORA only processes files you can open freely.",
                code="encrypted_pdf",
            )
        if doc.page_count > self.max_pages:
            raise UnsupportedFileError(f"This PDF has {doc.page_count} pages; the limit is {self.max_pages}.", code="too_many_pages")

        meta = doc.metadata or {}
        result = ExtractedDocument(
            format="pdf",
            metadata=DocMetadata(
                title=_junk_meta(meta.get("title")),
                author=_junk_meta(meta.get("author")),
                description=_junk_meta(meta.get("subject")),
                year=(re.search(r"(\d{4})", meta.get("creationDate") or "") or [None, None])[1],
            ),
            page_count=doc.page_count,
        )
        result.toc = [TocEntry(title=t.strip(), level=lvl, page=pg) for lvl, t, pg in doc.get_toc(simple=True) if t and t.strip()]

        page_infos: list[tuple[int, list[dict], float, float]] = []
        ocr_pages: list[int] = []
        size_hist: Counter[float] = Counter()
        for i, page in enumerate(doc):
            if progress and i % 10 == 0:
                progress(f"Reading page {i + 1} of {doc.page_count}", i / max(doc.page_count, 1) * 0.3)
            data = page.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)
            infos = [info for b in data.get("blocks", []) if b.get("type") == 0 and (info := _block_info(b))]
            chars = sum(i_["chars"] for i_ in infos)
            has_images = bool(page.get_images(full=False))
            if self.ocr_mode == "force" or (self.ocr_mode == "auto" and chars < MIN_TEXT_CHARS and has_images):
                ocr_pages.append(i)
                infos = []
            for info in infos:
                size_hist.update(info["sizes"])
            page_infos.append((i, infos, page.rect.width, page.rect.height))

        body_size = size_hist.most_common(1)[0][0] if size_hist else 11.0
        heading_sizes = sorted({s for s, n in size_hist.items() if s >= body_size * 1.25}, reverse=True)
        level_of = {s: min(idx + 1, 4) for idx, s in enumerate(heading_sizes)}

        blocks_by_page: dict[int, list[Block]] = {}
        for i, infos, width, height in page_infos:
            page_blocks: list[Block] = []
            for info in _order_columns(infos, width):
                y0, y1 = info["bbox"][1], info["bbox"][3]
                edge = (y1 < height * EDGE_ZONE or y0 > height * (1 - EDGE_ZONE)) and len(info["lines"]) <= 2
                joined = " ".join(info["lines"]).strip()
                size = info["size"]
                is_heading = (
                    size >= body_size * 1.25 and len(joined) < 160 and len(info["lines"]) <= 4 and not edge
                ) or (info["bold"] and len(joined) < 90 and len(info["lines"]) <= 2 and not edge and not joined.endswith("."))
                if is_heading:
                    page_blocks.append(
                        Block(
                            text="\n".join(info["lines"]),
                            kind="heading",
                            level=level_of.get(size, len(heading_sizes) + 1),
                            page=i + 1,
                            font_size=size,
                            bold=info["bold"],
                            meta={"weak": size < body_size * 1.25},
                        )
                    )
                    continue
                for para in _split_paragraphs(info):
                    page_blocks.append(
                        Block(text="\n".join(para), page=i + 1, font_size=size, bold=info["bold"], meta={"edge": edge})
                    )
            blocks_by_page[i] = page_blocks

        if ocr_pages:
            result.ocr = self._run_ocr(doc, ocr_pages, blocks_by_page, result, progress)

        result.blocks = [b for i in range(doc.page_count) for b in blocks_by_page.get(i, [])]
        result.cover_image, result.cover_mime = self._cover(doc)
        if not result.blocks:
            result.warnings.append("No readable text was found in this PDF.")
        doc.close()
        return result

    def _run_ocr(self, doc, pages: list[int], blocks_by_page: dict[int, list[Block]], result: ExtractedDocument, progress) -> OcrReport:
        from app.providers.ocr import get_ocr_provider

        try:
            provider = get_ocr_provider(self.ocr_provider_name, self.languages)
        except ProviderUnavailableError as exc:
            if len(pages) == doc.page_count:
                raise ProviderUnavailableError(
                    "ocr", f"This PDF is scanned (no text layer), but OCR is unavailable: {exc.message}", retryable=False
                ) from exc
            result.warnings.append(f"{len(pages)} scanned page(s) were skipped because OCR is unavailable: {exc.message}")
            return OcrReport(engine="none")
        unsupported = [l for l in self.languages if l not in provider.supported_languages]
        if unsupported:
            result.warnings.append(
                f"The OCR engine '{provider.name}' has no model for: {', '.join(unsupported)}. Text in those languages may be missing."
            )
        report = OcrReport(engine=provider.name)
        confidences: list[tuple[float, int]] = []
        # Pages render in order on this thread (PyMuPDF isn't thread-safe) and are
        # recognized concurrently when the engine supports it; results are consumed
        # in page order, with a bounded window so memory stays flat on huge scans.
        parallel = max(1, int(getattr(provider, "max_parallel_pages", 1)))
        languages = self.languages

        def render(i: int) -> bytes:
            return doc[i].get_pixmap(dpi=self.dpi, colorspace="gray").tobytes("png")

        pool = ThreadPoolExecutor(max_workers=parallel, thread_name_prefix="ocr") if parallel > 1 else None
        inflight: deque = deque()
        feed = iter(pages)

        def submit_next() -> None:
            i = next(feed, None)
            if i is None:
                return
            png = render(i)
            inflight.append((i, pool.submit(provider.recognize, png, languages) if pool else None, png))

        try:
            for _ in range(parallel * 2):
                submit_next()
            n = -1
            while inflight:
                n += 1
                i, future, png = inflight.popleft()
                submit_next()
                if progress:
                    progress(f"Running OCR on page {i + 1} ({n + 1} of {len(pages)} scanned pages)", 0.3 + 0.6 * n / len(pages))
                ocr_page = future.result() if future else provider.recognize(png, languages)
                self._record_ocr_page(ocr_page, i, provider, report, blocks_by_page, confidences)
        finally:
            if pool:
                pool.shutdown(wait=True, cancel_futures=True)
        total = sum(c for _, c in confidences)
        report.mean_confidence = sum(c * w for c, w in confidences) / total if total else None
        return report

    @staticmethod
    def _record_ocr_page(ocr_page, i, provider, report, blocks_by_page, confidences) -> None:
        report.engine = ocr_page.engine or provider.name
        blocks_by_page[i] = ocr_page_to_blocks(ocr_page, i + 1)
        conf = ocr_page.mean_confidence
        chars = sum(len(ln.text) for ln in ocr_page.lines)
        if conf is not None and chars:
            confidences.append((conf, chars))
            if conf < 0.7:
                report.low_confidence_pages.append(i + 1)
        report.pages_ocrd += 1

    def _cover(self, doc) -> tuple[bytes | None, str | None]:
        """Use page 1 as the cover when it is dominated by an image."""
        if not doc.page_count:
            return None, None
        page = doc[0]
        area = page.rect.width * page.rect.height
        image_area = 0.0
        for info in page.get_image_info():
            x0, y0, x1, y1 = info["bbox"]
            image_area += max(0, x1 - x0) * max(0, y1 - y0)
        text_chars = len(page.get_text("text").strip())
        if area and (image_area / area > 0.4 and text_chars < 400):
            pix = page.get_pixmap(dpi=110)
            return pix.tobytes("jpeg", jpg_quality=88), "image/jpeg"
        return None, None
