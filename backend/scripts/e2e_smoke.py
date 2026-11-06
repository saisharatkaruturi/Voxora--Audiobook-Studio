"""End-to-end smoke test against a running server.

    python scripts/e2e_smoke.py [book-file] [--base http://127.0.0.1:8000] [--voice en_US-lessac-medium]

Registers (or logs in) a test user, uploads a book, waits for analysis,
generates audio, and checks playback, progress, bookmarks, Ask the Book and downloads.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("book", nargs="?", default=str(ROOT / "tests" / "fixtures" / "lantern-at-gull-point.txt"))
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--provider", default="piper")
    ap.add_argument("--voice", default="en_US-lessac-medium")
    ap.add_argument("--chapters", type=int, default=3, help="generate only the first N narrated chapters (0 = all)")
    ap.add_argument("--ask", default="Who is Elias and why is he coming home?")
    args = ap.parse_args()
    c = httpx.Client(base_url=args.base, timeout=120, transport=httpx.HTTPTransport(retries=3))

    def ok(r: httpx.Response) -> dict:
        if r.status_code >= 400:
            print("FAILED", r.request.method, r.request.url, r.status_code, r.text[:500])
            sys.exit(1)
        return r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else {}

    creds = {"email": "smoke@example.com", "password": "smoke-test-password", "display_name": "Smoke Test"}
    r = c.post("/api/auth/register", json=creds)
    if r.status_code == 409:
        r = c.post("/api/auth/login", json={"email": creds["email"], "password": creds["password"]})
    token = ok(r)["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    print("✓ authenticated")

    path = Path(args.book)
    with open(path, "rb") as fh:
        up = ok(c.post("/api/books", files={"file": (path.name, fh)}, data={"auto_analyze": "true"}))
    book_id, job_id = up["book"]["id"], up["job"]["id"]
    print(f"✓ uploaded {path.name} -> {book_id}")

    def wait(job_id: str, label: str, timeout: int = 1800) -> dict:
        start, last = time.time(), None
        while time.time() - start < timeout:
            try:
                job = ok(c.get(f"/api/jobs/{job_id}"))
            except httpx.TransportError:
                time.sleep(1)
                continue
            msg = f"  {label}: {job['status']} {job['progress']}% {job['message']}"
            if msg != last:
                print(msg)
                last = msg
            if job["status"] in ("completed", "failed", "cancelled"):
                return job
            time.sleep(1.5)
        print("TIMEOUT")
        sys.exit(1)

    job = wait(job_id, "analyze")
    assert job["status"] == "completed", job
    chapters = ok(c.get(f"/api/books/{book_id}/chapters"))["items"]
    book = ok(c.get(f"/api/books/{book_id}"))
    print(f"✓ analyzed: '{book['title']}' by {book['author']} — {len(chapters)} sections")
    for ch in chapters:
        print(f"    {'♪' if ch['include_in_audio'] else ' '} [{ch['kind']:<12}] {ch['title']} ({ch['word_count']} words)")

    ok(c.patch(f"/api/books/{book_id}", json={"narration": {"provider": args.provider, "voice_id": args.voice}}))
    est = ok(c.get(f"/api/books/{book_id}/estimate"))
    print(f"✓ voice set; estimate {est['characters']} chars ≈ {est['estimated_audio_minutes']} min")

    narrated = [ch["id"] for ch in chapters if ch["include_in_audio"]]
    target = narrated[: args.chapters] if args.chapters else None
    t0 = time.time()
    job = ok(c.post(f"/api/books/{book_id}/generate", json={"chapter_ids": target}))
    job = wait(job["id"], "generate", 3600)
    assert job["status"] == "completed", job
    print(f"✓ generated in {time.time() - t0:.0f}s: {job['result']}")

    pb = ok(c.get(f"/api/books/{book_id}/playback"))
    assert pb["tracks"], "no playable tracks"
    t = pb["tracks"][0]
    audio = c.get(t["url"], headers={"Range": "bytes=0-1023"})
    assert audio.status_code == 206 and audio.headers["content-type"].startswith("audio/"), (audio.status_code, audio.headers)
    print(f"✓ playback: {len(pb['tracks'])} track(s), total {pb['total_duration']:.1f}s, range request OK")

    tm = ok(c.get(f"/api/chapters/{t['chapter_id']}/timings"))
    print(f"✓ timings: {len(tm['sentences'])} sentences ({tm['timing_source']}); first: {tm['sentences'][:2]}")

    ok(c.put(f"/api/books/{book_id}/progress", json={"chapter_id": t["chapter_id"], "position_seconds": 12.5, "playback_rate": 1.25}))
    again = ok(c.get(f"/api/books/{book_id}/playback"))["progress"]
    assert abs(again["position_seconds"] - 12.5) < 0.01, again
    print(f"✓ progress saved and restored: {again}")

    bm = ok(c.post(f"/api/books/{book_id}/bookmarks", json={"chapter_id": t["chapter_id"], "position_seconds": 8.0, "note": "Important conversation"}))
    print(f"✓ bookmark: {bm['chapter_title']} @ {bm['position_seconds']}s")

    idx = ok(c.post(f"/api/books/{book_id}/index"))
    wait(idx["id"], "index")
    asked = ok(c.post(f"/api/books/{book_id}/ask", json={"question": args.ask}))
    wait(asked["job"]["id"], "ask", 1200)
    ans = ok(c.get(f"/api/books/{book_id}/chat"))["items"][-1]
    print(f"✓ ask ({ans['meta'].get('mode')}): {ans['content'][:400]}")
    print(f"    citations: {[x['chapter_title'] for x in ans['citations']]}")

    dl = ok(c.get(f"/api/books/{book_id}/downloads"))["items"]
    print(f"✓ downloads: {[d['kind'] for d in dl]}")
    z = c.get(f"/api/books/{book_id}/export/zip")
    assert z.status_code == 200 and z.content[:2] == b"PK"
    print(f"✓ zip: {len(z.content) // 1024} KB")
    print("\nALL CHECKS PASSED  book_id =", book_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
