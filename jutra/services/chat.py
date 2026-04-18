"""Chat with future-self (safety wrapped + optional RAG)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from jutra.agents.future_self import future_self_reply, future_self_reply_stream
from jutra.infra.vertex import embed
from jutra.memory import store as memstore
from jutra.memory.save_turn import extract_and_save
from jutra.safety.crisis import crisis_reply, detect_crisis
from jutra.safety.pii import redact_pii
from jutra.safety.wrap_turn import SafeTurn, wrap_turn

logger = logging.getLogger(__name__)


def chat_with_future_self(
    uid: str,
    horizon_years: int,
    user_message: str,
    *,
    display_name: str = "Ty",
    use_rag: bool = True,
    persist_memory: bool = True,
    fast: bool = False,
) -> dict:
    """Run one chat turn and return the structured result.

    Pipeline:
      1. `wrap_turn` (PII redact + crisis detect). On crisis -> return helpline.
      2. Embed the (redacted) message for RAG if we have any posts stored.
      3. Call `future_self_reply` with that embedding so FutureSelf_N can cite
         the user's own past posts.
      4. After the reply, run `extract_and_save` to keep Chronicle / memories
         fresh (best-effort; ignores failures).

    Pass `fast=True` for voice sessions: flash model + no thinking + short
    output, see `future_self_reply`.
    """
    rag_emb: list[float] | None = None
    if use_rag and memstore.count_posts(uid) > 0:
        try:
            rag_emb = embed([user_message])[0]
        except Exception as exc:  # noqa: BLE001
            logger.warning("RAG embedding failed: %s", exc)

    def agent(redacted_msg: str) -> str:
        return future_self_reply(
            uid,
            horizon_years,
            redacted_msg,
            rag_query_embedding=rag_emb,
            display_name=display_name,
            fast=fast,
        )

    result: SafeTurn = wrap_turn(user_message, agent)

    if persist_memory and not result.crisis:
        try:
            extract_and_save(uid, user_message, horizon=horizon_years)
        except Exception as exc:  # noqa: BLE001
            logger.warning("save_turn failed: %s", exc)

    return {
        "uid": uid,
        "horizon_years": horizon_years,
        "response": result.response,
        "crisis": result.crisis,
        "crisis_severity": result.severity,
        "pii_redactions": result.pii_redactions,
    }


async def chat_with_future_self_stream(
    uid: str,
    horizon_years: int,
    user_message: str,
    *,
    display_name: str = "Ty",
    use_rag: bool = True,
    persist_memory: bool = True,
) -> AsyncIterator[dict]:
    """Streaming variant of `chat_with_future_self` for the voice path.

    Yields typed SSE-ready events:
      - {"event": "meta",  "data": {"crisis", "severity", "pii_redactions"}}
      - {"event": "delta", "data": {"text": <token chunk>}}  (0..N times)
      - {"event": "done",  "data": {"response": <full text>}}
      - {"event": "error", "data": {"error": <str>}}

    Safety pipeline:
      1. `redact_pii` on the raw message (same as non-stream path).
      2. `detect_crisis` on redacted text. On crisis -> emit helpline text as
         a single delta, skip LLM entirely.
      3. Otherwise embed once (blocking) for RAG, then stream Gemini chunks.

    The disclosure prefix is NOT prepended here: the voice worker speaks the
    disclosure once at session start and would otherwise hear "[Rozmawiasz z
    symulacją jutra...]" at the head of every reply. Text callers should use
    `chat_with_future_self` instead.
    """
    try:
        redacted = redact_pii(user_message)
        verdict = detect_crisis(redacted.text, use_llm=True)
    except Exception as exc:  # noqa: BLE001
        logger.exception("chat_with_future_self_stream: safety pipeline failed")
        yield {"event": "error", "data": {"error": f"safety: {exc}"}}
        return

    if verdict.is_crisis:
        body = crisis_reply() + "\n\n" + "\n".join(f"- {r}" for r in verdict.resources)
        yield {
            "event": "meta",
            "data": {
                "crisis": True,
                "severity": verdict.severity,
                "pii_redactions": redacted.replacements,
            },
        }
        yield {"event": "delta", "data": {"text": body}}
        yield {"event": "done", "data": {"response": body}}
        return

    rag_emb: list[float] | None = None
    if use_rag:
        try:
            if memstore.count_posts(uid) > 0:
                rag_emb = embed([redacted.text])[0]
        except Exception as exc:  # noqa: BLE001
            logger.warning("RAG embedding failed: %s", exc)

    yield {
        "event": "meta",
        "data": {
            "crisis": False,
            "severity": verdict.severity,
            "pii_redactions": redacted.replacements,
        },
    }

    parts: list[str] = []
    try:
        async for delta in future_self_reply_stream(
            uid,
            horizon_years,
            redacted.text,
            rag_query_embedding=rag_emb,
            display_name=display_name,
        ):
            parts.append(delta)
            yield {"event": "delta", "data": {"text": delta}}
    except Exception as exc:  # noqa: BLE001
        logger.exception("future_self_reply_stream failed mid-flight")
        yield {"event": "error", "data": {"error": str(exc)}}
        return

    full = "".join(parts).strip()
    yield {"event": "done", "data": {"response": full}}

    if persist_memory:
        try:
            extract_and_save(uid, user_message, horizon=horizon_years)
        except Exception as exc:  # noqa: BLE001
            logger.warning("save_turn (stream) failed: %s", exc)
