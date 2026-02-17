"""Tests for pdf2md.converter — Marker wrapper and conversion logic."""

import asyncio
from unittest.mock import patch, MagicMock

import pytest

from pdf2md.converter import (
    ConversionError,
    ConversionResult,
    ConversionTimeoutError,
    convert_pdf,
    _run_marker,
)


class TestConvertPdfWithMockedMarker:
    """Test the async conversion wrapper with Marker mocked out."""

    @pytest.mark.asyncio
    async def test_successful_conversion_returns_markdown(self) -> None:
        mock_result = ConversionResult(
            markdown="# Test Document\n\nHello world.",
            images={},
            page_count=1,
        )
        with patch("pdf2md.converter._run_marker", return_value=mock_result):
            result = await convert_pdf(b"%PDF-fake", timeout=10)
            assert result.markdown == "# Test Document\n\nHello world."

    @pytest.mark.asyncio
    async def test_successful_conversion_returns_page_count(self) -> None:
        mock_result = ConversionResult(markdown="content", images={}, page_count=5)
        with patch("pdf2md.converter._run_marker", return_value=mock_result):
            result = await convert_pdf(b"%PDF-fake", timeout=10)
            assert result.page_count == 5

    @pytest.mark.asyncio
    async def test_successful_conversion_returns_images(self) -> None:
        images = {"fig1.png": b"\x89PNG_DATA"}
        mock_result = ConversionResult(markdown="content", images=images, page_count=1)
        with patch("pdf2md.converter._run_marker", return_value=mock_result):
            result = await convert_pdf(b"%PDF-fake", timeout=10)
            assert "fig1.png" in result.images

    @pytest.mark.asyncio
    async def test_timeout_raises_conversion_timeout_error(self) -> None:
        async def slow_marker(*args, **kwargs):
            await asyncio.sleep(100)
            return ConversionResult(markdown="", images={}, page_count=0)

        with patch("pdf2md.converter.asyncio.to_thread", side_effect=slow_marker):
            with pytest.raises(ConversionTimeoutError):
                await convert_pdf(b"%PDF-fake", timeout=0.01)

    @pytest.mark.asyncio
    async def test_marker_failure_raises_conversion_error(self) -> None:
        with patch("pdf2md.converter._run_marker", side_effect=ConversionError("Could not parse PDF.")):
            with pytest.raises(ConversionError, match="Could not parse PDF"):
                await convert_pdf(b"%PDF-fake", timeout=10)


class TestRunMarkerWithoutDependency:
    """Test _run_marker when marker-pdf is not installed."""

    def test_import_error_raises_conversion_error(self) -> None:
        with patch.dict("sys.modules", {"marker.converters.pdf": None, "marker.config.parser": None}):
            # Force the import inside _run_marker to fail
            with patch("builtins.__import__", side_effect=ImportError("No module")):
                with pytest.raises(ConversionError, match="Marker is not installed"):
                    _run_marker("/tmp/fake.pdf")
