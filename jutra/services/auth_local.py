"""Local email/password auth: bcrypt + HS256 JWT (no external IdP)."""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(normalize_email(email)))


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def new_uid() -> str:
    """Alphanumeric uid similar length to previous nanoid(10)."""
    return secrets.token_urlsafe(8)[:10].replace("-", "x")


def create_access_token(*, uid: str, email: str, secret: str, expires_days: int = 7) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": uid,
        "email": email,
        "iat": now,
        "exp": now + timedelta(days=expires_days),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, secret: str) -> dict:
    return jwt.decode(token, secret, algorithms=["HS256"])
