"""Join MP3 files at disk speed by concatenating their audio frames.

An MP3 stream is a sequence of self-contained frames, so chapter files encoded
with identical settings can be joined without decoding: drop each file's ID3
tags and its Xing/Info header frame, then append the frames. (ffmpeg's concat
demuxer with stream copy measured ~2 MB/s on a 548 MB book; this runs at the
speed of the disk.) Tags and chapter markers are written afterwards.
"""

from __future__ import annotations

from pathlib import Path

# kbps by [version is MPEG-1][bitrate index], Layer III
_BITRATES = {
    True: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    False: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
}
_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


def _frame(buf: bytes, i: int) -> tuple[int, tuple] | None:
    """(frame length, format key) if a valid Layer III frame header starts at i."""
    if i + 4 > len(buf) or buf[i] != 0xFF or (buf[i + 1] & 0xE0) != 0xE0:
        return None
    version = (buf[i + 1] >> 3) & 3  # 3 = MPEG-1, 2 = MPEG-2, 0 = MPEG-2.5
    layer = (buf[i + 1] >> 1) & 3
    bitrate_idx = buf[i + 2] >> 4
    rate_idx = (buf[i + 2] >> 2) & 3
    if version == 1 or layer != 1 or bitrate_idx in (0, 15) or rate_idx == 3:
        return None
    mpeg1 = version == 3
    bitrate = _BITRATES[mpeg1][bitrate_idx] * 1000
    rate = _RATES[version][rate_idx]
    padding = (buf[i + 2] >> 1) & 1
    length = (144 if mpeg1 else 72) * bitrate // rate + padding
    channels = buf[i + 3] >> 6
    return length, (version, rate, channels)


def _duration(data: bytes, start: int, end: int, key: tuple) -> float:
    """Exact playing time of data[start:end] (frames x samples per frame / rate)."""
    version, rate, _channels = key
    per_frame = 1152 if version == 3 else 576
    count, i = 0, start
    while i < end:
        f = _frame(data, i)
        if f is None:
            i += 1  # resync past stray bytes
            continue
        count += 1
        i += f[0]
    return count * per_frame / rate


def _audio_frames(data: bytes) -> tuple[int, int, tuple]:
    """The frame region of one MP3 file, minus tags and the Xing/Info frame."""
    start, end = 0, len(data)
    if data[:3] == b"ID3" and len(data) >= 10:
        size = (data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9]
        start = 10 + size + (10 if data[5] & 0x10 else 0)
    if end - start >= 128 and data[end - 128 : end - 125] == b"TAG":
        end -= 128
    # Find the first real frame (confirmed by the frame that follows it).
    i = start
    while i < end:
        f = _frame(data, i)
        if f and (i + f[0] >= end or _frame(data, i + f[0])):
            break
        i += 1
    else:
        raise ValueError("no MPEG audio frames found")
    length, key = f
    head = bytes(data[i : i + length])
    if b"Xing" in head[:64] or b"Info" in head[:64] or b"VBRI" in head[:64]:
        i += length  # the encoder's header frame describes this file only
    return i, end, key


def join_mp3(inputs: list[Path], out_path: Path) -> list[float]:
    """Concatenate MP3 files that share an encoding format; returns each input's
    exact duration in the joined stream (for chapter markers). Raises ValueError if
    the formats differ (the caller then falls back to a re-encoding join)."""
    fmt = None
    durations: list[float] = []
    with open(out_path, "wb") as out:
        for path in inputs:
            data = path.read_bytes()
            start, end, key = _audio_frames(data)
            # Same format *and* bitrate: players estimate a CBR file's duration from it.
            signature = (*key, _frame(data, start)[0] // 8)
            if fmt is None:
                fmt = signature
            elif signature != fmt:
                raise ValueError(f"{path.name} uses a different MP3 format")
            out.write(memoryview(data)[start:end])
            durations.append(_duration(data, start, end, key))
    return durations
