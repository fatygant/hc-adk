from __future__ import annotations

import pytest

from jutra.memory import store as memstore
from jutra.memory.models import ChronicleTriple, MemoryItem, SocialPost, UserProfile
from tests._fakestore import FakeFirestore


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> FakeFirestore:
    db = FakeFirestore()
    monkeypatch.setattr(memstore, "firestore_client", lambda: db)
    return db


def test_upsert_user_and_fetch(fake_db: FakeFirestore) -> None:
    memstore.upsert_user(
        UserProfile(uid="alex", display_name="Alex", base_age=15, ocean_t={"C": 50.0})
    )
    u = memstore.get_user("alex")
    assert u is not None
    assert u.display_name == "Alex"
    assert u.base_age == 15
    assert u.ocean_t == {"C": 50.0}


def test_update_ocean_merges(fake_db: FakeFirestore) -> None:
    memstore.upsert_user(UserProfile(uid="alex", base_age=15))
    memstore.update_ocean("alex", {"C": 55.0, "A": 52.0})
    u = memstore.get_user("alex")
    assert u is not None
    assert u.ocean_t == {"C": 55.0, "A": 52.0}


def test_chronicle_dedupes_by_semantic_id(fake_db: FakeFirestore) -> None:
    t = ChronicleTriple("alex", "ceni", "wolnosc", kind="value", weight=0.9)
    id1 = memstore.add_chronicle("alex", t)
    id2 = memstore.add_chronicle("alex", t)
    assert id1 == id2  # idempotent by content
    values = memstore.list_chronicle("alex", kind="value")
    assert len(values) == 1


def test_top_values_returns_by_weight(fake_db: FakeFirestore) -> None:
    for obj, w in [("wolnosc", 0.9), ("muzyka", 0.6), ("przyjazn", 0.8)]:
        memstore.add_chronicle(
            "alex",
            ChronicleTriple("alex", "ceni", obj, kind="value", weight=w),
        )
    top = memstore.top_values("alex", limit=2)
    assert top == ["wolnosc", "przyjazn"]


def test_add_memory_and_recent(fake_db: FakeFirestore) -> None:
    memstore.add_memory("alex", MemoryItem(text="boi sie porazki", topic="fears"))
    memstore.add_memory("alex", MemoryItem(text="lubi grac w kosza", topic="hobby"))
    got = memstore.recent_memories("alex", limit=5)
    assert len(got) == 2
    assert {m["topic"] for m in got} == {"fears", "hobby"}


def test_semantic_posts_returns_nearest_by_cosine(fake_db: FakeFirestore) -> None:
    e_music = [1.0, 0.0, 0.0]
    e_sport = [0.0, 1.0, 0.0]
    e_school = [0.0, 0.0, 1.0]
    memstore.add_post(
        "alex",
        SocialPost(platform="twitter", raw_text="nowy utwor", embedding=e_music),
    )
    memstore.add_post(
        "alex",
        SocialPost(platform="twitter", raw_text="mecz wczoraj", embedding=e_sport),
    )
    memstore.add_post(
        "alex",
        SocialPost(platform="twitter", raw_text="matma byla ciezka", embedding=e_school),
    )

    nearest = memstore.semantic_posts("alex", query_embedding=[0.9, 0.1, 0.0], k=2)
    assert len(nearest) == 2
    assert nearest[0]["raw_text"] == "nowy utwor"


def test_count_posts(fake_db: FakeFirestore) -> None:
    assert memstore.count_posts("alex") == 0
    memstore.add_post(
        "alex",
        SocialPost(platform="twitter", raw_text="pierwszy", embedding=[0.1, 0.2, 0.3]),
    )
    assert memstore.count_posts("alex") == 1


def test_append_context_notes_dedupes_and_caps(fake_db: FakeFirestore) -> None:
    memstore.append_context_notes("alex", ["a", "b", "a"])
    u = memstore.get_user("alex")
    assert u is not None
    assert u.context_notes == ["a", "b"]


def test_set_user_base_age_merges(fake_db: FakeFirestore) -> None:
    memstore.upsert_user(UserProfile(uid="alex", base_age=15))
    memstore.set_user_base_age("alex", 17)
    u = memstore.get_user("alex")
    assert u is not None
    assert u.base_age == 17
