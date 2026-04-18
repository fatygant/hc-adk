from __future__ import annotations

import pytest

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


def test_ocean_describe_contains_all_traits() -> None:
    o = Ocean(O=62, C=45, E=50, A=55, N=40)
    desc = o.describe()
    for label in ("Otwartosc", "Sumiennosc", "Ekstrawersja", "Ugodowosc", "Neurotycznosc"):
        assert label in desc


def test_ocean_clipped_stays_in_range() -> None:
    o = Ocean(O=120, C=-5, E=50, A=0, N=95)
    c = o.clipped()
    for v in c.as_dict().values():
        assert T_MIN <= v <= T_MAX


def test_riasec_top3_defaults_when_no_signal() -> None:
    result = riasec_top3([])
    assert len(result.top3) == 3
    assert result.exploration_scenarios, "scenarios must not be empty"


def test_riasec_top3_picks_investigative_for_math_interests() -> None:
    result = riasec_top3(["lubie matematyke i programowanie", "naukowe podcasty"])
    assert "I" in result.top3
