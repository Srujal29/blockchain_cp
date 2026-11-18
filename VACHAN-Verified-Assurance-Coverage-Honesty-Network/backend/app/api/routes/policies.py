"""
Policy catalogue and version management endpoints.
Enforces authority permissions for creation and publishing.
"""

from datetime import date
import json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from app.api.deps import get_current_active_user, require_active_authority
from app.core.config import get_settings
from app.core.exceptions import (
    AuthorizationException,
    ConflictException,
    ResourceNotFoundException,
    ValidationException,
)
from app.core.logging import get_logger
from app.core.security import UserRole, validate_uuid
from app.db.connection import get_db_connection
from app.db.repositories import audit_repo, extraction_repo, policy_repo
from app.schemas.policy import (
    AuthorityPolicyManageResponse,
    CreatePolicyRequest,
    CreatePolicyVersionRequest,
    PolicyDocumentUrlResponse,
    PolicyResponse,
    PolicyVersionResponse,
)
from app.services.evidence_service import evidence_service
from app.services.policy_extractor import PolicyExtractorService

policy_extractor = PolicyExtractorService()

logger = get_logger(__name__)
router = APIRouter(prefix="/policies", tags=["Policy Catalogue"])


@router.get("", response_model=List[PolicyResponse])
async def list_active_policies(
    category: Optional[str] = Query(default=None),
) -> List[Dict[str, Any]]:
    """Lists active insurance policies that have at least one published version."""
    async with get_db_connection() as conn:
        policies = await policy_repo.list_policies(conn, category=category, is_active=True)
        version_query = f"""
        SELECT DISTINCT ON (policy_id) {policy_repo.VERSION_FIELDS}
        FROM policy_versions
        WHERE is_published = TRUE
        ORDER BY policy_id, version_number DESC;
        """
        async with conn.cursor() as cur:
            await cur.execute(version_query)
            version_rows = await cur.fetchall()
            version_map = {str(r[1]): policy_repo._row_to_version_dict(r) for r in version_rows}

        results = []
        for p in policies:
            latest_ver = version_map.get(str(p["id"]))
            if latest_ver is None:
                continue  # Never leak draft-only policies to customers or agents
            p_dict = dict(p)
            p_dict["latest_version"] = latest_ver
            results.append(p_dict)
        return results


@router.get("/manage", response_model=List[AuthorityPolicyManageResponse])
async def manage_list_policies(
    category: Optional[str] = Query(default=None),
    is_active: Optional[bool] = Query(default=None),
    current_authority: Dict[str, Any] = Depends(require_active_authority),
) -> List[Dict[str, Any]]:
    """Authority-only listing of all policies (draft and published) with all versions."""
    async with get_db_connection() as conn:
        policies = await policy_repo.list_policies(conn, category=category, is_active=is_active)
        all_versions_sql = f"""
        SELECT {policy_repo.VERSION_FIELDS}
        FROM policy_versions
        ORDER BY policy_id, version_number DESC;
        """
        async with conn.cursor() as cur:
            await cur.execute(all_versions_sql)
            version_rows = await cur.fetchall()

        versions_by_policy: Dict[str, List[Dict[str, Any]]] = {}
        for r in version_rows:
            v = policy_repo._row_to_version_dict(r)
            versions_by_policy.setdefault(v["policy_id"], []).append(v)

        results = []
        for p in policies:
            p_dict = dict(p)
            versions = versions_by_policy.get(str(p["id"]), [])
            published = [v for v in versions if v.get("is_published")]
            p_dict["latest_version"] = published[0] if published else None
            p_dict["versions"] = versions
            results.append(p_dict)
        return results


