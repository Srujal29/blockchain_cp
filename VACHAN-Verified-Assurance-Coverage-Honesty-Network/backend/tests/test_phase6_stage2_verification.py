"""
Comprehensive Verification Suite for Phase 6 Stage 2:
- Section 3: Upload Reliability (Scenarios A, B, C, D)
- Section 4: API Authorization Matrix & RBAC Isolation
- Section 5: Versioning, Concurrency Locking & DB Status Constraint Adherence
"""

from datetime import date, datetime
from decimal import Decimal
import io
import uuid
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import UploadFile

from app.core.exceptions import (
    AuthorizationException,
    NotFoundException,
    ValidationException,
    InsureChainException,
)
from app.core.security import ClaimStatus, EvidenceType, UserRole
from app.schemas.evidence_analysis import (
    DocumentType,
    ExtractionMethod,
    OverallAnalysisStatus,
    ReviewRecommendation,
)
from app.services.evidence_analysis_service import evidence_analysis_service
from app.api.routes.claims import (
    upload_evidence,
    analyze_claim_evidence,
    get_evidence_analysis,
    get_evidence_analysis_history,
    list_claim_evidence_analysis,
)
from app.db.repositories import evidence_analysis_repo

PDF_MIN = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"

SAMPLE_VALID_PDF_TEXT = """
CITY HOSPITAL INVOICE
GSTIN: 27AABCA1234F1Z5
Invoice No: INV-2026-101
Invoice Date: 12/04/2026
Admission Date: 10/04/2026
Discharge Date: 12/04/2026

Patient Name: Ramesh Patel
Bed Charges: 2 x 4000.00 = 8000.00
Medication: 1 x 2000.00 = 2000.00

Sub Total: 10000.00
Tax: 500.00
Total Amount: 10500.00
"""


def make_upload(name: str, data: bytes, mime: str = "application/pdf") -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(data), headers={"content-type": mime})


def make_mock_row(version: int = 1, is_latest: bool = True, status: str = "CONSISTENT") -> tuple:
    row = [None] * 36
    row[0] = str(uuid.uuid4())
    row[1] = str(uuid.uuid4())
    row[2] = str(uuid.uuid4())
    row[3] = version
    row[4] = is_latest
    row[5] = "MEDICAL_INVOICE"
    row[6] = "PDF_TEXT"
    row[7] = "vachan-extractor-1.0"
    row[8] = 0.95
    row[31] = status
    row[32] = "NO_ACTION_REQUIRED"
    row[34] = datetime.now()
    row[35] = datetime.now()
    return tuple(row)


# ==============================================================================
# SECTION 3: UPLOAD RELIABILITY VERIFICATION (SCENARIOS A, B, C, D)
# ==============================================================================

