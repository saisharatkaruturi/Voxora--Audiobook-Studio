"""Measure local TTS throughput for different parallelism settings.

    python scripts/benchmark_tts.py [--voice en_US-lessac-medium] [--configs 1x12,2x6,3x4,4x3,6x2]

Each config is SESSIONSxTHREADS: that many independent ONNX sessions running
concurrently, each with that many intra-op threads. Reports audio seconds
produced per wall second (realtime factor) and characters per second, so the
worker pool can be sized from measurements instead of guesses.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sample_book import CHAPTERS  # noqa: E402

PHONEMIZE_LOCK = threading.Lock()


def load(voice_path: Path, threads: int):
    import json

    import onnxruntime
    from piper import PiperVoice
    from piper.config import PiperConfig

    opts = onnxruntime.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.inter_op_num_threads = 1
    session = onnxruntime.InferenceSession(str(voice_path), sess_options=opts, providers=["CPUExecutionProvider"])
    config = PiperConfig.from_dict(json.loads(Path(f"{voice_path}.json").read_text(encoding="utf-8")))
    voice = PiperVoice(session=session, config=config)
    original = voice.phonemize

    def locked(text):
        with PHONEMIZE_LOCK:
            return original(text)

    voice.phonemize = locked  # espeak-ng is not thread-safe; inference is
    return voice


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="en_US-lessac-medium")
    ap.add_argument("--configs", default="1x12,2x6,3x4,4x3,6x2")
    ap.add_argument("--texts", type=int, default=12)
    args = ap.parse_args()
    voice_path = Path(__file__).resolve().parents[1] / "data" / "voices" / "piper" / f"{args.voice}.onnx"
    paragraphs = [p for _, _, paras in CHAPTERS for p in paras][: args.texts]
    chars = sum(len(p) for p in paragraphs)
    print(f"cpu cores: {os.cpu_count()}  texts: {len(paragraphs)}  chars: {chars}")
    results = []
    for cfg in args.configs.split(","):
        sessions, threads = (int(x) for x in cfg.split("x"))
        voices = [load(voice_path, threads) for _ in range(sessions)]
        rate = voices[0].config.sample_rate
        free = list(voices)
        lock = threading.Lock()

        def run(text: str) -> int:
            with lock:
                v = free.pop()
            try:
                return sum(len(c.audio_int16_array) for c in v.synthesize(text))
            finally:
                with lock:
                    free.append(v)

        run(paragraphs[0])  # warm up
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=sessions) as pool:
            samples = sum(pool.map(run, paragraphs))
        wall = time.perf_counter() - t0
        audio = samples / rate
        results.append((cfg, wall, audio / wall, chars / wall))
        print(f"{cfg:>5}: {wall:6.1f}s wall  {audio / wall:5.1f}x realtime  {chars / wall:7.0f} chars/s")
    best = max(results, key=lambda r: r[2])
    print(f"best: {best[0]} ({best[2]:.1f}x realtime)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
