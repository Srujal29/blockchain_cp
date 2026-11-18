"""
Unit tests for Evidence Analysis Repository (Phase 6 Stage 1).
Validates version incrementation, row-level FOR UPDATE concurrency locking,
is_latest flag management, JSON field serialization, and Neon-compatible status updates.
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import uuid
import pytest

from app.core.exceptions import NotFoundException
from app.db.repositories import evidence_analysis_repo


def make_mock_row(rep_id, ev_id, cl_id, version=1, is_latest=True, overall_status="CONSISTENT"):
    now = datetime.now()
    return (
        rep_id, ev_id, cl_id, version, is_latest, "MEDICAL_INVOICE",
        "PDF_TEXT", "vachan-extractor-1.0", 0.95,
        "City Hospital", "36AABCA1234F1Z8", "INV-101",
        None, None, None, None, None,
        Decimal("1000.00"), Decimal("50.00"), Decimal("0.00"), Decimal("1050.00"),
        '[{"description": "Consultation", "total": 1050.0}]',
        True, True, Decimal("1050.00"),
        Decimal("0.00"), True, Decimal("0.00"),
        True, '[]', '[]',
        overall_status, "NO_ACTION_REQUIRED", "Extracted raw text", now, now
    )


@pytest.mark.anyio
async def test_create_analysis_report_queries(anyio_backend):
    mock_cursor = AsyncMock()
    ev_id = uuid.uuid4()
    cl_id = uuid.uuid4()
    rep_id = uuid.uuid4()

    mock_row = make_mock_row(rep_id, ev_id, cl_id, version=1, is_latest=True)
    mock_cursor.fetchone.side_effect = [
        (ev_id,),   # 0. SELECT FOR UPDATE finds evidence
        (0,),       # 1. current max version
        mock_row,   # 2. inserted report row
    ]

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__aexit__ = AsyncMock(return_value=False)

    report = await evidence_analysis_repo.create_analysis_report(
        conn=mock_conn,
        evidence_id=str(ev_id),
        claim_id=str(cl_id),
        document_type="MEDICAL_INVOICE",
        extraction_method="PDF_TEXT",
        confidence_score=0.95,
        extracted_provider_name="City Hospital",
        extracted_total_amount=Decimal("1050.00"),
        extracted_line_items=[{"description": "Consultation", "total": Decimal("1050.00")}],
        line_item_math_valid=True,
        sum_matches_total=True,
        calculated_line_items_sum=Decimal("1050.00"),
        overall_status="CONSISTENT",
        review_recommendation="NO_ACTION_REQUIRED",
    )

    assert report["evidence_id"] == str(ev_id)
    assert report["claim_id"] == str(cl_id)
    assert report["analysis_version"] == 1
    assert report["is_latest"] is True
    assert report["overall_status"] == "CONSISTENT"
    assert report["review_recommendation"] == "NO_ACTION_REQUIRED"
    # Call count is 5:
    # 0. SELECT FOR UPDATE on claim_evidence
    # 1. SELECT MAX(version)
    # 2. UPDATE previous is_latest = FALSE
    # 3. INSERT new report
    # 4. UPDATE claim_evidence analysis_status
    assert mock_cursor.execute.call_count == 5

    # Confirm the last execute updated claim_evidence with PROCESSED
    last_call = mock_cursor.execute.call_args_list[-1]
    assert "UPDATE claim_evidence SET analysis_status = %s WHERE id = %s" in last_call[0][0]
    assert last_call[0][1] == ("PROCESSED", str(ev_id))


@pytest.mark.anyio
async def test_create_analysis_report_second_version_updates_previous(anyio_backend):
    mock_cursor = AsyncMock()
    ev_id = uuid.uuid4()
    cl_id = uuid.uuid4()
    rep_id = uuid.uuid4()

    mock_row = make_mock_row(rep_id, ev_id, cl_id, version=2, is_latest=True)
    mock_cursor.fetchone.side_effect = [
        (ev_id,),   # 0. SELECT FOR UPDATE finds evidence
        (1,),       # 1. current max version is 1
        mock_row,   # 2. inserted version 2 report row
    ]

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__aexit__ = AsyncMock(return_value=False)

    report = await evidence_analysis_repo.create_analysis_report(
        conn=mock_conn,
        evidence_id=str(ev_id),
        claim_id=str(cl_id),
        document_type="MEDICAL_INVOICE",
        extraction_method="PDF_TEXT",
        confidence_score=0.95,
    )

    assert report["analysis_version"] == 2
    assert mock_cursor.execute.call_count == 5


@pytest.mark.anyio
async def test_create_analysis_report_missing_evidence_raises_not_found(anyio_backend):
    mock_cursor = AsyncMock()
    # 0. SELECT FOR UPDATE returns None (evidence not found)
    mock_cursor.fetchone.return_value = None

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__aexit__ = AsyncMock(return_value=False)

    with pytest.raises(NotFoundException) as exc_info:
        await evidence_analysis_repo.create_analysis_report(
            conn=mock_conn,
            evidence_id=str(uuid.uuid4()),
            claim_id=str(uuid.uuid4()),
            document_type="MEDICAL_INVOICE",
            extraction_method="PDF_TEXT",
            confidence_score=0.95,
        )

    assert "not found" in str(exc_info.value).lower()
    # Should stop at step 0 (only 1 execute call)
    assert mock_cursor.execute.call_count == 1


@pytest.mark.anyio
async def test_create_analysis_report_failed_status_updates_evidence_failed(anyio_backend):
    mock_cursor = AsyncMock()
    ev_id = uuid.uuid4()
    cl_id = uuid.uuid4()
    rep_id = uuid.uuid4()

    mock_row = make_mock_row(rep_id, ev_id, cl_id, version=1, is_latest=True, overall_status="FAILED")
    mock_cursor.fetchone.side_effect = [
        (ev_id,),   # 0. SELECT FOR UPDATE finds evidence
        (0,),       # 1. current max version
        mock_row,   # 2. inserted report row
    ]

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__aexit__ = AsyncMock(return_value=False)

    report = await evidence_analysis_repo.create_analysis_report(
        conn=mock_conn,
        evidence_id=str(ev_id),
        claim_id=str(cl_id),
        document_type="UNKNOWN",
        extraction_method="MANUAL_FALLBACK",
        confidence_score=0.0,
        overall_status="FAILED",
        review_recommendation="EXTRACTION_UNAVAILABLE",
    )

    assert report["overall_status"] == "FAILED"
    # Confirm last execute updated claim_evidence with FAILED
    last_call = mock_cursor.execute.call_args_list[-1]
    assert last_call[0][1] == ("FAILED", str(ev_id))


@pytest.mark.anyio
async def test_get_latest_report_by_evidence_id_found(anyio_backend):
    mock_cursor = AsyncMock()
    rep_id = uuid.uuid4()
    ev_id = uuid.uuid4()
    cl_id = uuid.uuid4()

    mock_cursor.fetchone.return_value = make_mock_row(rep_id, ev_id, cl_id)

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__aexit__ = AsyncMock(return_value=False)

    report = await evidence_analysis_repo.get_latest_report_by_evidence_id(mock_conn, str(ev_id))
    assert report is not None
    assert report["id"] == str(rep_id)
    assert report["evidence_id"] == str(ev_id)
    assert report["is_latest"] is True
    assert report["confidence_score"] == 0.95
    assert len(report["extracted_line_items"]) == 1


@pytest.mark.anyio
async def test_get_latest_report_by_evidence_id_not_found(anyio_backend):
    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = None

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__aexit__ = AsyncMock(return_value=False)

    report = await evidence_analysis_repo.get_latest_report_by_evidence_id(mock_conn, str(uuid.uuid4()))
    assert report is None
