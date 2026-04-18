"""Orchestrate safety checks around a chat turn.

Input pipeline (before LLM):
  1. redact_pii  (email/phone/address/pesel/iban -> placeholders)
  2. detect_crisis (keywords fast path; LLM Flash-Lite second stage)
     -> if crisis: short-circuit with the hard-coded PL resources message.

Output pipeline (after LLM):
  1. prefix_with_disclosure (EU AI Act style prefix for every reply)

Used by `jutra/mcp/tools/chat_with_future_self.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from jutra.safety.crisis import CrisisVerdict, crisis_reply, detect_crisis
from jutra.safety.disclosure import prefix_with_disclosure
from jutra.safety.pii import redact_pii


@dataclass(frozen=True, slots=True)
class SafeTurn:
    response: str
    crisis: bool
    severity: int
    pii_redactions: dict[str, int]


def wrap_turn(
    user_message: str,
    agent: Callable[[str], str],
    *,
    use_llm_crisis_check: bool = True,
) -> SafeTurn:
    """Run agent only if user_message is safe; always return a wrapped reply."""
    redacted = redact_pii(user_message)

    verdict: CrisisVerdict = detect_crisis(redacted.text, use_llm=use_llm_crisis_check)
    if verdict.is_crisis:
        body = crisis_reply() + "\n\n" + "\n".join(f"- {r}" for r in verdict.resources)
        return SafeTurn(
            response=prefix_with_disclosure(body),
            crisis=True,
            severity=verdict.severity,
            pii_redactions=redacted.replacements,
        )

    raw = agent(redacted.text)
    return SafeTurn(
        response=prefix_with_disclosure(raw),
        crisis=False,
        severity=verdict.severity,
        pii_redactions=redacted.replacements,
    )
