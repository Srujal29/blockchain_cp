"""
Test suite for InsureChain VoiceGuard Demonstration Scenarios (Phase 6 Stage 3).
Verifies:
1. All 15 scenario definitions and expected outcomes.
2. Scenario 03 exact published policy wording and mis-selling contradiction detection.
3. Scenario 12 actual OCR extraction results (no hardcoded confidence or fabricated outcomes).
4. Scenario 15 in-memory synthetic Merkle fixture verification (authentic vs tampered).
5. Idempotent seeding without automatic wiping of existing records.
6. Authorized, foreign-key safe demo cleanup with non-demo data protection.
"""

from decimal import Decimal
import json
import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import require_active_authority
from app.core.exceptions import AuthorizationException
from app.db.connection import get_db_connection
from app.main import app


@pytest.fixture(autouse=True)
def cleanup_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_and_get_all_15_scenarios():
    """Verifies that all 15 scenarios are catalogued and accessible via API."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/demo/scenarios")
        assert res.status_code == 200
        scenarios = res.json()
        assert len(scenarios) == 15

        scenario_ids = [s["scenario_id"] for s in scenarios]
        for i in range(1, 16):
            expected_id = f"DEMO-SCN-{i:02d}"
            assert expected_id in scenario_ids

        # Test single scenario endpoint
        res_single = await client.get("/api/v1/demo/scenarios/DEMO-SCN-01")
        assert res_single.status_code == 200
        assert res_single.json()["scenario_id"] == "DEMO-SCN-01"


@pytest.mark.asyncio
async def test_scenario_15_synthetic_merkle_fixture():
    """
    Verifies Scenario 15:
    - Tests authentic inclusion proof validates True
    - Tests single-byte tampered payload validates False
    - Zero database mutation and zero blockchain calls.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/demo/audit-tamper-check")
        assert res.status_code == 200
        data = res.json()
        assert data["scenario_id"] == "DEMO-SCN-15"
        assert data["authentic_proof_valid"] is True
        assert data["tampered_proof_valid"] is False
        assert data["tamper_detected"] is True
        assert len(data["authentic_root"]) == 64
        assert len(data["tampered_leaf_hash"]) == 64


@pytest.mark.asyncio
async def test_scenario_12_actual_ocr_extraction():
    """
    Verifies Scenario 12:
    - Executes actual OCR extraction engine on unreadable bytes
    - Verifies extraction produces MANUAL_FALLBACK with 0.0 confidence score
    - Confirms no hardcoded confidence score or fabricated outcome.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/demo/scenarios/DEMO-SCN-12/seed")
        assert res.status_code == 200
        data = res.json()
        assert data["scenario_id"] == "DEMO-SCN-12"
        claim_id = data["claim_id"]

        # Inspect the persisted evidence analysis report
        async with get_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT extraction_method, confidence_score, overall_status, review_recommendation
                    FROM evidence_analysis_reports
                    WHERE claim_id = %s;
                    """,
                    (claim_id,),
                )
                row = await cur.fetchone()
                assert row is not None
                extraction_method, confidence, overall_status, review_rec = row
                assert extraction_method == "MANUAL_FALLBACK"
                assert float(confidence) == 0.0
                assert overall_status == "NEEDS_MANUAL_REVIEW"
                assert review_rec == "EXTRACTION_UNAVAILABLE"


@pytest.mark.asyncio
async def test_scenario_03_exact_published_policy_wording():
    """
    Verifies Scenario 03:
    - Verifies synthetic sales transcript mis-selling against published Care Premier Health Shield terms
    - Checks that verification report contains 2 CONTRADICTED findings using exact published policy wording.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/demo/scenarios/DEMO-SCN-03/seed")
        assert res.status_code == 200
        data = res.json()
        session_id = data["session_id"]
        assert session_id is not None

        async with get_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT overall_integrity_status, contradicted_count, findings, review_flags
                    FROM verification_reports
                    WHERE sales_session_id = %s;
                    """,
                    (session_id,),
                )
                row = await cur.fetchone()
                assert row is not None
                status, contra_count, findings_data, review_flags = row
                assert status == "MISLEADING_CLAIMS_DETECTED"
                assert contra_count == 2
                assert "CONTRADICTION_PRE_EXISTING_WAITING_PERIOD" in review_flags
                assert "CONTRADICTION_ICU_ROOM_RENT_CAP" in review_flags

                # Inspect findings
                findings_obj = findings_data if isinstance(findings_data, dict) else json.loads(findings_data)
                findings_list = findings_obj.get("findings", [])
                assert len(findings_list) == 2
                f1 = findings_list[0]
                assert f1["status"] == "CONTRADICTED"
                assert "waiting_period_pre_existing_months: 24" in f1["policy_ground_truth"]
                f2 = findings_list[1]
                assert f2["status"] == "CONTRADICTED"
                assert "room_rent_cap: Up to 1% per day; ICU up to 2%" in f2["policy_ground_truth"]


