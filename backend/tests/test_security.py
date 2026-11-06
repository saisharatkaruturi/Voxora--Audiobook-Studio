import time

import pytest

from app.core.errors import AuthError, UnsupportedFileError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    safe_filename,
    sign_media_path,
    verify_media_signature,
    verify_password,
)
from app.document_processing.detect import sniff
from app.providers.storage.base import validate_key


def test_password_hashing_roundtrip():
    h = hash_password("correct horse battery")
    assert h != "correct horse battery"
    assert verify_password("correct horse battery", h)
    assert not verify_password("wrong", h)


def test_access_tokens_verify_and_reject_tampering():
    token = create_access_token("user-1")
    assert decode_access_token(token) == "user-1"
    with pytest.raises(AuthError):
        decode_access_token(token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1])
    with pytest.raises(AuthError):
        decode_access_token(create_access_token("user-1", ttl_minutes=-1))


def test_signed_media_urls_expire_and_bind_to_path():
    url = sign_media_path("/media/books/x/audio/01.mp3", 60)
    params = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))
    exp, sig = int(params["exp"]), params["sig"]
    assert verify_media_signature("/media/books/x/audio/01.mp3", exp, sig)
    assert not verify_media_signature("/media/books/y/audio/01.mp3", exp, sig)
    assert not verify_media_signature("/media/books/x/audio/01.mp3", int(time.time()) - 5, sig)


@pytest.mark.parametrize("name", ["../../etc/passwd", "..\\..\\windows\\system32", "CON", "a/b/c.pdf", "\x00evil.pdf"])
def test_filenames_are_never_trusted(name):
    safe = safe_filename(name)
    assert "/" not in safe and "\\" not in safe and ".." not in safe and "\x00" not in safe
    assert safe


@pytest.mark.parametrize("key", ["../secret", "books/../../x", "/abs/path", "C:/windows", "books\\x"])
def test_storage_keys_block_path_traversal(key):
    with pytest.raises(ValueError):
        validate_key(key)


def test_uploads_are_identified_by_content_not_name(tmp_path):
    exe = tmp_path / "book.pdf"
    exe.write_bytes(b"MZ\x90\x00" + b"\x00" * 100)
    with pytest.raises(UnsupportedFileError):
        sniff(exe, "book.pdf")
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    with pytest.raises(UnsupportedFileError):
        sniff(empty, "empty.txt")
    fake_pdf = tmp_path / "notes.pdf"
    fake_pdf.write_text("just some plain text pretending", encoding="utf-8")
    with pytest.raises(UnsupportedFileError):  # named .pdf, but it's plain text
        sniff(fake_pdf, "notes.pdf")
