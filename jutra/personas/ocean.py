"""OCEAN (Big Five) trait vector with T-score helpers.

Values are stored as *normative T-scores* (population mean = 50, SD = 10).
A T-score of 60 therefore means the user sits one SD above the age-adjusted
population average on that trait. Prompts render these as plain numbers so the
model can reason "you score 62 on conscientiousness (above average)".
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Literal

TraitName = Literal["O", "C", "E", "A", "N"]

T_MIN = 20.0
T_MAX = 80.0
T_MEAN = 50.0
T_SD = 10.0


@dataclass(frozen=True, slots=True)
class Ocean:
    """Big Five profile in T-score space (20..80)."""

    O: float = T_MEAN
    C: float = T_MEAN
    E: float = T_MEAN
    A: float = T_MEAN
    N: float = T_MEAN

    def as_dict(self) -> dict[TraitName, float]:
        return {f.name: getattr(self, f.name) for f in fields(self)}  # type: ignore[misc]

    def clipped(self) -> Ocean:
        return Ocean(
            O=clip(self.O),
            C=clip(self.C),
            E=clip(self.E),
            A=clip(self.A),
            N=clip(self.N),
        )

    def describe(self) -> str:
        """Short human-readable description used in prompts."""
        parts = []
        for k, v in self.as_dict().items():
            label = _TRAIT_LABELS[k]
            parts.append(f"{label} T={v:.0f} ({_bucket(v)})")
        return "; ".join(parts)


@dataclass(frozen=True, slots=True)
class HorizonProfile:
    """Everything a FutureSelf_N prompt needs to ground its voice."""

    ocean: Ocean
    base_age: int
    target_age: int
    horizon_years: int
    erikson_stage: str
    riasec_top3: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "ocean": self.ocean.as_dict(),
            "base_age": self.base_age,
            "target_age": self.target_age,
            "horizon_years": self.horizon_years,
            "erikson_stage": self.erikson_stage,
            "riasec_top3": list(self.riasec_top3),
        }


_TRAIT_LABELS: dict[TraitName, str] = {
    "O": "Otwartosc",
    "C": "Sumiennosc",
    "E": "Ekstrawersja",
    "A": "Ugodowosc",
    "N": "Neurotycznosc",
}


def clip(value: float, lo: float = T_MIN, hi: float = T_MAX) -> float:
    return max(lo, min(hi, value))


def t_score(raw: float, mean: float, sd: float) -> float:
    """Convert a raw Big Five score to population T-score."""
    if sd <= 0:
        raise ValueError("sd must be > 0")
    return 10.0 * (raw - mean) / sd + 50.0


def _bucket(t: float) -> str:
    if t >= 65:
        return "wysokie"
    if t >= 55:
        return "podwyzszone"
    if t >= 45:
        return "przecietne"
    if t >= 35:
        return "obnizone"
    return "niskie"
