"""save_turn_hook: extract and persist memories + chronicle notes after each chat turn.

Called from `chat_with_future_self` after the assistant reply is known so the
extractor can use (assistant, user) context for short confirmations.
"""

from __future__ import annotations

import json
import logging
import re

from google.genai import types as genai_types

from jutra.infra.vertex import generate_with_fallback
from jutra.memory import store as memstore
from jutra.memory.models import ChronicleTriple, MemoryItem
from jutra.memory.store import add_chronicle, add_memory, append_context_notes
from jutra.personas import riasec as riasec_mod

logger = logging.getLogger(__name__)

_SYSTEM = (
    "Ekstrahujesz strukturalne informacje z rozmowy: najpierw (jesli jest) "
    "ostatnia odpowiedz przyszlego ja, potem wypowiedz uzytkownika (po polsku).\n"
    "Odpowiedz TYLKO JSON-em wg schemy:\n"
    '{"facts": [{"text": "<krotko PL>", "topic": "'
    "values|plans|fears|relations|hobby|school|career|health|none"
    '"}], "notes": ["<krotka obserwacja kontekstowa PL>"], '
    '"values": ["<wartosc do Chronicle kind=value>"], '
    '"preferences": ["<preferencja do Chronicle kind=preference>"], '
    '"retractions": [{"kind": "value"|"preference", "object": "<tekst>"}], '
    '"commitments": [{"text": "<krotko>", "due_hint": "<opcjonalnie lub null>"}], '
    '"identity_facets": {"pronouns": "", "locality": "", "language": "", "school_or_work": ""}}\n'
    "Reguly:\n"
    '- "facts": co najwyzej 5 pozycji; pusty "text" lub topic "none" — pomin.\n'
    '- "notes": co najwyzej 3 krotkie linie (styl zycia, nastroj, kontekst).\n'
    '- "values" / "preferences": co najwyzej 3 kazda; tylko jasno wypowiedziane.\n'
    '- "retractions": tylko gdy uzytkownik cofa wczesniejsza wartosc/preferencje.\n'
    '- "commitments": max 2, tylko wyrazne postanowienia.\n'
    '- "identity_facets": uzupelnij pole tylko gdy uzytkownik podaje wprost; inaczej pusty string.\n'
    "Jesli wiadomosc jest czysto grzecznosciowa, zwroc puste listy.\n"
    "Stary format legacy {fact, topic} nadal obslugiwany."
)


def _as_str_list(val: object, cap: int) -> list[str]:
    if not isinstance(val, list):
        return []
    out: list[str] = []
    for x in val[:cap]:
        s = str(x).strip() if x is not None else ""
        if s:
            out.append(s)
    return out


def _as_fact_list(val: object, cap: int) -> list[dict[str, str]]:
    if not isinstance(val, list):
        return []
    out: list[dict[str, str]] = []
    for item in val[:cap]:
        if isinstance(item, dict):
            text = str(item.get("text", "")).strip()
            topic = str(item.get("topic", "none")).strip() or "none"
        else:
            continue
        if not text or topic.lower() == "none":
            continue
        out.append({"text": text, "topic": topic})
    return out


def _build_extractor_input(user_message: str, assistant_reply: str | None) -> str:
    if assistant_reply and assistant_reply.strip():
        return (
            "Ostatnia odpowiedz przyszlego ja:\n"
            f"{assistant_reply.strip()[:2000]}\n\n"
            "Wypowiedz uzytkownika:\n"
            f"{user_message.strip()[:2000]}"
        )
    return user_message.strip()


def extract_and_save(
    uid: str,
    user_message: str,
    *,
    assistant_reply: str | None = None,
) -> str | None:
    """Persist extracted data; return last Firestore id touched, else None."""
    payload = _build_extractor_input(user_message, assistant_reply)
    config = genai_types.GenerateContentConfig(
        system_instruction=_SYSTEM,
        temperature=0.1,
        response_mime_type="application/json",
        max_output_tokens=512,
    )
    try:
        resp = generate_with_fallback("extract", payload, config=config)
        raw = resp.text or "{}"
        data = json.loads(re.sub(r"```json|```", "", raw).strip() or "{}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("save_turn extraction failed: %s", exc, exc_info=False)
        return None

    last_id: str | None = None

    facts_list = _as_fact_list(data.get("facts"), 5)
    if not facts_list:
        legacy_fact = str(data.get("fact", "")).strip()
        if legacy_fact and legacy_fact.lower() != "none":
            topic = str(data.get("topic", "none")).strip() or "none"
            last_id = add_memory(
                uid,
                MemoryItem(text=legacy_fact, topic=topic, source="chat"),
            )

    for fact in facts_list:
        last_id = add_memory(
            uid,
            MemoryItem(
                text=fact["text"],
                topic=fact["topic"],
                source="chat",
            ),
        )

    for v in _as_str_list(data.get("values"), 3):
        last_id = add_chronicle(
            uid,
            ChronicleTriple(
                subject=uid,
                predicate="ceni",
                object=v,
                kind="value",
                weight=0.75,
                source="chat",
            ),
        )

    for p in _as_str_list(data.get("preferences"), 3):
        last_id = add_chronicle(
            uid,
            ChronicleTriple(
                subject=uid,
                predicate="lubi",
                object=p,
                kind="preference",
                weight=0.65,
                source="chat",
            ),
        )

    retr = data.get("retractions") or []
    if isinstance(retr, list):
        for item in retr[:5]:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", "")).strip().lower()
            obj = str(item.get("object", "")).strip()
            if kind in ("value", "preference") and obj:
                memstore.revoke_chronicle(uid, kind, obj)

    commits = data.get("commitments") or []
    if isinstance(commits, list):
        for c in commits[:2]:
            if not isinstance(c, dict):
                continue
            txt = str(c.get("text", "")).strip()
            if not txt:
                continue
            dh_raw = c.get("due_hint")
            dh = str(dh_raw).strip() if dh_raw not in (None, "") else None
            last_id = add_memory(
                uid,
                MemoryItem(
                    text=txt,
                    topic="commitment",
                    source="chat",
                    due_hint=dh,
                ),
            )

    facets_raw = data.get("identity_facets")
    if isinstance(facets_raw, dict):
        facet_map: dict[str, str] = {}
        for k in ("pronouns", "locality", "language", "school_or_work"):
            v = facets_raw.get(k)
            if v is not None and str(v).strip():
                facet_map[k] = str(v).strip()
        if facet_map:
            memstore.merge_identity_facets(uid, facet_map)

    notes = _as_str_list(data.get("notes"), 3)
    if notes:
        append_context_notes(uid, notes)

    try:
        riasec_mod.refresh_riasec_from_chat(uid, user_message)
    except Exception as exc:  # noqa: BLE001
        logger.warning("riasec refresh skipped: %s", exc)

    # Adaptive speaking-style refresh (every 3 new user turns vs last snapshot).
    try:
        from jutra.agents import style as style_mod

        n = memstore.count_user_chat_turns(uid)
        u = memstore.get_user(uid)
        last = u.style_turn_count if u else 0
        if n - last >= 3:
            style_mod.refresh_user_style(uid)
    except Exception as exc:  # noqa: BLE001
        logger.warning("style refresh skipped: %s", exc, exc_info=False)

    return last_id
