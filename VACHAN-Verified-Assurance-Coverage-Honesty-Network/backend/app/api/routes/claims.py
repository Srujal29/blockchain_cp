"""
Claims Engine API routes for InsureChain VoiceGuard.
Provides authenticated claim submission, secure evidence management with Cloudinary,
deterministic eligibility evaluation, duplicate detection, and strictly audited lifecycle transitions.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
import psycopg

from app.api.deps import (
    get_current_active_user,
    require_active_authority,
    require_active_customer,
)
from app.core.config import get_settings
from app.core.exceptions import (
    AuthorizationException,
    ConflictException,
    NotFoundException,
    ValidationException,
)
from app.core.logging import get_logger
from app.core.security import (
    ClaimCategory,
    ClaimStatus,
    EvidenceType,
    UserRole,
)
from app.db.connection import get_db_connection
from app.db.repositories import (
    assessment_repo,
    audit_repo,
    claim_evidence_repo,
    claim_repo,
    evidence_analysis_repo,
    policy_repo,
    registration_repo,
)
from app.schemas.claim import (
    ClaimAssessmentResponse,
    ClaimDetailResponse,
    ClaimEvidenceResponse,
    ClaimResponse,
    ClaimStatusHistoryResponse,
    CreateClaimRequest,
    DuplicateCandidateResponse,
    DuplicateCandidatesListResponse,
    SignedUrlResponse,
    TransitionStatusRequest,
)
from app.schemas.evidence_analysis import (
    EvidenceAnalysisListResponse,
    EvidenceAnalysisReportResponse,
)
from app.schemas.voice_assistant import ClaimSpokenExplanationResponse
from app.services.claim_lifecycle import claim_lifecycle_service
from app.services.duplicate_detector import duplicate_detector
from app.services.eligibility_engine import eligibility_engine
from app.services.evidence_analysis_service import evidence_analysis_service
from app.services.evidence_service import compute_sha256, evidence_service, validate_file
from app.services.voice_assistant import voice_assistant_service

logger = get_logger(__name__)

router = APIRouter(prefix="/claims", tags=["Claims Engine"])


async def _verify_claim_access(
    conn: psycopg.AsyncConnection,
    claim_id: str,
    user: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Retrieves claim and validates caller access permissions.
    - CUSTOMER: must be owner.
    - INSURANCE_AGENT: must be registering agent.
    - APPROVAL_AUTHORITY: unrestricted.
    Raises NotFoundException without leaking existence if unauthorized.
    """
    import uuid
    try:
        uuid.UUID(str(claim_id))
    except (ValueError, TypeError):
        raise NotFoundException("Claim not found.")

    claim = await claim_repo.get_claim_by_id(conn, claim_id)
    if not claim:
        raise NotFoundException("Claim not found.")

    user_role = user.get("role")
    user_id = user.get("id")

    if user_role == UserRole.APPROVAL_AUTHORITY.value:
        return claim

    if user_role == UserRole.CUSTOMER.value:
        if claim["customer_id"] != user_id:
            raise NotFoundException("Claim not found.")
        return claim

    if user_role == UserRole.INSURANCE_AGENT.value:
        reg = await registration_repo.get_registration_by_id(conn, claim["registration_id"])
        if not reg or reg["agent_id"] != user_id:
            raise NotFoundException("Claim not found.")
        return claim

    raise AuthorizationException("Access denied to claim resource.")


# ==============================================================================
# 1. Claim Submission and Listing
# ==============================================================================

