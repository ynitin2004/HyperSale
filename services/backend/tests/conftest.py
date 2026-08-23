from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app


@pytest.fixture(autouse=True)
def clean_settings_cache() -> Iterator[None]:
    """Settings are cached process-wide; no test may leak configuration into the next."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def settings_for(**overrides: object) -> Settings:
    """Explicit settings so a developer's local .env cannot change a test outcome."""
    base: dict[str, object] = {
        "app_env": "test",
        "supabase_jwks_url": None,
        "supabase_jwt_secret": None,
        "supabase_jwt_issuer": None,
        "supabase_jwt_audience": "authenticated",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]
