"""Social media ingestion (text + GDPR exports)."""

from __future__ import annotations

from jutra.ingestion.parsers.instagram_json import parse_instagram_json
from jutra.ingestion.parsers.twitter_archive import parse_twitter_archive
from jutra.ingestion.pipeline import IngestResult, text_ingest


def ingest_text(uid: str, posts: list[str], platform: str = "manual") -> dict:
    result: IngestResult = text_ingest(uid, posts, platform=platform)
    return {
        "uid": uid,
        "platform": platform,
        "ingested": result.ingested,
        "skipped": result.skipped,
        "top_themes": result.top_themes,
        "ocean_t": result.updated_ocean,
    }


def ingest_export(uid: str, filename: str, raw: str) -> dict:
    """Dispatch by filename: tweets.js -> twitter, posts_*.json -> instagram."""
    lower = filename.lower()
    if lower.endswith(".js") and "tweet" in lower:
        posts = [p.text for p in parse_twitter_archive(raw, limit=50)]
        platform = "twitter"
    elif lower.endswith(".json"):
        posts = [p.text for p in parse_instagram_json(raw, limit=50)]
        platform = "instagram"
    else:
        raise ValueError(f"unknown export: {filename} (expected tweets.js or posts_*.json)")
    return ingest_text(uid, posts, platform=platform)
