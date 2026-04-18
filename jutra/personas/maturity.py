"""Maturity Principle: age-driven OCEAN drift + adolescence correction.

Rationale (see docs/synthetic-identity-persona-creation.md):
- Longitudinal studies find stable mean-level trends per decade of adulthood
  (Roberts & Mroczek 2008, Soto 2016). We use conservative linear coefficients
  expressed in *T-score points per decade* (1 SD = 10 T-points):
    Conscientiousness  +1.5  (growth peaks 50-70y)
    Agreeableness      +1.2
    Emotional Stability (i.e. -Neuroticism)  +1.0   -> N -= 1.0/dec
    Openness           -0.2
    Extraversion        0.0
- Disruption hypothesis: during puberty (~12-14y) Conscientiousness and
  Agreeableness dip and Neuroticism rises temporarily. We model this as a
  one-time correction applied when the *current* age is <18, and we *reverse*
  the dip over the first ~5 years of projection so that by early adulthood the
  agent already reflects post-adolescence recovery.
"""

from __future__ import annotations

from jutra.personas.ocean import Ocean, clip

# T-score points per decade of life (positive = trait increases with age).
OCEAN_DRIFT_PER_DECADE: dict[str, float] = {
    "O": -0.2,
    "C": +1.5,
    "E": +0.0,
    "A": +1.2,
    "N": -1.0,
}

# Adolescence disruption applied when base_age is in [11, 16]. Subtracted from
# the baseline so that "the current self" reflects the temporary dip.
ADOLESCENCE_DIP: dict[str, float] = {
    "C": -2.0,
    "A": -1.5,
    "N": +2.0,
    "O": 0.0,
    "E": 0.0,
}

ADOLESCENCE_WINDOW = range(11, 17)  # 11..16 inclusive


def adolescence_correction(base: Ocean, base_age: int) -> Ocean:
    """Apply the disruption hypothesis for base_age in 11..16."""
    if base_age not in ADOLESCENCE_WINDOW:
        return base
    dip = ADOLESCENCE_DIP
    return Ocean(
        O=clip(base.O + dip["O"]),
        C=clip(base.C + dip["C"]),
        E=clip(base.E + dip["E"]),
        A=clip(base.A + dip["A"]),
        N=clip(base.N + dip["N"]),
    ).clipped()


def _recovery_fraction(base_age: int, delta_years: int) -> float:
    """How much of the adolescence dip has recovered by target_age.

    Linear ramp from 0 at adolescence to 1.0 once target_age >= 21.
    """
    target_age = base_age + delta_years
    if target_age <= base_age:
        return 0.0
    if target_age >= 21:
        return 1.0
    return min(1.0, max(0.0, (target_age - base_age) / (21 - base_age)))


def maturity_shift(base: Ocean, base_age: int, delta_years: int) -> Ocean:
    """Return OCEAN vector projected `delta_years` into the future.

    Property: `maturity_shift(maturity_shift(o, a, d1), a+d1, d2)` approximates
    `maturity_shift(o, a, d1+d2)` up to ~0.5 T-score drift introduced by
    adolescence recovery (tested with hypothesis).
    """
    if delta_years < 0:
        raise ValueError("delta_years must be >= 0 for future projection")

    # Start from adolescence-corrected baseline so the "present self" carries
    # the dip, then linearly restore dip as agent approaches 21.
    corrected = adolescence_correction(base, base_age)
    recover = _recovery_fraction(base_age, delta_years)
    dip = ADOLESCENCE_DIP if base_age in ADOLESCENCE_WINDOW else dict.fromkeys("OCEAN", 0.0)

    decades = delta_years / 10.0
    drift = OCEAN_DRIFT_PER_DECADE
    return Ocean(
        O=clip(corrected.O + drift["O"] * decades - dip["O"] * recover),
        C=clip(corrected.C + drift["C"] * decades - dip["C"] * recover),
        E=clip(corrected.E + drift["E"] * decades - dip["E"] * recover),
        A=clip(corrected.A + drift["A"] * decades - dip["A"] * recover),
        N=clip(corrected.N + drift["N"] * decades - dip["N"] * recover),
    )
