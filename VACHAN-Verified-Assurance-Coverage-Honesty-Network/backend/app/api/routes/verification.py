"""
Policy-Promise Verification API endpoints for InsureChain VoiceGuard.
Enforces RBAC scoping, grounding validation, and immutable report versioning.
"""

from typing import Any, Dict, List, Optional, Union
from fastapi import APIRouter, Depends, Query, status
import psycopg

from app.api.deps import get_current_active_user
from app.core.exceptions import (
    AuthorizationException,
    NotFoundException,
    ValidationException,
)
from app.core.security import UserRole
from app.db.connection import get_db_connection
from app.db.repositories import (
    audit_repo,
    sales_session_repo,
    verification_repo,
)
from app.schemas.verification import (
    ReanalyzeRequest,
    StartVerificationResponse,
    VerificationReportResponse,
)
from app.services.gemini_verifier import gemini_verifier_service

router = APIRouter(tags=["Policy Verification"])


async def _verify_session_or_report_access(
    conn: psycopg.AsyncConnection,
    user: Dict[str, Any],
    customer_id: str,
    agent_id: str,
) -> None:
    """Enforces RBAC access scoping: Customer (own), Agent (own), Authority (all)."""
    user_role = user.get("role")
    user_id = user.get("id")

    if user_role == UserRole.APPROVAL_AUTHORITY.value:
        return

    if user_role == UserRole.CUSTOMER.value:
        if customer_id != user_id:
            raise NotFoundException("Resource not found.")
        return

    if user_role == UserRole.INSURANCE_AGENT.value:
        if agent_id != user_id:
            raise NotFoundException("Resource not found.")
        return

    raise AuthorizationException("Access denied.")


