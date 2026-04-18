from __future__ import annotations

from dataclasses import dataclass

import pytest

from jutra.memory import save_turn as st_mod
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


def test_extract_and_save_structured_writes_memories_chronicle_notes(
    monkeypatch: pytest.MonkeyPatch, fake_db: FakeFirestore
) -> None:
    memstore.upsert_user(UserProfile(uid="alex", base_age=15))

    payload = (
        '{"facts": [{"text": "boi sie matury", "topic": "fears"}], '
        '"notes": ["napiety dzien"], '
        '"values": ["uczciwosc"], '
        '"preferences": ["koszykowka"]}'
    )

    def fake_generate(kind, contents, *, config=None):  # type: ignore[no-untyped-def]
        return _FakeResp(text=payload)

    monkeypatch.setattr(st_mod, "generate_with_fallback", fake_generate)

    mid = st_mod.extract_and_save("alex", "jestem zestresowany przed matura")
    assert mid is not None

    mems = memstore.recent_memories("alex", limit=10)
    assert any("matury" in (m.get("text") or "") for m in mems)

    vals = memstore.top_values("alex", limit=5)
    assert "uczciwosc" in vals

    prefs = memstore.list_chronicle("alex", kind="preference", limit=5)
    assert any(p.get("object") == "koszykowka" for p in prefs)

    u = memstore.get_user("alex")
    assert u is not None
    assert any("napiety" in n for n in u.context_notes)


def test_extract_and_save_style_refresh_throttle(
    monkeypatch: pytest.MonkeyPatch, fake_db: FakeFirestore
) -> None:
    memstore.upsert_user(UserProfile(uid="alex", base_age=15))
    calls = {"n": 0}

    def fake_refresh(uid: str) -> None:
        calls["n"] += 1
        assert uid == "alex"
        # Real impl updates style_turn_count; without this, last stays 0 and every
        # extract re-fires the throttle.
        memstore.set_user_style_state(uid, {"stub": True}, memstore.count_user_chat_turns(uid))

    monkeypatch.setattr("jutra.agents.style.refresh_user_style", fake_refresh)

    empty = '{"facts":[], "notes":[], "values":[], "preferences":[]}'

    def fake_generate(kind, contents, *, config=None):  # type: ignore[no-untyped-def]
        return _FakeResp(text=empty)

    monkeypatch.setattr(st_mod, "generate_with_fallback", fake_generate)

    memstore.append_chat_turn("alex", "user", "raz")
    st_mod.extract_and_save("alex", "raz")
    assert calls["n"] == 0

    memstore.append_chat_turn("alex", "user", "dwa")
    st_mod.extract_and_save("alex", "dwa")
    assert calls["n"] == 0

    memstore.append_chat_turn("alex", "user", "trzy")
    st_mod.extract_and_save("alex", "trzy")
    assert calls["n"] == 1

    memstore.append_chat_turn("alex", "user", "cztery")
    st_mod.extract_and_save("alex", "cztery")
    assert calls["n"] == 1

    memstore.append_chat_turn("alex", "user", "piec")
    memstore.append_chat_turn("alex", "user", "szesc")
    st_mod.extract_and_save("alex", "szesc")
    assert calls["n"] == 2
