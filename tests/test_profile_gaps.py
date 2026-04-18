from __future__ import annotations

import pytest

from jutra.memory import store as memstore
from jutra.memory.models import ChronicleTriple, MemoryItem, UserProfile
from jutra.services.profile_gaps import profile_gaps
from tests._fakestore import FakeFirestore


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> FakeFirestore:
    db = FakeFirestore()
    monkeypatch.setattr(memstore, "firestore_client", lambda: db)
    return db


def test_profile_gaps_new_user_lists_core_slots(fake_db: FakeFirestore) -> None:
    gaps = profile_gaps("nobody")
    joined = " ".join(gaps)
    assert "wartości" in joined
    assert "preferencje" in joined
    assert "lęki" in joined or "obawy" in joined


def test_profile_gaps_shrinks_when_data_present(fake_db: FakeFirestore) -> None:
    memstore.upsert_user(
        UserProfile(uid="alex", base_age=16, riasec_top3=["I", "A", "S"]),
    )
    memstore.add_chronicle(
        "alex",
        ChronicleTriple("alex", "ceni", "wolnosc", kind="value", weight=0.9),
    )
    memstore.add_chronicle(
        "alex",
        ChronicleTriple("alex", "lubi", "gitara", kind="preference", weight=0.7),
    )
    for topic in ("fears", "plans", "relations", "hobby", "school", "career"):
        memstore.add_memory("alex", MemoryItem(text=f"x {topic}", topic=topic))

    gaps = profile_gaps("alex")
    joined = " ".join(gaps).lower()
    assert "wartości" not in joined
    assert "preferencje" not in joined
    assert "riasec" not in joined
    assert "lęki" not in joined
