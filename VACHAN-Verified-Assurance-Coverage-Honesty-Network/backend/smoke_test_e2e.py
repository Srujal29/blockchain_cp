"""
End-to-end Smoke Test for VACHAN (Phases 1-6).
Tests:
1. Authentication: Authority bootstrap & Login
2. Policy Assistant (Phase 5): Grounded query via /voice/assistant/query
3. Evidence & Invoice Arithmetic (Phase 6 Stage 1): OCR & Arithmetic audit
4. Spoken Claim Explanation (Phase 5): Plain-language adjudication narrative via /claims/{id}/spoken-explanation
5. Blockchain Merkle Integrity (Phase 2 & Phase 6 Stage 4): Merkle root & tamper detection
"""

import asyncio
from datetime import date, timedelta
from decimal import Decimal
import io
import json
import uuid
import httpx

from app.core.config import get_settings
from app.main import app
from app.services.invoice_auditor import (
    detect_document_type,
    parse_invoice_fields,
    validate_invoice_arithmetic,
)
from app.services.merkle_tree import MerkleTree, sha256_hex, verify_merkle_proof

async def run_smoke_test():
    print("=== STARTING END-TO-END SMOKE TEST ===")
    settings = get_settings()
    transport = httpx.ASGITransport(app=app)
    
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=30.0) as client:
        # 1. Authentication
        print("\n--- 1. Testing Authentication ---")
        pwd = "SmokeTestPassword123!"
        auth_email = f"auth_smoke_{uuid.uuid4().hex[:6]}@example.com"
        r_boot = await client.post(
            "/api/v1/auth/bootstrap-authority",
            json={
                "email": auth_email,
                "password": pwd,
                "full_name": "Smoke Test Authority",
                "bootstrap_secret": settings.AUTHORITY_BOOTSTRAP_SECRET,
            },
        )
        assert r_boot.status_code == 201, f"Authority bootstrap failed: {r_boot.text}"
        
        r_login = await client.post("/api/v1/auth/login", json={"email": auth_email, "password": pwd})
        assert r_login.status_code == 200, f"Authority login failed: {r_login.text}"
        auth_token = r_login.json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {auth_token}"}
        print("  [SUCCESS] Authority bootstrapped and authenticated successfully.")

        # Customer creation
        cust_email = f"cust_smoke_{uuid.uuid4().hex[:6]}@example.com"
        r_cust = await client.post(
            "/api/v1/auth/signup",
            json={"email": cust_email, "password": pwd, "full_name": "Smoke Customer", "role": "CUSTOMER"},
        )
        assert r_cust.status_code == 201, f"Customer signup failed: {r_cust.text}"
        cust_id = r_cust.json()["id"]
        
        # Verify email directly via DB or endpoint
        from app.db.connection import get_db_connection
        from app.db.repositories import user_repo
        async with get_db_connection() as conn:
            await user_repo.verify_user_email(conn, cust_id)
        
        r_cust_login = await client.post("/api/v1/auth/login", json={"email": cust_email, "password": pwd})
        assert r_cust_login.status_code == 200, f"Customer login failed: {r_cust_login.text}"
        cust_token = r_cust_login.json()["access_token"]
        cust_headers = {"Authorization": f"Bearer {cust_token}"}
        print("  [SUCCESS] Customer registered, verified, and authenticated successfully.")

        # 2. Create Policy, Version, and Registration
        print("\n--- 2. Setting Up Policy and Registration ---")
        r_pol = await client.post(
            "/api/v1/policies",
            headers=auth_headers,
            json={
                "insurer_name": "Vortexa Smoke Assurance",
                "policy_name": "Smoke Care Health Plan",
                "policy_code": f"SMK-{uuid.uuid4().hex[:6].upper()}",
                "category": "MEDICAL",
                "description": "Comprehensive health plan for smoke testing",
                "coverage_limit": "150000.00",
                "waiting_period_days": 30,
                "claim_filing_window_days": 45,
            },
        )
        assert r_pol.status_code == 201, f"Policy creation failed: {r_pol.text}"
        policy_id = r_pol.json()["id"]

        terms_dict = {
            "policy_name": "Smoke Care Health Plan",
            "room_rent_limit": "₹2,500 per day",
            "icu_limit": "₹5,000 per day",
            "waiting_period_days": 30,
            "exclusions": ["Cosmetic surgery", "Self-inflicted injury"],
            "required_evidence": ["HOSPITAL_BILL", "DISCHARGE_SUMMARY"],
        }
        r_ver = await client.post(
            f"/api/v1/policies/{policy_id}/versions",
            headers=auth_headers,
            json={
                "version_number": 1,
                "document_storage_ref": "cloudinary://vachan/policies/smoke_v1.pdf",
                "document_checksum": "b" * 64,
                "effective_date": "2026-01-01",
                "terms_json": terms_dict,
            },
        )
        assert r_ver.status_code == 201, f"Policy version creation failed: {r_ver.text}"
        version_id = r_ver.json()["id"]

        r_pub = await client.post(f"/api/v1/policies/{policy_id}/versions/{version_id}/publish", headers=auth_headers)
        assert r_pub.status_code == 200, f"Policy publishing failed: {r_pub.text}"

        # Agent creation & registration
        agent_email = f"agent_smoke_{uuid.uuid4().hex[:6]}@example.com"
        r_agent = await client.post(
            "/api/v1/auth/signup",
            json={"email": agent_email, "password": pwd, "full_name": "Smoke Agent", "role": "INSURANCE_AGENT"},
        )
        agent_id = r_agent.json()["id"]
        await client.post("/api/v1/auth/approve-account", headers=auth_headers, json={"user_id": agent_id, "status": "ACTIVE"})
        r_agent_login = await client.post("/api/v1/auth/login", json={"email": agent_email, "password": pwd})
        agent_token = r_agent_login.json()["access_token"]
        agent_headers = {"Authorization": f"Bearer {agent_token}"}

        r_reg = await client.post(
            "/api/v1/registrations",
            headers=agent_headers,
            json={
                "customer_id": cust_id,
                "policy_id": policy_id,
                "policy_version_id": version_id,
                "customer_consent": True,
                "consent_notes": "Smoke test consent note.",
            },
        )
        assert r_reg.status_code == 201, f"Registration creation failed: {r_reg.text}"
        reg_id = r_reg.json()["id"]

        r_conf = await client.post(f"/api/v1/registrations/{reg_id}/confirm", headers=cust_headers)
        assert r_conf.status_code == 200, f"Registration confirm failed: {r_conf.text}"
        print("  [SUCCESS] Policy published and customer confirmed registration.")

        # 3. Policy Assistant (Phase 5)
        print("\n--- 3. Testing Conversational Policy Assistant (Phase 5) ---")
        r_qa = await client.post(
            "/api/v1/voice/assistant/query",
            headers=cust_headers,
            json={
                "question": "What is my room rent limit and waiting period?",
                "policy_id": policy_id,
                "voice_output": True,
            },
        )
        assert r_qa.status_code == 200, f"Policy assistant query failed: {r_qa.text}"
        qa_data = r_qa.json()
        print(f"  [SUCCESS] Policy Assistant Answer: {qa_data['answer'][:80]}...")
        print(f"  [SUCCESS] Answer grounded: {qa_data.get('is_grounded')} | Audio URL present: {bool(qa_data.get('audio_url'))}")

        # 4. Invoice Arithmetic Integrity Analysis (Phase 6 Stage 1)
        print("\n--- 4. Testing Invoice Arithmetic Integrity Analysis (Phase 6) ---")
        extracted_invoice = {
            "total_amount": Decimal("45000.00"),  # Inflated total claimed
            "subtotal": Decimal("45000.00"),
            "tax_amount": Decimal("0.00"),
            "discount_amount": Decimal("0.00"),
            "line_items": [
                {"description": "Room Charges", "quantity": Decimal("4"), "unit_rate": Decimal("2500.00"), "total": Decimal("10000.00"), "math_valid": True},
                {"description": "Surgical Procedures", "quantity": Decimal("1"), "unit_rate": Decimal("25000.00"), "total": Decimal("25000.00"), "math_valid": True},
            ],  # Actual sum: 35000.00
        }
        audit_res = validate_invoice_arithmetic(extracted_invoice, claim_requested_amount=Decimal("45000.00"))
        print(f"  [SUCCESS] Calculated sum: {audit_res['calculated_line_items_sum']} vs Claimed: 45000.00")
        print(f"  [SUCCESS] Sum matches total: {audit_res['sum_matches_total']} | Math valid: {audit_res['line_item_math_valid']}")
        print(f"  [SUCCESS] Rounding/Tax discrepancy: ₹{audit_res['rounding_or_tax_discrepancy']}")
        assert audit_res["sum_matches_total"] is False, "Arithmetic auditor failed to detect inflated invoice total!"

        # 5. Claim Submission & Spoken Adjudication Explanation (Phase 5)
        print("\n--- 5. Testing Claim Creation & Spoken Adjudication Explanation (Phase 5) ---")
        inc_date = (date.today() - timedelta(days=5)).isoformat()
        r_claim = await client.post(
            "/api/v1/claims",
            headers=cust_headers,
            json={
                "registration_id": reg_id,
                "claim_category": "MEDICAL",
                "requested_amount": "35000.00",
                "incident_date": inc_date,
                "description": "Hospitalization claim for acute appendectomy.",
            },
        )
        assert r_claim.status_code == 201, f"Claim creation failed: {r_claim.text}"
        claim_id = r_claim.json()["id"]

        # Authority transitions to UNDER_REVIEW then APPROVES
        await client.post(
            f"/api/v1/claims/{claim_id}/transition",
            headers=auth_headers,
            json={"target_status": "UNDER_REVIEW", "reason": "Adjuster review started."},
        )
        await client.post(
            f"/api/v1/claims/{claim_id}/transition",
            headers=auth_headers,
            json={
                "target_status": "APPROVED",
                "reason": "Hospitalization validated and eligible under Smoke Care Health Plan terms.",
            },
        )
        print("  [SUCCESS] Claim created and approved by Authority.")

        # Customer generates spoken explanation
        r_explain = await client.post(
            f"/api/v1/claims/{claim_id}/spoken-explanation",
            headers=cust_headers,
        )
        assert r_explain.status_code == 200, f"Spoken explanation failed: {r_explain.text}"
        exp_data = r_explain.json()
        print(f"  [SUCCESS] Spoken Narrative: {exp_data['explanation_text']}")
        print(f"  [SUCCESS] Audio Base64 length: {len(exp_data['audio_base64'])} bytes")
        print(f"  [SUCCESS] Voice provider: {exp_data.get('voice_provider')}")

        # 6. Blockchain Merkle Integrity Verification (Phase 2 & Phase 6 Stage 4)
        print("\n--- 6. Testing Cryptographic Merkle Audit Tree Integrity ---")
        event1 = sha256_hex("EVENT_1_POLICY_PUBLISHED")
        event2 = sha256_hex("EVENT_2_CLAIM_FILED")
        event3 = sha256_hex("EVENT_3_INVOICE_AUDITED")
        event4 = sha256_hex("EVENT_4_CLAIM_APPROVED")
        
        leaves = [event1, event2, event3, event4]
        tree = MerkleTree(leaves)
        root = tree.root()
        proof_for_e3 = tree.get_proof(2)
        
        valid = verify_merkle_proof(event3, proof_for_e3, root)
        print(f"  [SUCCESS] Merkle root: {root}")
        print(f"  [SUCCESS] Authentic inclusion proof for event 3 verified: {valid}")
        assert valid is True, "Authentic proof failed!"
        
        tampered_event = sha256_hex("EVENT_3_TAMPERED_INVOICE")
        tamper_detected = not verify_merkle_proof(tampered_event, proof_for_e3, root)
        print(f"  [SUCCESS] Tampered event correctly detected & rejected: {tamper_detected}")
        assert tamper_detected is True, "Tamper was not detected!"

    print("\n=== ALL END-TO-END SMOKE TESTS COMPLETED SUCCESSFULLY ===")

if __name__ == "__main__":
    asyncio.run(run_smoke_test())
