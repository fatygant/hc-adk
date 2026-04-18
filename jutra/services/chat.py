"""Chat with future-self (safety wrapped + optional RAG)."""

from __future__ import annotations

import logging

from jutra.agents.future_self import future_self_reply
from jutra.infra.vertex import embed
from jutra.memory import store as memstore
from jutra.memory.save_turn import extract_and_save
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
) -> dict:
    """Run one chat turn and return the structured result.

    Pipeline:
      1. `wrap_turn` (PII redact + crisis detect). On crisis -> return helpline.
      2. Embed the (redacted) message for RAG if we have any posts stored.
      3. Call `future_self_reply` with that embedding so FutureSelf_N can cite
         the user's own past posts.
      4. After the reply, run `extract_and_save` to keep Chronicle / memories
         fresh (best-effort; ignores failures).
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
