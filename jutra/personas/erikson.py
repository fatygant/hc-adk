"""Erikson's psychosocial stages mapped to age ranges.

The label + key_virtue + agenda fields are injected into FutureSelf prompts so
each horizon brings its own life-stage concerns (identity vs. role confusion
for a 15yo, generativity vs. stagnation for a 45yo, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EriksonStage:
    key: str
    label_pl: str
    age_range: tuple[int, int]
    key_virtue: str
    agenda: str  # short PL sentence used in system prompt


_STAGES: tuple[EriksonStage, ...] = (
    EriksonStage(
        "trust_vs_mistrust",
        "Ufnosc vs. nieufnosc",
        (0, 1),
        "nadzieja",
        "Budujesz podstawowe poczucie bezpieczenstwa.",
    ),
    EriksonStage(
        "autonomy_vs_shame",
        "Autonomia vs. wstyd",
        (2, 3),
        "wola",
        "Uczysz sie samodzielnosci w malej skali.",
    ),
    EriksonStage(
        "initiative_vs_guilt",
        "Inicjatywa vs. poczucie winy",
        (4, 5),
        "cel",
        "Probujesz wlasnych pomyslow na dzialanie.",
    ),
    EriksonStage(
        "industry_vs_inferiority",
        "Pracowitosc vs. poczucie nizszosci",
        (6, 11),
        "kompetencja",
        "Uczysz sie, ze cwiczenie daje kompetencje i uznanie.",
    ),
    EriksonStage(
        "identity_vs_role_confusion",
        "Tozsamosc vs. pomieszanie rol",
        (12, 19),
        "wiernosc sobie",
        "Szukasz wlasnych wartosci i jezyka, po ktorym mozna Cie poznac.",
    ),
    EriksonStage(
        "intimacy_vs_isolation",
        "Intymnosc vs. izolacja",
        (20, 39),
        "milosc",
        "Budujesz glebokie relacje i uczysz sie byc z kims bez tracenia siebie.",
    ),
    EriksonStage(
        "generativity_vs_stagnation",
        "Generatywnosc vs. stagnacja",
        (40, 64),
        "troska",
        "Inwestujesz w to, co przetrwa Ciebie: projekty, ludzi mlodszych, wspolnote.",
    ),
    EriksonStage(
        "integrity_vs_despair",
        "Integralnosc vs. rozpacz",
        (65, 200),
        "madrosc",
        "Zbierasz swoje zycie w historie, z ktorej jestes w stanie byc dumny/a.",
    ),
)


def erikson_stage(age: int) -> EriksonStage:
    if age < 0:
        raise ValueError("age must be >= 0")
    for stage in _STAGES:
        lo, hi = stage.age_range
        if lo <= age <= hi:
            return stage
    return _STAGES[-1]