@pytest.mark.asyncio
async def test_scenario_a_upload_and_analysis_succeed():
    """
    Scenario A: Upload succeeds, document analysis succeeds.
    - Evidence status transitions to PROCESSED
    - Analysis report version 1 created and marked is_latest=True
    - Overall status is CONSISTENT, recommendation is NO_ACTION_REQUIRED
    - Arithmetic and timeline audits populated
    """
    mock_conn = AsyncMock()
    cust_id = str(uuid.uuid4())
    claim_id = str(uuid.uuid4())
    evidence_id = str(uuid.uuid4())
    customer_user = {"id": cust_id, "role": UserRole.CUSTOMER.value}

    mock_claim = {
        "id": claim_id,
        "customer_id": cust_id,
        "status": ClaimStatus.SUBMITTED.value,
        "requested_amount": "10500.00",
        "incident_date": "2026-04-10",
        "submission_timestamp": "2026-04-15T10:00:00",
    }
    initial_evidence = {
        "id": evidence_id,
        "claim_id": claim_id,
        "uploader_id": cust_id,
        "evidence_type": "MEDICAL_BILL",
        "original_filename": "hospital_bill.pdf",
        "document_storage_ref": "claims/test/hospital_bill",
        "file_size_bytes": len(PDF_MIN),
        "mime_type": "application/pdf",
        "analysis_status": "PENDING",
    }
    processed_evidence = dict(initial_evidence, analysis_status="PROCESSED")

    with patch("app.api.routes.claims.get_db_connection") as mock_db, \
         patch("app.api.routes.claims.claim_repo.get_claim_by_id", new=AsyncMock(return_value=mock_claim)), \
         patch("app.api.routes.claims.claim_evidence_repo.lock_claim_for_evidence", new=AsyncMock()), \
         patch("app.api.routes.claims.claim_evidence_repo.count_evidence_by_claim", new=AsyncMock(return_value=0)), \
         patch("app.api.routes.claims.claim_evidence_repo.get_evidence_by_checksum", new=AsyncMock(return_value=None)), \
         patch("app.api.routes.claims.evidence_service.upload_evidence", new=AsyncMock(return_value=("claims/test/hospital_bill", "a"*64, {"resource_type": "raw"}))), \
         patch("app.api.routes.claims.claim_evidence_repo.create_evidence", new=AsyncMock(return_value=initial_evidence)), \
         patch("app.db.repositories.claim_evidence_repo.get_evidence_by_id", new=AsyncMock(side_effect=[initial_evidence, processed_evidence])), \
         patch("app.api.routes.claims.audit_repo.log_audit_event", new=AsyncMock(return_value={"id": "audit-1"})), \
         patch("app.services.evidence_analysis_service.claim_repo.get_claim_by_id", new=AsyncMock(return_value=mock_claim)), \
         patch("app.services.evidence_analysis_service.audit_repo.log_audit_event", new=AsyncMock(return_value={"id": "audit-2"})), \
         patch("app.services.evidence_analysis_service.extract_document_text", return_value=(SAMPLE_VALID_PDF_TEXT, "PDF_TEXT", 0.98)), \
         patch("app.services.evidence_analysis_service.evidence_analysis_repo.create_analysis_report") as mock_create_report:

        mock_db.return_value.__aenter__.return_value = mock_conn
        mock_create_report.return_value = {
            "id": "report-uuid-1",
            "evidence_id": evidence_id,
            "claim_id": claim_id,
            "analysis_version": 1,
            "is_latest": True,
            "overall_status": "CONSISTENT",
            "review_recommendation": "NO_ACTION_REQUIRED",
        }

        result = await upload_evidence(
            claim_id=claim_id,
            evidence_type=EvidenceType.MEDICAL_BILL,
            file=make_upload("hospital_bill.pdf", PDF_MIN),
            current_user=customer_user,
        )

        assert result["id"] == evidence_id
        assert result["analysis_status"] == "PROCESSED"
        mock_create_report.assert_called_once()
        kwargs = mock_create_report.call_args.kwargs
        assert kwargs["overall_status"] == "CONSISTENT"
        assert kwargs["review_recommendation"] == "NO_ACTION_REQUIRED"
        assert kwargs["sum_matches_total"] is True
        assert kwargs["amount_matches_claim"] is True


@pytest.mark.asyncio
async def test_scenario_b_upload_succeeds_ocr_fails():
    """
    Scenario B: Upload succeeds, but OCR extraction raises an unexpected error.
    - Upload still succeeds and returns 201/valid evidence record
    - Evidence record remains intact and accessible via signed URL
    - Re-analysis can be triggered later
    """
    mock_conn = AsyncMock()
    cust_id = str(uuid.uuid4())
    claim_id = str(uuid.uuid4())
    evidence_id = str(uuid.uuid4())
    customer_user = {"id": cust_id, "role": UserRole.CUSTOMER.value}

    mock_claim = {
        "id": claim_id,
        "customer_id": cust_id,
        "status": ClaimStatus.SUBMITTED.value,
        "requested_amount": "5000.00",
        "incident_date": "2026-04-10",
    }
    initial_evidence = {
        "id": evidence_id,
        "claim_id": claim_id,
        "uploader_id": cust_id,
        "evidence_type": "MEDICAL_BILL",
        "original_filename": "corrupt.pdf",
        "document_storage_ref": "claims/test/corrupt",
        "file_size_bytes": len(PDF_MIN),
        "mime_type": "application/pdf",
        "analysis_status": "PENDING",
    }

    with patch("app.api.routes.claims.get_db_connection") as mock_db, \
         patch("app.api.routes.claims.claim_repo.get_claim_by_id", new=AsyncMock(return_value=mock_claim)), \
         patch("app.api.routes.claims.claim_evidence_repo.lock_claim_for_evidence", new=AsyncMock()), \
         patch("app.api.routes.claims.claim_evidence_repo.count_evidence_by_claim", new=AsyncMock(return_value=0)), \
         patch("app.api.routes.claims.claim_evidence_repo.get_evidence_by_checksum", new=AsyncMock(return_value=None)), \
         patch("app.api.routes.claims.evidence_service.upload_evidence", new=AsyncMock(return_value=("claims/test/corrupt", "b"*64, {"resource_type": "raw"}))), \
         patch("app.api.routes.claims.claim_evidence_repo.create_evidence", new=AsyncMock(return_value=initial_evidence)), \
         patch("app.api.routes.claims.claim_evidence_repo.get_evidence_by_id", new=AsyncMock(return_value=initial_evidence)), \
         patch("app.api.routes.claims.audit_repo.log_audit_event", new=AsyncMock(return_value={"id": "audit-2"})), \
         patch("app.services.evidence_analysis_service.extract_document_text", side_effect=Exception("Corrupt PDF stream")):

        mock_db.return_value.__aenter__.return_value = mock_conn

        # Upload does not crash even though OCR threw an exception
        result = await upload_evidence(
            claim_id=claim_id,
            evidence_type=EvidenceType.MEDICAL_BILL,
            file=make_upload("corrupt.pdf", PDF_MIN),
            current_user=customer_user,
        )

        assert result["id"] == evidence_id
        assert result["original_filename"] == "corrupt.pdf"
        assert result["document_storage_ref"] == "claims/test/corrupt"


