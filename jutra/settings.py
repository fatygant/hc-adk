"""Runtime configuration for jutra.

Values come from env; defaults reflect the hackathon demo target.
Two Vertex AI regions are used on purpose:
- LLM inference (Gemini 3 preview) lives in `global` only.
- Embeddings (`text-embedding-005`) lives in `europe-west4`.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    google_cloud_project: str = Field(default="jutra-493710")
    google_genai_use_vertexai: bool = Field(default=True)
    llm_location: str = Field(default="global")
    embed_location: str = Field(default="europe-west4")

    model_reasoning: str = Field(default="gemini-3.1-pro-preview")
    model_chat: str = Field(default="gemini-3-flash-preview")
    model_extract: str = Field(default="gemini-3.1-flash-lite-preview")
    embed_model: str = Field(default="text-embedding-005")
    fallback_model: str = Field(default="gemini-2.5-flash")

    mcp_bearer_token: str = Field(default="dev-local-token")
    api_bearer_token: str = Field(default="dev-local-token")

    log_level: str = Field(default="INFO")
    port: int = Field(default=8080)

    ai_disclosure_pl: str = Field(
        default=(
            "Rozmawiasz z symulacją jutra (AI). To nie jest prawdziwa wersja "
            "Ciebie. Traktuj odpowiedź jako inspirację, nie decyzję za Ciebie."
        )
    )
    crisis_reply_pl: str = Field(
        default=(
            "To, co czujesz, brzmi naprawdę trudno i nie chcę ryzykować "
            "rozmowy na ten temat jako AI. Proszę, zadzwoń teraz do kogoś, "
            "kto może pomóc natychmiast:\n"
            "- 116 111: telefon zaufania dla dzieci i młodzieży (24h, "
            "bezpłatny)\n"
            "- 112: numer alarmowy, jeśli czujesz, że jesteś w zagrożeniu "
            "teraz.\n"
            "Jeśli jest przy Tobie ktoś dorosły, powiedz mu o tym. Nie "
            "jesteś sam(a)."
        )
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
