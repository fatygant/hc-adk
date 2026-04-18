"""Conversational onboarding agent.

Deprecated for product UX: replaced by emergent voice onboarding (future_self +
extract_and_save + profile_gaps). Kept for API compatibility and demos.

Runs a 5-7 turn JSON-based Q&A to seed the Chronicle + OCEAN from direct user
answers. State lives in-memory keyed by session_id for the hackathon (fine for
a single Cloud Run instance with --min-instances 1). Each turn:

  1. Collect user's answer + any signals it carries.
  2. Write extracted values / preferences / fears to Firestore Chronicle.
  3. Bump RIASEC and (very light) OCEAN signals on the user profile.
  4. Return the next question (or completed=true when we have >= 3 values and
     >= 3 preferences).
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field

from google.genai import types as genai_types

from jutra.agents.prompts import load as load_prompt
from jutra.infra.vertex import generate_with_fallback
from jutra.memory import store as memstore
from jutra.memory.models import ChronicleTriple, MemoryItem, UserProfile
from jutra.personas.ocean import Ocean, clip
from jutra.personas.riasec import RIASEC_TYPES, riasec_top3

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class OnboardingSession:
    session_id: str
    uid: str
    turns: int = 0
    completed: bool = False
    collected_values: list[str] = field(default_factory=list)
    collected_prefs: list[str] = field(default_factory=list)
    collected_fears: list[str] = field(default_factory=list)
    collected_riasec_signals: list[str] = field(default_factory=list)


_SESSIONS: dict[str, OnboardingSession] = {}


_FIRST_QUESTION = (
    "Powiedz mi trzy rzeczy, idee albo osoby, ktore dzis sa dla Ciebie "
    "najwazniejsze. Po kolei, jak przyjdzie."
)


def start_onboarding(uid: str) -> tuple[str, str]:
    """Create a session and return (session_id, first_question)."""
    sid = uuid.uuid4().hex[:16]
    _SESSIONS[sid] = OnboardingSession(session_id=sid, uid=uid)
    return sid, _FIRST_QUESTION


def _llm_turn(user_message: str, history: list[dict]) -> dict:
    # We send system + the last user message; history is optional context.
    # Gemini 3 Flash has thinking on by default; for a short structured-JSON
    # answer we disable it (thinking_budget=0) and give the model enough
    # output budget so it never truncates the closing braces.
    config = genai_types.GenerateContentConfig(
        system_instruction=load_prompt("onboarding"),
        temperature=0.4,
        response_mime_type="application/json",
        max_output_tokens=1024,
        thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
    )
    context = user_message
    if history:
        context = (
            "Historia ostatnich wypowiedzi uzytkownika:\n"
            + "\n".join(f"- {h.get('text', '')}" for h in history[-3:])
            + "\n\nOstatnia wypowiedz uzytkownika:\n"
            + user_message
        )
    try:
        resp = generate_with_fallback("chat", context, config=config)
        raw = resp.text or "{}"
        return json.loads(re.sub(r"```json|```", "", raw).strip() or "{}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("onboarding LLM turn failed: %s", exc)
        return {}


def _apply_extraction_to_chronicle(
    uid: str,
    values: list[str],
    prefs: list[str],
    fears: list[str],
) -> None:
    for v in values:
        memstore.add_chronicle(
            uid,
            ChronicleTriple(
                subject=uid,
                predicate="ceni",
                object=v,
                kind="value",
                weight=0.9,
                source="onboarding",
            ),
        )
    for p in prefs:
        memstore.add_chronicle(
            uid,
            ChronicleTriple(
                subject=uid,
                predicate="lubi",
                object=p,
                kind="preference",
                weight=0.7,
                source="onboarding",
            ),
        )
    for f in fears:
        memstore.add_memory(uid, MemoryItem(text=f, topic="fears", source="onboarding"))


def _update_user_with_riasec(uid: str, signals: list[str]) -> list[str]:
    """Merge RIASEC signals into user profile; return the current top3."""
    clean = [s for s in signals if s in RIASEC_TYPES]
    if not clean:
        user = memstore.get_user(uid)
        return list(user.riasec_top3) if user and user.riasec_top3 else []
    riasec_result = riasec_top3([f"riasec:{s}" for s in clean])  # passthrough
    # Simpler: keep the union of existing top3 + new signals, cap at 3.
    user = memstore.get_user(uid)
    current = set(user.riasec_top3) if user and user.riasec_top3 else set()
    merged = list(current) + [s for s in clean if s not in current]
    merged = merged[:3] if len(merged) >= 3 else (merged + riasec_result.top3)[:3]
    memstore.upsert_user(
        UserProfile(
            uid=uid,
            display_name=user.display_name if user else "",
            base_age=user.base_age if user else 15,
            ocean_t=dict(user.ocean_t) if user and user.ocean_t else Ocean().as_dict(),
            riasec_top3=merged,
        )
    )
    return merged


def _nudge_ocean_from_signals(uid: str, values: list[str], prefs: list[str]) -> None:
    """Very light heuristic: each declared value adds +0.5 T on Openness,
    each preference adds +0.3 T on Extraversion. Bounded."""
    user = memstore.get_user(uid)
    if user is None:
        return
    ocean = dict(user.ocean_t) if user.ocean_t else Ocean().as_dict()
    ocean["O"] = clip(ocean.get("O", 50.0) + 0.5 * len(values))
    ocean["E"] = clip(ocean.get("E", 50.0) + 0.3 * len(prefs))
    memstore.update_ocean(uid, ocean, source="onboarding")


def onboarding_turn(session_id: str, user_message: str) -> dict:
    """Process one onboarding reply; return dict matching the MCP tool schema."""
    session = _SESSIONS.get(session_id)
    if session is None:
        raise ValueError(f"unknown onboarding session: {session_id}")
    if session.completed:
        return {
            "acknowledgment": "Juz zakonczylismy onboarding.",
            "next_question": None,
            "progress": 1.0,
            "completed": True,
            "extracted": {},
        }

    result = _llm_turn(user_message, history=[{"text": user_message}])
    values = [v for v in result.get("extracted_values", []) if v]
    prefs = [p for p in result.get("extracted_preferences", []) if p]
    fears = [f for f in result.get("extracted_fears", []) if f]
    riasec_signals = [s for s in result.get("riasec_signals", []) if s in RIASEC_TYPES]

    _apply_extraction_to_chronicle(session.uid, values, prefs, fears)
    _nudge_ocean_from_signals(session.uid, values, prefs)
    current_riasec = _update_user_with_riasec(session.uid, riasec_signals)

    session.turns += 1
    session.collected_values.extend(values)
    session.collected_prefs.extend(prefs)
    session.collected_fears.extend(fears)
    session.collected_riasec_signals.extend(riasec_signals)

    have_enough = len(set(session.collected_values)) >= 3 and len(set(session.collected_prefs)) >= 3
    completed = bool(result.get("completed")) or (session.turns >= 7 and have_enough)
    progress = min(1.0, session.turns / 7.0 if not completed else 1.0)

    question = result.get("question") if not completed else None
    if completed:
        session.completed = True

    return {
        "acknowledgment": result.get("acknowledgment", ""),
        "next_question": question,
        "progress": progress,
        "completed": completed,
        "extracted": {
            "values": values,
            "preferences": prefs,
            "fears": fears,
            "riasec_signals": riasec_signals,
            "riasec_top3": current_riasec,
        },
    }
