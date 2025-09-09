"""Application settings, loaded from environment / .env (prefix ORBIT_)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ORBIT_", env_file=".env", extra="ignore")

    # Database (async SQLAlchemy URL, e.g. postgresql+asyncpg://user:pass@host/db)
    database_url: str = "postgresql+asyncpg://orbit:orbit@localhost:5432/orbit"

    # Auth / JWT
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Rate limiting (requests per window, applied to auth + write endpoints)
    rate_limit: str = "100/minute"
    auth_rate_limit: str = "10/minute"

    # App
    app_name: str = "orbit"
    debug: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
