"""Text ingestion pipeline: Parser -> Extractor -> Psychometrist.

Implemented as plain Python (not ADK SequentialAgent yet) so the MCP tools can
invoke it synchronously from a single Cloud Run request without spawning an
extra Runner. Extractor and Psychometrist share a single
`gemini-3.1-flash-lite-preview` call per post to keep the demo fast.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
from dataclasses import dataclass, field

from google.genai import types as genai_types

from jutra.infra.vertex import embed, generate_with_fallback
from jutra.memory import store as memstore
from jutra.memory.models import ChronicleTriple, SocialPost, UserProfile
from jutra.personas.ocean import Ocean, clip

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IngestResult:
    ingested: int
    skipped: int
    top_themes: list[str] = field(default_factory=list)
    updated_ocean: dict[str, float] = field(default_factory=dict)


_PARSE_SYSTEM = (
    "Jestes analitykiem tresci z mediow spolecznosciowych. "
    "Dla KAZDEGO postu zwroc JSON: "
    '{"themes":[str,...], "values":[str,...], '
    '"preferences":[str,...], '
    '"ocean_signals":{"O":float,"C":float,"E":float,"A":float,"N":float}}.\n'
    "Kazdy sygnal OCEAN to liczba w zakresie [-1.0, 1.0] wyrazajaca kierunek i sile "
    "(0 = brak sygnalu). Themes to 1-3 slowne etykiety po polsku. "
    "Values to wartosci zyciowe wyrazone w pierwszej osobie ('cenie wolnosc'). "
    "Preferences to lubienia/niechecia ('lubie jazz', 'nie lubie szkoly')."
)


def _parse_post_llm(text: str) -> dict:
    config = genai_types.GenerateContentConfig(
        system_instruction=_PARSE_SYSTEM,
        temperature=0.1,
        response_mime_type="application/json",
        max_output_tokens=300,
    )
    resp = generate_with_fallback("extract", text, config=config)
    raw = resp.text or "{}"
    cleaned = re.sub(r"```json|```", "", raw).strip() or "{}"
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("post LLM returned non-JSON: %s", cleaned[:80])
        return {}


def _apply_ocean_signals(
    current: dict[str, float], signals: dict[str, float], *, weight: float = 2.0
) -> dict[str, float]:
    """Nudge current OCEAN T-score by signal * weight (in T-score points)."""
    out = dict(current) if current else Ocean().as_dict()
    for trait, sig in signals.items():
        if trait not in out:
            continue
        try:
            delta = float(sig) * weight
        except (TypeError, ValueError):
            continue
        out[trait] = clip(out[trait] + delta)
    return out


def text_ingest(
    uid: str,
    raw_posts: list[str],
    platform: str = "twitter",
    *,
    embed_batch_size: int = 10,
) -> IngestResult:
    """Ingest a batch of post texts: extract signals, embed, write to Firestore.

    Updates the user's OCEAN profile based on cumulative per-post signals and
    writes each post (with embedding) + extracted values/preferences into the
    chronicle.
    """
    if not raw_posts:
        return IngestResult(ingested=0, skipped=0)

    user = memstore.get_user(uid) or UserProfile(uid=uid)
    ocean_state = dict(user.ocean_t) if user.ocean_t else Ocean().as_dict()

    accumulated_signals: dict[str, float] = dict.fromkeys("OCEAN", 0.0)
    accumulated_themes: dict[str, int] = {}
    ingested = 0
    skipped = 0

    # Batch embeddings; LLM analysis stays per-post (bounded by small demo set).
    embeddings: list[list[float]] = []
    for i in range(0, len(raw_posts), embed_batch_size):
        chunk = raw_posts[i : i + embed_batch_size]
        try:
            embeddings.extend(embed(chunk))
        except Exception as exc:  # noqa: BLE001
            logger.warning("embedding batch failed, skipping: %s", exc)
            embeddings.extend([[] for _ in chunk])

    for text, emb in zip(raw_posts, embeddings, strict=False):
        analysis = _parse_post_llm(text)
        themes = [str(t) for t in analysis.get("themes", []) if t][:3]
        values = [str(v) for v in analysis.get("values", []) if v][:5]
        preferences = [str(p) for p in analysis.get("preferences", []) if p][:5]
        signals = analysis.get("ocean_signals", {}) or {}

        if not themes and not values and not preferences and not signals:
            skipped += 1
            continue

        for t in themes:
            accumulated_themes[t] = accumulated_themes.get(t, 0) + 1
        for trait in "OCEAN":
            with contextlib.suppress(TypeError, ValueError):
                accumulated_signals[trait] += float(signals.get(trait, 0) or 0)

        memstore.add_post(
            uid,
            SocialPost(platform=platform, raw_text=text, themes=themes, embedding=emb),
        )
        for v in values:
            memstore.add_chronicle(
                uid,
                ChronicleTriple(
                    subject=uid,
                    predicate="ceni",
                    object=v,
                    kind="value",
                    weight=0.7,
                    source=platform,
                ),
            )
        for p in preferences:
            memstore.add_chronicle(
                uid,
                ChronicleTriple(
                    subject=uid,
                    predicate="lubi",
                    object=p,
                    kind="preference",
                    weight=0.5,
                    source=platform,
                ),
            )
        ingested += 1

    if ingested > 0:
        avg_signals = {k: v / ingested for k, v in accumulated_signals.items()}
        ocean_state = _apply_ocean_signals(ocean_state, avg_signals, weight=3.0)
        memstore.upsert_user(
            UserProfile(
                uid=uid,
                display_name=user.display_name,
                base_age=user.base_age,
                ocean_t=ocean_state,
                riasec_top3=user.riasec_top3,
            )
        )

    top_themes = [
        t for t, _ in sorted(accumulated_themes.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    ]

    return IngestResult(
        ingested=ingested,
        skipped=skipped,
        top_themes=top_themes,
        updated_ocean=ocean_state,
    )
