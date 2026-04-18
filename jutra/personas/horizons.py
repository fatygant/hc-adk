"""Compute a HorizonProfile ready to inject into a FutureSelf_N prompt."""

from __future__ import annotations

from jutra.personas.erikson import erikson_stage
from jutra.personas.maturity import maturity_shift
from jutra.personas.ocean import HorizonProfile, Ocean

SUPPORTED_HORIZONS: tuple[int, ...] = (5, 10, 20, 30)


def horizon_profile(
    base: Ocean,
    base_age: int,
    delta_years: int,
    riasec_top3: list[str] | None = None,
) -> HorizonProfile:
    if delta_years not in SUPPORTED_HORIZONS:
        raise ValueError(f"unsupported horizon {delta_years}; pick one of {SUPPORTED_HORIZONS}")
    target_age = base_age + delta_years
    return HorizonProfile(
        ocean=maturity_shift(base, base_age, delta_years),
        base_age=base_age,
        target_age=target_age,
        horizon_years=delta_years,
        erikson_stage=erikson_stage(target_age).label_pl,
        riasec_top3=list(riasec_top3 or []),
    )
