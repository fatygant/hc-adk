"""Identity extraction agent: JSON-only output that feeds Chronicle."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from google.genai import types as genai_types

from jutra.agents.prompts import load as load_prompt
from jutra.infra.vertex import generate_with_fallback

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExtractionResult:
    values: list[dict] = field(default_factory=list)
    preferences: list[dict] = field(default_factory=list)
    facts: list[dict] = field(default_factory=list)
    fears: list[str] = field(default_factory=list)


def extract_identity(text: str) -> ExtractionResult:
    config = genai_types.GenerateContentConfig(
        system_instruction=load_prompt("extraction"),
        temperature=0.1,
        response_mime_type="application/json",
        max_output_tokens=400,
    )
    try:
        resp = generate_with_fallback("extract", text, config=config)
        raw = resp.text or "{}"
        data = json.loads(re.sub(r"```json|```", "", raw).strip() or "{}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("extract_identity failed: %s", exc)
        return ExtractionResult()
    return ExtractionResult(
        values=[
            {"object": str(v["object"]), "weight": float(v.get("weight", 0.7))}
            for v in data.get("values", [])
            if isinstance(v, dict) and v.get("object")
        ],
        preferences=[
            {"object": str(p["object"]), "weight": float(p.get("weight", 0.5))}
            for p in data.get("preferences", [])
            if isinstance(p, dict) and p.get("object")
        ],
        facts=[
            {
                "predicate": str(f.get("predicate", "ma")),
                "object": str(f["object"]),
                "weight": float(f.get("weight", 0.6)),
            }
            for f in data.get("facts", [])
            if isinstance(f, dict) and f.get("object")
        ],
        fears=[str(x) for x in data.get("fears", []) if x],
    )
