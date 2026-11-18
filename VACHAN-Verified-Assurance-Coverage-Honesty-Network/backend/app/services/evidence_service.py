"""
Secure Evidence Upload and Access Service for InsureChain VoiceGuard.
Enforces file format whitelisting, size restrictions, magic byte validation,
SHA-256 checksums, Cloudinary private asset uploads, signed URL generation,
and compensating transaction cleanups.
"""

from datetime import datetime, timezone
import hashlib
import io
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import uuid

import cloudinary
import cloudinary.uploader
import cloudinary.utils

from app.core.config import get_settings
from app.core.exceptions import IntegrationException, ValidationException
from app.core.logging import get_logger

logger = get_logger(__name__)

# Magic byte signatures for supported binary document types
MAGIC_BYTES = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/webp": [b"RIFF"],
    "application/pdf": [b"%PDF-"],
}

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}

EXTENSION_TO_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}

MIME_TO_FORMAT = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "audio/m4a": "m4a",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/ogg": "ogg",
    "audio/webm": "webm",
    "audio/aac": "aac",
}

ALLOWED_AUDIO_EXTENSIONS = {".m4a", ".mp4", ".mp3", ".wav", ".ogg", ".webm", ".aac"}

AUDIO_EXTENSION_TO_MIME = {
    ".m4a": "audio/m4a",
    ".mp4": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
    ".aac": "audio/aac",
}

AUDIO_EXTENSION_TO_FORMAT = {
    ".m4a": "m4a",
    ".mp4": "mp4",
    ".mp3": "mp3",
    ".wav": "wav",
    ".ogg": "ogg",
    ".webm": "webm",
    ".aac": "aac",
}


def _matches_audio_magic_bytes(content: bytes, ext: str) -> bool:
    """Validates binary container/frame headers for supported audio formats."""
    if ext in (".m4a", ".mp4"):
        return len(content) >= 8 and content[4:8] == b"ftyp"
    if ext == ".wav":
        return content.startswith(b"RIFF") and len(content) >= 12 and content[8:12] == b"WAVE"
    if ext == ".mp3":
        return content.startswith(b"ID3") or (
            len(content) >= 2 and content[0] == 0xFF and (content[1] & 0xE0) == 0xE0
        )
    if ext == ".ogg":
        return content.startswith(b"OggS")
    if ext == ".webm":
        return content.startswith(b"\x1a\x45\xdf\xa3")
    if ext == ".aac":
        return content.startswith(b"ADIF") or (
            len(content) >= 2 and content[0] == 0xFF and (content[1] & 0xF0) == 0xF0
        )
    return False


def validate_audio_file(filename: str, content: bytes, declared_mime: str) -> Tuple[str, str]:
    """
    Validates sales session audio size, extension, declared MIME, and magic bytes.
    Returns (verified_mime, format_ext) or raises ValidationException.
    """
    settings = get_settings()

    if len(content) == 0:
        raise ValidationException("Uploaded audio file cannot be empty.")
    if len(content) > settings.MAX_AUDIO_FILE_SIZE_BYTES:
        raise ValidationException(
            f"Audio file size ({len(content)} bytes) exceeds maximum permitted limit "
            f"of {settings.MAX_AUDIO_FILE_SIZE_BYTES} bytes."
        )

    ext = Path(filename or "recording.m4a").suffix.lower()
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise ValidationException(
            f"Invalid audio extension '{ext}'. Allowed extensions: {', '.join(sorted(ALLOWED_AUDIO_EXTENSIONS))}."
        )

    expected_mime = AUDIO_EXTENSION_TO_MIME[ext]
    norm_declared = (declared_mime or "").lower().split(";")[0].strip()
    if norm_declared and norm_declared != "application/octet-stream":
        allowed_mimes = {m.lower() for m in settings.ALLOWED_AUDIO_MIME_TYPES} | set(AUDIO_EXTENSION_TO_MIME.values())
        if norm_declared not in allowed_mimes and not norm_declared.startswith("audio/"):
            raise ValidationException(f"Unsupported audio MIME type '{declared_mime}'.")

    if not _matches_audio_magic_bytes(content, ext):
        raise ValidationException(
            f"Audio file content does not match expected binary header for '{ext}'."
        )

    return expected_mime, AUDIO_EXTENSION_TO_FORMAT[ext]


