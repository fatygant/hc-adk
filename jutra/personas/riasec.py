"""RIASEC interest model used as *exploration scenarios*, not career prediction.

Ethical note: we deliberately do NOT map a user's RIASEC vector to "you will
be a <job> in 20 years". Research (Nye et al., 2017; Roberts & Davis, 2016)
shows that adolescent interests explain a modest share of career outcomes.
Instead we surface the top 3 themes as "scenariusze do eksploracji" so the
FutureSelf agent can say "w jednym ze scenariuszy kariery, ktorzy ludzie
podobni do Ciebie wybierali, mozesz lubic ... ".
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

RIASEC_TYPES = ("R", "I", "A", "S", "E", "C")


@dataclass(frozen=True, slots=True)
class RiasecResult:
    top3: list[str]
    exploration_scenarios: list[str]


# PL labels + 2-3 concrete exploration scenarios per type.
_SCENARIOS: dict[str, list[str]] = {
    "R": [
        "Praca z rzeczami: robotyka, sprzet elektroniczny, prototypy fizyczne.",
        "Rzemioslo lub sport wymagajacy precyzji ruchu.",
    ],
    "I": [
        "Praca badawcza: data science, nauki przyrodnicze, medycyna.",
        "Inzynieria oprogramowania z naciskiem na rozwiazywanie zlozonych problemow.",
    ],
    "A": [
        "Projektowanie, muzyka, pisanie, film lub UX.",
        "Praca kreatywna tam, gdzie Twoj styl jest podpisem, nie konwencja.",
    ],
    "S": [
        "Uczenie, terapia, opieka zdrowotna, praca z mlodszymi.",
        "Role facylitujace rozwoj innych (coaching, praca organizacji spolecznych).",
    ],
    "E": [
        "Zakladanie wlasnej inicjatywy, praca w produkcie lub sprzedazy.",
        "Rola lidera zespolu, gdzie trzeba przekonac ludzi do pomyslu.",
    ],
    "C": [
        "Analityka, finanse, prawo, audyt - tam gdzie liczy sie porzadek danych.",
        "Rola 'operatora' w firmie: procesy, logistyka, planowanie.",
    ],
}


# Crude keyword map so the onboarding agent can infer RIASEC from free text
# collected during conversation. Deliberately simple for the hackathon.
_KEYWORDS_PL: dict[str, tuple[str, ...]] = {
    "R": ("rower", "sport", "gra", "motor", "narzedzia", "drewno", "ogrod"),
    "I": ("matematyk", "nauk", "badan", "fizyk", "biolog", "programow", "kod", "ai"),
    "A": ("muzyk", "rysow", "pisan", "film", "gra muzyczn", "fotograf", "design", "moda"),
    "S": ("pomoc", "wolontariat", "uczyc", "opiekowa", "psycholog", "przyjac"),
    "E": ("biznes", "sprzeda", "lider", "zespol", "zalozyc", "negocj", "startup"),
    "C": ("porzadek", "planowa", "listy", "rachunk", "finanse", "budzet", "ksiegowosc"),
}


def _normalize(text: str) -> str:
    return text.lower()


def riasec_from_interests(interests: list[str]) -> Counter:
    """Score RIASEC types from raw interest phrases using keyword overlap."""
    scores: Counter[str] = Counter()
    for phrase in interests:
        norm = _normalize(phrase)
        for riasec, kws in _KEYWORDS_PL.items():
            if any(kw in norm for kw in kws):
                scores[riasec] += 1
    return scores


def refresh_riasec_from_chat(uid: str, user_message: str) -> None:
    """Increment per-letter RIASEC counters from chat text; refresh stored top3."""
    scores = riasec_from_interests([user_message])
    if not scores:
        return
    from jutra.memory import store as memstore

    counter = memstore.get_riasec_counter(uid)
    for t in RIASEC_TYPES:
        counter[t] = counter.get(t, 0) + int(scores.get(t, 0))
    ranked = sorted(
        RIASEC_TYPES,
        key=lambda x: (-counter.get(x, 0), RIASEC_TYPES.index(x)),
    )
    top = [x for x in ranked if counter.get(x, 0) > 0][:3]
    if len(top) < 3:
        pad = [x for x in ("I", "S", "A") if x not in top]
        top = (top + pad)[:3]
    memstore.set_riasec_state(uid, counter, top)


def riasec_top3(interests: list[str]) -> RiasecResult:
    """Return the top 3 RIASEC types + exploration scenarios (never predictions)."""
    scores = riasec_from_interests(interests)
    # Stable tie-break: insertion order of RIASEC_TYPES, higher score first.
    ranked = sorted(
        RIASEC_TYPES,
        key=lambda t: (-scores.get(t, 0), RIASEC_TYPES.index(t)),
    )
    top = [t for t in ranked if scores.get(t, 0) > 0][:3]
    if not top:
        # No signal -> pick neutral investigative/social default for 15yo demo.
        top = ["I", "S", "A"]
    scenarios: list[str] = []
    for t in top:
        scenarios.extend(_SCENARIOS[t])
    return RiasecResult(top3=top, exploration_scenarios=scenarios)
