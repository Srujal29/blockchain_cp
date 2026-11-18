"""
Unit and Integration Tests for Phase 6 Stage 2:
Multimodal Evidence Analysis API, Automated Upload Trigger, Versioning, and Strict RBAC.
"""

from datetime import date, datetime
from decimal import Decimal
import io
import pytest
from unittest.mock import AsyncMock, patch

from app.core.exceptions import AuthorizationException, NotFoundException
from app.core.security import UserRole
from app.schemas.evidence_analysis import (
    DocumentType,
    ExtractionMethod,
    OverallAnalysisStatus,
    ReviewRecommendation,
)
from app.services.evidence_analysis_service import evidence_analysis_service
from app.services.evidence_service import evidence_service


SAMPLE_HOSPITAL_BILL_TEXT = """
APOLLO MULTISPECIALITY HOSPITALS
GSTIN: 27AABCA1234F1Z5
PAN: AABCA1234F
Invoice No: INV-2026-9921
Invoice Date: 12/04/2026
Admission Date: 10/04/2026
Discharge Date: 12/04/2026

Patient Name: Rajesh Sharma
Room Charges: 2 x 5000.00 = 10000.00
ICU Charges: 1 x 15000.00 = 15000.00
Consultation: 2 x 2500.00 = 5000.00

Sub Total: 30000.00
Total Tax: 2500.00
Total Discount: 1000.00
Total Amount: 31500.00
"""

SAMPLE_MISMATCH_BILL_TEXT = """
CITY REPAIR GARAGE
GSTIN: 29ABCDE1234F1Z5
Invoice No: GAR-8822
Invoice Date: 01/03/2026
Inspection Date: 05/03/2026
Repair Date: 02/03/2026

Bumper Replacement: 1 x 8000.00 = 8000.00
Paint Charges: 1 x 4000.00 = 4000.00

Sub Total: 12000.00
Total Tax: 1000.00
Total Amount: 25000.00
"""


@pytest.mark.asyncio
async def test_evidence_analysis_service_with_content():
    """Verifies that evidence_analysis_service analyzes raw text content directly and outputs structured report."""
    mock_conn = AsyncMock()
    mock_claim = {
        "id": "claim-uuid-1",
        "requested_amount": "31500.00",
        "incident_date": "2026-04-10",
        "submission_timestamp": "2026-04-15T10:00:00",
    }
    mock_evidence = {
        "id": "evidence-uuid-1",
        "claim_id": "claim-uuid-1",
        "evidence_type": "HOSPITAL_BILL",
        "mime_type": "application/pdf",
        "original_filename": "apollo_bill.pdf",
        "document_storage_ref": "claims/test/apollo_bill",
    }

    with patch("app.services.evidence_analysis_service.claim_evidence_repo.get_evidence_by_id", return_value=mock_evidence), \
         patch("app.services.evidence_analysis_service.claim_repo.get_claim_by_id", return_value=mock_claim), \
         patch("app.services.evidence_analysis_service.extract_document_text", return_value=(SAMPLE_HOSPITAL_BILL_TEXT, "PDF_TEXT", 0.95)), \
         patch("app.services.evidence_analysis_service.evidence_analysis_repo.create_analysis_report") as mock_create_report, \
         patch("app.services.evidence_analysis_service.audit_repo.log_audit_event", return_value={"id": "audit-1"}):

        mock_create_report.return_value = {
            "id": "report-uuid-1",
            "evidence_id": "evidence-uuid-1",
            "claim_id": "claim-uuid-1",
            "analysis_version": 1,
            "is_latest": True,
            "overall_status": "CONSISTENT",
            "review_recommendation": "NO_ACTION_REQUIRED",
        }

        report = await evidence_analysis_service.analyze_evidence_document(
            conn=mock_conn,
            claim_id="claim-uuid-1",
            evidence_id="evidence-uuid-1",
            content=b"dummy-pdf-bytes",
            actor_id="user-123",
            actor_role="CUSTOMER",
        )

        assert report["overall_status"] == "CONSISTENT"
        mock_create_report.assert_called_once()
        call_kwargs = mock_create_report.call_args.kwargs
        assert call_kwargs["document_type"] == "MEDICAL_INVOICE"
        assert call_kwargs["extracted_invoice_number"] == "INV-2026-9921"
        assert call_kwargs["extracted_total_amount"] == Decimal("31500.00")
        assert call_kwargs["sum_matches_total"] is True
        assert call_kwargs["amount_matches_claim"] is True


