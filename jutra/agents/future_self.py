"""FutureSelf chat agent.

We build the system prompt at every turn (not once at agent construction) so the
baseline persona, Chronicle, recent memories, and RAG posts are always fresh.
The agent is a plain `generate_with_fallback` call routed to
`gemini-3-flash-preview`; ADK's `LlmAgent` is reserved for the conversational
onboarding agent (multi-turn tool use shines there).

The agent speaks as a *wiser future version of the user*. The model chooses its
own age standpoint per reply from conversation context — no fixed horizon.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from google.genai import types as genai_types

from jutra.agents.prompts import load as load_prompt
from jutra.infra.vertex import generate_stream_with_fallback, generate_with_fallback
from jutra.memory import store as memstore
from jutra.memory.models import Gender, UserProfile
from jutra.personas.gender import infer_gender_pl
from jutra.personas.ocean import Ocean
from jutra.services.profile_gaps import profile_gaps

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PersonaSnapshot:
    uid: str
    display_name: str
    base_age: int
    gender: Gender
    base_ocean: Ocean
    top_values: list[str]
    riasec_top3: list[str]


def _user_or_fresh(uid: str) -> UserProfile:
    u = memstore.get_user(uid)
    if u is not None:
        return u
    new = UserProfile(uid=uid, base_age=15, ocean_t=Ocean().as_dict())
    memstore.upsert_user(new)
    return new


def build_persona_snapshot(
    uid: str,
    display_name: str | None = None,
    gender: Gender | None = None,
) -> PersonaSnapshot:
    user = _user_or_fresh(uid)
    base_ocean = (
        Ocean(**{k: float(v) for k, v in (user.ocean_t or {}).items()})
        if user.ocean_t
        else Ocean()
    )
    # None = REST/persona path: use stored profile. Otherwise caller overrides (chat/MCP).
    if display_name is None:
        name = user.display_name or "Ty"
    else:
        name = display_name or user.display_name or "Ty"
    # Prefer explicit request override, then stored profile, then a fresh
    # name-based inference (handles legacy users with gender="u").
    if gender in ("f", "m", "u"):
        effective_gender: Gender = gender
    elif user.gender in ("f", "m"):
        effective_gender = user.gender
    else:
        effective_gender = infer_gender_pl(name)
    return PersonaSnapshot(
        uid=uid,
        display_name=name,
        base_age=user.base_age,
        gender=effective_gender,
        base_ocean=base_ocean,
        top_values=memstore.top_values(uid, limit=5),
        riasec_top3=list(user.riasec_top3 or []),
    )


def _format_list(items: list[str]) -> str:
    if not items:
        return "(brak danych)"
    return "\n".join(f"- {i}" for i in items)


def _format_memories(items: list[dict]) -> str:
    if not items:
        return "(brak - to pierwsza rozmowa)"
    return "\n".join(f"- [{m.get('topic', 'n/a')}] {m.get('text', '')}" for m in items)


def _memory_relevance_score(mem: dict, user_message: str) -> float:
    um = user_message.lower()
    blob = f"{mem.get('topic', '')} {mem.get('text', '')}".lower()
    u_toks = set(re.findall(r"\w{3,}", um))
    b_toks = set(re.findall(r"\w{3,}", blob))
    overlap = len(u_toks & b_toks)
    topic = str(mem.get("topic") or "").lower()
    bonus = 0.0
    if topic == "plans" and any(x in um for x in ("plan", "jutro", "rok", "cel", "zdąż", "zdaz")):
        bonus += 2.0
    if topic == "fears" and any(x in um for x in ("boj", "lek", "stres", "lęk")):
        bonus += 2.0
    if topic == "school" and any(x in um for x in ("szkoł", "szkol", "lekcj", "klas", "matur")):
        bonus += 2.0
    return float(overlap) + bonus


def _select_topic_biased_memories(uid: str, user_message: str, *, limit: int = 5) -> list[dict]:
    pool = memstore.recent_memories(uid, limit=30)
    if not pool:
        return []
    scored: list[tuple[float, int, dict]] = []
    for i, mem in enumerate(pool):
        recency = float(len(pool) - i)
        rel = _memory_relevance_score(mem, user_message)
        scored.append((rel * 3.0 + recency * 0.15, i, mem))
    scored.sort(key=lambda x: (-x[0], x[1]))
    out: list[dict] = []
    seen: set[int] = set()
    for _, _, mem in scored:
        hid = hash(str(mem.get("text", ""))[:200])
        if hid in seen:
            continue
        seen.add(hid)
        out.append(mem)
        if len(out) >= limit:
            break
    return out


def _horizon_line(user_message: str) -> str:
    m = user_message.lower()
    far_kw = (
        "sens życia",
        "sens zycia",
        "za 10 lat",
        "za dziesiec",
        "kim będę",
        "kim bede",
        "śmierć",
        "smierc",
        "przyszłość",
        "przyszlosc",
        "cel życia",
        "cel zycia",
    )
    near_kw = (
        "dziś",
        "dzis",
        "jutro",
        "teraz",
        "klasówka",
        "klasowka",
        "dziennik",
        "dziś mam",
    )
    if any(k in m for k in far_kw):
        return "odlegly — jakby patrzec z dalszej perspektywy zyciowej (bez liczenia lat)."
    if any(k in m for k in near_kw):
        return "bliski — jakby to bylo za chwile albo kilka dni (bez liczenia lat)."
    return "sredni — jak kilka lat doswiadczenia wiecej niz teraz (bez liczenia lat)."


def _banned_openers_from_turns(turns: list[dict]) -> list[str]:
    asst: list[str] = []
    for t in turns:
        if (t.get("role") or "").strip() != "assistant":
            continue
        text = (t.get("text") or "").strip()
        if not text:
            continue
        words = text.split()[:3]
        if words:
            asst.append(" ".join(words))
    return asst[-4:]


def _format_identity_facets_block(uid: str) -> str:
    facets = memstore.get_identity_facets(uid)
    if not facets:
        return "(brak — tylko gdy uzytkownik poda wprost)"
    lines = [f"- {k}: {v}" for k, v in facets.items()]
    return "\n".join(lines)


def _format_disputed_block(uid: str) -> str:
    items = memstore.list_disputed_chronicle(uid, limit=12)
    if not items:
        return "(brak)"
    lines = []
    for it in items:
        k = it.get("kind", "")
        o = it.get("object", "")
        if o:
            lines.append(f"- ({k}) {o}")
    return "\n".join(lines) if lines else "(brak)"


def _format_commitments_block(uid: str) -> str:
    rows = memstore.list_open_commitments(uid, limit=3)
    if not rows:
        return "(brak)"
    lines = []
    for r in rows:
        t = (r.get("text") or "").strip()
        dh = (r.get("due_hint") or "").strip()
        if dh:
            lines.append(f"- {t} (termin: {dh})")
        else:
            lines.append(f"- {t}")
    return "\n".join(lines)


def _format_arcs_block(uid: str) -> str:
    arcs = memstore.list_recent_arcs(uid, limit=3)
    if not arcs:
        return "(brak)"
    lines = []
    for a in arcs:
        o = (a.get("object") or "").strip()
        if o:
            lines.append(f"- {o[:400]}")
    return "\n".join(lines) if lines else "(brak)"


def _session_continuity_block(is_continuing: bool) -> str:
    if is_continuing:
        return (
            "To jest **trwajaca rozmowa glosowa**. Powitanie juz sie odbylo na poczatku sesji. "
            "**NIE zaczynaj odpowiedzi od powitania** — zadnego \"Czesc\", \"Hej\", \"Witaj\", "
            "\"Dzien dobry\", \"Sluchaj\", \"No wiesz\". Wchodz prosto w tresc."
        )
    return (
        "To moze byc **pierwsza wymiana tresci** w tej sesji (poza ewentualnym powitaniem glosowym). "
        "Mozesz zaczac naturalnie, bez sztucznego skracania — nadal bez podawania liczby lat."
    )


def _banned_openers_block(phrases: list[str]) -> str:
    if not phrases:
        return "(brak zapisanych otwarc — unikaj szablonow typu \"Rozumiem\", \"Wiesz co\")"
    return "; ".join(f'\"{p}\"' for p in phrases)


def _closing_directive(is_continuing: bool) -> str:
    if is_continuing:
        return "Pamietaj: **bez powitan, bez liczby lat i bez powtarzalnych otwarc** — to jest srodek rozmowy."
    return "Bez podawania liczby lat; nie powtarzaj tych samych otwarc co wczesniej w tej sesji."


def _gender_directive(gender: Gender) -> str:
    """Polish grammatical-gender instruction for the system prompt.

    Polish past-tense verbs and adjectives inflect for gender, so a mismatched
    voice (female TTS reading masculine verb endings) breaks the illusion of
    talking to yourself. We pin the grammar deterministically here; the model
    is free to vary register otherwise.
    """
    if gender == "f":
        return (
            "Mow o sobie w rodzaju zenskim: uzywaj form typu 'myslalam', 'bylam', "
            "'robilam', 'pewna', 'gotowa', 'spokojna'. Jestes przyszla, dojrzalsza "
            "wersja kobiety — nigdy nie uzywaj form meskich o sobie."
        )
    if gender == "m":
        return (
            "Mow o sobie w rodzaju meskim: uzywaj form typu 'myslalem', 'bylem', "
            "'robilem', 'pewny', 'gotowy', 'spokojny'. Jestes przyszla, dojrzalsza "
            "wersja mezczyzny — nigdy nie uzywaj form zenskich o sobie."
        )
    # unknown: stay grammatically neutral by preferring present tense and
    # impersonal constructions ("myśli się", "warto", "dobrze jest").
    return (
        "Nie znasz rodzaju gramatycznego uzytkownika. Gdy mowisz o sobie w czasie "
        "przeszlym, uzywaj konstrukcji bezosobowych lub czasu terazniejszego "
        "(np. 'pamietam, ze', 'wydaje mi sie', 'warto'). Unikaj form typu "
        "'myslalem/myslalam' i 'pewny/pewna' — wybieraj opisy neutralne."
    )


def _format_rag(posts: list[dict]) -> str:
    if not posts:
        return "(brak pasujacych postow)"
    return "\n".join(f"- ({p.get('platform', '?')}) {p.get('raw_text', '')[:220]}" for p in posts)


def _format_context_notes(notes: list[str]) -> str:
    if not notes:
        return "(brak notatek — buduj relacje z tej rozmowy)"
    return "\n".join(f"- {n}" for n in notes)


def _format_profile_gaps_block(uid: str) -> str:
    gaps = profile_gaps(uid)
    if not gaps:
        return "(brak oczywistych luk — pytaj tylko gdy naturalnie pasuje)"
    return ", ".join(gaps)


def _format_recent_turns(turns: list[dict]) -> str:
    if not turns:
        return "(to pierwsza wypowiedz uzytkownika po powitaniu startowym)"
    lines: list[str] = []
    for t in turns:
        role = (t.get("role") or "").strip()
        text = (t.get("text") or "").strip().replace("\n", " ")
        if not text or role not in ("user", "assistant"):
            continue
        label = "Uzytkownik" if role == "user" else "Ty (przyszle ja)"
        if len(text) > 240:
            text = text[:237] + "..."
        lines.append(f"- {label}: {text}")
    return "\n".join(lines) or "(pusto)"


def _format_style_profile_block(uid: str) -> str:
    u = memstore.get_user(uid)
    sp = dict((u.style_profile if u else {}) or {})
    sp.pop("updated_at", None)
    if not sp:
        return "(jeszcze za malo rozmowy — nasluchuj)"
    lines: list[str] = []
    for key in ("formality", "tone", "sentence_length", "vocabulary_notes", "emoji_usage"):
        v = sp.get(key)
        if v is not None and str(v).strip():
            lines.append(f"- {key}: {v}")
    for key in ("typical_openers", "fillers", "signature_phrases", "examples"):
        val = sp.get(key)
        if isinstance(val, list) and val:
            lines.append(f"- {key}: {', '.join(str(x) for x in val[:10] if str(x).strip())}")
    return "\n".join(lines) if lines else "(jeszcze za malo rozmowy — nasluchuj)"


@dataclass(frozen=True, slots=True)
class _PromptContext:
    snap: PersonaSnapshot
    user_message: str
    rag_posts: list[dict] = field(default_factory=list)


def _build_system_prompt(ctx: _PromptContext) -> str:
    snap = ctx.snap
    uid = snap.uid
    template = load_prompt("future_self")
    ctx_notes = memstore.get_context_notes(uid, limit=40)
    recent_turns = memstore.recent_chat_turns(uid, limit=8)
    is_continuing = len(recent_turns) > 0
    mems = _select_topic_biased_memories(uid, ctx.user_message, limit=5)
    banned = _banned_openers_from_turns(recent_turns)
    return template.format(
        display_name=snap.display_name or "Ty",
        base_age=snap.base_age,
        gender_directive=_gender_directive(snap.gender),
        horizon_line=_horizon_line(ctx.user_message),
        ocean_description=snap.base_ocean.describe(),
        identity_facets_block=_format_identity_facets_block(uid),
        top_values_block=_format_list(snap.top_values),
        riasec_block=_format_list(snap.riasec_top3 or []),
        recent_memories_block=_format_memories(mems),
        context_notes_block=_format_context_notes(ctx_notes),
        disputed_block=_format_disputed_block(uid),
        commitments_block=_format_commitments_block(uid),
        arcs_block=_format_arcs_block(uid),
        profile_gaps_block=_format_profile_gaps_block(uid),
        rag_posts_block=_format_rag(ctx.rag_posts),
        recent_turns_block=_format_recent_turns(recent_turns),
        style_profile_block=_format_style_profile_block(uid),
        session_continuity_block=_session_continuity_block(is_continuing),
        banned_openers_block=_banned_openers_block(banned),
        closing_directive=_closing_directive(is_continuing),
    )


def future_self_reply(
    uid: str,
    user_message: str,
    *,
    rag_query_embedding: list[float] | None = None,
    display_name: str | None = None,
    gender: Gender | None = None,
    fast: bool = False,
) -> str:
    """Generate a future-self reply grounded in persona + Chronicle + RAG.

    Caller is responsible for safety wrapping (wrap_turn). Returns raw LLM text.
    When `fast=True`, tightens the output budget and disables thinking tokens
    (used by the voice path).
    """
    snap = build_persona_snapshot(uid, display_name=display_name, gender=gender)
    rag_posts: list[dict] = []
    if rag_query_embedding:
        try:
            rag_posts = memstore.semantic_posts(uid, rag_query_embedding, k=5)
        except Exception as exc:  # noqa: BLE001
            logger.warning("semantic_posts failed (%s); proceeding without RAG", exc)

    system = _build_system_prompt(
        _PromptContext(snap=snap, user_message=user_message, rag_posts=rag_posts)
    )
    if fast:
        thinking_budget = 0
        max_output_tokens = 400
    else:
        thinking_budget = 128
        max_output_tokens = 1400
    config = genai_types.GenerateContentConfig(
        system_instruction=system,
        temperature=0.8,
        top_p=0.95,
        max_output_tokens=max_output_tokens,
        thinking_config=genai_types.ThinkingConfig(thinking_budget=thinking_budget),
    )
    resp = generate_with_fallback("chat", user_message, config=config)
    return (resp.text or "").strip()


def _fast_voice_config(ctx: _PromptContext) -> genai_types.GenerateContentConfig:
    system = _build_system_prompt(ctx)
    return genai_types.GenerateContentConfig(
        system_instruction=system,
        temperature=0.8,
        top_p=0.95,
        max_output_tokens=400,
        thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
    )


async def future_self_reply_stream(
    uid: str,
    user_message: str,
    *,
    rag_query_embedding: list[float] | None = None,
    display_name: str | None = None,
    gender: Gender | None = None,
) -> AsyncIterator[str]:
    """Voice-optimised streaming variant of `future_self_reply`.

    Always runs with the fast preset (thinking_budget=0, max_output_tokens=400)
    because this path is only reachable from the LiveKit worker, where first-
    audio latency trumps full-reasoning quality.
    """
    snap = build_persona_snapshot(uid, display_name=display_name, gender=gender)
    rag_posts: list[dict] = []
    if rag_query_embedding:
        try:
            rag_posts = memstore.semantic_posts(uid, rag_query_embedding, k=5)
        except Exception as exc:  # noqa: BLE001
            logger.warning("semantic_posts failed (%s); proceeding without RAG", exc)

    config = _fast_voice_config(
        _PromptContext(snap=snap, user_message=user_message, rag_posts=rag_posts)
    )
    async for delta in generate_stream_with_fallback("chat", user_message, config=config):
        yield delta
