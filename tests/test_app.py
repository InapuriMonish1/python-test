"""
Basic tests for InsureLite API (FastAPI version).
Run with: pytest tests/
"""
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    # FastAPI has no config["TESTING"] flag to set - TestClient wraps
    # the ASGI app directly and runs requests synchronously against it,
    # no real socket involved. Nothing to toggle.
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="session")
def live_server():
    # test_premium_quote_internal_call needs a REAL socket: the route
    # under test makes its own httpx call out to INTERNAL_BASE_URL
    # (default http://localhost:5000), and that call bypasses
    # TestClient's in-process ASGI transport entirely. Without an actual
    # server listening, the request fails with a connection error, which
    # the route turns into a 502 - that's exactly what happened the
    # first time this test ran. That's a real gap in the FastAPI port,
    # not a test artifact: swapping requests -> httpx.AsyncClient didn't
    # change that the self-call needs the process to be reachable over
    # the network, which isn't true inside TestClient alone.
    config = uvicorn.Config(app, host="127.0.0.1", port=5000, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(50):
        try:
            httpx.get("http://127.0.0.1:5000/health", timeout=0.2)
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        pytest.fail("live server did not start in time")

    yield
    server.should_exit = True
    thread.join(timeout=2)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_list_policies(client):
    resp = client.get("/api/policies")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert len(resp.json()) >= 1


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
    body = resp.json()
    assert body["holder_name"] == "Test User"
    assert body["policy_id"].startswith("POL-")


def test_risk_score(client):
    resp = client.post("/api/risk/score", json={"prior_claims": 2, "driver_age": 20})
    assert resp.status_code == 200
    body = resp.json()
    assert "risk_score" in body
    assert body["risk_band"] in {"low", "medium", "high"}


def test_file_claim_invalid_policy(client):
    # policy_id is present and well-typed, just not a real policy, so this
    # still hits our own `if body.policy_id not in POLICIES` check and
    # returns 400 same as Flask did. Contrast with the next test below.
    resp = client.post("/api/claims", json={"policy_id": "NOPE"})
    assert resp.status_code == 400


def test_file_claim_missing_policy_id(client):
    # NEW vs. the Flask suite: omitting a required field entirely never
    # reaches our route code. Pydantic rejects it first with 422, not 400.
    # The old test suite had no equivalent case because Flask's manual
    # `if "policy_id" not in data` handled both "missing" and "invalid"
    # the same way (400). FastAPI splits them into two different codes -
    # this test exists so that split doesn't go unnoticed.
    resp = client.post("/api/claims", json={"amount_claimed": 500})
    assert resp.status_code == 422


def test_premium_quote_internal_call(client, live_server):
    # NEW: the original suite never exercised the chained internal call
    # that hits /api/risk/score. Worth having explicit coverage since
    # that's the one endpoint whose behavior depends on network I/O
    # (INTERNAL_BASE_URL) rather than pure in-process logic. Needs
    # live_server - see that fixture for why TestClient alone isn't enough.
    resp = client.get("/api/policies/POL-1001/premium")
    assert resp.status_code == 200
    body = resp.json()
    assert body["policy_id"] == "POL-1001"
    assert "annual_premium" in body
    assert body["risk_band"] in {"low", "medium", "high"}