@router.post("", response_model=ClaimResponse, status_code=status.HTTP_201_CREATED)
async def submit_claim(
    payload: CreateClaimRequest,
    current_user: Dict[str, Any] = Depends(require_active_customer),
) -> Dict[str, Any]:
    """
    Submits a new insurance claim against a confirmed policy registration.
    Restricted to customers holding active registrations.
    """
    async with get_db_connection() as conn:
        # 1. Validate policy registration
        reg = await registration_repo.get_registration_by_id(conn, payload.registration_id)
        if not reg:
            raise NotFoundException("Policy registration not found.")

        # Ensure customer owns the registration
        if reg["customer_id"] != current_user["id"]:
            raise AuthorizationException("You are not authorized to file claims against this policy registration.")

        # Ensure registration is CONFIRMED
        if reg["status"] != "CONFIRMED":
            raise ConflictException(
                f"Claims can only be filed against CONFIRMED policy registrations (current status: {reg['status']})."
            )

        # 2. Validate policy and published version
        policy = await policy_repo.get_policy_by_id(conn, reg["policy_id"])
        if not policy or not policy.get("is_active"):
            raise ValidationException("The associated policy is not currently active.")

        policy_version = await policy_repo.get_policy_version_id(conn, reg["policy_version_id"]) if hasattr(policy_repo, "get_policy_version_id") else await policy_repo.get_policy_version_by_id(conn, reg["policy_version_id"])
        if not policy_version or not policy_version.get("is_published"):
            raise ValidationException("The associated policy version is not published.")

        # 3. Create claim record
        claim = await claim_repo.create_claim(
            conn=conn,
            customer_id=current_user["id"],
            registration_id=reg["id"],
            policy_id=policy["id"],
            policy_version_id=policy_version["id"],
            claim_category=payload.claim_category.value,
            requested_amount=payload.requested_amount,
            incident_date=payload.incident_date,
            description=payload.description,
            structured_details=payload.structured_details,
        )

        # Record initial status history
        await audit_repo.log_audit_event(
            conn=conn,
            actor_id=current_user["id"],
            actor_role=current_user["role"],
            action="CLAIM_CREATED",
            target_type="claim",
            target_id=claim["id"],
            metadata={
                "registration_id": reg["id"],
                "policy_code": policy["policy_code"],
                "requested_amount": str(payload.requested_amount),
                "category": payload.claim_category.value,
            },
        )

        return claim


