"""Test configuration.

Every test session runs against a throwaway SQLite database and storage
directory, local-only providers, and a deterministic fake TTS engine, so the
suite is hermetic (no network, no downloaded voices or models).
"""

from __future__ import annotations

import io
import math
import random
import time
import os
import shutil
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
FIXTURES = Path(__file__).parent / "fixtures"

_TMP = Path(tempfile.mkdtemp(prefix="abs-tests-"))
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": f"sqlite:///{(_TMP / 'test.db').as_posix()}",
        "STORAGE_PATH": str(_TMP / "storage"),
        "SECRET_KEY": "test-secret-key-for-signing-tokens-and-media-urls",
        "RATE_LIMIT_ENABLED": "false",
        "RUN_WORKER_IN_PROCESS": "false",
        "TTS_PROVIDER": "fake",
        "TTS_ENABLED_PROVIDERS": "piper",
        "LLM_PROVIDER": "none",
        "EMBEDDING_PROVIDER": "hashing",
        "OCR_PROVIDER": "auto",
        "TTS_MAX_RETRIES": "2",
        "TTS_SEGMENT_CACHE": "true",  # tests exercise the cache regardless of the local .env
        # ...and built-in accounts with open sign-up, whatever the local .env says
        "ALLOW_REGISTRATION": "true",
        "AUTH_PROVIDER": "local",
        "SUPABASE_URL": "",
        "ADMIN_EMAILS": "",
        "AUDIO_DELIVERY": "server",
    }
)

from app.core.errors import ProviderTimeoutError  # noqa: E402
from app.providers.tts.base import SynthesisOptions, SynthesisResult, TTSProvider, VoiceInfo  # noqa: E402


class FakeTTS(TTSProvider):
    """Deterministic engine: a short tone per sentence, with exact sentence timings.

    `fail_on` makes synthesis fail for text containing that marker (to test retries/resume).
    """

    name = "fake"
    display_name = "Fake (tests)"
    is_local = True
    supports_timestamps = True
    max_chunk_chars = 120  # small chunks -> many per chapter
    max_chunk_parallelism = 4  # exercise the parallel synthesis path
    max_chapter_parallelism = 3  # ...and several chapters at once

    def __init__(self) -> None:
        self.calls = 0
        self.fail_on: str | None = None

    def is_available(self):
        return True, None

    def list_voices(self):
        return [
            VoiceInfo(provider="fake", id="fake-en", name="Fake English", language="en", locale="en-US", gender="female"),
            VoiceInfo(provider="fake", id="fake-hi", name="Fake Hindi", language="hi", locale="hi-IN", gender="male"),
        ]

    def synthesize(self, sentences: list[str], options: SynthesisOptions) -> SynthesisResult:
        self.calls += 1
        time.sleep(random.uniform(0, 0.03))  # chunks finish out of order on purpose
        if self.fail_on and any(self.fail_on in s for s in sentences):
            raise ProviderTimeoutError("fake", "The fake TTS engine timed out.")
        rate = 16000
        pcm: list[np.ndarray] = []
        times = []
        t = 0.0
        for s in sentences:
            dur = max(0.2, len(s) * 0.01) / options.speed
            n = int(dur * rate)
            tone = (np.sin(2 * math.pi * 220 * np.arange(n) / rate) * 8000).astype(np.int16)
            pcm.append(tone)
            times.append((t, t + dur))
            t += dur
            gap = np.zeros(int(0.1 * rate), dtype=np.int16)
            pcm.append(gap)
            t += 0.1
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(np.concatenate(pcm).tobytes())
        return SynthesisResult(audio=buf.getvalue(), format="wav", sample_rate=rate, sentence_times=times)


FAKE_TTS = FakeTTS()


@pytest.fixture(scope="session", autouse=True)
def _app_setup():
    from app.db.init import init_db
    from app.providers.tts import _registry

    init_db()
    _registry()["fake"] = FAKE_TTS
    yield
    from app.db.session import reset_engine

    reset_engine()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture
def fake_tts():
    FAKE_TTS.fail_on = None
    yield FAKE_TTS
    FAKE_TTS.fail_on = None


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


_counter = {"n": 0}


@pytest.fixture
def user(client):
    """A freshly registered user; returns (headers, user_json)."""
    _counter["n"] += 1
    r = client.post("/api/auth/register", json={"email": f"user{_counter['n']}-{os.getpid()}@example.com", "password": "correct horse battery", "display_name": "Reader"})
    assert r.status_code == 200, r.text
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}, body["user"]


def run_jobs(max_jobs: int = 20) -> list[str]:
    """Run queued jobs synchronously through the real worker code path."""
    from app.workers import queue
    from app.workers.runner import run_job
    from app.workers.tasks import HANDLERS

    ran = []
    for _ in range(max_jobs):
        job_id = queue.claim_next()
        if job_id is None:
            break
        run_job(job_id, HANDLERS)
        ran.append(job_id)
    return ran


def upload(client, headers, fixture: str = "lantern-at-gull-point.txt", analyze: bool = True) -> dict:
    with open(FIXTURES / fixture, "rb") as fh:
        r = client.post("/api/books", headers=headers, files={"file": (fixture, fh)}, data={"auto_analyze": str(analyze).lower()})
    assert r.status_code == 201, r.text
    if analyze:
        run_jobs()
    return r.json()
