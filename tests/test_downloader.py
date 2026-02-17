"""Tests for pdf2md.downloader — PDF fetching and validation."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from pdf2md.downloader import (
    DownloadError,
    DownloadTimeoutError,
    InvalidPDFURLError,
    PDFNotFoundError,
    PDFTooLargeError,
    download_pdf,
    normalize_url,
)


class TestNormalizeUrl:
    """Verify URL construction from host + path segments."""

    def test_basic_url(self) -> None:
        assert normalize_url("example.com", "doc.pdf") == "https://example.com/doc.pdf"

    def test_url_with_path(self) -> None:
        result = normalize_url("arxiv.org", "pdf/2301.00001v1.pdf")
        assert result == "https://arxiv.org/pdf/2301.00001v1.pdf"

    def test_url_with_port(self) -> None:
        result = normalize_url("site.com:8080", "file.pdf")
        assert result == "https://site.com:8080/file.pdf"

    def test_always_uses_https(self) -> None:
        result = normalize_url("example.com", "doc.pdf")
        assert result.startswith("https://")


def _make_mock_response(status_code: int, content: bytes = b"", headers: dict | None = None):
    """Build a mock httpx response that works with async streaming."""
    mock_response = AsyncMock()
    mock_response.status_code = status_code
    mock_response.headers = httpx.Headers(headers or {})
    mock_response.aread = AsyncMock(return_value=content)

    # Support async context manager (for client.stream())
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)
    return mock_response


def _make_mock_client(mock_response):
    """Build a mock httpx.AsyncClient that returns the given response from stream()."""
    mock_client = AsyncMock()
    mock_client.stream = MagicMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


class TestDownloadPdfErrors:
    """Test error handling for various failure modes."""

    @pytest.mark.asyncio
    async def test_404_raises_pdf_not_found(self) -> None:
        mock_resp = _make_mock_response(404)
        mock_client = _make_mock_client(mock_resp)
        with patch("pdf2md.downloader.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(PDFNotFoundError):
                await download_pdf(
                    "https://example.com/missing.pdf",
                    max_size_bytes=50 * 1024 * 1024,
                    timeout=10,
                )

    @pytest.mark.asyncio
    async def test_401_raises_download_error_with_502(self) -> None:
        mock_resp = _make_mock_response(401)
        mock_client = _make_mock_client(mock_resp)
        with patch("pdf2md.downloader.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(DownloadError) as exc_info:
                await download_pdf(
                    "https://example.com/private.pdf",
                    max_size_bytes=50 * 1024 * 1024,
                    timeout=10,
                )
            assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_403_raises_download_error_with_502(self) -> None:
        mock_resp = _make_mock_response(403)
        mock_client = _make_mock_client(mock_resp)
        with patch("pdf2md.downloader.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(DownloadError) as exc_info:
                await download_pdf(
                    "https://example.com/forbidden.pdf",
                    max_size_bytes=50 * 1024 * 1024,
                    timeout=10,
                )
            assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_non_pdf_content_raises_invalid_url(self) -> None:
        mock_resp = _make_mock_response(200, b"<html>Not a PDF</html>")
        mock_client = _make_mock_client(mock_resp)
        with patch("pdf2md.downloader.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(InvalidPDFURLError):
                await download_pdf(
                    "https://example.com/page.html",
                    max_size_bytes=50 * 1024 * 1024,
                    timeout=10,
                )

    @pytest.mark.asyncio
    async def test_oversized_content_length_raises_too_large(self) -> None:
        mock_resp = _make_mock_response(
            200,
            b"%PDF-fake",
            headers={"content-length": str(100 * 1024 * 1024)},
        )
        mock_client = _make_mock_client(mock_resp)
        with patch("pdf2md.downloader.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(PDFTooLargeError):
                await download_pdf(
                    "https://example.com/huge.pdf",
                    max_size_bytes=50 * 1024 * 1024,
                    timeout=10,
                )

    @pytest.mark.asyncio
    async def test_oversized_body_without_content_length_raises_too_large(self) -> None:
        big_content = b"%PDF" + b"\x00" * (51 * 1024 * 1024)
        mock_resp = _make_mock_response(200, big_content)
        mock_client = _make_mock_client(mock_resp)
        with patch("pdf2md.downloader.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(PDFTooLargeError):
                await download_pdf(
                    "https://example.com/sneaky-big.pdf",
                    max_size_bytes=50 * 1024 * 1024,
                    timeout=10,
                )


class TestDownloadPdfSuccess:
    """Test successful PDF downloads."""

    @pytest.mark.asyncio
    async def test_valid_pdf_returns_content(self) -> None:
        pdf_content = b"%PDF-1.4 fake pdf content"
        mock_resp = _make_mock_response(200, pdf_content, {"content-type": "application/pdf"})
        mock_client = _make_mock_client(mock_resp)
        with patch("pdf2md.downloader.httpx.AsyncClient", return_value=mock_client):
            result = await download_pdf(
                "https://example.com/doc.pdf",
                max_size_bytes=50 * 1024 * 1024,
                timeout=10,
            )
            assert result.content == pdf_content

    @pytest.mark.asyncio
    async def test_valid_pdf_returns_source_url(self) -> None:
        mock_resp = _make_mock_response(200, b"%PDF-1.4 fake", {"content-type": "application/pdf"})
        mock_client = _make_mock_client(mock_resp)
        with patch("pdf2md.downloader.httpx.AsyncClient", return_value=mock_client):
            result = await download_pdf(
                "https://example.com/doc.pdf",
                max_size_bytes=50 * 1024 * 1024,
                timeout=10,
            )
            assert result.source_url == "https://example.com/doc.pdf"
