"""Settings, read from environment variables (or from backend/.env on a local run)."""

from functools import lru_cache
from typing import Literal

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


@lru_cache
def get_settings() -> Settings:
    """Read the environment once and reuse the result."""
    return Settings()
