from __future__ import annotations

import pytest

from jutra.safety.crisis import detect_crisis, keyword_hit
from jutra.safety.disclosure import prefix_with_disclosure
from jutra.safety.pii import redact_pii
from jutra.safety.wrap_turn import wrap_turn

# --- PII redaction --------------------------------------------------------


def test_redact_email_and_phone() -> None:
    result = redact_pii("moj email to alex@example.com a telefon 600 700 800")
    assert "[EMAIL]" in result.text
    assert "[TEL]" in result.text
    assert "alex@example.com" not in result.text
    assert result.had_pii is True


def test_redact_polish_plus48_phone() -> None:
    result = redact_pii("zadzwon +48 600-700-800")
    assert "[TEL]" in result.text


def test_redact_address_and_pesel() -> None:
    result = redact_pii("mieszkam ul. Slowackiego 12/5 pesel 92010112345")
    assert "[ADRES]" in result.text
    assert "[PESEL]" in result.text


def test_redact_iban_pl() -> None:
    result = redact_pii("konto PL61 1090 1014 0000 0712 1981 2874")
    assert "[IBAN]" in result.text


def test_redact_keeps_clean_text_untouched() -> None:
    result = redact_pii("lubie programowac i muzyke")
    assert result.text == "lubie programowac i muzyke"
    assert result.had_pii is False


# --- Crisis detector (keyword only, deterministic) ------------------------


@pytest.mark.parametrize(
    "msg",
    [
        "nie chce zyc",
        "chce umrzec",
        "chcę umrzeć",
        "want to die",
        "i will kill myself tonight",
        "planuje samobojstwo",
    ],
)
def test_keyword_hit_catches_explicit(msg: str) -> None:
    assert keyword_hit(msg) is True


@pytest.mark.parametrize(
    "msg",
    [
        "mam ciezki dzien",
        "nie chce sie uczyc",
        "czasem jest smutno ale ogarniam",
        "tired of everything feels hard",  # deliberately ambiguous, must NOT trigger
    ],
)
def test_keyword_hit_does_not_overtrigger(msg: str) -> None:
    assert keyword_hit(msg) is False


def test_detect_crisis_short_circuits_on_keyword_without_llm() -> None:
    verdict = detect_crisis("juz nie chce zyc", use_llm=True)
    assert verdict.is_crisis is True
    assert verdict.severity >= 3
    assert any("116 111" in r for r in verdict.resources)


def test_detect_crisis_skips_llm_when_disabled() -> None:
    verdict = detect_crisis("smutno mi ale dam rade", use_llm=False)
    assert verdict.is_crisis is False
    assert verdict.severity == 0


# --- Disclosure -----------------------------------------------------------


def test_disclosure_is_prepended() -> None:
    out = prefix_with_disclosure("Twoja odpowiedz.")
    assert out.startswith("[")
    assert "Twoja odpowiedz." in out


# --- wrap_turn orchestrator ----------------------------------------------


def test_wrap_turn_redacts_and_calls_agent_when_safe() -> None:
    seen: list[str] = []

    def fake_agent(msg: str) -> str:
        seen.append(msg)
        return "ok"

    result = wrap_turn(
        "mail: alex@example.com, tel 600700800, wiadomosc",
        fake_agent,
        use_llm_crisis_check=False,
    )
    assert result.crisis is False
    assert "[EMAIL]" in seen[0]
    assert "[TEL]" in seen[0]
    assert result.pii_redactions["email"] == 1
    assert result.pii_redactions["phone"] == 1
    assert "ok" in result.response
    assert not result.response.strip().startswith("[")


def test_wrap_turn_short_circuits_on_crisis_without_calling_agent() -> None:
    calls: list[str] = []

    def fake_agent(msg: str) -> str:
        calls.append(msg)
        return "should not be called"

    result = wrap_turn("nie chce zyc", fake_agent, use_llm_crisis_check=False)
    assert result.crisis is True
    assert calls == []
    assert "116 111" in result.response
    assert "112" in result.response
    assert not result.response.strip().startswith("[")
