from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from uuid import UUID

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_model_name: str = Field(default="openai:gpt-4o-mini", min_length=1)
    openai_api_key: SecretStr | None = None
    openai_base_url: str | None = None
    embedding_api_key: SecretStr | None = None
    embedding_base_url: str | None = None
    embedding_model: str = Field(default="text-embedding-3-small", min_length=1)
    database_url: str = "postgresql+asyncpg://lexora:lexora@127.0.0.1:5434/lexora"
    personal_user_id: UUID = UUID("00000000-0000-0000-0000-000000000001")
    lexora_host: str = "127.0.0.1"
    lexora_port: int = Field(default=8010, ge=1, le=65_535)
    lexora_log_level: str = "info"
    legal_source_repository_path: Path = Path("../lvyan-lawtext")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
