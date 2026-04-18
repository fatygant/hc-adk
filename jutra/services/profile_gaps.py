"""Heuristic 'missing slot' labels for emergent onboarding (prompt injection)."""

from __future__ import annotations

from jutra.memory import store as memstore


def profile_gaps(uid: str) -> list[str]:
    """Polish labels for weak/empty persona slots."""
    gaps: list[str] = []
    if not memstore.top_values(uid, limit=1):
        gaps.append("wartości (co jest ważne)")
    prefs = memstore.list_chronicle(uid, kind="preference", limit=1)
    if not prefs:
        gaps.append("preferencje / co lubisz robić")
    user = memstore.get_user(uid)
    if user is not None and not (user.riasec_top3 or []):
        gaps.append("zainteresowania zawodowe / ścieżki (RIASEC)")

    recent = memstore.recent_memories(uid, limit=30)
    topics = {str(m.get("topic", "") or "").lower() for m in recent}

    if "fears" not in topics:
        gaps.append("lęki lub obawy")
    if "plans" not in topics:
        gaps.append("plany / cele")
    if "relations" not in topics:
        gaps.append("bliscy / relacje")
    if "hobby" not in topics:
        gaps.append("pasje / hobby")
    if "school" not in topics:
        gaps.append("szkoła / nauka")
    if "career" not in topics:
        gaps.append("praca / kariera")

    return gaps
