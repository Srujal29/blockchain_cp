"""
Unit tests for configuration, secret redaction, and third-party integration modules.
"""

import logging
from app.core.config import Settings
from app.core.exceptions import ConfigurationException
from app.core.logging import RedactingFormatter
from app.integrations.cloudinary_client import CloudinaryClient
from app.integrations.elevenlabs_client import ElevenLabsClient
from app.integrations.gemini_client import GeminiClient, PromiseVerdict


def test_settings_database_url_resolution():
    """Tests resolution and scheme validation of database URLs."""
    # 1. Valid postgresql URL
    settings = Settings(DATABASE_URL="postgresql://user:pass@host:5432/db?sslmode=require")
    assert settings.get_database_url() == "postgresql://user:pass@host:5432/db?sslmode=require"
    assert settings.get_sanitized_database_host() == "host"

    # 2. Alternative DB_URI support
    settings_uri = Settings(DATABASE_URL=None, DB_URI="postgres://user:pass@remote:5432/db")
    assert settings_uri.get_database_url() == "postgres://user:pass@remote:5432/db"
    assert settings_uri.get_sanitized_database_host() == "remote"

    # 3. Missing database URL
    empty_settings = Settings(DATABASE_URL=None, DB_URI=None)
    try:
        empty_settings.get_database_url()
        assert False, "Should raise ConfigurationException"
    except ConfigurationException as exc:
        assert "Database connection string is missing" in exc.message

    # 4. Invalid scheme (e.g. SQLite attempt)
    sqlite_settings = Settings(DATABASE_URL="sqlite:///test.db")
    try:
        sqlite_settings.get_database_url()
        assert False, "Should raise ConfigurationException"
    except ConfigurationException as exc:
        assert "strictly requires a Neon PostgreSQL connection string" in exc.message


def test_cors_frontend_origins_parsing():
    """Tests parsing comma-separated origins and origin lists."""
    settings = Settings(FRONTEND_ORIGINS="http://localhost:5173, http://localhost:3000")
    assert "http://localhost:5173" in settings.FRONTEND_ORIGINS
    assert "http://localhost:3000" in settings.FRONTEND_ORIGINS


def test_secret_redaction_logging():
    """Tests that RedactingFormatter scrubs credentials and API keys."""
    formatter = RedactingFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Connecting to postgresql://admin:SuperSecretPass123@neon-host:5432/db with api_key: AIzaSyD983756281",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    assert "SuperSecretPass123" not in formatted
    assert "postgresql://admin:***@neon-host:5432/db" in formatted
    assert "api_key=***" in formatted or "***" in formatted


def test_integrations_clean_initialization():
    """Tests that third-party integrations initialize and report status safely."""
    cloudinary = CloudinaryClient()
    c_status = cloudinary.get_status()
    assert c_status["service"] == "Cloudinary"
    assert "ready_for_phase2" in c_status

    elevenlabs = ElevenLabsClient()
    e_status = elevenlabs.get_status()
    assert e_status["service"] == "ElevenLabs"
    assert "Speech-to-Text (sales recording transcription)" in e_status["capabilities"]

    gemini = GeminiClient()
    g_status = gemini.get_status()
    assert g_status["service"] == "Google Gemini"
    assert "SUPPORTED" in g_status["supported_verdicts"]
    assert "CONTRADICTED" in g_status["supported_verdicts"]
    assert len(PromiseVerdict) == 5


def test_elevenlabs_client_supports_both_env_key_spellings(monkeypatch):
    """Tests that ElevenLabsClient recognizes both ELEVEN_LABS_API_KEY and ELEVENLABS_API_KEY."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ELEVENLABS_API_KEY", "")
    monkeypatch.setenv("ELEVEN_LABS_API_KEY", "test_key_underscore")
    client = ElevenLabsClient()
    assert client.get_status()["configured"] is True
    get_settings.cache_clear()


def test_cloudinary_client_ignores_placeholder_url(monkeypatch):
    """Tests that placeholder CLOUDINARY_URL does not override explicit Cloudinary credentials."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("CLOUDINARY_URL", "cloudinary://<your_api_key>:<your_api_secret>@demo")
    monkeypatch.setenv("CLOUDINARY_CLOUD_NAME", "explicit_cloud")
    monkeypatch.setenv("CLOUDINARY_API_KEY", "123456")
    monkeypatch.setenv("CLOUDINARY_API_SECRET", "abcdef")
    client = CloudinaryClient()
    status = client.get_status()
    assert status["configured"] is True
    assert status["cloud_name"] == "explicit_cloud"
    get_settings.cache_clear()