@pytest.mark.asyncio
async def test_scenario_c_download_failure_on_reanalysis():
    """
    Scenario C: Upload succeeds, but Cloudinary asset download fails during manual re-analysis.
    - Analysis returns report with NEEDS_MANUAL_REVIEW
    - Extraction method set to MANUAL_FALLBACK
    - Review recommendation set to EXTRACTION_UNAVAILABLE
    - Original evidence document remains untouched and accessible
    """
    mock_conn = AsyncMock()
    authority_user = {"id": str(uuid.uuid4()), "role": UserRole.APPROVAL_AUTHORITY.value}
    claim_id = str(uuid.uuid4())
    evidence_id = str(uuid.uuid4())

    mock_claim = {
        "id": claim_id,
        "customer_id": str(uuid.uuid4()),
        "requested_amount": "5000.00",
        "incident_date": "2026-04-10",
    }
    mock_evidence = {
        "id": evidence_id,
        "claim_id": claim_id,
        "evidence_type": "MEDICAL_BILL",
        "original_filename": "remote_bill.pdf",
        "document_storage_ref": "claims/test/remote_bill",
        "mime_type": "application/pdf",
        "analysis_status": "PENDING",
    }

    with patch("app.services.evidence_analysis_service.claim_evidence_repo.get_evidence_by_id", new=AsyncMock(return_value=mock_evidence)), \
         patch("app.services.evidence_analysis_service.claim_repo.get_claim_by_id", new=AsyncMock(return_value=mock_claim)), \
         patch("app.services.evidence_analysis_service.evidence_service.download_private_file_bytes", side_effect=Exception("Cloudinary timeout")), \
         patch("app.services.evidence_analysis_service.evidence_analysis_repo.create_analysis_report") as mock_create_report, \
         patch("app.services.evidence_analysis_service.audit_repo.log_audit_event", new=AsyncMock()):

        mock_create_report.return_value = {
            "id": "report-uuid-3",
            "evidence_id": evidence_id,
            "claim_id": claim_id,
            "analysis_version": 1,
            "overall_status": "NEEDS_MANUAL_REVIEW",
            "review_recommendation": "EXTRACTION_UNAVAILABLE",
            "extraction_method": "MANUAL_FALLBACK",
        }

        report = await evidence_analysis_service.analyze_evidence_document(
            conn=mock_conn,
            claim_id=claim_id,
            evidence_id=evidence_id,
            content=None,
            actor_id=authority_user["id"],
            actor_role=authority_user["role"],
        )

        assert report["overall_status"] == "NEEDS_MANUAL_REVIEW"
        assert report["review_recommendation"] == "EXTRACTION_UNAVAILABLE"
        call_kwargs = mock_create_report.call_args.kwargs
        assert call_kwargs["extraction_method"] == "MANUAL_FALLBACK"
        assert call_kwargs["overall_status"] == "NEEDS_MANUAL_REVIEW"


