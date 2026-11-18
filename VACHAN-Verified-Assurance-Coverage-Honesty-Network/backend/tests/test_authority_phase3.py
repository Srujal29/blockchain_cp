"""
Phase 3 Backend Tests: Approval Authority Agent Approval & Policy Management Workflows.
"""

from datetime import date
import io
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest
from fastapi import UploadFile

from pathlib import Path
from app.core.exceptions import (
    AuthorizationException,
    ConflictException,
    ValidationException,
)
from app.core.security import AccountStatus, PolicyCategory, UserRole
from app.schemas.auth import ApproveAccountRequest
from app.schemas.policy import CreatePolicyRequest
from app.services.policy_extractor import PolicyExtractorService


_SAMPLE_PDF_PATH = Path(__file__).resolve().parent.parent / "care_premier_health_shield_policy_wording.pdf"
PDF_VALID = _SAMPLE_PDF_PATH.read_bytes() if _SAMPLE_PDF_PATH.is_file() else (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
    b"0000000054 00000 n \n0000000105 00000 n \n"
    b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n171\n%%EOF"
)


@pytest.mark.asyncio
async def test_agent_listing_pagination_and_rbac():
    """Authority can list paginated agents with filters; non-authorities are rejected by deps."""
    from app.api.routes.auth import list_agents_for_authority

    authority = {"id": str(uuid.uuid4()), "role": UserRole.APPROVAL_AUTHORITY.value}
    sample_agent = {
        "id": str(uuid.uuid4()),
        "email": "agent1@example.com",
        "full_name": "Agent One",
        "phone": "9999999999",
        "role": UserRole.INSURANCE_AGENT.value,
        "account_status": AccountStatus.PENDING_APPROVAL.value,
        "email_verified_at": None,
        "created_at": "2026-11-12T10:00:00Z",
    }

    with patch("app.api.routes.auth.get_db_connection") as mock_db, \
         patch("app.api.routes.auth.user_repo.list_users", new=AsyncMock(return_value=[sample_agent])) as mock_list, \
         patch("app.api.routes.auth.user_repo.count_users", new=AsyncMock(return_value=1)):
        mock_db.return_value.__aenter__.return_value = AsyncMock()
        res = await list_agents_for_authority(
            status_filter="PENDING_APPROVAL",
            page=2,
            page_size=10,
            current_authority=authority,
        )

    assert res["total"] == 1
    assert res["page"] == 2
    assert res["page_size"] == 10
    assert len(res["items"]) == 1
    mock_list.assert_awaited_once()
    assert mock_list.call_args.kwargs["offset"] == 10

    with pytest.raises(ValidationException):
        await list_agents_for_authority(
            status_filter="INVALID_STATUS",
            page=1,
            page_size=20,
            current_authority=authority,
        )