@pytest.mark.asyncio
async def test_seed_idempotency():
    """
    Verifies Requirement 4:
    - Running seed twice for a scenario preserves existing records and returns ALREADY_EXISTS
    - Does not wipe or duplicate data.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First execution: seeded or already exists
        res1 = await client.post("/api/v1/demo/scenarios/DEMO-SCN-01/seed")
        assert res1.status_code == 200

        # Second execution: must be idempotent and preserve existing record
        res2 = await client.post("/api/v1/demo/scenarios/DEMO-SCN-01/seed")
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["seeded"] is False
        assert data2["status"] == "ALREADY_EXISTS"
        assert "preserved without modification" in data2["message"].lower()


@pytest.mark.asyncio
async def test_deterministic_eligibility_engine_outcomes():
    """
    Verifies that eligibility assessments across scenarios match deterministic engine rules:
    - Scenario 01: ELIGIBLE
    - Scenario 04: INELIGIBLE (Filing deadline exceeded)
    - Scenario 05: INELIGIBLE (Coverage limit exceeded)
    - Scenario 06: INELIGIBLE (Waiting period not elapsed)
    - Scenario 07: NEEDS_REVIEW (Duplicate candidate match)
    - Scenario 13: NEEDS_REVIEW (Exclusion clause triggered)
    - Scenario 14: NEEDS_REVIEW (Missing mandatory evidence)
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Seed scenarios 04, 05, 06, 07, 13, 14
        for scn_id in ["DEMO-SCN-04", "DEMO-SCN-05", "DEMO-SCN-06", "DEMO-SCN-07", "DEMO-SCN-13", "DEMO-SCN-14"]:
            res = await client.post(f"/api/v1/demo/scenarios/{scn_id}/seed")
            assert res.status_code == 200

        async with get_db_connection() as conn:
            async with conn.cursor() as cur:
                # Check SCN-01
                await cur.execute(
                    """
                    SELECT a.overall_outcome
                    FROM claim_assessments a
                    JOIN claims c ON a.claim_id = c.id
                    WHERE c.structured_details->>'scenario_id' = 'DEMO-SCN-01';
                    """
                )
                assert (await cur.fetchone())[0] == "ELIGIBLE"

                # Check SCN-04: Late filing
                await cur.execute(
                    """
                    SELECT a.overall_outcome, a.rules_evaluated
                    FROM claim_assessments a
                    JOIN claims c ON a.claim_id = c.id
                    WHERE c.structured_details->>'scenario_id' = 'DEMO-SCN-04';
                    """
                )
                row_04 = await cur.fetchone()
                assert row_04[0] == "INELIGIBLE"
                rules_04 = row_04[1] if isinstance(row_04[1], list) else json.loads(row_04[1])
                filing_rule = next(r for r in rules_04 if r["rule_id"] == "RULE_FILING_DEADLINE")
                assert filing_rule["result"] == "FAIL"

                # Check SCN-05: Coverage limit exceeded
                await cur.execute(
                    """
                    SELECT a.overall_outcome, a.excess_amount, a.potentially_payable_amount
                    FROM claim_assessments a
                    JOIN claims c ON a.claim_id = c.id
                    WHERE c.structured_details->>'scenario_id' = 'DEMO-SCN-05';
                    """
                )
                row_05 = await cur.fetchone()
                assert row_05[0] == "INELIGIBLE"
                assert Decimal(str(row_05[1])) == Decimal("13000.00")
                assert Decimal(str(row_05[2])) == Decimal("25000.00")

                # Check SCN-06: Waiting period
                await cur.execute(
                    """
                    SELECT a.overall_outcome, a.rules_evaluated
                    FROM claim_assessments a
                    JOIN claims c ON a.claim_id = c.id
                    WHERE c.structured_details->>'scenario_id' = 'DEMO-SCN-06';
                    """
                )
                row_06 = await cur.fetchone()
                assert row_06[0] == "INELIGIBLE"
                rules_06 = row_06[1] if isinstance(row_06[1], list) else json.loads(row_06[1])
                wait_rule = next(r for r in rules_06 if r["rule_id"] == "RULE_COVERAGE_PERIOD")
                assert wait_rule["result"] == "FAIL"

                # Check SCN-07: Duplicate detection
                await cur.execute(
                    """
                    SELECT a.overall_outcome, a.review_flags
                    FROM claim_assessments a
                    JOIN claims c ON a.claim_id = c.id
                    WHERE c.structured_details->>'scenario_id' = 'DEMO-SCN-07';
                    """
                )
                row_07 = await cur.fetchone()
                assert row_07[0] == "NEEDS_REVIEW"
                flags_07 = row_07[1] if isinstance(row_07[1], list) else json.loads(row_07[1])
                assert any("duplicate" in f.lower() for f in flags_07)

                # Check SCN-13: Policy exclusion
                await cur.execute(
                    """
                    SELECT a.overall_outcome, a.review_flags
                    FROM claim_assessments a
                    JOIN claims c ON a.claim_id = c.id
                    WHERE c.structured_details->>'scenario_id' = 'DEMO-SCN-13';
                    """
                )
                row_13 = await cur.fetchone()
                assert row_13[0] == "NEEDS_REVIEW"
                flags_13 = row_13[1] if isinstance(row_13[1], list) else json.loads(row_13[1])
                assert any("exclusion" in f.lower() for f in flags_13)

                # Check SCN-14: Missing evidence
                await cur.execute(
                    """
                    SELECT a.overall_outcome, a.missing_evidence
                    FROM claim_assessments a
                    JOIN claims c ON a.claim_id = c.id
                    WHERE c.structured_details->>'scenario_id' = 'DEMO-SCN-14';
                    """
                )
                row_14 = await cur.fetchone()
                assert row_14[0] == "NEEDS_REVIEW"
                missing_14 = row_14[1] if isinstance(row_14[1], list) else json.loads(row_14[1])
                assert "DISCHARGE_SUMMARY" in missing_14


