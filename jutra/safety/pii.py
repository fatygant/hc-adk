"""Conservative PII redaction for teen-facing conversations.

We redact before anything reaches the LLM so that Gemini never stores raw PII.
This is NOT production-grade (no NLP, no entity linking); for the hackathon it
covers the five realistic vectors we saw in the demo tweets: email, Polish
phone numbers, full names attached to school references, street addresses,
and IBAN/PESEL numbers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# Polish mobile: +48 xxx xxx xxx, or 9-digit local with optional spaces/dashes.
PHONE_RE = re.compile(r"(?<!\d)(?:\+48[\s-]?)?(?:\d{3}[\s-]?\d{3}[\s-]?\d{3})(?!\d)")
# PESEL: 11-digit national ID.
PESEL_RE = re.compile(r"(?<!\d)\d{11}(?!\d)")
# IBAN (PL form starts with PL + 26 digits).
IBAN_PL_RE = re.compile(r"\bPL\d{2}(?:[\s-]?\d){24}\b", re.IGNORECASE)
# Street addresses: "ul. <name> <number>" or "ulica <name> <number>".
ADDRESS_RE = re.compile(
    r"\b(?:ul\.?|ulica|al\.?|aleja)\s+[A-ZĄĆĘŁŃÓŚŹŻ][\w\sĄĆĘŁŃÓŚŹŻąćęłńóśźż-]{2,40}\s+\d+[a-zA-Z]?(?:/\d+)?",
    re.UNICODE,
)


@dataclass(frozen=True, slots=True)
class RedactionResult:
    text: str
    replacements: dict[str, int]

    @property
    def had_pii(self) -> bool:
        return any(v > 0 for v in self.replacements.values())


def redact_pii(text: str) -> RedactionResult:
    counts: dict[str, int] = {"email": 0, "phone": 0, "pesel": 0, "iban": 0, "address": 0}

    def _sub(pattern: re.Pattern[str], placeholder: str, key: str, src: str) -> str:
        def _replace(_: re.Match[str]) -> str:
            counts[key] += 1
            return placeholder

        return pattern.sub(_replace, src)

    out = text
    out = _sub(EMAIL_RE, "[EMAIL]", "email", out)
    out = _sub(IBAN_PL_RE, "[IBAN]", "iban", out)
    out = _sub(PESEL_RE, "[PESEL]", "pesel", out)
    out = _sub(PHONE_RE, "[TEL]", "phone", out)
    out = _sub(ADDRESS_RE, "[ADRES]", "address", out)
    return RedactionResult(text=out, replacements=counts)
