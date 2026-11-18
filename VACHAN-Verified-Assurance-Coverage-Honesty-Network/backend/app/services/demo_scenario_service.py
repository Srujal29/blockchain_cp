"""
Demonstration Scenarios Service for InsureChain VoiceGuard (Phase 6 Stage 3).
Provides 15 realistic demonstration scenarios covering:
- Standard claims & settlement workflows
- VoiceGuard sales mis-selling verification
- Deterministic eligibility engine rules
- Multimodal evidence OCR & invoice arithmetic auditing
- Cryptographic Merkle audit integrity verification

All scenarios operate through standard backend repositories, engines, and services.
Seeding is idempotent (does not duplicate or wipe existing records).
Cleanup is a separate, destructive, explicitly confirmed operation.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import io
import json
from typing import Any, Dict, List, Optional, Tuple
import uuid

import psycopg

from app.core.exceptions import NotFoundException, ValidationException
from app.core.logging import get_logger
from app.core.security import hash_password
from app.db.repositories import (
    assessment_repo,
    claim_evidence_repo,
    claim_repo,
    evidence_analysis_repo,
    policy_repo,
    registration_repo,
    sales_session_repo,
    user_repo,
    verification_repo,
)
from app.schemas.demo import (
    DemoCleanupResult,
    DemoScenarioDefinition,
    DemoSeedResult,
    DemoTamperCheckResult,
)
from app.services.duplicate_detector import duplicate_detector
from app.services.eligibility_engine import eligibility_engine
from app.services.evidence_analysis_service import EvidenceAnalysisService
from app.services.merkle_tree import MerkleTree, sha256_hex, verify_merkle_proof

logger = get_logger(__name__)

SCENARIO_DEFINITIONS: List[DemoScenarioDefinition] = [
    DemoScenarioDefinition(
        scenario_id="DEMO-SCN-01",
        title="Standard Vehicle Settlement",
        category="VEHICLE",
        policy_name="DriveProtect Comprehensive Auto",
        description="Standard approved motor collision claim with valid repair invoice and RC.",
        input_conditions="Requested ₹18,500. Evidence: itemized repair invoice and RC certificate.",
        engine_evaluation="RULE_COVERAGE_LIMIT: PASS (₹18,500 <= ₹50,000), RULE_FILING_DEADLINE: PASS, RULE_EVIDENCE_COMPLETENESS: PASS",
        expected_outcome="ELIGIBLE",
        stage2_analysis_status="CONSISTENT / NO_ACTION_REQUIRED",
    ),
    DemoScenarioDefinition(
        scenario_id="DEMO-SCN-02",
        title="Standard Health Hospitalization",
        category="MEDICAL",
        policy_name="Care Premier Health Shield",
        description="Standard approved hospital inpatient claim with valid medical bill and discharge summary.",
        input_conditions="Requested ₹64,200. Evidence: itemized hospital bill and discharge summary.",
        engine_evaluation="RULE_COVERAGE_LIMIT: PASS (₹64,200 <= ₹2,00,000), RULE_FILING_DEADLINE: PASS, RULE_EVIDENCE_COMPLETENESS: PASS",
        expected_outcome="ELIGIBLE",
        stage2_analysis_status="CONSISTENT / NO_ACTION_REQUIRED",
    ),
    DemoScenarioDefinition(
        scenario_id="DEMO-SCN-03",
        title="VoiceGuard Mis-selling & Policy Verification",
        category="GOVERNANCE",
        policy_name="Care Premier Health Shield",
        description="Agent verbally promises zero waiting period for pre-existing illness and unlimited ICU.",
        input_conditions="Agent voice recording promising day-1 pre-existing coverage and unlimited ICU.",
        engine_evaluation="VoiceGuard Verifier flags direct contradiction against published policy clauses.",
        expected_outcome="NEEDS_REVIEW (Sales Verification)",
        stage2_analysis_status="N/A",
    ),
    DemoScenarioDefinition(
        scenario_id="DEMO-SCN-04",
        title="Late Claim Submission Exceeding Deadline",
        category="VEHICLE",
        policy_name="DriveProtect Comprehensive Auto",
        description="Claim filed 53 days after incident, exceeding the policy's 30-day deadline window.",
        input_conditions="Incident occurred T-55d, filed T-2d (53 days elapsed vs 30-day limit).",
        engine_evaluation="RULE_FILING_DEADLINE: FAIL (53 days > 30 days limit).",
        expected_outcome="INELIGIBLE",
        stage2_analysis_status="CONSISTENT / NO_ACTION_REQUIRED",
    ),
    DemoScenarioDefinition(
        scenario_id="DEMO-SCN-05",
        title="Claim Amount Exceeding Coverage Limit",
        category="VEHICLE",
        policy_name="Two-Wheeler Standard Protect",
        description="Claimant requested ₹38,000 on a policy with strict ₹25,000 coverage limit.",
        input_conditions="Requested ₹38,000 vs Policy Coverage Limit ₹25,000 (Excess: ₹13,000).",
        engine_evaluation="RULE_COVERAGE_LIMIT: FAIL. Engine deterministically rules INELIGIBLE. Capping at limit is manual Authority discretion.",
        expected_outcome="INELIGIBLE",
        stage2_analysis_status="CONSISTENT / NO_ACTION_REQUIRED",
    ),
    DemoScenarioDefinition(
        scenario_id="DEMO-SCN-06",
        title="Incident Within Waiting Period",
        category="MEDICAL",
        policy_name="Critical Illness Protect 90",
        description="Critical illness diagnosis occurred 20 days after inception on a policy with 90-day waiting period.",
        input_conditions="Policy effective T-30d, incident diagnosed T-10d (20 days < 90-day waiting window).",
        engine_evaluation="RULE_COVERAGE_PERIOD: FAIL (Incident occurred during mandatory waiting window).",
        expected_outcome="INELIGIBLE",
        stage2_analysis_status="CONSISTENT / NO_ACTION_REQUIRED",
    ),
    DemoScenarioDefinition(
        scenario_id="DEMO-SCN-07",
        title="Duplicate Claim Candidate Detection",
        category="VEHICLE",
        policy_name="DriveProtect Comprehensive Auto",
        description="Claimant submits duplicate claim for same vehicle registration number on identical incident date.",
        input_conditions="Identical claimant, vehicle reg 'KA-01-MJ-4040', and same incident date.",
        engine_evaluation="DuplicateDetector flags candidate match (score >= 0.70). Review flag appended without auto-rejection.",
        expected_outcome="NEEDS_REVIEW",
        stage2_analysis_status="CONSISTENT / NO_ACTION_REQUIRED",
    ),
    DemoScenarioDefinition(
        scenario_id="DEMO-SCN-08",
        title="Invoice Arithmetic Line-Item Mismatch",
        category="MEDICAL",
        policy_name="Care Premier Health Shield",
        description="Hospital bill line items sum to ₹30,000 but printed grand total is ₹38,000.",
        input_conditions="Line items sum: ₹30,000. Printed Total: ₹38,000 (Phantom ₹8,000 variance).",
        engine_evaluation="InvoiceAuditor flags sum_matches_total: False. Math discrepancy advisory flag appended.",
        expected_outcome="NEEDS_REVIEW",
        stage2_analysis_status="DISCREPANCIES_DETECTED / ADVISORY_REVIEW_RECOMMENDED",
    ),
    DemoScenarioDefinition(
        scenario_id="DEMO-SCN-09",
        title="Invoice Total vs Claimed Amount Discrepancy",
        category="VEHICLE",
        policy_name="DriveProtect Comprehensive Auto",
        description="Customer claimed ₹45,000 but workshop estimate total is only ₹27,500.",
        input_conditions="Customer requested: ₹45,000. Invoice total: ₹27,500 (Discrepancy ₹17,500).",
        engine_evaluation="InvoiceAuditor flags amount_matches_claim: False. Claim exceeds evidence total.",
        expected_outcome="NEEDS_REVIEW",
        stage2_analysis_status="DISCREPANCIES_DETECTED / ADVISORY_REVIEW_RECOMMENDED",
    ),
    DemoScenarioDefinition(
        scenario_id="DEMO-SCN-10",
        title="Timeline Inconsistency (Invoice Before Incident)",
        category="VEHICLE",
        policy_name="DriveProtect Comprehensive Auto",
        description="Workshop repair invoice date is 7 days before the reported collision occurred.",
        input_conditions="Incident date: T-5d. Repair invoice date: T-12d (7 days before incident).",
        engine_evaluation="InvoiceAuditor flags timeline_valid: False (INVOICE_PREDATES_INCIDENT).",
        expected_outcome="NEEDS_REVIEW",
        stage2_analysis_status="DISCREPANCIES_DETECTED / ADVISORY_REVIEW_RECOMMENDED",
    ),
    DemoScenarioDefinition(
        scenario_id="DEMO-SCN-11",
        title="Tax & Subtotal Reconciliation Mismatch",
        category="MEDICAL",
        policy_name="Care Premier Health Shield",
        description="Subtotal is ₹50,000, 18% GST is ₹9,000, but printed grand total is ₹65,000.",
        input_conditions="Subtotal: ₹50,000, GST: ₹9,000. Printed Total: ₹65,000 (Double tax / ₹6,000 unexplained).",
        engine_evaluation="InvoiceAuditor flags rounding_or_tax_discrepancy: True.",
        expected_outcome="NEEDS_REVIEW",
        stage2_analysis_status="DISCREPANCIES_DETECTED / ADVISORY_REVIEW_RECOMMENDED",
    ),
    DemoScenarioDefinition(
        scenario_id="DEMO-SCN-12",
        title="Unreadable/Corrupted Evidence Document",
        category="VEHICLE",
        policy_name="DriveProtect Comprehensive Auto",
        description="Unreadable/corrupted file uploaded; actual OCR engine yields MANUAL_FALLBACK with 0.0 confidence.",
        input_conditions="Uploaded corrupted byte sequence. OCR engine executed on live file bytes.",
        engine_evaluation="Actual OCR returns confidence 0.0, MANUAL_FALLBACK. Status evaluated as NEEDS_MANUAL_REVIEW.",
        expected_outcome="NEEDS_REVIEW",
        stage2_analysis_status="NEEDS_MANUAL_REVIEW / EXTRACTION_UNAVAILABLE",
    ),
    DemoScenarioDefinition(
        scenario_id="DEMO-SCN-13",
        title="Policy Exclusion Clause Triggered",
        category="VEHICLE",
        policy_name="DriveProtect Comprehensive Auto",
        description="Incident description mentions collision occurred during commercial speed contest / racing.",
        input_conditions="Description: 'Collision occurred during commercial speed contest / racing event.'",
        engine_evaluation="RULE_POLICY_EXCLUSIONS: NEEDS_REVIEW. Exclusion clause matched and flagged for manual adjuster.",
        expected_outcome="NEEDS_REVIEW",
        stage2_analysis_status="CONSISTENT / NO_ACTION_REQUIRED",
    ),
    DemoScenarioDefinition(
        scenario_id="DEMO-SCN-14",
        title="Missing Mandatory Discharge Summary",
        category="MEDICAL",
        policy_name="Care Premier Health Shield",
        description="Inpatient hospitalization claim submitted without mandatory hospital discharge summary.",
        input_conditions="Only medical bill uploaded. Mandatory discharge summary omitted.",
        engine_evaluation="RULE_EVIDENCE_COMPLETENESS: NEEDS_REVIEW (missing: DISCHARGE_SUMMARY).",
        expected_outcome="NEEDS_REVIEW",
        stage2_analysis_status="CONSISTENT (for uploaded bill)",
    ),
    DemoScenarioDefinition(
        scenario_id="DEMO-SCN-15",
        title="Tamper-Evident Merkle Audit Verification",
        category="GOVERNANCE",
        policy_name="InsureChain Cryptographic Governance",
        description="In-memory synthetic fixture verification proving cryptographic tamper detection.",
        input_conditions="Synthetic 4-event audit fixture. Valid inclusion proof vs single-byte tampered payload.",
        engine_evaluation="Authentic proof validates True; tampered payload validates False. Zero DB or blockchain modification.",
        expected_outcome="TAMPER_DETECTED (Audit Check)",
        stage2_analysis_status="N/A",
    ),
]


class DemoScenarioService:
    """Manages idempotent seeding, scenario execution, and safe cleanup for demonstration workflows."""

    def __init__(self) -> None:
        self.evidence_service = EvidenceAnalysisService()

    def get_all_scenarios(self) -> List[DemoScenarioDefinition]:
        return SCENARIO_DEFINITIONS

    def get_scenario_definition(self, scenario_id: str) -> Optional[DemoScenarioDefinition]:
        for s in SCENARIO_DEFINITIONS:
            if s.scenario_id.upper() == scenario_id.upper():
                return s
        return None

    def _generate_invoice_pdf(
        self,
        title: str,
        provider_name: str,
        tax_id: str,
        invoice_number: str,
        invoice_date_str: str,
        line_items: List[Tuple[str, str, str, str]],  # desc, qty, rate, total
        subtotal_str: str,
        tax_str: str,
        total_str: str,
        admission_date_str: Optional[str] = None,
        discharge_date_str: Optional[str] = None,
    ) -> bytes:
        """Generates standard, deterministic text-based PDF bytes using pure Python."""
        lines = [
            title.upper(),
            f"Provider: {provider_name}",
            f"GSTIN: {tax_id}",
            f"Invoice Number: {invoice_number}",
            f"Invoice Date: {invoice_date_str}",
        ]
        if admission_date_str:
            lines.append(f"Admission Date: {admission_date_str}")
        if discharge_date_str:
            lines.append(f"Discharge Date: {discharge_date_str}")

        lines.append("Line Items:")
        for desc, qty, rate, tot in line_items:
            lines.append(f"{desc}: {qty} x {rate} = {tot}")

        lines.append(f"Sub Total: {subtotal_str}")
        lines.append(f"Total Tax: {tax_str}")
        lines.append(f"Total Amount: {total_str}")

        stream = "BT\n/F1 12 Tf\n50 750 Td\n14 TL\n"
        for l in lines:
            esc = l.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream += f"({esc}) Tj\nT*\n"
        stream += "ET\n"
        stream_b = stream.encode("latin1")

        header = b"%PDF-1.4\n"
        obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        obj2 = b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        obj3 = b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
        obj4_header = f"4 0 obj\n<< /Length {len(stream_b)} >>\nstream\n".encode("latin1")
        obj4_footer = b"endstream\nendobj\n"
        obj4 = obj4_header + stream_b + obj4_footer
        obj5 = b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"

        offsets = [0]
        offsets.append(len(header))
        offsets.append(offsets[-1] + len(obj1))
        offsets.append(offsets[-1] + len(obj2))
        offsets.append(offsets[-1] + len(obj3))
        offsets.append(offsets[-1] + len(obj4))

        xref_pos = offsets[-1] + len(obj5)
        xref = "xref\n0 6\n0000000000 65535 f \n"
        for off in offsets[1:]:
            xref += f"{off:010d} 00000 n \n"

        trailer = f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"

        return header + obj1 + obj2 + obj3 + obj4 + obj5 + xref.encode("latin1") + trailer.encode("latin1")

    async def _ensure_demo_user(
        self,
        conn: psycopg.AsyncConnection,
        email: str,
        full_name: str,
        role: str = "CUSTOMER",
    ) -> Dict[str, Any]:
        """Idempotently ensures demo user exists with secure hashed credentials."""
        existing = await user_repo.get_user_by_email(conn, email)
        if existing:
            return existing

        password_hash = hash_password(f"DemoPass_{uuid.uuid4().hex[:8]}")
        sql = """
        INSERT INTO users (
            email, password_hash, full_name, role, account_status, email_verified_at
        )
        VALUES (%s, %s, %s, %s, 'ACTIVE', %s)
        RETURNING id, email, full_name, role, account_status, created_at;
        """
        async with conn.cursor() as cur:
            await cur.execute(
                sql,
                (email, password_hash, f"[DEMO] {full_name}", role, datetime.now(timezone.utc)),
            )
            row = await cur.fetchone()
            return {
                "id": str(row[0]),
                "email": row[1],
                "full_name": row[2],
                "role": row[3],
                "account_status": row[4],
                "created_at": row[5].isoformat() if row[5] else None,
            }

    async def _ensure_demo_policy(
        self,
        conn: psycopg.AsyncConnection,
        policy_code: str,
        policy_name: str,
        category: str,
        coverage_limit: str,
        waiting_period_days: int,
        claim_filing_window_days: int,
        terms_json: Dict[str, Any],
        version_effective_offset_days: int = 180,
    ) -> Tuple[str, str]:
        """Idempotently ensures demo policy and version exist."""
        sql_pol = "SELECT id FROM policies WHERE policy_code = %s;"
        async with conn.cursor() as cur:
            await cur.execute(sql_pol, (policy_code,))
            row = await cur.fetchone()
            if row:
                policy_id = str(row[0])
            else:
                await cur.execute(
                    """
                    INSERT INTO policies (
                        insurer_name, policy_name, policy_code, category,
                        description, coverage_limit, waiting_period_days,
                        claim_filing_window_days, is_active
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                    RETURNING id;
                    """,
                    (
                        "InsureChain Demo Assurance",
                        f"[DEMO] {policy_name}",
                        policy_code,
                        category,
                        f"[DEMO] {policy_name} Demonstration Policy",
                        coverage_limit,
                        waiting_period_days,
                        claim_filing_window_days,
                    ),
                )
                policy_id = str((await cur.fetchone())[0])

            # Ensure version 1 exists
            await cur.execute(
                "SELECT id FROM policy_versions WHERE policy_id = %s AND version_number = 1;",
                (policy_id,),
            )
            vrow = await cur.fetchone()
            if vrow:
                version_id = str(vrow[0])
            else:
                terms_tagged = dict(terms_json)
                terms_tagged["is_demo"] = True
                terms_str = json.dumps(terms_tagged, sort_keys=True)
                checksum = hashlib.sha256(terms_str.encode("utf-8")).hexdigest()
                await cur.execute(
                    """
                    INSERT INTO policy_versions (
                        policy_id, version_number, document_storage_ref,
                        document_checksum, effective_date, terms_json,
                        is_published, published_at
                    )
                    VALUES (%s, 1, %s, %s, %s, %s::jsonb, TRUE, %s)
                    RETURNING id;
                    """,
                    (
                        policy_id,
                        f"policies/{policy_code.lower()}_v1.pdf",
                        checksum,
                        date.today() - timedelta(days=version_effective_offset_days),
                        terms_str,
                        datetime.now(timezone.utc),
                    ),
                )
                version_id = str((await cur.fetchone())[0])

        return policy_id, version_id

    async def _ensure_demo_registration(
        self,
        conn: psycopg.AsyncConnection,
        customer_id: str,
        policy_id: str,
        policy_version_id: str,
        scenario_id: str,
        agent_id: Optional[str] = None,
        effective_offset_days: int = 60,
    ) -> str:
        """Idempotently ensures confirmed policy registration exists for customer."""
        sql = """
        SELECT id FROM policy_registrations
        WHERE customer_id = %s AND policy_id = %s AND status = 'CONFIRMED';
        """
        async with conn.cursor() as cur:
            await cur.execute(sql, (customer_id, policy_id))
            row = await cur.fetchone()
            if row:
                return str(row[0])

            activated_at = datetime.now(timezone.utc) - timedelta(days=effective_offset_days)
            await cur.execute(
                """
                INSERT INTO policy_registrations (
                    customer_id, agent_id, policy_id, policy_version_id,
                    status, customer_consent, consent_timestamp,
                    consent_notes, activated_at
                )
                VALUES (%s, %s, %s, %s, 'CONFIRMED', TRUE, %s, %s, %s)
                RETURNING id;
                """,
                (
                    customer_id,
                    agent_id,
                    policy_id,
                    policy_version_id,
                    activated_at,
                    f"[DEMO: {scenario_id}] Customer confirmed terms.",
                    activated_at,
                ),
            )
            return str((await cur.fetchone())[0])

    async def seed_scenario(
        self, conn: psycopg.AsyncConnection, scenario_id: str
    ) -> DemoSeedResult:
        """
        Idempotently seeds a single demonstration scenario.
        If scenario records already exist, returns existing state without modifying or wiping records.
        """
        scn = self.get_scenario_definition(scenario_id)
        if not scn:
            raise NotFoundException(f"Scenario '{scenario_id}' not found.")

        today = date.today()
        now = datetime.now(timezone.utc)

        # -------------------------------------------------------------
        # Scenario 15: Tamper-Evident Merkle Audit Verification
        # -------------------------------------------------------------
        if scn.scenario_id == "DEMO-SCN-15":
            tamper_res = self.verify_synthetic_merkle_fixture()
            return DemoSeedResult(
                scenario_id="DEMO-SCN-15",
                seeded=True,
                status="VERIFIED_IN_MEMORY",
                message=(
                    f"Scenario 15 verified synthetic fixture in-memory: "
                    f"authentic_valid={tamper_res.authentic_proof_valid}, "
                    f"tampered_valid={tamper_res.tampered_proof_valid}. No DB modification."
                ),
            )

        # -------------------------------------------------------------
        # Scenario 03: VoiceGuard Mis-selling & Policy Verification
        # -------------------------------------------------------------
        if scn.scenario_id == "DEMO-SCN-03":
            # Check if already seeded
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id FROM sales_sessions WHERE consent_notes LIKE %s;",
                    (f"%[DEMO: {scn.scenario_id}]%",),
                )
                existing_sess = await cur.fetchone()
                if existing_sess:
                    return DemoSeedResult(
                        scenario_id=scn.scenario_id,
                        seeded=False,
                        status="ALREADY_EXISTS",
                        session_id=str(existing_sess[0]),
                        message=f"Scenario {scn.scenario_id} already exists. Preserved without modification.",
                    )

            # Setup customer and agent
            customer = await self._ensure_demo_user(
                conn, "demo_cust_03@vachan.local", "Vikram Sharma", "CUSTOMER"
            )
            agent = await self._ensure_demo_user(
                conn, "demo_agent_03@vachan.local", "Rohit Verma", "INSURANCE_AGENT"
            )

            # Published Care Premier Health Shield terms (Exact wording)
            published_terms = {
                "policy_name": "Care Premier Health Shield",
                "room_rent_cap": "Up to 1% of sum insured per day; ICU up to 2%",
                "waiting_period_general_days": 30,
                "waiting_period_pre_existing_months": 24,
                "co_payment_percentage": 10,
                "exclusions": ["Cosmetic surgery", "Self-inflicted injury", "Experimental treatments"],
            }
            policy_id, version_id = await self._ensure_demo_policy(
                conn,
                "DEMO-POL-HLT-03",
                "Care Premier Health Shield",
                "HOSPITALIZATION",
                "1500000.00",
                30,
                45,
                published_terms,
            )
            reg_id = await self._ensure_demo_registration(
                conn, customer["id"], policy_id, version_id, scn.scenario_id, agent["id"]
            )

            # Synthetic voice sales transcript with spoken mis-selling claims
            transcript_text = (
                "Agent: Namaste Mr. Vikram Sharma. I am calling from Care Premier regarding your "
                "Care Premier Health Shield policy. I am pleased to inform you that under this plan, "
                "all your pre-existing conditions including diabetes and hypertension are covered "
                "immediately from day one with zero waiting period. Moreover, there is no limit on ICU "
                "room rent; you get unlimited ICU room rent coverage.\n"
                "Customer: That sounds great, especially having no waiting period for my hypertension. "
                "I confirm my acceptance."
            )
            transcript_hash = hashlib.sha256(transcript_text.encode("utf-8")).hexdigest()

            # Create sales session
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO sales_sessions (
                        customer_id, agent_id, policy_id, policy_version_id, registration_id,
                        audio_storage_ref, audio_mime_type, audio_file_size_bytes, duration_seconds,
                        audio_checksum, customer_consent, consent_timestamp, consent_notes,
                        status, transcript, detected_language, provider_model
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s, 'COMPLETED', %s, 'en', 'elevenlabs-demo-model')
                    RETURNING id;
                    """,
                    (
                        customer["id"],
                        agent["id"],
                        policy_id,
                        version_id,
                        reg_id,
                        "audio/demo_sales_session_03.wav",
                        "audio/wav",
                        128000,
                        45,
                        transcript_hash,
                        now - timedelta(days=20),
                        f"[DEMO: {scn.scenario_id}] Voice sales session with recorded consent.",
                        transcript_text,
                    ),
                )
                session_id = str((await cur.fetchone())[0])

                # Create verification report flagging contradiction with exact ground truth
                findings_json = [
                    {
                        "claim_index": 1,
                        "spoken_statement": "Pre-existing conditions including diabetes and hypertension are covered immediately from day one with zero waiting period.",
                        "policy_ground_truth": "Clause 4.1: Pre-existing diseases are subject to a mandatory 24-month waiting period from policy inception before coverage applies (waiting_period_pre_existing_months: 24).",
                        "status": "CONTRADICTED",
                        "confidence": 0.96,
                    },
                    {
                        "claim_index": 2,
                        "spoken_statement": "There is no limit on ICU room rent; you get unlimited ICU room rent coverage.",
                        "policy_ground_truth": "Clause 3.2: ICU room rent is capped at a maximum of 2% of sum insured per day (room_rent_cap: Up to 1% per day; ICU up to 2%).",
                        "status": "CONTRADICTED",
                        "confidence": 0.95,
                    },
                ]
                await cur.execute(
                    """
                    INSERT INTO verification_reports (
                        sales_session_id, customer_id, agent_id, policy_id, policy_version_id,
                        transcript_checksum, report_version, status, model_identifier,
                        summary, overall_integrity_status, findings,
                        supported_count, partly_true_count, contradicted_count, not_in_policy_count,
                        unclear_count, review_flags
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 1, 'COMPLETED', 'gemini-1.5-pro-demo',
                            %s, 'MISLEADING_CLAIMS_DETECTED', %s::jsonb, 0, 0, 2, 0, 0, %s::jsonb)
                    RETURNING id;
                    """,
                    (
                        session_id,
                        customer["id"],
                        agent["id"],
                        policy_id,
                        version_id,
                        transcript_hash,
                        "Agent statements directly contradict published policy waiting periods and ICU room rent caps.",
                        json.dumps({"is_demo": True, "scenario_id": scn.scenario_id, "findings": findings_json}),
                        json.dumps(["CONTRADICTION_PRE_EXISTING_WAITING_PERIOD", "CONTRADICTION_ICU_ROOM_RENT_CAP"]),
                    ),
                )

            return DemoSeedResult(
                scenario_id=scn.scenario_id,
                seeded=True,
                status="SEEDED",
                session_id=session_id,
                policy_id=policy_id,
                customer_email=customer["email"],
                message=f"Scenario {scn.scenario_id} seeded successfully with published policy contradictions.",
            )

        # -------------------------------------------------------------
        # Claim Scenarios (01, 02, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14)
        # -------------------------------------------------------------
        # Check if claim for this scenario already exists
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id FROM claims WHERE structured_details->>'scenario_id' = %s;",
                (scn.scenario_id,),
            )
            existing_claim = await cur.fetchone()
            if existing_claim:
                return DemoSeedResult(
                    scenario_id=scn.scenario_id,
                    seeded=False,
                    status="ALREADY_EXISTS",
                    claim_id=str(existing_claim[0]),
                    message=f"Scenario {scn.scenario_id} already exists. Preserved without modification.",
                )

        # Build specific parameters per scenario
        claim_params = await self._build_scenario_claim_data(conn, scn, today, now)
        claim_id = await self._insert_scenario_claim(conn, scn, claim_params)

        return DemoSeedResult(
            scenario_id=scn.scenario_id,
            seeded=True,
            status="SEEDED",
            claim_id=claim_id,
            policy_id=claim_params["policy_id"],
            customer_email=claim_params["customer"]["email"],
            message=f"Scenario {scn.scenario_id} seeded and evaluated successfully ({scn.expected_outcome}).",
        )

    async def _build_scenario_claim_data(
        self,
        conn: psycopg.AsyncConnection,
        scn: DemoScenarioDefinition,
        today: date,
        now: datetime,
    ) -> Dict[str, Any]:
        """Constructs data, policies, and evidence bytes per scenario definition."""
        cust_num = scn.scenario_id.split("-")[-1]
        customer = await self._ensure_demo_user(
            conn, f"demo_cust_{cust_num}@vachan.local", f"Claimant {cust_num}", "CUSTOMER"
        )
        agent = await self._ensure_demo_user(
            conn, f"demo_agent_{cust_num}@vachan.local", f"Agent {cust_num}", "INSURANCE_AGENT"
        )

        # Default policy setup
        if scn.category == "VEHICLE":
            limit = "25000.00" if scn.scenario_id == "DEMO-SCN-05" else "50000.00"
            filing = 30
            waiting = 0
            exclusions = ["Commercial racing", "Driving under influence"]
            terms = {
                "zero_depreciation": True,
                "exclusions": exclusions,
                "required_evidence": ["REGISTRATION_CERTIFICATE", "VEHICLE_REPAIR_ESTIMATE"],
            }
            policy_id, version_id = await self._ensure_demo_policy(
                conn, f"DEMO-POL-MOT-{cust_num}", scn.policy_name, "VEHICLE", limit, waiting, filing, terms
            )
            reg_id = await self._ensure_demo_registration(
                conn, customer["id"], policy_id, version_id, scn.scenario_id, agent_id=agent["id"], effective_offset_days=90
            )
        else:  # MEDICAL
            limit = "200000.00"
            filing = 45
            waiting = 90 if scn.scenario_id == "DEMO-SCN-06" else 30
            exclusions = ["Cosmetic surgery", "Self-inflicted injury"]
            terms = {
                "room_rent_cap": "Up to 1% of sum insured per day",
                "exclusions": exclusions,
                "required_evidence": ["MEDICAL_BILL", "DISCHARGE_SUMMARY"],
            }
            ver_offset = 5 if scn.scenario_id == "DEMO-SCN-06" else 180
            policy_id, version_id = await self._ensure_demo_policy(
                conn, f"DEMO-POL-HLT-{cust_num}", scn.policy_name, "HOSPITALIZATION", limit, waiting, filing, terms,
                version_effective_offset_days=ver_offset,
            )
            # Inception offset: for SCN-06 inception is 30d ago (waiting is 90d, incident is 10d ago)
            eff_offset = 30 if scn.scenario_id == "DEMO-SCN-06" else 120
            reg_id = await self._ensure_demo_registration(
                conn, customer["id"], policy_id, version_id, scn.scenario_id, agent_id=agent["id"], effective_offset_days=eff_offset
            )

        # Retrieve policy and version dicts for engine evaluation
        policy = await policy_repo.get_policy_by_id(conn, policy_id)
        version = await policy_repo.get_policy_version_by_id(conn, version_id)
        registration = await registration_repo.get_registration_by_id(conn, reg_id)

        # Default dates and amounts
        incident_date = today - timedelta(days=5)
        submission_ts = now - timedelta(days=2)
        requested_amount = Decimal("18500.00")
        desc = "Standard claim filing for insured incident."
        structured: Dict[str, Any] = {
            "is_demo": True,
            "scenario_id": scn.scenario_id,
            "claimant_name": customer["full_name"],
        }
        evidence_files: List[Dict[str, Any]] = []

        # Scenario customizations
        if scn.scenario_id == "DEMO-SCN-01":
            requested_amount = Decimal("18500.00")
            pdf_bytes = self._generate_invoice_pdf(
                title="Vehicle Repair Estimate & Tax Invoice",
                provider_name="Speedy Motors Workshop",
                tax_id="27AABCS1429B1Z8",
                invoice_number="INV-MOT-0101",
                invoice_date_str=(today - timedelta(days=3)).strftime("%d/%m/%Y"),
                line_items=[
                    ("Bumper Replacement", "1", "12000.00", "12000.00"),
                    ("Paint & Labour Charges", "1", "6500.00", "6500.00"),
                ],
                subtotal_str="18500.00",
                tax_str="0.00",
                total_str="18500.00",
            )
            evidence_files.append({
                "type": "VEHICLE_REPAIR_ESTIMATE",
                "filename": "repair_estimate_scn01.pdf",
                "mime": "application/pdf",
                "bytes": pdf_bytes,
            })
            evidence_files.append({
                "type": "REGISTRATION_CERTIFICATE",
                "filename": "vehicle_rc_scn01.pdf",
                "mime": "application/pdf",
                "bytes": b"%PDF-1.4\n%RC-CERTIFICATE-SCN01\n",
            })

        elif scn.scenario_id == "DEMO-SCN-02":
            requested_amount = Decimal("64200.00")
            incident_date = today - timedelta(days=10)
            submission_ts = now - timedelta(days=4)
            pdf_bytes = self._generate_invoice_pdf(
                title="Tax Invoice - Hospitalization Bill",
                provider_name="Apex Multispeciality Hospital",
                tax_id="27AABCA1234F1Z5",
                invoice_number="INV-MED-0201",
                invoice_date_str=(today - timedelta(days=6)).strftime("%d/%m/%Y"),
                line_items=[
                    ("Room & Nursing Charges", "4", "5000.00", "20000.00"),
                    ("Surgical & Specialist Procedure", "1", "35000.00", "35000.00"),
                    ("Medicines & Consumables", "1", "9200.00", "9200.00"),
                ],
                subtotal_str="64200.00",
                tax_str="0.00",
                total_str="64200.00",
                admission_date_str=(today - timedelta(days=10)).strftime("%d/%m/%Y"),
                discharge_date_str=(today - timedelta(days=6)).strftime("%d/%m/%Y"),
            )
            evidence_files.append({
                "type": "MEDICAL_BILL",
                "filename": "hospital_bill_scn02.pdf",
                "mime": "application/pdf",
                "bytes": pdf_bytes,
            })
            evidence_files.append({
                "type": "DISCHARGE_SUMMARY",
                "filename": "discharge_summary_scn02.pdf",
                "mime": "application/pdf",
                "bytes": b"%PDF-1.4\n%DISCHARGE-SUMMARY-SCN02\n",
            })

        elif scn.scenario_id == "DEMO-SCN-04":
            # Late claim: incident 55 days ago vs 30d window
            incident_date = today - timedelta(days=55)
            submission_ts = now - timedelta(days=2)
            requested_amount = Decimal("12000.00")

        elif scn.scenario_id == "DEMO-SCN-05":
            # Requested ₹38,000 exceeds ₹25,000 limit
            incident_date = today - timedelta(days=7)
            requested_amount = Decimal("38000.00")

        elif scn.scenario_id == "DEMO-SCN-06":
            # In waiting period: policy effective 30d ago, incident 10d ago (<90d waiting)
            incident_date = today - timedelta(days=10)
            requested_amount = Decimal("50000.00")

        elif scn.scenario_id == "DEMO-SCN-07":
            # Duplicate claim candidate setup
            requested_amount = Decimal("15000.00")
            incident_date = today - timedelta(days=4)
            structured["vehicle_registration_number"] = "KA-01-MJ-4040"
            # Ensure base claim exists first for comparison
            base_claim_sql = """
            SELECT id FROM claims WHERE structured_details->>'vehicle_registration_number' = 'KA-01-MJ-4040';
            """
            async with conn.cursor() as cur:
                await cur.execute(base_claim_sql)
                if not await cur.fetchone():
                    # Insert primary claim
                    await cur.execute(
                        """
                        INSERT INTO claims (
                            customer_id, registration_id, policy_id, policy_version_id,
                            claim_category, requested_amount, incident_date, submission_timestamp,
                            description, structured_details, status
                        )
                        VALUES (%s, %s, %s, %s, 'VEHICLE', 15000.00, %s, %s, 'Initial accident claim', %s::jsonb, 'SUBMITTED');
                        """,
                        (
                            customer["id"],
                            reg_id,
                            policy_id,
                            version_id,
                            incident_date,
                            submission_ts - timedelta(days=1),
                            json.dumps({
                                "is_demo": True,
                                "scenario_id": "DEMO-SCN-07-BASE",
                                "vehicle_registration_number": "KA-01-MJ-4040",
                            }),
                        ),
                    )

        elif scn.scenario_id == "DEMO-SCN-08":
            # Line items mismatch: items sum to 30,000, printed total is 38,000
            requested_amount = Decimal("38000.00")
            pdf_bytes = self._generate_invoice_pdf(
                title="Hospital Bill - Tax Invoice",
                provider_name="City General Hospital",
                tax_id="27AABCC5555D1Z2",
                invoice_number="INV-MED-0801",
                invoice_date_str=(today - timedelta(days=3)).strftime("%d/%m/%Y"),
                line_items=[
                    ("Room Charges", "1", "10000.00", "10000.00"),
                    ("Surgeon Charges", "1", "15000.00", "15000.00"),
                    ("Pharmacy Charges", "1", "5000.00", "5000.00"),
                ],
                subtotal_str="38000.00",  # Mismatch: 10k + 15k + 5k = 30k != 38k
                tax_str="0.00",
                total_str="38000.00",
            )
            evidence_files.append({
                "type": "MEDICAL_BILL",
                "filename": "mismatched_invoice_scn08.pdf",
                "mime": "application/pdf",
                "bytes": pdf_bytes,
            })
            evidence_files.append({
                "type": "DISCHARGE_SUMMARY",
                "filename": "discharge_scn08.pdf",
                "mime": "application/pdf",
                "bytes": b"%PDF-1.4\n%DISCHARGE-SUMMARY-SCN08\n",
            })

        elif scn.scenario_id == "DEMO-SCN-09":
            # Claimed ₹45,000 but invoice total is ₹27,500
            requested_amount = Decimal("45000.00")
            pdf_bytes = self._generate_invoice_pdf(
                title="Motor Repair Tax Invoice",
                provider_name="Metro Collision Center",
                tax_id="27AABCM9876E1Z1",
                invoice_number="INV-MOT-0901",
                invoice_date_str=(today - timedelta(days=2)).strftime("%d/%m/%Y"),
                line_items=[
                    ("Body Panel Denting", "1", "15000.00", "15000.00"),
                    ("Surface Painting", "1", "12500.00", "12500.00"),
                ],
                subtotal_str="27500.00",
                tax_str="0.00",
                total_str="27500.00",
            )
            evidence_files.append({
                "type": "VEHICLE_REPAIR_ESTIMATE",
                "filename": "repair_estimate_scn09.pdf",
                "mime": "application/pdf",
                "bytes": pdf_bytes,
            })
            evidence_files.append({
                "type": "REGISTRATION_CERTIFICATE",
                "filename": "rc_scn09.pdf",
                "mime": "application/pdf",
                "bytes": b"%PDF-1.4\n%RC-SCN09\n",
            })

        elif scn.scenario_id == "DEMO-SCN-10":
            # Timeline error: invoice dated T-12d, incident was T-5d (invoice predates incident)
            incident_date = today - timedelta(days=5)
            requested_amount = Decimal("20000.00")
            pdf_bytes = self._generate_invoice_pdf(
                title="Automobile Repair Tax Invoice",
                provider_name="QuickFix Bodyworks",
                tax_id="27AABCB4321A1Z0",
                invoice_number="INV-MOT-1001",
                invoice_date_str=(today - timedelta(days=12)).strftime("%d/%m/%Y"),  # 7 days before incident
                line_items=[("Suspension Overhaul", "1", "20000.00", "20000.00")],
                subtotal_str="20000.00",
                tax_str="0.00",
                total_str="20000.00",
            )
            evidence_files.append({
                "type": "VEHICLE_REPAIR_ESTIMATE",
                "filename": "predated_invoice_scn10.pdf",
                "mime": "application/pdf",
                "bytes": pdf_bytes,
            })
            evidence_files.append({
                "type": "REGISTRATION_CERTIFICATE",
                "filename": "rc_scn10.pdf",
                "mime": "application/pdf",
                "bytes": b"%PDF-1.4\n%RC-SCN10\n",
            })

        elif scn.scenario_id == "DEMO-SCN-11":
            # Tax mismatch: Subtotal 50,000, Tax 9,000, Total printed 65,000
            requested_amount = Decimal("65000.00")
            pdf_bytes = self._generate_invoice_pdf(
                title="Hospital Treatment Tax Invoice",
                provider_name="Prime Health Hospital",
                tax_id="27AABCP7777H1Z9",
                invoice_number="INV-MED-1101",
                invoice_date_str=(today - timedelta(days=3)).strftime("%d/%m/%Y"),
                line_items=[
                    ("ICU Treatment", "1", "30000.00", "30000.00"),
                    ("Diagnostics & Scans", "1", "20000.00", "20000.00"),
                ],
                subtotal_str="50000.00",
                tax_str="9000.00",
                total_str="65000.00",  # Error: 50,000 + 9,000 = 59,000 != 65,000
            )
            evidence_files.append({
                "type": "MEDICAL_BILL",
                "filename": "tax_error_invoice_scn11.pdf",
                "mime": "application/pdf",
                "bytes": pdf_bytes,
            })
            evidence_files.append({
                "type": "DISCHARGE_SUMMARY",
                "filename": "discharge_scn11.pdf",
                "mime": "application/pdf",
                "bytes": b"%PDF-1.4\n%DISCHARGE-SCN11\n",
            })

        elif scn.scenario_id == "DEMO-SCN-12":
            # Corrupted unreadable bytes passed to real OCR engine
            requested_amount = Decimal("14000.00")
            evidence_files.append({
                "type": "VEHICLE_REPAIR_ESTIMATE",
                "filename": "corrupted_scan_scn12.pdf",
                "mime": "application/pdf",
                "bytes": b"CORRUPTED_NON_PDF_UNREADABLE_SCAN_BYTES_SCENARIO_12_TEST",
            })
            evidence_files.append({
                "type": "REGISTRATION_CERTIFICATE",
                "filename": "rc_scn12.pdf",
                "mime": "application/pdf",
                "bytes": b"%PDF-1.4\n%RC-SCN12\n",
            })

        elif scn.scenario_id == "DEMO-SCN-13":
            # Policy exclusion triggered in description
            requested_amount = Decimal("22000.00")
            desc = (
                "Vehicle sustained heavy front-end collision damage during participation "
                "in a commercial racing or speed contest event at local track."
            )
            evidence_files.append({
                "type": "VEHICLE_REPAIR_ESTIMATE",
                "filename": "repair_scn13.pdf",
                "mime": "application/pdf",
                "bytes": b"%PDF-1.4\n%REPAIR-SCN13\n",
            })
            evidence_files.append({
                "type": "REGISTRATION_CERTIFICATE",
                "filename": "rc_scn13.pdf",
                "mime": "application/pdf",
                "bytes": b"%PDF-1.4\n%RC-SCN13\n",
            })

        elif scn.scenario_id == "DEMO-SCN-14":
            # Missing mandatory discharge summary
            requested_amount = Decimal("35000.00")
            pdf_bytes = self._generate_invoice_pdf(
                title="Hospital Treatment Bill",
                provider_name="City Care Clinic",
                tax_id="27AABCC1111B1Z4",
                invoice_number="INV-MED-1401",
                invoice_date_str=(today - timedelta(days=3)).strftime("%d/%m/%Y"),
                line_items=[("Treatment & Medicines", "1", "35000.00", "35000.00")],
                subtotal_str="35000.00",
                tax_str="0.00",
                total_str="35000.00",
            )
            # Only upload bill, omit discharge summary
            evidence_files.append({
                "type": "MEDICAL_BILL",
                "filename": "hospital_bill_scn14.pdf",
                "mime": "application/pdf",
                "bytes": pdf_bytes,
            })

        return {
            "customer": customer,
            "policy": policy,
            "policy_version": version,
            "registration": registration,
            "policy_id": policy_id,
            "policy_version_id": version_id,
            "registration_id": reg_id,
            "category": scn.category,
            "requested_amount": requested_amount,
            "incident_date": incident_date,
            "submission_timestamp": submission_ts,
            "description": desc,
            "structured_details": structured,
            "evidence_files": evidence_files,
        }

    async def _insert_scenario_claim(
        self,
        conn: psycopg.AsyncConnection,
        scn: DemoScenarioDefinition,
        params: Dict[str, Any],
    ) -> str:
        """Inserts claim, evidence files, performs OCR/invoice analysis, and evaluates deterministic eligibility."""
        customer = params["customer"]
        policy = params["policy"]
        version = params["policy_version"]
        registration = params["registration"]

        # 1. Insert claim
        sql_claim = """
        INSERT INTO claims (
            customer_id, registration_id, policy_id, policy_version_id,
            claim_category, requested_amount, incident_date, submission_timestamp,
            description, structured_details, status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, 'SUBMITTED')
        RETURNING id;
        """
        async with conn.cursor() as cur:
            await cur.execute(
                sql_claim,
                (
                    customer["id"],
                    params["registration_id"],
                    params["policy_id"],
                    params["policy_version_id"],
                    params["category"],
                    params["requested_amount"],
                    params["incident_date"],
                    params["submission_timestamp"],
                    params["description"],
                    json.dumps(params["structured_details"]),
                ),
            )
            claim_id = str((await cur.fetchone())[0])

        target_claim = await claim_repo.get_claim_by_id(conn, claim_id)

        # 2. Insert and analyze evidence documents
        persisted_evidence_list: List[Dict[str, Any]] = []
        for ef in params["evidence_files"]:
            file_bytes = ef["bytes"]
            checksum = hashlib.sha256(file_bytes).hexdigest()
            doc_ref = f"demo_evidence/{claim_id}/{ef['filename']}"

            evidence_row = await claim_evidence_repo.create_evidence(
                conn,
                claim_id=claim_id,
                uploader_id=customer["id"],
                evidence_type=ef["type"],
                original_filename=ef["filename"],
                document_storage_ref=doc_ref,
                file_size_bytes=len(file_bytes),
                mime_type=ef["mime"],
                document_checksum=checksum,
                resource_metadata={"is_demo": True, "scenario_id": scn.scenario_id},
            )
            persisted_evidence_list.append(evidence_row)

            # Run OCR and invoice analysis pipeline on file bytes
            try:
                await self.evidence_service.analyze_evidence_document(
                    conn,
                    claim_id=claim_id,
                    evidence_id=evidence_row["id"],
                    content=file_bytes,
                    actor_id=customer["id"],
                    actor_role="CUSTOMER",
                )
            except Exception as exc:
                logger.warning(f"Demo analysis execution handled for {ef['filename']}: {exc}")

        # 3. Duplicate check for duplicate detector rule
        dup_count = 0
        if scn.scenario_id == "DEMO-SCN-07":
            candidates = await duplicate_detector.find_candidates(conn, target_claim)
            dup_count = len(candidates)

        # 4. Deterministic eligibility assessment
        eval_result = eligibility_engine.evaluate_claim(
            claim=target_claim,
            registration=registration,
            policy=policy,
            policy_version=version,
            evidence_list=persisted_evidence_list,
            duplicate_candidate_count=dup_count,
        )

        rules_evaluated_dicts = [
            {
                "rule_id": r.rule_id,
                "result": r.result.value if hasattr(r.result, "value") else str(r.result),
                "explanation": r.explanation,
                "details": r.details,
            }
            for r in eval_result.rules_evaluated
        ]

        await assessment_repo.create_assessment(
            conn,
            claim_id=claim_id,
            policy_version_id=params["policy_version_id"],
            overall_outcome=(
                eval_result.overall_outcome.value
                if hasattr(eval_result.overall_outcome, "value")
                else str(eval_result.overall_outcome)
            ),
            rules_evaluated=rules_evaluated_dicts,
            requested_amount=eval_result.requested_amount,
            applicable_limit=eval_result.applicable_limit,
            potentially_payable_amount=eval_result.potentially_payable_amount,
            excess_amount=eval_result.excess_amount,
            missing_evidence=eval_result.missing_evidence,
            review_flags=eval_result.review_flags,
            assessed_by=None,
        )

        # 5. Record initial status history
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO claim_status_history (
                    claim_id, actor_id, actor_role, previous_status, new_status,
                    reason, decision_metadata
                )
                VALUES (%s, %s, 'CUSTOMER', 'SUBMITTED', 'UNDER_REVIEW', %s, %s::jsonb);
                """,
                (
                    claim_id,
                    customer["id"],
                    f"Initial automated assessment completed: {eval_result.overall_outcome.value}",
                    json.dumps({"is_demo": True, "scenario_id": scn.scenario_id}),
                ),
            )
            # Update claim status
            await cur.execute(
                "UPDATE claims SET status = 'UNDER_REVIEW', updated_at = NOW() WHERE id = %s;",
                (claim_id,),
            )

        return claim_id

    async def seed_all_scenarios(
        self, conn: psycopg.AsyncConnection
    ) -> List[DemoSeedResult]:
        """Seeds all 15 scenarios in deterministic order."""
        results: List[DemoSeedResult] = []
        for scn in SCENARIO_DEFINITIONS:
            res = await self.seed_scenario(conn, scn.scenario_id)
            results.append(res)
        return results

    def verify_synthetic_merkle_fixture(self) -> DemoTamperCheckResult:
        """
        Executes Scenario 15: In-memory synthetic fixture verification proving cryptographic tamper detection.
        Zero database modification, zero database contamination, zero blockchain calls.
        """
        synthetic_events = [
            {
                "sequence": 1,
                "actor_id": "usr-demo-001",
                "action": "CUSTOMER_REGISTRATION_CONFIRMED",
                "timestamp": "2026-11-10T09:00:00Z",
                "policy_code": "DEMO-POL-HLT-01",
            },
            {
                "sequence": 2,
                "actor_id": "usr-demo-002",
                "action": "VOICE_CONSENT_RECORDED",
                "timestamp": "2026-11-10T09:15:00Z",
                "duration_seconds": 45,
            },
            {
                "sequence": 3,
                "actor_id": "usr-demo-001",
                "action": "CLAIM_SUBMITTED",
                "timestamp": "2026-11-12T14:30:00Z",
                "requested_amount": "18500.00",
            },
            {
                "sequence": 4,
                "actor_id": "usr-auth-001",
                "action": "ELIGIBILITY_ASSESSMENT_COMPLETED",
                "timestamp": "2026-11-12T14:31:00Z",
                "outcome": "ELIGIBLE",
            },
        ]

        leaf_hashes = [
            sha256_hex(json.dumps(evt, sort_keys=True)) for evt in synthetic_events
        ]
        tree = MerkleTree(leaf_hashes)
        authentic_root = tree.root

        # Audit inclusion proof for Event 3 (index 2: CLAIM_SUBMITTED)
        target_index = 2
        proof = tree.get_proof(target_index)

        # 1. Authentic proof verification
        authentic_valid = verify_merkle_proof(
            leaf_hash=leaf_hashes[target_index],
            proof=proof,
            expected_root=authentic_root,
        )

        # 2. Tampered event simulation (altering requested_amount in Event 3 payload)
        tampered_event = dict(synthetic_events[target_index])
        tampered_event["requested_amount"] = "99999.00"  # Tampered amount
        tampered_leaf = sha256_hex(json.dumps(tampered_event, sort_keys=True))
        tampered_valid = verify_merkle_proof(
            leaf_hash=tampered_leaf,
            proof=proof,
            expected_root=authentic_root,
        )

        return DemoTamperCheckResult(
            scenario_id="DEMO-SCN-15",
            authentic_root=authentic_root,
            leaf_count=len(leaf_hashes),
            tested_leaf_index=target_index,
            tested_event_id=f"seq-{synthetic_events[target_index]['sequence']}",
            authentic_proof_valid=authentic_valid,
            tampered_leaf_hash=tampered_leaf,
            tampered_proof_valid=tampered_valid,
            tamper_detected=(not tampered_valid),
            verification_explanation=(
                f"Synthetic Merkle tree built from {len(leaf_hashes)} audit events. "
                f"Authentic inclusion proof verified successfully (valid={authentic_valid}). "
                f"When event payload was tampered in-memory, cryptographic verification failed (valid={tampered_valid}), "
                f"proving tamper-evidence without database modification or blockchain calls."
            ),
        )

    async def cleanup_demo_data(
        self, conn: psycopg.AsyncConnection, confirm: bool
    ) -> DemoCleanupResult:
        """
        Destructive cleanup operation with strict demo-record filtering.
        Executes cascade deletion in strict reverse foreign-key dependency order.
        Never touches non-demo records.
        """
        if not confirm:
            raise ValidationException("Explicit confirmation (confirm=True) is required for demo cleanup.")

        counts: Dict[str, int] = {}

        async with conn.cursor() as cur:
            # 1. evidence_analysis_reports for demo claims
            await cur.execute(
                """
                DELETE FROM evidence_analysis_reports
                WHERE claim_id IN (
                    SELECT id FROM claims WHERE structured_details->>'is_demo' = 'true'
                );
                """
            )
            counts["evidence_analysis_reports"] = cur.rowcount

            # 2. claim_evidence for demo claims
            await cur.execute(
                """
                DELETE FROM claim_evidence
                WHERE resource_metadata->>'is_demo' = 'true'
                   OR claim_id IN (
                       SELECT id FROM claims WHERE structured_details->>'is_demo' = 'true'
                   );
                """
            )
            counts["claim_evidence"] = cur.rowcount

            # 3. claim_status_history for demo claims
            await cur.execute(
                """
                DELETE FROM claim_status_history
                WHERE decision_metadata->>'is_demo' = 'true'
                   OR claim_id IN (
                       SELECT id FROM claims WHERE structured_details->>'is_demo' = 'true'
                   );
                """
            )
            counts["claim_status_history"] = cur.rowcount

            # 4. claim_assessments for demo claims
            await cur.execute(
                """
                DELETE FROM claim_assessments
                WHERE claim_id IN (
                    SELECT id FROM claims WHERE structured_details->>'is_demo' = 'true'
                );
                """
            )
            counts["claim_assessments"] = cur.rowcount

            # 5. claims with is_demo
            await cur.execute(
                "DELETE FROM claims WHERE structured_details->>'is_demo' = 'true';"
            )
            counts["claims"] = cur.rowcount

            # 6. verification_reports for demo sessions
            await cur.execute(
                """
                DELETE FROM verification_reports
                WHERE findings->>'is_demo' = 'true'
                   OR sales_session_id IN (
                       SELECT id FROM sales_sessions WHERE consent_notes LIKE '[DEMO:%'
                   );
                """
            )
            counts["verification_reports"] = cur.rowcount

            # 7. sales_sessions with demo tag
            await cur.execute(
                "DELETE FROM sales_sessions WHERE consent_notes LIKE '[DEMO:%';"
            )
            counts["sales_sessions"] = cur.rowcount

            # 8. policy_registrations with demo tag
            await cur.execute(
                "DELETE FROM policy_registrations WHERE consent_notes LIKE '[DEMO:%';"
            )
            counts["policy_registrations"] = cur.rowcount

            # 9. policy_versions with demo tag
            await cur.execute(
                "DELETE FROM policy_versions WHERE terms_json->>'is_demo' = 'true';"
            )
            counts["policy_versions"] = cur.rowcount

            # 10. policies with DEMO-POL- prefix
            await cur.execute(
                "DELETE FROM policies WHERE policy_code LIKE 'DEMO-POL-%';"
            )
            counts["policies"] = cur.rowcount

            # 11. user_tokens and refresh_tokens for demo users
            await cur.execute(
                """
                DELETE FROM user_tokens
                WHERE user_id IN (
                    SELECT id FROM users WHERE email LIKE 'demo_%@vachan.local'
                );
                """
            )
            await cur.execute(
                """
                DELETE FROM refresh_tokens
                WHERE user_id IN (
                    SELECT id FROM users WHERE email LIKE 'demo_%@vachan.local'
                );
                """
            )

            # 12. audit_logs with demo tag
            await cur.execute(
                "DELETE FROM audit_logs WHERE metadata->>'is_demo' = 'true';"
            )
            counts["audit_logs"] = cur.rowcount

            # 13. users with demo emails
            await cur.execute(
                "DELETE FROM users WHERE email LIKE 'demo_%@vachan.local';"
            )
            counts["users"] = cur.rowcount

        logger.info(f"Demo cleanup completed: {counts}")
        return DemoCleanupResult(
            success=True,
            deleted_records=counts,
            message=f"Cleaned up {sum(counts.values())} demo records across all tables.",
        )


demo_scenario_service = DemoScenarioService()
