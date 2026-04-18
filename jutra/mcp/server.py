"""MCP server exposing the tools consumed by the LiveKit voice agent.

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
from jutra.services.personas import get_chronicle, persona_snapshot
from jutra.services.session_close import close_session_and_summarize, cold_open_line
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
            "Chronicle. Then call `chat_with_future_self_tool` — the agent picks "
            "its own age standpoint per reply, no fixed horizon."
        ),
    )

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
    def get_persona_snapshot(uid: str) -> dict:
        """Return the user's persona baseline (OCEAN + values + RIASEC + notes)."""
        return persona_snapshot(uid)

    @mcp.tool()
    def get_chronicle_tool(uid: str, limit: int = 50) -> dict:
        """Return Chronicle (values / preferences / facts) for a user."""
        return get_chronicle(uid, limit=limit)

    @mcp.tool()
    def chat_with_future_self_tool(
        uid: str,
        message: str,
        display_name: str | None = None,
        base_age: int | None = None,
        gender: str | None = None,
        use_rag: bool = True,
        fast: bool = False,
    ) -> dict:
        """One chat turn with the future-self agent. Safety wrapped + RAG grounded.

        Set `fast=True` from voice callers (LiveKit worker) to disable thinking
        tokens and cap output length so TTS starts sooner. The agent chooses its
        own age standpoint per reply from conversation context. `gender` is one
        of "f" / "m" / "u" and controls Polish grammatical gender in the reply.
        """
        g = gender.lower() if isinstance(gender, str) else None
        g = g if g in ("f", "m", "u") else None
        return chat_with_future_self(
            uid,
            message,
            display_name=display_name,
            base_age=base_age,
            gender=g,  # type: ignore[arg-type]
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

    @mcp.tool()
    def close_voice_session(uid: str) -> dict:
        """Persist session arc + commitments from recent chat_log. Call when the user leaves."""
        return close_session_and_summarize(uid)

    @mcp.tool()
    def get_voice_session_primer(uid: str) -> dict:
        """One-line cold-open suggestion from last arcs / open commitments."""
        return {"uid": uid, "line": cold_open_line(uid)}

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
    logger.info("Mounted MCP server at %s with 10 tools", _MCP_PATH)
    return mcp
