from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/hypersale"
    supabase_jwks_url: str | None = None
    supabase_jwt_audience: str = "authenticated"
    openai_api_key: str | None = None
    openai_realtime_model: str = "gpt-realtime-2.1"
    openai_safety_identifier_salt: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()

