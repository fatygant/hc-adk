"""Persona-facing service functions."""

from __future__ import annotations

from jutra.agents.future_self import build_persona_snapshot
from jutra.memory import store as memstore
from jutra.personas.horizons import SUPPORTED_HORIZONS


def list_horizons() -> list[int]:
    return list(SUPPORTED_HORIZONS)


def persona_snapshot(uid: str, horizon_years: int) -> dict:
    snap = build_persona_snapshot(uid, horizon_years)
    return {
        "uid": uid,
        "horizon_years": snap.horizon_years,
        "base_age": snap.profile.base_age,
        "target_age": snap.profile.target_age,
        "erikson_stage": snap.profile.erikson_stage,
        "ocean_t": snap.profile.ocean.as_dict(),
        "ocean_described": snap.profile.ocean.describe(),
        "riasec_top3": list(snap.profile.riasec_top3),
        "top_values": list(snap.top_values),
        "recent_memories_count": len(snap.recent_memories),
    }


def get_chronicle(uid: str, limit: int = 50) -> dict:
    values = memstore.list_chronicle(uid, kind="value", limit=limit)
    prefs = memstore.list_chronicle(uid, kind="preference", limit=limit)
    facts = memstore.list_chronicle(uid, kind="fact", limit=limit)
    return {
        "uid": uid,
        "values": values,
        "preferences": prefs,
        "facts": facts,
    }
