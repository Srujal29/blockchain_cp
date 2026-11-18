"""
Sales Sessions and Voice Transcription API routes for InsureChain VoiceGuard.
Enforces agent authorization, affirmative customer recording consent,
Cloudinary private audio integration, and ElevenLabs Scribe STT processing.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, File, Query, UploadFile, status
import psycopg

from app.api.deps import (
    get_current_active_user,
    require_active_agent,
)
from app.core.config import get_settings
from app.core.exceptions import (
    AuthorizationException,
    ConflictException,
    IntegrationException,
    NotFoundException,
    ValidationException,
)
from app.core.security import AccountStatus, hash_password, UserRole
from app.db.connection import get_db_connection
from app.db.repositories import (
    audit_repo,
    policy_repo,
    registration_repo,
    sales_session_repo,
    user_repo,
)
from app.services.evidence_service import evidence_service
from app.schemas.sales_session import (
    CreateSalesSessionRequest,
    SalesSessionResponse,
    StartTranscriptionResponse,
    TranscriptResponse,
)
from app.services.elevenlabs_stt import elevenlabs_stt_service
from app.services.email_service import EmailService
from app.services.evidence_service import evidence_service

router = APIRouter(prefix="/sales-sessions", tags=["Sales Voice Sessions"])


async def _verify_session_access(
    conn: psycopg.AsyncConnection,
    session_id: str,
    user: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Validates caller access to sales session:
    - CUSTOMER: own sessions only.
    - INSURANCE_AGENT: sessions created by this agent.
    - APPROVAL_AUTHORITY: unrestricted.
    Fails closed with 404 to avoid information leakage.
    """
    import uuid
    try:
        uuid.UUID(str(session_id))
    except (ValueError, TypeError):
        raise NotFoundException("Sales session not found.")

    session = await sales_session_repo.get_session_by_id(conn, session_id)
    if not session:
        raise NotFoundException("Sales session not found.")

    user_role = user.get("role")
    user_id = user.get("id")

    if user_role == UserRole.APPROVAL_AUTHORITY.value:
        return session

    if user_role == UserRole.CUSTOMER.value:
        if session["customer_id"] != user_id:
            raise NotFoundException("Sales session not found.")
        return session

    if user_role == UserRole.INSURANCE_AGENT.value:
        if session["agent_id"] != user_id:
            raise NotFoundException("Sales session not found.")
        return session

    raise AuthorizationException("Access denied to sales session resource.")


# ==============================================================================
# 1. Sales Session Creation and Listing
# ==============================================================================

