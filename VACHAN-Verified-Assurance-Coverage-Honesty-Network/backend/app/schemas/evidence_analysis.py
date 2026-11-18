"""
Pydantic schemas for Phase 6 Evidence Analysis, Document OCR, and Invoice Arithmetic Audits.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    MEDICAL_INVOICE = "MEDICAL_INVOICE"
    DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"
    VEHICLE_REPAIR_ESTIMATE = "VEHICLE_REPAIR_ESTIMATE"
    RECEIPT = "RECEIPT"
    GENERIC_INVOICE = "GENERIC_INVOICE"
    UNKNOWN = "UNKNOWN"


class ExtractionMethod(str, Enum):
    PDF_TEXT = "PDF_TEXT"
    OCR_TESSERACT = "OCR_TESSERACT"
    MANUAL_FALLBACK = "MANUAL_FALLBACK"


class OverallAnalysisStatus(str, Enum):
    CONSISTENT = "CONSISTENT"
    DISCREPANCIES_DETECTED = "DISCREPANCIES_DETECTED"
    NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"
    FAILED = "FAILED"


class ReviewRecommendation(str, Enum):
    NO_ACTION_REQUIRED = "NO_ACTION_REQUIRED"
    ADVISORY_REVIEW_RECOMMENDED = "ADVISORY_REVIEW_RECOMMENDED"
    MANUAL_INSPECTION_REQUIRED = "MANUAL_INSPECTION_REQUIRED"
    EXTRACTION_UNAVAILABLE = "EXTRACTION_UNAVAILABLE"


class LineItemModel(BaseModel):
    description: str = Field(description="Description of invoiced item or service")
    quantity: Optional[Decimal] = Field(default=None, description="Extracted quantity if present")
    unit_rate: Optional[Decimal] = Field(default=None, description="Extracted rate per unit if present")
    total: Decimal = Field(description="Extracted total monetary amount for line item")
    math_valid: Optional[bool] = Field(
        default=None, description="True if quantity * unit_rate == total within tolerance"
    )


class EvidenceAnalysisReportResponse(BaseModel):
    id: str
    evidence_id: str
    claim_id: str
    analysis_version: int
    is_latest: bool
    document_type: DocumentType
    extraction_method: ExtractionMethod
    parser_engine_version: str
    confidence_score: float
    
    # Extracted fields
    extracted_provider_name: Optional[str] = None
    extracted_tax_id: Optional[str] = None
    extracted_invoice_number: Optional[str] = None
    extracted_invoice_date: Optional[date] = None
    extracted_admission_date: Optional[date] = None
    extracted_discharge_date: Optional[date] = None
    extracted_inspection_date: Optional[date] = None
    extracted_repair_date: Optional[date] = None
    
    # Monetary figures
    extracted_subtotal: Optional[Decimal] = None
    extracted_tax_amount: Optional[Decimal] = None
    extracted_discount_amount: Optional[Decimal] = None
    extracted_total_amount: Optional[Decimal] = None
    extracted_line_items: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Arithmetic & Timeline checks
    line_item_math_valid: Optional[bool] = None
    sum_matches_total: Optional[bool] = None
    calculated_line_items_sum: Optional[Decimal] = None
    rounding_or_tax_discrepancy: Optional[Decimal] = None
    amount_matches_claim: Optional[bool] = None
    invoice_vs_claim_amount_discrepancy: Optional[Decimal] = None
    timeline_valid: Optional[bool] = None
    timeline_findings: List[str] = Field(default_factory=list)
    discrepancy_flags: List[str] = Field(default_factory=list)
    
    overall_status: OverallAnalysisStatus
    review_recommendation: ReviewRecommendation
    raw_extracted_text: Optional[str] = None
    created_at: datetime


class EvidenceAnalysisListResponse(BaseModel):
    claim_id: str
    total_reports: int
    reports: List[EvidenceAnalysisReportResponse]