@pytest.mark.asyncio
async def test_approve_reject_agent_rules_and_token_revocation():
    """Tests self-approval block, customer-protection, mandatory rejection reason, token revocation, and audit."""
    from app.api.routes.auth import approve_account

    auth_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    cust_id = str(uuid.uuid4())
    authority = {"id": auth_id, "role": UserRole.APPROVAL_AUTHORITY.value}

    # 1. Self-approval blocked
    with pytest.raises(AuthorizationException):
        await approve_account(
            ApproveAccountRequest(user_id=auth_id, status=AccountStatus.ACTIVE),
            current_authority=authority,
        )

    # 2. Rejection requires >= 5 char reason
    with pytest.raises(ValidationException):
        await approve_account(
            ApproveAccountRequest(user_id=agent_id, status=AccountStatus.REJECTED, reason="no"),
            current_authority=authority,
        )

    # 3. Customer accounts cannot be modified here
    with patch("app.api.routes.auth.get_db_connection") as mock_db, \
         patch("app.api.routes.auth.user_repo.lock_user_for_status_update", new=AsyncMock()), \
         patch("app.api.routes.auth.user_repo.get_user_by_id", new=AsyncMock(return_value={
             "id": cust_id, "role": UserRole.CUSTOMER.value, "account_status": "ACTIVE"
         })):
        mock_db.return_value.__aenter__.return_value = AsyncMock()
        with pytest.raises(AuthorizationException):
            await approve_account(
                ApproveAccountRequest(user_id=cust_id, status=AccountStatus.REJECTED, reason="Invalid customer"),
                current_authority=authority,
            )

    # 4. Rejecting an agent revokes refresh tokens and writes audit log
    revoke_mock = AsyncMock()
    audit_mock = AsyncMock()
    updated_agent = {
        "id": agent_id,
        "email": "agent@example.com",
        "full_name": "Agent Test",
        "role": UserRole.INSURANCE_AGENT.value,
        "account_status": AccountStatus.REJECTED.value,
    }
    with patch("app.api.routes.auth.get_db_connection") as mock_db, \
         patch("app.api.routes.auth.user_repo.lock_user_for_status_update", new=AsyncMock()), \
         patch("app.api.routes.auth.user_repo.get_user_by_id", new=AsyncMock(return_value={
             "id": agent_id, "role": UserRole.INSURANCE_AGENT.value, "account_status": "PENDING_APPROVAL"
         })), \
         patch("app.api.routes.auth.user_repo.update_account_status", new=AsyncMock(return_value=updated_agent)), \
         patch("app.api.routes.auth.token_repo.revoke_all_user_refresh_tokens", new=revoke_mock), \
         patch("app.api.routes.auth.audit_repo.log_audit_event", new=audit_mock):
        mock_db.return_value.__aenter__.return_value = AsyncMock()
        res = await approve_account(
            ApproveAccountRequest(
                user_id=agent_id,
                status=AccountStatus.REJECTED,
                reason="Missing IRDAI license number",
            ),
            current_authority=authority,
        )

    assert res["account_status"] == AccountStatus.REJECTED.value
    revoke_mock.assert_awaited_once()
    audit_mock.assert_awaited_once()
    assert audit_mock.call_args.kwargs["action"] == "ACCOUNT_STATUS_DECISION"


