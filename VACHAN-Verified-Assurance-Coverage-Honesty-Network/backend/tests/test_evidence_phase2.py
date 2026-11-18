"""
Phase 2 Backend Tests: Real Claim Evidence Validation, Concurrency, Authorization,
Compensating Cleanup, and Cloudinary Private Signed URLs.
"""

import asyncio
import base64
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest
import psycopg

from app.core.config import get_settings
from app.core.exceptions import (
    AuthorizationException,
    ConflictException,
    NotFoundException,
    ValidationException,
)
from app.core.security import ClaimStatus, EvidenceType, UserRole
from app.db.repositories import claim_evidence_repo
from app.services.evidence_service import EvidenceStorageService, validate_file


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
PDF_MIN = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"


def test_validate_file_magic_bytes_and_spoofing():
    """Rejects spoofed extensions/MIME types and accepts valid octet-stream with matching magic bytes."""
    # Valid PDF with application/octet-stream (Android stream fallback)
    assert validate_file("bill.pdf", PDF_MIN, "application/octet-stream") == "application/pdf"
    # Valid PNG with image/png
    assert validate_file("photo.png", PNG_1X1, "image/png") == "image/png"

    # Spoofed PDF (plain text)
    with pytest.raises(ValidationException):
        validate_file("fake.pdf", b"not a real pdf", "application/pdf")

    # Spoofed WebP (RIFF header without WEBP marker)
    with pytest.raises(ValidationException):
        validate_file("fake.webp", b"RIFF1234WAVEfmt ", "image/webp")

    # Extension vs declared MIME mismatch
    with pytest.raises(ValidationException):
        validate_file("photo.png", PNG_1X1, "image/jpeg")

    # Oversized file
    settings = get_settings()
    oversized = b"%PDF-1.4\n" + (b"0" * settings.MAX_EVIDENCE_FILE_SIZE_BYTES)
    with pytest.raises(ValidationException):
        validate_file("huge.pdf", oversized, "application/pdf")


@pytest.mark.asyncio
async def test_private_download_url_parameters(monkeypatch):
    """Verifies EvidenceStorageService uses cloudinary.utils.private_download_url with 300s expiry."""
    captured = {}

    def fake_private_download_url(public_id, fmt, **options):
        captured["public_id"] = public_id
        captured["format"] = fmt
        captured["options"] = options
        return f"https://api.cloudinary.com/v1_1/demo/{options.get('resource_type')}/download?public_id={public_id}&format={fmt}"

    monkeypatch.setattr("cloudinary.utils.private_download_url", fake_private_download_url)

    svc = EvidenceStorageService()
    svc._is_configured = True
    url = await svc.generate_signed_url("claims/c1/evidence_abc", "application/pdf", expires_in_seconds=300)

    assert "download" in url
    assert captured["public_id"] == "claims/c1/evidence_abc"
    assert captured["format"] == "pdf"
    assert captured["options"]["type"] == "private"
    assert captured["options"]["resource_type"] == "raw"
    assert captured["options"]["expires_at"] > 0


@pytest.mark.asyncio
async def test_create_evidence_unique_violation_raises_conflict():
    """DB UniqueViolation on (claim_id, document_checksum) translates to ConflictException."""
    mock_cursor = AsyncMock()
    mock_cursor.execute.side_effect = psycopg.errors.UniqueViolation("uq_claim_evidence_claim_checksum")
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__aexit__ = AsyncMock(return_value=False)

    with pytest.raises(ConflictException):
        await claim_evidence_repo.create_evidence(
            conn=mock_conn,
            claim_id=str(uuid.uuid4()),
            uploader_id=str(uuid.uuid4()),
            evidence_type="MEDICAL_BILL",
            original_filename="inv.pdf",
            document_storage_ref="claims/1/ev_1",
            file_size_bytes=47,
            mime_type="application/pdf",
            document_checksum="a" * 64,
        )


