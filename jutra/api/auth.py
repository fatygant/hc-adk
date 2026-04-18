"""Shared Bearer auth for REST and MCP transports."""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from jutra.settings import get_settings


def require_api_bearer(
    authorization: str | None = Header(default=None),
) -> None:
    expected = get_settings().api_bearer_token
    _check(authorization, expected)


def require_mcp_bearer(
    authorization: str | None = Header(default=None),
) -> None:
    expected = get_settings().mcp_bearer_token
    _check(authorization, expected)


def _check(authorization: str | None, expected: str) -> None:
    if not expected:
        return  # auth disabled (local dev)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    if token != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid token")
