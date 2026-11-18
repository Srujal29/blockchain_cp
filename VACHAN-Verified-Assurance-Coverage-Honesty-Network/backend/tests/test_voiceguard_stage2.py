"""
Phase 4 — Stage 2 Backend Regression Tests:
VoiceGuard Audio Cloudinary Storage, ElevenLabs Diarization, Gemini Failure Handling, and Transcript Audit.
"""

import io
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import httpx
import pytest
from fastapi import UploadFile

from app.core.exceptions import IntegrationException, NotFoundException, ValidationException
from app.core.security import UserRole
from app.services.elevenlabs_stt import ElevenLabsSTTService
from app.services.evidence_service import EvidenceStorageService, validate_audio_file
from app.services.gemini_verifier import GeminiVerifierService


VALID_M4A = b"\x00\x00\x00\x1cftypM4A \x00\x00\x00\x00M4A mp42isom"
VALID_WAV = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00"


def _make_upload(name: str, data: bytes, mime: str) -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(data), headers={"content-type": mime})


@pytest.mark.asyncio
async def test_audio_upload_validation_success_cleanup_and_cloudinary_failure(monkeypatch):
    """Tests 1, 2, 3, 5, 6: valid upload, invalid format, oversized, Cloudinary failure, and DB cleanup."""
    from app.api.routes.sales_sessions import upload_session_audio

    agent = {"id": str(uuid.uuid4()), "role": UserRole.INSURANCE_AGENT.value}
    session_id = str(uuid.uuid4())
    session_row = {
        "id": session_id,
        "agent_id": agent["id"],
        "customer_id": str(uuid.uuid4()),
        "audio_storage_ref": "voiceguard/sessions/placeholder.m4a",
    }

    # 2. Invalid audio format / spoofed header rejected
    with pytest.raises(ValidationException):
        validate_audio_file("evil.exe", VALID_M4A, "application/octet-stream")
    with pytest.raises(ValidationException):
        validate_audio_file("fake.m4a", b"not-an-m4a-header", "audio/m4a")

    # 3. Oversized audio rejected
    with patch("app.services.evidence_service.get_settings") as mock_settings:
        mock_settings.return_value.MAX_AUDIO_FILE_SIZE_BYTES = 10
        mock_settings.return_value.ALLOWED_AUDIO_MIME_TYPES = ["audio/m4a"]
        with pytest.raises(ValidationException, match="exceeds maximum"):
            validate_audio_file("big.m4a", VALID_M4A, "audio/m4a")

    # 1. Successful real audio upload using mocked Cloudinary transport
    svc = EvidenceStorageService()
    svc._is_configured = True
    with patch("cloudinary.uploader.upload", return_value={"public_id": f"sales_sessions/{session_id}/abc", "bytes": len(VALID_M4A)}):
        ref, checksum, meta = await svc.upload_session_audio(session_id, "rec.m4a", VALID_M4A, "audio/m4a")
    assert ref == f"sales_sessions/{session_id}/abc"
    assert len(checksum) == 64
    assert meta["resource_type"] == "raw"

    # 5. Cloudinary failure raises IntegrationException
    with patch("cloudinary.uploader.upload", side_effect=RuntimeError("Cloudinary 503")):
        with pytest.raises(IntegrationException):
            await svc.upload_session_audio(session_id, "rec.m4a", VALID_M4A, "audio/m4a")

    # 6. DB failure triggers compensating delete_evidence_file cleanup
    delete_mock = AsyncMock()
    mock_cursor = AsyncMock()
    mock_cursor.execute.side_effect = RuntimeError("DB write failure")
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("app.api.routes.sales_sessions.get_db_connection") as mock_db, \
         patch("app.api.routes.sales_sessions._verify_session_access", new=AsyncMock(return_value=session_row)), \
         patch("app.api.routes.sales_sessions.evidence_service.upload_session_audio", new=AsyncMock(return_value=(f"sales_sessions/{session_id}/cleanup", "a" * 64, {"mime_type": "audio/m4a"}))), \
         patch("app.api.routes.sales_sessions.evidence_service.delete_evidence_file", new=delete_mock):
        mock_db.return_value.__aenter__.return_value = mock_conn
        with pytest.raises(RuntimeError, match="DB write failure"):
            await upload_session_audio(
                session_id=session_id,
                file=_make_upload("rec.m4a", VALID_M4A, "audio/m4a"),
                current_user=agent,
            )
    delete_mock.assert_awaited_once_with(f"sales_sessions/{session_id}/cleanup", resource_type="raw")


