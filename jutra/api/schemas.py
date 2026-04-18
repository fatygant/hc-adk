"""Pydantic schemas used by the REST API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class IngestTextRequest(BaseModel):
    posts: list[str] = Field(..., description="Raw social media post texts")
    platform: str = Field(default="manual")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    display_name: str = Field(default="Ty")
    use_rag: bool = Field(default=True)
    fast: bool = Field(default=False)


class OnboardingStartRequest(BaseModel):
    uid: str


class OnboardingTurnRequest(BaseModel):
    session_id: str
    message: str = Field(..., min_length=1, max_length=2000)


class SeedRequest(BaseModel):
    uid: str = Field(default="alex")
    display_name: str = Field(default="Alex")
    base_age: int = Field(default=15, ge=10, le=80)