@pytest.mark.asyncio
async def test_policy_pdf_upload_spoofing_cleanup_and_audit():
    """Tests PDF magic-byte rejection, successful private upload + extraction + audit, and cleanup on DB error."""
    from app.api.routes.policies import upload_policy_version_pdf

    authority = {"id": str(uuid.uuid4()), "role": UserRole.APPROVAL_AUTHORITY.value}
    policy_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())

    def make_pdf_upload(name: str, data: bytes) -> UploadFile:
        return UploadFile(filename=name, file=io.BytesIO(data), headers={"content-type": "application/pdf"})

    # 1. Spoofed non-PDF rejected before Cloudinary upload
    with patch("app.api.routes.policies.get_db_connection") as mock_db, \
         patch("app.api.routes.policies.policy_repo.lock_policy_for_versioning", new=AsyncMock()), \
         patch("app.api.routes.policies.policy_repo.get_policy_by_id", new=AsyncMock(return_value={"id": policy_id, "is_active": True})), \
         patch("app.api.routes.policies.policy_repo.get_next_version_number", new=AsyncMock(return_value=1)), \
         patch("app.api.routes.policies.policy_repo.list_policy_versions", new=AsyncMock(return_value=[])):
        mock_db.return_value.__aenter__.return_value = AsyncMock()
        with pytest.raises(ValidationException):
            await upload_policy_version_pdf(
                policy_id=policy_id,
                effective_date=date(2026, 11, 12),
                expiry_date=None,
                version_number=None,
                terms_json=None,
                file=make_pdf_upload("fake.pdf", b"not-a-pdf"),
                current_authority=authority,
            )

    # 2. Compensating cleanup if DB insert fails
    delete_mock = AsyncMock()
    with patch("app.api.routes.policies.get_db_connection") as mock_db, \
         patch("app.api.routes.policies.policy_repo.lock_policy_for_versioning", new=AsyncMock()), \
         patch("app.api.routes.policies.policy_repo.get_policy_by_id", new=AsyncMock(return_value={"id": policy_id, "is_active": True})), \
         patch("app.api.routes.policies.policy_repo.get_next_version_number", new=AsyncMock(return_value=1)), \
         patch("app.api.routes.policies.policy_repo.list_policy_versions", new=AsyncMock(return_value=[])), \
         patch("app.api.routes.policies.evidence_service.upload_policy_pdf", new=AsyncMock(return_value=("policies/p1/v1_abc", "b" * 64, {"resource_type": "raw"}))), \
         patch("app.api.routes.policies.policy_repo.create_policy_version", new=AsyncMock(side_effect=RuntimeError("DB fail"))), \
         patch("app.api.routes.policies.evidence_service.delete_evidence_file", new=delete_mock):
        mock_db.return_value.__aenter__.return_value = AsyncMock()
        with pytest.raises(RuntimeError):
            await upload_policy_version_pdf(
                policy_id=policy_id,
                effective_date=date(2026, 11, 12),
                expiry_date=None,
                version_number=None,
                terms_json=None,
                file=make_pdf_upload("valid.pdf", PDF_VALID),
                current_authority=authority,
            )
        delete_mock.assert_awaited_once_with("policies/p1/v1_abc", resource_type="raw")

    # 3. Successful upload + extraction + audit events
    audit_mock = AsyncMock()
    extract_save_mock = AsyncMock()
    created_ver = {
        "id": version_id,
        "policy_id": policy_id,
        "version_number": 1,
        "document_storage_ref": "policies/p1/v1_abc",
        "document_checksum": "b" * 64,
        "effective_date": "2026-11-12",
        "expiry_date": None,
        "terms_json": {},
        "is_published": False,
        "published_at": None,
        "published_by": None,
        "created_at": "2026-11-12T10:00:00Z",
    }
    with patch("app.api.routes.policies.get_db_connection") as mock_db, \
         patch("app.api.routes.policies.policy_repo.lock_policy_for_versioning", new=AsyncMock()), \
         patch("app.api.routes.policies.policy_repo.get_policy_by_id", new=AsyncMock(return_value={"id": policy_id, "is_active": True})), \
         patch("app.api.routes.policies.policy_repo.get_next_version_number", new=AsyncMock(return_value=1)), \
         patch("app.api.routes.policies.policy_repo.list_policy_versions", new=AsyncMock(return_value=[])), \
         patch("app.api.routes.policies.evidence_service.upload_policy_pdf", new=AsyncMock(return_value=("policies/p1/v1_abc", "b" * 64, {"resource_type": "raw"}))), \
         patch("app.api.routes.policies.policy_repo.create_policy_version", new=AsyncMock(return_value=created_ver)), \
         patch("app.api.routes.policies.extraction_repo.create_extraction", new=extract_save_mock), \
         patch("app.api.routes.policies.audit_repo.log_audit_event", new=audit_mock):
        mock_db.return_value.__aenter__.return_value = AsyncMock()
        res = await upload_policy_version_pdf(
            policy_id=policy_id,
            effective_date=date(2026, 11, 12),
            expiry_date=None,
            version_number=None,
            terms_json=None,
            file=make_pdf_upload("valid.pdf", PDF_VALID),
            current_authority=authority,
        )
    assert res["id"] == version_id
    extract_save_mock.assert_awaited_once()
    actions = [c.kwargs["action"] for c in audit_mock.call_args_list]
    assert "UPLOAD_POLICY_DOCUMENT" in actions
    assert "CREATE_POLICY_VERSION" in actions


@pytest.mark.asyncio
async def test_policy_publish_validation_and_draft_visibility():
    """Tests publish immutability, document validation, and that GET /policies excludes drafts."""
    from app.api.routes.policies import list_active_policies, publish_policy_version

    authority = {"id": str(uuid.uuid4()), "role": UserRole.APPROVAL_AUTHORITY.value}
    policy_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())

    # Cannot re-publish an already published version
    with patch("app.api.routes.policies.get_db_connection") as mock_db, \
         patch("app.api.routes.policies.policy_repo.lock_policy_for_versioning", new=AsyncMock()), \
         patch("app.api.routes.policies.policy_repo.get_policy_by_id", new=AsyncMock(return_value={"id": policy_id, "is_active": True})), \
         patch("app.api.routes.policies.policy_repo.get_policy_version_by_id", new=AsyncMock(return_value={
             "id": version_id, "policy_id": policy_id, "version_number": 1, "is_published": True
         })):
        mock_db.return_value.__aenter__.return_value = AsyncMock()
        with pytest.raises(ConflictException):
            await publish_policy_version(policy_id, version_id, current_authority=authority)

    # Draft policy without published version is excluded from public GET /policies
    draft_policy = {
        "id": policy_id,
        "insurer_name": "Test",
        "policy_name": "Draft Shield",
        "policy_code": "DRF-01",
        "category": "GENERIC",
        "description": "Draft only policy",
        "coverage_limit": 100000.0,
        "waiting_period_days": 0,
        "claim_filing_window_days": 30,
        "is_active": True,
    }
    mock_cursor = AsyncMock()
    mock_cursor.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("app.api.routes.policies.get_db_connection") as mock_db, \
         patch("app.api.routes.policies.policy_repo.list_policies", new=AsyncMock(return_value=[draft_policy])):
        mock_db.return_value.__aenter__.return_value = mock_conn
        visible = await list_active_policies()
    assert visible == []


