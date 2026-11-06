"""DOCX extraction with python-docx: headings from paragraph styles, lists,
tables (read row by row), page breaks, core properties and an embedded cover image."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.errors import CorruptedFileError
from app.document_processing.base import Block, DocMetadata, ExtractedDocument, ProgressCallback

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _heading_level(style_name: str) -> int | None:
    name = (style_name or "").lower()
    if name == "title":
        return 0
    if name == "subtitle":
        return None
    m = re.match(r"(heading|überschrift|titre|título|titolo)\s*(\d)", name)
    if m:
        return int(m.group(2))
    return None


class DocxExtractor:
    def extract(self, path: Path, progress: ProgressCallback | None = None) -> ExtractedDocument:
        import docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph as DocxParagraph

        try:
            document = docx.Document(str(path))
        except Exception as exc:
            raise CorruptedFileError(f"This DOCX file could not be opened ({exc}). Try re-saving it from your word processor.") from exc

        props = document.core_properties
        result = ExtractedDocument(
            format="docx",
            metadata=DocMetadata(
                title=(props.title or "").strip() or None,
                author=(props.author or "").strip() or None,
                description=(props.subject or props.comments or "").strip() or None,
                language=(props.language or "").split("-")[0].lower() or None,
                year=str(props.created.year) if props.created else None,
                genre=(props.category or "").strip() or None,
            ),
        )
        page = 1
        blocks: list[Block] = []
        body = document.element.body
        first_heading_seen = False
        for child in body.iterchildren():
            if child.tag == f"{_W}p":
                para = DocxParagraph(child, document)
                xml = child.xml
                if 'w:type="page"' in xml or "lastRenderedPageBreak" in xml:
                    page += xml.count('w:type="page"') or 1
                text = para.text.strip()
                if not text:
                    if not first_heading_seen and result.cover_image is None and "graphicData" in xml:
                        result.cover_image, result.cover_mime = self._inline_image(document, child)
                    continue
                style = para.style.name if para.style is not None else ""
                level = _heading_level(style)
                is_list = "List" in style or child.find(f".//{_W}numPr") is not None
                if level is not None:
                    first_heading_seen = True
                    if level == 0 and not result.metadata.title:
                        result.metadata.title = text
                    blocks.append(Block(text=text, kind="heading", level=max(level, 1), page=page, meta={"style": style}))
                elif (style or "").lower() == "subtitle":
                    if not result.metadata.subtitle:
                        result.metadata.subtitle = text
                    blocks.append(Block(text=text, page=page, meta={"style": style}))
                else:
                    bold = all(r.bold for r in para.runs if r.text.strip()) and bool(para.runs)
                    blocks.append(Block(text=text, page=page, bold=bold, meta={"list_item": is_list, "style": style}))
            elif child.tag == f"{_W}tbl":
                table = Table(child, document)
                for row in table.rows:
                    cells = []
                    for cell in row.cells:
                        t = cell.text.strip()
                        if t and (not cells or cells[-1] != t):  # merged cells repeat
                            cells.append(t)
                    if cells:
                        blocks.append(Block(text="; ".join(cells), page=page, meta={"table": True}))
        result.blocks = blocks
        result.page_count = page
        return result

    @staticmethod
    def _inline_image(document, element) -> tuple[bytes | None, str | None]:
        blips = element.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip")
        for blip in blips:
            rid = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
            part = document.part.related_parts.get(rid) if rid else None
            if part is not None and getattr(part, "content_type", "").startswith("image/"):
                return part.blob, part.content_type
        return None, None
