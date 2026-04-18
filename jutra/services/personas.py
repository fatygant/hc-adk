"""Persona-facing service functions."""

from __future__ import annotations

from jutra.agents.future_self import build_persona_snapshot
from jutra.memory import store as memstore


def persona_snapshot(uid: str) -> dict:
    snap = build_persona_snapshot(uid)
    return {
        "uid": uid,
        "display_name": snap.display_name,
        "base_age": snap.base_age,
        "gender": snap.gender,
        "ocean_t": snap.base_ocean.as_dict(),
        "ocean_described": snap.base_ocean.describe(),
        "riasec_top3": list(snap.riasec_top3),
        "top_values": list(snap.top_values),
        "recent_memories_count": len(memstore.recent_memories(uid, limit=5)),
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
