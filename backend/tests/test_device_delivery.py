"""AUDIO_DELIVERY=device: the server converts books but keeps no audio once the
listener's browser has it."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from tests.conftest import run_jobs, upload


@pytest.fixture
def device(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "audio_delivery", "device")
    monkeypatch.setattr(s, "tts_segment_cache", False)
    return s


def _narrate(client, headers, book_id):
    r = client.patch(f"/api/books/{book_id}", headers=headers, json={"narration": {"provider": "fake", "voice_id": "fake-en", "build_full_audiobook": True}})
    assert r.status_code == 200, r.text
    client.post(f"/api/books/{book_id}/generate", headers=headers, json={})
    run_jobs()
    return client.get(f"/api/books/{book_id}/playback", headers=headers).json()


def _stored_audio(book_id):
    from app.models import AudioAsset
    from app.db.session import session_scope
    from app.providers.storage import get_storage

    storage = get_storage()
    with session_scope(write=False) as db:
        assets = list(db.scalars(select(AudioAsset).where(AudioAsset.book_id == book_id)))
        return [a.kind for a in assets if storage.exists(a.storage_key)]


def test_audio_waits_on_the_server_until_the_device_has_it(client, user, fake_tts, device):
    headers, _ = user
    book_id = upload(client, headers)["book"]["id"]
    play = _narrate(client, headers, book_id)
    assert play["audio_delivery"] == "device"
    tracks = play["tracks"]
    assert tracks and all(t["url"] and t["audio_hash"] and not t["on_device"] for t in tracks)
    # No server-side full-book file in device mode: only chapters wait for pickup.
    assert set(_stored_audio(book_id)) == {"chapter"}

    first = tracks[0]
    audio = client.get(first["url"])
    assert audio.status_code == 200 and len(audio.content) > 100
    r = client.post(f"/api/books/{book_id}/chapters/{first['chapter_id']}/audio/received", headers=headers, json={"audio_hash": first["audio_hash"]})
    assert r.status_code == 200 and r.json() == {"on_device": True}
    # Saying it twice is harmless.
    assert client.post(f"/api/books/{book_id}/chapters/{first['chapter_id']}/audio/received", headers=headers, json={"audio_hash": first["audio_hash"]}).status_code == 200

    after = client.get(f"/api/books/{book_id}/playback", headers=headers).json()["tracks"]
    t0 = next(t for t in after if t["chapter_id"] == first["chapter_id"])
    assert t0["on_device"] is True and t0["url"] is None
    assert t0["duration"] == first["duration"]  # player metadata survives
    assert client.get(first["url"]).status_code == 404  # the file itself is gone

    # Deliver the rest: nothing audible is left on the server.
    for t in after:
        if not t["on_device"]:
            client.post(f"/api/books/{book_id}/chapters/{t['chapter_id']}/audio/received", headers=headers, json={"audio_hash": t["audio_hash"]})
    assert _stored_audio(book_id) == []

    # Generating again doesn't re-narrate chapters the device already holds.
    calls = fake_tts.calls
    client.post(f"/api/books/{book_id}/generate", headers=headers, json={})
    run_jobs()
    assert fake_tts.calls == calls


def test_stale_hash_is_refused(client, user, fake_tts, device):
    headers, _ = user
    book_id = upload(client, headers)["book"]["id"]
    t = _narrate(client, headers, book_id)["tracks"][0]
    r = client.post(f"/api/books/{book_id}/chapters/{t['chapter_id']}/audio/received", headers=headers, json={"audio_hash": "0" * 64})
    assert r.status_code == 409 and r.json()["error"]["code"] == "audio_changed"
    assert "chapter" in _stored_audio(book_id)


def test_other_users_cannot_confirm(client, user, fake_tts, device):
    headers, _ = user
    book_id = upload(client, headers)["book"]["id"]
    t = _narrate(client, headers, book_id)["tracks"][0]
    other = client.post("/api/auth/register", json={"email": "thief@example.com", "password": "another password", "display_name": "T"}).json()
    r = client.post(
        f"/api/books/{book_id}/chapters/{t['chapter_id']}/audio/received",
        headers={"Authorization": f"Bearer {other['token']}"},
        json={"audio_hash": t["audio_hash"]},
    )
    assert r.status_code in (403, 404)


def test_uncollected_audio_is_swept(client, user, fake_tts, device):
    from app.db.base import utcnow
    from app.db.session import session_scope
    from app.models import AudioAsset
    from app.services.handoff import sweep_undelivered

    headers, _ = user
    book_id = upload(client, headers)["book"]["id"]
    tracks = _narrate(client, headers, book_id)["tracks"]
    keep = tracks[0]
    client.post(f"/api/books/{book_id}/chapters/{keep['chapter_id']}/audio/received", headers=headers, json={"audio_hash": keep["audio_hash"]})
    with session_scope() as db:
        for a in db.scalars(select(AudioAsset).where(AudioAsset.book_id == book_id)):
            a.created_at = utcnow() - timedelta(hours=device.device_handoff_ttl_hours + 1)
    with session_scope() as db:
        assert sweep_undelivered(db) == len(tracks) - 1
    assert _stored_audio(book_id) == []
    chapters = {c["id"]: c["audio_status"] for c in client.get(f"/api/books/{book_id}/chapters", headers=headers).json()["items"]}
    assert chapters[keep["chapter_id"]] == "done"  # delivered ones stay listenable on the device
    assert sum(1 for t in tracks[1:] if chapters[t["chapter_id"]] == "pending") == len(tracks) - 1


def test_server_mode_is_unchanged(client, user, fake_tts):
    headers, _ = user
    book_id = upload(client, headers)["book"]["id"]
    play = _narrate(client, headers, book_id)
    assert play["audio_delivery"] == "server"
    t = play["tracks"][0]
    assert client.post(f"/api/books/{book_id}/chapters/{t['chapter_id']}/audio/received", headers=headers, json={"audio_hash": t["audio_hash"]}).json() == {"on_device": False}
    assert client.get(t["url"]).status_code == 200


def test_downloads_offer_no_server_audiobook_builds(client, user, fake_tts, device):
    headers, _ = user
    book_id = upload(client, headers)["book"]["id"]
    _narrate(client, headers, book_id)
    kinds = {i["kind"] for i in client.get(f"/api/books/{book_id}/downloads", headers=headers).json()["items"]}
    assert "full" not in kinds and "m4b" not in kinds


def test_sweep_spares_audio_made_before_device_mode(client, user, fake_tts, monkeypatch):
    """Switching an existing library to device mode must not wipe its audio."""
    from app.db.base import utcnow
    from app.db.session import session_scope
    from app.models import AudioAsset
    from app.services.handoff import sweep_undelivered

    headers, _ = user
    book_id = upload(client, headers)["book"]["id"]
    _narrate(client, headers, book_id)  # server mode: no hand-off tag
    s = get_settings()
    monkeypatch.setattr(s, "audio_delivery", "device")
    with session_scope() as db:
        for a in db.scalars(select(AudioAsset).where(AudioAsset.book_id == book_id)):
            a.created_at = utcnow() - timedelta(days=30)
    with session_scope() as db:
        assert sweep_undelivered(db) == 0
    assert "chapter" in _stored_audio(book_id)


def test_swept_book_is_no_longer_ready(client, user, fake_tts, device):
    from app.db.base import utcnow
    from app.db.session import session_scope
    from app.models import AudioAsset
    from app.services.handoff import sweep_undelivered

    headers, _ = user
    book_id = upload(client, headers)["book"]["id"]
    _narrate(client, headers, book_id)
    assert client.get(f"/api/books/{book_id}", headers=headers).json()["status"] == "ready"
    with session_scope() as db:
        for a in db.scalars(select(AudioAsset).where(AudioAsset.book_id == book_id)):
            a.created_at = utcnow() - timedelta(hours=device.device_handoff_ttl_hours + 1)
    with session_scope() as db:
        sweep_undelivered(db)
    assert client.get(f"/api/books/{book_id}", headers=headers).json()["status"] == "review"
