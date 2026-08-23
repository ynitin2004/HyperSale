"""Supabase access-token verification.

Two signing modes exist in the wild: JWKS (asymmetric, current projects) and a shared
HS256 secret (legacy projects). The mode is chosen from configuration, never from the
token header, so a forged `alg` cannot downgrade an asymmetric project to HMAC.
"""
import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import jwt
from jwt import PyJWK, PyJWKSet

from app.config import Settings, get_settings
from app.errors import AppError, AuthError

ASYMMETRIC_ALGORITHMS = frozenset({"RS256", "ES256"})
SYMMETRIC_ALGORITHMS = frozenset({"HS256"})
JWKS_TIMEOUT_SECONDS = 5.0
# Floor between forced refreshes so unknown-kid tokens cannot be used to hammer Supabase.
MIN_FORCED_REFRESH_SECONDS = 30.0


@dataclass(frozen=True)
class TokenClaims:
    user_id: UUID
    email: str | None
    session_id: str | None
    expires_at: datetime
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


class JwksCache:
    """In-process JWKS cache with TTL and rate-limited rotation refresh."""

    def __init__(self, url: str, ttl_seconds: int) -> None:
        self._url = url
        self._ttl = ttl_seconds
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    def _is_fresh(self) -> bool:
        return bool(self._keys) and (time.monotonic() - self._fetched_at) < self._ttl

    async def _refresh(self) -> None:
        async with httpx.AsyncClient(timeout=JWKS_TIMEOUT_SECONDS) as client:
            response = await client.get(self._url)
        if response.is_error:
            raise AppError(
                "jwks_unavailable",
                "Identity provider keys are temporarily unavailable",
                status_code=503,
            )
        key_set = PyJWKSet.from_dict(response.json())
        self._keys = {key.key_id: key for key in key_set.keys if key.key_id}
        self._fetched_at = time.monotonic()

    async def get(self, kid: str) -> PyJWK:
        async with self._lock:
            if not self._is_fresh():
                await self._refresh()
            key = self._keys.get(kid)
            if key is None and (time.monotonic() - self._fetched_at) >= MIN_FORCED_REFRESH_SECONDS:
                # Signing keys rotate; one bounded re-fetch covers the rotation window.
                await self._refresh()
                key = self._keys.get(kid)
        if key is None:
            raise AuthError("unknown_signing_key", "Token was signed by an unrecognised key")
        return key


class TokenVerifier:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._jwks: JwksCache | None = (
            JwksCache(self._settings.supabase_jwks_url, self._settings.jwks_cache_seconds)
            if self._settings.supabase_jwks_url
            else None
        )

    async def verify(self, token: str) -> TokenClaims:
        settings = self._settings
        if not settings.auth_configured:
            raise AppError(
                "auth_not_configured",
                "Set SUPABASE_JWKS_URL or SUPABASE_JWT_SECRET to enable authentication",
                status_code=503,
            )
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AuthError("invalid_token", "Malformed access token") from exc

        algorithm = header.get("alg", "")
        if self._jwks is not None:
            if algorithm not in ASYMMETRIC_ALGORITHMS:
                raise AuthError("unsupported_algorithm", f"Algorithm {algorithm!r} is not accepted")
            kid = header.get("kid")
            if not kid:
                raise AuthError("invalid_token", "Access token is missing a key id")
            key: Any = (await self._jwks.get(kid)).key
            algorithms = sorted(ASYMMETRIC_ALGORITHMS)
        else:
            if algorithm not in SYMMETRIC_ALGORITHMS:
                raise AuthError("unsupported_algorithm", f"Algorithm {algorithm!r} is not accepted")
            key = settings.supabase_jwt_secret
            algorithms = sorted(SYMMETRIC_ALGORITHMS)

        options = {"require": ["exp", "sub"], "verify_aud": bool(settings.supabase_jwt_audience)}
        try:
            payload = jwt.decode(
                token,
                key=key,
                algorithms=algorithms,
                audience=settings.supabase_jwt_audience or None,
                issuer=settings.supabase_jwt_issuer,
                leeway=settings.jwt_leeway_seconds,
                options=options,
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthError("token_expired", "Access token has expired") from exc
        except jwt.InvalidAudienceError as exc:
            raise AuthError("invalid_audience", "Access token audience is not accepted") from exc
        except jwt.InvalidIssuerError as exc:
            raise AuthError("invalid_issuer", "Access token issuer is not accepted") from exc
        except jwt.PyJWTError as exc:
            raise AuthError("invalid_token", "Access token could not be verified") from exc

        return _to_claims(payload)


def _to_claims(payload: dict[str, Any]) -> TokenClaims:
    try:
        user_id = UUID(str(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise AuthError("invalid_subject", "Access token subject is not a user id") from exc
    return TokenClaims(
        user_id=user_id,
        email=payload.get("email"),
        session_id=payload.get("session_id"),
        expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=UTC),
        raw=payload,
    )


_verifier: TokenVerifier | None = None


def get_verifier() -> TokenVerifier:
    global _verifier
    if _verifier is None:
        _verifier = TokenVerifier()
    return _verifier


def reset_verifier() -> None:
    """Test seam: drop the cached verifier after settings change."""
    global _verifier
    _verifier = None
