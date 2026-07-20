"""
InsureLite - Minimal Insurance Tech Backend
--------------------------------------------
A small Flask service simulating a claims/policy backend for a
'containerize -> ACR -> AKS' DevOps exercise.

Design notes:
- In-memory data store (no DB) to keep the exercise focused on
  containerization/deployment, not persistence.
- /api/premium/quote makes an INTERNAL API call (via requests) to
  /api/risk/score on the same running service, simulating how a
  real insurance backend might chain a "risk engine" call before
  returning a premium quote. This satisfies the "few internal API
  calls" requirement without needing external dependencies.
"""

import os
import uuid
from datetime import UTC, datetime

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory "database"
# ---------------------------------------------------------------------------
POLICIES = {
    "POL-1001": {
        "policy_id": "POL-1001",
        "holder_name": "Asha Rao",
        "policy_type": "auto",
        "vehicle_value": 850000,
        "driver_age": 34,
        "prior_claims": 0,
        "status": "active",
    },
    "POL-1002": {
        "policy_id": "POL-1002",
        "holder_name": "Vikram Shah",
        "policy_type": "health",
        "coverage_amount": 500000,
        "driver_age": None,
        "prior_claims": 1,
        "status": "active",
    },
}

CLAIMS = {
    "CLM-5001": {
        "claim_id": "CLM-5001",
        "policy_id": "POL-1001",
        "status": "under_review",
        "amount_claimed": 45000,
        "filed_on": "2026-06-12",
    }
}

# Base URL the app uses to call *itself* for internal chained calls.
# In Kubernetes this stays localhost because the risk-engine logic
# lives in the same pod/process - this just demonstrates the pattern.
INTERNAL_BASE_URL = os.environ.get("INTERNAL_BASE_URL", "http://localhost:5000")


# ---------------------------------------------------------------------------
# Health check (required by Kubernetes liveness/readiness probes)
# ---------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "insurelite", "time": datetime.now(UTC).isoformat()}), 200


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------
@app.route("/api/policies", methods=["GET"])
def list_policies():
    return jsonify(list(POLICIES.values())), 200


@app.route("/api/policies/<policy_id>", methods=["GET"])
def get_policy(policy_id):
    policy = POLICIES.get(policy_id)
    if not policy:
        return jsonify({"error": "policy not found"}), 404
    return jsonify(policy), 200


@app.route("/api/policies", methods=["POST"])
def create_policy():
    data = request.get_json(force=True, silent=True) or {}
    required = {"holder_name", "policy_type"}
    if not required.issubset(data):
        return jsonify({"error": f"missing fields, required: {sorted(required)}"}), 400

    policy_id = f"POL-{uuid.uuid4().hex[:6].upper()}"
    policy = {
        "policy_id": policy_id,
        "holder_name": data["holder_name"],
        "policy_type": data["policy_type"],
        "vehicle_value": data.get("vehicle_value"),
        "coverage_amount": data.get("coverage_amount"),
        "driver_age": data.get("driver_age"),
        "prior_claims": data.get("prior_claims", 0),
        "status": "active",
    }
    POLICIES[policy_id] = policy
    return jsonify(policy), 201


# ---------------------------------------------------------------------------
# Risk engine (internal service-style endpoint)
# ---------------------------------------------------------------------------
@app.route("/api/risk/score", methods=["POST"])
def risk_score():
    """Pure calculation endpoint. Called internally by /api/premium/quote."""
    data = request.get_json(force=True, silent=True) or {}
    prior_claims = data.get("prior_claims", 0) or 0
    driver_age = data.get("driver_age")

    score = 20  # base risk score
    score += prior_claims * 15

    if driver_age is not None:
        if driver_age < 25:
            score += 20
        elif driver_age > 60:
            score += 10

    score = min(score, 100)
    band = "low" if score < 30 else "medium" if score < 60 else "high"
    return jsonify({"risk_score": score, "risk_band": band}), 200


# ---------------------------------------------------------------------------
# Premium quote - demonstrates an INTERNAL API call to /api/risk/score
# ---------------------------------------------------------------------------
@app.route("/api/policies/<policy_id>/premium", methods=["GET"])
def premium_quote(policy_id):
    policy = POLICIES.get(policy_id)
    if not policy:
        return jsonify({"error": "policy not found"}), 404

    # --- Internal API call to the risk engine ---
    try:
        risk_resp = requests.post(
            f"{INTERNAL_BASE_URL}/api/risk/score",
            json={
                "prior_claims": policy.get("prior_claims", 0),
                "driver_age": policy.get("driver_age"),
            },
            timeout=3,
        )
        risk_resp.raise_for_status()
        risk_data = risk_resp.json()
    except requests.RequestException as exc:
        return jsonify({"error": "risk engine unavailable", "detail": str(exc)}), 502

    base_value = policy.get("vehicle_value") or policy.get("coverage_amount") or 100000
    risk_multiplier = 1 + (risk_data["risk_score"] / 100)
    premium = round(base_value * 0.02 * risk_multiplier, 2)

    return jsonify({
        "policy_id": policy_id,
        "base_value": base_value,
        "risk_score": risk_data["risk_score"],
        "risk_band": risk_data["risk_band"],
        "annual_premium": premium,
    }), 200


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------
@app.route("/api/claims/<claim_id>/status", methods=["GET"])
def claim_status(claim_id):
    claim = CLAIMS.get(claim_id)
    if not claim:
        return jsonify({"error": "claim not found"}), 404
    return jsonify(claim), 200


@app.route("/api/claims", methods=["POST"])
def file_claim():
    data = request.get_json(force=True, silent=True) or {}
    if "policy_id" not in data or data["policy_id"] not in POLICIES:
        return jsonify({"error": "valid policy_id is required"}), 400

    claim_id = f"CLM-{uuid.uuid4().hex[:6].upper()}"
    claim = {
        "claim_id": claim_id,
        "policy_id": data["policy_id"],
        "status": "filed",
        "amount_claimed": data.get("amount_claimed", 0),
        "filed_on": datetime.now(UTC).strftime("%Y-%m-%d"),
    }
    CLAIMS[claim_id] = claim
    return jsonify(claim), 201


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
