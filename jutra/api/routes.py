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
from jutra.personas.gender import infer_gender_pl
from jutra.personas.ocean import Ocean
from jutra.safety.crisis import detect_crisis
from jutra.services.chat import chat_with_future_self
from jutra.services.ingestion import ingest_export, ingest_text
from jutra.services.personas import (
    get_chronicle,
    persona_snapshot,
)
from jutra.services.session_close import close_session_and_summarize, cold_open_line

router = APIRouter(dependencies=[Depends(require_api_bearer)])


@router.post("/admin/seed", status_code=status.HTTP_201_CREATED)
def admin_seed(req: SeedRequest) -> dict:
    gender = req.gender if req.gender in ("f", "m", "u") else None
    if gender is None:
        # Auto-detect from the Polish first name. Caller can still override in
        # the portal settings; that POSTs /admin/seed again with an explicit
        # value and re-upserts the user doc.
        gender = infer_gender_pl(req.display_name)
    memstore.upsert_user(
        UserProfile(
            uid=req.uid,
            display_name=req.display_name,
            base_age=req.base_age,
            gender=gender,
            ocean_t=Ocean().as_dict(),
        )
    )
    return {"ok": True, "uid": req.uid, "gender": gender}


@router.get("/users/{uid}/persona")
def get_persona(uid: str) -> dict:
    try:
        return persona_snapshot(uid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/users/{uid}/chronicle")
def chronicle(uid: str, limit: int = 50) -> dict:
    return get_chronicle(uid, limit=limit)


@router.get("/users/{uid}/chat/history")
def chat_history(uid: str, limit: int = 200) -> dict:
    limit = max(1, min(limit, 200))
    return {"uid": uid, "turns": memstore.recent_chat_turns(uid, limit=limit)}


@router.post("/users/{uid}/sessions/close")
def sessions_close(uid: str) -> dict:
    """Summarize the recent chat log into an arc + optional commitments."""
    return close_session_and_summarize(uid)


@router.get("/users/{uid}/voice/primer")
def voice_primer(uid: str) -> dict:
    """Suggested cold-open line from arcs/commitments (voice UI)."""
    try:
        line = cold_open_line(uid)
    except Exception:  # noqa: BLE001 — missing user / Firestore read failure is non-fatal
        line = ""
    return {"uid": uid, "line": line}


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


@router.post("/users/{uid}/chat")
def chat_endpoint(uid: str, req: ChatRequest) -> dict:
    try:
        return chat_with_future_self(
            uid,
            req.message,
            display_name=req.display_name,
            base_age=req.base_age,
            use_rag=req.use_rag,
            fast=req.fast,
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
