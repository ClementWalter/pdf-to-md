"""Formula detection, OCR, and markdown patching for math-heavy PDFs.

Uses PyMuPDF font analysis to detect formula regions (Computer Modern / AMS math
fonts), crops formula images at high DPI, OCRs them in batches via OpenRouter
vision API, and patches the resulting LaTeX back into pymupdf4llm markdown output.
"""

import base64
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from io import BytesIO

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

# Computer Modern and AMS math fonts used in LaTeX-typeset PDFs.
# Body text uses SF* fonts (SFRM, SFTI, SFBX) which we exclude.
MATH_FONT_RE = re.compile(
    r"^(CMMI|CMSY|CMEX|CMR|CMSS|MSBM|EUFM|MSAM)", re.IGNORECASE
)

# Minimum non-whitespace characters for a formula to be worth OCR-ing.
# Single variables (x, p) are not worth the OCR cost.
MIN_FORMULA_CHARS = 3

# DPI for formula image cropping — high enough for OCR accuracy
RENDER_DPI = 300
# Padding around formula bounding boxes in pixels (at render DPI)
CROP_PADDING = 5

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Markdown formatting chars that pymupdf4llm inserts around text.
# Used in regex patterns to flexibly match formatted output.
_MD_FILLER = r"[\s_*\[\]]{0,6}"


@dataclass
class FormulaRegion:
    """A detected formula region on a page."""

    page_num: int
    # Bounding box in PDF coordinates (points)
    bbox: tuple[float, float, float, float]
    # Whether this is a display formula (vs inline)
    is_display: bool
    # Spans that make up this formula (both math and glue)
    spans: list[dict] = field(default_factory=list)
    # Non-whitespace characters extracted from spans (for matching)
    raw_chars: str = ""
    # OCR result
    latex: str = ""


def is_math_font(font_name: str) -> bool:
    """Check if a font name matches known math font patterns."""
    return bool(MATH_FONT_RE.search(font_name))


def _extract_raw_chars(spans: list[dict]) -> str:
    """Extract non-whitespace characters from spans in order.

    Used to build flexible search patterns that match regardless of
    how pymupdf4llm renders whitespace and formatting markers.
    """
    chars: list[str] = []
    for span in spans:
        for ch in span.get("text", ""):
            if not ch.isspace():
                chars.append(ch)
    return "".join(chars)


def _has_math_structure(spans: list[dict]) -> bool:
    """Check if spans contain mathematical structure beyond plain text.

    Returns True if there are superscripts, subscripts, special operators,
    or multiple font changes — indicators of actual formulas vs. plain
    variable names.
    """
    has_super = any(s.get("flags", 0) & 1 for s in spans)
    # Multiple distinct fonts suggests structure (e.g. italic var + roman operator)
    fonts = {s.get("font", "") for s in spans}
    has_mixed_fonts = len(fonts) > 1
    return has_super or has_mixed_fonts


def detect_formula_regions(page) -> list[FormulaRegion]:
    """Detect formula regions on a page using font-based analysis.

    Walks spans in reading order, grouping consecutive math-font spans
    into formula regions. Classifies each as display or inline.
    """
    import pymupdf

    text_dict = page.get_text("dict")
    page_width = page.rect.width
    regions: list[FormulaRegion] = []

    for block in text_dict.get("blocks", []):
        # Skip image blocks
        if block.get("type") != 0:
            continue

        for line in block.get("lines", []):
            # Group consecutive math-font spans within each line
            current_math_spans: list[dict] = []

            for span in line.get("spans", []):
                if is_math_font(span.get("font", "")):
                    current_math_spans.append(span)
                else:
                    # Non-math span breaks the current group
                    if current_math_spans:
                        region = _build_region(
                            page.number, current_math_spans, page_width, line
                        )
                        if region:
                            regions.append(region)
                        current_math_spans = []

            # Flush remaining math spans at end of line
            if current_math_spans:
                region = _build_region(
                    page.number, current_math_spans, page_width, line
                )
                if region:
                    regions.append(region)

    # Merge adjacent regions on the same line that are close together
    return _merge_nearby_regions(regions)


