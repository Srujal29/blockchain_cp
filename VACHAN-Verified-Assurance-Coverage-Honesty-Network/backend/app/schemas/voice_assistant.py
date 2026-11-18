"""
Pydantic schemas for ElevenLabs Conversational Policy Assistant and Spoken Explainability (Phase 5).
Defines request and response contracts for policy Q&A and claim decision audio explainability.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class PolicyAssistantQueryRequest(BaseModel):
    """Customer query request for Conversational Policy Assistant."""

    question: str = Field(
        ...,
        min_length=2,
        max_length=1000,
        description="The customer's natural language question regarding their policy.",
    )
    policy_id: Optional[str] = Field(
        default=None,
        description="Optional policy UUID to scope the question to a specific held policy.",
    )
    language: Optional[str] = Field(
        default="en",
        description="Language code for the response (e.g. 'en', 'hi').",
    )
    voice_output: bool = Field(
        default=True,
        description="Whether to generate synthesized spoken audio along with text answer.",
    )


class PolicyAssistantQueryResponse(BaseModel):
    """Response containing grounded answer, clause references, and optional spoken audio."""

    question: str = Field(..., description="The original or transcribed customer question.")
    answer: str = Field(..., description="Clear, plain-language, policy-grounded answer.")
    policy_id: Optional[str] = Field(default=None, description="Policy UUID answered from.")
    policy_name: Optional[str] = Field(default=None, description="Name of the referenced policy.")
    clause_references: List[str] = Field(
        default_factory=list,
        description="Specific policy sections or clause numbers establishing the answer.",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Grounding confidence score.",
    )
    is_grounded: bool = Field(
        default=True,
        description="Whether the answer is grounded in actual published policy wording.",
    )
    audio_base64: Optional[str] = Field(
        default=None,
        description="Data URI or base64 encoded audio payload for spoken response.",
    )
    audio_format: str = Field(
        default="audio/mpeg",
        description="MIME type of the audio payload (audio/mpeg or audio/wav).",
    )
    audio_duration_seconds: Optional[float] = Field(
        default=None,
        description="Estimated audio duration in seconds.",
    )
    voice_provider: str = Field(
        default="elevenlabs",
        description="Provider used for speech synthesis ('elevenlabs' or 'deterministic_fallback').",
    )


class ClaimSpokenExplanationResponse(BaseModel):
    """Response providing customer-facing spoken explanation of an adjudication decision."""

    claim_id: str = Field(..., description="Claim UUID.")
    claim_number: str = Field(..., description="Human-readable claim tracking number.")
    claim_status: str = Field(..., description="Current status of the claim (e.g. APPROVED, REJECTED).")
    adjudication_decision: str = Field(
        ...,
        description="Underwriting outcome (e.g. APPROVED, REJECTED, UNDER_REVIEW).",
    )
    recorded_reason: str = Field(
        ...,
        description="The actual recorded adjudication reasoning from the approval authority.",
    )
    explanation_text: str = Field(
        ...,
        description="Clear, transparent narrative explanation crafted for the policyholder.",
    )
    audio_base64: Optional[str] = Field(
        default=None,
        description="Data URI or base64 encoded audio bytes for the spoken explanation.",
    )
    audio_format: str = Field(
        default="audio/mpeg",
        description="MIME type of the audio payload.",
    )
    generated_at: str = Field(
        ...,
        description="ISO 8601 timestamp when the spoken explanation was produced.",
    )
    voice_provider: str = Field(
        default="elevenlabs",
        description="Provider used for TTS audio generation.",
    )

