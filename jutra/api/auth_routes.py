"""Email/password registration and login (Firestore + JWT).

Rate limiting and password reset are out of scope for this minimal build.
"""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from jutra.infra.firestore import firestore_client
from jutra.memory import store as memstore
from jutra.memory.models import UserProfile
from jutra.personas.ocean import Ocean
from jutra.services.auth_local import (
    create_access_token,
    hash_password,
    is_valid_email,
    new_uid,
    normalize_email,
    verify_password,
)
from jutra.settings import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])

_EMAIL_ACCOUNTS = "email_accounts"


def _account_doc_id(email: str) -> str:
    return hashlib.sha256(normalize_email(email).encode()).hexdigest()


class AuthBody(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=8, max_length=128)


def _require_jwt_secret() -> str:
    s = (get_settings().auth_jwt_secret or "").strip()
    if not s:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth is not configured (AUTH_JWT_SECRET empty)",
        )
    return s


@router.post("/register")
def register(body: AuthBody) -> dict:
    secret = _require_jwt_secret()
    email = normalize_email(body.email)
    if not is_valid_email(email):
        raise HTTPException(status_code=400, detail="Invalid email")

    db = firestore_client()
    ref = db.collection(_EMAIL_ACCOUNTS).document(_account_doc_id(email))
    if ref.get().exists:
        raise HTTPException(status_code=409, detail="Account already exists")

    uid = new_uid()
    pwd_hash = hash_password(body.password)

    ref.set(
        {
            "email": email,
            "uid": uid,
            "password_hash": pwd_hash,
        }
    )

    memstore.upsert_user(
        UserProfile(
            uid=uid,
            display_name="Ty",
            base_age=15,
            ocean_t=Ocean().as_dict(),
        )
    )

    token = create_access_token(uid=uid, email=email, secret=secret)
    return {"uid": uid, "access_token": token, "email": email}


@router.post("/login")
def login(body: AuthBody) -> dict:
    secret = _require_jwt_secret()
    email = normalize_email(body.email)
    if not is_valid_email(email):
        raise HTTPException(status_code=400, detail="Invalid email")

    db = firestore_client()
    snap = db.collection(_EMAIL_ACCOUNTS).document(_account_doc_id(email)).get()
    if not snap.exists:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    data = snap.to_dict() or {}
    pwd_hash = str(data.get("password_hash", ""))
    uid = str(data.get("uid", ""))
    if not uid or not verify_password(body.password, pwd_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(uid=uid, email=email, secret=secret)
    return {"uid": uid, "access_token": token, "email": email}
