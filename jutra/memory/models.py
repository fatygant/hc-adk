"""Data models for the Firestore-backed persona store."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

ChronicleKind = Literal["value", "preference", "fact", "arc"]

Gender = Literal["f", "m", "u"]


@dataclass(slots=True)
class UserProfile:
    uid: str
    display_name: str = ""
    base_age: int = 15
    gender: Gender = "u"
    ocean_t: dict[str, float] = field(default_factory=dict)
    riasec_top3: list[str] = field(default_factory=list)
    context_notes: list[str] = field(default_factory=list)
    style_profile: dict = field(default_factory=dict)
    style_turn_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class ChronicleTriple:
    """Identity triple: subject-predicate-object, tagged with kind and weight."""

    subject: str
    predicate: str
    object: str
    kind: ChronicleKind = "fact"
    weight: float = 1.0
    source: str = "onboarding"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class MemoryItem:
    """Short extracted fact from a conversation turn."""

    text: str
    topic: str = ""
    source: str = "chat"
    due_hint: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class SocialPost:
    """Social media post with embedding for semantic retrieval."""

    platform: str
    raw_text: str
    themes: list[str] = field(default_factory=list)
    embedding: list[float] = field(default_factory=list)
    salience: float | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
