"""
Unit tests for Invoice Auditor & Arithmetic Verification Engine (Phase 6 Stage 1).
Validates document classification, entity parsing, deterministic line-item arithmetic,
sum-versus-total matching with tolerance, category-specific timeline auditing,
and advisory discrepancy synthesis.
"""

from datetime import date
from decimal import Decimal
import pytest

from app.services.invoice_auditor import (
    detect_document_type,
    parse_clean_decimal,
    parse_flexible_date,
    parse_invoice_fields,
    validate_invoice_arithmetic,
    validate_document_timeline,
    evaluate_overall_evidence_integrity,
)


def test_detect_document_type():
    assert detect_document_type("Discharge Summary for patient John Doe. Date of Admission: 2026-04-01. Date of Discharge: 2026-04-05.") == "DISCHARGE_SUMMARY"
    assert detect_document_type("Apex Super Speciality Hospital. Consultation fee and pharmacy bed charges. Patient Name: Jane.") == "MEDICAL_INVOICE"
    assert detect_document_type("AutoCare Garage & Workshop. Vehicle No: MH-02-AB-1234. Spare parts and labour charges.") == "VEHICLE_REPAIR_ESTIMATE"
    assert detect_document_type("Cash Payment Receipt. Received with thanks from Alex.") == "RECEIPT"
    assert detect_document_type("Tax Invoice. Bill of Supply. Invoice No: INV-998811.") == "GENERIC_INVOICE"
    assert detect_document_type("Some random unrelated document text here.") == "UNKNOWN"


def test_parse_clean_decimal():
    assert parse_clean_decimal("₹ 1,500.50") == Decimal("1500.50")
    assert parse_clean_decimal("Rs. 25,000.00") == Decimal("25000.00")
    assert parse_clean_decimal("INR 300") == Decimal("300.00")
    assert parse_clean_decimal("") is None
    assert parse_clean_decimal("N/A") is None


def test_parse_flexible_date():
    assert parse_flexible_date("2026-05-15") == date(2026, 5, 15)
    assert parse_flexible_date("15/05/2026") == date(2026, 5, 15)
    assert parse_flexible_date("15-05-2026") == date(2026, 5, 15)
    assert parse_flexible_date("15-May-2026") == date(2026, 5, 15)
    assert parse_flexible_date("15 May 2026") == date(2026, 5, 15)
    assert parse_flexible_date("invalid-date") is None


def test_parse_invoice_fields_medical():
    text = """
    Apollo Health City Hospital
    GSTIN: 36AABCA1234F1Z8
    Invoice No: MED-2026-881
    Invoice Date: 12/05/2026
    Date of Admission: 08/05/2026
    Date of Discharge: 12/05/2026

    1. Doctor Consultation  2 x 1500.00  3000.00
    2. Room Rent ICU        4 x 2500.00  10000.00
    3. Pharmacy Medicines   1 x 4500.00  4500.00

    Sub Total: ₹ 17,500.00
    GST Amount: ₹ 875.00
    Discount: ₹ 500.00
    Grand Total: ₹ 17,875.00
    """
    fields = parse_invoice_fields(text)
    assert fields["provider_name"] == "Apollo Health City Hospital"
    assert fields["tax_id"] == "36AABCA1234F1Z8"
    assert fields["invoice_number"] == "MED-2026-881"
    assert fields["invoice_date"] == date(2026, 5, 12)
    assert fields["admission_date"] == date(2026, 5, 8)
    assert fields["discharge_date"] == date(2026, 5, 12)
    assert fields["subtotal"] == Decimal("17500.00")
    assert fields["tax_amount"] == Decimal("875.00")
    assert fields["discount_amount"] == Decimal("500.00")
    assert fields["total_amount"] == Decimal("17875.00")
    assert len(fields["line_items"]) == 3
    assert fields["line_items"][0]["description"] == "Doctor Consultation"
    assert fields["line_items"][0]["quantity"] == Decimal("2.00")
    assert fields["line_items"][0]["unit_rate"] == Decimal("1500.00")
    assert fields["line_items"][0]["total"] == Decimal("3000.00")
    assert fields["line_items"][0]["math_valid"] is True


def test_validate_invoice_arithmetic_exact_match():
    extracted = {
        "total_amount": Decimal("17875.00"),
        "subtotal": Decimal("17500.00"),
        "tax_amount": Decimal("875.00"),
        "discount_amount": Decimal("500.00"),
        "line_items": [
            {"description": "A", "quantity": Decimal("2"), "unit_rate": Decimal("1500.00"), "total": Decimal("3000.00"), "math_valid": True},
            {"description": "B", "quantity": Decimal("4"), "unit_rate": Decimal("2500.00"), "total": Decimal("10000.00"), "math_valid": True},
            {"description": "C", "quantity": Decimal("1"), "unit_rate": Decimal("4500.00"), "total": Decimal("4500.00"), "math_valid": True},
        ]
    }
    # 3000 + 10000 + 4500 = 17500. With tax (875) - discount (500) = 17875.00
    res = validate_invoice_arithmetic(extracted, claim_requested_amount=Decimal("17875.00"))
    assert res["line_item_math_valid"] is True
    assert res["sum_matches_total"] is True
    assert res["calculated_line_items_sum"] == Decimal("17500.00")
    assert res["amount_matches_claim"] is True
    assert res["invoice_vs_claim_amount_discrepancy"] == Decimal("0.00")


