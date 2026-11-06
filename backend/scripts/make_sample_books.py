"""Generate the sample book in every supported input format.

    python scripts/make_sample_books.py [output_dir]

Outputs: .txt, .pdf (text layer, with running headers, page numbers and
hyphenated line breaks), -scanned.pdf (images only, exercises OCR), .docx, .epub
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sample_book import AUTHOR, CHAPTERS, DEDICATION, TITLE, as_plain_text, toc_lines  # noqa: E402

PAGE_W, PAGE_H = 420, 600
MARGIN = 48


def make_txt(out: Path) -> Path:
    path = out / "lantern-at-gull-point.txt"
    path.write_text(as_plain_text(), encoding="utf-8")
    return path


def _hyphen_wrap(text: str, width: int) -> list[str]:
    """Wrap like a typesetter, hyphenating some long words across lines."""
    lines: list[str] = []
    for line in textwrap.wrap(text, width=width, break_long_words=False):
        lines.append(line)
    # Hyphenate: move the first half of the next line's first long word up.
    for i in range(len(lines) - 1):
        nxt = lines[i + 1].split(" ", 1)
        word = nxt[0]
        if len(word) >= 8 and word.isalpha() and len(lines[i]) + len(word) // 2 + 1 <= width + 4:
            cut = len(word) // 2
            lines[i] = f"{lines[i]} {word[:cut]}-"
            lines[i + 1] = word[cut:] + (" " + nxt[1] if len(nxt) > 1 else "")
    return lines


def make_pdf(out: Path, scanned: bool = False) -> Path:
    import pymupdf

    doc = pymupdf.open()
    page_no = 0
    state = {"page": None, "y": 0.0}

    def new_page(running_head: bool = True):
        nonlocal page_no
        page_no += 1
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        if running_head and page_no > 2:
            page.insert_text((MARGIN, 30), TITLE.upper(), fontsize=7, fontname="helv")
            page.insert_text((PAGE_W / 2 - 6, PAGE_H - 24), str(page_no), fontsize=8, fontname="helv")
        state["page"], state["y"] = page, 70.0
        return page

    def write(text: str, size: float = 10.5, font: str = "tiro", gap: float = 6, width: int = 62, hyphenate: bool = True):
        lines = _hyphen_wrap(text, width) if hyphenate else textwrap.wrap(text, width)
        for line in lines:
            if state["y"] + size * 1.4 > PAGE_H - 50:
                new_page()
            state["page"].insert_text((MARGIN, state["y"]), line, fontsize=size, fontname=font)
            state["y"] += size * 1.4
        state["y"] += gap

    new_page(running_head=False)
    state["y"] = 200
    write(TITLE, size=22, font="tibo", width=28, hyphenate=False)
    write(f"by {AUTHOR}", size=12, font="tiro", hyphenate=False)
    new_page(running_head=False)
    write("Copyright © 2026. Released into the public domain (CC0).", size=8, hyphenate=False)
    write("Dedication", size=16, font="tibo", hyphenate=False)
    write(DEDICATION, size=10.5, font="tiit", hyphenate=False)
    new_page()
    write("Contents", size=16, font="tibo", hyphenate=False)
    for n, t in enumerate(toc_lines()):
        write(f"{t} ........ {3 + n * 2}", size=10, gap=1, hyphenate=False)
    toc = []
    for part, title, paras in CHAPTERS:
        if part:
            new_page()
            state["y"] = 240
            write(part.upper(), size=18, font="tibo", hyphenate=False)
            toc.append([1, part, page_no])
        new_page()
        state["y"] = 110
        write(title, size=16, font="tibo", gap=14, width=40, hyphenate=False)
        toc.append([2 if part or title.startswith("Chapter") else 1, title, page_no])
        for p in paras:
            write(p)
    if not scanned:
        doc.set_toc(toc)
        doc.set_metadata({"title": TITLE, "author": AUTHOR})
        path = out / "lantern-at-gull-point.pdf"
        doc.save(path)
        return path

    # Scanned version: rasterise every page and rebuild an image-only PDF.
    scanned_doc = pymupdf.open()
    for page in doc:
        pix = page.get_pixmap(dpi=200, colorspace="gray")
        new = scanned_doc.new_page(width=PAGE_W, height=PAGE_H)
        new.insert_image(new.rect, stream=pix.tobytes("jpeg", jpg_quality=72))
    path = out / "lantern-at-gull-point-scanned.pdf"
    scanned_doc.save(path, garbage=4, deflate=True)
    return path


def make_docx(out: Path) -> Path:
    import docx

    d = docx.Document()
    d.core_properties.title = TITLE
    d.core_properties.author = AUTHOR
    d.add_heading(TITLE, level=0)
    d.add_paragraph(f"by {AUTHOR}")
    d.add_heading("Dedication", level=1)
    d.add_paragraph(DEDICATION)
    for part, title, paras in CHAPTERS:
        if part:
            d.add_heading(part, level=1)
        d.add_heading(title, level=1 if not part and not title.startswith("Chapter") else 2)
        for p in paras:
            d.add_paragraph(p)
    path = out / "lantern-at-gull-point.docx"
    d.save(path)
    return path


def make_epub(out: Path) -> Path:
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("lantern-at-gull-point")
    book.set_title(TITLE)
    book.set_language("en")
    book.add_author(AUTHOR)
    items = []
    ded = epub.EpubHtml(title="Dedication", file_name="dedication.xhtml", lang="en")
    ded.content = f"<html><body><h1>Dedication</h1><p><em>{DEDICATION}</em></p></body></html>"
    items.append(ded)
    for n, (part, title, paras) in enumerate(CHAPTERS):
        ch = epub.EpubHtml(title=title, file_name=f"chapter{n + 1:02d}.xhtml", lang="en")
        body = "".join(f"<p>{p}</p>" for p in paras)
        part_html = f"<h1 class='part'>{part}</h1>" if part else ""
        ch.content = f"<html><body>{part_html}<h2>{title}</h2>{body}</body></html>"
        items.append(ch)
    for it in items:
        book.add_item(it)
    book.toc = items
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *items]
    path = out / "lantern-at-gull-point.epub"
    epub.write_epub(str(path), book)
    return path


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "tests" / "fixtures"
    out.mkdir(parents=True, exist_ok=True)
    for fn in (make_txt, make_pdf, lambda o: make_pdf(o, scanned=True), make_docx, make_epub):
        print("wrote", fn(out))


if __name__ == "__main__":
    main()
