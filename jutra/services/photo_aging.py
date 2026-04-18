"""Vertex AI Imagen photo aging service (Nano Banana / imagen-3.0-capability-001)."""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from google import genai
from google.genai import types as genai_types

from jutra.settings import get_settings

logger = logging.getLogger(__name__)

HORIZONS: list[int] = [5, 10, 20, 30]

_PROMPTS: dict[int, str] = {
    5: (
        "Realistically age this person by exactly 5 years. "
        "Preserve exact identity, facial structure, pose, background, clothing. "
        "Add only subtle aging: faint crow's feet, very slightly less vibrant skin tone. "
        "Photorealistic portrait, same lighting."
    ),
    10: (
        "Realistically age this person by exactly 10 years. "
        "Preserve exact identity, facial structure, pose, background, clothing. "
        "Natural aging: light forehead wrinkles, slight eye lines, slightly graying hair at temples, "
        "mature skin texture. Photorealistic portrait, same lighting."
    ),
    20: (
        "Realistically age this person by exactly 20 years. "
        "Preserve exact identity, facial structure, pose, background, clothing. "
        "Visible aging: deeper facial wrinkles, graying or silver hair, age spots, "
        "skin texture changes, slightly thinner lips. Photorealistic portrait, same lighting."
    ),
    30: (
        "Realistically age this person by exactly 30 years. "
        "Preserve exact identity, facial structure, pose, background, clothing. "
        "Advanced aging: deep wrinkles, mostly gray or white hair, significant skin texture changes, "
        "jowls, elderly features. Photorealistic portrait, same lighting."
    ),
}


@lru_cache(maxsize=1)
def _image_client() -> genai.Client:
    s = get_settings()
    return genai.Client(vertexai=True, project=s.google_cloud_project, location=s.image_location)


async def age_photo(image_bytes: bytes, years: int) -> bytes:
    """Generate one aged version using Imagen edit_image."""
    client = _image_client()
    response = await asyncio.to_thread(
        client.models.edit_image,
        model="imagen-3.0-capability-001",
        prompt=_PROMPTS[years],
        reference_images=[
            genai_types.RawReferenceImage(
                reference_id=1,
                reference_image=genai_types.Image(image_bytes=image_bytes),
            )
        ],
        config=genai_types.EditImageConfig(
            number_of_images=1,
            output_mime_type="image/jpeg",
        ),
    )
    return response.generated_images[0].image.image_bytes  # type: ignore[index]


async def age_all_horizons(image_bytes: bytes) -> dict[int, bytes]:
    """Generate aged versions for all 4 horizons in parallel."""
    results = await asyncio.gather(
        *[age_photo(image_bytes, h) for h in HORIZONS],
        return_exceptions=True,
    )
    out: dict[int, bytes] = {}
    for horizon, result in zip(HORIZONS, results):
        if isinstance(result, Exception):
            logger.error("Aging failed +%d years: %s", horizon, result)
            raise result
        out[horizon] = result  # type: ignore[assignment]
    return out
