"""
Pydantic schemas for InsureChain VoiceGuard demonstration scenarios (Phase 6 Stage 3).
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DemoScenarioDefinition(BaseModel):
    scenario_id: str = Field(..., description="Unique scenario identifier, e.g. DEMO-SCN-01")
    title: str = Field(..., description="Human-readable title of scenario")
    category: str = Field(..., description="Insurance category: VEHICLE, MEDICAL, GENERIC, GOVERNANCE")
    policy_name: str = Field(..., description="Applicable insurance policy")
    description: str = Field(..., description="Short summary of scenario flow")
    input_conditions: str = Field(..., description="Claim parameters and injected conditions")
    engine_evaluation: str = Field(..., description="Deterministic rules evaluated by engine")
    expected_outcome: str = Field(..., description="Expected overall eligibility/integrity outcome")
    stage2_analysis_status: Optional[str] = Field(None, description="Expected OCR/Invoice Auditor status")


class DemoSeedResult(BaseModel):
    scenario_id: str
    seeded: bool
    status: str
    claim_id: Optional[str] = None
    session_id: Optional[str] = None
    policy_id: Optional[str] = None
    customer_email: Optional[str] = None
    message: str


class DemoCleanupRequest(BaseModel):
    confirm: bool = Field(..., description="Explicit confirmation required to execute destructive cleanup")


class DemoCleanupResult(BaseModel):
    success: bool
    deleted_records: Dict[str, int]
    message: str


class DemoTamperCheckResult(BaseModel):
    scenario_id: str
    authentic_root: str
    leaf_count: int
    tested_leaf_index: int
    tested_event_id: str
    authentic_proof_valid: bool
    tampered_leaf_hash: str
    tampered_proof_valid: bool
    tamper_detected: bool
    verification_explanation: str

