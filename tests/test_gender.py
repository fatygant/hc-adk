from __future__ import annotations

import pytest

from jutra.agents import future_self as fs_mod
from jutra.memory import store as memstore
from jutra.memory.models import UserProfile
from jutra.personas.gender import infer_gender_pl
from tests._fakestore import FakeFirestore

# --- infer_gender_pl --------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["Anna", "Marta", "Katarzyna", "Ewa", "Joanna", "Agnieszka", "Małgorzata"],
)
def test_infer_gender_female(name: str) -> None:
    assert infer_gender_pl(name) == "f"


@pytest.mark.parametrize(
    "name",
    ["Piotr", "Jan", "Michał", "Tomasz", "Krzysztof", "Adam", "Paweł"],
)
def test_infer_gender_male(name: str) -> None:
    assert infer_gender_pl(name) == "m"


@pytest.mark.parametrize("name", ["Kuba", "Barnaba", "Kosma", "Bonawentura", "Jarema"])
def test_infer_gender_male_overrides(name: str) -> None:
    assert infer_gender_pl(name) == "m"


@pytest.mark.parametrize("name", ["", "A", "???", "x"])
def test_infer_gender_unknown(name: str) -> None:
    assert infer_gender_pl(name) == "u"


def test_infer_gender_uses_first_token() -> None:
    assert infer_gender_pl("Anna Maria Kowalska") == "f"
    assert infer_gender_pl("  Piotr  Nowak") == "m"


def test_infer_gender_is_case_insensitive_and_diacritic_safe() -> None:
    assert infer_gender_pl("MAŁGORZATA") == "f"
    assert infer_gender_pl("małgorzata") == "f"
    assert infer_gender_pl("Kuba") == "m"


# --- build_persona_snapshot gender wiring -----------------------------------


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> FakeFirestore:
    db = FakeFirestore()
    monkeypatch.setattr(memstore, "firestore_client", lambda: db)
    return db


def test_persona_snapshot_uses_stored_gender(fake_db: FakeFirestore) -> None:
    memstore.upsert_user(UserProfile(uid="u1", display_name="Jan", base_age=20, gender="m"))
    snap = fs_mod.build_persona_snapshot("u1")
    assert snap.gender == "m"


def test_persona_snapshot_falls_back_to_name_inference(
    fake_db: FakeFirestore,
) -> None:
    memstore.upsert_user(UserProfile(uid="u2", display_name="Anna", base_age=20, gender="u"))
    snap = fs_mod.build_persona_snapshot("u2")
    assert snap.gender == "f"


def test_persona_snapshot_respects_request_override(fake_db: FakeFirestore) -> None:
    memstore.upsert_user(UserProfile(uid="u3", display_name="Anna", base_age=20, gender="f"))
    snap = fs_mod.build_persona_snapshot("u3", gender="u")
    assert snap.gender == "u"


# --- _gender_directive copy matches what the prompt expects -----------------


def test_gender_directive_female_mentions_female_form() -> None:
    directive = fs_mod._gender_directive("f")
    assert "zenskim" in directive.lower() or "myslalam" in directive.lower()


def test_gender_directive_male_mentions_male_form() -> None:
    directive = fs_mod._gender_directive("m")
    assert "meskim" in directive.lower() or "myslalem" in directive.lower()


def test_gender_directive_unknown_avoids_guessing() -> None:
    directive = fs_mod._gender_directive("u")
    assert "bezosobow" in directive.lower() or "neutraln" in directive.lower()