@pytest.mark.asyncio
async def test_evidence_authorization_and_claim_mismatch(async_client):
    """Tests Customer ownership, Agent denial, and evidence/claim mismatch via API routes."""
    from app.api.routes.claims import get_evidence_signed_url, list_claim_evidence, upload_evidence

    agent_user = {"id": str(uuid.uuid4()), "role": UserRole.INSURANCE_AGENT.value}
    cust_b = {"id": str(uuid.uuid4()), "role": UserRole.CUSTOMER.value}

    # Agent blocked from listing & signed-url
    with pytest.raises(AuthorizationException):
        await list_claim_evidence(str(uuid.uuid4()), current_user=agent_user)

    with pytest.raises(AuthorizationException):
        await get_evidence_signed_url(str(uuid.uuid4()), str(uuid.uuid4()), current_user=agent_user)

    # Customer B blocked from Customer A's claim
    fake_claim_id = str(uuid.uuid4())
    fake_evidence_id = str(uuid.uuid4())
    with patch("app.api.routes.claims.get_db_connection") as mock_db, \
         patch("app.api.routes.claims.claim_repo.get_claim_by_id", new=AsyncMock(return_value={
             "id": fake_claim_id,
             "customer_id": str(uuid.uuid4()),  # Different owner
             "registration_id": str(uuid.uuid4()),
             "status": ClaimStatus.SUBMITTED.value,
         })):
        mock_db.return_value.__aenter__.return_value = AsyncMock()
        with pytest.raises(NotFoundException):
            await get_evidence_signed_url(fake_claim_id, fake_evidence_id, current_user=cust_b)


@pytest.mark.asyncio
async def test_upload_evidence_compensating_cleanup_and_limit(monkeypatch):
    """Tests 5-file limit enforcement and Cloudinary cleanup when DB insert fails."""
    from fastapi import UploadFile
    import io
    from app.api.routes.claims import upload_evidence

    cust_id = str(uuid.uuid4())
    claim_id = str(uuid.uuid4())
    cust_user = {"id": cust_id, "role": UserRole.CUSTOMER.value}

    def make_upload(name: str, data: bytes, mime: str) -> UploadFile:
        return UploadFile(filename=name, file=io.BytesIO(data), headers={"content-type": mime})

    # 1. Limit of 5 exceeded
    with patch("app.api.routes.claims.get_db_connection") as mock_db, \
         patch("app.api.routes.claims.claim_repo.get_claim_by_id", new=AsyncMock(return_value={
             "id": claim_id, "customer_id": cust_id, "registration_id": str(uuid.uuid4()),
             "status": ClaimStatus.SUBMITTED.value,
         })), \
         patch("app.api.routes.claims.claim_evidence_repo.lock_claim_for_evidence", new=AsyncMock()), \
         patch("app.api.routes.claims.claim_evidence_repo.count_evidence_by_claim", new=AsyncMock(return_value=5)):
        mock_db.return_value.__aenter__.return_value = AsyncMock()
        with pytest.raises(ValidationException) as exc:
            await upload_evidence(
                claim_id=claim_id,
                evidence_type=EvidenceType.MEDICAL_BILL,
                file=make_upload("bill.pdf", PDF_MIN, "application/pdf"),
                current_user=cust_user,
            )
        assert "Maximum of 5" in exc.value.message

    # 2. Compensating cleanup on DB insert failure
    delete_mock = AsyncMock()
    with patch("app.api.routes.claims.get_db_connection") as mock_db, \
         patch("app.api.routes.claims.claim_repo.get_claim_by_id", new=AsyncMock(return_value={
             "id": claim_id, "customer_id": cust_id, "registration_id": str(uuid.uuid4()),
             "status": ClaimStatus.SUBMITTED.value,
         })), \
         patch("app.api.routes.claims.claim_evidence_repo.lock_claim_for_evidence", new=AsyncMock()), \
         patch("app.api.routes.claims.claim_evidence_repo.count_evidence_by_claim", new=AsyncMock(return_value=0)), \
         patch("app.api.routes.claims.claim_evidence_repo.get_evidence_by_checksum", new=AsyncMock(return_value=None)), \
         patch("app.api.routes.claims.evidence_service.upload_evidence", new=AsyncMock(return_value=("claims/c/ev1", "a" * 64, {"resource_type": "raw"}))), \
         patch("app.api.routes.claims.claim_evidence_repo.create_evidence", new=AsyncMock(side_effect=RuntimeError("DB write failed"))), \
         patch("app.api.routes.claims.evidence_service.delete_evidence_file", new=delete_mock):
        mock_db.return_value.__aenter__.return_value = AsyncMock()
        with pytest.raises(RuntimeError):
            await upload_evidence(
                claim_id=claim_id,
                evidence_type=EvidenceType.MEDICAL_BILL,
                file=make_upload("bill.pdf", PDF_MIN, "application/pdf"),
                current_user=cust_user,
            )
        delete_mock.assert_awaited_once_with("claims/c/ev1", resource_type="raw")
