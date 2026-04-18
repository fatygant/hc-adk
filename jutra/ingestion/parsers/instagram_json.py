"""Parser for Instagram `posts_*.json` files from the GDPR export.

The format is a JSON array where each entry has `media[*].title` and optional
top-level `title` plus a `taken_at` unix timestamp:
    [
      {"media": [{"title": "caption", "creation_timestamp": 1710000000}], "title": "..."},
      ...
    ]
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class ParsedInstagramPost:
    created_at: str
    text: str


def parse_instagram_json(raw: str, *, limit: int = 50) -> list[ParsedInstagramPost]:
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("posts_*.json must be a JSON array")
    out: list[ParsedInstagramPost] = []
    for entry in data:
        media = entry.get("media") or []
        text = (entry.get("title") or "").strip()
        ts = entry.get("creation_timestamp")
        for m in media:
            if not text:
                text = (m.get("title") or "").strip()
            if ts is None:
                ts = m.get("creation_timestamp")
        if not text:
            continue
        when = _fmt_ts(ts)
        out.append(ParsedInstagramPost(created_at=when, text=text))
        if len(out) >= limit:
            break
    return out


def _fmt_ts(ts: int | float | None) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(int(ts), tz=UTC).isoformat()
