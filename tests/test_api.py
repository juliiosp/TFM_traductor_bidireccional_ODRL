import os

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/odrl_api_test.db")

from fastapi.testclient import TestClient

from app.api.app import app


VALID_POLICY = {
    "@context": "http://www.w3.org/ns/odrl.jsonld",
    "@type": "Set",
    "uid": "http://example.com/policy/TestPolicy",
    "permission": [
        {
            "target": "http://example.com/asset/Dataset1",
            "assignee": "http://example.com/party/CompanyA",
            "action": "use",
        }
    ],
}


def test_health_and_readiness() -> None:
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        ready = client.get("/ready")
        assert ready.status_code == 200
        assert ready.json()["database"] == "ok"


def test_validate_endpoint() -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/validate", json={"policy": VALID_POLICY})

    assert response.status_code == 200
    assert response.json()["validation"]["valid"] is True


def test_validate_endpoint_rejects_invalid_policy() -> None:
    invalid = {**VALID_POLICY, "permission": [{**VALID_POLICY["permission"][0]}]}
    invalid["permission"][0].pop("action")

    with TestClient(app) as client:
        response = client.post("/api/v1/validate", json={"policy": invalid})

    assert response.status_code == 200
    assert response.json()["validation"]["valid"] is False


def test_history_can_be_cleared_and_read() -> None:
    with TestClient(app) as client:
        deleted = client.delete("/api/v1/history")
        history = client.get("/api/v1/history")

    assert deleted.status_code == 200
    assert deleted.json()["deleted"] >= 0
    assert history.status_code == 200
    assert history.json()["items"] == []
