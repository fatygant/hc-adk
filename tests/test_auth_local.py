from __future__ import annotations

import pytest

from jutra.services.auth_local import (
    create_access_token,
    decode_access_token,
    hash_password,
    is_valid_email,
    new_uid,
    normalize_email,
    verify_password,
)


def test_normalize_email() -> None:
    assert normalize_email("  Test@Example.COM ") == "test@example.com"


def test_is_valid_email() -> None:
    assert is_valid_email("a@b.co")
    assert not is_valid_email("not-an-email")
    assert not is_valid_email("")


def test_password_hash_roundtrip() -> None:
    h = hash_password("secretpass12")
    assert verify_password("secret12", h) is False
    assert verify_password("secretpass12", h) is True


def test_jwt_roundtrip() -> None:
    secret = "test-secret-at-least-32-chars-long!!"
    uid = new_uid()
    tok = create_access_token(uid=uid, email="u@example.com", secret=secret)
    payload = decode_access_token(tok, secret)
    assert payload["sub"] == uid
    assert payload["email"] == "u@example.com"


def test_jwt_wrong_secret() -> None:
    tok = create_access_token(uid="u1", email="a@b.c", secret="a" * 32)
    with pytest.raises(Exception):
        decode_access_token(tok, "b" * 32)