@router.get("/{policy_id}/manage", response_model=AuthorityPolicyManageResponse)
async def manage_get_policy_detail(
    policy_id: str,
    current_authority: Dict[str, Any] = Depends(require_active_authority),
) -> Dict[str, Any]:
    """Authority-only policy detail including all draft and published versions."""
    policy_id = validate_uuid(policy_id, "policy_id")
    async with get_db_connection() as conn:
        policy = await policy_repo.get_policy_by_id(conn, policy_id)
        if not policy:
            raise ResourceNotFoundException("Policy not found.")

        versions = await policy_repo.list_policy_versions(conn, policy_id)
        published = [v for v in versions if v.get("is_published")]
        p_dict = dict(policy)
        p_dict["latest_version"] = published[0] if published else None
        p_dict["versions"] = versions
        return p_dict


@router.get("/{policy_id}", response_model=PolicyResponse)
async def get_policy_detail(
    policy_id: str,
) -> Dict[str, Any]:
    """Retrieves policy details and published terms."""
    policy_id = validate_uuid(policy_id, "policy_id")
    async with get_db_connection() as conn:
        policy = await policy_repo.get_policy_by_id(conn, policy_id)
        if not policy:
            raise ResourceNotFoundException("Policy not found.")

        latest_version = await policy_repo.get_published_version(conn, policy_id)
        policy_dict = dict(policy)
        policy_dict["latest_version"] = latest_version
        return policy_dict


@router.post("", response_model=PolicyResponse, status_code=status.HTTP_201_CREATED)
async def create_new_policy(
    body: CreatePolicyRequest,
    current_authority: Dict[str, Any] = Depends(require_active_authority),
) -> Dict[str, Any]:
    """Authority-only endpoint to define a new policy scheme."""
    async with get_db_connection() as conn:
        existing = await policy_repo.get_policy_by_code(conn, body.policy_code)
        if existing:
            raise ConflictException(f"Policy with code '{body.policy_code}' already exists.")

        policy = await policy_repo.create_policy(
            conn=conn,
            insurer_name=body.insurer_name,
            policy_name=body.policy_name,
            policy_code=body.policy_code,
            category=body.category.value,
            description=body.description,
            coverage_limit=body.coverage_limit,
            waiting_period_days=body.waiting_period_days,
            claim_filing_window_days=body.claim_filing_window_days,
            created_by=current_authority["id"],
        )

        await audit_repo.log_audit_event(
            conn=conn,
            actor_id=current_authority["id"],
            actor_role=current_authority["role"],
            action="CREATE_POLICY",
            target_type="policy",
            target_id=policy["id"],
            metadata={"code": body.policy_code, "category": body.category.value},
        )

        return policy


@router.post("/{policy_id}/versions", response_model=PolicyVersionResponse, status_code=status.HTTP_201_CREATED)
async def create_policy_version(
    policy_id: str,
    body: CreatePolicyVersionRequest,
    current_authority: Dict[str, Any] = Depends(require_active_authority),
) -> Dict[str, Any]:
    """Authority-only endpoint to upload versioned terms and document checksum."""
    policy_id = validate_uuid(policy_id, "policy_id")
    async with get_db_connection() as conn:
        policy = await policy_repo.get_policy_by_id(conn, policy_id)
        if not policy:
            raise ResourceNotFoundException("Policy not found.")

        version = await policy_repo.create_policy_version(
            conn=conn,
            policy_id=policy_id,
            version_number=body.version_number,
            document_storage_ref=body.document_storage_ref,
            document_checksum=body.document_checksum,
            effective_date=body.effective_date,
            expiry_date=body.expiry_date,
            terms_json=body.terms_json,
        )

        await audit_repo.log_audit_event(
            conn=conn,
            actor_id=current_authority["id"],
            actor_role=current_authority["role"],
            action="CREATE_POLICY_VERSION",
            target_type="policy_version",
            target_id=version["id"],
            metadata={"policy_id": policy_id, "version": body.version_number},
        )

        return version