@router.post(
    "/sales-sessions/{session_id}/verify-policy",
    response_model=VerificationReportResponse,
    status_code=status.HTTP_200_OK,
)
async def verify_sales_session_policy(
    session_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """
    Triggers Gemini promise verification of a completed sales session against official policy terms.
    Enforces customer and agent access scoping.
    """
    async with get_db_connection() as conn:
        session = await sales_session_repo.get_session_by_id(conn, session_id)
        if not session:
            raise NotFoundException("Sales session not found.")

        await _verify_session_or_report_access(
            conn=conn,
            user=current_user,
            customer_id=session["customer_id"],
            agent_id=session["agent_id"],
        )

        existing_report = await verification_repo.get_latest_report_for_session(conn, session_id)
        if existing_report and existing_report.get("status") == "COMPLETED":
            return existing_report

        report = await gemini_verifier_service.verify_sales_session(
            conn=conn,
            sales_session_id=session_id,
            actor_id=current_user["id"],
            actor_role=current_user["role"],
        )
        return report


@router.get(
    "/sales-sessions/{session_id}/verification",
    response_model=Union[VerificationReportResponse, List[VerificationReportResponse]],
)
async def get_session_verification(
    session_id: str,
    all_versions: bool = Query(default=False, description="Return all historical versions if true"),
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    """Retrieves the latest verification report or all versioned reports for a sales session."""
    async with get_db_connection() as conn:
        session = await sales_session_repo.get_session_by_id(conn, session_id)
        if not session:
            raise NotFoundException("Sales session not found.")

        await _verify_session_or_report_access(
            conn=conn,
            user=current_user,
            customer_id=session["customer_id"],
            agent_id=session["agent_id"],
        )

        if all_versions:
            reports = await verification_repo.list_reports_for_session(conn, session_id)
            return reports

        latest = await verification_repo.get_latest_report_for_session(conn, session_id)
        if not latest:
            raise NotFoundException("No verification report found for this sales session.")
        return latest


@router.get(
    "/verification-reports/{report_id}",
    response_model=VerificationReportResponse,
)
async def get_verification_report(
    report_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """Retrieves a specific verification report by UUID."""
    async with get_db_connection() as conn:
        report = await verification_repo.get_report_by_id(conn, report_id)
        if not report:
            raise NotFoundException("Verification report not found.")

        await _verify_session_or_report_access(
            conn=conn,
            user=current_user,
            customer_id=report["customer_id"],
            agent_id=report["agent_id"],
        )

        return report


@router.post(
    "/verification-reports/{report_id}/reanalyze",
    response_model=VerificationReportResponse,
    status_code=status.HTTP_200_OK,
)
async def reanalyze_verification_report(
    report_id: str,
    body: Optional[ReanalyzeRequest] = None,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """
    Triggers re-analysis of the underlying sales session without overwriting prior reports.
    Increments report_version sequentially.
    """
    async with get_db_connection() as conn:
        old_report = await verification_repo.get_report_by_id(conn, report_id)
        if not old_report:
            raise NotFoundException("Verification report not found.")

        await _verify_session_or_report_access(
            conn=conn,
            user=current_user,
            customer_id=old_report["customer_id"],
            agent_id=old_report["agent_id"],
        )

        session_id = old_report["sales_session_id"]

        # Run fresh verification producing an incremental version
        new_report = await gemini_verifier_service.verify_sales_session(
            conn=conn,
            sales_session_id=session_id,
            actor_id=current_user["id"],
            actor_role=current_user["role"],
        )

        # Audit reanalysis request
        await audit_repo.log_audit_event(
            conn=conn,
            actor_id=current_user["id"],
            actor_role=current_user["role"],
            action="REANALYZE_VERIFICATION",
            target_type="verification_report",
            target_id=new_report["id"],
            metadata={
                "previous_report_id": report_id,
                "previous_version": old_report["report_version"],
                "new_version": new_report["report_version"],
                "reason": body.reason if body else None,
            },
        )

        return new_report


from pydantic import BaseModel
class AuditTranscriptRequest(BaseModel):
    transcript: str
    policy_id: Optional[str] = None


@router.post("/verification/audit-transcript")
async def audit_transcript_direct(
    body: AuditTranscriptRequest,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """Directly audits a sales transcript against official policy wording from the database using Gemini."""
    import uuid
    from app.core.exceptions import IntegrationException, ValidationException
    from app.db.repositories import audit_repo, policy_repo
    from app.services.policy_extractor import policy_extractor_service

    if not body.transcript or not body.transcript.strip():
        raise ValidationException("Transcript text cannot be empty.")

    async with get_db_connection() as conn:
        policy = None
        if body.policy_id:
            try:
                uuid.UUID(str(body.policy_id))
                policy = await policy_repo.get_policy_by_id(conn, body.policy_id)
            except (ValueError, TypeError):
                policy = await policy_repo.get_policy_by_code(conn, body.policy_id)
            if not policy:
                raise NotFoundException(f"Policy '{body.policy_id}' not found.")
        else:
            pols = await policy_repo.list_policies(conn, is_active=True)
            if pols:
                policy = pols[0]
            if not policy:
                raise NotFoundException("No active policy found in database to audit against.")

        policy_text = ""
        published_ver = await policy_repo.get_published_version(conn, policy["id"])
        if published_ver:
            try:
                extraction = await policy_extractor_service.get_or_extract_policy_text(
                    conn, published_ver["id"]
                )
                policy_text = (extraction.get("extracted_text") or "").strip()
            except Exception as ext_err:
                logger.warning("Policy extraction unavailable during direct audit: %s", type(ext_err).__name__)

        if not policy_text:
            policy_text = (
                f"Policy Name: {policy.get('policy_name')} ({policy.get('policy_code')})\n"
                f"Insurer: {policy.get('insurer_name')}\n"
                f"Category: {policy.get('category')}\n"
                f"Coverage Limit: {policy.get('coverage_limit')}\n"
                f"Waiting Period Days: {policy.get('waiting_period_days')}\n"
                f"Claim Filing Window Days: {policy.get('claim_filing_window_days')}\n"
                f"Description: {policy.get('description') or ''}"
            )

        llm_result = await gemini_verifier_service._call_gemini_api(
            transcript=body.transcript,
            policy_text=policy_text,
            policy_meta=policy,
        )
        if not isinstance(llm_result, dict):
            raise IntegrationException(
                service="Gemini",
                message="Gemini returned an invalid audit response.",
            )

        raw_findings = llm_result.get("findings", [])
        supported = sum(1 for f in raw_findings if f.get("verdict") == "SUPPORTED" or f.get("classification") == "SUPPORTED")
        partly = sum(1 for f in raw_findings if f.get("verdict") == "PARTLY_TRUE" or f.get("classification") == "PARTLY_TRUE")
        contradicted = sum(1 for f in raw_findings if f.get("verdict") == "CONTRADICTED" or f.get("classification") == "CONTRADICTED")
        overall = "COMPLIANT" if contradicted == 0 and partly == 0 else "PARITY_DISCREPANCY_DETECTED"

        await audit_repo.log_audit_event(
            conn=conn,
            actor_id=current_user["id"],
            actor_role=current_user["role"],
            action="AUDIT_TRANSCRIPT_DIRECT",
            target_type="policy",
            target_id=policy["id"],
            metadata={
                "overall_status": overall,
                "supported_count": supported,
                "partly_true_count": partly,
                "contradicted_count": contradicted,
            },
        )

        return {
            "summary": llm_result.get("summary", "Gemini Policy Parity Evaluation"),
            "overall_status": overall,
            "policy_id": policy["id"],
            "supported_count": supported,
            "partly_true_count": partly,
            "contradicted_count": contradicted,
            "findings": raw_findings,
        }

