"""Tests for pdf2md.config — settings loading and defaults."""

import pytest

from pdf2md.config import Settings


class TestSettingsDefaults:
    """Verify that default values match the PRD specification."""

    def test_default_domain(self) -> None:
        settings = Settings()
        assert settings.domain == "localhost:8000"

    def test_default_cache_dir(self) -> None:
        settings = Settings()
        assert str(settings.cache_dir) == "cache"

    def test_default_max_pdf_size_mb(self) -> None:
        settings = Settings()
        assert settings.max_pdf_size_mb == 50

    def test_default_cache_ttl_days(self) -> None:
        settings = Settings()
        assert settings.cache_ttl_days == 30

    def test_default_download_timeout(self) -> None:
        settings = Settings()
        assert settings.download_timeout == 30

    def test_default_conversion_timeout(self) -> None:
        settings = Settings()
        assert settings.conversion_timeout == 300


class TestSettingsFromEnv:
    """Verify settings are correctly loaded from environment variables."""

    def test_domain_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PDF2MD_DOMAIN", "pdf2md.example.com")
        settings = Settings()
        assert settings.domain == "pdf2md.example.com"

    def test_max_file_size_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PDF2MD_MAX_FILE_SIZE_MB", "100")
        settings = Settings()
        assert settings.max_file_size_mb == 100

    def test_cache_dir_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PDF2MD_CACHE_DIR", "/tmp/test-cache")
        settings = Settings()
        assert str(settings.cache_dir) == "/tmp/test-cache"


class TestSettingsProperties:
    """Test computed properties."""

    def test_max_pdf_size_bytes_default(self) -> None:
        settings = Settings()
        assert settings.max_pdf_size_bytes == 50 * 1024 * 1024

    def test_max_file_size_bytes_custom(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PDF2MD_MAX_FILE_SIZE_MB", "10")
        settings = Settings()
        assert settings.max_file_size_bytes == 10 * 1024 * 1024