@pytest.mark.asyncio
async def test_missing_audio_does_not_trigger_sample_fallback():
    """Test 4: Missing or placeholder audio raises ValidationException without calling ElevenLabs."""
    from app.api.routes.sales_sessions import start_session_transcription

    agent = {"id": str(uuid.uuid4()), "role": UserRole.INSURANCE_AGENT.value}
    session_id = str(uuid.uuid4())
    session_row = {
        "id": session_id,
        "agent_id": agent["id"],
        "customer_id": str(uuid.uuid4()),
        "customer_consent": True,
        "status": "PENDING",
        "audio_storage_ref": "local://uploads/nonexistent.m4a",
        "audio_mime_type": "audio/m4a",
    }

    stt_mock = AsyncMock()
    fail_repo_mock = AsyncMock()
    mock_conn = AsyncMock()

    with patch("app.api.routes.sales_sessions.get_db_connection") as mock_db, \
         patch("app.api.routes.sales_sessions._verify_session_access", new=AsyncMock(return_value=session_row)), \
         patch("app.api.routes.sales_sessions.sales_session_repo.acquire_session_for_transcription_atomic", new=AsyncMock(return_value=(True, session_row))), \
         patch("app.api.routes.sales_sessions.audit_repo.log_audit_event", new=AsyncMock()), \
         patch("app.api.routes.sales_sessions.sales_session_repo.update_transcription_failure", new=fail_repo_mock), \
         patch("app.api.routes.sales_sessions.elevenlabs_stt_service.transcribe_audio", new=stt_mock):
        mock_db.return_value.__aenter__.return_value = mock_conn
        with pytest.raises(ValidationException, match="not been uploaded"):
            await start_session_transcription(session_id=session_id, current_user=agent)

    stt_mock.assert_not_called()
    fail_repo_mock.assert_awaited_once()
    assert fail_repo_mock.call_args.kwargs["error_category"] == "MISSING_AUDIO"