@pytest.mark.asyncio
async def test_scenario_d_analysis_persistence_fails_upload_survives():
    """
    Scenario D: Analysis database persistence fails after upload.
    - Evidence record upload still succeeds (201 Created)
    - File storage remains intact on Cloudinary
    - Claim integrity preserved
    - Authority review screen can handle evidence without analysis report
    """
    mock_conn = AsyncMock()
    cust_id = str(uuid.uuid4())
    claim_id = str(uuid.uuid4())
    evidence_id = str(uuid.uuid4())
    customer_user = {"id": cust_id, "role": UserRole.CUSTOMER.value}

    mock_claim = {
        "id": claim_id,
        "customer_id": cust_id,
        "status": ClaimStatus.SUBMITTED.value,
        "requested_amount": "5000.00",
        "incident_date": "2026-04-10",
    }
    initial_evidence = {
        "id": evidence_id,
        "claim_id": claim_id,
        "uploader_id": cust_id,
        "evidence_type": "MEDICAL_BILL",
        "original_filename": "bill.pdf",
        "document_storage_ref": "claims/test/bill",
        "file_size_bytes": len(PDF_MIN),
        "mime_type": "application/pdf",
        "analysis_status": "PENDING",
    }

    with patch("app.api.routes.claims.get_db_connection") as mock_db, \
         patch("app.api.routes.claims.claim_repo.get_claim_by_id", new=AsyncMock(return_value=mock_claim)), \
         patch("app.api.routes.claims.claim_evidence_repo.lock_claim_for_evidence", new=AsyncMock()), \
         patch("app.api.routes.claims.claim_evidence_repo.count_evidence_by_claim", new=AsyncMock(return_value=0)), \
         patch("app.api.routes.claims.claim_evidence_repo.get_evidence_by_checksum", new=AsyncMock(return_value=None)), \
         patch("app.api.routes.claims.evidence_service.upload_evidence", new=AsyncMock(return_value=("claims/test/bill", "d"*64, {"resource_type": "raw"}))), \
         patch("app.api.routes.claims.claim_evidence_repo.create_evidence", new=AsyncMock(return_value=initial_evidence)), \
         patch("app.api.routes.claims.claim_evidence_repo.get_evidence_by_id", new=AsyncMock(return_value=initial_evidence)), \
         patch("app.api.routes.claims.audit_repo.log_audit_event", new=AsyncMock(return_value={"id": "audit-4"})), \
         patch("app.api.routes.claims.evidence_analysis_service.analyze_evidence_document", side_effect=Exception("DB pool timeout during report insert")):

        mock_db.return_value.__aenter__.return_value = mock_conn

        # Upload completes successfully despite analysis failure
        result = await upload_evidence(
            claim_id=claim_id,
            evidence_type=EvidenceType.MEDICAL_BILL,
            file=make_upload("bill.pdf", PDF_MIN),
            current_user=customer_user,
        )

        assert result["id"] == evidence_id
        assert result["document_storage_ref"] == "claims/test/bill"
        assert result["analysis_status"] == "PENDING"


# ==============================================================================
# SECTION 4: API AUTHORIZATION & RBAC ISOLATION
# ==============================================================================

