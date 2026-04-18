from __future__ import annotations

from dataclasses import dataclass

import pytest

from jutra.agents import extraction as extr_mod
from jutra.agents import future_self as fs_mod
from jutra.agents import onboarding as ob_mod
from jutra.memory import store as memstore
from jutra.memory.models import ChronicleTriple, UserProfile
from jutra.personas.horizons import SUPPORTED_HORIZONS
from tests._fakestore import FakeFirestore


@dataclass
class _FakeResp:
    text: str


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> FakeFirestore:
    db = FakeFirestore()
    monkeypatch.setattr(memstore, "firestore_client", lambda: db)
    return db


# --- future_self ----------------------------------------------------------


def test_build_persona_snapshot_returns_shifted_ocean_for_each_horizon(
    fake_db: FakeFirestore,
) -> None:
    memstore.upsert_user(
        UserProfile(
            uid="alex",
            base_age=15,
            ocean_t={"O": 55, "C": 48, "E": 55, "A": 50, "N": 55},
            riasec_top3=["I", "A"],
        )
    )
    memstore.add_chronicle(
        "alex",
        ChronicleTriple("alex", "ceni", "wolnosc", kind="value", weight=0.9),
    )
    memstore.add_chronicle(
        "alex",
        ChronicleTriple("alex", "ceni", "przyjazn", kind="value", weight=0.7),
    )

    snaps = {h: fs_mod.build_persona_snapshot("alex", h) for h in SUPPORTED_HORIZONS}
    c_scores = {h: snaps[h].profile.ocean.C for h in SUPPORTED_HORIZONS}
    # All four horizons must have distinct C scores (the loudest drifting trait).
    assert len(set(c_scores.values())) == len(SUPPORTED_HORIZONS)
    # Values should be present and ordered by weight.
    assert snaps[10].top_values[:2] == ["wolnosc", "przyjazn"]


def test_future_self_reply_passes_system_prompt_and_returns_text(
    monkeypatch: pytest.MonkeyPatch, fake_db: FakeFirestore
) -> None:
    captured = {}

    def fake_generate(kind, contents, *, config=None):  # type: ignore[no-untyped-def]
        captured["kind"] = kind
        captured["system"] = config.system_instruction if config else ""
        captured["msg"] = contents
        return _FakeResp(text="Czesc, mowi twoje przyszle ja.")

    memstore.upsert_user(
        UserProfile(uid="alex", base_age=15, ocean_t={"O": 55, "C": 48, "E": 55, "A": 50, "N": 55})
    )
    monkeypatch.setattr(fs_mod, "generate_with_fallback", fake_generate)

    out = fs_mod.future_self_reply("alex", 30, "czy warto uczyc sie kodowania?")
    assert "przyszle ja" in out
    assert captured["kind"] == "reasoning"  # horizon 30 -> reasoning model
    assert (
        "horyzont" in captured["system"].lower()
        or "horizon" in captured["system"].lower()
        or "lat" in captured["system"].lower()
    )
    # horizon 5 uses chat model
    captured.clear()
    fs_mod.future_self_reply("alex", 5, "a za 5 lat?")
    assert captured["kind"] == "chat"


# --- extraction -----------------------------------------------------------


def test_extract_identity_parses_llm_json(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = (
        '{"values":[{"object":"wolnosc","weight":0.9}],'
        '"preferences":[{"object":"lubie jazz","weight":0.6}],'
        '"facts":[{"predicate":"uczy sie","object":"programowania","weight":0.8}],'
        '"fears":["bojaz porazki"]}'
    )
    monkeypatch.setattr(
        extr_mod, "generate_with_fallback", lambda *a, **kw: _FakeResp(text=payload)
    )
    r = extr_mod.extract_identity(
        "cenie wolnosc, lubie jazz, ucze sie programowania, boje sie porazki"
    )
    assert r.values == [{"object": "wolnosc", "weight": 0.9}]
    assert r.preferences[0]["object"] == "lubie jazz"
    assert r.facts[0]["object"] == "programowania"
    assert r.fears == ["bojaz porazki"]


def test_extract_identity_handles_bad_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        extr_mod, "generate_with_fallback", lambda *a, **kw: _FakeResp(text="not json")
    )
    r = extr_mod.extract_identity("hmm")
    assert r.values == [] and r.preferences == [] and r.facts == [] and r.fears == []


# --- onboarding -----------------------------------------------------------


def test_onboarding_end_to_end(monkeypatch: pytest.MonkeyPatch, fake_db: FakeFirestore) -> None:
    ob_mod._SESSIONS.clear()
    memstore.upsert_user(UserProfile(uid="alex", base_age=15))

    turn1 = _FakeResp(
        text=(
            '{"acknowledgment":"Slysze.",'
            '"question":"Co lubisz robic tak, ze tracisz poczucie czasu?",'
            '"extracted_values":["wolnosc","przyjazn","wiedza"],'
            '"extracted_preferences":[],"extracted_fears":[],'
            '"riasec_signals":["I"],"progress":0.3,"completed":false}'
        )
    )
    turn2 = _FakeResp(
        text=(
            '{"acknowledgment":"Fajnie.",'
            '"question":"A czego sie boisz?",'
            '"extracted_values":[],'
            '"extracted_preferences":["lubie programowac","lubie muzyke","lubie biegac"],'
            '"extracted_fears":[],"riasec_signals":["R"],"progress":0.7,"completed":false}'
        )
    )
    turn3 = _FakeResp(
        text=(
            '{"acknowledgment":"Rozumiem.",'
            '"question":null,"extracted_values":[],'
            '"extracted_preferences":[],"extracted_fears":["porazka"],'
            '"riasec_signals":[],"progress":1.0,"completed":true}'
        )
    )
    responses = iter([turn1, turn2, turn3])
    monkeypatch.setattr(ob_mod, "generate_with_fallback", lambda *a, **kw: next(responses))

    sid, q = ob_mod.start_onboarding("alex")
    assert q and isinstance(q, str)

    r1 = ob_mod.onboarding_turn(sid, "cenie wolnosc, przyjazn i wiedze")
    assert not r1["completed"]
    assert "wolnosc" in r1["extracted"]["values"]

    r2 = ob_mod.onboarding_turn(sid, "lubie programowac, muzyke, biegac")
    assert "lubie programowac" in r2["extracted"]["preferences"]

    r3 = ob_mod.onboarding_turn(sid, "boje sie porazki")
    assert r3["completed"] is True
    # Chronicle should now hold at least the 3 values + 3 preferences.
    values = memstore.list_chronicle("alex", kind="value")
    prefs = memstore.list_chronicle("alex", kind="preference")
    assert len(values) >= 3
    assert len(prefs) >= 3
    # Fear stored as memory
    mems = memstore.recent_memories("alex", limit=5)
    assert any(m.get("topic") == "fears" for m in mems)
    # RIASEC updated
    user = memstore.get_user("alex")
    assert user is not None
    assert set(user.riasec_top3) & {"I", "R"}
