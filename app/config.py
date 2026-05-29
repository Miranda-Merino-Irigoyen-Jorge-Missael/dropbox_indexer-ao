# app/config.py
from typing import Optional
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    # Token Service
    token_service_url: str = "https://accesstokendropbox-223080314602.us-central1.run.app"
    api_secret_key: str = ""
    # Database
    database_url: str = "postgresql+asyncpg://user:pass@localhost:5432/dropbox_index"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Application
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

@lru_cache()
def get_settings() -> Settings:
    return Settings()