@pytest.mark.asyncio
async def test_elevenlabs_word_speaker_diarization_and_malformed_responses(monkeypatch):
    """Tests 7 & 8: Word-level speaker_id grouping with timestamps + malformed/empty response handling."""
    stt = ElevenLabsSTTService()
    monkeypatch.setattr(stt, "_get_api_key", lambda: "test-xi-key")

    # 7. Word-level speaker_id diarization without top-level speakers array
    scribe_payload = {
        "text": "Hello sir, room rent is covered. What about OPD?",
        "language_code": "en",
        "words": [
            {"text": "Hello", "start": 0.1, "end": 0.4, "type": "word", "speaker_id": "speaker_0"},
            {"text": " ", "start": 0.4, "end": 0.45, "type": "spacing", "speaker_id": "speaker_0"},
            {"text": "sir.", "start": 0.45, "end": 0.8, "type": "word", "speaker_id": "speaker_0"},
            {"text": " ", "start": 0.8, "end": 0.9, "type": "spacing", "speaker_id": "speaker_1"},
            {"text": "What", "start": 0.9, "end": 1.1, "type": "word", "speaker_id": "speaker_1"},
            {"text": " ", "start": 1.1, "end": 1.15, "type": "spacing", "speaker_id": "speaker_1"},
            {"text": "about", "start": 1.15, "end": 1.4, "type": "word", "speaker_id": "speaker_1"},
            {"text": " ", "start": 1.4, "end": 1.45, "type": "spacing", "speaker_id": "speaker_1"},
            {"text": "OPD?", "start": 1.45, "end": 1.9, "type": "word", "speaker_id": "speaker_1"},
        ],
    }

    class FakeResp:
        def __init__(self, status_code, json_data=None, bad_json=False):
            self.status_code = status_code
            self._json = json_data
            self._bad_json = bad_json
        def json(self):
            if self._bad_json:
                raise ValueError("Invalid JSON")
            return self._json

    with patch("httpx.post", return_value=FakeResp(200, scribe_payload)):
        res = await stt.transcribe_audio(VALID_WAV, "conv.wav", "audio/wav")

    assert len(res.speaker_diarization) == 2
    assert res.speaker_diarization[0] == {"speaker": "speaker_0", "text": "Hello sir.", "start": 0.1, "end": 0.8}
    assert res.speaker_diarization[1] == {"speaker": "speaker_1", "text": "What about OPD?", "start": 0.9, "end": 1.9}

    # 8a. Malformed JSON
    with patch("httpx.post", return_value=FakeResp(200, bad_json=True)):
        with pytest.raises(IntegrationException, match="malformed JSON"):
            await stt.transcribe_audio(VALID_WAV, "conv.wav", "audio/wav")

    # 8b. Empty transcript
    with patch("httpx.post", return_value=FakeResp(200, {"text": "   ", "words": []})):
        with pytest.raises(IntegrationException, match="empty transcript"):
            await stt.transcribe_audio(VALID_WAV, "conv.wav", "audio/wav")

    # 8c. Route neutrality: verify sales_sessions maps speaker_0/1 to neutral labels Speaker 1, Speaker 2
    from app.api.routes.sales_sessions import start_session_transcription
    agent = {"id": str(uuid.uuid4()), "role": UserRole.INSURANCE_AGENT.value}
    session_id = str(uuid.uuid4())
    session_row = {
        "id": session_id,
        "agent_id": agent["id"],
        "customer_id": str(uuid.uuid4()),
        "customer_consent": True,
        "status": "RECORDED",
        "audio_storage_ref": f"sales_sessions/{session_id}/test.wav",
        "audio_mime_type": "audio/wav",
    }
    success_repo_mock = AsyncMock()
    with patch("app.api.routes.sales_sessions.get_db_connection") as mock_db, \
         patch("app.api.routes.sales_sessions._verify_session_access", new=AsyncMock(return_value=session_row)), \
         patch("app.api.routes.sales_sessions.sales_session_repo.acquire_session_for_transcription_atomic", new=AsyncMock(return_value=(True, session_row))), \
         patch("app.api.routes.sales_sessions.evidence_service.download_private_file_bytes", new=AsyncMock(return_value=VALID_WAV)), \
         patch("app.api.routes.sales_sessions.elevenlabs_stt_service.transcribe_audio", new=AsyncMock(return_value=res)), \
         patch("app.api.routes.sales_sessions.sales_session_repo.update_transcription_success", new=success_repo_mock), \
         patch("app.api.routes.sales_sessions.audit_repo.log_audit_event", new=AsyncMock()):
        mock_db.return_value.__aenter__.return_value = MagicMock()
        await start_session_transcription(session_id=session_id, current_user=agent)

    success_repo_mock.assert_awaited_once()
    saved_turns = success_repo_mock.call_args.kwargs["speaker_diarization"]
    assert len(saved_turns) == 2
    assert saved_turns[0]["speaker"] == "Speaker 1"
    assert saved_turns[0]["text"] == "Hello sir."
    assert saved_turns[1]["speaker"] == "Speaker 2"
    assert saved_turns[1]["text"] == "What about OPD?"


