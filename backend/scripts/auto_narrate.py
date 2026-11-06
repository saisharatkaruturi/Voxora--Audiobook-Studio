"""Narrate every book in the library as soon as its analysis finishes.

Books waiting for review get an Edge voice (if they somehow aren't on one) and
are sent to generation; failed generations are retried once. Exits when every
book is ready, or failed twice.
"""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000/api"
TOKEN = open(sys.argv[1]).read().strip()
retried: set[str] = set()
started_at = time.time()

if sys.platform == "win32":
    # Keep the PC awake (the screen may still turn off) while books are converting;
    # Windows drops the request automatically when this process exits.
    import ctypes

    ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Authorization": f"Bearer {TOKEN}", **({"Content-Type": "application/json"} if data else {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"null")


def books():
    out, page = [], 1
    while True:
        d = call("GET", f"/books?page={page}&page_size=100")
        out += d["items"]
        if page * 100 >= d["total"] or not d["items"]:
            return out
        page += 1


def log(msg):
    print(f"[{(time.time() - started_at) / 60:6.1f}m] {msg}", flush=True)


while True:
    try:
        lib = [b for b in books() if "Lantern" not in (b["title"] or "")]  # skip old test uploads
    except Exception as e:  # server restarting, etc.
        log(f"library unavailable ({e!r}); retrying")
        time.sleep(20)
        continue
    counts: dict[str, int] = {}
    for b in lib:
        counts[b["status"]] = counts.get(b["status"], 0) + 1
        active = b.get("active_job")
        if b["status"] == "review" and not active:
            try:
                if (b.get("narration") or {}).get("provider") != "edge":
                    call("PATCH", f"/books/{b['id']}", {"narration": {"provider": "edge"}})
                    log(f"voice -> Edge for {b['title']}")
                call("POST", f"/books/{b['id']}/generate", {})
                log(f"narrating: {b['title']} ({b.get('word_count')} words, {b.get('language')})")
            except urllib.error.HTTPError as e:
                if e.code != 409:  # 409: a job is already running for it
                    log(f"could not start {b['title']}: HTTP {e.code} {e.read()[:160]!r}")
            except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
                log(f"server unreachable while starting {b['title']} ({e!r}); will retry")
        elif b["status"] == "ready" and not active and b.get("error") and b["id"] not in retried:
            retried.add(b["id"])
            try:
                call("POST", f"/books/{b['id']}/generate", {})
                log(f"retrying failed chapters: {b['title']}")
            except urllib.error.HTTPError as e:
                log(f"retry refused for {b['title']}: HTTP {e.code}")
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                retried.discard(b["id"])
        elif b["status"] == "failed" and b["id"] not in retried:
            retried.add(b["id"])
            log(f"ANALYSIS FAILED: {b['title']}: {(b.get('error') or {}).get('message')}")
    log("status: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    pending = [b for b in lib if b["status"] in ("uploaded", "analyzing", "review", "generating") or b.get("active_job")]
    if not pending:
        log("all books finished")
        break
    time.sleep(20)