def compute_sha256(content: bytes) -> str:
    """Computes SHA-256 cryptographic checksum of file content."""
    return hashlib.sha256(content).hexdigest()


def _matches_magic_bytes(content: bytes, mime_type: str) -> bool:
    signatures = MAGIC_BYTES.get(mime_type)
    if not signatures:
        return False
    for sig in signatures:
        if mime_type == "image/webp":
            if content.startswith(b"RIFF") and len(content) >= 12 and content[8:12] == b"WEBP":
                return True
        elif content.startswith(sig):
            return True
    return False


def validate_file(filename: str, content: bytes, declared_mime: str) -> str:
    """
    Validates file extension, declared MIME, size limits, and magic bytes.
    Does not trust client-provided MIME types alone.
    Returns server-verified MIME type or raises ValidationException.
    """
    settings = get_settings()

    # 1. Check size limit
    if len(content) == 0:
        raise ValidationException("Uploaded file cannot be empty.")
    if len(content) > settings.MAX_EVIDENCE_FILE_SIZE_BYTES:
        raise ValidationException(
            f"File size ({len(content)} bytes) exceeds maximum permitted limit "
            f"of {settings.MAX_EVIDENCE_FILE_SIZE_BYTES} bytes ({settings.MAX_EVIDENCE_FILE_SIZE_BYTES // (1024 * 1024)}MB)."
        )

    # 2. Check extension
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationException(
            f"Invalid file extension '{ext}'. Allowed extensions are: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
        )

    expected_mime = EXTENSION_TO_MIME[ext]
    norm_declared = (declared_mime or "").lower().strip()
    if norm_declared and norm_declared != "application/octet-stream":
        if norm_declared not in settings.ALLOWED_EVIDENCE_MIME_TYPES:
            raise ValidationException(
                f"Unsupported MIME type '{declared_mime}'. Allowed MIME types: {', '.join(settings.ALLOWED_EVIDENCE_MIME_TYPES)}."
            )
        if norm_declared != expected_mime:
            raise ValidationException(
                f"File extension '{ext}' does not match declared MIME type '{declared_mime}'."
            )

    # 3. Verify magic bytes signature against server-expected MIME
    if not _matches_magic_bytes(content, expected_mime):
        raise ValidationException(
            f"File content does not match expected binary signature for '{expected_mime}'."
        )

    return expected_mime


from urllib.parse import urlparse


