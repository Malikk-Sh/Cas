from fastapi.testclient import TestClient

from app import app


def test_vercel_health_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["service"] == "cas-arbitrage-scanner"
    assert payload["runtime"] == "vercel"
