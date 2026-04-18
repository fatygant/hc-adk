"""Photo upload, aging status, and image serving endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import Response

from jutra.api.auth import require_api_bearer
from jutra.infra.gcs import download_bytes, upload_bytes
from jutra.memory import store as memstore
from jutra.services.photo_aging import age_photo_once

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_api_bearer)])

_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB


async def _run_aging(uid: str, image_bytes: bytes) -> None:
    try:
        aged_bytes = await age_photo_once(image_bytes)
        blob_name = f"{uid}/aged.jpg"
        upload_bytes(blob_name, aged_bytes, "image/jpeg")
        memstore.set_aged_photo_done(uid, blob_name)
        memstore.set_overall_photo_status(uid, "done")
        logger.info("Photo aging complete for %s", uid)
    except Exception:
        logger.exception("Photo aging failed for %s", uid)
        memstore.set_overall_photo_status(uid, "error")


@router.post("/users/{uid}/photo/upload", status_code=202)
async def upload_photo(
    uid: str,
    file: UploadFile,
    background_tasks: BackgroundTasks,
) -> dict:
    content_type = file.content_type or "image/jpeg"
    if content_type not in _ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported type: {content_type}")

    image_bytes = await file.read()
    if len(image_bytes) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 10 MB)")

    blob_name = f"{uid}/original.jpg"
    upload_bytes(blob_name, image_bytes, "image/jpeg")
    memstore.save_photo_original(uid, blob_name)

    background_tasks.add_task(_run_aging, uid, image_bytes)
    return {"status": "processing", "uid": uid}


@router.get("/users/{uid}/photo/status")
def photo_status(uid: str) -> dict:
    meta = memstore.get_photo_meta(uid)
    if not meta:
        return {"overall_status": "none", "aged": {"status": "pending"}}

    aged = meta.get("aged") or {}
    return {
        "overall_status": meta.get("overall_status", "none"),
        "aged": {
            "status": aged.get("status", "pending"),
            "gcs_path": aged.get("gcs_path", ""),
        },
    }


@router.get("/users/{uid}/photo/aged/image")
def get_aged_image(uid: str) -> Response:
    meta = memstore.get_photo_meta(uid)
    if not meta:
        raise HTTPException(status_code=404, detail="No photo for this user")

    aged_entry = meta.get("aged") or {}
    if aged_entry.get("status") != "done":
        raise HTTPException(status_code=404, detail="Aged photo not ready yet")

    blob_name = aged_entry.get("gcs_path", "")
    if not blob_name:
        raise HTTPException(status_code=404, detail="GCS path missing")

    try:
        data = download_bytes(blob_name)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to fetch image") from exc

    return Response(content=data, media_type="image/jpeg")


@router.get("/users/{uid}/photo/original/image")
def get_original_image(uid: str) -> Response:
    meta = memstore.get_photo_meta(uid)
    if not meta or not meta.get("original_gcs"):
        raise HTTPException(status_code=404, detail="No photo for this user")

    try:
        data = download_bytes(meta["original_gcs"])
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to fetch image") from exc

    return Response(content=data, media_type="image/jpeg")
