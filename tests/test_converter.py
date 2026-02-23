"""Tests for pdf2md.converter — pymupdf4llm wrapper, MarkItDown, and routing."""

import asyncio
from unittest.mock import patch, MagicMock

import pytest

from pdf2md.converter import (
    ConversionError,
    ConversionResult,
    ConversionTimeoutError,
    convert_file,
    convert_pdf,
    _get_extension_from_url,
    _run_markitdown,
    _run_pymupdf,
)


class TestConvertPdfWithMockedPymupdf:
    """Test the async conversion wrapper with pymupdf4llm mocked out."""

    @pytest.mark.asyncio
    async def test_successful_conversion_returns_markdown(self) -> None:
        mock_result = ConversionResult(
            markdown="# Test Document\n\nHello world.",
            images={},
            page_count=1,
        )
        with patch("pdf2md.converter._run_pymupdf", return_value=mock_result):
            result = await convert_pdf(b"%PDF-fake", timeout=10)
            assert result.markdown == "# Test Document\n\nHello world."

    @pytest.mark.asyncio
    async def test_successful_conversion_returns_page_count(self) -> None:
        mock_result = ConversionResult(markdown="content", images={}, page_count=5)
        with patch("pdf2md.converter._run_pymupdf", return_value=mock_result):
            result = await convert_pdf(b"%PDF-fake", timeout=10)
            assert result.page_count == 5

    @pytest.mark.asyncio
    async def test_successful_conversion_returns_images(self) -> None:
        images = {"fig1.png": b"\x89PNG_DATA"}
        mock_result = ConversionResult(markdown="content", images=images, page_count=1)
        with patch("pdf2md.converter._run_pymupdf", return_value=mock_result):
            result = await convert_pdf(b"%PDF-fake", timeout=10)
            assert "fig1.png" in result.images

    @pytest.mark.asyncio
    async def test_timeout_raises_conversion_timeout_error(self) -> None:
        async def slow_conversion(*args, **kwargs):
            await asyncio.sleep(100)
            return ConversionResult(markdown="", images={}, page_count=0)

        with patch("pdf2md.converter.asyncio.to_thread", side_effect=slow_conversion):
            with pytest.raises(ConversionTimeoutError):
                await convert_pdf(b"%PDF-fake", timeout=0.01)

    @pytest.mark.asyncio
    async def test_conversion_failure_raises_conversion_error(self) -> None:
        with patch(
            "pdf2md.converter._run_pymupdf",
            side_effect=ConversionError("Could not parse PDF."),
        ):
            with pytest.raises(ConversionError, match="Could not parse PDF"):
                await convert_pdf(b"%PDF-fake", timeout=10)


class TestRunPymupdfWithoutDependency:
    """Test _run_pymupdf when pymupdf4llm is not installed."""

    def test_import_error_raises_conversion_error(self) -> None:
        with patch("builtins.__import__", side_effect=ImportError("No module")):
            with pytest.raises(ConversionError, match="pymupdf4llm is not installed"):
                _run_pymupdf("/tmp/fake.pdf")


class TestConvertPdfFallbackWithoutApiKey:
    """Without an API key, convert_pdf uses plain pymupdf4llm (no OCR)."""

    @pytest.mark.asyncio
    async def test_no_api_key_skips_formula_ocr(self) -> None:
        mock_result = ConversionResult(markdown="plain text", images={}, page_count=1)
        with patch("pdf2md.converter._run_pymupdf", return_value=mock_result) as mock_pymupdf:
            result = await convert_pdf(b"%PDF-fake", timeout=10, openrouter_api_key="")
            # Should call _run_pymupdf directly (not _run_hybrid)
            mock_pymupdf.assert_called_once()
            assert result.markdown == "plain text"


class TestConvertPdfWithApiKey:
    """With an API key, convert_pdf runs the hybrid pipeline."""

    @pytest.mark.asyncio
    async def test_api_key_triggers_hybrid_pipeline(self) -> None:
        mock_result = ConversionResult(
            markdown="patched $$x^2$$ text", images={}, page_count=2
        )
        with patch("pdf2md.converter._run_hybrid", return_value=mock_result) as mock_hybrid:
            result = await convert_pdf(
                b"%PDF-fake",
                timeout=10,
                openrouter_api_key="sk-or-test-key",
                ocr_model="google/gemini-2.5-flash",
            )
            mock_hybrid.assert_called_once()
            assert "$$x^2$$" in result.markdown

    @pytest.mark.asyncio
    async def test_hybrid_receives_correct_model(self) -> None:
        mock_result = ConversionResult(markdown="ok", images={}, page_count=1)
        with patch("pdf2md.converter._run_hybrid", return_value=mock_result) as mock_hybrid:
            await convert_pdf(
                b"%PDF-fake",
                timeout=10,
                openrouter_api_key="sk-or-test",
                ocr_model="openai/gpt-4o-mini",
            )
            # Verify the model parameter was passed through
            call_kwargs = mock_hybrid.call_args
            assert call_kwargs.kwargs["ocr_model"] == "openai/gpt-4o-mini"


