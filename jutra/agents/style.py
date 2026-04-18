"""Distill the user's speaking style from chat_log for FutureSelf prompt injection."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

from google.genai import types as genai_types

from jutra.agents.prompts import load as load_prompt
from jutra.infra.vertex import generate_with_fallback
from jutra.memory import store as memstore

logger = logging.getLogger(__name__)


def _user_message_texts(uid: str, window: int) -> list[str]:
    rows = memstore.recent_chat_turns(uid, limit=64)
    texts: list[str] = []
    for r in rows:
        if (r.get("role") or "") != "user":
            continue
        t = (r.get("text") or "").strip()
        if t:
            texts.append(t)
    return texts[-window:] if window else texts


def refresh_user_style(uid: str, *, min_user_turns: int = 3, window: int = 20) -> dict | None:
    """Recompute style_profile from recent user lines; persist if enough data."""
    n = memstore.count_user_chat_turns(uid)
    if n < min_user_turns:
        return None

    texts = _user_message_texts(uid, window=window)
    if len(texts) < min_user_turns:
        return None

    corpus = "\n---\n".join(texts)
    system = load_prompt("style")
    config = genai_types.GenerateContentConfig(
        system_instruction=system,
        temperature=0.15,
        response_mime_type="application/json",
        max_output_tokens=512,
    )
    try:
        resp = generate_with_fallback(
            "extract",
            f"Wiadomosci uzytkownika (oddzielone ---):\n\n{corpus}",
            config=config,
        )
        raw = resp.text or "{}"
        data = json.loads(re.sub(r"```json|```", "", raw).strip() or "{}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("refresh_user_style LLM/JSON failed for %s: %s", uid, exc)
        return None

    if not isinstance(data, dict):
        return None

    data = dict(data)
    data["updated_at"] = datetime.now(UTC).isoformat()

    memstore.set_user_style_state(uid, data, memstore.count_user_chat_turns(uid))
    return data
