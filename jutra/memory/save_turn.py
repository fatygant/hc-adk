"""save_turn_hook: extract and persist a short memory after each chat turn.

Called from `chat_with_future_self` (MCP tool) as a background task. Uses
`gemini-3.1-flash-lite-preview` (extract) to pull out at most one atomic fact
from the user turn and write it to `users/{uid}/memories`.
"""

from __future__ import annotations

import json
import logging
import re

from google.genai import types as genai_types

from jutra.infra.vertex import generate_with_fallback
from jutra.memory.models import MemoryItem
from jutra.memory.store import add_memory

logger = logging.getLogger(__name__)

_SYSTEM = (
    "Ekstrahujesz JEDEN najwazniejszy fakt osobowy z wiadomosci uzytkownika. "
    "Odpowiedz JSON-em wg schemy:\n"
    '{"fact": "<krotko, 1 zdanie PL; lub pusty string jesli brak nowego faktu>", '
    '"topic": "<jedno slowo: values|plans|fears|relations|hobby|school|career|health|none>"}\n'
    "Jesli wiadomosc nie wnosi nowego faktu (np. grzecznosciowa), wroc fact=''."
)


def extract_and_save(uid: str, user_message: str, *, horizon: int | None = None) -> str | None:
    """Return the memory id if something was stored, else None."""
    config = genai_types.GenerateContentConfig(
        system_instruction=_SYSTEM,
        temperature=0.1,
        response_mime_type="application/json",
        max_output_tokens=150,
    )
    try:
        resp = generate_with_fallback("extract", user_message, config=config)
        payload = resp.text or "{}"
        data = json.loads(re.sub(r"```json|```", "", payload).strip() or "{}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("save_turn extraction failed: %s", exc, exc_info=False)
        return None

    fact = str(data.get("fact", "")).strip()
    topic = str(data.get("topic", "none")).strip() or "none"
    if not fact or fact.lower() == "none":
        return None
    return add_memory(
        uid,
        MemoryItem(text=fact, topic=topic, source="chat", horizon=horizon),
    )
