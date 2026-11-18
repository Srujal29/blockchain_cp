"""
Repository for Phase 6 Evidence Analysis Reports.
Pure parameterized SQL queries interacting with Neon PostgreSQL.
"""

from decimal import Decimal
import json
from typing import Any, Dict, List, Optional
import psycopg

from app.core.exceptions import DatabaseException, NotFoundException

REPORT_FIELDS = """
    id, evidence_id, claim_id, analysis_version, is_latest, document_type,
    extraction_method, parser_engine_version, confidence_score,
    extracted_provider_name, extracted_tax_id, extracted_invoice_number,
    extracted_invoice_date, extracted_admission_date, extracted_discharge_date,
    extracted_inspection_date, extracted_repair_date,
    extracted_subtotal, extracted_tax_amount, extracted_discount_amount, extracted_total_amount,
    extracted_line_items,
    line_item_math_valid, sum_matches_total, calculated_line_items_sum,
    rounding_or_tax_discrepancy, amount_matches_claim, invoice_vs_claim_amount_discrepancy,
    timeline_valid, timeline_findings, discrepancy_flags,
    overall_status, review_recommendation, raw_extracted_text, created_at, updated_at
"""


def _json_default(obj: Any) -> Any:
    """Helper to serialize Decimal and dates for JSONB fields."""
    if isinstance(obj, Decimal):
        return float(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _row_to_report_dict(row: tuple) -> Dict[str, Any]:
    """Maps SQL tuple to an evidence analysis report dictionary."""
    return {
        "id": str(row[0]),
        "evidence_id": str(row[1]),
        "claim_id": str(row[2]),
        "analysis_version": row[3],
        "is_latest": row[4],
        "document_type": row[5],
        "extraction_method": row[6],
        "parser_engine_version": row[7],
        "confidence_score": float(row[8]) if row[8] is not None else 1.0,
        "extracted_provider_name": row[9],
        "extracted_tax_id": row[10],
        "extracted_invoice_number": row[11],
        "extracted_invoice_date": row[12],
        "extracted_admission_date": row[13],
        "extracted_discharge_date": row[14],
        "extracted_inspection_date": row[15],
        "extracted_repair_date": row[16],
        "extracted_subtotal": row[17],
        "extracted_tax_amount": row[18],
        "extracted_discount_amount": row[19],
        "extracted_total_amount": row[20],
        "extracted_line_items": row[21] if isinstance(row[21], list) else (json.loads(row[21]) if row[21] else []),
        "line_item_math_valid": row[22],
        "sum_matches_total": row[23],
        "calculated_line_items_sum": row[24],
        "rounding_or_tax_discrepancy": row[25],
        "amount_matches_claim": row[26],
        "invoice_vs_claim_amount_discrepancy": row[27],
        "timeline_valid": row[28],
        "timeline_findings": row[29] if isinstance(row[29], list) else (json.loads(row[29]) if row[29] else []),
        "discrepancy_flags": row[30] if isinstance(row[30], list) else (json.loads(row[30]) if row[30] else []),
        "overall_status": row[31],
        "review_recommendation": row[32],
        "raw_extracted_text": row[33],
        "created_at": row[34].isoformat() if row[34] else None,
        "updated_at": row[35].isoformat() if row[35] else None,
    }


async def create_analysis_report(
    conn: psycopg.AsyncConnection,
    evidence_id: str,
    claim_id: str,
    document_type: str,
    extraction_method: str,
    confidence_score: float,
    parser_engine_version: str = "vachan-extractor-1.0",
    extracted_provider_name: Optional[str] = None,
    extracted_tax_id: Optional[str] = None,
    extracted_invoice_number: Optional[str] = None,
    extracted_invoice_date: Optional[Any] = None,
    extracted_admission_date: Optional[Any] = None,
    extracted_discharge_date: Optional[Any] = None,
    extracted_inspection_date: Optional[Any] = None,
    extracted_repair_date: Optional[Any] = None,
    extracted_subtotal: Optional[Decimal] = None,
    extracted_tax_amount: Optional[Decimal] = None,
    extracted_discount_amount: Optional[Decimal] = None,
    extracted_total_amount: Optional[Decimal] = None,
    extracted_line_items: Optional[List[Dict[str, Any]]] = None,
    line_item_math_valid: Optional[bool] = None,
    sum_matches_total: Optional[bool] = None,
    calculated_line_items_sum: Optional[Decimal] = None,
    rounding_or_tax_discrepancy: Optional[Decimal] = None,
    amount_matches_claim: Optional[bool] = None,
    invoice_vs_claim_amount_discrepancy: Optional[Decimal] = None,
    timeline_valid: Optional[bool] = None,
    timeline_findings: Optional[List[str]] = None,
    discrepancy_flags: Optional[List[str]] = None,
    overall_status: str = "CONSISTENT",
    review_recommendation: str = "NO_ACTION_REQUIRED",
    raw_extracted_text: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Creates a new analysis report.
    Supports versioned history: increments analysis_version and updates previous reports
    for this evidence to is_latest = FALSE.
    """
    async with conn.cursor() as cur:
        # 0. Acquire row-level lock on the claim_evidence row to serialize concurrent analysis requests
        await cur.execute(
            "SELECT id FROM claim_evidence WHERE id = %s FOR UPDATE;",
            (evidence_id,),
        )
        evidence_row = await cur.fetchone()
        if not evidence_row:
            raise NotFoundException(f"Claim evidence '{evidence_id}' not found.")

        # 1. Determine next version
        await cur.execute(
            "SELECT COALESCE(MAX(analysis_version), 0) FROM evidence_analysis_reports WHERE evidence_id = %s",
            (evidence_id,),
        )
        row = await cur.fetchone()
        next_ver = (row[0] if row else 0) + 1

        # 2. Mark previous reports as not latest
        await cur.execute(
            "UPDATE evidence_analysis_reports SET is_latest = FALSE WHERE evidence_id = %s",
            (evidence_id,),
        )

        # 3. Truncate raw extracted text if exceeds retention limit
        truncated_text = raw_extracted_text[:10000] if raw_extracted_text else None

        # 4. Insert new report
        insert_sql = f"""
        INSERT INTO evidence_analysis_reports (
            evidence_id, claim_id, analysis_version, is_latest, document_type,
            extraction_method, parser_engine_version, confidence_score,
            extracted_provider_name, extracted_tax_id, extracted_invoice_number,
            extracted_invoice_date, extracted_admission_date, extracted_discharge_date,
            extracted_inspection_date, extracted_repair_date,
            extracted_subtotal, extracted_tax_amount, extracted_discount_amount, extracted_total_amount,
            extracted_line_items,
            line_item_math_valid, sum_matches_total, calculated_line_items_sum,
            rounding_or_tax_discrepancy, amount_matches_claim, invoice_vs_claim_amount_discrepancy,
            timeline_valid, timeline_findings, discrepancy_flags,
            overall_status, review_recommendation, raw_extracted_text
        )
        VALUES (
            %s, %s, %s, TRUE, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s, %s, %s,
            %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s
        )
        RETURNING {REPORT_FIELDS};
        """
        await cur.execute(
            insert_sql,
            (
                evidence_id,
                claim_id,
                next_ver,
                document_type,
                extraction_method,
                parser_engine_version,
                confidence_score,
                extracted_provider_name,
                extracted_tax_id,
                extracted_invoice_number,
                extracted_invoice_date,
                extracted_admission_date,
                extracted_discharge_date,
                extracted_inspection_date,
                extracted_repair_date,
                extracted_subtotal,
                extracted_tax_amount,
                extracted_discount_amount,
                extracted_total_amount,
                json.dumps(extracted_line_items or [], default=_json_default),
                line_item_math_valid,
                sum_matches_total,
                calculated_line_items_sum,
                rounding_or_tax_discrepancy,
                amount_matches_claim,
                invoice_vs_claim_amount_discrepancy,
                timeline_valid,
                json.dumps(timeline_findings or [], default=_json_default),
                json.dumps(discrepancy_flags or [], default=_json_default),
                overall_status,
                review_recommendation,
                truncated_text,
            ),
        )
        inserted = await cur.fetchone()
        if not inserted:
            raise DatabaseException("Failed to insert evidence analysis report.")

        # Also update analysis_status on claim_evidence record
        await cur.execute(
            "UPDATE claim_evidence SET analysis_status = %s WHERE id = %s",
            ("PROCESSED" if overall_status != "FAILED" else "FAILED", evidence_id),
        )

        return _row_to_report_dict(inserted)


async def get_latest_report_by_evidence_id(
    conn: psycopg.AsyncConnection,
    evidence_id: str,
) -> Optional[Dict[str, Any]]:
    """Fetches the latest analysis report for a given evidence item."""
    sql = f"SELECT {REPORT_FIELDS} FROM evidence_analysis_reports WHERE evidence_id = %s AND is_latest = TRUE LIMIT 1"
    async with conn.cursor() as cur:
        await cur.execute(sql, (evidence_id,))
        row = await cur.fetchone()
        return _row_to_report_dict(row) if row else None


async def get_report_by_id(
    conn: psycopg.AsyncConnection,
    report_id: str,
) -> Optional[Dict[str, Any]]:
    """Fetches an analysis report by primary key UUID."""
    sql = f"SELECT {REPORT_FIELDS} FROM evidence_analysis_reports WHERE id = %s LIMIT 1"
    async with conn.cursor() as cur:
        await cur.execute(sql, (report_id,))
        row = await cur.fetchone()
        return _row_to_report_dict(row) if row else None


async def list_reports_by_claim_id(
    conn: psycopg.AsyncConnection,
    claim_id: str,
    latest_only: bool = True,
) -> List[Dict[str, Any]]:
    """Lists all evidence analysis reports associated with a claim."""
    where_clause = "WHERE claim_id = %s"
    if latest_only:
        where_clause += " AND is_latest = TRUE"
    sql = f"SELECT {REPORT_FIELDS} FROM evidence_analysis_reports {where_clause} ORDER BY created_at DESC"
    async with conn.cursor() as cur:
        await cur.execute(sql, (claim_id,))
        rows = await cur.fetchall()
        return [_row_to_report_dict(r) for r in rows]


async def get_analysis_history_for_evidence(
    conn: psycopg.AsyncConnection,
    evidence_id: str,
) -> List[Dict[str, Any]]:
    """Retrieves full versioned history of analysis runs for an evidence item."""
    sql = f"SELECT {REPORT_FIELDS} FROM evidence_analysis_reports WHERE evidence_id = %s ORDER BY analysis_version ASC"
    async with conn.cursor() as cur:
        await cur.execute(sql, (evidence_id,))
        rows = await cur.fetchall()
        return [_row_to_report_dict(r) for r in rows]

