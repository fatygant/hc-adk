"""Voice-specific streaming endpoint (SSE).

The LiveKit worker consumes `POST /voice/chat-stream` to get Gemini tokens as
they arrive, so TTS can start speaking ~2s after end-of-speech instead of
waiting for the full backend reply (Pattern C in AGENTS.md).

Authenticated with the same bearer the worker uses for MCP
(`MCP_BEARER_TOKEN`), so no extra secret is required in the worker.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from jutra.api.auth import require_mcp_bearer
from jutra.services.chat import chat_with_future_self_stream

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/voice",
    tags=["voice"],
    dependencies=[Depends(require_mcp_bearer)],
)


class VoiceChatRequest(BaseModel):
    uid: str = Field(..., min_length=1)
    horizon: int = Field(..., description="Future-self horizon in years: 5/10/20/30")
    message: str = Field(..., min_length=1, max_length=2000)
    display_name: str = Field(default="Ty")
    use_rag: bool = Field(default=True)


def _sse_frame(event: str, data: dict) -> bytes:
    # JSON payload on a single `data:` line so clients can split by blank-line
    # boundaries without worrying about multi-line data framing.
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode()


@router.post("/chat-stream")
async def chat_stream(req: VoiceChatRequest) -> StreamingResponse:
    """SSE stream of backend tokens for the voice agent.

    Event types: `meta`, `delta`, `done`, `error`. See
    `jutra.services.chat.chat_with_future_self_stream` for the contract.
    """

    async def generator() -> AsyncIterator[bytes]:
        try:
            async for ev in chat_with_future_self_stream(
                req.uid,
                req.horizon,
                req.message,
                display_name=req.display_name,
                use_rag=req.use_rag,
            ):
                yield _sse_frame(ev["event"], ev["data"])
        except Exception as exc:  # noqa: BLE001
            logger.exception("voice chat-stream top-level failure")
            yield _sse_frame("error", {"error": str(exc)})

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            # Disable intermediary buffering so chunks reach the worker ASAP.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