class EvidenceStorageService:
    """Handles secure file upload and access via Cloudinary private storage."""

    def __init__(self) -> None:
        self._is_configured: bool = False
        self._cloud_name: Optional[str] = None
        self._api_key: Optional[str] = None
        self._api_secret: Optional[str] = None
        self._setup_cloudinary()

    def _setup_cloudinary(self) -> None:
        settings = get_settings()
        cloud_name = settings.CLOUDINARY_CLOUD_NAME
        api_key = settings.CLOUDINARY_API_KEY
        api_secret = settings.CLOUDINARY_API_SECRET

        if (
            (not cloud_name or not api_key or not api_secret)
            and settings.CLOUDINARY_URL
            and "<your_" not in settings.CLOUDINARY_URL
            and "your_" not in settings.CLOUDINARY_URL
        ):
            try:
                parsed = urlparse(settings.CLOUDINARY_URL)
                if parsed.hostname:
                    cloud_name = cloud_name or parsed.hostname
                if parsed.username:
                    api_key = api_key or parsed.username
                if parsed.password:
                    api_secret = api_secret or parsed.password
            except Exception:
                pass

        if cloud_name and api_key and api_secret:
            if "<your_" not in api_key and "<your_" not in api_secret and "<your_" not in cloud_name:
                self._cloud_name = cloud_name
                self._api_key = api_key
                self._api_secret = api_secret
                cloudinary.config(
                    cloud_name=cloud_name,
                    api_key=api_key,
                    api_secret=api_secret,
                    secure=True,
                )
                self._is_configured = True

    async def upload_evidence(
        self,
        claim_id: str,
        filename: str,
        content: bytes,
        declared_mime: str,
    ) -> Tuple[str, str, Dict[str, Any]]:
        """
        Validates and uploads evidence to Cloudinary private storage.
        Returns (document_storage_ref, checksum, resource_metadata).
        """
        norm_mime = validate_file(filename, content, declared_mime)
        checksum = compute_sha256(content)
        settings = get_settings()

        storage_id = f"claims/{claim_id}/evidence_{uuid.uuid4().hex[:12]}"
        resource_type = "raw" if norm_mime == "application/pdf" else "image"

        if not self._is_configured:
            raise IntegrationException(
                service="Cloudinary",
                message="Cloudinary storage is not configured for evidence uploads.",
            )

        try:
            upload_result = cloudinary.uploader.upload(
                file=io.BytesIO(content),
                public_id=storage_id,
                type="private",
                resource_type=resource_type,
                tags=["claim_evidence", f"claim_{claim_id}"],
                overwrite=True,
            )
            metadata = {
                "public_id": upload_result.get("public_id", storage_id),
                "resource_type": resource_type,
                "format": upload_result.get("format", norm_mime.split("/")[-1]),
                "bytes": upload_result.get("bytes", len(content)),
                "created_at": upload_result.get("created_at"),
            }
            return storage_id, checksum, metadata

        except Exception as exc:
            logger.error("Cloudinary upload failed: %s", type(exc).__name__)
            raise IntegrationException(
                service="Cloudinary",
                message="Failed to upload evidence document to secure storage.",
            ) from exc

    async def upload_policy_pdf(
        self,
        policy_id: str,
        version_number: int,
        filename: str,
        content: bytes,
        declared_mime: str,
    ) -> Tuple[str, str, Dict[str, Any]]:
        """
        Validates and uploads a policy PDF to Cloudinary private raw storage.
        Never overwrites historical policy versions (uses unique versioned public_id).
        Returns (document_storage_ref, checksum, resource_metadata).
        """
        norm_mime = validate_file(filename, content, declared_mime)
        if norm_mime != "application/pdf":
            raise ValidationException("Only PDF documents are permitted for policy wordings.")

        checksum = compute_sha256(content)
        storage_id = f"policies/{policy_id}/v{version_number}_{uuid.uuid4().hex[:8]}"

        if not self._is_configured:
            raise IntegrationException(
                service="Cloudinary",
                message="Cloudinary storage is not configured for policy uploads.",
            )

        try:
            upload_result = cloudinary.uploader.upload(
                file=io.BytesIO(content),
                public_id=storage_id,
                type="private",
                resource_type="raw",
                tags=["policy_document", f"policy_{policy_id}", f"v{version_number}"],
                overwrite=False,
            )
            metadata = {
                "public_id": upload_result.get("public_id", storage_id),
                "resource_type": "raw",
                "format": "pdf",
                "bytes": upload_result.get("bytes", len(content)),
                "created_at": upload_result.get("created_at"),
            }
            return storage_id, checksum, metadata
        except Exception as exc:
            logger.error("Cloudinary policy PDF upload failed: %s", type(exc).__name__)
            raise IntegrationException(
                service="Cloudinary",
                message="Failed to upload policy PDF to secure storage.",
            ) from exc

    async def upload_session_audio(
        self,
        session_id: str,
        filename: str,
        content: bytes,
        declared_mime: str,
    ) -> Tuple[str, str, Dict[str, Any]]:
        """
        Validates and uploads recorded sales session audio to Cloudinary private raw storage.
        Returns (audio_storage_ref, checksum, metadata).
        """
        verified_mime, fmt = validate_audio_file(filename, content, declared_mime)
        checksum = compute_sha256(content)
        storage_id = f"sales_sessions/{session_id}/{uuid.uuid4().hex[:12]}"

        if not self._is_configured:
            raise IntegrationException(
                service="Cloudinary",
                message="Cloudinary private storage is not configured for audio uploads.",
            )

        try:
            upload_result = cloudinary.uploader.upload(
                file=io.BytesIO(content),
                public_id=storage_id,
                type="private",
                resource_type="raw",
                format=fmt,
                tags=["sales_session_audio", f"session_{session_id}"],
                overwrite=False,
            )
            returned_public_id = upload_result.get("public_id", storage_id)
            metadata = {
                "public_id": returned_public_id,
                "resource_type": "raw",
                "format": fmt,
                "mime_type": verified_mime,
                "bytes": upload_result.get("bytes", len(content)),
                "created_at": upload_result.get("created_at"),
            }
            return returned_public_id, checksum, metadata
        except IntegrationException:
            raise
        except Exception as exc:
            logger.error("Cloudinary session audio upload failed: %s", type(exc).__name__)
            raise IntegrationException(
                service="Cloudinary",
                message="Failed to upload sales session audio to secure storage.",
            ) from exc

    async def download_private_file_bytes(
        self,
        document_storage_ref: str,
        mime_type: str,
        expires_in_seconds: int = 300,
    ) -> bytes:
        """
        Downloads private asset bytes from Cloudinary using a short-lived signed URL.
        """
        import asyncio
        import httpx

        signed_url = await self.generate_signed_url(
            document_storage_ref=document_storage_ref,
            mime_type=mime_type,
            expires_in_seconds=expires_in_seconds,
        )

        def _fetch_sync() -> bytes:
            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                resp = client.get(signed_url)
                resp.raise_for_status()
                return resp.content

        try:
            data = await asyncio.to_thread(_fetch_sync)
        except Exception as exc:
            logger.error("Failed to download private Cloudinary asset %s: %s", document_storage_ref, type(exc).__name__)
            raise IntegrationException(
                service="Cloudinary",
                message="Failed to retrieve private file from secure storage.",
            ) from exc

        if not data:
            raise IntegrationException(
                service="Cloudinary",
                message="Retrieved empty file from secure storage.",
            )
        return data

    async def generate_signed_url(
        self,
        document_storage_ref: str,
        mime_type: str,
        expires_in_seconds: int = 300,
    ) -> str:
        """
        Generates a short-lived signed access URL for private evidence documents
        using Cloudinary's private_download_url with server-enforced expiry.
        """
        norm_mime = (mime_type or "").lower().split(";")[0].strip()
        is_raw = norm_mime == "application/pdf" or norm_mime.startswith("audio/")
        resource_type = "raw" if is_raw else "image"
        fmt = MIME_TO_FORMAT.get(norm_mime, "m4a" if norm_mime.startswith("audio/") else ("pdf" if resource_type == "raw" else "jpg"))
        expires_at = int(datetime.now(timezone.utc).timestamp()) + expires_in_seconds

        if not self._is_configured:
            raise IntegrationException(
                service="Cloudinary",
                message="Cloudinary storage is not configured for generating signed URLs.",
            )

        try:
            signed_url = cloudinary.utils.private_download_url(
                document_storage_ref,
                fmt,
                type="private",
                resource_type=resource_type,
                expires_at=expires_at,
            )
            return signed_url
        except Exception as exc:
            logger.error("Failed to generate Cloudinary signed URL: %s", type(exc).__name__)
            raise IntegrationException(
                service="Cloudinary",
                message="Failed to generate secure signed access URL.",
            ) from exc

    async def delete_evidence_file(
        self,
        document_storage_ref: str,
        resource_type: str = "image",
    ) -> None:
        """
        Compensating cleanup: deletes uploaded file from Cloudinary if database persistence fails.
        """
        if not self._is_configured:
            return
        try:
            cloudinary.uploader.destroy(
                document_storage_ref,
                type="private",
                resource_type=resource_type,
            )
            logger.info("Successfully executed compensating cleanup for %s", document_storage_ref)
        except Exception as exc:
            logger.warning("Compensating cleanup for %s failed: %s", document_storage_ref, type(exc).__name__)


evidence_service = EvidenceStorageService()
