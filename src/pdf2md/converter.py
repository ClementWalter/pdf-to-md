"""PDF-to-Markdown conversion using pymupdf4llm with optional formula OCR.

Uses PyMuPDF's rule-based extraction (no ML models, no GPU needed) which runs
in seconds with minimal memory — suitable for serverless containers.  When an
OpenRouter API key is provided, a hybrid pipeline detects math formulas via font
analysis, OCRs them with a vision model, and patches LaTeX back into the output.
"""

import asyncio
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


def _run_pymupdf(pdf_path: str, *, page_chunks: bool = False) -> ConversionResult:
    """Synchronous pymupdf4llm invocation — runs in a thread via asyncio.

    When *page_chunks* is True, returns per-page markdown joined by newline
    (and stores the individual page list in ``_page_markdowns`` for the formula
    OCR pipeline).  Separated so it can be easily mocked in tests.
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

        if page_chunks:
            # Per-page chunks for easier formula-region matching
            chunks = pymupdf4llm.to_markdown(
                pdf_path,
                write_images=True,
                image_path="/tmp/pymupdf_images",
                page_chunks=True,
            )
            page_markdowns = [chunk["text"] for chunk in chunks]
            markdown = "\n".join(page_markdowns)
        else:
            markdown = pymupdf4llm.to_markdown(
                pdf_path,
                write_images=True,
                image_path="/tmp/pymupdf_images",
            )
            page_markdowns = []
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

    result = ConversionResult(
        markdown=markdown,
        images=images,
        page_count=page_count,
    )
    # Attach per-page markdowns for the formula OCR pipeline (not part of
    # the public dataclass contract, but needed internally)
    result._page_markdowns = page_markdowns  # type: ignore[attr-defined]
    return result


def _run_formula_ocr(
    pdf_path: str,
    page_markdowns: list[str],
    *,
    openrouter_api_key: str,
    ocr_model: str,
) -> str:
    """Detect formula regions, OCR them, and patch LaTeX into the markdown.

    Runs synchronously — called from a thread pool alongside _run_pymupdf.
    """
    import pymupdf

    from pdf2md.formula_ocr import (
        detect_formula_regions,
        ocr_formulas,
        patch_markdown,
        RENDER_DPI,
    )

    doc = pymupdf.open(pdf_path)
    all_regions = []

    # Step 1: Detect formula regions via font analysis
    for page_num in range(len(doc)):
        page = doc[page_num]
        regions = detect_formula_regions(page)
        all_regions.extend(regions)

    if not all_regions:
        logger.info("No formula regions detected — skipping OCR")
        doc.close()
        return "\n".join(page_markdowns)

    logger.info(
        "Detected %d formula regions across %d pages",
        len(all_regions),
        len({r.page_num for r in all_regions}),
    )

    # Step 2: Render pages with formulas at high DPI for cropping
    pages_with_formulas = {r.page_num for r in all_regions}
    zoom = RENDER_DPI / 72.0
    matrix = pymupdf.Matrix(zoom, zoom)
    page_images: dict[int, bytes] = {}

    for page_num in pages_with_formulas:
        page = doc[page_num]
        pix = page.get_pixmap(matrix=matrix)
        page_images[page_num] = pix.tobytes("png")

    doc.close()

    # Step 3: OCR formulas via OpenRouter
    all_regions = ocr_formulas(
        all_regions,
        page_images,
        model=ocr_model,
        api_key=openrouter_api_key,
    )

    # Step 4: Patch markdown with LaTeX
    return patch_markdown(page_markdowns, all_regions)


def _run_hybrid(
    pdf_path: str,
    *,
    openrouter_api_key: str,
    ocr_model: str,
) -> ConversionResult:
    """Full hybrid pipeline: pymupdf4llm text + OpenRouter formula OCR.

    Runs synchronously in a thread pool via asyncio.to_thread().
    """
    # First get per-page markdown from pymupdf4llm
    result = _run_pymupdf(pdf_path, page_chunks=True)
    page_markdowns = result._page_markdowns  # type: ignore[attr-defined]

    if not page_markdowns:
        # Fallback: no page chunks available, return as-is
        return result

    # Run formula OCR + patching; fall back to plain pymupdf4llm on any error
    # so a formula-OCR failure never takes down the whole conversion
    try:
        patched_markdown = _run_formula_ocr(
            pdf_path,
            page_markdowns,
            openrouter_api_key=openrouter_api_key,
            ocr_model=ocr_model,
        )
    except Exception:
        logger.exception("Formula OCR failed — falling back to plain pymupdf4llm")
        return result

    # Re-apply image path normalization on the patched markdown
    image_dir = Path("/tmp/pymupdf_images")
    for image_name in result.images:
        patched_markdown = patched_markdown.replace(
            str(image_dir / image_name), image_name
        )
        patched_markdown = patched_markdown.replace(
            f"/tmp/pymupdf_images/{image_name}", image_name
        )

    return ConversionResult(
        markdown=patched_markdown,
        images=result.images,
        page_count=result.page_count,
    )


async def convert_pdf(
    pdf_content: bytes,
    *,
    timeout: int = 300,
    cache_key: str = "",
    openrouter_api_key: str = "",
    ocr_model: str = "google/gemini-2.5-flash",
) -> ConversionResult:
    """Convert raw PDF bytes to markdown using pymupdf4llm.

    When *openrouter_api_key* is set, runs the hybrid pipeline that detects
    math formulas via font analysis and OCRs them with a vision model.
    Falls back to plain pymupdf4llm when no API key is provided.

    Runs the conversion in a thread pool to avoid blocking the async event loop.
    Enforces a timeout to prevent runaway conversions.
    """
    # Write PDF to a temp file because pymupdf expects a filesystem path
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_content)
        tmp_path = tmp.name

    try:
        if openrouter_api_key:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    _run_hybrid,
                    tmp_path,
                    openrouter_api_key=openrouter_api_key,
                    ocr_model=ocr_model,
                ),
                timeout=timeout,
            )
        else:
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