@pytest.mark.asyncio
async def test_evidence_analysis_discrepancy_detection():
    """Verifies that mismatch in math, total vs claim, and inverted timeline generates DISCREPANCIES_DETECTED."""
    mock_conn = AsyncMock()
    mock_claim = {
        "id": "claim-uuid-2",
        "requested_amount": "12000.00",
        "incident_date": "2026-03-04",
        "submission_timestamp": "2026-03-10T10:00:00",
    }
    mock_evidence = {
        "id": "evidence-uuid-2",
        "claim_id": "claim-uuid-2",
        "evidence_type": "REPAIR_ESTIMATE",
        "mime_type": "application/pdf",
        "original_filename": "repair.pdf",
        "document_storage_ref": "claims/test/repair",
    }

    with patch("app.services.evidence_analysis_service.claim_evidence_repo.get_evidence_by_id", return_value=mock_evidence), \
         patch("app.services.evidence_analysis_service.claim_repo.get_claim_by_id", return_value=mock_claim), \
         patch("app.services.evidence_analysis_service.extract_document_text", return_value=(SAMPLE_MISMATCH_BILL_TEXT, "PDF_TEXT", 0.90)), \
         patch("app.services.evidence_analysis_service.evidence_analysis_repo.create_analysis_report") as mock_create_report, \
         patch("app.services.evidence_analysis_service.audit_repo.log_audit_event", return_value={"id": "audit-2"}):

        mock_create_report.return_value = {
            "id": "report-uuid-2",
            "evidence_id": "evidence-uuid-2",
            "claim_id": "claim-uuid-2",
            "analysis_version": 1,
            "is_latest": True,
            "overall_status": "DISCREPANCIES_DETECTED",
            "review_recommendation": "ADVISORY_REVIEW_RECOMMENDED",
        }

        report = await evidence_analysis_service.analyze_evidence_document(
            conn=mock_conn,
            claim_id="claim-uuid-2",
            evidence_id="evidence-uuid-2",
            content=b"dummy-pdf-bytes",
        )

        assert report["overall_status"] == "DISCREPANCIES_DETECTED"
        call_kwargs = mock_create_report.call_args.kwargs
        assert call_kwargs["overall_status"] == "DISCREPANCIES_DETECTED"
        assert call_kwargs["review_recommendation"] == "ADVISORY_REVIEW_RECOMMENDED"
        assert call_kwargs["sum_matches_total"] is False
        assert call_kwargs["amount_matches_claim"] is False
        assert len(call_kwargs["discrepancy_flags"]) >= 2


