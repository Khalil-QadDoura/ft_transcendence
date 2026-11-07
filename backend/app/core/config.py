"""Settings, read from environment variables (or from backend/.env on a local run)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # "prod" by default, so a forgotten ENV never exposes the Swagger page.
    env: Literal["dev", "prod"] = "prod"
    # Required: the app refuses to start without it.
    database_url: str
    log_level: str = "INFO"
    # Empty = all /_internal/* routes are closed.
    internal_api_key: str = ""

    # Signs the login tokens (JWTs). Required, like DATABASE_URL, and at least 32 characters,
    # because a short key can be guessed. Generate one with: openssl rand -hex 32
    jwt_secret: str = Field(min_length=32)


@lru_cache
def get_settings() -> Settings:
    """Read the environment once and reuse the result."""
    return Settings()