class TestGetExtensionFromUrl:
    """Test URL extension extraction logic."""

    def test_pdf_extension(self) -> None:
        assert _get_extension_from_url("https://example.com/doc.pdf") == ".pdf"

    def test_docx_extension(self) -> None:
        assert _get_extension_from_url("https://example.com/report.docx") == ".docx"

    def test_xlsx_extension(self) -> None:
        assert _get_extension_from_url("https://example.com/data.xlsx") == ".xlsx"

    def test_html_extension(self) -> None:
        assert _get_extension_from_url("https://example.com/page.html") == ".html"

    def test_csv_extension(self) -> None:
        assert _get_extension_from_url("https://example.com/data.csv") == ".csv"

    def test_uppercase_extension_normalized(self) -> None:
        assert _get_extension_from_url("https://example.com/doc.PPTX") == ".pptx"

    def test_no_extension(self) -> None:
        assert _get_extension_from_url("https://example.com/resource") == ""

    def test_extension_with_query_params(self) -> None:
        assert _get_extension_from_url("https://example.com/doc.pdf?v=1") == ".pdf"


class TestRunMarkitdown:
    """Test _run_markitdown with MarkItDown mocked."""

    def test_successful_conversion_returns_markdown(self) -> None:
        mock_md_result = MagicMock()
        mock_md_result.text_content = "# Converted DOCX\n\nHello from Word."
        mock_md_instance = MagicMock()
        mock_md_instance.convert.return_value = mock_md_result
        with patch("pdf2md.converter.MarkItDown", return_value=mock_md_instance):
            result = _run_markitdown(b"fake docx bytes", ".docx")
            assert result.markdown == "# Converted DOCX\n\nHello from Word."

    def test_returns_zero_page_count(self) -> None:
        mock_md_result = MagicMock()
        mock_md_result.text_content = "content"
        mock_md_instance = MagicMock()
        mock_md_instance.convert.return_value = mock_md_result
        with patch("pdf2md.converter.MarkItDown", return_value=mock_md_instance):
            result = _run_markitdown(b"fake", ".docx")
            assert result.page_count == 0

    def test_returns_empty_images(self) -> None:
        mock_md_result = MagicMock()
        mock_md_result.text_content = "content"
        mock_md_instance = MagicMock()
        mock_md_instance.convert.return_value = mock_md_result
        with patch("pdf2md.converter.MarkItDown", return_value=mock_md_instance):
            result = _run_markitdown(b"fake", ".xlsx")
            assert result.images == {}

    def test_conversion_failure_raises_conversion_error(self) -> None:
        mock_md_instance = MagicMock()
        mock_md_instance.convert.side_effect = RuntimeError("bad file")
        with patch("pdf2md.converter.MarkItDown", return_value=mock_md_instance):
            with pytest.raises(ConversionError, match="Could not convert .docx file"):
                _run_markitdown(b"bad data", ".docx")


class TestConvertFileRouting:
    """Test convert_file routes PDFs vs other formats correctly."""

    @pytest.mark.asyncio
    async def test_pdf_routes_to_convert_pdf(self) -> None:
        mock_result = ConversionResult(markdown="PDF content", images={}, page_count=3)
        with patch("pdf2md.converter.convert_pdf", return_value=mock_result) as mock_pdf:
            result = await convert_file(
                b"%PDF-fake",
                source_url="https://example.com/doc.pdf",
                timeout=10,
            )
            mock_pdf.assert_called_once()
            assert result.page_count == 3

    @pytest.mark.asyncio
    async def test_docx_routes_to_markitdown(self) -> None:
        mock_result = ConversionResult(markdown="DOCX content", images={}, page_count=0)
        with patch("pdf2md.converter._run_markitdown", return_value=mock_result) as mock_md:
            result = await convert_file(
                b"fake docx",
                source_url="https://example.com/report.docx",
                timeout=10,
            )
            mock_md.assert_called_once()
            assert result.markdown == "DOCX content"

    @pytest.mark.asyncio
    async def test_xlsx_routes_to_markitdown(self) -> None:
        mock_result = ConversionResult(markdown="| A | B |", images={}, page_count=0)
        with patch("pdf2md.converter._run_markitdown", return_value=mock_result) as mock_md:
            result = await convert_file(
                b"fake xlsx",
                source_url="https://example.com/data.xlsx",
                timeout=10,
            )
            mock_md.assert_called_once()
            assert result.markdown == "| A | B |"

    @pytest.mark.asyncio
    async def test_unknown_extension_routes_to_markitdown(self) -> None:
        mock_result = ConversionResult(markdown="content", images={}, page_count=0)
        with patch("pdf2md.converter._run_markitdown", return_value=mock_result) as mock_md:
            await convert_file(
                b"unknown content",
                source_url="https://example.com/file.xyz",
                timeout=10,
            )
            mock_md.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_extension_routes_to_markitdown(self) -> None:
        mock_result = ConversionResult(markdown="content", images={}, page_count=0)
        with patch("pdf2md.converter._run_markitdown", return_value=mock_result) as mock_md:
            await convert_file(
                b"mystery content",
                source_url="https://example.com/resource",
                timeout=10,
            )
            mock_md.assert_called_once()

    @pytest.mark.asyncio
    async def test_markitdown_timeout_raises_conversion_timeout(self) -> None:
        async def slow(*args, **kwargs):
            await asyncio.sleep(100)

        with patch("pdf2md.converter.asyncio.to_thread", side_effect=slow):
            with pytest.raises(ConversionTimeoutError):
                await convert_file(
                    b"fake",
                    source_url="https://example.com/doc.docx",
                    timeout=0.01,
                )
