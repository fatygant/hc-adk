from __future__ import annotations

from dataclasses import dataclass

import pytest

from jutra.agents import style as style_mod
from jutra.memory import store as memstore
from jutra.memory.models import UserProfile
from tests._fakestore import FakeFirestore


@dataclass
class _FakeResp:
    text: str


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> FakeFirestore:
    db = FakeFirestore()
    monkeypatch.setattr(memstore, "firestore_client", lambda: db)
    return db


def test_refresh_user_style_persists_profile(
    monkeypatch: pytest.MonkeyPatch, fake_db: FakeFirestore
) -> None:
    memstore.upsert_user(UserProfile(uid="alex", base_age=15))
    for i in range(3):
        memstore.append_chat_turn("alex", "user", f"wiadomosc {i}")

    payload = (
        '{"formality":"casual","tone":"zartobliwy","sentence_length":"short",'
        '"typical_openers":["no wiesz"],"fillers":["no"],"signature_phrases":[],'
        '"vocabulary_notes":"slang","emoji_usage":"none","examples":["cytat"],'
        '"updated_at":""}'
    )

    def fake_generate(kind, contents, *, config=None):  # type: ignore[no-untyped-def]
        assert "wiadomosc" in contents
        return _FakeResp(text=payload)

    monkeypatch.setattr(style_mod, "generate_with_fallback", fake_generate)

    out = style_mod.refresh_user_style("alex")
    assert out is not None
    assert out.get("formality") == "casual"
    assert out.get("updated_at")

    u = memstore.get_user("alex")
    assert u is not None
    assert u.style_profile.get("formality") == "casual"
    assert u.style_turn_count == 3


def test_refresh_user_style_skips_when_few_turns(fake_db: FakeFirestore) -> None:
    memstore.upsert_user(UserProfile(uid="alex", base_age=15))
    memstore.append_chat_turn("alex", "user", "jedna")
    assert style_mod.refresh_user_style("alex") is None
