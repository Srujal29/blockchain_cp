-- ==============================================================================
-- InsureChain VoiceGuard — Migration 0009: Evidence Analysis Reports Table
-- ==============================================================================
-- Additive, idempotent migration storing structured OCR extractions,
-- line-item parsing, invoice arithmetic audits, and timeline integrity findings.
-- Supports versioned re-analysis history while preserving claim & evidence ownership.

CREATE TABLE IF NOT EXISTS evidence_analysis_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    evidence_id UUID NOT NULL REFERENCES claim_evidence(id) ON DELETE CASCADE,
    claim_id UUID NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    analysis_version INTEGER NOT NULL DEFAULT 1 CHECK (analysis_version >= 1),
    is_latest BOOLEAN NOT NULL DEFAULT TRUE,
    
    document_type VARCHAR(64) NOT NULL CHECK (
        document_type IN (
            'MEDICAL_INVOICE',
            'DISCHARGE_SUMMARY',
            'VEHICLE_REPAIR_ESTIMATE',
            'RECEIPT',
            'GENERIC_INVOICE',
            'UNKNOWN'
        )
    ),
    extraction_method VARCHAR(32) NOT NULL CHECK (
        extraction_method IN ('PDF_TEXT', 'OCR_TESSERACT', 'MANUAL_FALLBACK')
    ),
    parser_engine_version VARCHAR(64) NOT NULL DEFAULT 'vachan-extractor-1.0',
    confidence_score NUMERIC(5, 4) NOT NULL DEFAULT 1.0000 CHECK (
        confidence_score >= 0.0000 AND confidence_score <= 1.0000
    ),
    
    -- Extracted Entity Fields
    extracted_provider_name VARCHAR(255),
    extracted_tax_id VARCHAR(64),
    extracted_invoice_number VARCHAR(128),
    extracted_invoice_date DATE,
    extracted_admission_date DATE,
    extracted_discharge_date DATE,
    extracted_inspection_date DATE,
    extracted_repair_date DATE,
    
    -- Extracted Monetary Figures
    extracted_subtotal NUMERIC(14, 2),
    extracted_tax_amount NUMERIC(14, 2),
    extracted_discount_amount NUMERIC(14, 2),
    extracted_total_amount NUMERIC(14, 2),
    extracted_line_items JSONB NOT NULL DEFAULT '[]'::jsonb,
    
    -- Deterministic Arithmetic & Timeline Validation Results
    line_item_math_valid BOOLEAN,
    sum_matches_total BOOLEAN,
    calculated_line_items_sum NUMERIC(14, 2),
    rounding_or_tax_discrepancy NUMERIC(14, 2),
    amount_matches_claim BOOLEAN,
    invoice_vs_claim_amount_discrepancy NUMERIC(14, 2),
    timeline_valid BOOLEAN,
    timeline_findings JSONB NOT NULL DEFAULT '[]'::jsonb,
    discrepancy_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    
    -- High-Level Report Status & Recommendations
    overall_status VARCHAR(32) NOT NULL DEFAULT 'CONSISTENT' CHECK (
        overall_status IN (
            'CONSISTENT',
            'DISCREPANCIES_DETECTED',
            'NEEDS_MANUAL_REVIEW',
            'FAILED'
        )
    ),
    review_recommendation VARCHAR(64) NOT NULL DEFAULT 'NO_ACTION_REQUIRED' CHECK (
        review_recommendation IN (
            'NO_ACTION_REQUIRED',
            'ADVISORY_REVIEW_RECOMMENDED',
            'MANUAL_INSPECTION_REQUIRED',
            'EXTRACTION_UNAVAILABLE'
        )
    ),
    
    -- Raw content with retention boundaries (truncated to 10k chars)
    raw_extracted_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT uq_evidence_analysis_version UNIQUE (evidence_id, analysis_version)
);

CREATE INDEX IF NOT EXISTS idx_evidence_analysis_claim ON evidence_analysis_reports (claim_id);
CREATE INDEX IF NOT EXISTS idx_evidence_analysis_evidence_latest ON evidence_analysis_reports (evidence_id, is_latest);
CREATE INDEX IF NOT EXISTS idx_evidence_analysis_status ON evidence_analysis_reports (overall_status);

