"""Vertex AI Imagen photo aging service.

Uses `imagen-3.0-capability-001` in *subject customization* mode so that the
person's identity is preserved (via `SubjectReferenceImage` with
`SUBJECT_TYPE_PERSON`) while still letting the model re-render the face with
real aging changes. We deliberately do NOT add a `FACE_MESH` control image
here — a face mesh pins facial geometry so tightly that the model can't add
wrinkles, jowls, volume loss or hairline changes, which is exactly what we
want Imagen to apply.

We render a single "slightly older me" photo at a fixed +10 years delta.
The prompt describes aging with concrete biological markers (hair grey
fraction, specific wrinkle locations, skin elasticity changes) and references
the subject as [1] per the Vertex customization prompt convention.
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

AGED_DELTA_YEARS: int = 10

_PROMPT_VERSION = "2026-04-18.v4-single10"

# Shared scaffolding — every prompt references [1] (the subject photo).
_IDENTITY_LOCK = (
    "A photorealistic color portrait photograph of [1], the same individual "
    "from the reference image, naturally aged. "
    "Preserve identity: keep the same eye color, eye shape, iris pattern, "
    "eyebrow arch, nose bridge, lip shape, jaw and cheekbone structure, "
    "ethnicity, and skin undertone. It must clearly be the same person "
    "recognisable from the reference. "
    "Re-render all aging surfaces: skin texture and elasticity, hair color "
    "and density, facial volume distribution, and the specific age spots, "
    "lines, wrinkles, and folds described below MUST be visibly and "
    "dramatically applied — do not soften them. "
    "Output a natural photograph, not an illustration or 3D render. "
)

_AGING_PLUS_10 = (
    "Aged roughly ten years older than the reference. "
    "Show clear soft crow's-feet at the outer eye corners at rest, a "
    "shallow horizontal forehead line, a faint nasolabial fold beginning "
    "to form, slightly thinner under-eye skin, and a noticeable loss of "
    "skin dewiness. A visible sparse cluster of grey strands appears at "
    "the temples (approximately five percent of the hair). Lips a touch "
    "thinner than the reference."
)

_NEGATIVE_PROMPT = (
    "different person, face swap, identity change, younger than reference, "
    "child, baby, cartoon, illustration, anime, painting, 3d render, cgi, "
    "plastic skin, airbrushed, beauty filter, heavy makeup, makeup change, "
    "different ethnicity, different eye color, "
    "watermark, caption, text, logo, nsfw, cropped, blurred, low resolution, "
    "duplicate face, extra limbs, distorted anatomy, lens flare, heavy grain."
)

# Deterministic seed — same input photo always yields the same aged photo so
# regression debugging stays sane.
_SEED = 10_010


@lru_cache(maxsize=1)
def _image_client() -> genai.Client:
    s = get_settings()
    return genai.Client(
        vertexai=True,
        project=s.google_cloud_project,
        location=s.image_location,
    )


def _build_references(image_bytes: bytes) -> list:
    """Single subject reference — lets Imagen re-render aging while keeping identity."""
    return [
        genai_types.SubjectReferenceImage(
            reference_id=1,
            reference_image=genai_types.Image(image_bytes=image_bytes),
            config=genai_types.SubjectReferenceConfig(
                subject_type=genai_types.SubjectReferenceType.SUBJECT_TYPE_PERSON,
                subject_description="the person in the reference photograph",
            ),
        ),
    ]


async def age_photo_once(image_bytes: bytes) -> bytes:
    """Generate one aged version (+10 years) with identity preserved."""
    client = _image_client()
    prompt = _IDENTITY_LOCK + _AGING_PLUS_10
    t0 = time.perf_counter()
    logger.info(
        "imagen.age_photo_once start delta=%d seed=%d prompt_version=%s",
        AGED_DELTA_YEARS, _SEED, _PROMPT_VERSION,
    )
    response = await asyncio.to_thread(
        client.models.edit_image,
        model="imagen-3.0-capability-001",
        prompt=prompt,
        reference_images=_build_references(image_bytes),
        config=genai_types.EditImageConfig(
            edit_mode=genai_types.EditMode.EDIT_MODE_DEFAULT,
            number_of_images=1,
            seed=_SEED,
            negative_prompt=_NEGATIVE_PROMPT,
            # Lower guidance gives the model more freedom to apply aging
            # markers; values above ~10 tend to collapse toward a near-
            # identical copy of the input, suppressing visible aging.
            guidance_scale=7.0,
            person_generation=genai_types.PersonGeneration.ALLOW_ADULT,
            output_mime_type="image/jpeg",
            output_compression_quality=90,
            include_rai_reason=True,
        ),
    )
    dt = time.perf_counter() - t0
    logger.info(
        "imagen.age_photo_once done delta=%d seed=%d took_s=%.2f",
        AGED_DELTA_YEARS, _SEED, dt,
    )
    return response.generated_images[0].image.image_bytes  # type: ignore[index]
