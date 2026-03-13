from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://assistant:assistant@localhost:5432/assistant"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "changeme"
    openrouter_api_key: str = ""
    openrouter_model: str = "google/gemini-3.1-flash-lite-preview"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    worker_enabled: bool = False
    log_level: str = "info"
    cors_origins: list[str] = ["*"]

    model_config = {"env_prefix": "", "case_sensitive": False}


@lru_cache
def get_settings() -> Settings:
    return Settings()
