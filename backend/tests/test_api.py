"""End-to-end API tests: the real FastAPI app, database, job queue, audio pipeline
and storage, with the deterministic FakeTTS engine from conftest."""

import os
import zipfile
from io import BytesIO

from tests.conftest import FIXTURES, run_jobs, upload


def _narrated(client, headers, book_id):
    return [c for c in client.get(f"/api/books/{book_id}/chapters", headers=headers).json()["items"] if c["include_in_audio"]]


def _use_fake_voice(client, headers, book_id):
    r = client.patch(f"/api/books/{book_id}", headers=headers, json={"narration": {"provider": "fake", "voice_id": "fake-en", "build_full_audiobook": True}})
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- auth


def test_auth_required_and_tokens_work(client, user):
    headers, me = user
    assert client.get("/api/books").status_code == 401
    assert client.get("/api/auth/me", headers=headers).json()["email"] == me["email"]
    bad = client.post("/api/auth/login", json={"email": me["email"], "password": "wrong-password"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_credentials"


def test_users_cannot_see_each_others_books(client, user):
    headers, _ = user
    book = upload(client, headers, analyze=False)["book"]
    r = client.post("/api/auth/register", json={"email": "intruder@example.com", "password": "another password", "display_name": "Other"})
    other = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.get(f"/api/books/{book['id']}", headers=other).status_code in (403, 404)
    assert client.get("/api/books", headers=other).json()["total"] == 0


# --------------------------------------------------------------------------- upload & analysis


def test_upload_validation(client, user):
    headers, _ = user
    r = client.post("/api/books", headers=headers, files={"file": ("evil.pdf", b"MZ\x90\x00binary")})
    assert r.status_code == 415
    assert r.json()["error"]["message"]


def test_upload_analyze_and_edit_chapters(client, user):
    headers, _ = user
    up = upload(client, headers, "lantern-at-gull-point.docx")
    book_id = up["book"]["id"]
    book = client.get(f"/api/books/{book_id}", headers=headers).json()
    assert book["status"] == "review"
    assert book["title"].lower() == "the lantern at gull point"
    chapters = client.get(f"/api/books/{book_id}/chapters", headers=headers).json()["items"]
    titles = [c["title"] for c in chapters]
    assert "Chapter 1: The Keeper" in titles

    ch1 = next(c for c in chapters if c["title"] == "Chapter 1: The Keeper")
    ch2 = next(c for c in chapters if c["title"] == "Chapter 2: The Letter")
    # rename
    r = client.patch(f"/api/chapters/{ch1['id']}", headers=headers, json={"title": "Chapter 1: The Lighthouse Keeper"})
    assert r.json()["title"] == "Chapter 1: The Lighthouse Keeper"
    # edit text (blank line = paragraph break)
    detail = client.get(f"/api/chapters/{ch2['id']}", headers=headers).json()
    text = "\n\n".join(p["text"] for p in detail["paragraphs"]) + "\n\nA brand new closing paragraph."
    r = client.patch(f"/api/chapters/{ch2['id']}", headers=headers, json={"text": text})
    assert r.json()["paragraphs"][-1]["text"] == "A brand new closing paragraph."
    # split then merge back
    n = len(r.json()["paragraphs"])
    new_id = client.post(f"/api/chapters/{ch2['id']}/split", headers=headers, json={"paragraph_index": n - 1, "title": "Coda"}).json()["chapter_id"]
    assert client.get(f"/api/chapters/{new_id}", headers=headers).json()["title"] == "Coda"
    merged = client.post(f"/api/books/{book_id}/chapters/merge", headers=headers, json={"chapter_ids": [ch2["id"], new_id]})
    assert merged.status_code == 200
    # reorder: reverse, then check positions
    ids = [c["id"] for c in client.get(f"/api/books/{book_id}/chapters", headers=headers).json()["items"]]
    after = client.post(f"/api/books/{book_id}/chapters/reorder", headers=headers, json={"chapter_ids": ids[::-1]}).json()["items"]
    assert [c["id"] for c in after] == ids[::-1]
    # delete
    assert client.delete(f"/api/chapters/{new_id}", headers=headers).status_code in (204, 404)


# --------------------------------------------------------------------------- generation, resume, cache


def test_generation_resume_cache_playback_and_downloads(client, user, fake_tts):
    headers, _ = user
    book_id = upload(client, headers)["book"]["id"]
    _use_fake_voice(client, headers, book_id)
    narrated = _narrated(client, headers, book_id)
    assert len(narrated) >= 4

    # Fail on chapter 3's text: earlier chapters must be kept, later ones untouched.
    fake_tts.fail_on = "Chapter 3"  # the spoken chapter title
    job = client.post(f"/api/books/{book_id}/generate", headers=headers, json={}).json()
    run_jobs()
    status = {c["title"]: c["audio_status"] for c in _narrated(client, headers, book_id)}
    assert status["Chapter 1: The Keeper"] == "done"
    assert status["Chapter 3: The Signal"] in ("failed", "pending", "queued")
    assert status.get("Chapter 4: The Long Night") != "done" or status["Chapter 3: The Signal"] == "failed"

    # Resume: only unfinished chapters are synthesized; finished ones come from cache/current audio.
    fake_tts.fail_on = None
    calls_before = fake_tts.calls
    j = client.get(f"/api/jobs/{job['id']}", headers=headers).json()
    if j["status"] == "failed":
        client.post(f"/api/jobs/{job['id']}/resume", headers=headers)
    else:
        client.post(f"/api/books/{book_id}/generate", headers=headers, json={})
    for _ in range(5):
        if not run_jobs():
            break
    # retries may be scheduled in the future; force them due
    from app.db.session import session_scope
    from app.models import GenerationJob

    with session_scope() as db:
        for g in db.query(GenerationJob).filter(GenerationJob.status == "queued"):
            g.run_after = None
    run_jobs()
    statuses = {c["audio_status"] for c in _narrated(client, headers, book_id)}
    assert statuses == {"done"}, statuses
    synthesized_on_resume = fake_tts.calls - calls_before

    # Regenerating with identical text + voice reuses every cached segment.
    calls_before = fake_tts.calls
    client.post(f"/api/books/{book_id}/generate", headers=headers, json={"force": True})
    run_jobs()
    assert fake_tts.calls == calls_before, "unchanged text should never be re-synthesized"
    assert synthesized_on_resume > 0

    book = client.get(f"/api/books/{book_id}", headers=headers).json()
    assert book["status"] == "ready" and book["total_duration"] > 0

    # Playback: tracks with offsets, signed URLs that support HTTP range requests.
    pb = client.get(f"/api/books/{book_id}/playback", headers=headers).json()
    assert len(pb["tracks"]) == len(narrated)
    first = pb["tracks"][0]
    audio = client.get(first["url"], headers={"Range": "bytes=0-99"})
    assert audio.status_code == 206 and audio.headers["content-type"] == "audio/mpeg"
    assert client.get(first["url"].replace("sig=", "sig=x")).status_code == 403

    # Sentence timings for read-along.
    tm = client.get(f"/api/chapters/{first['chapter_id']}/timings", headers=headers).json()
    assert tm["sentences"] and tm["timing_source"] == "provider"
    t0s = [s[3] for s in tm["sentences"]]
    assert t0s == sorted(t0s)

    # Progress + resume.
    second = pb["tracks"][1]
    client.put(f"/api/books/{book_id}/progress", headers=headers, json={"chapter_id": second["chapter_id"], "position_seconds": 1.5, "playback_rate": 1.25})
    again = client.get(f"/api/books/{book_id}/playback", headers=headers).json()["progress"]
    assert again["chapter_id"] == second["chapter_id"] and again["position_seconds"] == 1.5 and again["playback_rate"] == 1.25
    assert abs(again["book_position_seconds"] - (second["offset"] + 1.5)) < 0.05
    cont = client.get("/api/books/continue", headers=headers).json()["items"]
    assert any(b["id"] == book_id for b in cont)

    # Bookmarks.
    bm = client.post(f"/api/books/{book_id}/bookmarks", headers=headers, json={"chapter_id": second["chapter_id"], "position_seconds": 1.0, "note": "Important conversation"}).json()
    assert bm["note"] == "Important conversation"
    assert client.delete(f"/api/bookmarks/{bm['id']}", headers=headers).status_code == 204

    # Downloads: full book with ID3 chapters, chapter files, texts, ZIP.
    kinds = {d["kind"] for d in client.get(f"/api/books/{book_id}/downloads", headers=headers).json()["items"]}
    assert {"full", "chapter", "processed_text", "zip"} <= kinds
    from mutagen.id3 import ID3

    full = next(d for d in client.get(f"/api/books/{book_id}/downloads", headers=headers).json()["items"] if d["kind"] == "full")
    data = client.get(full["url"]).content
    tags = ID3(BytesIO(data))
    assert tags["TIT2"].text[0].lower() == "the lantern at gull point"
    assert tags.getall("CHAP"), "full audiobook should carry chapter markers"
    z = client.get(f"/api/books/{book_id}/export/zip", headers=headers)
    names = zipfile.ZipFile(BytesIO(z.content)).namelist()
    assert any(n.endswith(".mp3") for n in names) and any("metadata" in n for n in names)


def test_pause_and_cancel(client, user):
    headers, _ = user
    book_id = upload(client, headers)["book"]["id"]
    _use_fake_voice(client, headers, book_id)
    job = client.post(f"/api/books/{book_id}/generate", headers=headers, json={}).json()
    assert client.post(f"/api/jobs/{job['id']}/pause", headers=headers).json()["status"] == "paused"
    assert run_jobs() == []  # paused jobs are not picked up
    assert client.post(f"/api/jobs/{job['id']}/resume", headers=headers).json()["status"] == "queued"
    assert client.post(f"/api/jobs/{job['id']}/cancel", headers=headers).json()["status"] == "cancelled"
    assert client.get(f"/api/books/{book_id}", headers=headers).json()["status"] in ("review", "ready")


# --------------------------------------------------------------------------- ask the book


def test_ask_the_book_is_scoped_to_one_book(client, user):
    headers, _ = user
    book_id = upload(client, headers)["book"]["id"]
    client.post(f"/api/books/{book_id}/index", headers=headers)
    run_jobs()
    assert client.get(f"/api/books/{book_id}/ask/status", headers=headers).json()["indexed_chunks"] > 0
    # No LLM in tests: the answer is the best-matching passages, clearly labelled.
    ans = client.post(f"/api/books/{book_id}/ask?sync=true", headers=headers, json={"question": "Who is Elias?"}).json()
    assert ans["mode"] == "passages_only"
    assert any("Elias" in c["excerpt"] for c in ans["citations"])
    from app.services.rag import namespace, retrieve

    assert namespace(book_id) == f"books/{book_id}"
    assert all(p.chapter_id for p in retrieve(book_id, "Elias"))
    # A different book's index is never consulted.
    other_id = upload(client, headers, "lantern-at-gull-point.txt")["book"]["id"]
    assert retrieve(other_id, "Elias") == []  # not indexed yet


def test_m4b_export_has_chapters(client, user, fake_tts):
    headers, _ = user
    book_id = upload(client, headers)["book"]["id"]
    _use_fake_voice(client, headers, book_id)
    client.post(f"/api/books/{book_id}/generate", headers=headers, json={})
    run_jobs()
    items = client.get(f"/api/books/{book_id}/downloads", headers=headers).json()["items"]
    assert any(i["kind"] == "m4b" and i.get("buildable") for i in items)
    assert client.post(f"/api/books/{book_id}/export/m4b", headers=headers).status_code == 200
    run_jobs()
    m4b = next(i for i in client.get(f"/api/books/{book_id}/downloads", headers=headers).json()["items"] if i["kind"] == "m4b")
    assert m4b["url"]
    from mutagen.mp4 import MP4

    data = client.get(m4b["url"]).content
    import tempfile, os

    fd, path = tempfile.mkstemp(suffix=".m4b")
    os.close(fd)
    try:
        open(path, "wb").write(data)
        mp4 = MP4(path)
        assert mp4["\xa9nam"][0].lower() == "the lantern at gull point"
        assert len(mp4.chapters) == len(_narrated(client, headers, book_id))
    finally:
        os.unlink(path)


def test_content_modes(client, user):
    headers, _ = user
    book_id = upload(client, headers)["book"]["id"]
    items = client.get(f"/api/books/{book_id}/chapters", headers=headers).json()["items"]
    kinds = {c["kind"]: c for c in items}
    # Narrative Only is the default: story sections in, front matter out.
    assert kinds["chapter"]["include_in_audio"] and kinds["chapter"]["group"] == "narrative"
    assert not kinds["toc"]["include_in_audio"] and kinds["toc"]["group"] == "front"
    ded = next((c for c in items if c["kind"] == "dedication"), None)
    if ded:
        assert not ded["include_in_audio"]
        full = client.post(f"/api/books/{book_id}/content-mode", headers=headers, json={"mode": "full"}).json()["items"]
        assert next(c for c in full if c["id"] == ded["id"])["include_in_audio"]
        assert not next(c for c in full if c["kind"] == "toc")["include_in_audio"]
    # Toggling one section switches the book to Custom.
    ch = kinds["chapter"]
    client.patch(f"/api/chapters/{ch['id']}", headers=headers, json={"include_in_audio": False})
    assert client.get(f"/api/books/{book_id}", headers=headers).json()["narration"]["content_mode"] == "custom"


def test_upload_with_spaces_and_unicode_in_filename(client, user):
    """Real book files are named like 'The Chase - Elle Kennedy.pdf'."""
    headers, _ = user
    data = (FIXTURES / "lantern-at-gull-point.pdf").read_bytes()
    for name in ["The Chase - Elle Kennedy.pdf", "Mara's Book (2nd ed.) — Final.pdf", "తెలుగు కథ.pdf"]:
        r = client.post("/api/books", headers=headers, files={"file": (name, data)}, data={"auto_analyze": "false"})
        assert r.status_code == 201, (name, r.text)
        items = client.get(f"/api/books/{r.json()['book']['id']}/downloads", headers=headers).json()["items"]
        original = next(i for i in items if i["kind"] == "original")
        assert "Original file" in original["label"]
        assert client.get(original["url"]).status_code == 200


def test_mp3_passthrough_builds_chapters_from_provider_frames(client, user, fake_tts, monkeypatch):
    """Cloud MP3 voices: chapters are assembled from the provider's own frames plus
    silent frames (no decode/re-encode), and still decode cleanly with exact timings."""
    import re
    import subprocess

    from app.audio.ffmpeg import ffmpeg_exe
    from app.core.config import BACKEND_DIR
    from app.db.session import session_scope
    from app.models import AudioAsset, Chapter
    from app.providers.tts.base import SynthesisResult
    from sqlalchemy import select

    original = type(fake_tts).synthesize

    def as_mp3(self, sentences, options):
        wav = original(self, sentences, options)
        mp3 = subprocess.run(
            [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-ar", "24000", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "48k", "-f", "mp3", "pipe:1"],
            input=wav.audio, capture_output=True, check=True,
        ).stdout
        return SynthesisResult(audio=mp3, format="mp3", sample_rate=24000, sentence_times=wav.sentence_times)

    monkeypatch.setattr(type(fake_tts), "synthesize", as_mp3)
    monkeypatch.setattr(type(fake_tts), "mp3_passthrough", True, raising=False)

    headers, _ = user
    book_id = upload(client, headers)["book"]["id"]
    _use_fake_voice(client, headers, book_id)
    client.post(f"/api/books/{book_id}/generate", headers=headers, json={})
    run_jobs()

    from app.providers.storage import get_storage

    storage = get_storage()
    with session_scope() as db:
        assets = db.scalars(select(AudioAsset).join(Chapter, AudioAsset.chapter_id == Chapter.id).where(Chapter.book_id == book_id, AudioAsset.kind == "chapter")).all()
        assert assets
        for a in assets:
            assert (a.meta or {}).get("passthrough") is True
            path = storage.local_path(a.storage_key)
            # -map 0:a: the embedded cover art is a (one-frame) video stream.
            proc = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path), "-map", "0:a", "-f", "null", "-"], capture_output=True, text=True)
            assert proc.returncode == 0 and "error" not in proc.stderr.lower()
            h, m, s = re.findall(r"time=(\d+):(\d+):([\d.]+)", proc.stderr)[-1]
            if os.environ.get("DEBUG_PASSTHROUGH"):
                import shutil

                shutil.copy(path, os.environ["DEBUG_PASSTHROUGH"])
                print("DURATION", a.duration)
            assert abs(int(h) * 3600 + int(m) * 60 + float(s) - a.duration) < 0.1
            starts = [t[3] for t in a.timings]
            assert starts == sorted(starts) and all(0 <= t[3] <= t[4] <= a.duration + 0.01 for t in a.timings)
