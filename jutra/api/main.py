"""FastAPI entrypoint (REST + MCP SSE mounted at /mcp).

Routers are plugged in by subsequent milestones; this file only owns the app
lifecycle and the `/healthz` probe so that `gcloud run deploy` works from day 1.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from jutra.api.routes import router as rest_router
from jutra.logging_setup import configure_logging
from jutra.mcp.server import mount_mcp
from jutra.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    # Build MCP first so we can weave its session_manager into our lifespan.
    # We cannot call mount_mcp before FastAPI is created, so use a two-step:
    # build a temporary app and then wrap everything inside the lifespan.

    mcp_holder: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        mcp = mcp_holder["mcp"]
        async with mcp.session_manager.run():
            yield

    app = FastAPI(
        title="jutra",
        version="0.1.0",
        summary="Conversational future-self backend (Gemini 3 + ADK + Firestore)",
        lifespan=lifespan,
    )

    # NOTE: Cloud Run GFE reserves `/healthz` and returns its own 404 before
    # the request reaches the container, so we publish the readiness probe
    # on `/readyz` and keep `/healthz` as a defensive alias for any external
    # tooling that can still reach the app (e.g. during local runs).
    def _health_payload() -> dict[str, object]:
        return {
            "status": "ok",
            "project": settings.google_cloud_project,
            "models": {
                "reasoning": settings.model_reasoning,
                "chat": settings.model_chat,
                "extract": settings.model_extract,
                "embed": settings.embed_model,
            },
            "locations": {
                "llm": settings.llm_location,
                "embed": settings.embed_location,
            },
        }

    @app.get("/readyz")
    async def readyz() -> dict[str, object]:
        return _health_payload()

    @app.get("/healthz")
    async def healthz() -> dict[str, object]:
        return _health_payload()

    app.include_router(rest_router)
    mcp_holder["mcp"] = mount_mcp(app)
    return app


app = create_app()
