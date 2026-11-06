"""ffmpeg access. Uses FFMPEG_PATH, then ffmpeg on PATH, then the binary bundled
with `imageio-ffmpeg` (so no system install is required)."""

from __future__ import annotations

import io

import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.core.config import get_settings
from app.core.errors import StudioError


class AudioProcessingError(StudioError):
    code = "audio_processing_failed"
    status_code = 500
    retryable = True


@lru_cache
def ffmpeg_exe() -> str:
    configured = get_settings().ffmpeg_path
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - environment specific
        raise AudioProcessingError("ffmpeg was not found. Install ffmpeg or `pip install imageio-ffmpeg`.", retryable=False) from exc


def run_ffmpeg(args: list[str], input_bytes: bytes | None = None, timeout: int = 3600) -> bytes:
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin", *args]
    try:
        proc = subprocess.run(cmd, input=input_bytes, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise AudioProcessingError("Audio conversion timed out.") from exc
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise AudioProcessingError(f"Audio conversion failed: {err[-1] if err else 'unknown ffmpeg error'}")
    return proc.stdout


def _sf_decode(data: bytes, target_rate: int) -> np.ndarray | None:
    """In-process decode via libsndfile (MP3/FLAC/WAV/OGG): no ffmpeg process per
    chunk, which matters when a book is thousands of chunks. None -> use ffmpeg."""
    try:
        import soundfile as sf

        pcm, rate = sf.read(io.BytesIO(data), dtype="int16", always_2d=True)
    except Exception:
        return None
    if rate != target_rate:
        return None
    return np.ascontiguousarray(pcm[:, 0] if pcm.shape[1] == 1 else pcm.mean(axis=1).astype(np.int16))


def decode_to_pcm16(data: bytes, fmt: str, source_rate: int, target_rate: int) -> np.ndarray:
    """Decode provider output (wav/mp3/raw PCM) to mono int16 at `target_rate`."""
    if fmt != "pcm_s16le":
        pcm = _sf_decode(data, target_rate)
        if pcm is not None:
            return pcm
    if fmt == "pcm_s16le":
        in_args = ["-f", "s16le", "-ar", str(source_rate), "-ac", "1", "-i", "pipe:0"]
        if source_rate == target_rate:
            return np.frombuffer(data, dtype=np.int16).copy()
    else:
        in_args = ["-i", "pipe:0"]
    out = run_ffmpeg([*in_args, "-f", "s16le", "-ac", "1", "-ar", str(target_rate), "pipe:1"], input_bytes=data)
    return np.frombuffer(out, dtype=np.int16).copy()


def pcm_to_flac(pcm: np.ndarray, rate: int) -> bytes:
    try:
        import soundfile as sf

        buf = io.BytesIO()
        sf.write(buf, pcm, rate, format="FLAC", subtype="PCM_16")
        return buf.getvalue()
    except Exception:
        pass
    return run_ffmpeg(["-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", "pipe:0", "-c:a", "flac", "-f", "flac", "pipe:1"], input_bytes=pcm.tobytes())


def flac_to_pcm(data: bytes, rate: int) -> np.ndarray:
    return decode_to_pcm16(data, "flac", rate, rate)
