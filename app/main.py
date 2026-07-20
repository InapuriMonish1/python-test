"""
InsureLite - Minimal Insurance Tech Backend (FastAPI version)"""
import os
import uuid
from datetime import UTC, datetime
from typing import Literal, Optional
 
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
 
app = FastAPI(title="InsureLite", version="1.0.0")
 
# ---------------------------------------------------------------------------
# In-memory "database"
# ---------------------------------------------------------------------------
POLICIES: dict[str, dict] = {
    "POL-1001": {
        "policy_id": "POL-1001",
        "holder_name": "Asha Rao",
        "policy_type": "auto",
        "vehicle_value": 850000,
        "coverage_amount": None,
        "driver_age": 34,
        "prior_claims": 0,
        "status": "active",
    },
    "POL-1002": {
        "policy_id": "POL-1002",
        "holder_name": "Vikram Shah",
        "policy_type": "health",
        "vehicle_value": None,
        "coverage_amount": 500000,
        "driver_age": None,
        "prior_claims": 1,
        "status": "active",
    },
}
 
CLAIMS: dict[str, dict] = {
    "CLM-5001": {
        "claim_id": "CLM-5001",
        "policy_id": "POL-1001",
        "status": "under_review",
        "amount_claimed": 45000,
        "filed_on": "2026-06-12",
    }
}
 
INTERNAL_BASE_URL = os.environ.get("INTERNAL_BASE_URL", "http://localhost:5000")
 
 
# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
class Policy(BaseModel):
    policy_id: str
    holder_name: str
    policy_type: str
    vehicle_value: Optional[float] = None
    coverage_amount: Optional[float] = None
    driver_age: Optional[int] = None
    prior_claims: int = 0
    status: str = "active"
 
 
class PolicyCreate(BaseModel):
    holder_name: str
    policy_type: str
    vehicle_value: Optional[float] = None
    coverage_amount: Optional[float] = None
    driver_age: Optional[int] = None
    prior_claims: int = 0
 
 
class RiskInput(BaseModel):
    prior_claims: int = 0
    driver_age: Optional[int] = None
 
 
class RiskOutput(BaseModel):
    risk_score: int
    risk_band: Literal["low", "medium", "high"]
 
 
class PremiumQuote(BaseModel):
    policy_id: str
    base_value: float
    risk_score: int
    risk_band: str
    annual_premium: float
 
 
class Claim(BaseModel):
    claim_id: str
    policy_id: str
    status: str
    amount_claimed: float = 0
    filed_on: str
 
 
class ClaimCreate(BaseModel):
    policy_id: str
    amount_claimed: float = Field(default=0, ge=0)
 
 
# ---------------------------------------------------------------------------
# Health check (Kubernetes liveness/readiness probe)
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "service": "insurelite", "time": datetime.now(UTC).isoformat()}
 
 
# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------
@app.get("/api/policies", response_model=list[Policy])
def list_policies():
    return list(POLICIES.values())
 
 
@app.get("/api/policies/{policy_id}", response_model=Policy)
def get_policy(policy_id: str):
    policy = POLICIES.get(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="policy not found")
    return policy
 
 
@app.post("/api/policies", response_model=Policy, status_code=201)
def create_policy(body: PolicyCreate):
    policy_id = f"POL-{uuid.uuid4().hex[:6].upper()}"
    policy = {
        "policy_id": policy_id,
        "holder_name": body.holder_name,
        "policy_type": body.policy_type,
        "vehicle_value": body.vehicle_value,
        "coverage_amount": body.coverage_amount,
        "driver_age": body.driver_age,
        "prior_claims": body.prior_claims,
        "status": "active",
    }
    POLICIES[policy_id] = policy
    return policy
 
 
# ---------------------------------------------------------------------------
# Risk engine (internal service-style endpoint)
# ---------------------------------------------------------------------------
@app.post("/api/risk/score", response_model=RiskOutput)
def risk_score(body: RiskInput):
    score = 20
    score += (body.prior_claims or 0) * 15
 
    if body.driver_age is not None:
        if body.driver_age < 25:
            score += 20
        elif body.driver_age > 60:
            score += 10
 
    score = min(score, 100)
    band = "low" if score < 30 else "medium" if score < 60 else "high"
    return {"risk_score": score, "risk_band": band}
 
 
# ---------------------------------------------------------------------------
# Premium quote - internal API call to /api/risk/score
# ---------------------------------------------------------------------------
@app.get("/api/policies/{policy_id}/premium", response_model=PremiumQuote)
async def premium_quote(policy_id: str):
    policy = POLICIES.get(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="policy not found")
 
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            risk_resp = await client.post(
                f"{INTERNAL_BASE_URL}/api/risk/score",
                json={
                    "prior_claims": policy.get("prior_claims", 0),
                    "driver_age": policy.get("driver_age"),
                },
            )
            risk_resp.raise_for_status()
            risk_data = risk_resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"risk engine unavailable: {exc}") from exc
 
    base_value = policy.get("vehicle_value") or policy.get("coverage_amount") or 100000
    risk_multiplier = 1 + (risk_data["risk_score"] / 100)
    premium = round(base_value * 0.02 * risk_multiplier, 2)
 
    return {
        "policy_id": policy_id,
        "base_value": base_value,
        "risk_score": risk_data["risk_score"],
        "risk_band": risk_data["risk_band"],
        "annual_premium": premium,
    }
 
 
# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------
@app.get("/api/claims/{claim_id}/status", response_model=Claim)
def claim_status(claim_id: str):
    claim = CLAIMS.get(claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="claim not found")
    return claim
 
 
@app.post("/api/claims", response_model=Claim, status_code=201)
def file_claim(body: ClaimCreate):
    if body.policy_id not in POLICIES:
        raise HTTPException(status_code=400, detail="valid policy_id is required")
 
    claim_id = f"CLM-{uuid.uuid4().hex[:6].upper()}"
    claim = {
        "claim_id": claim_id,
        "policy_id": body.policy_id,
        "status": "filed",
        "amount_claimed": body.amount_claimed,
        "filed_on": datetime.now(UTC).strftime("%Y-%m-%d"),
    }
    CLAIMS[claim_id] = claim
    return claim
 
 
if __name__ == "__main__":
    import uvicorn
 
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)
 
# ---------------------------------------------------------------------------
# Production note: replace the per-request httpx.AsyncClient() in
# premium_quote with a client created once in a lifespan handler and
# stored on app.state, then reused across requests. Cheap to do,
# skipped here to keep this a direct line-for-line port of the Flask
# version rather than a redesign.
# ---------------------------------------------------------------------------
 
