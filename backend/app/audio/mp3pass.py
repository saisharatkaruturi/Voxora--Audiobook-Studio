"""Build chapter MP3s directly from a cloud voice's MP3 frames (no decode/re-encode).

Microsoft Edge voices return CBR MP3 (MPEG-2 Layer III, 24 kHz mono, 48 kbps) at a
consistent -20.5 to -21.3 LUFS across voices, which is already inside the usual
audiobook range. Decoding that and re-encoding it cost 150-440 CPU seconds per hour
of audio on a laptop, and re-encoding lossy audio loses a little quality. Instead the
frames are appended as-is, with pauses made of silent frames in the same format.
"""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from functools import lru_cache

from app.audio.ffmpeg import ffmpeg_exe
from app.audio.mp3join import _audio_frames, _frame


@dataclass(frozen=True)
class Mp3Format:
    version: int
    rate: int
    channels: int
    bitrate_kbps: int

    @property
    def frame_seconds(self) -> float:
        return (1152 if self.version == 3 else 576) / self.rate


def split_frames(data: bytes) -> tuple[bytes, int, Mp3Format]:
    """The audio frames of an MP3 (tags and Xing/Info frame removed), their count and format.
    Raises ValueError if the frames don't share one CBR format."""
    start, end, key = _audio_frames(data)
    count, i, kbps = 0, start, None
    while i < end:
        f = _frame(data, i)
        if f is None:
            raise ValueError("unexpected bytes between MP3 frames")
        rate_kbps = f[0] * 8 * key[1] // ((1152 if key[0] == 3 else 576) * 1000)
        if kbps is None:
            kbps = rate_kbps
        elif abs(rate_kbps - kbps) > 1:  # padding makes lengths differ by a byte
            raise ValueError("variable-bitrate MP3")
        count += 1
        i += f[0]
    if not count:
        raise ValueError("no MP3 frames")
    return data[start:end], count, Mp3Format(key[0], key[1], key[2], kbps)


_silence_lock = threading.Lock()


@lru_cache(maxsize=8)
def _silent_frame(fmt: Mp3Format) -> bytes:
    """One self-contained silent frame in `fmt` (bit reservoir off, so it never
    references bytes of the frame before it)."""
    layout = "mono" if fmt.channels == 3 else "stereo"
    out = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"anullsrc=r={fmt.rate}:cl={layout}", "-t", "2",
         "-c:a", "libmp3lame", "-b:a", f"{fmt.bitrate_kbps}k", "-reservoir", "0", "-write_xing", "0", "-id3v2_version", "0", "-f", "mp3", "pipe:1"],
        capture_output=True, check=True,
    ).stdout
    frames, count, got = split_frames(out)
    if (got.version, got.rate, got.channels, got.bitrate_kbps) != (fmt.version, fmt.rate, fmt.channels, fmt.bitrate_kbps):
        raise ValueError(f"silence encoder produced {got}, wanted {fmt}")
    size = len(frames) // count
    # A frame from the middle of the stream: past the encoder's start-up frames.
    return frames[size * (count // 2) : size * (count // 2 + 1)]


def silence(fmt: Mp3Format, seconds: float) -> tuple[bytes, int]:
    """Silent frames lasting about `seconds` (rounded to whole frames)."""
    n = max(0, round(seconds / fmt.frame_seconds))
    if not n:
        return b"", 0
    with _silence_lock:
        frame = _silent_frame(fmt)
    return frame * n, n
