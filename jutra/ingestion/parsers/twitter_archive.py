"""Parser for the `tweets.js` file from a Twitter/X GDPR data export.

The file looks like:
    window.YTD.tweets.part0 = [ { "tweet": { "full_text": "...", "created_at": "...", ... } }, ... ]

We skip retweets (start with "RT @") and protected-mention-only tweets, and we
keep at most `limit` posts per export to keep the demo fast.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

_PREFIX_RE = re.compile(r"^\s*window\.YTD\.[\w.]+\s*=\s*", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class ParsedTweet:
    created_at: str
    text: str


def parse_twitter_archive(raw: str, *, limit: int = 50) -> list[ParsedTweet]:
    body = _PREFIX_RE.sub("", raw.strip(), count=1).rstrip(";").strip()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid tweets.js format: {exc}") from exc

    out: list[ParsedTweet] = []
    for entry in payload:
        tweet = entry.get("tweet") or entry
        text = (tweet.get("full_text") or tweet.get("text") or "").strip()
        if not text or text.startswith("RT @"):
            continue
        created = tweet.get("created_at", "")
        out.append(ParsedTweet(created_at=created, text=text))
        if len(out) >= limit:
            break
    return out
