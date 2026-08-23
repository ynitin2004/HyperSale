from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    log_level: str = "INFO"
    service_name: str = "hypersale-api"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/hypersale"
    database_pool_size: int = 5
    database_max_overflow: int = 5
    database_pool_recycle_seconds: int = 900

    # Supabase signs with JWKS keys on new projects and a shared HS256 secret on legacy ones.
    # Exactly one of these must be set; the verifier refuses to guess.
    supabase_jwks_url: str | None = None
    supabase_jwt_secret: str | None = None
    supabase_jwt_audience: str = "authenticated"
    supabase_jwt_issuer: str | None = None
    jwt_leeway_seconds: int = 30
    jwks_cache_seconds: int = 600

    openai_api_key: str | None = None
    openai_realtime_model: str = "gpt-realtime-2.1"
    openai_safety_identifier_salt: str | None = None

    # Cost rates stay zero until a real session measures them. An unmeasured rate is
    # recorded as `rate_missing` rather than invented, so cost reports stay honest.
    realtime_audio_input_microusd_per_minute: int = 0
    realtime_audio_output_microusd_per_minute: int = 0

    worker_id: str = "worker-local"
    worker_batch_size: int = 5
    worker_poll_seconds: float = 1.0
    worker_stall_seconds: int = 120
    job_max_attempts: int = 5
    job_backoff_base_seconds: int = 5
    job_backoff_max_seconds: int = 900

    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.1
    otel_exporter_otlp_endpoint: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def auth_configured(self) -> bool:
        return bool(self.supabase_jwks_url or self.supabase_jwt_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
