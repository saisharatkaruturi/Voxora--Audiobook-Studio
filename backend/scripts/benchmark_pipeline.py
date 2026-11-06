"""Benchmark the book pipeline at several sizes.

    python scripts/benchmark_pipeline.py [--pages 50,100,200,400,600] [--voice en_US-lessac-medium] [--tts-sample 4000]

For each size it builds a synthetic PDF novel (original text, chapter headings,
running headers and page numbers), then measures:
  - extraction + cleaning + structure detection (the real analyze() pipeline)
  - chunk planning
  - peak Python memory
It also measures real TTS throughput once (parallel engine, current settings) on
a sample and reports the projected synthesis time for each size. Projections
are labelled as such; nothing is extrapolated silently.
"""

from __future__ import annotations

import argparse
import random
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sample_book import CHAPTERS  # noqa: E402

WORDS_PER_PAGE = 300
PARAGRAPHS = [p for _, _, paras in CHAPTERS for p in paras]
SENTENCES = [s.strip() + "." for p in PARAGRAPHS for s in p.replace("?", ".").replace("!", ".").split(".") if len(s.split()) > 3]


def paragraph(rnd: random.Random) -> str:
    """A unique paragraph (so the header/footer de-duplication treats it as prose, like a real book)."""
    return " ".join(rnd.sample(SENTENCES, rnd.randint(3, 6)))


def make_pdf(pages: int, path: Path) -> int:
    import pymupdf

    rnd = random.Random(pages)
    doc = pymupdf.open()
    words = 0
    chapter = 0
    for n in range(1, pages + 1):
        page = doc.new_page(width=432, height=648)
        page.insert_text((54, 36), "THE BENCHMARK NOVEL", fontsize=8)
        page.insert_text((210, 624), str(n), fontsize=9)
        y = 70
        text_parts = []
        if n == 1 or n % 12 == 2:
            chapter += 1
            page.insert_text((54, 100), f"Chapter {chapter}", fontsize=20)
            y = 130
        budget = WORDS_PER_PAGE if y == 70 else WORDS_PER_PAGE - 60
        while budget > 0:
            para = paragraph(rnd)
            text_parts.append(para)
            budget -= len(para.split())
        body = "\n\n".join(text_parts)
        words += len(body.split())
        page.insert_textbox(pymupdf.Rect(54, y, 378, 600), body, fontsize=10.5, lineheight=1.25)
    doc.save(path)
    return words


def tts_throughput(voice: str, sample_chars: int) -> tuple[float, float, int]:
    """Real synthesis on a sample with the production parallel engine. Returns (chars/s, x realtime, workers)."""
    from concurrent.futures import ThreadPoolExecutor

    from app.document_processing.segmentation import split_sentences
    from app.providers.tts import SynthesisOptions, get_tts_provider

    provider = get_tts_provider("piper")
    text, i = [], 0
    while sum(len(t) for t in text) < sample_chars:
        text.append(PARAGRAPHS[i % len(PARAGRAPHS)])
        i += 1
    chunks = [[s.text for s in split_sentences(p)] for p in text]
    opts = SynthesisOptions(voice_id=voice)
    provider.synthesize(chunks[0][:1], opts)  # load sessions
    workers = provider.max_chunk_parallelism
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda c: provider.synthesize(c, opts), chunks))
    wall = time.perf_counter() - t0
    audio_seconds = sum(len(r.audio) / 2 / r.sample_rate for r in results)
    chars = sum(len(t) for t in text)
    return chars / wall, audio_seconds / wall, workers


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="50,100,200,400,600")
    ap.add_argument("--voice", default="en_US-lessac-medium")
    ap.add_argument("--tts-sample", type=int, default=4000, help="characters to synthesize for the throughput measurement (0 = skip)")
    args = ap.parse_args()

    from app.document_processing.pipeline import AnalyzeOptions, analyze

    tts = tts_throughput(args.voice, args.tts_sample) if args.tts_sample else None
    if tts:
        print(f"TTS (measured): {tts[0]:.0f} chars/s, {tts[1]:.1f}x realtime with {tts[2]} parallel sessions\n")
    print(f"{'pages':>5} {'words':>8} {'chapters':>8} {'analyze':>9} {'pages/min':>9} {'peak MB':>8} {'chars':>9} {'TTS (projected)':>16}")
    with tempfile.TemporaryDirectory() as tmp:
        for pages in (int(p) for p in args.pages.split(",")):
            pdf = Path(tmp) / f"bench-{pages}.pdf"
            words = make_pdf(pages, pdf)
            tracemalloc.start()
            t0 = time.perf_counter()
            result = analyze(pdf, "pdf", pdf.name, AnalyzeOptions())
            analyze_s = time.perf_counter() - t0
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            narrated = [c for c in result.structure.chapters if c.include_in_audio]
            chars = sum(len(b.text) for c in narrated for b in c.blocks)
            projected = f"{chars / tts[0] / 60:6.1f} min" if tts else "-"
            print(f"{pages:>5} {words:>8} {len(narrated):>8} {analyze_s:>8.1f}s {pages / analyze_s * 60:>9.0f} {peak / 1e6:>8.0f} {chars:>9} {projected:>16}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