@router.post(
    "/{policy_id}/versions/upload-pdf",
    response_model=PolicyVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_policy_version_pdf(
    policy_id: str,
    effective_date: date = Form(...),
    expiry_date: Optional[date] = Form(default=None),
    version_number: Optional[int] = Form(default=None),
    terms_json: Optional[str] = Form(default=None),
    file: UploadFile = File(...),
    current_authority: Dict[str, Any] = Depends(require_active_authority),
) -> Dict[str, Any]:
    """
    Authority-only multipart PDF upload that creates a new draft policy version.
    Validates PDF magic bytes & size, calculates SHA-256 on backend, stores privately
    in Cloudinary, extracts PDF text, and performs compensating cleanup on DB failure.
    """
    policy_id = validate_uuid(policy_id, "policy_id")
    if expiry_date is not None and expiry_date <= effective_date:
        raise ValidationException("Expiry date must be after effective date.")

    parsed_terms: Dict[str, Any] = {}
    if terms_json and terms_json.strip():
        try:
            loaded = json.loads(terms_json)
            if not isinstance(loaded, dict):
                raise ValueError("terms_json must be a JSON object")
            parsed_terms = loaded
        except Exception as exc:
            raise ValidationException("terms_json must be a valid JSON object.") from exc

    settings = get_settings()
    content = await file.read(settings.MAX_EVIDENCE_FILE_SIZE_BYTES + 1)
    filename = file.filename or "policy_document.pdf"
    declared_mime = file.content_type or "application/pdf"

    async with get_db_connection() as conn:
        await policy_repo.lock_policy_for_versioning(conn, policy_id)
        policy = await policy_repo.get_policy_by_id(conn, policy_id)
        if not policy:
            raise ResourceNotFoundException("Policy not found.")

        target_version = version_number if version_number is not None else await policy_repo.get_next_version_number(conn, policy_id)
        if target_version <= 0:
            raise ValidationException("Version number must be positive.")

        existing_versions = await policy_repo.list_policy_versions(conn, policy_id)
        if any(v["version_number"] == target_version for v in existing_versions):
            raise ConflictException(f"Version {target_version} already exists for this policy.")

        storage_ref, checksum, metadata = await evidence_service.upload_policy_pdf(
            policy_id=policy_id,
            version_number=target_version,
            filename=filename,
            content=content,
            declared_mime=declared_mime,
        )

        try:
            version = await policy_repo.create_policy_version(
                conn=conn,
                policy_id=policy_id,
                version_number=target_version,
                document_storage_ref=storage_ref,
                document_checksum=checksum,
                effective_date=effective_date,
                expiry_date=expiry_date,
                terms_json=parsed_terms,
            )

            # Extract PDF text non-destructively for grounded Gemini verification
            try:
                text, page_count, pages_data, ext_status = policy_extractor.extract_from_pdf_bytes(content)
                ext_error_msg = (
                    "PDF contains insufficient digital text (scanned image or empty). Review required."
                    if ext_status == "NEEDS_REVIEW"
                    else None
                )
                await extraction_repo.create_extraction(
                    conn=conn,
                    policy_version_id=version["id"],
                    document_checksum=checksum,
                    status=ext_status,
                    extracted_text=text,
                    page_count=page_count,
                    pages_json=pages_data,
                    error_message=ext_error_msg,
                )
                await audit_repo.log_audit_event(
                    conn=conn,
                    actor_id=current_authority["id"],
                    actor_role=current_authority["role"],
                    action="POLICY_PDF_EXTRACTED",
                    target_type="policy_version",
                    target_id=version["id"],
                    metadata={
                        "policy_id": policy_id,
                        "status": ext_status,
                        "page_count": page_count,
                    },
                )
            except Exception as ext_exc:
                err_name = type(ext_exc).__name__
                logger.warning(
                    "Policy PDF extraction failed for version %s: %s",
                    version["id"],
                    err_name,
                )
                await extraction_repo.create_extraction(
                    conn=conn,
                    policy_version_id=version["id"],
                    document_checksum=checksum,
                    status="FAILED",
                    extracted_text=None,
                    page_count=0,
                    pages_json=None,
                    error_message=f"PDF extraction failed: {err_name}",
                )
                await audit_repo.log_audit_event(
                    conn=conn,
                    actor_id=current_authority["id"],
                    actor_role=current_authority["role"],
                    action="POLICY_PDF_EXTRACTION_FAILED",
                    target_type="policy_version",
                    target_id=version["id"],
                    metadata={
                        "policy_id": policy_id,
                        "status": "FAILED",
                        "error_type": err_name,
                    },
                )

            await audit_repo.log_audit_event(
                conn=conn,
                actor_id=current_authority["id"],
                actor_role=current_authority["role"],
                action="UPLOAD_POLICY_DOCUMENT",
                target_type="policy_version",
                target_id=version["id"],
                metadata={
                    "policy_id": policy_id,
                    "version_number": target_version,
                    "checksum": checksum,
                    "file_size": len(content),
                },
            )
            await audit_repo.log_audit_event(
                conn=conn,
                actor_id=current_authority["id"],
                actor_role=current_authority["role"],
                action="CREATE_POLICY_VERSION",
                target_type="policy_version",
                target_id=version["id"],
                metadata={"policy_id": policy_id, "version": target_version},
            )

            return version

        except Exception as exc:
            await evidence_service.delete_evidence_file(storage_ref, resource_type="raw")
            raise exc


@router.get(
    "/{policy_id}/versions/{version_id}/published-document-url",
    response_model=PolicyDocumentUrlResponse,
)
async def get_published_policy_version_document_url(
    policy_id: str,
    version_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """
    Authenticated customer endpoint to retrieve a short-lived (300s) signed URL
    for an active published policy version document in private Cloudinary storage.
    Strictly forbids access to draft or unpublished policy versions.
    """
    if current_user.get("role") not in [UserRole.CUSTOMER.value, UserRole.APPROVAL_AUTHORITY.value]:
        raise AuthorizationException("Access restricted to customers and approval authorities.")

    policy_id = validate_uuid(policy_id, "policy_id")
    version_id = validate_uuid(version_id, "version_id")
    async with get_db_connection() as conn:
        # 1. Verify policy exists and is active
        policy = await policy_repo.get_policy_by_id(conn, policy_id)
        if not policy:
            raise ResourceNotFoundException("Policy not found.")
        if not policy.get("is_active"):
            raise ValidationException("The requested policy is inactive or unavailable.")

        # 2. Verify version exists, belongs to policy, and is published
        version = await policy_repo.get_policy_version_by_id(conn, version_id)
        if not version or version["policy_id"] != policy_id:
            raise ResourceNotFoundException("Policy version not found.")

        if not version.get("is_published"):
            raise AuthorizationException("Cannot access unpublished draft policy versions.")

        storage_ref = (version.get("document_storage_ref") or "").strip()
        if not storage_ref:
            raise ValidationException("Policy document is not available for this version.")

        expires_in = 300
        signed_url = await evidence_service.generate_signed_url(
            document_storage_ref=storage_ref,
            mime_type="application/pdf",
            expires_in_seconds=expires_in,
        )

        # 3. Audit log document access without recording sensitive signed URLs
        await audit_repo.log_audit_event(
            conn=conn,
            actor_id=current_user["id"],
            actor_role=current_user["role"],
            action="CUSTOMER_ACCESS_POLICY_DOCUMENT",
            target_type="policy_version",
            target_id=version_id,
            metadata={
                "policy_id": policy_id,
                "version_number": version["version_number"],
            },
        )

        return {
            "policy_id": policy_id,
            "version_id": version_id,
            "signed_url": signed_url,
            "expires_in_seconds": expires_in,
        }


@router.get(
    "/{policy_id}/published-document-url",
    response_model=PolicyDocumentUrlResponse,
)
async def get_latest_published_policy_document_url(
    policy_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """
    Convenience endpoint to retrieve the signed URL for the latest published version of a policy.
    """
    if current_user.get("role") not in [UserRole.CUSTOMER.value, UserRole.APPROVAL_AUTHORITY.value]:
        raise AuthorizationException("Access restricted to customers and approval authorities.")

    policy_id = validate_uuid(policy_id, "policy_id")
    async with get_db_connection() as conn:
        policy = await policy_repo.get_policy_by_id(conn, policy_id)
        if not policy:
            raise ResourceNotFoundException("Policy not found.")
        if not policy.get("is_active"):
            raise ValidationException("The requested policy is inactive or unavailable.")

        latest_version = await policy_repo.get_published_version(conn, policy_id)
        if not latest_version:
            raise ResourceNotFoundException("No published version available for this policy.")

    return await get_published_policy_version_document_url(
        policy_id=policy_id,
        version_id=latest_version["id"],
        current_user=current_user,
    )


@router.get(
    "/{policy_id}/versions/{version_id}/document-url",
    response_model=PolicyDocumentUrlResponse,
)
async def get_policy_version_document_url(
    policy_id: str,
    version_id: str,
    current_authority: Dict[str, Any] = Depends(require_active_authority),
) -> Dict[str, Any]:
    """Authority-only 300s signed URL to preview a policy version PDF."""
    policy_id = validate_uuid(policy_id, "policy_id")
    version_id = validate_uuid(version_id, "version_id")
    async with get_db_connection() as conn:
        version = await policy_repo.get_policy_version_by_id(conn, version_id)
        if not version or version["policy_id"] != policy_id:
            raise ResourceNotFoundException("Policy version not found.")

        storage_ref = version.get("document_storage_ref") or ""
        if not storage_ref:
            raise ValidationException("Policy version does not have an uploaded document.")

        expires_in = 300
        signed_url = await evidence_service.generate_signed_url(
            document_storage_ref=storage_ref,
            mime_type="application/pdf",
            expires_in_seconds=expires_in,
        )
        return {
            "policy_id": policy_id,
            "version_id": version_id,
            "signed_url": signed_url,
            "expires_in_seconds": expires_in,
        }


@router.post("/{policy_id}/versions/{version_id}/publish", response_model=PolicyVersionResponse)
async def publish_policy_version(
    policy_id: str,
    version_id: str,
    current_authority: Dict[str, Any] = Depends(require_active_authority),
) -> Dict[str, Any]:
    """Authority-only endpoint to publish a draft policy version after strict validation."""
    policy_id = validate_uuid(policy_id, "policy_id")
    version_id = validate_uuid(version_id, "version_id")
    async with get_db_connection() as conn:
        await policy_repo.lock_policy_for_versioning(conn, policy_id)
        policy = await policy_repo.get_policy_by_id(conn, policy_id)
        if not policy:
            raise ResourceNotFoundException("Policy not found.")
        if not policy.get("is_active"):
            raise ValidationException("Cannot publish a version for an inactive policy.")

        version = await policy_repo.get_policy_version_by_id(conn, version_id)
        if not version or version["policy_id"] != policy_id:
            raise ResourceNotFoundException("Policy version not found.")
        if version.get("is_published"):
            raise ConflictException("Policy version is already published and immutable.")

        storage_ref = (version.get("document_storage_ref") or "").strip()
        checksum = (version.get("document_checksum") or "").strip()
        if not storage_ref or len(checksum) != 64:
            raise ValidationException(
                "Policy version must have an uploaded PDF document and valid SHA-256 checksum before publishing."
            )
        if not version.get("effective_date"):
            raise ValidationException("Policy version must have an effective date before publishing.")
        if version.get("expiry_date") and version["expiry_date"] <= version["effective_date"]:
            raise ValidationException("Policy version expiry date must be after effective date.")

        published = await policy_repo.publish_policy_version(
            conn=conn, version_id=version_id, published_by=current_authority["id"]
        )
        if not published:
            raise ResourceNotFoundException("Failed to publish version.")

        await audit_repo.log_audit_event(
            conn=conn,
            actor_id=current_authority["id"],
            actor_role=current_authority["role"],
            action="PUBLISH_POLICY_VERSION",
            target_type="policy_version",
            target_id=version_id,
            metadata={"policy_id": policy_id, "version": version["version_number"]},
        )

        return published
