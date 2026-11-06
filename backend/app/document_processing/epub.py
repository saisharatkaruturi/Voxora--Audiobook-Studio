"""EPUB extraction: Dublin Core metadata, cover, table of contents and spine
documents. Each spine document becomes a `Section`, titled from the TOC, so the
publisher's chapter structure is preserved.

DRM-protected EPUBs (encryption.xml with non-font resources) are rejected.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from pathlib import Path
from urllib.parse import unquote

from app.core.errors import CorruptedFileError, UnsupportedFileError
from app.document_processing.base import Block, DocMetadata, ExtractedDocument, ProgressCallback, Section, TocEntry

BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "dt", "dd", "figcaption", "td", "th"}
SKIP_TAGS = {"script", "style", "nav", "head", "sup", "rt", "rp", "svg", "math"}
_FONT_OBFUSCATION = ("http://www.idpf.org/2008/embedding", "http://ns.adobe.com/pdf/enc#RC")


def _check_drm(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if "META-INF/rights.xml" in names:
                raise UnsupportedFileError(
                    "This EPUB is DRM-protected. VOXORA does not remove DRM; please use a DRM-free copy.", code="drm_protected"
                )
            if "META-INF/encryption.xml" in names:
                xml = zf.read("META-INF/encryption.xml").decode("utf-8", "ignore")
                algorithms = re.findall(r'EncryptionMethod[^>]*Algorithm="([^"]+)"', xml)
                # Font obfuscation is allowed; any other encryption means protected content.
                if any(not a.startswith(_FONT_OBFUSCATION) for a in algorithms):
                    raise UnsupportedFileError(
                        "This EPUB's content is encrypted (DRM). Please use a DRM-free copy.", code="drm_protected"
                    )
    except zipfile.BadZipFile as exc:
        raise CorruptedFileError("This EPUB file is corrupted (not a valid ZIP archive).") from exc


def _dc(book, name: str) -> str | None:
    values = book.get_metadata("DC", name)
    if values:
        v = values[0][0]
        return v.strip() if isinstance(v, str) and v.strip() else None
    return None


def _html_blocks(html: bytes) -> tuple[list[Block], str | None]:
    import warnings

    from bs4 import BeautifulSoup, NavigableString, Tag, XMLParsedAsHTMLWarning

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(html, "lxml")
    body = soup.body or soup
    for tag in body.find_all(SKIP_TAGS):
        tag.decompose()
    # Footnote reference markers (<a epub:type="noteref">) are not narrated.
    for a in body.find_all("a"):
        if "noteref" in (a.get("epub:type") or "") or "noteref" in " ".join(a.get("class") or []):
            a.decompose()
    blocks: list[Block] = []
    first_heading: str | None = None

    def text_of(tag: Tag) -> str:
        return re.sub(r"[ \t\r\f\v]+", " ", tag.get_text(" ", strip=False)).strip()

    def walk(node: Tag) -> None:
        nonlocal first_heading
        for child in node.children:
            if isinstance(child, NavigableString):
                t = str(child).strip()
                if t and node.name in ("div", "section", "body", "article", "main"):
                    blocks.append(Block(text=t))
                continue
            if not isinstance(child, Tag):
                continue
            name = child.name.lower()
            if name in BLOCK_TAGS:
                if name in ("li", "td", "th") and child.find(BLOCK_TAGS - {"li", "td", "th"}):
                    walk(child)
                    continue
                text = text_of(child)
                if not text:
                    continue
                if re.match(r"h[1-6]$", name):
                    level = int(name[1])
                    blocks.append(Block(text=text, kind="heading", level=level))
                    first_heading = first_heading or text
                else:
                    blocks.append(
                        Block(text=child.get_text("\n") if name == "pre" else text, meta={"list_item": name == "li", "preformatted": name == "pre"})
                    )
            elif name == "br":
                continue
            else:
                walk(child)

    walk(body)
    return blocks, first_heading


def _flatten_toc(toc, level: int = 1) -> list[TocEntry]:
    from ebooklib import epub

    out: list[TocEntry] = []
    for entry in toc:
        if isinstance(entry, tuple) and len(entry) == 2:
            section, children = entry
            href = getattr(section, "href", None)
            out.append(TocEntry(title=(section.title or "").strip(), level=level, href=href))
            out.extend(_flatten_toc(children, level + 1))
        elif isinstance(entry, epub.Link):
            out.append(TocEntry(title=(entry.title or "").strip(), level=level, href=entry.href))
    return [e for e in out if e.title]


class EpubExtractor:
    def extract(self, path: Path, progress: ProgressCallback | None = None) -> ExtractedDocument:
        import ebooklib
        from ebooklib import epub

        _check_drm(path)
        try:
            book = epub.read_epub(str(path), options={"ignore_ncx": False})
        except Exception as exc:
            raise CorruptedFileError(f"This EPUB could not be parsed ({exc}).") from exc

        date = _dc(book, "date")
        result = ExtractedDocument(
            format="epub",
            metadata=DocMetadata(
                title=_dc(book, "title"),
                author=_dc(book, "creator"),
                language=(_dc(book, "language") or "").split("-")[0].lower() or None,
                publisher=_dc(book, "publisher"),
                description=_strip_html(_dc(book, "description")),
                year=(re.search(r"\d{4}", date) or [None])[0] if date else None,
                genre=_dc(book, "subject"),
            ),
        )
        result.toc = _flatten_toc(book.toc)
        toc_by_file: dict[str, str] = {}
        for entry in result.toc:
            if entry.href:
                file = unquote(entry.href.split("#")[0])
                toc_by_file.setdefault(file, entry.title)

        result.cover_image, result.cover_mime = self._cover(book)
        cover_ids = {item.get_id() for item in book.get_items_of_type(ebooklib.ITEM_COVER)}

        sections: list[Section] = []
        spine_ids = [sid for sid, _linear in book.spine]
        for n, sid in enumerate(spine_ids):
            item = book.get_item_with_id(sid)
            if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT or isinstance(item, epub.EpubNav):
                continue
            if progress:
                progress(f"Reading section {n + 1} of {len(spine_ids)}", n / max(len(spine_ids), 1))
            blocks, heading = _html_blocks(item.get_content())
            if not blocks or sid in cover_ids:
                continue
            name = item.get_name()
            title = toc_by_file.get(name) or toc_by_file.get(posixpath.basename(name)) or heading
            sections.append(Section(title=title, blocks=blocks, source_ref=name))
        result.sections = sections
        result.page_count = None
        if not sections:
            result.warnings.append("No readable text was found in this EPUB.")
        return result

    @staticmethod
    def _cover(book) -> tuple[bytes | None, str | None]:
        import ebooklib

        candidates = list(book.get_items_of_type(ebooklib.ITEM_COVER))
        meta = book.get_metadata("OPF", "cover")
        if meta:
            cover_id = meta[0][1].get("content") if isinstance(meta[0][1], dict) else None
            item = book.get_item_with_id(cover_id) if cover_id else None
            if item is not None:
                candidates.insert(0, item)
        for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
            if "cover" in (item.get_name() or "").lower() or "cover" in (item.get_id() or "").lower():
                candidates.append(item)
        for item in candidates:
            media = getattr(item, "media_type", "") or ""
            if media.startswith("image/"):
                return item.get_content(), media
        return None, None


def _strip_html(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"<[^>]+>", " ", value).strip() or None
