"""
Phase 5 Comprehensive Verification Test Suite:
ElevenLabs Conversational Policy Assistant & Spoken Explainability.
Tests:
- Policy grounded Q&A (coverage limit, waiting period, exclusions, room rent, unestablished queries)
- Customer identity isolation and RBAC
- Spoken claim decision explanations (Approved & Rejected outcomes)
- Deterministic audio fallback synthesis
- API route handlers for voice assistant and claims spoken explanation
"""

import base64
from datetime import datetime, timezone
from decimal import Decimal
import uuid
import pytest
from unittest.mock import AsyncMock, patch

from app.api.routes.claims import generate_claim_spoken_explanation
from app.api.routes.voice import get_voice_assistant_status, query_policy_assistant
from app.core.exceptions import AuthorizationException, ValidationException
from app.schemas.voice_assistant import PolicyAssistantQueryRequest
from app.services.voice_assistant import (
    ElevenLabsTTSService,
    VoiceAssistantService,
    voice_assistant_service,
)


@pytest.fixture
def sample_policy_bundle():
    policy_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    return {
        "policy": {
            "id": policy_id,
            "policy_name": "Care Premier Health Shield",
            "policy_code": "CPHS-2026",
            "category": "MEDICAL",
            "description": "Comprehensive inpatient hospitalization coverage",
            "coverage_limit": Decimal("200000.00"),
            "waiting_period_days": 90,
            "claim_filing_window_days": 30,
            "is_active": True,
        },
        "version": {
            "id": version_id,
            "policy_id": policy_id,
            "version_number": 1,
            "effective_date": "2026-01-01",
            "expiry_date": "2026-12-31",
            "terms_json": {
                "room_rent_limit": "₹3,000 per day",
                "icu_limit": "₹6,000 per day",
                "exclusions": [
                    "Cosmetic or aesthetic surgeries",
                    "Unapproved experimental therapies",
                    "Diagnostic admissions without active medical intervention",
                ],
            },
            "is_published": True,
        },
        "registration": {
            "id": str(uuid.uuid4()),
            "status": "CONFIRMED",
        },
    }


# ==============================================================================
# 1. Deterministic Audio Synthesis Tests
# ==============================================================================

def test_deterministic_audio_generator():
    """Validates that fallback audio generator produces valid playable PCM WAV byte sequence."""
    service = ElevenLabsTTSService()
    wav_bytes = service.generate_fallback_wav("Test explanation audio text")
    assert len(wav_bytes) > 44
    assert wav_bytes[:4] == b"RIFF"
    assert wav_bytes[8:12] == b"WAVE"
    assert wav_bytes[12:16] == b"fmt "
    assert b"data" in wav_bytes


@pytest.mark.asyncio
async def test_tts_service_fallback_on_missing_api_key():
    """When ElevenLabs API key is unconfigured, synthesizes speech via deterministic fallback."""
    service = ElevenLabsTTSService()
    with patch.object(service, "_get_api_key", return_value=None):
        audio_bytes, mime, provider = await service.synthesize_speech("Hello policyholder")
        assert len(audio_bytes) > 44
        assert mime == "audio/wav"
        assert provider == "deterministic_fallback"


# ==============================================================================
# 2. Conversational Policy Assistant Q&A Grounding Tests
# ==============================================================================

def test_grounded_answer_coverage_limit(sample_policy_bundle):
    """Customer asks about maximum coverage limit; receives exact sum insured & Clause 2.1."""
    ans, clauses, conf, is_grounded = voice_assistant_service._extract_policy_grounded_answer(
        "What is my maximum coverage limit?", sample_policy_bundle
    )
    assert "200,000.00" in ans
    assert "Clause 2.1" in clauses[0]
    assert is_grounded is True
    assert conf >= 0.95


def test_grounded_answer_waiting_period(sample_policy_bundle):
    """Customer asks about waiting periods; receives exact 90-day waiting period & Clause 4.2."""
    ans, clauses, conf, is_grounded = voice_assistant_service._extract_policy_grounded_answer(
        "What is the waiting period for pre-existing disease?", sample_policy_bundle
    )
    assert "90 days" in ans
    assert "Clause 4.2" in clauses[0]
    assert is_grounded is True
    assert conf >= 0.95


def test_grounded_answer_exclusions(sample_policy_bundle):
    """Customer asks about exclusions; extracts exact exclusions from published terms_json."""
    ans, clauses, conf, is_grounded = voice_assistant_service._extract_policy_grounded_answer(
        "Which treatments or situations are excluded?", sample_policy_bundle
    )
    assert "Cosmetic or aesthetic surgeries" in ans
    assert "Clause 5" in clauses[0]
    assert is_grounded is True


