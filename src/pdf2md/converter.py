"""Wrapper around Marker for PDF-to-Markdown conversion.

Marker is imported lazily because it pulls in torch (~2 GB). This lets the
rest of the application (config, cache, downloader, routes) load without
requiring the ML stack — useful for testing and lightweight operations.
"""

import asyncio
import logging
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


class ConversionError(Exception):
    """Raised when Marker fails to convert a PDF."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class ConversionTimeoutError(ConversionError):
    """Conversion exceeded the configured timeout."""

    def __init__(self, message: str = "Conversion timed out.") -> None:
        super().__init__(message, status_code=504)


@dataclass
class ConversionResult:
    """Output of a successful PDF→Markdown conversion."""

    markdown: str
    images: dict[str, bytes] = field(default_factory=dict)
    page_count: int = 0


def _run_marker(pdf_path: str) -> ConversionResult:
    """Synchronous Marker invocation — runs in a thread via asyncio.

    Separated so it can be easily mocked in tests.
    """
    try:
        from marker.converters.pdf import PdfConverter
        from marker.config.parser import ConfigParser
    except ImportError as exc:
        raise ConversionError(
            "Marker is not installed. Install with: pip install marker-pdf"
        ) from exc

    try:
        config_parser = ConfigParser({"output_format": "markdown"})
        converter = PdfConverter(config=config_parser.generate_config_dict())
        rendered = converter(pdf_path)
    except Exception as exc:
        logger.exception("Marker failed to convert %s", pdf_path)
        raise ConversionError("Could not parse PDF.") from exc

    markdown = rendered.markdown

    # Extract images from Marker's output
    images: dict[str, bytes] = {}
    for name, image in rendered.images.items():
        images[name] = image

    # Count pages (Marker exposes this on the document metadata)
    page_count = 0
    try:
        page_count = rendered.metadata.get("page_count", 0)
    except (AttributeError, TypeError):
        # Fallback: estimate from page break markers
        page_count = len(re.findall(r"\n---\n", markdown)) + 1

    return ConversionResult(
        markdown=markdown,
        images=images,
        page_count=page_count,
    )


async def convert_pdf(
    pdf_content: bytes,
    *,
    timeout: int = 120,
    cache_key: str = "",
) -> ConversionResult:
    """Convert raw PDF bytes to markdown using Marker.

    Runs the CPU/GPU-bound conversion in a thread pool to avoid blocking
    the async event loop.  Enforces a timeout to prevent runaway conversions.
    """
    # Write PDF to a temp file because Marker expects a filesystem path
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_content)
        tmp_path = tmp.name

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_run_marker, tmp_path),
            timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        raise ConversionTimeoutError() from exc
    finally:
        # Clean up the temp file
        Path(tmp_path).unlink(missing_ok=True)

    return result
