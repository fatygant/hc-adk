"""Summarize a voice/chat session and persist an arc Chronicle row."""

from __future__ import annotations

import json
import logging
import re

from google.genai import types as genai_types

from jutra.infra.vertex import generate_with_fallback
from jutra.memory import store as memstore
from jutra.memory.models import ChronicleTriple, MemoryItem

logger = logging.getLogger(__name__)

_SYSTEM = (
    "Masz ostatnia rozmowe uzytkownika z symulacja przyszlego ja (role user/assistant). "
    "Zwroc TYLKO JSON:\n"
    '{"arc_summary": "<3-5 zdan po polsku, druga osoba: co bylo wazne>", '
    '"commitments": [{"text": "<krotko>", "due_hint": "<opcjonalnie>"}]}\n'
    "commitments: max 2, tylko jesli uzytkownik wyraznie cos postanowil. "
    "arc_summary musi byc konkretny, bez moralizowania."
)


def close_session_and_summarize(uid: str, *, chat_limit: int = 20) -> dict:
    """Read recent chat_log, produce arc summary + optional commitments."""
    turns = memstore.recent_chat_turns(uid, limit=chat_limit)
    if not turns:
        return {"ok": True, "arc": False, "reason": "empty_chat"}

    lines: list[str] = []
    for t in turns:
        role = (t.get("role") or "").strip()
        text = (t.get("text") or "").strip().replace("\n", " ")
        if not text:
            continue
        label = "Uzytkownik" if role == "user" else "Przyszle_ja"
        lines.append(f"{label}: {text[:500]}")
    transcript = "\n".join(lines)
    if len(transcript) < 20:
        return {"ok": True, "arc": False, "reason": "too_short"}

    config = genai_types.GenerateContentConfig(
        system_instruction=_SYSTEM,
        temperature=0.35,
        response_mime_type="application/json",
        max_output_tokens=700,
    )
    try:
        resp = generate_with_fallback(
            "extract",
            f"Transkrypt rozmowy:\n\n{transcript}",
            config=config,
        )
        raw = resp.text or "{}"
        data = json.loads(re.sub(r"```json|```", "", raw).strip() or "{}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("session close LLM failed: %s", exc)
        return {"ok": False, "error": str(exc)}

    arc_text = str(data.get("arc_summary", "")).strip()
    if arc_text:
        memstore.add_chronicle(
            uid,
            ChronicleTriple(
                subject=uid,
                predicate="w_sesji",
                object=arc_text[:1800],
                kind="arc",
                weight=1.0,
                source="session",
            ),
        )
    for c in data.get("commitments") or []:
        if not isinstance(c, dict):
            continue
        txt = str(c.get("text", "")).strip()
        if not txt:
            continue
        dh = str(c.get("due_hint", "") or "").strip() or None
        memstore.add_memory(
            uid,
            MemoryItem(text=txt, topic="commitment", source="session_close", due_hint=dh),
        )

    return {"ok": True, "arc": bool(arc_text), "commitments": len(data.get("commitments") or [])}


def cold_open_line(uid: str) -> str:
    """One short line for voice greeting follow-up from arcs/commitments."""
    arcs = memstore.list_recent_arcs(uid, limit=1)
    if arcs:
        t = (arcs[0].get("object") or "").strip()
        if t:
            return f"Myślałem o naszej ostatniej rozmowie — {t[:160]}"
    comm = memstore.list_open_commitments(uid, limit=1)
    if comm:
        tx = (comm[0].get("text") or "").strip()
        if tx:
            return f"Wracam do tego, co mówiłeś: {tx[:120]} — jak poszło?"
    return ""
