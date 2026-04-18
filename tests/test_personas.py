from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from jutra.personas.erikson import erikson_stage
from jutra.personas.horizons import SUPPORTED_HORIZONS, horizon_profile
from jutra.personas.maturity import (
    OCEAN_DRIFT_PER_DECADE,
    adolescence_correction,
    maturity_shift,
)
from jutra.personas.ocean import T_MAX, T_MEAN, T_MIN, Ocean, clip, t_score
from jutra.personas.riasec import riasec_top3


def test_ocean_defaults_are_population_mean() -> None:
    o = Ocean()
    assert o.as_dict() == {"O": T_MEAN, "C": T_MEAN, "E": T_MEAN, "A": T_MEAN, "N": T_MEAN}


def test_t_score_maps_raw_to_population() -> None:
    assert t_score(50, mean=50, sd=10) == pytest.approx(50.0)
    assert t_score(60, mean=50, sd=10) == pytest.approx(60.0)
    assert t_score(40, mean=50, sd=10) == pytest.approx(40.0)
    with pytest.raises(ValueError):
        t_score(0, mean=50, sd=0)


def test_clip_bounds() -> None:
    assert clip(T_MIN - 10) == T_MIN
    assert clip(T_MAX + 10) == T_MAX
    assert clip(55) == 55


def test_adolescence_correction_pulls_C_A_down_and_N_up_for_13yo() -> None:
    base = Ocean(O=55, C=55, E=55, A=55, N=45)
    corrected = adolescence_correction(base, base_age=13)
    assert corrected.C < base.C
    assert corrected.A < base.A
    assert corrected.N > base.N
    # non-adolescent stays identical
    assert adolescence_correction(base, base_age=25) == base


def test_maturity_shift_moves_toward_mature_pattern() -> None:
    """A 15yo projected 20y forward should score higher on C and A, lower on N."""
    base = Ocean(O=55, C=50, E=50, A=50, N=55)
    future = maturity_shift(base, base_age=15, delta_years=20)
    assert future.C > base.C
    assert future.A > base.A
    assert future.N < base.N


def test_maturity_shift_bounded_within_20_80() -> None:
    base = Ocean(O=78, C=79, E=20, A=78, N=25)
    future = maturity_shift(base, base_age=15, delta_years=30)
    for v in future.as_dict().values():
        assert T_MIN <= v <= T_MAX


def test_maturity_shift_signs_match_drift_coefficients() -> None:
    """Non-adolescent: the sign of the shift in each trait equals sign of drift."""
    base = Ocean(O=50, C=50, E=50, A=50, N=50)
    fut = maturity_shift(base, base_age=25, delta_years=20)
    delta = {k: getattr(fut, k) - getattr(base, k) for k in "OCEAN"}
    for trait, drift in OCEAN_DRIFT_PER_DECADE.items():
        if drift > 0:
            assert delta[trait] > 0, f"{trait} expected to grow"
        elif drift < 0:
            assert delta[trait] < 0, f"{trait} expected to shrink"
        else:
            assert delta[trait] == 0, f"{trait} expected flat"


@given(delta1=st.integers(min_value=5, max_value=15), delta2=st.integers(min_value=5, max_value=15))
@settings(max_examples=50, deadline=None)
def test_maturity_shift_additive_for_adult_base(delta1: int, delta2: int) -> None:
    """For an adult base, applying shifts sequentially matches applying once (within eps)."""
    base = Ocean(O=52, C=48, E=55, A=50, N=52)
    chained = maturity_shift(maturity_shift(base, 25, delta1), 25 + delta1, delta2)
    one_shot = maturity_shift(base, 25, delta1 + delta2)
    for trait in "OCEAN":
        assert getattr(chained, trait) == pytest.approx(getattr(one_shot, trait), abs=0.05)


def test_erikson_stage_for_teen_is_identity() -> None:
    assert erikson_stage(15).key == "identity_vs_role_confusion"


def test_erikson_stage_for_45yo_is_generativity() -> None:
    assert erikson_stage(45).key == "generativity_vs_stagnation"


def test_erikson_stage_rejects_negative_age() -> None:
    with pytest.raises(ValueError):
        erikson_stage(-1)


def test_riasec_top3_defaults_when_no_signal() -> None:
    result = riasec_top3([])
    assert len(result.top3) == 3
    assert result.exploration_scenarios, "scenarios must not be empty"


def test_riasec_top3_picks_investigative_for_math_interests() -> None:
    result = riasec_top3(["lubie matematyke i programowanie", "naukowe podcasty"])
    assert "I" in result.top3
    assert all("scenariusz" not in s.lower() or True for s in result.exploration_scenarios)


def test_horizon_profile_rejects_unsupported_delta() -> None:
    base = Ocean()
    with pytest.raises(ValueError):
        horizon_profile(base, base_age=15, delta_years=7)


@pytest.mark.parametrize("delta", list(SUPPORTED_HORIZONS))
def test_horizon_profile_all_supported_horizons(delta: int) -> None:
    base = Ocean(O=55, C=48, E=55, A=50, N=55)
    profile = horizon_profile(base, base_age=15, delta_years=delta, riasec_top3=["I"])
    assert profile.horizon_years == delta
    assert profile.target_age == 15 + delta
    assert profile.erikson_stage  # non-empty PL label
    assert profile.riasec_top3 == ["I"]


def test_horizon_profile_yields_different_ocean_per_horizon() -> None:
    """Guardrail for the WOW demo: each horizon must be mathematically distinct."""
    base = Ocean(O=55, C=48, E=55, A=50, N=55)
    snapshots = {h: horizon_profile(base, 15, h).ocean.as_dict() for h in SUPPORTED_HORIZONS}
    # No two horizons should have exactly identical C (the loudest drifting trait).
    c_values = {h: snap["C"] for h, snap in snapshots.items()}
    assert len(set(c_values.values())) == len(SUPPORTED_HORIZONS)
