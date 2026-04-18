"""Tests for identity-adaptation upgrade (prompt helpers, chronicle dynamics, session)."""

from __future__ import annotations

import pytest

from jutra.agents import future_self as fs_mod
from jutra.memory import store as memstore
from jutra.memory.models import ChronicleTriple, UserProfile
from jutra.services.session_close import cold_open_line, close_session_and_summarize
from tests._fakestore import FakeFirestore


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> FakeFirestore:
    db = FakeFirestore()
    monkeypatch.setattr(memstore, "firestore_client", lambda: db)
    return db


def test_horizon_line_far_and_near() -> None:
    assert "odleg" in fs_mod._horizon_line("jaki jest sens życia?")
    assert "blisk" in fs_mod._horizon_line("jutro mam klasówkę")


def test_banned_openers_from_turns() -> None:
    turns = [
        {"role": "assistant", "text": "Rozumiem twoją sytuację całkiem dobrze"},
        {"role": "user", "text": "ok"},
        {"role": "assistant", "text": "Jasne, możemy tak zrobić"},
    ]
    op = fs_mod._banned_openers_from_turns(turns)
    assert "Rozumiem twoją" in op[-1] or any("Rozumiem" in x for x in op)


def test_chronicle_reinforcement_boosts_weight(fake_db: FakeFirestore) -> None:
    memstore.upsert_user(UserProfile(uid="u1", base_age=15))
    t = ChronicleTriple("u1", "ceni", "wolnosc", kind="value", weight=0.7)
    memstore.add_chronicle("u1", t)
    memstore.add_chronicle("u1", t)
    rows = memstore.list_chronicle("u1", kind="value", limit=5)
    assert len(rows) == 1
    assert float(rows[0].get("weight", 0)) > 0.7


def test_revoke_chronicle_marks_disputed(fake_db: FakeFirestore) -> None:
    memstore.upsert_user(UserProfile(uid="u2", base_age=15))
    memstore.add_chronicle(
        "u2",
        ChronicleTriple("u2", "ceni", "test", kind="value", weight=0.4),
    )
    ok = memstore.revoke_chronicle("u2", "value", "test")
    assert ok
    rows = memstore.list_disputed_chronicle("u2")
    assert rows


def test_cold_open_prefers_arc(fake_db: FakeFirestore) -> None:
    memstore.upsert_user(UserProfile(uid="u3", base_age=15))
    memstore.add_chronicle(
        "u3",
        ChronicleTriple("u3", "w_sesji", "Było o sporcie.", kind="arc", weight=1.0, source="session"),
    )
    line = cold_open_line("u3")
    assert "sport" in line.lower() or "rozmow" in line.lower()


def test_close_session_summarize_writes_arc(monkeypatch: pytest.MonkeyPatch, fake_db: FakeFirestore) -> None:
    memstore.upsert_user(UserProfile(uid="u4", base_age=15))
    memstore.append_chat_turn("u4", "user", "Chcę zacząć biegać")
    memstore.append_chat_turn("u4", "assistant", "Super, zacznij od krótkich dystansów.")

    class _R:
        text = '{"arc_summary": "Dziś mówiłeś o bieganiu.", "commitments": []}'

    monkeypatch.setattr("jutra.services.session_close.generate_with_fallback", lambda *a, **k: _R())
    out = close_session_and_summarize("u4")
    assert out.get("ok") is True
    arcs = memstore.list_recent_arcs("u4", limit=2)
    assert arcs
