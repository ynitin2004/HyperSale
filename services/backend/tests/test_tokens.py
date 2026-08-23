"""Token verification negative cases.

These are the tests that matter most: a verifier only ever fails open, and every one of
these cases is a way an attacker reaches another tenant's data.
"""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from app.errors import AppError, AuthError
from app.modules.identity.tokens import TokenVerifier
from tests.conftest import settings_for

SECRET = "test-signing-secret-at-least-32-bytes-long"
USER_ID = str(uuid4())


def make_token(
    *,
    secret: str = SECRET,
    algorithm: str = "HS256",
    audience: str | None = "authenticated",
    subject: str | None = USER_ID,
    expires_in: timedelta = timedelta(minutes=10),
    **extra: object,
) -> str:
    claims: dict[str, object] = {"exp": datetime.now(UTC) + expires_in, **extra}
    if subject is not None:
        claims["sub"] = subject
    if audience is not None:
        claims["aud"] = audience
    return jwt.encode(claims, secret, algorithm=algorithm)


@pytest.fixture
def verifier() -> TokenVerifier:
    return TokenVerifier(settings_for(supabase_jwt_secret=SECRET))


async def test_valid_token_yields_claims(verifier: TokenVerifier) -> None:
    claims = await verifier.verify(make_token(email="rep@example.com"))
    assert str(claims.user_id) == USER_ID
    assert claims.email == "rep@example.com"
    assert claims.expires_at > datetime.now(UTC)


async def test_expired_token_is_rejected(verifier: TokenVerifier) -> None:
    token = make_token(expires_in=timedelta(minutes=-10))
    with pytest.raises(AuthError) as exc:
        await verifier.verify(token)
    assert exc.value.code == "token_expired"


async def test_wrong_audience_is_rejected(verifier: TokenVerifier) -> None:
    with pytest.raises(AuthError) as exc:
        await verifier.verify(make_token(audience="some-other-service"))
    assert exc.value.code == "invalid_audience"


async def test_wrong_signing_secret_is_rejected(verifier: TokenVerifier) -> None:
    with pytest.raises(AuthError) as exc:
        await verifier.verify(make_token(secret="not-the-real-secret"))
    assert exc.value.code == "invalid_token"


async def test_missing_subject_is_rejected(verifier: TokenVerifier) -> None:
    with pytest.raises(AuthError) as exc:
        await verifier.verify(make_token(subject=None))
    assert exc.value.code == "invalid_token"


async def test_non_uuid_subject_is_rejected(verifier: TokenVerifier) -> None:
    with pytest.raises(AuthError) as exc:
        await verifier.verify(make_token(subject="service-account"))
    assert exc.value.code == "invalid_subject"


async def test_garbage_token_is_rejected(verifier: TokenVerifier) -> None:
    with pytest.raises(AuthError) as exc:
        await verifier.verify("not-a-jwt")
    assert exc.value.code == "invalid_token"


async def test_unsigned_token_is_rejected(verifier: TokenVerifier) -> None:
    """`alg: none` is the classic downgrade; the allow-list must reject it before decode."""
    token = jwt.encode({"sub": USER_ID, "aud": "authenticated"}, key=None, algorithm="none")
    with pytest.raises(AuthError) as exc:
        await verifier.verify(token)
    assert exc.value.code == "unsupported_algorithm"


async def test_hmac_token_is_rejected_when_the_project_uses_jwks() -> None:
    """Algorithm confusion: an HS256 token must not be verified against a JWKS project."""
    verifier = TokenVerifier(
        settings_for(supabase_jwks_url="https://project.supabase.co/auth/v1/.well-known/jwks.json")
    )
    with pytest.raises(AuthError) as exc:
        await verifier.verify(make_token())
    assert exc.value.code == "unsupported_algorithm"


async def test_wrong_issuer_is_rejected() -> None:
    verifier = TokenVerifier(
        settings_for(supabase_jwt_secret=SECRET, supabase_jwt_issuer="https://expected.example")
    )
    with pytest.raises(AuthError) as exc:
        await verifier.verify(make_token(iss="https://attacker.example"))
    assert exc.value.code == "invalid_issuer"


async def test_unconfigured_auth_fails_closed() -> None:
    """No configuration must never mean "let everyone in"."""
    verifier = TokenVerifier(settings_for())
    with pytest.raises(AppError) as exc:
        await verifier.verify(make_token())
    assert exc.value.code == "auth_not_configured"
    assert exc.value.status_code == 503