@pytest.mark.asyncio
async def test_gemini_timeout_fallback_and_failed_report_retry(monkeypatch):
    """Tests 9, 10, 11: Gemini timeout model fallback, FAILED report raises error (not 200), and retry increments."""
    from app.api.routes.verification import verify_sales_session_policy

    verifier = GeminiVerifierService()

    # 9. Primary model times out, fallback model succeeds
    calls = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def post(self, url, **kwargs):
            calls.append(url)
            if len(calls) == 1:
                raise httpx.TimeoutException("Primary timed out")
            class OkResp:
                status_code = 200
                def json(self):
                    return {
                        "candidates": [{
                            "content": {
                                "parts": [{
                                    "text": '{"summary": "Fallback ok", "findings": []}'
                                }]
                            }
                        }]
                    }
            return OkResp()

    with patch("httpx.Client", FakeClient), \
         patch("app.services.gemini_verifier.get_settings") as mock_gs:
        mock_gs.return_value.GEMINI_API_KEY = "test-gemini-key"
        mock_gs.return_value.GEMINI_MODEL = "gemini-3.8-flash"
        out = await verifier._call_gemini_api("Hello", "Policy text", {"policy_name": "P1", "policy_code": "C1"})
    assert out["summary"] == "Fallback ok"
    assert len(calls) == 2

    # 10. FAILED report is persisted + committed + raises IntegrationException (never HTTP 200)
    session_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    policy_id = str(uuid.uuid4())
    ver_id = str(uuid.uuid4())
    session_obj = {
        "id": session_id,
        "customer_id": str(uuid.uuid4()),
        "agent_id": agent_id,
        "policy_id": policy_id,
        "policy_version_id": ver_id,
        "status": "COMPLETED",
        "transcript": "Agent: Room rent is covered up to 5 lakhs.",
    }
    mock_conn = AsyncMock()
    update_mock = AsyncMock(return_value={"id": "rep-1", "status": "FAILED"})
    audit_mock = AsyncMock()

    with patch("app.services.gemini_verifier.sales_session_repo.get_session_by_id", new=AsyncMock(return_value=session_obj)), \
         patch("app.services.gemini_verifier.policy_repo.get_policy_by_id", new=AsyncMock(return_value={"id": policy_id, "policy_name": "P1"})), \
         patch("app.services.gemini_verifier.policy_extractor_service.get_or_extract_policy_text", new=AsyncMock(return_value={"extracted_text": "Room rent covered", "status": "COMPLETED"})), \
         patch("app.services.gemini_verifier.verification_repo.create_verification_report", new=AsyncMock(return_value={"id": "rep-1", "report_version": 1})), \
         patch.object(verifier, "_call_gemini_api", new=AsyncMock(side_effect=IntegrationException("Gemini", "All models timed out"))), \
         patch("app.services.gemini_verifier.verification_repo.update_report_results", new=update_mock), \
         patch("app.services.gemini_verifier.audit_repo.log_audit_event", new=audit_mock):
        with pytest.raises(IntegrationException, match="All models timed out"):
            await verifier.verify_sales_session(mock_conn, session_id, agent_id, UserRole.INSURANCE_AGENT.value)

    update_mock.assert_awaited_once()
    assert update_mock.call_args.kwargs["status"] == "FAILED"
    assert audit_mock.call_args.kwargs["action"] == "VERIFY_SALES_PROMISES_FAILED"
    mock_conn.commit.assert_awaited_once()

    # 11. Retry behavior: latest report is FAILED -> verify_sales_session_policy executes retry (does not return FAILED cache)
    completed_report = {"id": "rep-2", "report_version": 2, "status": "COMPLETED"}
    verify_mock = AsyncMock(return_value=completed_report)
    with patch("app.api.routes.verification.get_db_connection") as mock_db, \
         patch("app.api.routes.verification.sales_session_repo.get_session_by_id", new=AsyncMock(return_value=session_obj)), \
         patch("app.api.routes.verification.verification_repo.get_latest_report_for_session", new=AsyncMock(return_value={"id": "rep-1", "status": "FAILED"})), \
         patch("app.api.routes.verification.gemini_verifier_service.verify_sales_session", new=verify_mock):
        mock_db.return_value.__aenter__.return_value = AsyncMock()
        res = await verify_sales_session_policy(session_id, current_user={"id": agent_id, "role": UserRole.INSURANCE_AGENT.value})
    assert res["status"] == "COMPLETED"
    verify_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_audit_transcript_endpoint_existing_and_missing_policies():
    """Test 12: /verification/audit-transcript uses DB policy (no mock fallback), 404 on missing, 502 on Gemini error."""
    from app.api.routes.verification import AuditTranscriptRequest, audit_transcript_direct

    user = {"id": str(uuid.uuid4()), "role": UserRole.INSURANCE_AGENT.value}
    pol_id = str(uuid.uuid4())
    db_policy = {
        "id": pol_id,
        "insurer_name": "VACHAN",
        "policy_name": "Actual DB Policy",
        "policy_code": "DB-01",
        "category": "MEDICAL",
        "coverage_limit": 500000.0,
        "waiting_period_days": 30,
        "claim_filing_window_days": 30,
        "description": "Covers inpatient care.",
    }

    # Missing explicit policy -> 404 NotFoundException
    with patch("app.api.routes.verification.get_db_connection") as mock_db, \
         patch("app.db.repositories.policy_repo.get_policy_by_id", new=AsyncMock(return_value=None)):
        mock_db.return_value.__aenter__.return_value = AsyncMock()
        with pytest.raises(NotFoundException):
            await audit_transcript_direct(AuditTranscriptRequest(transcript="Hello", policy_id=pol_id), current_user=user)

    # Existing DB policy + Gemini success -> returns real findings (not None!)
    with patch("app.api.routes.verification.get_db_connection") as mock_db, \
         patch("app.db.repositories.policy_repo.get_policy_by_id", new=AsyncMock(return_value=db_policy)), \
         patch("app.db.repositories.policy_repo.get_published_version", new=AsyncMock(return_value={"id": "ver-1"})), \
         patch("app.services.policy_extractor.policy_extractor_service.get_or_extract_policy_text", new=AsyncMock(return_value={"extracted_text": "Inpatient care covered up to 500000."})), \
         patch("app.api.routes.verification.gemini_verifier_service._call_gemini_api", new=AsyncMock(return_value={
             "summary": "Real Gemini Audit",
             "findings": [{"promise_text": "Inpatient covered", "verdict": "SUPPORTED"}],
         })), \
         patch("app.db.repositories.audit_repo.log_audit_event", new=AsyncMock()):
        mock_db.return_value.__aenter__.return_value = AsyncMock()
        res = await audit_transcript_direct(AuditTranscriptRequest(transcript="Inpatient covered", policy_id=pol_id), current_user=user)
    assert res["policy_id"] == pol_id
    assert res["supported_count"] == 1
    assert res["overall_status"] == "COMPLIANT"

    # Gemini failure -> raises IntegrationException (never returns mock Hinglish findings)
    with patch("app.api.routes.verification.get_db_connection") as mock_db, \
         patch("app.db.repositories.policy_repo.get_policy_by_id", new=AsyncMock(return_value=db_policy)), \
         patch("app.db.repositories.policy_repo.get_published_version", new=AsyncMock(return_value=None)), \
         patch("app.api.routes.verification.gemini_verifier_service._call_gemini_api", new=AsyncMock(side_effect=IntegrationException("Gemini", "Quota exceeded"))):
        mock_db.return_value.__aenter__.return_value = AsyncMock()
        with pytest.raises(IntegrationException):
            await audit_transcript_direct(AuditTranscriptRequest(transcript="Test", policy_id=pol_id), current_user=user)


