"""Audiobook metadata: ID3v2 tags with CHAP/CTOC chapter frames for MP3,
iTunes-style tags + chapter list for M4A."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.audio.ffmpeg import run_ffmpeg


@dataclass
class TagInfo:
    title: str
    album: str
    author: str | None = None
    narrator: str | None = None
    genre: str | None = "Audiobook"
    year: str | None = None
    language: str | None = None
    track: int | None = None
    track_total: int | None = None
    comment: str | None = None
    cover: bytes | None = None
    cover_mime: str = "image/jpeg"


@dataclass
class ChapterMark:
    title: str
    start: float
    end: float


def write_mp3_tags(path: Path, info: TagInfo, chapters: list[ChapterMark] | None = None) -> None:
    from mutagen.id3 import APIC, CHAP, COMM, CTOC, ID3, TALB, TCON, TDRC, TIT2, TLAN, TPE1, TPE2, TRCK, TXXX, CTOCFlags, ID3NoHeaderError

    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.add(TIT2(encoding=3, text=info.title))
    tags.add(TALB(encoding=3, text=info.album))
    if info.author:
        tags.add(TPE1(encoding=3, text=info.author))
        tags.add(TPE2(encoding=3, text=info.author))
    if info.narrator:
        tags.add(TXXX(encoding=3, desc="NARRATOR", text=info.narrator))
    tags.add(TCON(encoding=3, text=info.genre or "Audiobook"))
    if info.year:
        tags.add(TDRC(encoding=3, text=info.year))
    if info.language:
        tags.add(TLAN(encoding=3, text=info.language))
    if info.track:
        tags.add(TRCK(encoding=3, text=f"{info.track}/{info.track_total}" if info.track_total else str(info.track)))
    if info.comment:
        tags.add(COMM(encoding=3, lang="eng", desc="", text=info.comment))
    if info.cover:
        tags.add(APIC(encoding=3, mime=info.cover_mime, type=3, desc="Cover", data=info.cover))
    if chapters:
        ids = [f"ch{i:03d}" for i in range(len(chapters))]
        tags.add(CTOC(element_id="toc", flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED, child_element_ids=ids, sub_frames=[TIT2(encoding=3, text="Chapters")]))
        for cid, ch in zip(ids, chapters):
            tags.add(
                CHAP(
                    element_id=cid,
                    start_time=int(ch.start * 1000),
                    end_time=int(ch.end * 1000),
                    sub_frames=[TIT2(encoding=3, text=ch.title)],
                )
            )
    tags.save(path, v2_version=3)


def write_m4a_tags(path: Path, info: TagInfo, chapters: list[ChapterMark] | None = None) -> None:
    """Remux with ffmpeg to embed chapters, then set tags with mutagen."""
    if chapters:
        meta = [";FFMETADATA1"]
        for ch in chapters:
            safe = ch.title.replace("=", "\\=").replace(";", "\\;").replace("#", "\\#").replace("\n", " ")
            meta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(ch.start * 1000)}", f"END={int(ch.end * 1000)}", f"title={safe}"]
        meta_file = path.with_suffix(".ffmeta")
        tmp = path.with_suffix(".tmp.m4a")
        meta_file.write_text("\n".join(meta), encoding="utf-8")
        try:
            run_ffmpeg(["-y", "-i", str(path), "-i", str(meta_file), "-map_metadata", "1", "-map_chapters", "1", "-c", "copy", str(tmp)])
            tmp.replace(path)
        finally:
            meta_file.unlink(missing_ok=True)
            tmp.unlink(missing_ok=True)
    from mutagen.mp4 import MP4, MP4Cover

    audio = MP4(path)
    audio["\xa9nam"] = [info.title]
    audio["\xa9alb"] = [info.album]
    if info.author:
        audio["\xa9ART"] = [info.author]
        audio["aART"] = [info.author]
    if info.narrator:
        audio["\xa9wrt"] = [info.narrator]
    audio["\xa9gen"] = [info.genre or "Audiobook"]
    if info.year:
        audio["\xa9day"] = [info.year]
    if info.track:
        audio["trkn"] = [(info.track, info.track_total or 0)]
    if info.cover:
        fmt = MP4Cover.FORMAT_PNG if info.cover_mime == "image/png" else MP4Cover.FORMAT_JPEG
        audio["covr"] = [MP4Cover(info.cover, imageformat=fmt)]
    audio.save()


def write_tags(path: Path, fmt: str, info: TagInfo, chapters: list[ChapterMark] | None = None) -> None:
    if fmt == "mp3":
        write_mp3_tags(path, info, chapters)
    elif fmt == "m4a":
        write_m4a_tags(path, info, chapters)
