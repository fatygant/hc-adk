"""Two-stage crisis detector: keyword hot-list + LLM severity rating.

Stage 1 (keywords) catches obvious self-harm/suicide signals in PL + EN with
zero latency and zero LLM cost. Stage 2 calls `gemini-3.1-flash-lite-preview`
only when stage 1 misses, with a strict JSON-schema severity rating 0..5. We
treat severity >= 3 as a crisis so the agent handoff to 116 111 / 112 kicks
in before ever reaching the FutureSelf LLM.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from google.genai import types as genai_types

from jutra.infra.vertex import generate_with_fallback
from jutra.settings import get_settings

logger = logging.getLogger(__name__)


# Deliberately short and unambiguous; precision > recall at stage 1.
_KEYWORDS_PL = (
    "nie chce zyc",
    "nie chce żyć",
    "chce umrzec",
    "chcę umrzeć",
    "zabic sie",
    "zabić się",
    "zabije sie",
    "zabiję się",
    "samobojstw",
    "samobójstw",
    "skonczyc ze soba",
    "skończyć ze sobą",
    "ciac sie",
    "tnę się",
    "tne sie",
)
_KEYWORDS_EN = (
    "kill myself",
    "end my life",
    "suicide",
    "want to die",
    "self harm",
    "self-harm",
    "cutting myself",
)

_CRISIS_SEVERITY_SYSTEM = (
    "Jestes klasyfikatorem bezpieczenstwa rozmow z nastolatkami. "
    "Na wejsciu dostajesz wiadomosc uzytkownika. "
    "Twoim zadaniem jest ocena, czy wiadomosc zawiera tresci samobojcze, samouszkadzajace "
    "lub przemocowe wobec wlasnej osoby. Odpowiedz WYLACZNIE JSON-em wg schemy:\n"
    '{"severity": <int 0..5>, "reason": "<krotkie PL uzasadnienie, <= 140 znakow>"}\n\n'
    "Skala: 0 = brak sygnalu, 1 = ogolne niezadowolenie, 2 = smutek / samotnosc, "
    "3 = mysli samobojcze pasywne, 4 = mysli samobojcze aktywne lub samouszkodzenia, "
    "5 = plan dzialania lub akt w toku."
)


@dataclass(frozen=True, slots=True)
class CrisisVerdict:
    is_crisis: bool
    severity: int
    reason: str
    resources: list[str]


def _resources_pl() -> list[str]:
    return [
        "116 111 - telefon zaufania dla dzieci i mlodziezy (24h, bezplatny)",
        "112 - numer alarmowy UE",
        "116 123 - telefon wsparcia emocjonalnego dla doroslych (ITAKA)",
    ]


def keyword_hit(text: str) -> bool:
    low = text.lower()
    return any(kw in low for kw in _KEYWORDS_PL + _KEYWORDS_EN)


def _severity_from_llm(text: str) -> tuple[int, str]:
    """Call Gemini Flash-Lite for severity; return (severity, reason)."""
    config = genai_types.GenerateContentConfig(
        system_instruction=_CRISIS_SEVERITY_SYSTEM,
        temperature=0.0,
        response_mime_type="application/json",
        max_output_tokens=120,
    )
    try:
        resp = generate_with_fallback("extract", text, config=config)
        payload = resp.text or "{}"
        data = json.loads(re.sub(r"```json|```", "", payload).strip() or "{}")
        sev = int(data.get("severity", 0))
        reason = str(data.get("reason", ""))[:160]
        return max(0, min(5, sev)), reason
    except Exception as exc:  # noqa: BLE001
        logger.warning("Crisis LLM classifier failed: %s", exc, exc_info=False)
        return 0, ""


def detect_crisis(text: str, *, use_llm: bool = True) -> CrisisVerdict:
    """Return a crisis verdict. LLM is skipped in tests by setting use_llm=False."""
    if keyword_hit(text):
        return CrisisVerdict(
            is_crisis=True,
            severity=4,
            reason="keyword-match",
            resources=_resources_pl(),
        )
    if not use_llm:
        return CrisisVerdict(is_crisis=False, severity=0, reason="", resources=_resources_pl())
    sev, reason = _severity_from_llm(text)
    return CrisisVerdict(
        is_crisis=sev >= 3,
        severity=sev,
        reason=reason,
        resources=_resources_pl(),
    )


def crisis_reply() -> str:
    return get_settings().crisis_reply_pl
