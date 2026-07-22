from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Inventory Service"
    app_version: str = "1.0.0"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://inventory:inventory@localhost:5432/inventory"

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        """Convert Railway/Heroku-style postgres URLs to async SQLAlchemy format."""
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value
    database_echo: bool = False

    log_level: str = "INFO"
    log_json: bool = True

    default_page_size: int = 20
    max_page_size: int = 100
    default_low_stock_threshold: int = 10

    idempotency_ttl_hours: int = 24


@lru_cache
def get_settings() -> Settings:
    return Settings()