def test_grounded_answer_room_rent_limits(sample_policy_bundle):
    """Customer asks about room rent and ICU capping."""
    ans, clauses, conf, is_grounded = voice_assistant_service._extract_policy_grounded_answer(
        "What are my room rent and ICU limits?", sample_policy_bundle
    )
    assert "₹3,000 per day" in ans
    assert "₹6,000 per day" in ans
    assert "Clause 3.3" in clauses[0]
    assert is_grounded is True


def test_grounded_answer_claim_documents(sample_policy_bundle):
    """Customer asks about required claim submission documents and deadline."""
    ans, clauses, conf, is_grounded = voice_assistant_service._extract_policy_grounded_answer(
        "What documents are required to submit a claim and what is the deadline?", sample_policy_bundle
    )
    assert "30 days" in ans
    assert "hospital bills" in ans.lower()
    assert "discharge summary" in ans.lower()
    assert "Clause 6.1" in clauses[0]
    assert is_grounded is True


def test_grounded_answer_unestablished_question(sample_policy_bundle):
    """Unrelated questions return transparent unestablished notice and is_grounded=False."""
    ans, clauses, conf, is_grounded = voice_assistant_service._extract_policy_grounded_answer(
        "Can I get discounts on movie tickets with this policy?", sample_policy_bundle
    )
    assert "cannot be established" in ans.lower()
    assert is_grounded is False


# ==============================================================================
# 3. Policy Assistant End-to-End Service & Route Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_policy_assistant_service_isolated_query(sample_policy_bundle):
    """Verifies answer_policy_query generates complete response and audio payload."""
    mock_conn = AsyncMock()
    cust_id = str(uuid.uuid4())

    with patch.object(voice_assistant_service, "_get_customer_policies", new=AsyncMock(return_value=[sample_policy_bundle])):
        response = await voice_assistant_service.answer_policy_query(
            conn=mock_conn,
            customer_id=cust_id,
            question="What is my maximum coverage amount?",
            voice_output=True,
        )
        assert response.question == "What is my maximum coverage amount?"
        assert "200,000.00" in response.answer
        assert response.is_grounded is True
        assert response.audio_base64 is not None
        assert response.audio_base64.startswith("data:audio/")


@pytest.mark.asyncio
async def test_policy_assistant_route_handler(sample_policy_bundle):
    """Verifies query_policy_assistant endpoint parses request and returns response."""
    cust_id = str(uuid.uuid4())
    customer_user = {"id": cust_id, "role": "CUSTOMER", "account_status": "ACTIVE"}
    req = PolicyAssistantQueryRequest(question="What is my waiting period?", voice_output=True)

    with patch("app.api.routes.voice.get_db_connection") as mock_db, \
         patch.object(voice_assistant_service, "_get_customer_policies", new=AsyncMock(return_value=[sample_policy_bundle])):
        mock_db.return_value.__aenter__.return_value = AsyncMock()

        res = await query_policy_assistant(
            request_data=req,
            current_user=customer_user,
        )
        assert "90 days" in res.answer
        assert res.is_grounded is True


@pytest.mark.asyncio
async def test_voice_status_route_handler():
    """Verifies get_voice_assistant_status endpoint returns operational status report."""
    auth_user = {"id": str(uuid.uuid4()), "role": "CUSTOMER"}
    res = await get_voice_assistant_status(current_user=auth_user)
    assert res["status"] == "OPERATIONAL"
    assert res["phase"] == "Phase 5"
    assert len(res["features"]) >= 4


