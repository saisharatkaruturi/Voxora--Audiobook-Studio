"""Supabase Auth: tokens are verified (HS256 secret or JWKS keys) and mapped to VOXORA users."""

from __future__ import annotations

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.config import get_settings

SUPABASE_URL = "https://testproject.supabase.co"
SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"


@pytest.fixture
def supabase(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "auth_provider", "supabase")
    monkeypatch.setattr(s, "supabase_url", SUPABASE_URL)
    monkeypatch.setattr(s, "supabase_anon_key", "public-anon-key")
    monkeypatch.setattr(s, "supabase_jwt_secret", SECRET)
    monkeypatch.setattr(s, "admin_emails", ["boss@example.com"])
    monkeypatch.setattr(s, "allow_registration", True)
    return s


def token(email: str | None = None, *, sub: str | None = None, verified: bool = True, key=SECRET, alg="HS256", headers=None, **overrides) -> str:
    claims = {
        "sub": sub or str(uuid.uuid4()),
        "aud": "authenticated",
        "iss": f"{SUPABASE_URL}/auth/v1",
        "role": "authenticated",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
        "email": email or f"{uuid.uuid4().hex[:8]}@example.com",
        "user_metadata": {"email_verified": verified, "full_name": "Asha Reader"},
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm=alg, headers=headers)


def bearer(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


def test_config_tells_the_browser_where_to_sign_in(client, supabase):
    cfg = client.get("/api/auth/config").json()
    assert cfg["provider"] == "supabase"
    assert cfg["supabase_url"] == SUPABASE_URL and cfg["supabase_anon_key"] == "public-anon-key"
    assert cfg["oauth_providers"] == ["google"]


def test_first_request_provisions_the_user(client, supabase):
    t = token("new.reader@example.com")
    me = client.get("/api/auth/me", headers=bearer(t))
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "new.reader@example.com"
    assert me.json()["display_name"] == "Asha Reader"
    assert me.json()["is_admin"] is False
    # Same subject again -> same account, not a duplicate.
    assert client.get("/api/auth/me", headers=bearer(t)).json()["id"] == me.json()["id"]
    assert client.get("/api/books", headers=bearer(t)).status_code == 200


def test_admin_comes_from_admin_emails_not_signup_order(client, supabase):
    assert client.get("/api/auth/me", headers=bearer(token("Boss@Example.com"))).json()["is_admin"] is True


@pytest.mark.parametrize(
    "bad",
    [
        lambda: token(key="wrong-secret-wrong-secret-wrong-secret-xx"),
        lambda: token(exp=int(time.time()) - 3600),
        lambda: token(aud="someone-else"),
        lambda: token(iss="https://evil.supabase.co/auth/v1"),
        lambda: token(role="anon"),
        lambda: token(is_anonymous=True),
        lambda: "not-a-jwt",
    ],
)
def test_rejects_bad_tokens(client, supabase, bad):
    r = client.get("/api/auth/me", headers=bearer(bad()))
    assert r.status_code == 401, r.text


def test_local_login_and_register_are_off(client, supabase):
    r = client.post("/api/auth/login", json={"email": "a@example.com", "password": "whatever-password"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "use_supabase"
    r = client.post("/api/auth/register", json={"email": "a@example.com", "password": "whatever-password", "display_name": "A"})
    assert r.status_code == 403


def test_existing_account_is_linked_only_after_email_is_confirmed(client, user, supabase):
    headers, me = user  # created with the built-in accounts
    unverified = client.get("/api/auth/me", headers=bearer(token(me["email"], verified=False)))
    assert unverified.status_code == 403 and unverified.json()["error"]["code"] == "email_unverified"
    linked = client.get("/api/auth/me", headers=bearer(token(me["email"])))
    assert linked.status_code == 200 and linked.json()["id"] == me["id"]
    # A second Supabase identity can't take over the same library.
    other = client.get("/api/auth/me", headers=bearer(token(me["email"])))
    assert other.status_code == 403 and other.json()["error"]["code"] == "account_conflict"


def test_closed_registration_still_admits_admins(client, supabase, monkeypatch):
    monkeypatch.setattr(supabase, "allow_registration", False)
    monkeypatch.setattr(supabase, "admin_emails", ["owner@example.com"])
    assert client.get("/api/auth/me", headers=bearer(token("stranger@example.com"))).status_code == 403
    r = client.get("/api/auth/me", headers=bearer(token("owner@example.com")))
    assert r.status_code == 200 and r.json()["is_admin"] is True


def test_password_changes_go_through_supabase(client, supabase):
    r = client.patch("/api/auth/me", headers=bearer(token()), json={"current_password": "x" * 8, "new_password": "y" * 8})
    assert r.status_code == 422 and r.json()["error"]["code"] == "use_supabase"


def test_asymmetric_keys_via_jwks(client, supabase, monkeypatch):
    from app.services import auth

    private = ec.generate_private_key(ec.SECP256R1())

    class FakeJWKS:
        def get_signing_key_from_jwt(self, _token):
            return type("Key", (), {"key": private.public_key()})()

    monkeypatch.setattr(auth, "_jwks", lambda: FakeJWKS())
    t = token("es256@example.com", key=private, alg="ES256", headers={"kid": "test-key"})
    assert client.get("/api/auth/me", headers=bearer(t)).json()["email"] == "es256@example.com"
    # A token signed by some other key is refused.
    stranger = ec.generate_private_key(ec.SECP256R1())
    forged = token("es256@example.com", key=stranger, alg="ES256", headers={"kid": "test-key"})
    assert client.get("/api/auth/me", headers=bearer(forged)).status_code == 401


def test_websocket_accepts_supabase_tokens(client, supabase):
    t = token()
    with client.websocket_connect(f"/ws/jobs/{uuid.uuid4()}?token={t}") as ws:
        assert ws.receive_json() == {"type": "error", "message": "Not found"}  # authenticated, job just doesn't exist
    with client.websocket_connect(f"/ws/jobs/{uuid.uuid4()}?token=garbage") as ws:
        assert ws.receive_json()["message"] == "Unauthorized"


def test_supabase_outage_is_not_a_sign_out(client, supabase, monkeypatch):
    from app.services import auth

    class DownJWKS:
        def get_signing_key_from_jwt(self, _token):
            raise jwt.PyJWKClientConnectionError("connection refused")

    monkeypatch.setattr(auth, "_jwks", lambda: DownJWKS())
    private = ec.generate_private_key(ec.SECP256R1())
    r = client.get("/api/auth/me", headers=bearer(token(key=private, alg="ES256", headers={"kid": "k"})))
    assert r.status_code == 503 and r.json()["error"]["retryable"] is True
