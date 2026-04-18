"""FutureSelf_N chat agent.

We build the system prompt at every turn (not once at agent construction) so
horizon, OCEAN, Chronicle and RAG posts are always fresh. The agent itself is
a plain `generate_with_fallback` call routed to `gemini-3-flash-preview` for
horizons 5/10/20 and `gemini-3.1-pro-preview` for horizon 30. ADK's `LlmAgent`
is reserved for the conversational onboarding agent (multi-turn tool use
shines there); FutureSelf is stateless per turn which makes a direct call
simpler and faster for the hackathon demo.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

from google.genai import types as genai_types

from jutra.agents.prompts import load as load_prompt
from jutra.infra.vertex import generate_stream_with_fallback, generate_with_fallback
from jutra.memory import store as memstore
from jutra.memory.models import UserProfile
from jutra.personas.horizons import SUPPORTED_HORIZONS, horizon_profile
from jutra.personas.ocean import HorizonProfile, Ocean

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PersonaSnapshot:
    uid: str
    horizon_years: int
    profile: HorizonProfile
    top_values: list[str]
    recent_memories: list[dict]


def _user_or_fresh(uid: str) -> UserProfile:
    u = memstore.get_user(uid)
    if u is not None:
        return u
    new = UserProfile(uid=uid, base_age=15, ocean_t=Ocean().as_dict())
    memstore.upsert_user(new)
    return new


def build_persona_snapshot(uid: str, horizon_years: int) -> PersonaSnapshot:
    if horizon_years not in SUPPORTED_HORIZONS:
        raise ValueError(f"unsupported horizon {horizon_years}; use {SUPPORTED_HORIZONS}")
    user = _user_or_fresh(uid)
    base_ocean = (
        Ocean(**{k: float(v) for k, v in (user.ocean_t or {}).items()}) if user.ocean_t else Ocean()
    )
    profile = horizon_profile(
        base_ocean,
        base_age=user.base_age,
        delta_years=horizon_years,
        riasec_top3=user.riasec_top3,
    )
    return PersonaSnapshot(
        uid=uid,
        horizon_years=horizon_years,
        profile=profile,
        top_values=memstore.top_values(uid, limit=5),
        recent_memories=memstore.recent_memories(uid, limit=5),
    )


def _format_list(items: list[str]) -> str:
    if not items:
        return "(brak danych)"
    return "\n".join(f"- {i}" for i in items)


def _format_memories(items: list[dict]) -> str:
    if not items:
        return "(brak - to pierwsza rozmowa)"
    return "\n".join(f"- [{m.get('topic', 'n/a')}] {m.get('text', '')}" for m in items)


def _format_rag(posts: list[dict]) -> str:
    if not posts:
        return "(brak pasujacych postow)"
    return "\n".join(f"- ({p.get('platform', '?')}) {p.get('raw_text', '')[:220]}" for p in posts)


def _build_system_prompt(
    snap: PersonaSnapshot,
    *,
    display_name: str,
    rag_posts: list[dict],
) -> str:
    template = load_prompt("future_self")
    return template.format(
        display_name=display_name or "Ty",
        horizon_years=snap.horizon_years,
        target_age=snap.profile.target_age,
        erikson_stage=snap.profile.erikson_stage,
        ocean_description=snap.profile.ocean.describe(),
        top_values_block=_format_list(snap.top_values),
        riasec_block=_format_list(snap.profile.riasec_top3 or []),
        recent_memories_block=_format_memories(snap.recent_memories),
        rag_posts_block=_format_rag(rag_posts),
    )


def _kind_for_horizon(horizon_years: int) -> str:
    return "reasoning" if horizon_years >= 30 else "chat"


def future_self_reply(
    uid: str,
    horizon_years: int,
    user_message: str,
    *,
    rag_query_embedding: list[float] | None = None,
    display_name: str = "Ty",
    fast: bool = False,
) -> str:
    """Generate a FutureSelf_N reply grounded in persona + Chronicle + RAG.

    Caller is responsible for safety wrapping (wrap_turn). Returns raw LLM text.

    When `fast=True`, the call is optimised for voice: we force the chat model
    regardless of horizon, disable thinking tokens, and tighten the output
    budget. Typical speedup on horizon=30 is ~4x (≈10s -> ≈2.5s).
    """
    snap = build_persona_snapshot(uid, horizon_years)
    rag_posts: list[dict] = []
    if rag_query_embedding:
        try:
            rag_posts = memstore.semantic_posts(uid, rag_query_embedding, k=5)
        except Exception as exc:  # noqa: BLE001
            logger.warning("semantic_posts failed (%s); proceeding without RAG", exc)

    system = _build_system_prompt(snap, display_name=display_name, rag_posts=rag_posts)
    if fast:
        # Voice path: always use the chat (flash) model, skip thinking, cap
        # output so TTS starts sooner and we don't bill for tokens the user
        # won't hear.
        kind = "chat"
        thinking_budget = 0
        max_output_tokens = 400
    else:
        kind = _kind_for_horizon(horizon_years)
        thinking_budget = 512 if kind == "reasoning" else 128
        max_output_tokens = 1400
    config = genai_types.GenerateContentConfig(
        system_instruction=system,
        temperature=0.8,
        top_p=0.95,
        max_output_tokens=max_output_tokens,
        thinking_config=genai_types.ThinkingConfig(thinking_budget=thinking_budget),
    )
    resp = generate_with_fallback(kind, user_message, config=config)
    return (resp.text or "").strip()


def _fast_voice_config(
    snap: PersonaSnapshot, *, display_name: str, rag_posts: list[dict]
) -> genai_types.GenerateContentConfig:
    system = _build_system_prompt(snap, display_name=display_name, rag_posts=rag_posts)
    return genai_types.GenerateContentConfig(
        system_instruction=system,
        temperature=0.8,
        top_p=0.95,
        max_output_tokens=400,
        thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
    )


async def future_self_reply_stream(
    uid: str,
    horizon_years: int,
    user_message: str,
    *,
    rag_query_embedding: list[float] | None = None,
    display_name: str = "Ty",
) -> AsyncIterator[str]:
    """Voice-optimised streaming variant of `future_self_reply`.

    Always runs with the fast voice preset (flash model, thinking_budget=0,
    max_output_tokens=400) because this path is only reachable from the
    LiveKit worker, where first-audio latency trumps full-reasoning quality.
    Yields raw text deltas; caller handles disclosure prefixing / TTS.
    """
    snap = build_persona_snapshot(uid, horizon_years)
    rag_posts: list[dict] = []
    if rag_query_embedding:
        try:
            rag_posts = memstore.semantic_posts(uid, rag_query_embedding, k=5)
        except Exception as exc:  # noqa: BLE001
            logger.warning("semantic_posts failed (%s); proceeding without RAG", exc)

    config = _fast_voice_config(snap, display_name=display_name, rag_posts=rag_posts)
    async for delta in generate_stream_with_fallback("chat", user_message, config=config):
        yield delta
