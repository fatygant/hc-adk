"""Vertex AI Imagen photo aging service.

Uses `imagen-3.0-capability-001` in *subject customization* mode so that the
person's identity is preserved (via `SubjectReferenceImage` with
`SUBJECT_TYPE_PERSON`) while still letting the model re-render the face with
real aging changes. We deliberately do NOT add a `FACE_MESH` control image
here — a face mesh pins facial geometry so tightly that the model can't add
wrinkles, jowls, volume loss or hairline changes, which is exactly what we
want Imagen to apply.

Each horizon gets a deterministic seed so repeated generations for the same
photo+horizon are stable. Prompts describe aging with concrete biological
markers (hair grey fraction, specific wrinkle locations, skin elasticity
changes) and reference the subject as [1] per the Vertex customization
prompt convention.
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

_PROMPT_VERSION = "2026-04-18.v4"

# Shared scaffolding — every prompt references [1] (the subject photo).
# We preserve *identity* (who the person is: eyes, ethnicity, bone structure)
# but explicitly grant freedom on pose, clothing, background, and all aging
# surfaces so each horizon looks unmistakably different.
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

# Horizon-specific aging markers with distinct poses and settings so each
# result is obviously different from every other horizon.
_AGING: dict[int, str] = {
    5: (
        "Aged roughly five years older than the reference. "
        "Show faint fine lines at the outer corners of the eyes, clearly "
        "visible at rest. Skin is slightly less dewy and a touch less uniform "
        "in tone. No grey hair yet. The change is subtle but must be visible "
        "compared to the reference. "
        "Pose: slight three-quarter turn, relaxed neutral expression. "
        "Setting: bright natural daylight, plain light background, "
        "casual everyday clothing."
    ),
    10: (
        "Aged roughly ten years older than the reference. "
        "Show clear soft crow's-feet at the outer eye corners at rest, a "
        "shallow horizontal forehead line, a faint nasolabial fold beginning "
        "to form, slightly thinner under-eye skin, and noticeable loss of "
        "skin dewiness. A visible sparse cluster of grey strands at the "
        "temples (approximately five percent of the hair). Lips a touch "
        "thinner than the reference. "
        "Pose: direct front-facing, calm expression. "
        "Setting: warm indoor light, blurred neutral background, "
        "smart-casual clothing."
    ),
    20: (
        "Aged roughly twenty years older than the reference. "
        "Show obvious crow's-feet at rest, a permanent shallow forehead line "
        "plus one faint glabellar line between the brows, defined nasolabial "
        "folds, mild under-eye bags with slight hollowing, thinner lips, "
        "early jowl formation, and approximately thirty to forty-five percent "
        "grey hair spreading from the temples toward the crown. Add several "
        "sun spots on the cheeks and one horizontal crease on the neck. "
        "This must read unmistakably as a middle-aged version of the "
        "reference — the aging changes must be obvious. "
        "Pose: relaxed slight side profile, thoughtful expression. "
        "Setting: soft afternoon indoor light, comfortable casual clothing "
        "appropriate for a person in their forties or fifties."
    ),
    30: (
        "Aged roughly thirty years older than the reference. "
        "Show deep crow's-feet, deep permanent forehead lines, visible "
        "glabellar furrows, deep nasolabial folds, marionette lines at the "
        "mouth corners, hooded upper eyelids, under-eye bags, pronounced "
        "jowls, clear loss of mid-face volume, distinctly thinner lips, and "
        "seventy-five to one-hundred percent grey or silver hair on a "
        "noticeably thinner hairline. Add multiple age spots on cheeks, "
        "temples, and forehead, horizontal neck wrinkles, crepey neck skin, "
        "and sparser eyebrows. The subject must look clearly elderly — "
        "unmistakably three decades older than the reference. "
        "Pose: relaxed seated posture, gentle warm expression. "
        "Setting: cozy warm indoor light, comfortable loose clothing "
        "appropriate for an elderly person."
    ),
}

_NEGATIVE_PROMPT = (
    "different person, face swap, identity change, younger than reference, "
    "child, baby, cartoon, illustration, anime, painting, 3d render, cgi, "
    "plastic skin, airbrushed, beauty filter, heavy makeup, makeup change, "
    "different ethnicity, different eye color, "
    "watermark, caption, text, logo, nsfw, cropped, blurred, low resolution, "
    "duplicate face, extra limbs, distorted anatomy, lens flare, heavy grain."
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