@pytest.mark.asyncio
async def test_policy_extractor_resolves_private_cloudinary_ref(monkeypatch):
    """PolicyExtractorService fetches private Cloudinary policy refs via signed URL."""
    signed_mock = AsyncMock(return_value="https://api.cloudinary.com/v1_1/demo/raw/download?sig=ok")
    monkeypatch.setattr("app.services.evidence_service.evidence_service.generate_signed_url", signed_mock)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def get(self, url):
            class Resp:
                content = PDF_VALID
                def raise_for_status(self):
                    pass
            return Resp()

    monkeypatch.setattr("httpx.Client", FakeClient)

    extractor = PolicyExtractorService()
    data = await extractor.fetch_document_bytes("policies/p1/v1_abc")
    assert data == PDF_VALID
    signed_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_policy_extraction_failure_recorded_and_retriable():
    """
    Extraction failure during upload records status='FAILED' + audit event without deleting the
    valid Cloudinary PDF, and failed extractions can be retried without duplicate policy_versions.
    """
    from app.api.routes.policies import upload_policy_version_pdf

    authority = {"id": str(uuid.uuid4()), "role": UserRole.APPROVAL_AUTHORITY.value}
    policy_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    checksum = "c" * 64
    created_ver = {
        "id": version_id,
        "policy_id": policy_id,
        "version_number": 1,
        "document_storage_ref": "policies/p1/v1_fail",
        "document_checksum": checksum,
        "effective_date": "2026-11-12",
        "expiry_date": None,
        "terms_json": {},
        "is_published": False,
        "published_at": None,
        "published_by": None,
        "created_at": "2026-11-12T10:00:00Z",
    }

    extract_save_mock = AsyncMock()
    audit_mock = AsyncMock()
    delete_mock = AsyncMock()

    with patch("app.api.routes.policies.get_db_connection") as mock_db, \
         patch("app.api.routes.policies.policy_repo.lock_policy_for_versioning", new=AsyncMock()), \
         patch("app.api.routes.policies.policy_repo.get_policy_by_id", new=AsyncMock(return_value={"id": policy_id, "is_active": True})), \
         patch("app.api.routes.policies.policy_repo.get_next_version_number", new=AsyncMock(return_value=1)), \
         patch("app.api.routes.policies.policy_repo.list_policy_versions", new=AsyncMock(return_value=[])), \
         patch("app.api.routes.policies.evidence_service.upload_policy_pdf", new=AsyncMock(return_value=("policies/p1/v1_fail", checksum, {"resource_type": "raw"}))), \
         patch("app.api.routes.policies.policy_repo.create_policy_version", new=AsyncMock(return_value=created_ver)), \
         patch("app.api.routes.policies.policy_extractor.extract_from_pdf_bytes", side_effect=ValueError("Corrupt PDF xref")), \
         patch("app.api.routes.policies.extraction_repo.create_extraction", new=extract_save_mock), \
         patch("app.api.routes.policies.audit_repo.log_audit_event", new=audit_mock), \
         patch("app.api.routes.policies.evidence_service.delete_evidence_file", new=delete_mock):
        mock_db.return_value.__aenter__.return_value = AsyncMock()
        res = await upload_policy_version_pdf(
            policy_id=policy_id,
            effective_date=date(2026, 11, 12),
            expiry_date=None,
            version_number=None,
            terms_json=None,
            file=UploadFile(filename="corrupt.pdf", file=io.BytesIO(PDF_VALID), headers={"content-type": "application/pdf"}),
            current_authority=authority,
        )

    assert res["id"] == version_id
    delete_mock.assert_not_called()
    extract_save_mock.assert_awaited_once()
    assert extract_save_mock.call_args.kwargs["status"] == "FAILED"
    assert "ValueError" in extract_save_mock.call_args.kwargs["error_message"]
    actions = [c.kwargs["action"] for c in audit_mock.call_args_list]
    assert "POLICY_PDF_EXTRACTION_FAILED" in actions

    # Retry via PolicyExtractorService.get_or_extract_policy_text updates in place without duplicate versions
    extractor = PolicyExtractorService()
    retry_save_mock = AsyncMock(return_value={"status": "COMPLETED", "extracted_text": "Recovered policy text"})
    with patch("app.services.policy_extractor.extraction_repo.get_extraction_by_version", new=AsyncMock(return_value={
             "id": str(uuid.uuid4()), "policy_version_id": version_id, "status": "FAILED", "extracted_text": None
         })), \
         patch("app.services.policy_extractor.policy_repo.get_policy_version_by_id", new=AsyncMock(return_value=created_ver)), \
         patch.object(extractor, "fetch_document_bytes", new=AsyncMock(return_value=PDF_VALID)), \
         patch.object(extractor, "extract_from_pdf_bytes", return_value=("Recovered policy text " * 3, 1, [{"page_number": 1, "text": "Recovered"}], "COMPLETED")), \
         patch("app.services.policy_extractor.extraction_repo.create_extraction", new=retry_save_mock):
        retried = await extractor.get_or_extract_policy_text(AsyncMock(), version_id)

    assert retried["status"] == "COMPLETED"
    retry_save_mock.assert_awaited_once()
    assert retry_save_mock.call_args.kwargs["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_authority_agent_workflow_e2e(async_client):
    """End-to-end API integration test for Authority agent listing, approval, rejection, token revocation, and RBAC."""
    from app.core.config import get_settings
    from app.services.email_service import EmailService

    settings = get_settings()
    suffix = uuid.uuid4().hex[:8]
    pwd = "Password123!"

    # 1. Bootstrap Approval Authority
    auth_email = f"p3_auth_{suffix}@example.com"
    boot_res = await async_client.post(
        "/api/v1/auth/bootstrap-authority",
        json={
            "email": auth_email,
            "password": pwd,
            "full_name": "Phase3 Authority",
            "bootstrap_secret": settings.AUTHORITY_BOOTSTRAP_SECRET,
        },
    )
    assert boot_res.status_code == 201
    authority_id = boot_res.json()["id"]

    auth_login = await async_client.post("/api/v1/auth/login", json={"email": auth_email, "password": pwd})
    assert auth_login.status_code == 200
    auth_headers = {"Authorization": f"Bearer {auth_login.json()['access_token']}"}

    # 2. Register two agents (PENDING_APPROVAL) and one customer (verified ACTIVE)
    agent1_email = f"p3_agent1_{suffix}@example.com"
    agent2_email = f"p3_agent2_{suffix}@example.com"
    cust_email = f"p3_cust_{suffix}@example.com"

    a1_res = await async_client.post(
        "/api/v1/auth/signup",
        json={"email": agent1_email, "password": pwd, "full_name": "Agent Reject", "role": "INSURANCE_AGENT"},
    )
    a2_res = await async_client.post(
        "/api/v1/auth/signup",
        json={"email": agent2_email, "password": pwd, "full_name": "Agent Approve", "role": "INSURANCE_AGENT"},
    )
    c_res = await async_client.post(
        "/api/v1/auth/signup",
        json={"email": cust_email, "password": pwd, "full_name": "Customer User", "role": "CUSTOMER"},
    )
    assert a1_res.status_code == 201
    assert a2_res.status_code == 201
    assert c_res.status_code == 201
    agent1_id = a1_res.json()["id"]
    agent2_id = a2_res.json()["id"]
    cust_id = c_res.json()["id"]

    cust_tok = [m for m in EmailService.sent_messages if m.to_email == cust_email][-1].token
    assert (await async_client.post("/api/v1/auth/verify-email", json={"token": cust_tok})).status_code == 200
    cust_login = await async_client.post("/api/v1/auth/login", json={"email": cust_email, "password": pwd})
    assert cust_login.status_code == 200
    cust_headers = {"Authorization": f"Bearer {cust_login.json()['access_token']}"}

    # 3. Customer RBAC: cannot list agents or approve accounts
    assert (await async_client.get("/api/v1/auth/agents", headers=cust_headers)).status_code == 403
    assert (
        await async_client.post(
            "/api/v1/auth/approve-account",
            headers=cust_headers,
            json={"user_id": agent1_id, "status": "ACTIVE"},
        )
    ).status_code == 403

    # 4. Authority lists PENDING_APPROVAL agents and sees both new agents
    list_pending = await async_client.get(
        "/api/v1/auth/agents?status_filter=PENDING_APPROVAL&page=1&page_size=50",
        headers=auth_headers,
    )
    assert list_pending.status_code == 200
    pending_ids = {item["id"] for item in list_pending.json()["items"]}
    assert agent1_id in pending_ids
    assert agent2_id in pending_ids

    # 5. Short rejection reason fails (422); valid rejection succeeds and blocks login
    short_reject = await async_client.post(
        "/api/v1/auth/approve-account",
        headers=auth_headers,
        json={"user_id": agent1_id, "status": "REJECTED", "reason": "no"},
    )
    assert short_reject.status_code == 422

    reject_a1 = await async_client.post(
        "/api/v1/auth/approve-account",
        headers=auth_headers,
        json={"user_id": agent1_id, "status": "REJECTED", "reason": "Invalid license documentation"},
    )
    assert reject_a1.status_code == 200
    assert reject_a1.json()["account_status"] == "REJECTED"

    a1_login = await async_client.post("/api/v1/auth/login", json={"email": agent1_email, "password": pwd})
    assert a1_login.status_code == 403

    # 6. Approve agent 2 -> can log in -> later reject agent 2 -> refresh token revoked + login blocked
    approve_a2 = await async_client.post(
        "/api/v1/auth/approve-account",
        headers=auth_headers,
        json={"user_id": agent2_id, "status": "ACTIVE"},
    )
    assert approve_a2.status_code == 200
    assert approve_a2.json()["account_status"] == "ACTIVE"

    a2_login = await async_client.post("/api/v1/auth/login", json={"email": agent2_email, "password": pwd})
    assert a2_login.status_code == 200
    a2_refresh = a2_login.json()["refresh_token"]

    revoke_a2 = await async_client.post(
        "/api/v1/auth/approve-account",
        headers=auth_headers,
        json={"user_id": agent2_id, "status": "REJECTED", "reason": "Compliance audit suspension"},
    )
    assert revoke_a2.status_code == 200
    assert (await async_client.post("/api/v1/auth/refresh", json={"refresh_token": a2_refresh})).status_code == 401
    assert (await async_client.post("/api/v1/auth/login", json={"email": agent2_email, "password": pwd})).status_code == 403

    # 7. Cannot self-approve or modify customer accounts
    assert (
        await async_client.post(
            "/api/v1/auth/approve-account",
            headers=auth_headers,
            json={"user_id": authority_id, "status": "REJECTED", "reason": "Self reject test"},
        )
    ).status_code == 403
    assert (
        await async_client.post(
            "/api/v1/auth/approve-account",
            headers=auth_headers,
            json={"user_id": cust_id, "status": "REJECTED", "reason": "Customer reject test"},
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_authority_policy_workflow_e2e(async_client):
    """End-to-end API integration test for Policy create, draft isolation, PDF upload, signed URL, publish, and RBAC."""
    from app.core.config import get_settings
    from app.services.email_service import EmailService

    settings = get_settings()
    suffix = uuid.uuid4().hex[:8]
    pwd = "Password123!"

    # 1. Bootstrap authority + verified customer
    auth_email = f"p3_pol_auth_{suffix}@example.com"
    cust_email = f"p3_pol_cust_{suffix}@example.com"
    await async_client.post(
        "/api/v1/auth/bootstrap-authority",
        json={
            "email": auth_email,
            "password": pwd,
            "full_name": "Policy Authority",
            "bootstrap_secret": settings.AUTHORITY_BOOTSTRAP_SECRET,
        },
    )
    auth_login = await async_client.post("/api/v1/auth/login", json={"email": auth_email, "password": pwd})
    auth_headers = {"Authorization": f"Bearer {auth_login.json()['access_token']}"}

    await async_client.post(
        "/api/v1/auth/signup",
        json={"email": cust_email, "password": pwd, "full_name": "Policy Customer", "role": "CUSTOMER"},
    )
    cust_tok = [m for m in EmailService.sent_messages if m.to_email == cust_email][-1].token
    await async_client.post("/api/v1/auth/verify-email", json={"token": cust_tok})
    cust_login = await async_client.post("/api/v1/auth/login", json={"email": cust_email, "password": pwd})
    cust_headers = {"Authorization": f"Bearer {cust_login.json()['access_token']}"}

    # 2. Authority creates a new policy
    policy_code = f"P3-{suffix.upper()}"
    create_res = await async_client.post(
        "/api/v1/policies",
        headers=auth_headers,
        json={
            "insurer_name": "VACHAN Test Assurance",
            "policy_name": f"Phase3 Health Shield {suffix}",
            "policy_code": policy_code,
            "category": "MEDICAL",
            "description": "End-to-end Phase 3 verification policy",
            "coverage_limit": 250000.0,
            "waiting_period_days": 30,
            "claim_filing_window_days": 60,
        },
    )
    assert create_res.status_code == 201
    policy_id = create_res.json()["id"]

    # 3. Draft policy is visible in /policies/manage, excluded from public /policies
    manage_res = await async_client.get("/api/v1/policies/manage", headers=auth_headers)
    assert manage_res.status_code == 200
    assert any(p["id"] == policy_id for p in manage_res.json())

    public_before = await async_client.get("/api/v1/policies", headers=cust_headers)
    assert public_before.status_code == 200
    assert all(p["id"] != policy_id for p in public_before.json())

    # Customer cannot access /policies/manage
    assert (await async_client.get("/api/v1/policies/manage", headers=cust_headers)).status_code == 403

    # 4. Authority uploads PDF version (mocking Cloudinary transport while keeping real validation & DB persistence)
    fake_ref = f"policies/{policy_id}/v1_{suffix}"
    fake_signed = f"https://api.cloudinary.com/v1_1/demo/raw/download?public_id={fake_ref}"
    with patch("app.api.routes.policies.evidence_service.upload_policy_pdf", new=AsyncMock(return_value=(fake_ref, "d" * 64, {"resource_type": "raw"}))), \
         patch("app.api.routes.policies.evidence_service.generate_signed_url", new=AsyncMock(return_value=fake_signed)):
        upload_res = await async_client.post(
            f"/api/v1/policies/{policy_id}/versions/upload-pdf",
            headers=auth_headers,
            data={"effective_date": "2026-11-12"},
            files={"file": ("policy.pdf", PDF_VALID, "application/pdf")},
        )
        assert upload_res.status_code == 201
        version_id = upload_res.json()["id"]
        assert upload_res.json()["is_published"] is False

        # Signed URL available for authority, blocked for customer
        doc_url_res = await async_client.get(
            f"/api/v1/policies/{policy_id}/versions/{version_id}/document-url",
            headers=auth_headers,
        )
        assert doc_url_res.status_code == 200
        assert doc_url_res.json()["signed_url"] == fake_signed
        assert doc_url_res.json()["expires_in_seconds"] == 300

        assert (
            await async_client.get(
                f"/api/v1/policies/{policy_id}/versions/{version_id}/document-url",
                headers=cust_headers,
            )
        ).status_code == 403

    # 5. Customer cannot upload or publish; Authority publishes -> now visible in public /policies; re-publish -> 409
    assert (
        await async_client.post(
            f"/api/v1/policies/{policy_id}/versions/{version_id}/publish",
            headers=cust_headers,
        )
    ).status_code == 403

    pub_res = await async_client.post(
        f"/api/v1/policies/{policy_id}/versions/{version_id}/publish",
        headers=auth_headers,
    )
    assert pub_res.status_code == 200
    assert pub_res.json()["is_published"] is True

    repub_res = await async_client.post(
        f"/api/v1/policies/{policy_id}/versions/{version_id}/publish",
        headers=auth_headers,
    )
    assert repub_res.status_code == 409

    public_after = await async_client.get("/api/v1/policies", headers=cust_headers)
    assert public_after.status_code == 200
    assert any(p["id"] == policy_id for p in public_after.json())
