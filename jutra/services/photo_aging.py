"""Vertex AI Imagen photo aging service.

Uses `imagen-3.0-capability-001` in *customization* mode so that identity is
preserved (via `SubjectReferenceImage` with `SUBJECT_TYPE_PERSON`) and pose /
facial geometry is anchored (via `ControlReferenceImage` with
`CONTROL_TYPE_FACE_MESH`). Each horizon gets a deterministic seed so repeated
generations for the same photo+horizon are stable.

Prompts describe aging with concrete biological markers (hair grey fraction,
specific wrinkle locations, skin elasticity changes) instead of vague
qualifiers like "subtle" or "advanced" — this is what was making the aging
look random and horizon-agnostic before.
"""

from __future__ import annotations

import asyncio
import logging
import time
from functools import lru_cache

from google import genai
from google.genai import types as genai_types

from jutra.settings import get_settings

logger = logging.getLogger(__name__)

HORIZONS: list[int] = [5, 10, 20, 30]

_PROMPT_VERSION = "2026-04-18.v2"

# Shared scaffolding — every prompt references [1] (the subject photo) and
# [2] (the face-mesh control). The model is instructed to keep identity and
# geometry constant and to apply only the listed aging changes.
_IDENTITY_LOCK = (
    "A photorealistic color portrait photograph of the same person [1], "
    "rendered with the exact pose and facial geometry from [2]. "
    "Identity is locked: preserve the exact eye color, eye shape, iris pattern, "
    "eyebrow shape, nose shape, lip shape, jaw and cheekbone structure, "
    "ethnicity, skin undertone, ear shape, and hairline. "
    "Keep the same camera angle, framing, crop, background, clothing, and "
    "lighting as the reference. Do not restyle the image — keep it a natural "
    "photograph, not an illustration. "
)

# Horizon-specific aging markers — concrete and progressive so each horizon
# produces a visibly different result.
_AGING: dict[int, str] = {
    5: (
        "Age the subject by 5 years. Apply only these changes: "
        "very faint lines at the outer corners of the eyes visible only on "
        "slight expression; skin loses a touch of dewiness and becomes "
        "marginally less uniform in tone; lips remain full; the hairline is "
        "unchanged; no gray hair yet. The person should still read as the "
        "same age bracket, just slightly past the reference. The difference "
        "must be subtle but clearly visible when compared side-by-side."
    ),
    10: (
        "Age the subject by 10 years. Apply only these changes: "
        "soft crow's-feet at the outer eye corners even at rest; the first "
        "shallow horizontal line on the forehead appears only on expression; "
        "very faint nasolabial fold becoming visible; under-eye skin looks "
        "slightly thinner; skin tone a little less uniform, with a hint of "
        "warmth lost; a sparse cluster of grey strands starts at the temples "
        "(around 3-5 percent of hair); lip volume marginally reduced. "
        "The person must read as the same individual, one decade older."
    ),
    20: (
        "Age the subject by 20 years. Apply only these changes: "
        "clearly visible crow's-feet at rest; a permanent shallow forehead "
        "line and one faint line between the brows; defined nasolabial folds; "
        "mild under-eye bags and slight hollowing; lips thinner with a less "
        "defined cupid's bow; early jowl formation along the jawline; "
        "approximately 30 to 45 percent grey hair, starting at the temples "
        "and spreading to the crown; a few small sun spots on the cheeks or "
        "temples; the neck shows one horizontal crease. "
        "The person must read as the same individual, two decades older."
    ),
    30: (
        "Age the subject by 30 years. Apply only these changes: "
        "deep crow's-feet and permanent forehead lines; visible glabellar "
        "lines between the brows; deep nasolabial folds and developing "
        "marionette lines at the mouth corners; hooded upper eyelids and "
        "under-eye bags; pronounced jowls with a softened jawline; loss of "
        "mid-face volume; lips clearly thinner and less defined; "
        "approximately 75 to 100 percent grey or silver hair with a thinner "
        "hairline; several age spots distributed on cheeks, temples, and "
        "forehead; visible horizontal neck wrinkles and mild crepey neck "
        "skin; eyebrows slightly sparser. "
        "The person must read as the same individual, three decades older."
    ),
}

