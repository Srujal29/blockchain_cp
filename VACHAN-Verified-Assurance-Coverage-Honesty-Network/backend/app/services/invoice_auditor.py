"""
Invoice Auditor & Arithmetic Verification Engine for InsureChain VoiceGuard (Phase 6).
Performs deterministic field extraction, line-item arithmetic verification,
sum-versus-total matching, timeline consistency auditing, and discrepancy synthesis.
All integrity checks are advisory and non-destructive.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging import get_logger

logger = get_logger(__name__)

# Configurable tolerance for arithmetic checks (handles minor ₹1 rounding differences)
INVOICE_ARITHMETIC_TOLERANCE = Decimal("1.00")
LINE_ITEM_MATH_TOLERANCE = Decimal("0.05")

# GSTIN Regex (15 characters: 2 state code, 10 PAN, 1 entity code, 1 Z, 1 checksum)
GSTIN_REGEX = re.compile(r"\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1})\b")
# PAN Regex (10 characters: 5 letters, 4 digits, 1 letter)
PAN_REGEX = re.compile(r"\b([A-Z]{5}[0-9]{4}[A-Z]{1})\b")


def parse_clean_decimal(val_str: Optional[str]) -> Optional[Decimal]:
    """Cleans currency symbols, commas, spaces and converts to Decimal."""
    if not val_str:
        return None
    # Strip currency labels and symbols (including abbreviations like Rs.)
    s = re.sub(r"(?i)\b(?:rs|inr|usd|eur|gbp)\.?\b", "", val_str.replace("₹", "")).strip()
    s = s.replace(",", "")
    m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return Decimal(m.group(0)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def parse_flexible_date(date_str: Optional[str]) -> Optional[date]:
    """Parses various date formats commonly seen on Indian and international medical/repair invoices."""
    if not date_str:
        return None
    s = date_str.strip()
    patterns = [
        ("%Y-%m-%d", r"^\d{4}-\d{2}-\d{2}$"),
        ("%d/%m/%Y", r"^\d{1,2}/\d{1,2}/\d{4}$"),
        ("%d-%m-%Y", r"^\d{1,2}-\d{1,2}-\d{4}$"),
        ("%d.%m.%Y", r"^\d{1,2}\.\d{1,2}\.\d{4}$"),
        ("%d-%b-%Y", r"^\d{1,2}-[A-Za-z]{3}-\d{4}$"),
        ("%d %b %Y", r"^\d{1,2}\s+[A-Za-z]{3}\s+\d{4}$"),
        ("%d %B %Y", r"^\d{1,2}\s+[A-Za-z]+\s+\d{4}$"),
    ]
    for fmt, pat in patterns:
        if re.match(pat, s, re.IGNORECASE):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                pass
    return None


def detect_document_type(text: str) -> str:
    """
    Classifies document type based on deterministic keywords in the extracted text.
    Returns one of:
      DISCHARGE_SUMMARY, MEDICAL_INVOICE, VEHICLE_REPAIR_ESTIMATE, RECEIPT, GENERIC_INVOICE, UNKNOWN
    """
    if not text:
        return "UNKNOWN"

    lower = text.lower()

    # Discharge summary has specific inpatient markers
    if (
        "discharge summary" in lower
        or "date of admission" in lower and "date of discharge" in lower
        or "ipd no" in lower
        or "inpatient summary" in lower
    ):
        return "DISCHARGE_SUMMARY"

    # Medical bill / pharmacy
    medical_markers = [
        "hospital", "clinic", "healthcare", "medical center", "pharmacy",
        "patient name", "consultation fee", "doctor name", "rx", "bed charges",
        "nursing charges", "ot charges", "lab charges", "medicines"
    ]
    if sum(1 for m in medical_markers if m in lower) >= 2:
        return "MEDICAL_INVOICE"

    # Vehicle repair estimate / garage
    vehicle_markers = [
        "repair estimate", "bodyshop", "workshop", "garage", "vehicle no",
        "chassis no", "engine no", "spare parts", "labour charges", "dent repair",
        "paint charges", "survey date", "inspection date", "odometer"
    ]
    if sum(1 for v in vehicle_markers if v in lower) >= 2:
        return "VEHICLE_REPAIR_ESTIMATE"

    # Receipt
    receipt_markers = ["payment receipt", "cash receipt", "money receipt", "received with thanks"]
    if any(r in lower for r in receipt_markers):
        return "RECEIPT"

    # Generic invoice
    invoice_markers = ["tax invoice", "bill of supply", "invoice no", "commercial invoice"]
    if any(i in lower for i in invoice_markers):
        return "GENERIC_INVOICE"

    return "UNKNOWN"


def parse_invoice_fields(text: str, document_type: Optional[str] = None) -> Dict[str, Any]:
    """
    Deterministic extraction of key entities, dates, monetary totals and line items.
    Does NOT invent values. Missing fields remain None.
    """
    if not text:
        return {
            "provider_name": None,
            "tax_id": None,
            "invoice_number": None,
            "invoice_date": None,
            "admission_date": None,
            "discharge_date": None,
            "inspection_date": None,
            "repair_date": None,
            "subtotal": None,
            "tax_amount": None,
            "discount_amount": None,
            "total_amount": None,
            "line_items": [],
        }

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # 1. Provider Name: Check top 5 lines for likely organization name, skipping common headers
    provider_name = None
    for line in lines[:5]:
        skip_header = any(
            h in line.lower()
            for h in ["tax invoice", "bill of supply", "receipt", "estimate", "cash memo", "date:", "invoice no"]
        )
        if not skip_header and len(line) >= 4 and len(line) <= 80:
            provider_name = line
            break

    # 2. Tax ID (GSTIN or PAN)
    tax_id = None
    gstin_match = GSTIN_REGEX.search(text)
    if gstin_match:
        tax_id = gstin_match.group(1)
    else:
        pan_match = PAN_REGEX.search(text)
        if pan_match:
            tax_id = pan_match.group(1)

    # 3. Invoice Number
    invoice_number = None
    inv_num_patterns = [
        r"(?:Invoice|Bill|Estimate|Receipt|Memo|IPD)\s*(?:No|Number|#)[\s.:#]*([A-Za-z0-9\-\/]+)",
        r"(?:Inv|Est)\s*#[\s.:]*([A-Za-z0-9\-\/]+)",
    ]
    for pat in inv_num_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if len(val) >= 2 and not val.lower().startswith("date"):
                invoice_number = val
                break

    # 4. Dates
    def extract_date_after(keywords: List[str]) -> Optional[date]:
        for kw in keywords:
            # Look for keyword followed by date within the line or next tokens
            pat = rf"{kw}[\s.:\-]*([0-9]{{1,4}}[\/\-\.][0-9]{{1,2}}[\/\-\.][0-9]{{2,4}}|[0-9]{{1,2}}\s+[A-Za-z]{{3,9}}\s+[0-9]{{4}})"
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                d = parse_flexible_date(m.group(1))
                if d:
                    return d
        return None

    invoice_date = extract_date_after(["Invoice Date", "Bill Date", "Date of Bill", "Dated", "Date"])
    admission_date = extract_date_after(["Admission Date", "Date of Admission", "DOA", "Admitted On"])
    discharge_date = extract_date_after(["Discharge Date", "Date of Discharge", "DOD", "Discharged On"])
    inspection_date = extract_date_after(["Inspection Date", "Survey Date", "Inspected On", "Date of Inspection"])
    repair_date = extract_date_after(["Repair Date", "Completion Date", "Repaired On", "Date of Repair"])

    # 5. Monetary Figures (Subtotal, Tax, Discount, Total)
    def extract_amount_after(keywords: List[str]) -> Optional[Decimal]:
        for kw in keywords:
            pat = rf"{kw}[\s.:\-]*([₹Rs\.\s]*[0-9]+(?:,[0-9]{{3}})*(?:\.[0-9]{{1,2}})?)"
            matches = re.finditer(pat, text, re.IGNORECASE)
            for m in matches:
                amt = parse_clean_decimal(m.group(1))
                if amt is not None and amt > 0:
                    return amt
        return None

    subtotal = extract_amount_after(["Sub Total", "Sub-Total", "Subtotal", "Gross Amount", "Basic Amount"])
    tax_amount = extract_amount_after(["Total Tax", "GST Amount", "CGST", "SGST", "IGST", "Tax", "VAT"])
    discount_amount = extract_amount_after(["Total Discount", "Discount", "Rebate", "Less: Discount"])
    total_amount = extract_amount_after([
        "Total Amount", "Grand Total", "Net Payable", "Final Amount",
        "Invoice Total", "Total Payable", "Bill Total", "Total"
    ])

    # 6. Structured Line Items
    line_items: List[Dict[str, Any]] = []
    # Pattern for line items: Item Description ... Qty x Rate ... Total
    # or: Description ... Amount
    line_item_pattern_qty_rate = re.compile(
        r"^(?:\d+[\.\)]\s*)?([A-Za-z0-9\s\-_/().,]+?)\s*[:]?\s+(\d+(?:\.\d+)?)\s*(?:x|@|\*)\s*([0-9,]+(?:\.[0-9]{1,2})?)\s*(?:=)?\s*(?:INR|Rs\.?|₹)?\s*([0-9,]+(?:\.[0-9]{1,2})?)$"
    )
    line_item_pattern_simple = re.compile(
        r"^(?:\d+[\.\)]\s*)?([A-Za-z0-9\s\-_/().,]{3,40})\s+(?:INR|Rs\.?|₹)?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2}))$"
    )

    for line in lines:
        m_qr = line_item_pattern_qty_rate.match(line)
        if m_qr:
            desc = m_qr.group(1).strip()
            qty = parse_clean_decimal(m_qr.group(2))
            rate = parse_clean_decimal(m_qr.group(3))
            tot = parse_clean_decimal(m_qr.group(4))
            if tot is not None and desc.lower() not in ["sub total", "total", "grand total", "tax"]:
                math_valid = None
                if qty is not None and rate is not None:
                    math_valid = abs((qty * rate) - tot) <= LINE_ITEM_MATH_TOLERANCE
                line_items.append({
                    "description": desc,
                    "quantity": qty,
                    "unit_rate": rate,
                    "total": tot,
                    "math_valid": math_valid,
                })
            continue

        m_simp = line_item_pattern_simple.match(line)
        if m_simp:
            desc = m_simp.group(1).strip()
            tot = parse_clean_decimal(m_simp.group(2))
            # Filter out headers or total rows
            if (
                tot is not None
                and tot > 0
                and desc.lower() not in [
                    "sub total", "sub-total", "total", "grand total", "net payable",
                    "total tax", "cgst", "sgst", "igst", "discount", "advance paid"
                ]
            ):
                line_items.append({
                    "description": desc,
                    "quantity": None,
                    "unit_rate": None,
                    "total": tot,
                    "math_valid": None,
                })

    return {
        "provider_name": provider_name,
        "tax_id": tax_id,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "admission_date": admission_date,
        "discharge_date": discharge_date,
        "inspection_date": inspection_date,
        "repair_date": repair_date,
        "subtotal": subtotal,
        "tax_amount": tax_amount,
        "discount_amount": discount_amount,
        "total_amount": total_amount,
        "line_items": line_items,
    }


def validate_invoice_arithmetic(
    extracted: Dict[str, Any],
    claim_requested_amount: Optional[Decimal] = None,
    tolerance: Decimal = INVOICE_ARITHMETIC_TOLERANCE,
) -> Dict[str, Any]:
    """
    Performs deterministic arithmetic verification on extracted values:
    1. Line item math: checks qty * rate == total for items where both exist.
    2. Sum vs Total: compares sum of line items against extracted invoice total.
       Takes taxes and discounts into account if available.
    3. Claim amount match: compares invoice total against claim's requested amount.
    Missing fields produce inconclusive results (None), NEVER false mismatches.
    """
    line_items = extracted.get("line_items") or []
    extracted_total = extracted.get("total_amount")
    extracted_subtotal = extracted.get("subtotal")
    tax_amount = extracted.get("tax_amount") or Decimal("0.00")
    discount_amount = extracted.get("discount_amount") or Decimal("0.00")

    # 1. Line Item Math
    items_with_math = [it for it in line_items if it.get("math_valid") is not None]
    if items_with_math:
        line_item_math_valid = all(it["math_valid"] for it in items_with_math)
    else:
        line_item_math_valid = None

    # 2. Sum vs Total
    calculated_sum: Optional[Decimal] = None
    sum_matches_total: Optional[bool] = None
    rounding_or_tax_discrepancy: Optional[Decimal] = None

    if line_items:
        calculated_sum = sum((it["total"] for it in line_items), Decimal("0.00"))

        if extracted_total is not None:
            # Expected total = calculated_sum + tax - discount (if subtotal was parsed)
            diff_direct = abs(calculated_sum - extracted_total)
            diff_with_taxes = abs((calculated_sum + tax_amount - discount_amount) - extracted_total)

            if diff_direct <= tolerance:
                sum_matches_total = True
                rounding_or_tax_discrepancy = calculated_sum - extracted_total
            elif diff_with_taxes <= tolerance:
                sum_matches_total = True
                rounding_or_tax_discrepancy = (calculated_sum + tax_amount - discount_amount) - extracted_total
            else:
                sum_matches_total = False
                rounding_or_tax_discrepancy = calculated_sum - extracted_total

    # 3. Invoice Total vs Claim Requested Amount
    amount_matches_claim: Optional[bool] = None
    invoice_vs_claim_discrepancy: Optional[Decimal] = None

    if extracted_total is not None and claim_requested_amount is not None:
        discrepancy = extracted_total - claim_requested_amount
        invoice_vs_claim_discrepancy = discrepancy
        amount_matches_claim = abs(discrepancy) <= tolerance

    return {
        "line_item_math_valid": line_item_math_valid,
        "sum_matches_total": sum_matches_total,
        "calculated_line_items_sum": calculated_sum,
        "rounding_or_tax_discrepancy": rounding_or_tax_discrepancy,
        "amount_matches_claim": amount_matches_claim,
        "invoice_vs_claim_amount_discrepancy": invoice_vs_claim_discrepancy,
    }


def validate_document_timeline(
    extracted_dates: Dict[str, Optional[date]],
    claim_dates: Dict[str, Optional[date]],
    document_type: str,
) -> Tuple[Optional[bool], List[str]]:
    """
    Performs category-specific chronological ordering checks.
    Missing dates are skipped and NEVER treated as errors.
    Advisory flags highlight inverted chronology.
    """
    findings: List[str] = []
    comparisons_made = 0

    incident_date = claim_dates.get("incident_date")
    submission_date = claim_dates.get("submission_date")

    invoice_date = extracted_dates.get("invoice_date")
    admission_date = extracted_dates.get("admission_date")
    discharge_date = extracted_dates.get("discharge_date")
    inspection_date = extracted_dates.get("inspection_date")
    repair_date = extracted_dates.get("repair_date")

    # Document-type specific checks
    if document_type in ("MEDICAL_INVOICE", "DISCHARGE_SUMMARY"):
        # Incident <= Admission
        if incident_date and admission_date:
            comparisons_made += 1
            if admission_date < incident_date:
                findings.append(f"Hospital admission date ({admission_date}) predates reported incident date ({incident_date}).")

        # Admission <= Discharge
        if admission_date and discharge_date:
            comparisons_made += 1
            if discharge_date < admission_date:
                findings.append(f"Hospital discharge date ({discharge_date}) predates admission date ({admission_date}).")

        # Discharge <= Invoice
        if discharge_date and invoice_date:
            comparisons_made += 1
            if invoice_date < discharge_date:
                findings.append(f"Medical invoice date ({invoice_date}) predates hospital discharge date ({discharge_date}).")

    elif document_type == "VEHICLE_REPAIR_ESTIMATE":
        # Incident <= Inspection
        if incident_date and inspection_date:
            comparisons_made += 1
            if inspection_date < incident_date:
                findings.append(f"Vehicle inspection date ({inspection_date}) predates reported incident date ({incident_date}).")

        # Inspection <= Repair
        if inspection_date and repair_date:
            comparisons_made += 1
            if repair_date < inspection_date:
                findings.append(f"Vehicle repair date ({repair_date}) predates inspection date ({inspection_date}).")

        # Repair <= Invoice
        if repair_date and invoice_date:
            comparisons_made += 1
            if invoice_date < repair_date:
                findings.append(f"Repair estimate/invoice date ({invoice_date}) predates repair completion date ({repair_date}).")

    # General date consistency checks:
    # Incident <= Invoice
    if incident_date and invoice_date:
        comparisons_made += 1
        if invoice_date < incident_date:
            findings.append(f"Invoice date ({invoice_date}) predates reported incident date ({incident_date}).")

    # Invoice <= Submission
    if invoice_date and submission_date:
        comparisons_made += 1
        if submission_date < invoice_date:
            findings.append(f"Claim submission date ({submission_date}) predates invoice date ({invoice_date}).")

    if findings:
        return False, findings
    elif comparisons_made > 0:
        return True, []
    else:
        # Not enough dates to make any chronological comparison
        return None, []


def evaluate_overall_evidence_integrity(
    document_type: str,
    extraction_method: str,
    confidence_score: float,
    arithmetic_results: Dict[str, Any],
    timeline_valid: Optional[bool],
    timeline_findings: List[str],
    has_extracted_text: bool,
) -> Tuple[str, str, List[str]]:
    """
    Synthesizes overall analysis status and review recommendation.
    Statuses: CONSISTENT, DISCREPANCIES_DETECTED, NEEDS_MANUAL_REVIEW, FAILED
    Recommendations: NO_ACTION_REQUIRED, ADVISORY_REVIEW_RECOMMENDED, MANUAL_INSPECTION_REQUIRED, EXTRACTION_UNAVAILABLE
    """
    discrepancy_flags: List[str] = []

    # Collect arithmetic discrepancy flags
    if arithmetic_results.get("line_item_math_valid") is False:
        discrepancy_flags.append("One or more line items have quantity * rate math that does not match line item total.")

    if arithmetic_results.get("sum_matches_total") is False:
        discrepancy_flags.append(
            f"Calculated line items sum ({arithmetic_results.get('calculated_line_items_sum')}) does not match invoice total "
            f"(discrepancy: {arithmetic_results.get('rounding_or_tax_discrepancy')})."
        )

    if arithmetic_results.get("amount_matches_claim") is False:
        discrepancy_flags.append(
            f"Extracted invoice total does not match requested claim amount "
            f"(discrepancy: {arithmetic_results.get('invoice_vs_claim_amount_discrepancy')})."
        )

    # Append timeline flags
    discrepancy_flags.extend(timeline_findings)

    # Decision Matrix
    if not has_extracted_text or extraction_method == "MANUAL_FALLBACK":
        return "NEEDS_MANUAL_REVIEW", "EXTRACTION_UNAVAILABLE" if not has_extracted_text else "MANUAL_INSPECTION_REQUIRED", discrepancy_flags

    if discrepancy_flags:
        return "DISCREPANCIES_DETECTED", "ADVISORY_REVIEW_RECOMMENDED", discrepancy_flags

    if confidence_score < 0.50:
        return "NEEDS_MANUAL_REVIEW", "MANUAL_INSPECTION_REQUIRED", ["Low OCR confidence score; manual inspection recommended."]

    return "CONSISTENT", "NO_ACTION_REQUIRED", []