def _build_region(
    page_num: int,
    math_spans: list[dict],
    page_width: float,
    line: dict,
) -> FormulaRegion | None:
    """Build a FormulaRegion from a group of consecutive math-font spans.

    Filters out trivially small regions and regions without mathematical
    structure (e.g. a lone variable letter).
    """
    import pymupdf

    raw_chars = _extract_raw_chars(math_spans)
    # Skip regions with too few meaningful characters
    if len(raw_chars) < MIN_FORMULA_CHARS:
        # Allow smaller formulas if they have structure (e.g. x^2)
        if len(raw_chars) < 2 or not _has_math_structure(math_spans):
            return None

    # Strip leading/trailing whitespace-only spans before computing bbox.
    # These padding spans extend into adjacent body text, causing the OCR
    # to capture surrounding words in the cropped formula image.
    content_spans = math_spans
    while content_spans and not content_spans[0].get("text", "").strip():
        content_spans = content_spans[1:]
    while content_spans and not content_spans[-1].get("text", "").strip():
        content_spans = content_spans[:-1]
    # Fall back to all spans if stripping removed everything
    bbox_spans = content_spans if content_spans else math_spans

    # Compute union bounding box of content spans only
    rects = [pymupdf.Rect(s["bbox"]) for s in bbox_spans]
    union_rect = rects[0]
    for r in rects[1:]:
        union_rect |= r

    # Classify: display if formula dominates the line with no body text
    line_spans = line.get("spans", [])
    non_math_text = "".join(
        s.get("text", "").strip()
        for s in line_spans
        if not is_math_font(s.get("font", ""))
    )
    formula_width_ratio = union_rect.width / page_width if page_width > 0 else 0
    is_display = formula_width_ratio > 0.3 and len(non_math_text) < 5

    return FormulaRegion(
        page_num=page_num,
        bbox=(union_rect.x0, union_rect.y0, union_rect.x1, union_rect.y1),
        is_display=is_display,
        spans=[dict(s) for s in math_spans],
        raw_chars=raw_chars,
    )


def _merge_nearby_regions(
    regions: list[FormulaRegion], x_threshold: float = 3.0
) -> list[FormulaRegion]:
    """Merge formula regions on the same page that are horizontally adjacent.

    Regions must substantially overlap vertically (>50% of shorter height)
    and be close horizontally to qualify as parts of the same formula.
    """
    if not regions:
        return regions

    merged: list[FormulaRegion] = []
    current = regions[0]

    for next_region in regions[1:]:
        same_page = current.page_num == next_region.page_num
        # Require substantial vertical overlap (>50% of shorter region height)
        # to ensure regions are on the same visual line
        overlap_top = max(current.bbox[1], next_region.bbox[1])
        overlap_bot = min(current.bbox[3], next_region.bbox[3])
        overlap_height = max(0, overlap_bot - overlap_top)
        cur_height = current.bbox[3] - current.bbox[1]
        nxt_height = next_region.bbox[3] - next_region.bbox[1]
        min_height = min(cur_height, nxt_height)
        y_overlap = min_height > 0 and (overlap_height / min_height) > 0.5
        x_gap = next_region.bbox[0] - current.bbox[2]

        if same_page and y_overlap and x_gap < x_threshold:
            current = FormulaRegion(
                page_num=current.page_num,
                bbox=(
                    min(current.bbox[0], next_region.bbox[0]),
                    min(current.bbox[1], next_region.bbox[1]),
                    max(current.bbox[2], next_region.bbox[2]),
                    max(current.bbox[3], next_region.bbox[3]),
                ),
                is_display=current.is_display or next_region.is_display,
                spans=current.spans + next_region.spans,
                raw_chars=current.raw_chars + next_region.raw_chars,
            )
        else:
            merged.append(current)
            current = next_region

    merged.append(current)
    return merged


