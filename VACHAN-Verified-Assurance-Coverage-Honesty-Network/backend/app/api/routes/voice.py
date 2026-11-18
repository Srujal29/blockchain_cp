"""
Voice and Conversational Policy Assistant API Routes (Phase 5).
Provides:
- POST /api/v1/voice/assistant/query: Customer policy Q&A (text and voice audio input)
- GET /api/v1/voice/status: Non-sensitive status of voice integrations
"""

from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status

from app.api.deps import get_current_active_user, require_active_customer
from app.core.exceptions import ValidationException
from app.db.connection import get_db_connection
from app.schemas.voice_assistant import (
    PolicyAssistantQueryRequest,
    PolicyAssistantQueryResponse,
)
from app.services.voice_assistant import voice_assistant_service

router = APIRouter(prefix="/voice", tags=["Voice & Conversational Policy Assistant"])


@router.post(
    "/assistant/query",
    response_model=PolicyAssistantQueryResponse,
    status_code=status.HTTP_200_OK,
    summary="Ask policy question (text or voice audio)",
)
async def query_policy_assistant(
    request: Request = None,
    request_data: Optional[PolicyAssistantQueryRequest] = None,
    question: Optional[str] = Form(default=None),
    policy_id: Optional[str] = Form(default=None),
    language: Optional[str] = Form(default="en"),
    voice_output: bool = Form(default=True),
    audio_file: Optional[UploadFile] = File(default=None),
    current_user: Dict[str, Any] = Depends(require_active_customer),
) -> PolicyAssistantQueryResponse:
    """
    Submits a natural language policy query to the Conversational Policy Assistant.
    Supports JSON body, or multipart form with optional voice audio recording.
    If an audio file is uploaded, ElevenLabs STT transcribes the speech first.
    Grounds answers in the authenticated customer's published, active policy wording.
    """
    customer_id = current_user["id"]
    active_question = ""
    active_policy_id = None
    active_language = "en"
    active_voice_output = True

    # 1. Parse JSON body if application/json
    if request:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                raw_json = await request.json()
                if isinstance(raw_json, dict):
                    active_question = raw_json.get("question", "")
                    active_policy_id = raw_json.get("policy_id")
                    active_language = raw_json.get("language", "en")
                    if "voice_output" in raw_json:
                        active_voice_output = bool(raw_json["voice_output"])
            except Exception:
                pass

    if request_data:
        if not active_question and request_data.question:
            active_question = request_data.question
        if not active_policy_id and request_data.policy_id:
            active_policy_id = request_data.policy_id
        if request_data.language:
            active_language = request_data.language
        active_voice_output = request_data.voice_output

    # 2. Override with Form fields if multipart
    if isinstance(question, str) and question.strip():
        active_question = question.strip()
    if isinstance(policy_id, str) and policy_id.strip():
        active_policy_id = policy_id.strip()
    if isinstance(language, str) and language.strip():
        active_language = language.strip()
    if isinstance(voice_output, bool):
        active_voice_output = voice_output

    # 3. If audio file provided, transcribe using ElevenLabs STT
    if audio_file and hasattr(audio_file, "read") and hasattr(audio_file, "filename"):
        audio_bytes = await audio_file.read()
        if len(audio_bytes) > 0:
            try:
                stt_res = await voice_assistant_service.tts_service.stt_service.transcribe_audio(
                    audio_bytes=audio_bytes,
                    filename=audio_file.filename or "question.wav",
                    mime_type=audio_file.content_type or "audio/wav",
                )
                if stt_res and stt_res.transcript:
                    active_question = stt_res.transcript.strip()
            except Exception as e:
                # If STT fails and no text provided, raise validation error
                if not active_question:
                    raise ValidationException(f"Failed to transcribe voice question: {str(e)}")

    if not active_question or not active_question.strip():
        raise ValidationException("Please provide a policy question in text or voice.")

    async with get_db_connection() as conn:
        return await voice_assistant_service.answer_policy_query(
            conn=conn,
            customer_id=customer_id,
            question=active_question,
            policy_id=active_policy_id,
            language=active_language,
            voice_output=active_voice_output,
        )


@router.get(
    "/status",
    summary="Voice Assistant and ElevenLabs capability status",
)
async def get_voice_assistant_status(
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """Returns operational status of ElevenLabs STT and TTS services."""
    tts_key_configured = voice_assistant_service.tts_service._get_api_key() is not None
    return {
        "status": "OPERATIONAL",
        "phase": "Phase 5",
        "elevenlabs_tts_configured": tts_key_configured,
        "features": [
            "Customer Conversational Policy Assistant (Text & Voice)",
            "Policy-Grounded Answers with Clause Citations",
            "Spoken Claim Decision Explanations",
            "Deterministic Audio Fallback",
        ],
    }

