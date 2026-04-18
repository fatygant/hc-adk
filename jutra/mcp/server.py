"""MCP server exposing the 9 tools consumed by the LiveKit voice agent.

Mounted into the FastAPI app at `/mcp` (Streamable HTTP) so everything ships as
one Cloud Run service. Bearer auth is enforced via a starlette middleware on
the subapp so the voice agent only needs the shared secret.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from jutra.agents.onboarding import onboarding_turn, start_onboarding
from jutra.safety.crisis import detect_crisis
from jutra.services.chat import chat_with_future_self
from jutra.services.ingestion import ingest_export, ingest_text
from jutra.services.personas import get_chronicle, list_horizons, persona_snapshot
from jutra.settings import get_settings

logger = logging.getLogger(__name__)

_MCP_PATH = "/mcp"


def _build_mcp() -> FastMCP:
    # DNS-rebinding protection is aimed at *local* MCP servers reachable from
    # a browser. Our service is public behind Google Frontend and authenticates
    # every request with a shared Bearer token, so host-header filtering here
    # would only break legitimate Cloud Run traffic (GFE forwards the project-
    # level hostname). We therefore disable it explicitly.
    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    mcp = FastMCP(
        name="jutra",
        streamable_http_path="/",
        transport_security=security,
        instructions=(
            "jutra backend: conversational future-self for teens. "
            "Use `start_conversational_onboarding` + `onboarding_turn` to build a "
            "Chronicle. Then call `chat_with_future_self` with horizon 5/10/20/30."
        ),
    )

    @mcp.tool()
    def list_available_horizons() -> dict:
        """Return the list of supported future-self horizons (years)."""
        return {"horizons": list_horizons()}

    @mcp.tool()
    def start_conversational_onboarding(uid: str) -> dict:
        """Start an onboarding session; returns session_id + first question."""
        sid, q = start_onboarding(uid)
        return {"session_id": sid, "question": q}

    @mcp.tool()
    def onboarding_turn_tool(session_id: str, message: str) -> dict:
        """Submit one onboarding reply; returns ack + next question + extracted."""
        return onboarding_turn(session_id, message)

    @mcp.tool()
    def ingest_social_media_text(uid: str, posts: list[str], platform: str = "manual") -> dict:
        """Ingest raw social media post texts. Updates OCEAN + Chronicle."""
        return ingest_text(uid, posts, platform=platform)

    @mcp.tool()
    def ingest_social_media_export(uid: str, filename: str, raw: str) -> dict:
        """Ingest a GDPR export file (tweets.js or posts_*.json)."""
        return ingest_export(uid, filename, raw)

    @mcp.tool()
    def get_persona_snapshot(uid: str, horizon: int) -> dict:
        """Return the user's FutureSelf_N persona (OCEAN + Erikson + values)."""
        return persona_snapshot(uid, horizon)

    @mcp.tool()
    def get_chronicle_tool(uid: str, limit: int = 50) -> dict:
        """Return Chronicle (values / preferences / facts) for a user."""
        return get_chronicle(uid, limit=limit)

    @mcp.tool()
    def chat_with_future_self_tool(
        uid: str,
        horizon: int,
        message: str,
        display_name: str = "Ty",
        use_rag: bool = True,
        fast: bool = False,
    ) -> dict:
        """One chat turn with FutureSelf_N. Safety wrapped + RAG grounded.

        Set `fast=True` from voice callers (LiveKit worker) to pin the chat
        (flash) model, disable thinking tokens, and cap output length so TTS
        starts sooner. Drops p50 latency ~4x at horizon=30.
        """
        return chat_with_future_self(
            uid,
            horizon,
            message,
            display_name=display_name,
            use_rag=use_rag,
            fast=fast,
        )

    @mcp.tool()
    def detect_crisis_tool(message: str) -> dict:
        """Return the crisis classifier verdict for a message."""
        v = detect_crisis(message)
        return {
            "is_crisis": v.is_crisis,
            "severity": v.severity,
            "reason": v.reason,
            "resources": v.resources,
        }

    return mcp


class _BearerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Response:
        expected = get_settings().mcp_bearer_token
        if expected:
            hdr = request.headers.get("authorization") or ""
            ok = hdr.lower().startswith("bearer ") and hdr.split(" ", 1)[1].strip() == expected
            if not ok:
                return Response("invalid bearer", status_code=401)
        return await call_next(request)


def mount_mcp(app: FastAPI) -> FastMCP:
    """Mount the MCP Streamable HTTP subapp at /mcp with Bearer auth.

    Returns the FastMCP instance so the caller can weave its session manager
    into the parent FastAPI lifespan.
    """
    mcp = _build_mcp()
    mcp_app = mcp.streamable_http_app()
    mcp_app.add_middleware(_BearerMiddleware)
    app.mount(_MCP_PATH, mcp_app)
    logger.info("Mounted MCP server at %s with 9 tools", _MCP_PATH)
    return mcp
