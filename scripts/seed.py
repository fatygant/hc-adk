#!/usr/bin/env python3
"""Seed the demo persona Alex_15 end-to-end through the MCP interface.

What this script does (against a running jutra backend, local or Cloud Run):

  1. (optional) wipe users/alex-15 from Firestore so the demo is deterministic
  2. start_conversational_onboarding + replay 6 canned answers from
     demo_data/alex_15/onboarding.json
  3. ingest_social_media_text with the 30 tweet-style posts from
     demo_data/alex_15/tweets.txt (triggers OCEAN nudge + Firestore vectors)
  4. get_persona_snapshot and get_chronicle_tool, printing a
     short summary for the MP4 demo
  5. chat_with_future_self_tool with a canonical demo prompt
     ("Boje sie ze zmarnuje zycie") and print the live Gemini 3 response so
     the demo reel has a real answer recorded

The script takes a URL and reads MCP_BEARER_TOKEN from the environment.

Usage:
    MCP_BEARER_TOKEN=... python3 scripts/seed.py [url] [--reset]
    MCP_BEARER_TOKEN=... python3 scripts/seed.py https://jutra-...run.app/mcp/ --reset
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo_data" / "alex_15"
DEFAULT_URL = "http://127.0.0.1:8080/mcp/"
DEMO_PROMPT = "Boje sie ze zmarnuje zycie i skoncze jak moj wujek, ktory zylem jak chcial go tata."


def _payload(tool_result) -> dict:
    """Extract structured JSON from an MCP tool response (JSON-in-text format)."""
    if tool_result.structuredContent:
        return tool_result.structuredContent
    for item in tool_result.content:
        if getattr(item, "type", "") == "text":
            try:
                return json.loads(item.text)
            except json.JSONDecodeError:
                continue
    return {}


def _load_onboarding() -> list[str]:
    data = json.loads((DEMO / "onboarding.json").read_text(encoding="utf-8"))
    return list(data["answers"])


def _load_profile() -> dict:
    return json.loads((DEMO / "profile.json").read_text(encoding="utf-8"))


def _load_tweets() -> list[str]:
    raw = (DEMO / "tweets.txt").read_text(encoding="utf-8")
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _maybe_reset(uid: str) -> None:
    """Wipe Firestore user doc locally via `jutra.memory.store.wipe_user`.

    This requires GOOGLE_APPLICATION_CREDENTIALS pointing at a service account
    with Firestore writer access. We import lazily so the script still works
    without local GCP creds when --reset is NOT passed.
    """
    try:
        from jutra.memory.store import wipe_user  # noqa: PLC0415
    except ImportError as exc:
        print(f"!! cannot import jutra.memory.store ({exc}); skipping reset")
        return
    counts = wipe_user(uid)
    print(f"== wipe users/{uid}: {counts}")


async def run(url: str, token: str, reset: bool) -> int:
    profile = _load_profile()
    uid = profile["uid"]
    display_name = profile["display_name"]
    answers = _load_onboarding()
    tweets = _load_tweets()

    if reset:
        _maybe_reset(uid)

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    print(f"== connecting to {url}")
    async with (
        streamablehttp_client(url, headers=headers) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()

        print("\n== 1/5 start_conversational_onboarding")
        start_res = _payload(
            await session.call_tool("start_conversational_onboarding", {"uid": uid})
        )
        sid = start_res["session_id"]
        print(f"   session_id={sid}")
        print(f"   Q0: {start_res['question']}")

        print("\n== 2/5 onboarding turns (6x)")
        for i, ans in enumerate(answers, start=1):
            turn = _payload(
                await session.call_tool("onboarding_turn_tool", {"session_id": sid, "message": ans})
            )
            extracted = turn.get("extracted", {})
            print(
                f"   turn {i}: progress={turn.get('progress'):.2f} "
                f"values={extracted.get('values', [])} "
                f"prefs={extracted.get('preferences', [])} "
                f"fears={extracted.get('fears', [])} "
                f"riasec={extracted.get('riasec_top3', [])}"
            )
            if turn.get("completed"):
                print("   [onboarding completed early]")
                break

        print(f"\n== 3/5 ingest_social_media_text ({len(tweets)} posts)")
        ing = _payload(
            await session.call_tool(
                "ingest_social_media_text",
                {"uid": uid, "posts": tweets, "platform": "twitter"},
            )
        )
        print(f"   ingested={ing.get('ingested')} skipped={ing.get('skipped')}")
        print(f"   top_themes={ing.get('top_themes')}")
        print(f"   ocean_t={ing.get('ocean_t')}")

        print("\n== 4/5 get_persona_snapshot + get_chronicle")
        snap = _payload(await session.call_tool("get_persona_snapshot", {"uid": uid}))
        print(f"   base_age={snap.get('base_age')} display_name={snap.get('display_name')}")
        print(f"   ocean_t={snap.get('ocean_t')}")
        print(f"   riasec_top3={snap.get('riasec_top3')}")
        print(f"   top_values={snap.get('top_values')}")
        chron = _payload(await session.call_tool("get_chronicle_tool", {"uid": uid, "limit": 20}))
        print(
            f"   chronicle: values={len(chron.get('values', []))} "
            f"prefs={len(chron.get('preferences', []))} "
            f"facts={len(chron.get('facts', []))}"
        )

        print("\n== 5/5 chat_with_future_self_tool (live Gemini 3)")
        print(f"   prompt: {DEMO_PROMPT!r}")
        chat = _payload(
            await session.call_tool(
                "chat_with_future_self_tool",
                {
                    "uid": uid,
                    "message": DEMO_PROMPT,
                    "display_name": display_name,
                },
            )
        )
        print("\n----- FutureSelf -----")
        print(chat.get("response", "(no response)"))
        print("-------------------------")
        if chat.get("crisis"):
            print(f"[CRISIS detected, severity={chat.get('crisis_severity')}]")

    print("\n== done")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help="MCP streamable-http URL")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Wipe users/alex-15 from Firestore before seeding (needs GCP creds).",
    )
    args = parser.parse_args()
    token = os.environ.get("MCP_BEARER_TOKEN", "")
    return asyncio.run(run(args.url, token, args.reset))


if __name__ == "__main__":
    sys.exit(main())