@router.post("", response_model=SalesSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_sales_session(
    payload: CreateSalesSessionRequest,
    current_user: Dict[str, Any] = Depends(require_active_agent),
) -> Dict[str, Any]:
    """
    Creates a new sales conversation session recording.
    Requires insurance agent credentials and mandatory affirmative customer consent.
    """
    settings = get_settings()

    # Validate audio MIME type
    if payload.audio_mime_type.lower() not in settings.ALLOWED_AUDIO_MIME_TYPES:
        raise ValidationException(
            f"Unsupported audio MIME type '{payload.audio_mime_type}'. "
            f"Allowed types: {', '.join(settings.ALLOWED_AUDIO_MIME_TYPES)}."
        )

    # Validate audio file size
    if payload.audio_file_size_bytes > settings.MAX_AUDIO_FILE_SIZE_BYTES:
        raise ValidationException(
            f"Audio file size ({payload.audio_file_size_bytes} bytes) exceeds maximum "
            f"limit of {settings.MAX_AUDIO_FILE_SIZE_BYTES} bytes ({settings.MAX_AUDIO_FILE_SIZE_BYTES // (1024 * 1024)}MB)."
        )

    async with get_db_connection() as conn:
        # 1. Resolve customer account (no silent user creation or hardcoded fallbacks)
        customer = None
        if payload.customer_id:
            customer = await user_repo.get_user_by_id(conn, payload.customer_id)
            if not customer or customer.get("role") != UserRole.CUSTOMER.value:
                raise ValidationException("Invalid customer ID: Target user must be an active customer.")
            customer_id = customer["id"]
        elif payload.customer_email and payload.customer_email.strip():
            target_email = payload.customer_email.strip().lower()
            customer = await user_repo.get_user_by_email(conn, target_email)
            if not customer or customer.get("role") != UserRole.CUSTOMER.value:
                raise ValidationException(
                    f"Customer with email '{target_email}' does not exist. Please register the customer account first."
                )
            customer_id = customer["id"]
        else:
            raise ValidationException(
                "Customer identification (customer_id or customer_email) is required to create a sales session."
            )

        # 2. Resolve policy version and registration
        version_id = payload.policy_version_id
        policy = None
        if payload.policy_id:
            policy = await policy_repo.get_policy_by_id(conn, payload.policy_id)
            if not policy:
                raise ValidationException("Specified policy ID does not exist.")
            if not policy.get("is_active"):
                raise ValidationException("Specified policy is not currently active.")
            if not version_id:
                latest_ver = await policy_repo.get_published_version(conn, payload.policy_id)
                if not latest_ver:
                    raise ValidationException("Specified policy does not have an active published version.")
                version_id = latest_ver["id"]

        registration_id = payload.registration_id
        if not registration_id and payload.policy_id and version_id:
            existing_regs = await registration_repo.list_registrations(
                conn=conn, customer_id=customer_id, policy_id=payload.policy_id, limit=1
            )
            if existing_regs:
                registration_id = existing_regs[0]["id"]
            else:
                try:
                    new_reg = await registration_repo.create_registration(
                        conn=conn,
                        customer_id=customer_id,
                        agent_id=current_user["id"],
                        policy_id=payload.policy_id,
                        policy_version_id=version_id,
                        customer_consent=payload.customer_consent,
                        consent_notes=payload.consent_notes,
                        status="AWAITING_CUSTOMER_CONFIRMATION",
                    )
                    registration_id = new_reg["id"]
                except Exception as e:
                    logger.error("Failed to create registration for sales session: %s", str(e), exc_info=True)
                    registration_id = None

        session = await sales_session_repo.create_sales_session(
            conn=conn,
            customer_id=customer_id,
            agent_id=current_user["id"],
            audio_storage_ref=payload.audio_storage_ref,
            audio_mime_type=payload.audio_mime_type.lower(),
            audio_file_size_bytes=payload.audio_file_size_bytes,
            audio_checksum=payload.audio_checksum,
            customer_consent=payload.customer_consent,
            policy_id=payload.policy_id,
            policy_version_id=version_id,
            registration_id=registration_id,
            duration_seconds=payload.duration_seconds,
            consent_notes=payload.consent_notes,
        )

        # Audit events
        await audit_repo.log_audit_event(
            conn=conn,
            actor_id=current_user["id"],
            actor_role=current_user["role"],
            action="SALES_SESSION_CREATED",
            target_type="sales_session",
            target_id=session["id"],
            metadata={"customer_id": customer_id, "audio_checksum": payload.audio_checksum},
        )

        if payload.customer_consent:
            await audit_repo.log_audit_event(
                conn=conn,
                actor_id=current_user["id"],
                actor_role=current_user["role"],
                action="CUSTOMER_CONSENT_RECORDED",
                target_type="sales_session",
                target_id=session["id"],
                metadata={"consent_status": True},
            )

        return session


@router.get("", response_model=List[SalesSessionResponse])
async def list_sales_sessions(
    session_status: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> List[Dict[str, Any]]:
    """Lists sales sessions scoped by role permissions."""
    offset = (page - 1) * page_size
    user_role = current_user.get("role")
    user_id = current_user.get("id")

    async with get_db_connection() as conn:
        if user_role == UserRole.CUSTOMER.value:
            sessions = await sales_session_repo.list_sessions(
                conn=conn, customer_id=user_id, status=session_status, limit=page_size, offset=offset
            )
        elif user_role == UserRole.INSURANCE_AGENT.value:
            sessions = await sales_session_repo.list_sessions(
                conn=conn, agent_id=user_id, status=session_status, limit=page_size, offset=offset
            )
        else:
            sessions = await sales_session_repo.list_sessions(
                conn=conn, status=session_status, limit=page_size, offset=offset
            )
        return sessions


@router.get("/{session_id}", response_model=SalesSessionResponse)
async def get_sales_session_details(
    session_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """Retrieves session metadata and current transcription processing status."""
    async with get_db_connection() as conn:
        return await _verify_session_access(conn, session_id, current_user)


@router.post("/{session_id}/audio", response_model=SalesSessionResponse)
async def upload_session_audio(
    session_id: str,
    file: UploadFile = File(...),
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """
    Validates and uploads real recorded audio bytes to private Cloudinary storage
    for a sales session, with compensating cleanup if database persistence fails.
    """
    user_role = current_user.get("role")
    if user_role not in (UserRole.INSURANCE_AGENT.value, UserRole.APPROVAL_AUTHORITY.value):
        raise AuthorizationException("Not authorized to upload audio.")

    settings = get_settings()
    contents = await file.read(settings.MAX_AUDIO_FILE_SIZE_BYTES + 1)
    filename = file.filename or "recording.m4a"
    declared_mime = file.content_type or "audio/m4a"

    async with get_db_connection() as conn:
        await _verify_session_access(conn, session_id, current_user)

        storage_ref, checksum, meta = await evidence_service.upload_session_audio(
            session_id=session_id,
            filename=filename,
            content=contents,
            declared_mime=declared_mime,
        )

        try:
            sql = f"""
            UPDATE sales_sessions
            SET audio_file_size_bytes = %s,
                audio_checksum = %s,
                audio_mime_type = %s,
                audio_storage_ref = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING {sales_session_repo.SESSION_FIELDS};
            """
            async with conn.cursor() as cur:
                await cur.execute(
                    sql,
                    (len(contents), checksum, meta["mime_type"], storage_ref, session_id),
                )
                row = await cur.fetchone()
                updated = sales_session_repo._row_to_session_dict(row)

            await audit_repo.log_audit_event(
                conn=conn,
                actor_id=current_user["id"],
                actor_role=user_role,
                action="UPLOAD_SESSION_AUDIO",
                target_type="sales_session",
                target_id=session_id,
                metadata={
                    "audio_checksum": checksum,
                    "audio_mime_type": meta["mime_type"],
                    "file_size_bytes": len(contents),
                },
            )
            return updated
        except Exception:
            await evidence_service.delete_evidence_file(storage_ref, resource_type="raw")
            raise


# ==============================================================================
# 2. Transcription Execution & Transcript Access
# ==============================================================================

@router.post("/{session_id}/transcribe", response_model=StartTranscriptionResponse)
async def start_session_transcription(
    session_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """
    Initiates speech-to-text transcription via ElevenLabs Scribe API.
    Enforces customer consent check, agent authorization, and prevents duplicate jobs.
    """
    user_role = current_user.get("role")
    if user_role not in (UserRole.INSURANCE_AGENT.value, UserRole.APPROVAL_AUTHORITY.value):
        raise AuthorizationException("Customers cannot initiate transcription jobs.")

    async with get_db_connection() as conn:
        session = await _verify_session_access(conn, session_id, current_user)

        # 1. Explicit Consent Check
        if not session.get("customer_consent"):
            raise ConflictException(
                "Customer consent is missing or declined. Transcription cannot proceed without verified affirmative consent."
            )

        # 2. If already COMPLETED, return existing result without duplicate charge
        if session["status"] == "COMPLETED":
            return {
                "session_id": session_id,
                "status": "COMPLETED",
                "message": "Transcription already completed for this session.",
                "transcript": session["transcript"],
            }

        # 3. Atomic lock to transition to PROCESSING
        acquired, active_session = await sales_session_repo.acquire_session_for_transcription_atomic(
            conn, session_id
        )
        if not acquired:
            return {
                "session_id": session_id,
                "status": active_session["status"],
                "message": "Transcription is already in progress for this session.",
                "transcript": active_session.get("transcript"),
            }

        await audit_repo.log_audit_event(
            conn=conn,
            actor_id=current_user["id"],
            actor_role=user_role,
            action="TRANSCRIPTION_STARTED",
            target_type="sales_session",
            target_id=session_id,
            metadata={"provider_model": "scribe_v2"},
        )

        try:
            storage_ref = (session.get("audio_storage_ref") or "").strip()
            if (
                not storage_ref
                or storage_ref.startswith("local://")
                or storage_ref.startswith("voiceguard/sessions/")
            ):
                raise ValidationException(
                    "Recorded audio has not been uploaded to secure storage. "
                    "Please upload the recording before starting transcription."
                )

            audio_mime = session.get("audio_mime_type") or "audio/m4a"
            ext_map = {
                "audio/m4a": "m4a",
                "audio/mp4": "m4a",
                "audio/x-m4a": "m4a",
                "audio/mpeg": "mp3",
                "audio/mp3": "mp3",
                "audio/wav": "wav",
                "audio/x-wav": "wav",
                "audio/ogg": "ogg",
                "audio/webm": "webm",
                "audio/aac": "aac",
            }
            ext = ext_map.get(audio_mime.lower().split(";")[0].strip(), "m4a")
            audio_name = f"{session_id}.{ext}"

            audio_bytes = await evidence_service.download_private_file_bytes(
                document_storage_ref=storage_ref,
                mime_type=audio_mime,
                expires_in_seconds=300,
            )

            result = await elevenlabs_stt_service.transcribe_audio(
                audio_bytes=audio_bytes,
                filename=audio_name,
                mime_type=audio_mime,
            )

            speaker_diarization = []
            if result.speaker_diarization:
                for turn in result.speaker_diarization:
                    raw_speaker = str(turn.get("speaker") or turn.get("speaker_id") or "speaker_0").strip()
                    lower_sp = raw_speaker.lower()
                    # ElevenLabs Scribe v2 assigns acoustic cluster IDs (speaker_0, speaker_1...)
                    # without semantic role awareness. To avoid misattributing speaker identities,
                    # map raw cluster identifiers to neutral labels "Speaker 1", "Speaker 2", etc.
                    import re
                    match = re.match(r"^speaker_?(\d+)$", lower_sp)
                    if match:
                        speaker_label = f"Speaker {int(match.group(1)) + 1}"
                    elif lower_sp.startswith("speaker"):
                        speaker_label = raw_speaker
                    elif raw_speaker:
                        speaker_label = raw_speaker
                    else:
                        speaker_label = "Speaker 1"

                    turn_entry: Dict[str, Any] = {
                        "speaker": speaker_label,
                        "text": turn.get("text", ""),
                    }
                    if turn.get("start") is not None:
                        turn_entry["start"] = turn.get("start")
                    if turn.get("end") is not None:
                        turn_entry["end"] = turn.get("end")
                    speaker_diarization.append(turn_entry)
            elif result.transcript:
                speaker_diarization = [
                    {"speaker": "Speaker 1", "text": result.transcript}
                ]

            updated = await sales_session_repo.update_transcription_success(
                conn=conn,
                session_id=session_id,
                transcript=result.transcript,
                detected_language=result.detected_language or "en",
                word_segments=result.word_segments,
                speaker_diarization=speaker_diarization,
                provider_model=result.provider_model or "scribe_v2",
            )

            await audit_repo.log_audit_event(
                conn=conn,
                actor_id=current_user["id"],
                actor_role=user_role,
                action="TRANSCRIPTION_COMPLETED",
                target_type="sales_session",
                target_id=session_id,
                metadata={
                    "detected_language": result.detected_language,
                    "word_count": len(result.word_segments),
                },
            )

            return {
                "session_id": session_id,
                "status": "COMPLETED",
                "message": "Transcription completed successfully.",
                "transcript": updated["transcript"],
            }

        except Exception as exc:
            error_msg = str(exc)
            error_cat = "PROVIDER_ERROR"
            if "authentication" in error_msg.lower():
                error_cat = "AUTHENTICATION_FAILED"
            elif "rate limit" in error_msg.lower():
                error_cat = "RATE_LIMITED"
            elif "timeout" in error_msg.lower():
                error_cat = "PROVIDER_TIMEOUT"
            elif isinstance(exc, ValidationException):
                error_cat = "MISSING_AUDIO"

            await sales_session_repo.update_transcription_failure(
                conn=conn,
                session_id=session_id,
                error_category=error_cat,
                error_message=error_msg,
            )

            await audit_repo.log_audit_event(
                conn=conn,
                actor_id=current_user["id"],
                actor_role=user_role,
                action="TRANSCRIPTION_FAILED",
                target_type="sales_session",
                target_id=session_id,
                metadata={"error_category": error_cat},
            )
            await conn.commit()

            raise exc


@router.get("/{session_id}/transcript", response_model=TranscriptResponse)
async def get_session_transcript(
    session_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """Retrieves full transcript text, diarization, and word timestamps for authorized parties."""
    async with get_db_connection() as conn:
        session = await _verify_session_access(conn, session_id, current_user)

        if session["status"] != "COMPLETED":
            raise ConflictException(
                f"Transcript is not available (current status: {session['status']})."
            )

        await audit_repo.log_audit_event(
            conn=conn,
            actor_id=current_user["id"],
            actor_role=current_user.get("role"),
            action="TRANSCRIPT_ACCESSED",
            target_type="sales_session",
            target_id=session_id,
        )

        return {
            "session_id": session["id"],
            "status": session["status"],
            "transcript": session["transcript"],
            "detected_language": session["detected_language"],
            "word_segments": session["word_segments"],
            "speaker_diarization": session["speaker_diarization"],
            "provider_model": session["provider_model"],
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
        }
