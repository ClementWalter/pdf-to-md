"""PDF-to-Markdown conversion using pymupdf4llm.

Uses PyMuPDF's rule-based extraction (no ML models, no GPU needed) which runs
in seconds with minimal memory — suitable for serverless containers.
"""

import asyncio
import io
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


class ConversionError(Exception):
    """Raised when PDF conversion fails."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class ConversionTimeoutError(ConversionError):
    """Conversion exceeded the configured timeout."""

    def __init__(self, message: str = "Conversion timed out.") -> None:
        super().__init__(message, status_code=504)


@dataclass
class ConversionResult:
    """Output of a successful PDF to Markdown conversion."""

    markdown: str
    images: dict[str, bytes] = field(default_factory=dict)
    page_count: int = 0


def _run_pymupdf(pdf_path: str) -> ConversionResult:
    """Synchronous pymupdf4llm invocation — runs in a thread via asyncio.

    Separated so it can be easily mocked in tests.
    """
    try:
        import pymupdf4llm
        import pymupdf
    except ImportError as exc:
        raise ConversionError(
            "pymupdf4llm is not installed. Install with: pip install pymupdf4llm"
        ) from exc

    try:
        doc = pymupdf.open(pdf_path)
        page_count = len(doc)
        doc.close()

        # write_images=True extracts images and references them in markdown
        markdown = pymupdf4llm.to_markdown(
            pdf_path,
            write_images=True,
            image_path="/tmp/pymupdf_images",
        )
    except Exception as exc:
        logger.exception("pymupdf4llm failed to convert %s", pdf_path)
        raise ConversionError("Could not parse PDF.") from exc

    # Collect extracted images from the temp directory
    images: dict[str, bytes] = {}
    image_dir = Path("/tmp/pymupdf_images")
    if image_dir.exists():
        for img_file in image_dir.iterdir():
            if img_file.is_file():
                images[img_file.name] = img_file.read_bytes()
                # Replace absolute path references with just the filename
                # (main.py will rewrite these to /images/<cache_key>/<filename>)
                markdown = markdown.replace(str(img_file), img_file.name)
                # Also handle the relative path form
                markdown = markdown.replace(
                    f"/tmp/pymupdf_images/{img_file.name}", img_file.name
                )
        # Clean up extracted images
        for img_file in image_dir.iterdir():
            img_file.unlink(missing_ok=True)

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
    """Convert raw PDF bytes to markdown using pymupdf4llm.

    Runs the conversion in a thread pool to avoid blocking the async event loop.
    Enforces a timeout to prevent runaway conversions.
    """
    # Write PDF to a temp file because pymupdf expects a filesystem path
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_content)
        tmp_path = tmp.name

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_run_pymupdf, tmp_path),
            timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        raise ConversionTimeoutError() from exc
    finally:
        # Clean up the temp file
        Path(tmp_path).unlink(missing_ok=True)

    return result