def test_validate_invoice_arithmetic_tolerance():
    extracted = {
        "total_amount": Decimal("1000.00"),
        "tax_amount": Decimal("0.00"),
        "discount_amount": Decimal("0.00"),
        "line_items": [
            {"description": "Item 1", "quantity": Decimal("1"), "unit_rate": Decimal("999.50"), "total": Decimal("999.50"), "math_valid": True},
        ]
    }
    # 999.50 is within 1.00 tolerance of 1000.00
    res = validate_invoice_arithmetic(extracted, claim_requested_amount=Decimal("1000.00"))
    assert res["sum_matches_total"] is True
    assert res["amount_matches_claim"] is True


def test_validate_invoice_arithmetic_discrepancy():
    extracted = {
        "total_amount": Decimal("5000.00"),
        "tax_amount": Decimal("0.00"),
        "discount_amount": Decimal("0.00"),
        "line_items": [
            # Line item math invalid: 2 * 1000 != 3000
            {"description": "Bad Math Item", "quantity": Decimal("2"), "unit_rate": Decimal("1000.00"), "total": Decimal("3000.00"), "math_valid": False},
        ]
    }
    res = validate_invoice_arithmetic(extracted, claim_requested_amount=Decimal("4000.00"))
    assert res["line_item_math_valid"] is False
    assert res["sum_matches_total"] is False
    assert res["amount_matches_claim"] is False
    assert res["invoice_vs_claim_amount_discrepancy"] == Decimal("1000.00")


def test_validate_invoice_arithmetic_incomplete_data():
    # If no line items or no total, it returns None, NOT false mismatches
    extracted = {
        "total_amount": None,
        "line_items": [],
    }
    res = validate_invoice_arithmetic(extracted, claim_requested_amount=Decimal("5000.00"))
    assert res["line_item_math_valid"] is None
    assert res["sum_matches_total"] is None
    assert res["calculated_line_items_sum"] is None
    assert res["amount_matches_claim"] is None


def test_validate_document_timeline_medical_valid():
    extracted_dates = {
        "invoice_date": date(2026, 5, 10),
        "admission_date": date(2026, 5, 2),
        "discharge_date": date(2026, 5, 8),
    }
    claim_dates = {
        "incident_date": date(2026, 5, 1),
        "submission_date": date(2026, 5, 12),
    }
    valid, findings = validate_document_timeline(extracted_dates, claim_dates, "MEDICAL_INVOICE")
    assert valid is True
    assert len(findings) == 0


def test_validate_document_timeline_medical_inverted():
    extracted_dates = {
        "invoice_date": date(2026, 5, 1),
        "admission_date": date(2026, 5, 10),
        "discharge_date": date(2026, 5, 5),  # Discharge predates admission!
    }
    claim_dates = {
        "incident_date": date(2026, 5, 12),  # Admission predates incident!
        "submission_date": date(2026, 5, 20),
    }
    valid, findings = validate_document_timeline(extracted_dates, claim_dates, "MEDICAL_INVOICE")
    assert valid is False
    assert len(findings) >= 2
    assert any("predates admission date" in f for f in findings)


def test_validate_document_timeline_vehicle_checks():
    extracted_dates = {
        "inspection_date": date(2026, 6, 2),
        "repair_date": date(2026, 6, 5),
        "invoice_date": date(2026, 6, 6),
    }
    claim_dates = {
        "incident_date": date(2026, 6, 1),
        "submission_date": date(2026, 6, 7),
    }
    valid, findings = validate_document_timeline(extracted_dates, claim_dates, "VEHICLE_REPAIR_ESTIMATE")
    assert valid is True

    # Invert inspection vs repair
    extracted_dates["repair_date"] = date(2026, 6, 1)  # Repair predates inspection
    valid2, findings2 = validate_document_timeline(extracted_dates, claim_dates, "VEHICLE_REPAIR_ESTIMATE")
    assert valid2 is False
    assert any("predates inspection date" in f for f in findings2)


def test_validate_document_timeline_missing_dates():
    # Only invoice date present - no other dates to compare
    extracted_dates = {"invoice_date": date(2026, 5, 10)}
    claim_dates = {}
    valid, findings = validate_document_timeline(extracted_dates, claim_dates, "GENERIC_INVOICE")
    assert valid is None
    assert len(findings) == 0


def test_evaluate_overall_evidence_integrity():
    # 1. Consistent
    status, rec, flags = evaluate_overall_evidence_integrity(
        document_type="MEDICAL_INVOICE",
        extraction_method="PDF_TEXT",
        confidence_score=0.95,
        arithmetic_results={"line_item_math_valid": True, "sum_matches_total": True, "amount_matches_claim": True},
        timeline_valid=True,
        timeline_findings=[],
        has_extracted_text=True,
    )
    assert status == "CONSISTENT"
    assert rec == "NO_ACTION_REQUIRED"
    assert flags == []

    # 2. Discrepancies detected
    status, rec, flags = evaluate_overall_evidence_integrity(
        document_type="MEDICAL_INVOICE",
        extraction_method="PDF_TEXT",
        confidence_score=0.95,
        arithmetic_results={"line_item_math_valid": False, "sum_matches_total": False, "calculated_line_items_sum": Decimal("100"), "rounding_or_tax_discrepancy": Decimal("50"), "amount_matches_claim": True},
        timeline_valid=True,
        timeline_findings=[],
        has_extracted_text=True,
    )
    assert status == "DISCREPANCIES_DETECTED"
    assert rec == "ADVISORY_REVIEW_RECOMMENDED"
    assert len(flags) >= 1

    # 3. Manual Fallback / No text
    status, rec, flags = evaluate_overall_evidence_integrity(
        document_type="UNKNOWN",
        extraction_method="MANUAL_FALLBACK",
        confidence_score=0.0,
        arithmetic_results={},
        timeline_valid=None,
        timeline_findings=[],
        has_extracted_text=False,
    )
    assert status == "NEEDS_MANUAL_REVIEW"
    assert rec == "EXTRACTION_UNAVAILABLE"