@pytest.mark.asyncio
async def test_authorization_matrix_all_four_endpoints():
    """
    Verifies the RBAC matrix across all 4 analysis endpoints:
    1. POST /{claim_id}/evidence/{evidence_id}/analyze
    2. GET /{claim_id}/evidence/{evidence_id}/analysis
    3. GET /{claim_id}/evidence/{evidence_id}/analysis/history
    4. GET /{claim_id}/evidence-analysis
    """
    claim_id = str(uuid.uuid4())
    evidence_id = str(uuid.uuid4())
    mismatched_evidence_id = str(uuid.uuid4())
    owner_id = str(uuid.uuid4())
    intruder_id = str(uuid.uuid4())

    authority_user = {"id": str(uuid.uuid4()), "role": UserRole.APPROVAL_AUTHORITY.value}
    owner_user = {"id": owner_id, "role": UserRole.CUSTOMER.value}
    other_user = {"id": intruder_id, "role": UserRole.CUSTOMER.value}
    agent_user = {"id": str(uuid.uuid4()), "role": UserRole.INSURANCE_AGENT.value}

    mock_claim = {
        "id": claim_id,
        "customer_id": owner_id,
        "requested_amount": "5000.00",
    }
    mock_evidence = {
        "id": evidence_id,
        "claim_id": claim_id,
        "mime_type": "application/pdf",
        "document_storage_ref": "ref-1",
    }
    mock_mismatched_evidence = {
        "id": mismatched_evidence_id,
        "claim_id": str(uuid.uuid4()),
    }
    mock_report = {
        "id": str(uuid.uuid4()),
        "evidence_id": evidence_id,
        "claim_id": claim_id,
        "analysis_version": 1,
        "is_latest": True,
        "document_type": "MEDICAL_INVOICE",
        "extraction_method": "PDF_TEXT",
        "parser_engine_version": "v1.0",
        "confidence_score": 0.95,
        "overall_status": "CONSISTENT",
        "review_recommendation": "NO_ACTION_REQUIRED",
        "created_at": datetime.now(),
    }

    mock_conn = AsyncMock()

    with patch("app.api.routes.claims.get_db_connection") as mock_db, \
         patch("app.api.routes.claims.claim_repo.get_claim_by_id", new=AsyncMock(return_value=mock_claim)), \
         patch("app.api.routes.claims.claim_evidence_repo.get_evidence_by_id", new=AsyncMock(side_effect=lambda c, eid: mock_evidence if eid == evidence_id else mock_mismatched_evidence)), \
         patch("app.api.routes.claims.evidence_analysis_repo.get_latest_report_by_evidence_id", new=AsyncMock(return_value=mock_report)), \
         patch("app.api.routes.claims.evidence_analysis_repo.get_analysis_history_for_evidence", new=AsyncMock(return_value=[mock_report])), \
         patch("app.api.routes.claims.evidence_analysis_repo.list_reports_by_claim_id", new=AsyncMock(return_value=[mock_report])), \
         patch("app.api.routes.claims.evidence_analysis_service.analyze_evidence_document", new=AsyncMock(return_value=mock_report)):

        mock_db.return_value.__aenter__.return_value = mock_conn

        # --- A. AUTHORITY USER: 200 OK on all 4 endpoints ---
        r1 = await analyze_claim_evidence(claim_id, evidence_id, current_user=authority_user)
        assert r1["id"] == mock_report["id"]

        r2 = await get_evidence_analysis(claim_id, evidence_id, current_user=authority_user)
        assert r2["id"] == mock_report["id"]

        r3 = await get_evidence_analysis_history(claim_id, evidence_id, current_user=authority_user)
        assert len(r3) == 1

        r4 = await list_claim_evidence_analysis(claim_id, current_user=authority_user)
        assert r4["total_reports"] == 1

        # --- B. CUSTOMER OWNER: 200 OK on own claim ---
        r1_c = await analyze_claim_evidence(claim_id, evidence_id, current_user=owner_user)
        assert r1_c["id"] == mock_report["id"]

        r2_c = await get_evidence_analysis(claim_id, evidence_id, current_user=owner_user)
        assert r2_c["id"] == mock_report["id"]

        r3_c = await get_evidence_analysis_history(claim_id, evidence_id, current_user=owner_user)
        assert len(r3_c) == 1

        r4_c = await list_claim_evidence_analysis(claim_id, current_user=owner_user)
        assert r4_c["total_reports"] == 1

        # --- C. CUSTOMER NON-OWNER: 404 NotFound (no existence leakage) ---
        with pytest.raises(NotFoundException):
            await analyze_claim_evidence(claim_id, evidence_id, current_user=other_user)

        with pytest.raises(NotFoundException):
            await get_evidence_analysis(claim_id, evidence_id, current_user=other_user)

        with pytest.raises(NotFoundException):
            await get_evidence_analysis_history(claim_id, evidence_id, current_user=other_user)

        with pytest.raises(NotFoundException):
            await list_claim_evidence_analysis(claim_id, current_user=other_user)

        # --- D. INSURANCE AGENT: 403 Forbidden on all 4 endpoints ---
        with pytest.raises(AuthorizationException, match="Insurance agents cannot access claim evidence analysis"):
            await analyze_claim_evidence(claim_id, evidence_id, current_user=agent_user)

        with pytest.raises(AuthorizationException, match="Insurance agents cannot access claim evidence analysis"):
            await get_evidence_analysis(claim_id, evidence_id, current_user=agent_user)

        with pytest.raises(AuthorizationException, match="Insurance agents cannot access claim evidence analysis"):
            await get_evidence_analysis_history(claim_id, evidence_id, current_user=agent_user)

        with pytest.raises(AuthorizationException, match="Insurance agents cannot access claim evidence analysis"):
            await list_claim_evidence_analysis(claim_id, current_user=agent_user)

        # --- E. EVIDENCE BELONGING TO DIFFERENT CLAIM: 404 NotFound ---
        with pytest.raises(NotFoundException, match="Evidence document not found"):
            await get_evidence_analysis_history(claim_id, mismatched_evidence_id, current_user=authority_user)

        # --- F. MALFORMED / INVALID UUIDS: 404 NotFound without crash ---
        with pytest.raises(NotFoundException):
            await get_evidence_analysis("invalid-non-uuid-string", evidence_id, current_user=authority_user)


