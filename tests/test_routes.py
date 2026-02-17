"""Tests for pdf2md.main — FastAPI route handlers."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from pdf2md.cache import CacheEntry, DiskCache
from pdf2md.config import Settings
from pdf2md.converter import ConversionError, ConversionResult, ConversionTimeoutError
from pdf2md.downloader import (
    DownloadError,
    DownloadResult,
    InvalidPDFURLError,
    PDFNotFoundError,
    PDFTooLargeError,
)
from pdf2md.main import app, _get_settings, _get_cache


@pytest.fixture(autouse=True)
def _clear_caches():
    """Clear lru_cache between tests so each test gets fresh settings/cache."""
    _get_settings.cache_clear()
    _get_cache.cache_clear()
    yield
    _get_settings.cache_clear()
    _get_cache.cache_clear()


@pytest.fixture()
def tmp_cache(tmp_path):
    """Provide a temporary cache directory and override the app's cache."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    return cache_dir


@pytest.fixture()
def client(tmp_cache, monkeypatch):
    """Provide a test client with a temp cache directory."""
    monkeypatch.setenv("PDF2MD_CACHE_DIR", str(tmp_cache))
    monkeypatch.setenv("PDF2MD_DOMAIN", "test.pdf2md.com")
    _get_settings.cache_clear()
    _get_cache.cache_clear()
    return TestClient(app)


class TestRootRoute:
    """GET / should return usage instructions as text/markdown."""

    def test_root_returns_200(self, client) -> None:
        response = client.get("/")
        assert response.status_code == 200

    def test_root_returns_markdown_content_type(self, client) -> None:
        response = client.get("/")
        assert "text/markdown" in response.headers["content-type"]

    def test_root_contains_usage_heading(self, client) -> None:
        response = client.get("/")
        assert "# pdf2md" in response.text

    def test_root_contains_domain(self, client) -> None:
        response = client.get("/")
        assert "test.pdf2md.com" in response.text


class TestImageRoute:
    """GET /images/<hash>/<filename> should serve cached images."""

    def test_missing_image_returns_404(self, client) -> None:
        response = client.get("/images/abc123/fig1.png")
        assert response.status_code == 404

    def test_existing_image_returns_200(self, client, tmp_cache) -> None:
        # Manually create a cached image
        cache = DiskCache(tmp_cache)
        cache.put(
            "https://example.com/doc.pdf",
            "# Doc",
            {"fig1.png": b"\x89PNG_FAKE"},
            page_count=1,
        )
        from pdf2md.cache import url_to_cache_key
        key = url_to_cache_key("https://example.com/doc.pdf")
        response = client.get(f"/images/{key}/fig1.png")
        assert response.status_code == 200

    def test_existing_image_has_cache_control(self, client, tmp_cache) -> None:
        cache = DiskCache(tmp_cache)
        cache.put("https://example.com/doc.pdf", "# Doc", {"fig1.png": b"\x89PNG_FAKE"}, page_count=1)
        from pdf2md.cache import url_to_cache_key
        key = url_to_cache_key("https://example.com/doc.pdf")
        response = client.get(f"/images/{key}/fig1.png")
        assert "max-age=31536000" in response.headers.get("cache-control", "")


