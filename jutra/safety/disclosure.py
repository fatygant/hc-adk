"""AI Act style disclosure prefix for every chat_with_future_self reply."""

from __future__ import annotations

from jutra.settings import get_settings


def prefix_with_disclosure(response: str) -> str:
    settings = get_settings()
    return f"[{settings.ai_disclosure_pl}]\n\n{response.strip()}"
