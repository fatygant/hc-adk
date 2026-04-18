"""Optional AI Act style disclosure prefix for chat replies.

`prefix_with_disclosure` is kept for optional re-enable (e.g. per-env); the
default `wrap_turn` path does not prepend it — product UI may carry disclosure
instead.
"""

from __future__ import annotations

from jutra.settings import get_settings


def prefix_with_disclosure(response: str) -> str:
    settings = get_settings()
    return f"[{settings.ai_disclosure_pl}]\n\n{response.strip()}"
