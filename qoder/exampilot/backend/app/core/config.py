"""Application configuration loaded from environment variables (.env supported)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="EXAMPILOT_", extra="ignore"
    )

    # seekdb (embedded database, Linux/macOS only)
    seekdb_path: str = ""

    # PowerContext long-term memory
    powercontext_base_url: str = "http://127.0.0.1:8000"
    powercontext_token: str = ""
    memory_scope_prefix: str = "exampilot"

    # Embedding: "local" | "openai" | "none"
    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_dimension: int = 512
    embedding_openai_model: str = "text-embedding-3-small"
    openai_api_key: str = ""
    openai_base_url: str = ""

    # LLM: "none" | "openai"
    llm_provider: str = "none"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    # Service
    host: str = "127.0.0.1"
    port: int = 8001
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_upload_files: int = 50
    max_file_bytes: int = 50 * 1024 * 1024

    # Classification thresholds (configurable, calibrated via tests)
    classify_high_confidence: float = 0.65
    classify_mid_confidence: float = 0.45

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def seekdb_dir(self) -> Path:
        if not self.seekdb_path:
            raise RuntimeError(
                "EXAMPILOT_SEEKDB_PATH is required and must be a native Linux/macOS filesystem path"
            )
        return Path(self.seekdb_path).expanduser().resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
