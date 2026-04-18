"""REST routers for jutra."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from jutra.agents.onboarding import onboarding_turn, start_onboarding
from jutra.api.auth import require_api_bearer
from jutra.api.schemas import (
    ChatRequest,
    IngestTextRequest,
    OnboardingStartRequest,
    OnboardingTurnRequest,
    SeedRequest,
)
from jutra.memory import store as memstore
from jutra.memory.models import UserProfile
from jutra.personas.ocean import Ocean
from jutra.safety.crisis import detect_crisis
from jutra.services.chat import chat_with_future_self
from jutra.services.ingestion import ingest_export, ingest_text
from jutra.services.personas import (
    get_chronicle,
    list_horizons,
    persona_snapshot,
)

router = APIRouter(dependencies=[Depends(require_api_bearer)])


@router.get("/horizons")
def horizons() -> dict:
    return {"horizons": list_horizons()}


@router.post("/admin/seed", status_code=status.HTTP_201_CREATED)
def admin_seed(req: SeedRequest) -> dict:
    memstore.upsert_user(
        UserProfile(
            uid=req.uid,
            display_name=req.display_name,
            base_age=req.base_age,
            ocean_t=Ocean().as_dict(),
        )
    )
    return {"ok": True, "uid": req.uid}


@router.get("/users/{uid}/persona/{delta}")
def get_persona(uid: str, delta: int) -> dict:
    try:
        return persona_snapshot(uid, delta)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/users/{uid}/chronicle")
def chronicle(uid: str, limit: int = 50) -> dict:
    return get_chronicle(uid, limit=limit)


@router.post("/users/{uid}/ingest/text")
def ingest_text_endpoint(uid: str, req: IngestTextRequest) -> dict:
    return ingest_text(uid, req.posts, platform=req.platform)


@router.post("/users/{uid}/ingest/export")
async def ingest_export_endpoint(uid: str, file: UploadFile) -> dict:
    raw = (await file.read()).decode("utf-8", errors="replace")
    filename = file.filename or "upload"
    try:
        return ingest_export(uid, filename, raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/users/{uid}/chat/{horizon}")
def chat_endpoint(uid: str, horizon: int, req: ChatRequest) -> dict:
    try:
        return chat_with_future_self(
            uid,
            horizon,
            req.message,
            display_name=req.display_name,
            use_rag=req.use_rag,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/onboarding/start")
def onboarding_start(req: OnboardingStartRequest) -> dict:
    sid, q = start_onboarding(req.uid)
    return {"session_id": sid, "question": q}


@router.post("/onboarding/turn")
def onboarding_turn_endpoint(req: OnboardingTurnRequest) -> dict:
    try:
        return onboarding_turn(req.session_id, req.message)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/safety/crisis-check")
def safety_crisis_check(req: ChatRequest) -> dict:
    v = detect_crisis(req.message)
    return {
        "is_crisis": v.is_crisis,
        "severity": v.severity,
        "reason": v.reason,
        "resources": v.resources,
    }
