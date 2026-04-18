#!/usr/bin/env python3
"""Smoke test the jutra MCP server end-to-end via the official Python SDK.

Exits 0 on success, non-zero on any tool failure.

Usage:
    MCP_BEARER_TOKEN=... python3 scripts/mcp_smoke.py [url]
"""

from __future__ import annotations

import asyncio
import os
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main(url: str, token: str) -> int:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with (
        streamablehttp_client(url, headers=headers) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        names = [t.name for t in tools.tools]
        print("tools:", names)
        assert "list_available_horizons" in names, names

        hz = await session.call_tool("list_available_horizons", {})
        print("list_available_horizons:", hz.structuredContent or hz.content)

        det = await session.call_tool("detect_crisis_tool", {"message": "mam dzisiaj zle humory"})
        print("detect_crisis_tool:", det.structuredContent or det.content)
    return 0


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080/mcp/"
    token = os.environ.get("MCP_BEARER_TOKEN", "")
    sys.exit(asyncio.run(main(url, token)))
