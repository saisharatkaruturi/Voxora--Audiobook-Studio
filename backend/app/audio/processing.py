"""Audio post-processing that keeps sentence timestamps valid.

Silence trimming and long-pause shortening are done here in NumPy (so we know
exactly how timestamps move); loudness normalization and compression are done
by ffmpeg at encode time (they don't change timing).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.audio.ffmpeg import run_ffmpeg

SILENCE_DBFS = -45.0
FRAME_MS = 10


def _frame_rms_db(pcm: np.ndarray, rate: int) -> np.ndarray:
    frame = max(1, rate * FRAME_MS // 1000)
    n = len(pcm) // frame
    if n == 0:
        return np.array([-120.0])
    frames = pcm[: n * frame].astype(np.float32).reshape(n, frame) / 32768.0
    rms = np.sqrt(np.mean(frames**2, axis=1)) + 1e-9
    return 20 * np.log10(rms)


def trim_edges(pcm: np.ndarray, rate: int, keep_ms: int = 40) -> tuple[np.ndarray, int]:
    """Remove leading/trailing silence. Returns (audio, samples removed from start)."""
    if len(pcm) == 0:
        return pcm, 0
    db = _frame_rms_db(pcm, rate)
    voiced = np.nonzero(db > SILENCE_DBFS)[0]
    if len(voiced) == 0:
        return pcm[:0], 0
    frame = rate * FRAME_MS // 1000
    keep = rate * keep_ms // 1000
    start = max(0, voiced[0] * frame - keep)
    end = min(len(pcm), (voiced[-1] + 1) * frame + keep)
    return pcm[start:end], start


@dataclass
class Cut:
    at: float  # seconds (in the original timeline) where removed audio started
    removed: float  # seconds removed


def shorten_long_pauses(pcm: np.ndarray, rate: int, max_pause: float = 1.2, target: float = 0.7) -> tuple[np.ndarray, list[Cut]]:
    """Shorten internal silences longer than `max_pause` to `target` seconds."""
    db = _frame_rms_db(pcm, rate)
    frame = rate * FRAME_MS // 1000
    silent = db <= SILENCE_DBFS
    cuts: list[Cut] = []
    keep_ranges: list[tuple[int, int]] = []
    cursor = 0
    i = 0
    n = len(silent)
    while i < n:
        if silent[i]:
            j = i
            while j < n and silent[j]:
                j += 1
            length = (j - i) * FRAME_MS / 1000
            if length > max_pause and i > 0 and j < n:
                keep_until = i * frame + int(target / 2 * rate)
                resume_at = j * frame - int(target / 2 * rate)
                keep_ranges.append((cursor, keep_until))
                cuts.append(Cut(at=keep_until / rate, removed=(resume_at - keep_until) / rate))
                cursor = resume_at
            i = j
        else:
            i += 1
    if not cuts:
        return pcm, []
    keep_ranges.append((cursor, len(pcm)))
    return np.concatenate([pcm[a:b] for a, b in keep_ranges]), cuts


def remap_time(t: float, cuts: list[Cut]) -> float:
    shift = 0.0
    for c in cuts:
        if t >= c.at + c.removed:
            shift += c.removed
        elif t > c.at:
            shift += t - c.at
    return t - shift


def silence(rate: int, ms: int) -> np.ndarray:
    return np.zeros(int(rate * max(ms, 0) / 1000), dtype=np.int16)


CODECS = {
    "mp3": ["-c:a", "libmp3lame"],
    "m4a": ["-c:a", "aac", "-movflags", "+faststart"],
    "wav": ["-c:a", "pcm_s16le"],
}
MIME = {"m4b": "audio/mp4", "mp3": "audio/mpeg", "m4a": "audio/mp4", "wav": "audio/wav"}


def measure_loudness(raw_path: Path, rate: int, pre_filters: list[str] | None = None) -> float | None:
    """Integrated loudness (EBU R128 / BS.1770, LUFS) of a raw mono s16le file."""
    import re as _re
    import subprocess

    from app.audio.ffmpeg import ffmpeg_exe

    chain = ",".join([*(pre_filters or []), "ebur128"])
    proc = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-nostats", "-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", str(raw_path), "-af", chain, "-f", "null", "-"],
        capture_output=True, text=True, timeout=3600,
    )
    found = _re.findall(r"I:\s+(-?[\d.]+) LUFS", proc.stderr)
    return float(found[-1]) if found else None


# EBU R128 applies K-weighting before gating; on narration the gated plain-RMS level
# sits a near-constant amount below it (measured +0.53 dB, spread 0.07 dB, across
# six real chapters), so a numpy pass over the raw PCM replaces a full ffmpeg pass.
_K_WEIGHT_OFFSET_DB = 0.53


def estimate_loudness(raw_path: Path, rate: int) -> float | None:
    """Integrated loudness (LUFS, BS.1770 gating) of a raw mono s16le file, computed
    in-process: 400 ms blocks at 75% overlap, -70 LUFS absolute and -10 LU relative
    gates. Streams the file a minute at a time, so memory stays small."""
    hop = int(0.1 * rate)
    x = np.memmap(raw_path, dtype=np.int16, mode="r")
    n_hops = len(x) // hop
    if n_hops < 4:
        return None
    energy = np.empty(n_hops, dtype=np.float64)  # sum of squares per 100 ms hop
    step = 600  # hops per slice (one minute)
    for h in range(0, n_hops, step):
        part = np.asarray(x[h * hop : min(n_hops, h + step) * hop], dtype=np.float32) / 32768.0
        energy[h : h + len(part) // hop] = np.square(part).reshape(-1, hop).sum(axis=1, dtype=np.float64)
    del x
    ms = (energy[:-3] + energy[1:-2] + energy[2:-1] + energy[3:]) / (4 * hop)  # 400 ms blocks
    level = -0.691 + 10 * np.log10(np.maximum(ms, 1e-12))
    ms, level = ms[level > -70], level[level > -70]
    if not len(ms):
        return None
    rel = -0.691 + 10 * np.log10(ms.mean()) - 10
    ms = ms[level > rel]
    return -0.691 + 10 * np.log10(ms.mean()) + _K_WEIGHT_OFFSET_DB


def encode_raw(
    raw_path: Path,
    rate: int,
    out_path: Path,
    fmt: str = "mp3",
    bitrate: str = "96k",
    normalize: bool = True,
    target_lufs: float = -18.0,
    compress: bool = False,
) -> None:
    """Encode a raw mono s16le file with loudness normalization and optional gentle compression.

    Normalization is two-pass: measure integrated loudness (EBU R128), then apply one
    static gain plus a true-peak limiter. For narration from a single voice this reaches
    the same loudness as ffmpeg's dynamic `loudnorm` (measured: -18.5 vs -18.4 LUFS) about
    4-5x faster, because loudnorm resamples everything to 192 kHz internally, and it
    never "pumps" the level within a chapter.
    """
    filters = []
    if compress:
        filters.append("acompressor=threshold=-21dB:ratio=2:attack=20:release=250:makeup=1")
    if normalize:
        # Exact ffmpeg measurement when a compressor reshapes the signal first;
        # otherwise the in-process estimate (saves a full decode pass per chapter).
        measured = measure_loudness(raw_path, rate, filters) if filters else estimate_loudness(raw_path, rate)
        if measured is not None and measured > -70:
            gain = max(-20.0, min(20.0, target_lufs - measured))
            filters.append(f"volume={gain:.2f}dB")
        filters.append("alimiter=limit=0.79:level=false")  # about -2 dBTP
    args = ["-y", "-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", str(raw_path)]
    if filters:
        args += ["-af", ",".join(filters), "-ar", str(rate)]
    args += CODECS[fmt]
    if fmt != "wav":
        args += ["-b:a", bitrate]
    args.append(str(out_path))
    run_ffmpeg(args)


def concat_files(inputs: list[Path], out_path: Path, fmt: str, bitrate: str) -> None:
    """Concatenate encoded chapter files into one (re-encodes for clean joins)."""
    list_file = out_path.with_suffix(".txt")
    list_file.write_text("".join(f"file '{p.as_posix()}'\n" for p in inputs), encoding="utf-8")
    try:
        args = ["-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-vn"]
        if fmt == "mp3":
            args += ["-c", "copy"]
        else:
            args += CODECS[fmt] + (["-b:a", bitrate] if fmt != "wav" else [])
        run_ffmpeg([*args, str(out_path)])
    finally:
        list_file.unlink(missing_ok=True)