_NEGATIVE_PROMPT = (
    "different person, face swap, identity change, younger than reference, "
    "child, baby, cartoon, illustration, anime, painting, 3d render, cgi, "
    "plastic skin, airbrushed, beauty filter, heavy makeup, makeup change, "
    "different ethnicity, different eye color, different hair color baseline, "
    "different hairstyle, different pose, different camera angle, "
    "different framing, different background, different clothing, watermark, "
    "caption, text, logo, nsfw, cropped, blurred, low resolution, duplicate "
    "face, extra limbs, distorted anatomy, lens flare, heavy grain."
)

# Deterministic seed per horizon — lets us reproduce a given aged photo
# exactly and makes regression debugging easier.
_SEEDS: dict[int, int] = {5: 10_005, 10: 10_010, 20: 10_020, 30: 10_030}


def _prompt_for(years: int) -> str:
    return _IDENTITY_LOCK + _AGING[years]


@lru_cache(maxsize=1)
def _image_client() -> genai.Client:
    s = get_settings()
    return genai.Client(
        vertexai=True,
        project=s.google_cloud_project,
        location=s.image_location,
    )


def _build_references(image_bytes: bytes) -> list:
    """Subject + face-mesh control references for identity-preserving editing."""
    src = genai_types.Image(image_bytes=image_bytes)
    return [
        genai_types.SubjectReferenceImage(
            reference_id=1,
            reference_image=src,
            config=genai_types.SubjectReferenceConfig(
                subject_type=genai_types.SubjectReferenceType.SUBJECT_TYPE_PERSON,
                subject_description="the person in the uploaded photo",
            ),
        ),
        genai_types.ControlReferenceImage(
            reference_id=2,
            reference_image=src,
            config=genai_types.ControlReferenceConfig(
                control_type=genai_types.ControlReferenceType.CONTROL_TYPE_FACE_MESH,
                enable_control_image_computation=True,
            ),
        ),
    ]


async def age_photo(image_bytes: bytes, years: int) -> bytes:
    """Generate one aged version with identity preserved."""
    client = _image_client()
    prompt = _prompt_for(years)
    seed = _SEEDS[years]
    t0 = time.perf_counter()
    logger.info(
        "imagen.age_photo start years=%d seed=%d prompt_version=%s",
        years, seed, _PROMPT_VERSION,
    )
    response = await asyncio.to_thread(
        client.models.edit_image,
        model="imagen-3.0-capability-001",
        prompt=prompt,
        reference_images=_build_references(image_bytes),
        config=genai_types.EditImageConfig(
            edit_mode=genai_types.EditMode.EDIT_MODE_DEFAULT,
            number_of_images=1,
            seed=seed,
            negative_prompt=_NEGATIVE_PROMPT,
            guidance_scale=24.0,
            person_generation=genai_types.PersonGeneration.ALLOW_ADULT,
            output_mime_type="image/jpeg",
            output_compression_quality=90,
        ),
    )
    dt = time.perf_counter() - t0
    logger.info("imagen.age_photo done years=%d seed=%d took_s=%.2f", years, seed, dt)
    return response.generated_images[0].image.image_bytes  # type: ignore[index]


async def age_all_horizons(image_bytes: bytes) -> dict[int, bytes]:
    """Generate aged versions for all horizons in parallel."""
    t0 = time.perf_counter()
    logger.info(
        "imagen.age_all_horizons start horizons=%s prompt_version=%s",
        HORIZONS, _PROMPT_VERSION,
    )
    results = await asyncio.gather(
        *[age_photo(image_bytes, h) for h in HORIZONS],
        return_exceptions=True,
    )
    out: dict[int, bytes] = {}
    for horizon, result in zip(HORIZONS, results, strict=True):
        if isinstance(result, Exception):
            logger.error("imagen.age_all_horizons failed +%d years: %s", horizon, result)
            raise result
        out[horizon] = result  # type: ignore[assignment]
    logger.info(
        "imagen.age_all_horizons done horizons=%s total_s=%.2f",
        HORIZONS, time.perf_counter() - t0,
    )
    return out