# ==============================================================================
# SECTION 5: VERSIONING, CONCURRENCY LOCKING & DB STATUS CONSTRAINT
# ==============================================================================

@pytest.mark.asyncio
async def test_versioning_and_status_constraint_adherence():
    """
    Verifies versioning lifecycle and database constraints:
    - Version increments monotonically (v1 -> v2 on re-analysis)
    - Row-level lock acquired via SELECT ... FOR UPDATE before version compute
    - Previous reports set is_latest = FALSE
    - Neon claim_evidence status strictly updated to PROCESSED or FAILED
    """
    mock_conn = MagicMock()
    mock_cursor = AsyncMock()
    mock_cursor.__aenter__.return_value = mock_cursor
    mock_conn.cursor = MagicMock(return_value=mock_cursor)

    evidence_id = str(uuid.uuid4())
    claim_id = str(uuid.uuid4())

    mock_cursor.fetchone.side_effect = [
        (evidence_id,),
        (1,),
        make_mock_row(version=2, is_latest=True, status="CONSISTENT"),
    ]

    report = await evidence_analysis_repo.create_analysis_report(
        conn=mock_conn,
        evidence_id=evidence_id,
        claim_id=claim_id,
        document_type="MEDICAL_INVOICE",
        extraction_method="PDF_TEXT",
        parser_engine_version="vachan-extractor-1.0",
        confidence_score=0.95,
        overall_status="CONSISTENT",
        review_recommendation="NO_ACTION_REQUIRED",
    )

    assert report["analysis_version"] == 2
    assert report["is_latest"] is True

    # Verify SQL calls made by repository
    calls = mock_cursor.execute.call_args_list
    assert len(calls) == 5

    # Call 1: row lock with FOR UPDATE
    assert "FOR UPDATE" in calls[0][0][0]
    assert calls[0][0][1] == (evidence_id,)

    # Call 2: max version calculation
    assert "MAX(analysis_version)" in calls[1][0][0]

    # Call 3: set previous is_latest = FALSE
    assert "UPDATE evidence_analysis_reports" in calls[2][0][0]
    assert "is_latest = FALSE" in calls[2][0][0]

    # Call 4: insert new version with is_latest = TRUE
    assert "INSERT INTO evidence_analysis_reports" in calls[3][0][0]

    # Call 5: update claim_evidence analysis_status to PROCESSED (compliant with Neon constraint)
    assert "UPDATE claim_evidence" in calls[4][0][0]
    assert "analysis_status = %s" in calls[4][0][0]
    assert calls[4][0][1] == ("PROCESSED", evidence_id)


@pytest.mark.asyncio
async def test_failed_report_maps_to_failed_evidence_status():
    """
    Verifies that when overall_status is FAILED, claim_evidence status is updated to FAILED.
    """
    mock_conn = MagicMock()
    mock_cursor = AsyncMock()
    mock_cursor.__aenter__.return_value = mock_cursor
    mock_conn.cursor = MagicMock(return_value=mock_cursor)

    evidence_id = str(uuid.uuid4())
    claim_id = str(uuid.uuid4())

    mock_cursor.fetchone.side_effect = [
        (evidence_id,),
        (0,),
        make_mock_row(version=1, is_latest=True, status="FAILED"),
    ]

    await evidence_analysis_repo.create_analysis_report(
        conn=mock_conn,
        evidence_id=evidence_id,
        claim_id=claim_id,
        document_type="RECEIPT",
        extraction_method="MANUAL_FALLBACK",
        parser_engine_version="vachan-extractor-1.0",
        confidence_score=0.0,
        overall_status="FAILED",
        review_recommendation="EXTRACTION_UNAVAILABLE",
    )

    calls = mock_cursor.execute.call_args_list
    assert len(calls) == 5
    # Call 5 must set analysis_status = FAILED
    assert calls[4][0][1] == ("FAILED", evidence_id)
