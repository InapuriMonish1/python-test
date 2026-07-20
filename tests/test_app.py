"""
Basic tests for InsureLite API.
Run with: pytest tests/
"""
import pytest
from app import main


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_list_policies(client):
    resp = client.get("/api/policies")
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), list)
    assert len(resp.get_json()) >= 1


def test_get_policy_not_found(client):
    resp = client.get("/api/policies/DOES-NOT-EXIST")
    assert resp.status_code == 404


def test_create_policy(client):
    resp = client.post("/api/policies", json={
        "holder_name": "Test User",
        "policy_type": "auto",
        "vehicle_value": 200000,
        "driver_age": 30,
    })
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["holder_name"] == "Test User"
    assert body["policy_id"].startswith("POL-")


def test_risk_score(client):
    resp = client.post("/api/risk/score", json={"prior_claims": 2, "driver_age": 20})
    assert resp.status_code == 200
    body = resp.get_json()
    assert "risk_score" in body
    assert body["risk_band"] in {"low", "medium", "high"}


def test_file_claim_invalid_policy(client):
    resp = client.post("/api/claims", json={"policy_id": "NOPE"})
    assert resp.status_code == 400
