"""
Unit tests for GeminiVerifierService timeout and model fallback handling,
and EmailService reserved-domain / test-mode safeguards.
"""

import json
import httpx
import pytest

from app.core.config import get_settings
from app.core.exceptions import IntegrationException
from app.services.email_service import EmailService
from app.services.gemini_verifier import GeminiVerifierService


@pytest.mark.asyncio
async def test_gemini_primary_timeout_falls_back_to_next_model(monkeypatch):
    """Primary model ReadTimeout should trigger fallback to the next configured model."""
    get_settings.cache_clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_key_unit")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")

    called_urls = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json=None):
            called_urls.append(url)
            if "gemini-3.8-flash" in url:
                raise httpx.ReadTimeout("Simulated primary model timeout")
            return httpx.Response(
                200,
                content=b'{"candidates":[{"content":{"parts":[{"text":"{\\"summary\\":\\"OK\\",\\"overall_integrity_status\\":\\"VERIFIED\\",\\"findings\\":[]}"}]}}]}',
            )

    monkeypatch.setattr(httpx, "Client", FakeClient)

    service = GeminiVerifierService()
    result = await service._call_gemini_api(
        transcript="Agent: Waiting period is 30 days.",
        policy_text="General waiting period is 30 days.",
        policy_meta={"policy_name": "Care Premier"},
    )

    assert result["overall_integrity_status"] == "VERIFIED"
    assert len(called_urls) == 2
    assert "gemini-3.8-flash" in called_urls[0]
    assert "gemini-3.1-flash-lite" in called_urls[1]
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_gemini_all_models_timeout_raises_integration_exception(monkeypatch):
    """When all configured Gemini models fail or time out, raise IntegrationException."""
    get_settings.cache_clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_key_unit")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")

    called_urls = []

    class FakeFailingClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json=None):
            called_urls.append(url)
            raise httpx.ConnectError("Simulated network error")

    monkeypatch.setattr(httpx, "Client", FakeFailingClient)

    service = GeminiVerifierService()
    with pytest.raises(IntegrationException) as exc_info:
        await service._call_gemini_api(
            transcript="Agent: Zero waiting period.",
            policy_text="General waiting period is 30 days.",
            policy_meta={"policy_name": "Care Premier"},
        )

    assert "ConnectError" in exc_info.value.message
    assert len(called_urls) == 3
    get_settings.cache_clear()


def test_email_service_skips_smtp_for_reserved_domains(monkeypatch):
    """Reserved test domains like @example.com must never trigger real SMTP delivery."""
    get_settings.cache_clear()
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")

    def _forbid_smtp(*args, **kwargs):
        raise AssertionError("SMTP should not be called for @example.com")

    monkeypatch.setattr("smtplib.SMTP_SSL", _forbid_smtp)
    monkeypatch.setattr("smtplib.SMTP", _forbid_smtp)

    svc = EmailService()
    ok = svc.send_verification_email("cust_test@example.com", "raw-token-123")
    assert ok is True
    get_settings.cache_clear()