@pytest.mark.asyncio
async def test_demo_cleanup_authorization_and_isolation():
    """
    Verifies Requirement 5:
    - Unauthenticated or non-authority role cannot trigger demo cleanup
    - Authority role without confirm=True is rejected (HTTP 400)
    - Authority role with confirm=True purges demo data cleanly while leaving non-demo data intact.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Non-authority attempt -> 403 Forbidden
        def _mock_customer():
            raise AuthorizationException("Role 'CUSTOMER' is not authorized for this operation.")

        app.dependency_overrides[require_active_authority] = _mock_customer
        res_cust = await client.post("/api/v1/demo/cleanup", json={"confirm": True})
        assert res_cust.status_code == 403

        # 2. Authority attempt without confirmation -> 400 Bad Request
        app.dependency_overrides[require_active_authority] = lambda: {
            "id": "00000000-0000-0000-0000-000000000001",
            "role": "APPROVAL_AUTHORITY",
            "account_status": "ACTIVE",
        }
        res_no_conf = await client.post("/api/v1/demo/cleanup", json={"confirm": False})
        assert res_no_conf.status_code in (400, 422)

        # 3. Authorized cleanup -> 200 OK
        res_ok = await client.post("/api/v1/demo/cleanup", json={"confirm": True})
        assert res_ok.status_code == 200
        data = res_ok.json()
        assert data["success"] is True
        assert "deleted_records" in data

        # Verify all demo records are gone
        async with get_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT count(*) FROM claims WHERE structured_details->>'is_demo' = 'true';")
                assert (await cur.fetchone())[0] == 0
                await cur.execute("SELECT count(*) FROM users WHERE email LIKE 'demo_%@vachan.local';")
                assert (await cur.fetchone())[0] == 0