# ==============================================================================
# 4. Spoken Claim Decision Explanations Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_spoken_claim_explanation_approved():
    """Verifies approved claim generates clear customer narrative citing recorded reason."""
    mock_conn = AsyncMock()
    cust_id = str(uuid.uuid4())
    claim_id = str(uuid.uuid4())
    policy_id = str(uuid.uuid4())

    mock_claim = {
        "id": claim_id,
        "customer_id": cust_id,
        "policy_id": policy_id,
        "claim_number": "CLM-2026-9901",
        "status": "APPROVED",
        "claimed_amount": Decimal("45000.00"),
    }
    mock_history = [
        {
            "actor_role": "APPROVAL_AUTHORITY",
            "previous_status": "UNDER_REVIEW",
            "new_status": "APPROVED",
            "reason": "All hospital discharge documents verified; treatment is covered under cardiac schedule.",
        }
    ]
    mock_policy = {
        "id": policy_id,
        "policy_name": "Care Premier Health Shield",
    }

    with patch("app.services.voice_assistant.claim_repo.get_claim_by_id", new=AsyncMock(return_value=mock_claim)), \
         patch("app.services.voice_assistant.claim_repo.get_claim_history", new=AsyncMock(return_value=mock_history)), \
         patch("app.services.voice_assistant.policy_repo.get_policy_by_id", new=AsyncMock(return_value=mock_policy)), \
         patch("app.services.voice_assistant.assessment_repo.get_latest_assessment", new=AsyncMock(return_value=None)):

        res = await voice_assistant_service.generate_spoken_claim_explanation(
            conn=mock_conn,
            claim_id=claim_id,
            actor_id=cust_id,
            actor_role="CUSTOMER",
        )
        assert res.claim_id == claim_id
        assert res.claim_number == "CLM-2026-9901"
        assert res.adjudication_decision == "APPROVED"
        assert "Approved" in res.explanation_text
        assert "All hospital discharge documents verified" in res.explanation_text
        assert res.audio_base64 is not None
        assert res.audio_base64.startswith("data:audio/")


@pytest.mark.asyncio
async def test_spoken_claim_explanation_rejected():
    """Verifies rejected claim explains specific reason recorded by the underwriting authority."""
    mock_conn = AsyncMock()
    cust_id = str(uuid.uuid4())
    claim_id = str(uuid.uuid4())
    policy_id = str(uuid.uuid4())

    mock_claim = {
        "id": claim_id,
        "customer_id": cust_id,
        "policy_id": policy_id,
        "claim_number": "CLM-2026-8802",
        "status": "REJECTED",
        "claimed_amount": Decimal("18000.00"),
    }
    mock_history = [
        {
            "actor_role": "APPROVAL_AUTHORITY",
            "previous_status": "UNDER_REVIEW",
            "new_status": "REJECTED",
            "reason": "Claimed repair was incurred during illegal street racing contest (Policy Exclusion Clause 5.1).",
        }
    ]
    mock_policy = {
        "id": policy_id,
        "policy_name": "DriveProtect Comprehensive Auto",
    }

    with patch("app.services.voice_assistant.claim_repo.get_claim_by_id", new=AsyncMock(return_value=mock_claim)), \
         patch("app.services.voice_assistant.claim_repo.get_claim_history", new=AsyncMock(return_value=mock_history)), \
         patch("app.services.voice_assistant.policy_repo.get_policy_by_id", new=AsyncMock(return_value=mock_policy)), \
         patch("app.services.voice_assistant.assessment_repo.get_latest_assessment", new=AsyncMock(return_value=None)):

        res = await voice_assistant_service.generate_spoken_claim_explanation(
            conn=mock_conn,
            claim_id=claim_id,
            actor_id=cust_id,
            actor_role="CUSTOMER",
        )
        assert res.adjudication_decision == "REJECTED"
        assert "Rejected" in res.explanation_text
        assert "illegal street racing contest" in res.explanation_text
        assert res.audio_base64 is not None


@pytest.mark.asyncio
async def test_spoken_claim_explanation_rbac_foreign_customer_rejection():
    """A customer cannot generate or hear spoken explanation for another customer's claim."""
    mock_conn = AsyncMock()
    owner_cust_id = str(uuid.uuid4())
    foreign_cust_id = str(uuid.uuid4())
    claim_id = str(uuid.uuid4())

    mock_claim = {
        "id": claim_id,
        "customer_id": owner_cust_id,
        "status": "APPROVED",
        "claimed_amount": Decimal("10000.00"),
    }

    with patch("app.services.voice_assistant.claim_repo.get_claim_by_id", new=AsyncMock(return_value=mock_claim)):
        with pytest.raises(AuthorizationException) as exc_info:
            await voice_assistant_service.generate_spoken_claim_explanation(
                conn=mock_conn,
                claim_id=claim_id,
                actor_id=foreign_cust_id,
                actor_role="CUSTOMER",
            )
        assert "not authorized" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_spoken_claim_explanation_agent_rejection():
    """Insurance agents are rejected from accessing claim decision audio explanations."""
    cust_id = str(uuid.uuid4())
    claim_id = str(uuid.uuid4())
    agent_user = {"id": str(uuid.uuid4()), "role": "INSURANCE_AGENT"}

    with pytest.raises(AuthorizationException) as exc_info:
        await generate_claim_spoken_explanation(
            claim_id=claim_id,
            current_user=agent_user,
        )
    assert "insurance agents cannot access" in str(exc_info.value).lower()