class TestConvertRoute:
    """GET /<host>/<path> should download, convert, and return markdown."""

    def test_invalid_path_returns_400(self, client) -> None:
        # A path with no slash separator (just a host, no path) is invalid
        response = client.get("/example.com")
        assert response.status_code == 400

    @patch("pdf2md.main.convert_pdf")
    @patch("pdf2md.main.download_pdf")
    def test_successful_conversion_returns_200(self, mock_download, mock_convert, client) -> None:
        mock_download.return_value = DownloadResult(
            content=b"%PDF-fake",
            content_type="application/pdf",
            source_url="https://example.com/doc.pdf",
        )
        mock_convert.return_value = ConversionResult(
            markdown="# Converted",
            images={},
            page_count=3,
        )
        response = client.get("/example.com/doc.pdf")
        assert response.status_code == 200

    @patch("pdf2md.main.convert_pdf")
    @patch("pdf2md.main.download_pdf")
    def test_successful_conversion_returns_markdown_type(self, mock_download, mock_convert, client) -> None:
        mock_download.return_value = DownloadResult(
            content=b"%PDF-fake",
            content_type="application/pdf",
            source_url="https://example.com/doc.pdf",
        )
        mock_convert.return_value = ConversionResult(
            markdown="# Converted",
            images={},
            page_count=3,
        )
        response = client.get("/example.com/doc.pdf")
        assert "text/markdown" in response.headers["content-type"]

    @patch("pdf2md.main.convert_pdf")
    @patch("pdf2md.main.download_pdf")
    def test_response_has_source_url_header(self, mock_download, mock_convert, client) -> None:
        mock_download.return_value = DownloadResult(
            content=b"%PDF-fake",
            content_type="application/pdf",
            source_url="https://example.com/doc.pdf",
        )
        mock_convert.return_value = ConversionResult(
            markdown="# Converted",
            images={},
            page_count=3,
        )
        response = client.get("/example.com/doc.pdf")
        assert response.headers["x-source-url"] == "https://example.com/doc.pdf"

    @patch("pdf2md.main.convert_pdf")
    @patch("pdf2md.main.download_pdf")
    def test_response_has_page_count_header(self, mock_download, mock_convert, client) -> None:
        mock_download.return_value = DownloadResult(
            content=b"%PDF-fake",
            content_type="application/pdf",
            source_url="https://example.com/doc.pdf",
        )
        mock_convert.return_value = ConversionResult(
            markdown="# Converted",
            images={},
            page_count=7,
        )
        response = client.get("/example.com/doc.pdf")
        assert response.headers["x-page-count"] == "7"

    @patch("pdf2md.main.convert_pdf")
    @patch("pdf2md.main.download_pdf")
    def test_response_has_cached_false_header_on_fresh(self, mock_download, mock_convert, client) -> None:
        mock_download.return_value = DownloadResult(
            content=b"%PDF-fake",
            content_type="application/pdf",
            source_url="https://example.com/doc.pdf",
        )
        mock_convert.return_value = ConversionResult(
            markdown="# Converted",
            images={},
            page_count=1,
        )
        response = client.get("/example.com/doc.pdf")
        assert response.headers["x-cached"] == "false"

    @patch("pdf2md.main.download_pdf")
    def test_download_404_returns_404(self, mock_download, client) -> None:
        mock_download.side_effect = PDFNotFoundError("PDF not found at source URL.")
        response = client.get("/example.com/missing.pdf")
        assert response.status_code == 404

    @patch("pdf2md.main.download_pdf")
    def test_download_error_returns_502(self, mock_download, client) -> None:
        mock_download.side_effect = DownloadError("Could not download PDF.", status_code=502)
        response = client.get("/example.com/broken.pdf")
        assert response.status_code == 502

    @patch("pdf2md.main.download_pdf")
    def test_invalid_pdf_url_returns_400(self, mock_download, client) -> None:
        mock_download.side_effect = InvalidPDFURLError("URL does not point to a valid PDF.")
        response = client.get("/example.com/notapdf.html")
        assert response.status_code == 400

    @patch("pdf2md.main.download_pdf")
    def test_too_large_returns_413(self, mock_download, client) -> None:
        mock_download.side_effect = PDFTooLargeError("PDF exceeds maximum size of 50MB.")
        response = client.get("/example.com/huge.pdf")
        assert response.status_code == 413

    @patch("pdf2md.main.convert_pdf")
    @patch("pdf2md.main.download_pdf")
    def test_conversion_timeout_returns_504(self, mock_download, mock_convert, client) -> None:
        mock_download.return_value = DownloadResult(
            content=b"%PDF-fake",
            content_type="application/pdf",
            source_url="https://example.com/doc.pdf",
        )
        mock_convert.side_effect = ConversionTimeoutError()
        response = client.get("/example.com/doc.pdf")
        assert response.status_code == 504

    @patch("pdf2md.main.convert_pdf")
    @patch("pdf2md.main.download_pdf")
    def test_conversion_error_returns_400(self, mock_download, mock_convert, client) -> None:
        mock_download.return_value = DownloadResult(
            content=b"%PDF-fake",
            content_type="application/pdf",
            source_url="https://example.com/corrupt.pdf",
        )
        mock_convert.side_effect = ConversionError("Could not parse PDF.")
        response = client.get("/example.com/corrupt.pdf")
        assert response.status_code == 400

    @patch("pdf2md.main.convert_pdf")
    @patch("pdf2md.main.download_pdf")
    def test_error_responses_are_markdown(self, mock_download, mock_convert, client) -> None:
        mock_download.side_effect = PDFNotFoundError("PDF not found at source URL.")
        response = client.get("/example.com/missing.pdf")
        assert "# Error" in response.text


class TestCacheHit:
    """Test that cached results are returned correctly."""

    @patch("pdf2md.main.convert_pdf")
    @patch("pdf2md.main.download_pdf")
    def test_second_request_is_cached(self, mock_download, mock_convert, client) -> None:
        mock_download.return_value = DownloadResult(
            content=b"%PDF-fake",
            content_type="application/pdf",
            source_url="https://example.com/doc.pdf",
        )
        mock_convert.return_value = ConversionResult(
            markdown="# Cached Result",
            images={},
            page_count=2,
        )
        # First request — cache miss
        client.get("/example.com/doc.pdf")
        # Second request — should hit cache
        response = client.get("/example.com/doc.pdf")
        assert response.headers["x-cached"] == "true"

    @patch("pdf2md.main.convert_pdf")
    @patch("pdf2md.main.download_pdf")
    def test_cached_response_has_zero_conversion_time(self, mock_download, mock_convert, client) -> None:
        mock_download.return_value = DownloadResult(
            content=b"%PDF-fake",
            content_type="application/pdf",
            source_url="https://example.com/doc.pdf",
        )
        mock_convert.return_value = ConversionResult(
            markdown="# Doc",
            images={},
            page_count=1,
        )
        client.get("/example.com/doc.pdf")
        response = client.get("/example.com/doc.pdf")
        assert response.headers["x-conversion-time-ms"] == "0"
