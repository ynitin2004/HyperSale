"""The one place the Anthropic SDK is constructed (RULES: no provider SDK outside adapters/).

Credentials and the optional gateway base URL are configuration. A gateway that speaks the
Anthropic Messages API (Agent Router, OpenRouter's Anthropic endpoint, a corporate proxy)
is reached by setting ANTHROPIC_BASE_URL and whichever of ANTHROPIC_API_KEY (x-api-key) or
ANTHROPIC_AUTH_TOKEN (bearer) that gateway expects. Nothing else in the codebase knows
which one is in use.

D33: a Claude model goes direct to api.anthropic.com when CLAUDE_API_KEY is set; every other
model, and Claude without that key, uses the gateway credentials above.
"""
from __future__ import annotations

import anthropic

from app.adapters.llm.models import is_claude
from app.config import Settings, get_settings
from app.errors import AppError


def _kwargs(settings: Settings) -> dict:
    if not (settings.anthropic_api_key or settings.anthropic_auth_token):
        raise AppError(
            "llm_not_configured",
            "Set ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN to enable scoring",
            status_code=503,
        )
    kwargs: dict = {"max_retries": 1, "timeout": settings.anthropic_timeout_seconds}
    if settings.anthropic_base_url:
        kwargs["base_url"] = settings.anthropic_base_url
    if settings.anthropic_api_key:
        kwargs["api_key"] = settings.anthropic_api_key
    if settings.anthropic_auth_token:
        kwargs["auth_token"] = settings.anthropic_auth_token
    return kwargs


def uses_direct_route(settings: Settings, model_id: str | None) -> bool:
    return bool(model_id and is_claude(model_id) and settings.claude_api_key)


def build_client(settings: Settings | None = None, model_id: str | None = None) -> anthropic.Anthropic:
    settings = settings or get_settings()
    if uses_direct_route(settings, model_id):
        return anthropic.Anthropic(api_key=settings.claude_api_key, max_retries=1,
                                   timeout=settings.anthropic_timeout_seconds)
    return anthropic.Anthropic(**_kwargs(settings))


def build_async_client(settings: Settings | None = None) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(**_kwargs(settings or get_settings()))