@pytest.mark.asyncio
async def test_evidence_analysis_download_fallback():
    """Verifies that if downloading asset fails, status is NEEDS_MANUAL_REVIEW and extraction is MANUAL_FALLBACK."""
    mock_conn = AsyncMock()
    mock_claim = {
        "id": "claim-uuid-3",
        "requested_amount": "5000.00",
        "incident_date": "2026-01-01",
    }
    mock_evidence = {
        "id": "evidence-uuid-3",
        "claim_id": "claim-uuid-3",
        "evidence_type": "RECEIPT",
        "mime_type": "image/jpeg",
        "original_filename": "receipt.jpg",
        "document_storage_ref": "claims/test/receipt",
    }

    with patch("app.services.evidence_analysis_service.claim_evidence_repo.get_evidence_by_id", return_value=mock_evidence), \
         patch("app.services.evidence_analysis_service.claim_repo.get_claim_by_id", return_value=mock_claim), \
         patch("app.services.evidence_analysis_service.evidence_service.download_private_file_bytes", side_effect=Exception("Network error")), \
         patch("app.services.evidence_analysis_service.evidence_analysis_repo.create_analysis_report") as mock_create_report, \
         patch("app.services.evidence_analysis_service.audit_repo.log_audit_event"):

        mock_create_report.return_value = {
            "id": "report-uuid-3",
            "evidence_id": "evidence-uuid-3",
            "claim_id": "claim-uuid-3",
            "analysis_version": 1,
            "overall_status": "NEEDS_MANUAL_REVIEW",
            "review_recommendation": "EXTRACTION_UNAVAILABLE",
        }

        report = await evidence_analysis_service.analyze_evidence_document(
            conn=mock_conn,
            claim_id="claim-uuid-3",
            evidence_id="evidence-uuid-3",
            content=None,
        )

        call_kwargs = mock_create_report.call_args.kwargs
        assert call_kwargs["extraction_method"] == "MANUAL_FALLBACK"
        assert call_kwargs["overall_status"] == "NEEDS_MANUAL_REVIEW"
        assert call_kwargs["review_recommendation"] == "EXTRACTION_UNAVAILABLE"


@pytest.mark.asyncio
async def test_evidence_analysis_rbac_restrictions():
    """Verifies RBAC rules on evidence analysis endpoints: agents forbidden, other customers forbidden."""
    from app.api.routes.claims import (
        analyze_claim_evidence,
        get_evidence_analysis,
        get_evidence_analysis_history,
        list_claim_evidence_analysis,
    )

    agent_user = {"id": "agent-1", "role": UserRole.INSURANCE_AGENT.value}
    customer_other = {"id": "cust-2", "role": UserRole.CUSTOMER.value}

    # 1. Agent should be strictly rejected with AuthorizationException
    with pytest.raises(AuthorizationException, match="Insurance agents cannot access claim evidence analysis"):
        await analyze_claim_evidence("claim-1", "ev-1", current_user=agent_user)

    with pytest.raises(AuthorizationException, match="Insurance agents cannot access claim evidence analysis"):
        await get_evidence_analysis("claim-1", "ev-1", current_user=agent_user)

    with pytest.raises(AuthorizationException, match="Insurance agents cannot access claim evidence analysis"):
        await get_evidence_analysis_history("claim-1", "ev-1", current_user=agent_user)

    with pytest.raises(AuthorizationException, match="Insurance agents cannot access claim evidence analysis"):
        await list_claim_evidence_analysis("claim-1", current_user=agent_user)


