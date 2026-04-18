"""Streaming chat path (voice) tests.

Covers:
  - `future_self_reply_stream` forces fast voice config and relays deltas.
  - `chat_with_future_self_stream` short-circuits on crisis without calling
    the LLM and yields (meta, delta, done).
  - Happy path emits meta -> delta* -> done with accumulated response.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from jutra.agents import future_self as fs_mod
from jutra.memory import store as memstore
from jutra.memory.models import UserProfile
from jutra.safety import crisis as crisis_mod
from jutra.services import chat as chat_mod
from tests._fakestore import FakeFirestore


@dataclass
class _FakeVerdict:
    is_crisis: bool
    severity: int = 0
    reason: str = ""
    resources: tuple[str, ...] = ()


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> FakeFirestore:
    db = FakeFirestore()
    monkeypatch.setattr(memstore, "firestore_client", lambda: db)
    return db


async def _collect(aiter):
    out = []
    async for item in aiter:
        out.append(item)
    return out


async def test_future_self_reply_stream_uses_fast_voice_config(
    monkeypatch: pytest.MonkeyPatch, fake_db: FakeFirestore
) -> None:
    captured: dict = {}

    async def fake_stream(kind, contents, *, config=None):
        captured["kind"] = kind
        captured["msg"] = contents
        captured["config"] = config
        for chunk in ["Cze", "ść", ", ", "mówi", " twoje ja."]:
            yield chunk

    memstore.upsert_user(UserProfile(uid="alex", base_age=15))
    monkeypatch.setattr(fs_mod, "generate_stream_with_fallback", fake_stream)

    chunks = await _collect(fs_mod.future_self_reply_stream("alex", "hej"))
    assert "".join(chunks) == "Cześć, mówi twoje ja."
    # Voice path always pins the flash ("chat") model.
    assert captured["kind"] == "chat"
    cfg = captured["config"]
    assert cfg.thinking_config.thinking_budget == 0
    assert cfg.max_output_tokens == 400


async def test_chat_stream_crisis_short_circuits_without_llm(
    monkeypatch: pytest.MonkeyPatch, fake_db: FakeFirestore
) -> None:
    memstore.upsert_user(UserProfile(uid="alex", base_age=15))

    called = {"stream": 0}

    async def fake_stream(*_a, **_kw):
        called["stream"] += 1
        yield "should not happen"

    monkeypatch.setattr(chat_mod, "future_self_reply_stream", fake_stream)
    monkeypatch.setattr(
        chat_mod,
        "detect_crisis",
        lambda *_a, **_kw: _FakeVerdict(is_crisis=True, severity=3, resources=("116 111", "112")),
    )
    monkeypatch.setattr(chat_mod, "crisis_reply", lambda: "Zadzwoń teraz.")

    events = await _collect(chat_mod.chat_with_future_self_stream("alex", "nie chcę żyć"))

    kinds = [e["event"] for e in events]
    assert kinds == ["meta", "delta", "done"]
    assert events[0]["data"]["crisis"] is True
    assert "116 111" in events[1]["data"]["text"]
    assert "Zadzwoń" in events[2]["data"]["response"]
    assert called["stream"] == 0


async def test_chat_stream_happy_path_emits_meta_delta_done(
    monkeypatch: pytest.MonkeyPatch, fake_db: FakeFirestore
) -> None:
    memstore.upsert_user(UserProfile(uid="alex", base_age=15))

    async def fake_stream(*_a, **_kw):
        for c in ["Cze", "ść", "."]:
            yield c

    monkeypatch.setattr(chat_mod, "future_self_reply_stream", fake_stream)
    monkeypatch.setattr(chat_mod, "detect_crisis", lambda *_a, **_kw: _FakeVerdict(is_crisis=False))
    # No posts stored -> no embedding call.
    monkeypatch.setattr(memstore, "count_posts", lambda _uid: 0)
    # Memory extraction is best-effort; stub it out to avoid Vertex calls.
    monkeypatch.setattr(chat_mod, "extract_and_save", lambda *a, **kw: None)

    events = await _collect(chat_mod.chat_with_future_self_stream("alex", "hej"))

    kinds = [e["event"] for e in events]
    assert kinds[0] == "meta"
    assert kinds[-1] == "done"
    assert kinds.count("delta") == 3
    deltas = [e["data"]["text"] for e in events if e["event"] == "delta"]
    assert "".join(deltas) == "Cześć."
    done = events[-1]["data"]
    assert done["response"] == "Cześć."


def test_crisis_module_still_imports() -> None:
    # Sanity: the crisis module exports are stable so chat.py imports don't drift.
    assert hasattr(crisis_mod, "detect_crisis")
    assert hasattr(crisis_mod, "crisis_reply")
