-- ==============================================================================
-- InsureChain VoiceGuard — Migration 0008: Claim Evidence Checksum Uniqueness
-- ==============================================================================
-- Enforces database-level duplicate prevention for identical evidence files
-- uploaded to the same claim (paired with FOR UPDATE row locking on claims).

CREATE UNIQUE INDEX IF NOT EXISTS uq_claim_evidence_claim_checksum
    ON claim_evidence (claim_id, document_checksum);

