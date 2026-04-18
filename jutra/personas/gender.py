"""Gender inference from Polish first names.

Used to pick the right TTS voice per session and condition grammatical gender
in the future-self prompt (Polish past-tense verbs and adjectives differ by
gender; a mismatched voice or mismatched grammar sounds broken).

Deliberately rule-based, no LLM call on the hot path:

- Polish female first names end in ``-a`` with extremely high precision.
- A short override set handles the common male exceptions (Kuba, Barnaba,
  Kosma, ...) that also end in ``-a``.
- Tokens that are not plausibly a first name (empty, 1 char, non-alpha) fall
  back to ``"u"`` (unknown) so the caller can pick a neutral voice and neutral
  grammar.
"""

from __future__ import annotations

import re
from typing import Literal

Gender = Literal["f", "m", "u"]

# Male first names (or common nicknames/diminutives) that end in `-a`.
# Lowercase, ASCII-folded form. Keep short; false negatives here are cheap,
# the user can override in the portal settings.
_MALE_OVERRIDES: frozenset[str] = frozenset(
    {
        "kuba",
        "barnaba",
        "bonawentura",
        "kosma",
        "jarema",
        "saba",
        "jona",
        "aleksa",
        "nikita",
        "ilja",
    }
)

# Polish diacritics -> ASCII, just for the suffix heuristic. We don't need a
# full unidecode here.
_FOLD = str.maketrans(
    {
        "ą": "a",
        "ć": "c",
        "ę": "e",
        "ł": "l",
        "ń": "n",
        "ó": "o",
        "ś": "s",
        "ź": "z",
        "ż": "z",
        "Ą": "a",
        "Ć": "c",
        "Ę": "e",
        "Ł": "l",
        "Ń": "n",
        "Ó": "o",
        "Ś": "s",
        "Ź": "z",
        "Ż": "z",
    }
)

_NON_ALPHA = re.compile(r"[^a-zA-Z]")


def _first_token(display_name: str) -> str:
    if not display_name:
        return ""
    first = display_name.strip().split()[0] if display_name.strip() else ""
    folded = first.translate(_FOLD).lower()
    return _NON_ALPHA.sub("", folded)


def infer_gender_pl(display_name: str) -> Gender:
    """Infer gender from a Polish first name.

    Returns ``"f"`` for female, ``"m"`` for male, ``"u"`` when unsure.
    Caller treats ``"u"`` as "use the default/neutral voice" and neutral
    grammatical forms in the prompt.
    """
    token = _first_token(display_name)
    if len(token) < 2:
        return "u"
    if token in _MALE_OVERRIDES:
        return "m"
    if token.endswith("a"):
        return "f"
    return "m"