@pytest.mark.asyncio
async def test_failure_handling_private_download_and_external_auth():
    """Validates failure-path resilience: private download failure, ElevenLabs 401/429, and Gemini full failure."""
    # 1. Private audio retrieval failure raises IntegrationException
    svc = EvidenceStorageService()
    svc._is_configured = True
    with patch("cloudinary.utils.private_download_url", return_value="https://api.cloudinary.com/download"), \
         patch("httpx.Client.get", return_value=httpx.Response(404, request=httpx.Request("GET", "https://api.cloudinary.com/download"))):
        with pytest.raises(IntegrationException, match="Failed to retrieve private file from secure storage"):
            await svc.download_private_file_bytes("sales_sessions/s1/audio.m4a", mime_type="audio/m4a")

    # 2. ElevenLabs 401 raises immediately without retrying
    stt = ElevenLabsSTTService()
    with patch("httpx.post", return_value=httpx.Response(401, request=httpx.Request("POST", "https://api.elevenlabs.io"))), \
         patch.object(stt, "_get_api_key", return_value="bad-key"):
        with pytest.raises(IntegrationException, match="authentication failed"):
            await stt.transcribe_audio(VALID_WAV, "test.wav", "audio/wav")

    # 3. ElevenLabs 429 retries and raises rate limit exception
    with patch("httpx.post", return_value=httpx.Response(429, request=httpx.Request("POST", "https://api.elevenlabs.io"))), \
         patch.object(stt, "_get_api_key", return_value="test-key"), \
         patch("asyncio.sleep", new=AsyncMock()):
        with pytest.raises(IntegrationException, match="rate limit exceeded"):
            await stt.transcribe_audio(VALID_WAV, "test.wav", "audio/wav")
