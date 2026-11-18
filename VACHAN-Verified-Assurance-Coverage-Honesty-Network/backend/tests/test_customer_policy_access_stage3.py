"""
Phase 4 — Stage 3 Backend Tests:
Customer Published Policy PDF Access, Hardcoded Identity Removals, and Mock Evidence Removal.
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import httpx
import pytest

from app.core.exceptions import (
    AuthorizationException,
    IntegrationException,
    NotFoundException,
    ResourceNotFoundException,
    ValidationException,
)
from app.core.security import PolicyCategory, UserRole
from app.services.evidence_service import EvidenceStorageService


@pytest.mark.asyncio
async def test_customer_published_policy_document_access_success():
    """Authenticated customer can retrieve signed URL for published policy version document."""
    from app.api.routes.policies import get_published_policy_version_document_url

    cust_user = {"id": str(uuid.uuid4()), "role": UserRole.CUSTOMER.value}
    policy_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())

    mock_policy = {
        "id": policy_id,
        "is_active": True,
        "policy_name": "Care Health Guard",
    }
    mock_version = {
        "id": version_id,
        "policy_id": policy_id,
        "version_number": 1,
        "is_published": True,
        "document_storage_ref": f"policies/{policy_id}/v1_doc",
    }

    audit_mock = AsyncMock()

    with patch("app.api.routes.policies.get_db_connection") as mock_db, \
         patch("app.db.repositories.policy_repo.get_policy_by_id", new=AsyncMock(return_value=mock_policy)), \
         patch("app.db.repositories.policy_repo.get_policy_version_by_id", new=AsyncMock(return_value=mock_version)), \
         patch("app.api.routes.policies.evidence_service.generate_signed_url", new=AsyncMock(return_value="https://api.cloudinary.com/signed/doc.pdf")), \
         patch("app.db.repositories.audit_repo.log_audit_event", new=audit_mock):
        mock_db.return_value.__aenter__.return_value = AsyncMock()
        res = await get_published_policy_version_document_url(
            policy_id=policy_id,
            version_id=version_id,
            current_user=cust_user,
        )

    assert res["policy_id"] == policy_id
    assert res["version_id"] == version_id
    assert res["signed_url"] == "https://api.cloudinary.com/signed/doc.pdf"
    assert res["expires_in_seconds"] == 300

    # Verify audit event is logged with actor ID and NO sensitive signed URL in metadata
    audit_mock.assert_awaited_once()
    call_kwargs = audit_mock.call_args.kwargs
    assert call_kwargs["actor_id"] == cust_user["id"]
    assert call_kwargs["action"] == "CUSTOMER_ACCESS_POLICY_DOCUMENT"
    assert "signed_url" not in call_kwargs["metadata"]


@pytest.mark.asyncio
async def test_customer_cannot_access_unpublished_draft_or_foreign_version():
    """Unpublished draft policy versions and versions belonging to another policy are blocked."""
    from app.api.routes.policies import get_published_policy_version_document_url

    cust_user = {"id": str(uuid.uuid4()), "role": UserRole.CUSTOMER.value}
    policy_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())

    mock_policy = {"id": policy_id, "is_active": True}

    # 1. Unpublished draft version raises AuthorizationException
    draft_version = {
        "id": version_id,
        "policy_id": policy_id,
        "version_number": 2,
        "is_published": False,
        "document_storage_ref": "ref",
    }
    with patch("app.api.routes.policies.get_db_connection") as mock_db, \
         patch("app.db.repositories.policy_repo.get_policy_by_id", new=AsyncMock(return_value=mock_policy)), \
         patch("app.db.repositories.policy_repo.get_policy_version_by_id", new=AsyncMock(return_value=draft_version)):
        mock_db.return_value.__aenter__.return_value = AsyncMock()
        with pytest.raises(AuthorizationException, match="Cannot access unpublished draft"):
            await get_published_policy_version_document_url(policy_id, version_id, cust_user)

    # 2. Version belonging to another policy raises ResourceNotFoundException
    foreign_version = {
        "id": version_id,
        "policy_id": str(uuid.uuid4()),
        "is_published": True,
        "document_storage_ref": "ref",
    }
    with patch("app.api.routes.policies.get_db_connection") as mock_db, \
         patch("app.db.repositories.policy_repo.get_policy_by_id", new=AsyncMock(return_value=mock_policy)), \
         patch("app.db.repositories.policy_repo.get_policy_version_by_id", new=AsyncMock(return_value=foreign_version)):
        mock_db.return_value.__aenter__.return_value = AsyncMock()
        with pytest.raises(ResourceNotFoundException):
            await get_published_policy_version_document_url(policy_id, version_id, cust_user)

    # 3. Nonexistent policy raises ResourceNotFoundException
    with patch("app.api.routes.policies.get_db_connection") as mock_db, \
         patch("app.db.repositories.policy_repo.get_policy_by_id", new=AsyncMock(return_value=None)):
        mock_db.return_value.__aenter__.return_value = AsyncMock()
        with pytest.raises(ResourceNotFoundException):
            await get_published_policy_version_document_url(policy_id, version_id, cust_user)

    # 4. Unauthorized role (e.g. INSURANCE_AGENT) raises AuthorizationException
    agent_user = {"id": str(uuid.uuid4()), "role": UserRole.INSURANCE_AGENT.value}
    with pytest.raises(AuthorizationException, match="Access restricted to customers and approval authorities"):
        await get_published_policy_version_document_url(policy_id, version_id, agent_user)


@pytest.mark.asyncio
async def test_hardcoded_identity_removal_in_sales_sessions():
    """Sales session creation rejects missing customer and nonexistent customer without hardcoded fallbacks."""
    from app.api.routes.sales_sessions import create_sales_session
    from app.schemas.sales_session import CreateSalesSessionRequest

    agent = {"id": str(uuid.uuid4()), "role": UserRole.INSURANCE_AGENT.value}

    # 1. Missing both customer_id and customer_email raises ValidationException (never falls back to hardcoded UUID)
    req_empty = CreateSalesSessionRequest(
        audio_storage_ref="sales_sessions/test/rec.m4a",
        audio_mime_type="audio/m4a",
        audio_file_size_bytes=1000,
        audio_checksum="a" * 64,
        customer_consent=True,
    )
    with patch("app.api.routes.sales_sessions.get_db_connection") as mock_db:
        mock_db.return_value.__aenter__.return_value = AsyncMock()
        with pytest.raises(ValidationException, match="Customer identification .* is required"):
            await create_sales_session(req_empty, current_user=agent)

    # 2. Nonexistent customer_email raises ValidationException (never auto-creates customer with password123)
    req_email = CreateSalesSessionRequest(
        customer_email="ghost@example.com",
        audio_storage_ref="sales_sessions/test/rec.m4a",
        audio_mime_type="audio/m4a",
        audio_file_size_bytes=1000,
        audio_checksum="a" * 64,
        customer_consent=True,
    )
    with patch("app.api.routes.sales_sessions.get_db_connection") as mock_db, \
         patch("app.db.repositories.user_repo.get_user_by_email", new=AsyncMock(return_value=None)):
        mock_db.return_value.__aenter__.return_value = AsyncMock()
        with pytest.raises(ValidationException, match="does not exist"):
            await create_sales_session(req_email, current_user=agent)


@pytest.mark.asyncio
async def test_latest_published_document_url_rbac_and_authority_access():
    """Validates authority access, latest published lookup, and agent rejection on latest endpoint."""
    from app.api.routes.policies import (
        get_latest_published_policy_document_url,
        get_published_policy_version_document_url,
    )

    auth_user = {"id": str(uuid.uuid4()), "role": UserRole.APPROVAL_AUTHORITY.value}
    cust_user = {"id": str(uuid.uuid4()), "role": UserRole.CUSTOMER.value}
    agent_user = {"id": str(uuid.uuid4()), "role": UserRole.INSURANCE_AGENT.value}
    policy_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())

    mock_policy = {"id": policy_id, "is_active": True, "policy_name": "Care Health Guard"}
    mock_version = {
        "id": version_id,
        "policy_id": policy_id,
        "version_number": 1,
        "is_published": True,
        "document_storage_ref": f"policies/{policy_id}/v1_doc",
    }

    # 1. Authority can access version-specific document URL
    with patch("app.api.routes.policies.get_db_connection") as mock_db, \
         patch("app.db.repositories.policy_repo.get_policy_by_id", new=AsyncMock(return_value=mock_policy)), \
         patch("app.db.repositories.policy_repo.get_policy_version_by_id", new=AsyncMock(return_value=mock_version)), \
         patch("app.api.routes.policies.evidence_service.generate_signed_url", new=AsyncMock(return_value="https://api.cloudinary.com/signed/auth.pdf")), \
         patch("app.db.repositories.audit_repo.log_audit_event", new=AsyncMock()):
        mock_db.return_value.__aenter__.return_value = AsyncMock()
        res = await get_published_policy_version_document_url(policy_id, version_id, auth_user)
        assert res["signed_url"] == "https://api.cloudinary.com/signed/auth.pdf"

    # 2. Customer can access latest published document URL
    with patch("app.api.routes.policies.get_db_connection") as mock_db, \
         patch("app.db.repositories.policy_repo.get_policy_by_id", new=AsyncMock(return_value=mock_policy)), \
         patch("app.db.repositories.policy_repo.get_published_version", new=AsyncMock(return_value=mock_version)), \
         patch("app.db.repositories.policy_repo.get_policy_version_by_id", new=AsyncMock(return_value=mock_version)), \
         patch("app.api.routes.policies.evidence_service.generate_signed_url", new=AsyncMock(return_value="https://api.cloudinary.com/signed/latest.pdf")), \
         patch("app.db.repositories.audit_repo.log_audit_event", new=AsyncMock()):
        mock_db.return_value.__aenter__.return_value = AsyncMock()
        res_latest = await get_latest_published_policy_document_url(policy_id, cust_user)
        assert res_latest["signed_url"] == "https://api.cloudinary.com/signed/latest.pdf"

    # 3. Agent is strictly rejected on latest published document URL (403)
    with pytest.raises(AuthorizationException, match="Access restricted to customers and approval authorities"):
        await get_latest_published_policy_document_url(policy_id, agent_user)


@pytest.mark.asyncio
async def test_policy_document_http_unauthenticated_and_agent_rejection(async_client: httpx.AsyncClient):
    """HTTP integration tests: unauthenticated returns 401, agent returns 403 on both endpoints."""
    from app.core.security import create_access_token

    policy_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())

    # 1. Unauthenticated requests return 401 Unauthorized
    resp_v_unauth = await async_client.get(f"/api/v1/policies/{policy_id}/versions/{version_id}/published-document-url")
    assert resp_v_unauth.status_code == 401

    resp_latest_unauth = await async_client.get(f"/api/v1/policies/{policy_id}/published-document-url")
    assert resp_latest_unauth.status_code == 401

    # 2. Agent token returns 403 Forbidden
    agent_id = str(uuid.uuid4())
    agent_token = create_access_token({"sub": agent_id, "role": UserRole.INSURANCE_AGENT.value, "email": "agent@example.com"})
    agent_headers = {"Authorization": f"Bearer {agent_token}"}

    # Mock user retrieval so auth dependency passes active agent check
    mock_agent_db_user = {
        "id": agent_id,
        "email": "agent@example.com",
        "role": UserRole.INSURANCE_AGENT.value,
        "account_status": "ACTIVE",
    }
    with patch("app.api.deps.get_db_connection") as mock_db, \
         patch("app.db.repositories.user_repo.get_user_by_id", new=AsyncMock(return_value=mock_agent_db_user)):
        mock_db.return_value.__aenter__.return_value = AsyncMock()

        resp_v_agent = await async_client.get(
            f"/api/v1/policies/{policy_id}/versions/{version_id}/published-document-url",
            headers=agent_headers,
        )
        assert resp_v_agent.status_code == 403

        resp_latest_agent = await async_client.get(
            f"/api/v1/policies/{policy_id}/published-document-url",
            headers=agent_headers,
        )
        assert resp_latest_agent.status_code == 403


@pytest.mark.asyncio
async def test_mock_evidence_behavior_removed():
    """EvidenceStorageService raises IntegrationException when Cloudinary is unconfigured (no mock: True)."""
    svc = EvidenceStorageService()
    svc._is_configured = False

    # 1. upload_evidence raises IntegrationException when unconfigured
    with pytest.raises(IntegrationException, match="Cloudinary storage is not configured"):
        await svc.upload_evidence("c-1", "bill.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")

    # 2. upload_policy_pdf raises IntegrationException when unconfigured
    with pytest.raises(IntegrationException, match="Cloudinary storage is not configured"):
        await svc.upload_policy_pdf("p-1", 1, "terms.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")

    # 3. generate_signed_url raises IntegrationException when unconfigured
    with pytest.raises(IntegrationException, match="Cloudinary storage is not configured"):
        await svc.generate_signed_url("policies/p1/v1", "application/pdf")