def build_search_pattern(raw_chars: str) -> re.Pattern | None:
    """Build a flexible regex to find a formula's text in pymupdf4llm markdown.

    Creates a pattern where each non-whitespace character from the formula
    is an anchor, with optional markdown formatting chars (_, *, [, ], space)
    allowed between them. This handles pymupdf4llm's variable rendering of
    italic markers, superscript brackets, and whitespace.
    """
    if len(raw_chars) < 2:
        return None

    # Build pattern: each char separated by optional formatting/whitespace
    parts = [_MD_FILLER]
    for ch in raw_chars:
        parts.append(re.escape(ch))
        parts.append(_MD_FILLER)

    pattern_str = "".join(parts)
    try:
        return re.compile(pattern_str)
    except re.error:
        logger.debug("Failed to compile pattern for: %r", raw_chars)
        return None


def crop_formula_image(
    page_pixmap_bytes: bytes,
    formula_bbox: tuple[float, float, float, float],
    dpi: int = RENDER_DPI,
) -> Image.Image:
    """Crop a formula region from a pre-rendered page image.

    Converts PDF coordinates to pixel coordinates at the given DPI.
    Crops tightly to the formula, then adds white padding around it
    to prevent the OCR model from reading adjacent body text.
    """
    scale = dpi / 72.0

    # Crop tightly to the formula bbox (no padding into page content)
    x0 = int(formula_bbox[0] * scale)
    y0 = int(formula_bbox[1] * scale)
    x1 = int(formula_bbox[2] * scale)
    y1 = int(formula_bbox[3] * scale)

    page_img = Image.open(BytesIO(page_pixmap_bytes))
    x0 = max(0, x0)
    y0 = max(0, y0)
    x1 = min(page_img.width, x1)
    y1 = min(page_img.height, y1)

    cropped = page_img.crop((x0, y0, x1, y1))

    # Add white padding around the cropped formula so the OCR model
    # has clean borders and doesn't confuse adjacent text as formula content
    padded = Image.new(
        "RGB",
        (cropped.width + 2 * CROP_PADDING, cropped.height + 2 * CROP_PADDING),
        (255, 255, 255),
    )
    padded.paste(cropped, (CROP_PADDING, CROP_PADDING))
    return padded


def _image_to_base64(img: Image.Image) -> str:
    """Encode a PIL image as a base64 PNG data URL for the OpenRouter API."""
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _ocr_batch_openrouter(
    batch: list[tuple[int, Image.Image]],
    model: str,
    api_key: str,
) -> dict[int, str]:
    """Send a batch of formula images to OpenRouter for LaTeX OCR.

    Each image is numbered; the model returns one LaTeX string per line.
    Returns a mapping of region index → LaTeX string.
    """
    # Build multi-image message with numbered labels
    content: list[dict] = [
        {
            "type": "text",
            "text": (
                f"You are a LaTeX OCR engine. Below are {len(batch)} numbered "
                "images of mathematical formulas cropped from a PDF.\n\n"
                "For EACH image, output ONLY the raw LaTeX (no $$ delimiters, "
                "no commentary) on a single line, prefixed by its number.\n\n"
                "Format:\n"
                "1: x^2 + y^2 = 1\n"
                "2: \\sum_{i=1}^{n} a_i\n"
                "...\n\n"
                "Rules:\n"
                "- Output raw LaTeX only, no markdown code fences\n"
                "- One formula per line, numbered in order\n"
                "- If an image is unreadable, output the number followed by: ???"
            ),
        }
    ]

    for seq, (_, img) in enumerate(batch, 1):
        # Add a text label before each image for clarity
        content.append({"type": "text", "text": f"Image {seq}:"})
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{_image_to_base64(img)}"
                },
            }
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://unpdf.it",
        "X-Title": "pdf2md-formula-ocr",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 4096,
        "temperature": 0.0,
    }

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(OPENROUTER_API_URL, headers=headers, json=payload)
        resp.raise_for_status()
        result = resp.json()

    # Parse numbered lines from response
    response_text = result["choices"][0]["message"]["content"]
    results: dict[int, str] = {}

    for line in response_text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Match "1: latex" or "1. latex" patterns
        m = re.match(r"^(\d+)[:.]\s*(.+)$", line)
        if m:
            seq = int(m.group(1))
            latex = m.group(2).strip()
            if latex and latex != "???":
                # Strip any accidental $$ delimiters the model may add
                latex = re.sub(r"^\$+|\$+$", "", latex).strip()
                # Map sequence number back to region index
                if 1 <= seq <= len(batch):
                    region_idx = batch[seq - 1][0]
                    results[region_idx] = latex

    return results