@pytest.mark.asyncio
async def test_customer_access_control():
    """Verifies that customers can access their own claim evidence analysis, but get NotFound on other claims."""
    from app.api.routes.claims import get_evidence_analysis

    owner_user = {"id": "cust-owner", "role": UserRole.CUSTOMER.value}
    other_user = {"id": "cust-intruder", "role": UserRole.CUSTOMER.value}
    authority_user = {"id": "auth-1", "role": UserRole.APPROVAL_AUTHORITY.value}

    mock_claim = {
        "id": "11111111-1111-1111-1111-111111111111",
        "customer_id": "cust-owner",
        "requested_amount": "5000.00",
    }
    mock_report = {
        "id": "22222222-2222-2222-2222-222222222222",
        "evidence_id": "33333333-3333-3333-3333-333333333333",
        "claim_id": "11111111-1111-1111-1111-111111111111",
        "analysis_version": 1,
        "is_latest": True,
        "document_type": "MEDICAL_INVOICE",
        "extraction_method": "PDF_TEXT",
        "parser_engine_version": "vachan-extractor-1.0",
        "confidence_score": 0.95,
        "overall_status": "CONSISTENT",
        "review_recommendation": "NO_ACTION_REQUIRED",
        "created_at": datetime.now(),
    }

    mock_conn = AsyncMock()

    with patch("app.api.routes.claims.get_db_connection") as mock_get_conn, \
         patch("app.db.repositories.claim_repo.get_claim_by_id", return_value=mock_claim), \
         patch("app.db.repositories.evidence_analysis_repo.get_latest_report_by_evidence_id", return_value=mock_report):

        mock_get_conn.return_value.__aenter__.return_value = mock_conn

        # 1. Owner customer can access
        res_owner = await get_evidence_analysis(
            claim_id="11111111-1111-1111-1111-111111111111",
            evidence_id="33333333-3333-3333-3333-333333333333",
            current_user=owner_user,
        )
        assert res_owner["id"] == "22222222-2222-2222-2222-222222222222"

        # 2. Authority can access
        res_auth = await get_evidence_analysis(
            claim_id="11111111-1111-1111-1111-111111111111",
            evidence_id="33333333-3333-3333-3333-333333333333",
            current_user=authority_user,
        )
        assert res_auth["id"] == "22222222-2222-2222-2222-222222222222"

        # 3. Intruder customer is rejected with NotFoundException (no existence leakage)
        with pytest.raises(NotFoundException):
            await get_evidence_analysis(
                claim_id="11111111-1111-1111-1111-111111111111",
                evidence_id="33333333-3333-3333-3333-333333333333",
                current_user=other_user,
            )


@pytest.mark.asyncio
async def test_list_claim_evidence_analysis_endpoint():
    """Verifies that list_claim_evidence_analysis returns all latest reports for a claim."""
    from app.api.routes.claims import list_claim_evidence_analysis

    authority_user = {"id": "auth-1", "role": UserRole.APPROVAL_AUTHORITY.value}
    mock_claim = {
        "id": "11111111-1111-1111-1111-111111111111",
        "customer_id": "cust-owner",
    }
    mock_reports = [
        {
            "id": "report-1",
            "evidence_id": "ev-1",
            "claim_id": "11111111-1111-1111-1111-111111111111",
            "analysis_version": 1,
            "is_latest": True,
            "document_type": "MEDICAL_INVOICE",
            "extraction_method": "PDF_TEXT",
            "parser_engine_version": "vachan-extractor-1.0",
            "confidence_score": 0.95,
            "overall_status": "CONSISTENT",
            "review_recommendation": "NO_ACTION_REQUIRED",
            "created_at": datetime.now(),
        },
        {
            "id": "report-2",
            "evidence_id": "ev-2",
            "claim_id": "11111111-1111-1111-1111-111111111111",
            "analysis_version": 2,
            "is_latest": True,
            "document_type": "DISCHARGE_SUMMARY",
            "extraction_method": "PDF_TEXT",
            "parser_engine_version": "vachan-extractor-1.0",
            "confidence_score": 0.90,
            "overall_status": "CONSISTENT",
            "review_recommendation": "NO_ACTION_REQUIRED",
            "created_at": datetime.now(),
        },
    ]

    mock_conn = AsyncMock()

    with patch("app.api.routes.claims.get_db_connection") as mock_get_conn, \
         patch("app.db.repositories.claim_repo.get_claim_by_id", return_value=mock_claim), \
         patch("app.db.repositories.evidence_analysis_repo.list_reports_by_claim_id", return_value=mock_reports):

        mock_get_conn.return_value.__aenter__.return_value = mock_conn

        res = await list_claim_evidence_analysis(
            claim_id="11111111-1111-1111-1111-111111111111",
            current_user=authority_user,
        )

        assert res["claim_id"] == "11111111-1111-1111-1111-111111111111"
        assert res["total_reports"] == 2
        assert len(res["reports"]) == 2
