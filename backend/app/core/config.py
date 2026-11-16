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
    # Links in emails open the frontend at this address, e.g. <it>/verify-email?token=...
    frontend_base_url: str = "https://localhost"

    # Outgoing email over SMTP. The defaults point at the Mailpit container (INF-05), which
    # keeps every email in a web inbox instead of delivering it.
    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    mail_from: str = "no-reply@wozu.local"
    # Optional: when set, emails go out through Brevo's API (real inboxes) instead of SMTP.
    brevo_api_key: str = ""

    # Redis: WebSocket tickets, live events between API processes (pub/sub) and who is online.
    # The default is the "redis" service of the team's Docker Compose (no password, database 0).
    # The background queue lives there too: confirming a video puts a moderation task on it,
    # and the Celery worker takes it off (BE-07, BE-29).
    redis_url: str = "redis://redis:6379/0"

    # File storage: MinIO, the "minio" container (INF-04). The API itself talks to MinIO inside
    # the Docker network, over plain HTTP, at minio_endpoint.
    minio_endpoint: str = "minio:9000"
    # The upload and download links we hand out are signed for this public address instead:
    # the browser opens https://localhost/files/<key>, and the proxy passes it on to MinIO.
    minio_external_endpoint: str = "https://localhost"
    minio_bucket: str = "files"
    # Given here, so signing a link never needs to ask MinIO for it.
    minio_region: str = "us-east-1"
    # docker-compose.yml sets them from MINIO_ROOT_USER and MINIO_ROOT_PASSWORD (INF-04).
    # Empty means the links are not signed and MinIO refuses them.
    minio_access_key: str = ""
    minio_secret_key: str = ""

    # avatar_url of a user who has no picture (BE-08). By default a path on our own site, where
    # the API serves a plain grey picture; a full address (https://...) works too.
    default_avatar_url: str = "/api/media/avatar/default.svg"

    # Turing Duel matchmaking & room timings (BE-27). Defaults follow DOC-08; tests override
    # these cleanly to exercise fast timers, deterministic bot probabilities, and races.
    game_bot_probability: float = Field(default=0.7, ge=0.0, le=1.0)
    game_bot_min_delay_sec: float = Field(default=10.0, ge=0.0)
    game_bot_max_delay_sec: float = Field(default=30.0, ge=0.0)
    game_wait_timeout_sec: float = Field(default=180.0, gt=0.0)
    game_discussion_sec: float = Field(default=120.0, gt=0.0)
    game_voting_sec: float = Field(default=45.0, gt=0.0)
    game_tick_interval_sec: float = Field(default=0.5, gt=0.0)
    game_bot_chat_min_delay_sec: float = Field(default=4.0, ge=0.0)
    game_bot_chat_max_delay_sec: float = Field(default=15.0, ge=0.0)
    # The server clock of the game rooms (run_scheduler, started in the app's lifespan).
    # Off in tests that do not exercise game timers.
    game_scheduler_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    """Read the environment once and reuse the result."""
    return Settings()
