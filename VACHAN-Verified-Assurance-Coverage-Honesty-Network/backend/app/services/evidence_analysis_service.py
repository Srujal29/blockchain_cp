"""
Evidence Analysis Service for InsureChain VoiceGuard (Phase 6 Stage 2).
Integrates Document OCR and Invoice Arithmetic Auditor into the claim evidence lifecycle.
Extracts structured invoice and discharge summary fields, runs deterministic arithmetic and timeline checks,
and records versioned, advisory analysis reports.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
import psycopg

from app.core.exceptions import NotFoundException
from app.core.logging import get_logger
from app.db.repositories import (
    audit_repo,
    claim_evidence_repo,
    claim_repo,
    evidence_analysis_repo,
)
from app.services.document_ocr import extract_document_text
from app.services.evidence_service import evidence_service
from app.services.invoice_auditor import (
    detect_document_type,
    evaluate_overall_evidence_integrity,
    parse_clean_decimal,
    parse_flexible_date,
    parse_invoice_fields,
    validate_document_timeline,
    validate_invoice_arithmetic,
)

logger = get_logger(__name__)


class EvidenceAnalysisService:
    """Orchestrates evidence document extraction, deterministic arithmetic validation, and persistence."""

    async def analyze_evidence_document(
        self,
        conn: psycopg.AsyncConnection,
        claim_id: str,
        evidence_id: str,
        content: Optional[bytes] = None,
        actor_id: Optional[str] = None,
        actor_role: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes text extraction and arithmetic integrity analysis for a claim evidence document.
        If `content` is not provided, downloads private asset bytes via signed URL.
        Persists versioned report through evidence_analysis_repo.
        """
        evidence = await claim_evidence_repo.get_evidence_by_id(conn, evidence_id)
        if not evidence or evidence["claim_id"] != claim_id:
            raise NotFoundException("Evidence document not found.")

        claim = await claim_repo.get_claim_by_id(conn, claim_id)
        if not claim:
            raise NotFoundException("Claim not found.")

        # 1. Obtain file bytes
        file_bytes = content
        if file_bytes is None:
            try:
                file_bytes = await evidence_service.download_private_file_bytes(
                    document_storage_ref=evidence["document_storage_ref"],
                    mime_type=evidence["mime_type"],
                )
            except Exception as dl_err:
                logger.warning(
                    "Could not download evidence bytes for analysis (evidence_id=%s): %s",
                    evidence_id,
                    dl_err,
                )
                file_bytes = None

        # 2. Extract Text via multi-stage OCR / PDF reader
        if file_bytes:
            try:
                raw_text, extraction_method, confidence_score = extract_document_text(
                    content=file_bytes,
                    mime_type=evidence.get("mime_type"),
                    filename=evidence.get("original_filename"),
                )
            except Exception as ocr_err:
                logger.error("OCR extraction raised unexpected error: %s", ocr_err)
                raw_text, extraction_method, confidence_score = "", "MANUAL_FALLBACK", 0.0
        else:
            raw_text, extraction_method, confidence_score = "", "MANUAL_FALLBACK", 0.0

        # 3. Detect Document Type
        doc_type = detect_document_type(raw_text)
        if doc_type == "UNKNOWN":
            ev_type = (evidence.get("evidence_type") or "").upper()
            if any(k in ev_type for k in ["HOSPITAL", "MEDICAL", "BILL", "PHARMACY"]):
                doc_type = "MEDICAL_INVOICE"
            elif any(k in ev_type for k in ["REPAIR", "ESTIMATE", "GARAGE", "WORKSHOP"]):
                doc_type = "VEHICLE_REPAIR_ESTIMATE"
            elif "DISCHARGE" in ev_type:
                doc_type = "DISCHARGE_SUMMARY"
            elif "RECEIPT" in ev_type:
                doc_type = "RECEIPT"
            else:
                doc_type = "GENERIC_INVOICE"

        # 4. Extract Structured Fields
        extracted = parse_invoice_fields(raw_text, doc_type)

        # 5. Arithmetic Auditing
        claim_amt = parse_clean_decimal(str(claim.get("requested_amount", "")))
        arithmetic_results = validate_invoice_arithmetic(extracted, claim_requested_amount=claim_amt)

        # 6. Timeline Auditing
        inc_date = None
        raw_inc = claim.get("incident_date")
        if raw_inc:
            inc_date = parse_flexible_date(str(raw_inc)) if isinstance(raw_inc, str) else raw_inc

        sub_date = None
        raw_sub = claim.get("submission_timestamp") or claim.get("created_at")
        if raw_sub:
            sub_date = (
                parse_flexible_date(str(raw_sub)[:10])
                if isinstance(raw_sub, str)
                else getattr(raw_sub, "date", lambda: None)()
            )

        extracted_dates = {
            "invoice_date": extracted.get("invoice_date"),
            "admission_date": extracted.get("admission_date"),
            "discharge_date": extracted.get("discharge_date"),
            "inspection_date": extracted.get("inspection_date"),
            "repair_date": extracted.get("repair_date"),
        }
        claim_dates = {
            "incident_date": inc_date,
            "submission_date": sub_date,
        }

        timeline_valid, timeline_findings = validate_document_timeline(
            extracted_dates=extracted_dates,
            claim_dates=claim_dates,
            document_type=doc_type,
        )

        # 7. Overall Evidence Integrity Evaluation
        overall_status, review_rec, discrepancy_flags = evaluate_overall_evidence_integrity(
            document_type=doc_type,
            extraction_method=extraction_method,
            confidence_score=confidence_score,
            arithmetic_results=arithmetic_results,
            timeline_valid=timeline_valid,
            timeline_findings=timeline_findings,
            has_extracted_text=bool(raw_text and raw_text.strip()),
        )

        # 8. Persist Analysis Report (Atomic Versioning & Locked)
        report = await evidence_analysis_repo.create_analysis_report(
            conn=conn,
            evidence_id=evidence_id,
            claim_id=claim_id,
            document_type=doc_type,
            extraction_method=extraction_method,
            confidence_score=confidence_score,
            parser_engine_version="vachan-extractor-1.0",
            extracted_provider_name=extracted.get("provider_name"),
            extracted_tax_id=extracted.get("tax_id"),
            extracted_invoice_number=extracted.get("invoice_number"),
            extracted_invoice_date=extracted.get("invoice_date"),
            extracted_admission_date=extracted.get("admission_date"),
            extracted_discharge_date=extracted.get("discharge_date"),
            extracted_inspection_date=extracted.get("inspection_date"),
            extracted_repair_date=extracted.get("repair_date"),
            extracted_subtotal=extracted.get("subtotal"),
            extracted_tax_amount=extracted.get("tax_amount"),
            extracted_discount_amount=extracted.get("discount_amount"),
            extracted_total_amount=extracted.get("total_amount"),
            extracted_line_items=extracted.get("line_items", []),
            line_item_math_valid=arithmetic_results.get("line_item_math_valid"),
            sum_matches_total=arithmetic_results.get("sum_matches_total"),
            calculated_line_items_sum=arithmetic_results.get("calculated_line_items_sum"),
            rounding_or_tax_discrepancy=arithmetic_results.get("rounding_or_tax_discrepancy"),
            amount_matches_claim=arithmetic_results.get("amount_matches_claim"),
            invoice_vs_claim_amount_discrepancy=arithmetic_results.get("invoice_vs_claim_amount_discrepancy"),
            timeline_valid=timeline_valid,
            timeline_findings=timeline_findings,
            discrepancy_flags=discrepancy_flags,
            overall_status=overall_status,
            review_recommendation=review_rec,
            raw_extracted_text=raw_text,
        )

        # 9. Audit Event
        await audit_repo.log_audit_event(
            conn=conn,
            actor_id=actor_id or "system",
            actor_role=actor_role or "SYSTEM",
            action="EVIDENCE_ANALYSIS_COMPLETED",
            target_type="evidence_analysis_report",
            target_id=report["id"],
            metadata={
                "claim_id": claim_id,
                "evidence_id": evidence_id,
                "analysis_version": report["analysis_version"],
                "document_type": doc_type,
                "extraction_method": extraction_method,
                "overall_status": overall_status,
                "review_recommendation": review_rec,
                "discrepancies_count": len(discrepancy_flags),
            },
        )

        return report


evidence_analysis_service = EvidenceAnalysisService()
