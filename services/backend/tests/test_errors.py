"""Every failure leaves through the same envelope, or clients cannot handle errors once."""
from fastapi.testclient import TestClient


def _assert_envelope(body: dict, code: str) -> None:
    assert set(body) == {"error"}
    error = body["error"]
    assert error["code"] == code
    assert error["message"]
    assert error["request_id"]


def test_unknown_route_uses_the_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    _assert_envelope(response.json(), "http_404")


def test_protected_route_without_a_token_is_401(client: TestClient) -> None:
    response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    _assert_envelope(response.json(), "missing_token")


def test_error_response_carries_the_caller_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/me", headers={"X-Request-ID": "trace-err"})
    assert response.json()["error"]["request_id"] == "trace-err"


def test_public_config_never_exposes_provider_keys(client: TestClient) -> None:
    body = client.get("/api/v1/config").json()
    assert set(body) == {"environment", "auth_configured", "realtime_configured", "voice_provider",
                         "scoring_provider", "request_id"}
