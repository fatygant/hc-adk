"""Vertex AI clients split across two regions.

Gemini 3 preview models only live in `global`; `text-embedding-005` lives in
`europe-west4`. We expose two long-lived clients and a helper that falls back to
`gemini-2.5-flash` (in `global`, also available) when a preview model is gone.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

from google import genai
from google.api_core import exceptions as gax
from google.genai import types as genai_types

from jutra.settings import get_settings

logger = logging.getLogger(__name__)

ModelKind = Literal["reasoning", "chat", "extract"]


@lru_cache
def llm_client() -> genai.Client:
    s = get_settings()
    return genai.Client(vertexai=True, project=s.google_cloud_project, location=s.llm_location)


@lru_cache
def embed_client() -> genai.Client:
    s = get_settings()
    return genai.Client(vertexai=True, project=s.google_cloud_project, location=s.embed_location)


def resolve_model(kind: ModelKind) -> str:
    """Return the configured model name for the given role."""
    s = get_settings()
    return {
        "reasoning": s.model_reasoning,
        "chat": s.model_chat,
        "extract": s.model_extract,
    }[kind]


def fallback_model() -> str:
    return get_settings().fallback_model


def generate_with_fallback(
    kind: ModelKind,
    contents: str | list,
    *,
    config: genai_types.GenerateContentConfig | None = None,
) -> genai_types.GenerateContentResponse:
    """Call Gemini 3 (preview) and fall back to 2.5-flash on NotFound/FailedPrecondition."""
    client = llm_client()
    model = resolve_model(kind)
    try:
        return client.models.generate_content(model=model, contents=contents, config=config)
    except (gax.NotFound, gax.FailedPrecondition) as exc:
        logger.warning(
            "Gemini 3 preview model %s unavailable (%s); falling back to %s",
            model,
            exc.__class__.__name__,
            fallback_model(),
        )
        return client.models.generate_content(
            model=fallback_model(), contents=contents, config=config
        )


def embed(texts: list[str]) -> list[list[float]]:
    """Return 768-dim embeddings for a batch of strings."""
    s = get_settings()
    resp = embed_client().models.embed_content(model=s.embed_model, contents=texts)
    return [e.values for e in resp.embeddings]
