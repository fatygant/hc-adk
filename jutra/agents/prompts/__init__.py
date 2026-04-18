"""Prompt loader (reads .md files next to this package)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


@lru_cache
def load(name: str) -> str:
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt not found: {name}")
    return path.read_text(encoding="utf-8")