def ocr_formulas(
    regions: list[FormulaRegion],
    page_images: dict[int, bytes],
    *,
    model: str = "google/gemini-2.5-flash",
    api_key: str = "",
    batch_size: int = 30,
    max_workers: int = 10,
) -> list[FormulaRegion]:
    """OCR all formula regions using OpenRouter vision API.

    Crops each formula, batches them into groups, and sends them
    concurrently to a vision model for LaTeX recognition.
    """
    if not regions or not api_key:
        return regions

    # Prepare all cropped images with their region indices
    indexed_images: list[tuple[int, Image.Image]] = []
    for i, region in enumerate(regions):
        if region.page_num not in page_images:
            continue
        img = crop_formula_image(page_images[region.page_num], region.bbox)
        indexed_images.append((i, img))

    logger.info(
        "Sending %d formula images to %s in batches of %d...",
        len(indexed_images),
        model,
        batch_size,
    )

    # Split into batches
    batches: list[list[tuple[int, Image.Image]]] = []
    for start in range(0, len(indexed_images), batch_size):
        batches.append(indexed_images[start : start + batch_size])

    # Run batches concurrently via thread pool
    all_results: dict[int, str] = {}
    completed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_ocr_batch_openrouter, batch, model, api_key): batch_idx
            for batch_idx, batch in enumerate(batches)
        }

        for future in as_completed(futures):
            batch_idx = futures[future]
            try:
                batch_results = future.result()
                all_results.update(batch_results)
            except Exception:
                logger.exception("Batch %d failed", batch_idx)
            completed += 1
            if completed % 5 == 0 or completed == len(batches):
                logger.info(
                    "  OCR progress: %d / %d batches", completed, len(batches)
                )

    # Write results back to regions
    for idx, latex in all_results.items():
        regions[idx].latex = latex

    return regions


def patch_markdown(
    page_markdowns: list[str],
    regions: list[FormulaRegion],
) -> str:
    """Patch LaTeX formulas into pymupdf4llm markdown output.

    Uses flexible regex matching based on the formula's raw character
    content to find the corresponding text in the markdown, then
    replaces it with properly delimited LaTeX.
    """
    # Group regions by page, sorted by position (right-to-left, bottom-to-top)
    # to avoid offset shifts when replacing
    regions_by_page: dict[int, list[FormulaRegion]] = {}
    for region in regions:
        regions_by_page.setdefault(region.page_num, []).append(region)

    patched_pages: list[str] = []
    total_patched = 0
    total_skipped = 0

    for page_idx, page_md in enumerate(page_markdowns):
        page_regions = regions_by_page.get(page_idx, [])
        patched = page_md

        # Sort regions by raw_chars length (longest first) to replace
        # larger formulas before their sub-expressions
        page_regions.sort(key=lambda r: len(r.raw_chars), reverse=True)

        for region in page_regions:
            if not region.latex:
                total_skipped += 1
                continue

            latex = region.latex.strip()
            if not latex:
                total_skipped += 1
                continue

            # Build search pattern from raw characters
            pattern = build_search_pattern(region.raw_chars)
            if pattern is None:
                total_skipped += 1
                continue

            match = pattern.search(patched)
            if not match:
                logger.debug(
                    "No match on page %d for chars %r → %s",
                    page_idx + 1,
                    region.raw_chars,
                    latex,
                )
                total_skipped += 1
                continue

            # Wrap in appropriate delimiters
            if region.is_display:
                replacement = f"$${latex}$$"
            else:
                replacement = f"${latex}$"

            patched = patched[: match.start()] + replacement + patched[match.end() :]
            total_patched += 1

        patched_pages.append(patched)

    logger.info(
        "Patched %d / %d formula regions (%d skipped)",
        total_patched,
        len(regions),
        total_skipped,
    )
    return "\n".join(patched_pages)
