"""
ElevenLabs Speech-to-Text (STT) Client and Transcription Service for InsureChain VoiceGuard.
Integrates with ElevenLabs Scribe API (model: scribe_v2) supporting automatic
language detection for English, Hindi, Marathi, and mixed multilingual audio.
"""

from dataclasses import dataclass, field
import io
from typing import Any, Dict, List, Optional
import httpx

from app.core.config import get_settings
from app.core.exceptions import IntegrationException, ValidationException
from app.core.logging import get_logger

logger = get_logger(__name__)

ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"


@dataclass
class TranscriptionResult:
    transcript: str
    detected_language: Optional[str]
    word_segments: List[Dict[str, Any]] = field(default_factory=list)
    speaker_diarization: List[Dict[str, Any]] = field(default_factory=list)
    provider_model: str = "scribe_v2"


class ElevenLabsSTTService:
    """Production interface for ElevenLabs Speech-to-Text API."""

    def __init__(self) -> None:
        pass

    def _get_api_key(self) -> str:
        settings = get_settings()
        key = settings.ELEVEN_LABS_API_KEY or settings.ELEVENLABS_API_KEY
        if not key or not key.strip() or "your_" in key:
            raise IntegrationException(
                service="ElevenLabs",
                message="ELEVEN_LABS_API_KEY is not configured or contains placeholder value.",
            )
        return key.strip()

    async def transcribe_audio(
        self,
        audio_bytes: bytes,
        filename: str = "recording.mp3",
        mime_type: str = "audio/mpeg",
        language_code: Optional[str] = None,
        tag_audio_events: bool = True,
        diarize: bool = True,
    ) -> TranscriptionResult:
        """
        Sends audio to ElevenLabs Scribe API (model: scribe_v2).
        Preserves original multilingual transcript without forced translation.
        """
        settings = get_settings()
        api_key = self._get_api_key()

        # Validate audio content size
        if len(audio_bytes) == 0:
            raise ValidationException("Audio content is empty.")
        if len(audio_bytes) > settings.MAX_AUDIO_FILE_SIZE_BYTES:
            raise ValidationException(
                f"Audio file size ({len(audio_bytes)} bytes) exceeds limit of {settings.MAX_AUDIO_FILE_SIZE_BYTES} bytes."
            )

        headers = {
            "xi-api-key": api_key,
        }

        # Scribe API parameters
        data: Dict[str, Any] = {
            "model_id": settings.ELEVENLABS_STT_MODEL,
        }
        if tag_audio_events:
            data["tag_audio_events"] = "true"
        if diarize:
            data["diarize"] = "true"
        if language_code:
            data["language_code"] = language_code

        def _post_sync() -> httpx.Response:
            return httpx.post(
                ELEVENLABS_STT_URL,
                headers=headers,
                data=data,
                files={"file": (filename, io.BytesIO(audio_bytes), mime_type)},
                timeout=60.0,
            )

        max_retries = 2

        for attempt in range(max_retries + 1):
            try:
                import asyncio
                response = await asyncio.to_thread(_post_sync)

                if response.status_code == 200:
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise IntegrationException(
                            service="ElevenLabs",
                            message="ElevenLabs returned malformed JSON response.",
                        ) from exc

                    if not isinstance(payload, dict):
                        raise IntegrationException(
                            service="ElevenLabs",
                            message="ElevenLabs returned unexpected response structure.",
                        )

                    transcript_text = str(payload.get("text") or "").strip()
                    if not transcript_text:
                        raise IntegrationException(
                            service="ElevenLabs",
                            message="ElevenLabs returned an empty transcript.",
                        )

                    # Extract words and segments safely if present
                    word_segments: List[Dict[str, Any]] = []
                    raw_words = payload.get("words") or payload.get("segments") or []
                    if isinstance(raw_words, list):
                        for w in raw_words:
                            if isinstance(w, dict):
                                word_segments.append({
                                    "text": w.get("text") or w.get("word", ""),
                                    "start": w.get("start"),
                                    "end": w.get("end"),
                                    "speaker_id": w.get("speaker_id"),
                                    "type": w.get("type", "word"),
                                })

                    # Speaker diarization info: prefer explicit speakers turns if non-empty,
                    # otherwise group word_segments by speaker_id (ElevenLabs Scribe v2 format).
                    speaker_diarization: List[Dict[str, Any]] = []
                    raw_speakers = payload.get("speakers") or []
                    if isinstance(raw_speakers, list):
                        for s in raw_speakers:
                            if isinstance(s, dict) and str(s.get("text") or "").strip():
                                speaker_diarization.append(s)

                    if not speaker_diarization and word_segments:
                        speaker_diarization = self._group_words_by_speaker(word_segments)

                    detected_lang = payload.get("language_code") or payload.get("language")

                    return TranscriptionResult(
                        transcript=transcript_text,
                        detected_language=detected_lang,
                        word_segments=word_segments,
                        speaker_diarization=speaker_diarization,
                        provider_model=settings.ELEVENLABS_STT_MODEL,
                    )

                elif response.status_code in (401, 403):
                    logger.error("ElevenLabs authentication failure: HTTP %s", response.status_code)
                    raise IntegrationException(
                        service="ElevenLabs",
                        message="ElevenLabs API key authentication failed.",
                    )

                elif response.status_code == 429:
                    if attempt < max_retries:
                        delay = 0.5 * (2 ** attempt)
                        logger.warning("ElevenLabs rate limit encountered. Retrying in %.1fs...", delay)
                        await asyncio.sleep(delay)
                        continue
                    raise IntegrationException(
                        service="ElevenLabs",
                        message="ElevenLabs API rate limit exceeded.",
                    )

                elif response.status_code >= 500:
                    if attempt < max_retries:
                        delay = 0.5 * (2 ** attempt)
                        logger.warning("ElevenLabs server error (HTTP %s). Retrying in %.1fs...", response.status_code, delay)
                        await asyncio.sleep(delay)
                        continue
                    raise IntegrationException(
                        service="ElevenLabs",
                        message=f"ElevenLabs service temporarily unavailable (HTTP {response.status_code}).",
                    )

                else:
                    logger.error("ElevenLabs unexpected response: HTTP %s", response.status_code)
                    raise IntegrationException(
                        service="ElevenLabs",
                        message=f"Transcription failed: Provider returned HTTP {response.status_code}.",
                    )

            except httpx.TimeoutException as exc:
                if attempt < max_retries:
                    delay = 0.5 * (2 ** attempt)
                    logger.warning("ElevenLabs request timed out. Retrying in %.1fs...", delay)
                    await asyncio.sleep(delay)
                    continue
                raise IntegrationException(
                    service="ElevenLabs",
                    message="ElevenLabs API request timed out.",
                ) from exc

            except httpx.RequestError as exc:
                if attempt < max_retries:
                    delay = 0.5 * (2 ** attempt)
                    logger.warning("ElevenLabs network request error: %s. Retrying in %.1fs...", type(exc).__name__, delay)
                    await asyncio.sleep(delay)
                    continue
                raise IntegrationException(
                    service="ElevenLabs",
                    message="Failed to connect to ElevenLabs API.",
                ) from exc

    @staticmethod
    def _group_words_by_speaker(word_segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Groups consecutive word_segments by speaker_id while preserving timestamps."""
        has_spacing_tokens = any(w.get("type") == "spacing" for w in word_segments)
        turns: List[Dict[str, Any]] = []
        current_speaker: Optional[str] = None
        current_tokens: List[str] = []
        turn_start: Optional[Any] = None
        turn_end: Optional[Any] = None

        def _flush_turn() -> None:
            if not current_tokens:
                return
            joined = "".join(current_tokens) if has_spacing_tokens else " ".join(
                t.strip() for t in current_tokens if t.strip()
            )
            cleaned = joined.strip()
            if cleaned:
                turns.append({
                    "speaker": current_speaker or "speaker_0",
                    "text": cleaned,
                    "start": turn_start,
                    "end": turn_end,
                })

        for seg in word_segments:
            seg_text = str(seg.get("text") or "")
            seg_speaker = seg.get("speaker_id") or current_speaker or "speaker_0"

            if current_speaker is not None and seg_speaker != current_speaker:
                _flush_turn()
                current_tokens = []
                turn_start = None
                turn_end = None

            current_speaker = seg_speaker
            if seg.get("type") != "spacing":
                if turn_start is None and seg.get("start") is not None:
                    turn_start = seg.get("start")
                if seg.get("end") is not None:
                    turn_end = seg.get("end")
            current_tokens.append(seg_text)

        _flush_turn()
        return turns


elevenlabs_stt_service = ElevenLabsSTTService()
