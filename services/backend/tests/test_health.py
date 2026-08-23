from fastapi.testclient import TestClient


def test_health_is_live_without_a_database(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_echoes_a_supplied_request_id(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "trace-abc"})
    assert response.headers["X-Request-ID"] == "trace-abc"
    assert response.json()["request_id"] == "trace-abc"


def test_health_generates_a_request_id_when_absent(client: TestClient) -> None:
    response = client.get("/health")
    assert response.headers["X-Request-ID"]
    assert response.headers["X-Request-ID"] == response.json()["request_id"]


def test_oversized_request_id_is_truncated(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "x" * 500})
    assert len(response.headers["X-Request-ID"]) == 120