@router.get("", response_model=List[ClaimResponse])
async def list_claims(
    claim_status: Optional[ClaimStatus] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> List[Dict[str, Any]]:
    """
    Lists claims scoped to the caller's authorized domain:
    - CUSTOMER: own claims only.
    - INSURANCE_AGENT: claims for customers registered by this agent.
    - APPROVAL_AUTHORITY: all claims system-wide.
    """
    offset = (page - 1) * page_size
    user_role = current_user.get("role")
    user_id = current_user.get("id")
    status_filter = claim_status.value if claim_status else None

    async with get_db_connection() as conn:
        if user_role == UserRole.CUSTOMER.value:
            claims = await claim_repo.list_claims(
                conn=conn,
                customer_id=user_id,
                status=status_filter,
                limit=page_size,
                offset=offset,
            )
        elif user_role == UserRole.INSURANCE_AGENT.value:
            claims = await claim_repo.list_claims(
                conn=conn,
                agent_id=user_id,
                status=status_filter,
                limit=page_size,
                offset=offset,
            )
        else:
            claims = await claim_repo.list_claims(
                conn=conn,
                status=status_filter,
                limit=page_size,
                offset=offset,
            )
        return claims


@router.get("/{claim_id}", response_model=ClaimDetailResponse)
async def get_claim_details(
    claim_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """Retrieves full claim details, evidence files, latest assessment, and status history."""
    async with get_db_connection() as conn:
        claim = await _verify_claim_access(conn, claim_id, current_user)
        evidence = await claim_evidence_repo.list_evidence_by_claim(conn, claim_id)
        latest_assessment = await assessment_repo.get_latest_assessment(conn, claim_id)
        status_history = await claim_repo.get_claim_history(conn, claim_id)

        detail = dict(claim)
        detail["evidence"] = evidence
        detail["latest_assessment"] = latest_assessment
        detail["status_history"] = status_history
        return detail


# ==============================================================================
# 2. Secure Evidence Uploads and Signed Access
# ==============================================================================

@router.post("/{claim_id}/evidence", response_model=ClaimEvidenceResponse, status_code=status.HTTP_201_CREATED)
async def upload_evidence(
    claim_id: str,
    evidence_type: EvidenceType = Form(...),
    file: UploadFile = File(...),
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """
    Securely uploads evidence document for a claim into Cloudinary private storage.
    Enforces bounded reads, magic-byte validation, concurrency-safe per-claim file limits,
    and DB-backed duplicate checksum prevention.
    """
    user_role = current_user.get("role")
    user_id = current_user.get("id")
    settings = get_settings()

    # Insurance agents cannot upload evidence to claims
    if user_role == UserRole.INSURANCE_AGENT.value:
        raise AuthorizationException("Insurance agents cannot upload claim evidence.")

    # Bounded read prevents memory exhaustion on oversized uploads
    content = await file.read(settings.MAX_EVIDENCE_FILE_SIZE_BYTES + 1)
    filename = file.filename or "evidence.bin"
    declared_mime = file.content_type or "application/octet-stream"
    norm_mime = validate_file(filename=filename, content=content, declared_mime=declared_mime)
    checksum = compute_sha256(content)

    async with get_db_connection() as conn:
        claim = await _verify_claim_access(conn, claim_id, current_user)

        # Allow uploads only while claim is open for submission or review
        allowed_upload_statuses = {
            ClaimStatus.SUBMITTED.value,
            ClaimStatus.UNDER_REVIEW.value,
            ClaimStatus.EVIDENCE_REQUESTED.value,
        }
        if claim["status"] not in allowed_upload_statuses:
            raise ConflictException(f"Cannot upload evidence to claim in '{claim['status']}' state.")

        # Serialize concurrent uploads for this claim and enforce file count + duplicate checks
        await claim_evidence_repo.lock_claim_for_evidence(conn, claim_id)
        existing_count = await claim_evidence_repo.count_evidence_by_claim(conn, claim_id)
        if existing_count >= settings.MAX_EVIDENCE_FILES_PER_CLAIM:
            raise ValidationException(
                f"Maximum of {settings.MAX_EVIDENCE_FILES_PER_CLAIM} evidence files per claim exceeded."
            )

        duplicate = await claim_evidence_repo.get_evidence_by_checksum(conn, claim_id, checksum)
        if duplicate:
            raise ConflictException("This exact file has already been uploaded to this claim.")

        storage_ref, checksum, metadata = await evidence_service.upload_evidence(
            claim_id=claim_id,
            filename=filename,
            content=content,
            declared_mime=norm_mime,
        )

        try:
            evidence_record = await claim_evidence_repo.create_evidence(
                conn=conn,
                claim_id=claim_id,
                uploader_id=user_id,
                evidence_type=evidence_type.value,
                original_filename=filename,
                document_storage_ref=storage_ref,
                file_size_bytes=len(content),
                mime_type=norm_mime,
                document_checksum=checksum,
                resource_metadata=metadata,
            )

            await audit_repo.log_audit_event(
                conn=conn,
                actor_id=user_id,
                actor_role=user_role,
                action="CLAIM_EVIDENCE_UPLOADED",
                target_type="claim_evidence",
                target_id=evidence_record["id"],
                metadata={
                    "claim_id": claim_id,
                    "evidence_type": evidence_type.value,
                    "checksum": checksum,
                    "file_size": len(content),
                },
            )

            # Trigger automated multimodal document analysis (Phase 6 Stage 2)
            try:
                await evidence_analysis_service.analyze_evidence_document(
                    conn=conn,
                    claim_id=claim_id,
                    evidence_id=evidence_record["id"],
                    content=content,
                    actor_id=user_id,
                    actor_role=user_role,
                )
                refreshed = await claim_evidence_repo.get_evidence_by_id(conn, evidence_record["id"])
                if refreshed:
                    evidence_record = refreshed
            except Exception as analysis_exc:
                logger.warning(
                    "Automated evidence analysis failed for %s: %s",
                    evidence_record["id"],
                    analysis_exc,
                )

            return evidence_record

        except Exception as exc:
            # Compensating cleanup on Cloudinary if DB persistence fails
            await evidence_service.delete_evidence_file(
                storage_ref,
                resource_type=metadata.get("resource_type", "image"),
            )
            raise exc


@router.get("/{claim_id}/evidence", response_model=List[ClaimEvidenceResponse])
async def list_claim_evidence(
    claim_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> List[Dict[str, Any]]:
    """Lists all evidence metadata for an authorized claim."""
    if current_user.get("role") == UserRole.INSURANCE_AGENT.value:
        raise AuthorizationException("Insurance agents cannot access claim evidence.")
    async with get_db_connection() as conn:
        await _verify_claim_access(conn, claim_id, current_user)
        return await claim_evidence_repo.list_evidence_by_claim(conn, claim_id)


@router.get("/{claim_id}/evidence/{evidence_id}/signed-url", response_model=SignedUrlResponse)
async def get_evidence_signed_url(
    claim_id: str,
    evidence_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """Generates a short-lived signed access URL for private evidence viewing."""
    if current_user.get("role") == UserRole.INSURANCE_AGENT.value:
        raise AuthorizationException("Insurance agents cannot access claim evidence.")
    async with get_db_connection() as conn:
        await _verify_claim_access(conn, claim_id, current_user)
        evidence = await claim_evidence_repo.get_evidence_by_id(conn, evidence_id)
        if not evidence or evidence["claim_id"] != claim_id:
            raise NotFoundException("Evidence document not found.")

        expires_in = 300
        signed_url = await evidence_service.generate_signed_url(
            document_storage_ref=evidence["document_storage_ref"],
            mime_type=evidence["mime_type"],
            expires_in_seconds=expires_in,
        )

        await audit_repo.log_audit_event(
            conn=conn,
            actor_id=current_user["id"],
            actor_role=current_user["role"],
            action="CLAIM_EVIDENCE_ACCESSED",
            target_type="claim_evidence",
            target_id=evidence_id,
            metadata={"claim_id": claim_id, "expires_in_seconds": expires_in},
        )

        return {
            "evidence_id": evidence_id,
            "signed_url": signed_url,
            "expires_in_seconds": expires_in,
        }


# ==============================================================================
# 2.1 Multimodal Evidence Analysis & Arithmetic Auditing (Phase 6 Stage 2)
# ==============================================================================

@router.post(
    "/{claim_id}/evidence/{evidence_id}/analyze",
    response_model=EvidenceAnalysisReportResponse,
)
async def analyze_claim_evidence(
    claim_id: str,
    evidence_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """
    Triggers or re-triggers OCR, entity extraction, and arithmetic integrity auditing
    on an existing uploaded evidence document.
    Access restricted to the Claim Owner (Customer) and Approval Authority.
    """
    user_role = current_user.get("role")
    if user_role == UserRole.INSURANCE_AGENT.value:
        raise AuthorizationException("Insurance agents cannot access claim evidence analysis.")

    async with get_db_connection() as conn:
        await _verify_claim_access(conn, claim_id, current_user)
        report = await evidence_analysis_service.analyze_evidence_document(
            conn=conn,
            claim_id=claim_id,
            evidence_id=evidence_id,
            content=None,
            actor_id=current_user.get("id"),
            actor_role=user_role,
        )
        return report


@router.get(
    "/{claim_id}/evidence/{evidence_id}/analysis",
    response_model=EvidenceAnalysisReportResponse,
)
async def get_evidence_analysis(
    claim_id: str,
    evidence_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """
    Retrieves the latest versioned analysis report for a specific evidence document.
    """
    user_role = current_user.get("role")
    if user_role == UserRole.INSURANCE_AGENT.value:
        raise AuthorizationException("Insurance agents cannot access claim evidence analysis.")

    async with get_db_connection() as conn:
        await _verify_claim_access(conn, claim_id, current_user)
        report = await evidence_analysis_repo.get_latest_report_by_evidence_id(conn, evidence_id)
        if not report or report["claim_id"] != claim_id:
            raise NotFoundException("Analysis report not found for this evidence document.")
        return report


@router.get(
    "/{claim_id}/evidence/{evidence_id}/analysis/history",
    response_model=List[EvidenceAnalysisReportResponse],
)
async def get_evidence_analysis_history(
    claim_id: str,
    evidence_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> List[Dict[str, Any]]:
    """
    Retrieves all versioned analysis reports for a specific evidence document.
    """
    user_role = current_user.get("role")
    if user_role == UserRole.INSURANCE_AGENT.value:
        raise AuthorizationException("Insurance agents cannot access claim evidence analysis.")

    async with get_db_connection() as conn:
        await _verify_claim_access(conn, claim_id, current_user)
        evidence = await claim_evidence_repo.get_evidence_by_id(conn, evidence_id)
        if not evidence or evidence["claim_id"] != claim_id:
            raise NotFoundException("Evidence document not found.")
        return await evidence_analysis_repo.get_analysis_history_for_evidence(conn, evidence_id)


@router.get(
    "/{claim_id}/evidence-analysis",
    response_model=EvidenceAnalysisListResponse,
)
async def list_claim_evidence_analysis(
    claim_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """
    Retrieves all latest evidence analysis reports for a claim.
    """
    user_role = current_user.get("role")
    if user_role == UserRole.INSURANCE_AGENT.value:
        raise AuthorizationException("Insurance agents cannot access claim evidence analysis.")

    async with get_db_connection() as conn:
        await _verify_claim_access(conn, claim_id, current_user)
        reports = await evidence_analysis_repo.list_reports_by_claim_id(conn, claim_id, latest_only=True)
        return {
            "claim_id": claim_id,
            "total_reports": len(reports),
            "reports": reports,
        }


@router.post(
    "/{claim_id}/spoken-explanation",
    response_model=ClaimSpokenExplanationResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate customer-facing spoken explanation of claim decision (Phase 5)",
)
async def generate_claim_spoken_explanation(
    claim_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> ClaimSpokenExplanationResponse:
    """
    Retrieves the actual adjudication decision and reasoning recorded by the authority,
    composes a transparent, plain-language narrative, and synthesizes audio with ElevenLabs TTS.
    Accessible to Claim Owner (Customer) and Approval Authority.
    """
    user_role = current_user.get("role")
    if user_role == UserRole.INSURANCE_AGENT.value:
        raise AuthorizationException("Insurance agents cannot access claim adjudication explanations.")

    async with get_db_connection() as conn:
        return await voice_assistant_service.generate_spoken_claim_explanation(
            conn=conn,
            claim_id=claim_id,
            actor_id=current_user.get("id"),
            actor_role=user_role,
        )


# ==============================================================================
# 3. Deterministic Eligibility Evaluation
# ==============================================================================

@router.post("/{claim_id}/assess", response_model=ClaimAssessmentResponse)
async def assess_claim_eligibility(
    claim_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """
    Executes deterministic eligibility rules against the registered policy version.
    Records traceable versioned assessment result in database.
    """
    user_role = current_user.get("role")
    if user_role not in (UserRole.CUSTOMER.value, UserRole.APPROVAL_AUTHORITY.value):
        raise AuthorizationException("Agents cannot execute eligibility assessments.")

    async with get_db_connection() as conn:
        claim = await _verify_claim_access(conn, claim_id, current_user)
        reg = await registration_repo.get_registration_by_id(conn, claim["registration_id"])
        policy = await policy_repo.get_policy_by_id(conn, claim["policy_id"])
        policy_version = await policy_repo.get_policy_version_by_id(conn, claim["policy_version_id"])
        evidence_list = await claim_evidence_repo.list_evidence_by_claim(conn, claim_id)

        # Duplicate candidates check count
        candidates = await duplicate_detector.find_candidates(conn, claim)

        evaluation = eligibility_engine.evaluate_claim(
            claim=claim,
            registration=reg or {},
            policy=policy or {},
            policy_version=policy_version or {},
            evidence_list=evidence_list,
            duplicate_candidate_count=len(candidates),
        )

        # Persist versioned assessment
        assessment = await assessment_repo.create_assessment(
            conn=conn,
            claim_id=claim_id,
            policy_version_id=claim["policy_version_id"],
            overall_outcome=evaluation.overall_outcome.value,
            rules_evaluated=[
                {
                    "rule_id": r.rule_id,
                    "result": r.result.value,
                    "explanation": r.explanation,
                    "details": r.details,
                }
                for r in evaluation.rules_evaluated
            ],
            requested_amount=evaluation.requested_amount,
            applicable_limit=evaluation.applicable_limit,
            potentially_payable_amount=evaluation.potentially_payable_amount,
            excess_amount=evaluation.excess_amount,
            missing_evidence=evaluation.missing_evidence,
            review_flags=evaluation.review_flags,
            assessed_by=current_user["id"],
        )

        await audit_repo.log_audit_event(
            conn=conn,
            actor_id=current_user["id"],
            actor_role=current_user["role"],
            action="CLAIM_ASSESSED",
            target_type="claim_assessment",
            target_id=assessment["id"],
            metadata={
                "claim_id": claim_id,
                "overall_outcome": evaluation.overall_outcome.value,
                "potentially_payable_amount": str(evaluation.potentially_payable_amount),
            },
        )

        return assessment


@router.get("/{claim_id}/assessment", response_model=ClaimAssessmentResponse)
async def get_latest_claim_assessment(
    claim_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """Retrieves the most recent deterministic assessment result for a claim."""
    async with get_db_connection() as conn:
        await _verify_claim_access(conn, claim_id, current_user)
        assessment = await assessment_repo.get_latest_assessment(conn, claim_id)
        if not assessment:
            raise NotFoundException("No assessment has been conducted for this claim yet.")
        return assessment


# ==============================================================================
# 4. Duplicate Claim Detection
# ==============================================================================

@router.get("/{claim_id}/duplicates", response_model=DuplicateCandidatesListResponse)
async def check_claim_duplicates(
    claim_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """
    Checks for potential duplicate incidents.
    Customers are scoped strictly to their own past claims; Authorities search system-wide.
    """
    user_role = current_user.get("role")
    if user_role == UserRole.INSURANCE_AGENT.value:
        raise AuthorizationException("Agents cannot query duplicate claim candidates.")

    async with get_db_connection() as conn:
        claim = await _verify_claim_access(conn, claim_id, current_user)

        # Scoping: customer only sees candidates from their own claims
        scope_customer_id = (
            current_user["id"] if user_role == UserRole.CUSTOMER.value else None
        )

        candidates = await duplicate_detector.find_candidates(
            conn=conn,
            target_claim=claim,
            scope_customer_id=scope_customer_id,
        )

        await audit_repo.log_audit_event(
            conn=conn,
            actor_id=current_user["id"],
            actor_role=user_role,
            action="CLAIM_DUPLICATE_CHECKED",
            target_type="claim",
            target_id=claim_id,
            metadata={"candidate_count": len(candidates)},
        )

        return {
            "claim_id": claim_id,
            "total_candidates": len(candidates),
            "candidates": candidates,
        }


# ==============================================================================
# 5. Claim Lifecycle State Transitions & Simulated Payments
# ==============================================================================

@router.post("/{claim_id}/transition", response_model=ClaimResponse)
async def transition_claim_status(
    claim_id: str,
    payload: TransitionStatusRequest,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """
    Transitions claim lifecycle state according to strict state machine rules.
    Requires mandatory decision reasoning and role authorization.
    """
    async with get_db_connection() as conn:
        claim = await _verify_claim_access(conn, claim_id, current_user)
        updated_claim = await claim_lifecycle_service.transition_status(
            conn=conn,
            claim=claim,
            target_status=payload.target_status,
            actor_id=current_user["id"],
            actor_role=current_user["role"],
            reason=payload.reason,
            decision_metadata=payload.decision_metadata,
            is_simulated_payment=False,
        )
        return updated_claim


@router.post("/{claim_id}/simulate-payment", response_model=ClaimResponse)
async def simulate_claim_payment(
    claim_id: str,
    payload: TransitionStatusRequest,
    current_user: Dict[str, Any] = Depends(require_active_authority),
) -> Dict[str, Any]:
    """
    Executes simulated payment action for an APPROVED claim, transitioning it to PAID.
    Exclusively permitted for active Approval Authority operators.
    """
    async with get_db_connection() as conn:
        claim = await _verify_claim_access(conn, claim_id, current_user)
        if payload.target_status != ClaimStatus.PAID:
            raise ValidationException("Simulate-payment endpoint only transitions claims to PAID status.")

        updated_claim = await claim_lifecycle_service.transition_status(
            conn=conn,
            claim=claim,
            target_status=ClaimStatus.PAID,
            actor_id=current_user["id"],
            actor_role=current_user["role"],
            reason=payload.reason,
            decision_metadata=payload.decision_metadata,
            is_simulated_payment=True,
        )
        return updated_claim


@router.get("/{claim_id}/history", response_model=List[ClaimStatusHistoryResponse])
async def get_claim_status_history(
    claim_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> List[Dict[str, Any]]:
    """Retrieves full audit timeline of all lifecycle transitions for a claim."""
    async with get_db_connection() as conn:
        await _verify_claim_access(conn, claim_id, current_user)
        return await claim_repo.get_claim_history(conn, claim_id)
