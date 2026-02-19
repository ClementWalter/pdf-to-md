"""Tests for pdf2md.formula_ocr — formula detection, OCR helpers, and patching."""

import re
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from PIL import Image

from pdf2md.formula_ocr import (
    FormulaRegion,
    _extract_raw_chars,
    _merge_nearby_regions,
    build_search_pattern,
    crop_formula_image,
    is_math_font,
    patch_markdown,
)


# ---------------------------------------------------------------------------
# is_math_font
# ---------------------------------------------------------------------------


class TestIsMathFont:
    """Font names containing Computer Modern / AMS prefixes are math fonts."""

    @pytest.mark.parametrize(
        "font_name",
        [
            "CMMI10",
            "CMSY8",
            "CMEX10",
            "CMR12",
            "CMSS10",
            "MSBM10",
            "EUFM10",
            "MSAM10",
            # Case-insensitive match
            "cmmi7",
            "CmSy5",
        ],
    )
    def test_math_fonts_are_detected(self, font_name: str) -> None:
        assert is_math_font(font_name) is True

    @pytest.mark.parametrize(
        "font_name",
        [
            "SFRM1000",
            "SFTI1000",
            "SFBX1200",
            "Arial",
            "TimesNewRoman",
            "Helvetica",
            "",
        ],
    )
    def test_non_math_fonts_are_rejected(self, font_name: str) -> None:
        assert is_math_font(font_name) is False


# ---------------------------------------------------------------------------
# _extract_raw_chars
# ---------------------------------------------------------------------------


class TestExtractRawChars:
    """Extract non-whitespace characters from span dicts."""

    def test_extracts_chars_from_single_span(self) -> None:
        spans = [{"text": "x + y"}]
        assert _extract_raw_chars(spans) == "x+y"

    def test_extracts_chars_from_multiple_spans(self) -> None:
        spans = [{"text": "x "}, {"text": "+ y"}]
        assert _extract_raw_chars(spans) == "x+y"

    def test_returns_empty_for_whitespace_only(self) -> None:
        spans = [{"text": "   "}]
        assert _extract_raw_chars(spans) == ""

    def test_handles_empty_spans(self) -> None:
        assert _extract_raw_chars([]) == ""

    def test_handles_missing_text_key(self) -> None:
        spans = [{"font": "CMMI10"}]
        assert _extract_raw_chars(spans) == ""


# ---------------------------------------------------------------------------
# build_search_pattern
# ---------------------------------------------------------------------------


class TestBuildSearchPattern:
    """Build regex that matches raw chars with interleaved markdown formatting."""

    def test_returns_none_for_single_char(self) -> None:
        assert build_search_pattern("x") is None

    def test_matches_plain_text(self) -> None:
        pattern = build_search_pattern("x+y")
        assert pattern is not None
        assert pattern.search("x+y") is not None

    def test_matches_with_markdown_formatting(self) -> None:
        pattern = build_search_pattern("x2+y2")
        assert pattern is not None
        # pymupdf4llm might render as _x_ [2] + _y_ [2]
        assert pattern.search("_x_ [2] + _y_ [2]") is not None

    def test_no_match_on_different_text(self) -> None:
        pattern = build_search_pattern("abc")
        assert pattern is not None
        assert pattern.search("xyz") is None


# ---------------------------------------------------------------------------
# _merge_nearby_regions
# ---------------------------------------------------------------------------


class TestMergeNearbyRegions:
    """Merge horizontally adjacent regions on the same page/line."""

    def test_empty_list_returns_empty(self) -> None:
        assert _merge_nearby_regions([]) == []

    def test_single_region_unchanged(self) -> None:
        region = FormulaRegion(page_num=0, bbox=(10, 10, 50, 20), is_display=False)
        result = _merge_nearby_regions([region])
        assert len(result) == 1

    def test_adjacent_regions_are_merged(self) -> None:
        # Two regions close together on the same line
        r1 = FormulaRegion(page_num=0, bbox=(10, 10, 50, 20), is_display=False, raw_chars="ab")
        r2 = FormulaRegion(page_num=0, bbox=(52, 10, 90, 20), is_display=False, raw_chars="cd")
        result = _merge_nearby_regions([r1, r2])
        assert len(result) == 1

    def test_merged_bbox_is_union(self) -> None:
        r1 = FormulaRegion(page_num=0, bbox=(10, 10, 50, 20), is_display=False, raw_chars="ab")
        r2 = FormulaRegion(page_num=0, bbox=(52, 10, 90, 20), is_display=False, raw_chars="cd")
        result = _merge_nearby_regions([r1, r2])
        assert result[0].bbox == (10, 10, 90, 20)

    def test_merged_raw_chars_concatenated(self) -> None:
        r1 = FormulaRegion(page_num=0, bbox=(10, 10, 50, 20), is_display=False, raw_chars="ab")
        r2 = FormulaRegion(page_num=0, bbox=(52, 10, 90, 20), is_display=False, raw_chars="cd")
        result = _merge_nearby_regions([r1, r2])
        assert result[0].raw_chars == "abcd"

    def test_distant_regions_not_merged(self) -> None:
        # Two regions far apart horizontally
        r1 = FormulaRegion(page_num=0, bbox=(10, 10, 50, 20), is_display=False, raw_chars="ab")
        r2 = FormulaRegion(page_num=0, bbox=(100, 10, 150, 20), is_display=False, raw_chars="cd")
        result = _merge_nearby_regions([r1, r2])
        assert len(result) == 2

    def test_different_pages_not_merged(self) -> None:
        r1 = FormulaRegion(page_num=0, bbox=(10, 10, 50, 20), is_display=False, raw_chars="ab")
        r2 = FormulaRegion(page_num=1, bbox=(52, 10, 90, 20), is_display=False, raw_chars="cd")
        result = _merge_nearby_regions([r1, r2])
        assert len(result) == 2


# ---------------------------------------------------------------------------
# crop_formula_image
# ---------------------------------------------------------------------------


class TestCropFormulaImage:
    """Crop formula from a page image and add padding."""

    @pytest.fixture()
    def page_image_bytes(self) -> bytes:
        """Create a 200x100 white test image as PNG bytes."""
        img = Image.new("RGB", (200, 100), (255, 255, 255))
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def test_output_includes_padding(self, page_image_bytes: bytes) -> None:
        # bbox in PDF coordinates (points), at 72 DPI the image is 200x100 pixels
        # so bbox (10,10,50,30) at 72 DPI = (10,10,50,30) pixels
        result = crop_formula_image(page_image_bytes, (10, 10, 50, 30), dpi=72)
        # Expected: (50-10) + 2*5 = 50 wide, (30-10) + 2*5 = 30 tall
        assert result.width == 50
        assert result.height == 30

    def test_output_is_rgb_image(self, page_image_bytes: bytes) -> None:
        result = crop_formula_image(page_image_bytes, (10, 10, 50, 30), dpi=72)
        assert result.mode == "RGB"


# ---------------------------------------------------------------------------
# patch_markdown
# ---------------------------------------------------------------------------


class TestPatchMarkdown:
    """Patch LaTeX into markdown using formula regions with pre-set latex."""

    def test_inline_formula_patched(self) -> None:
        page_md = "The equation _x_ [2] + _y_ [2] = 1 is a circle."
        region = FormulaRegion(
            page_num=0,
            bbox=(0, 0, 100, 10),
            is_display=False,
            raw_chars="x2+y2=1",
            latex="x^2 + y^2 = 1",
        )
        result = patch_markdown([page_md], [region])
        assert "$x^2 + y^2 = 1$" in result

    def test_display_formula_patched(self) -> None:
        page_md = "Below:\n_x_ [2] + _y_ [2] = 1\nAbove."
        region = FormulaRegion(
            page_num=0,
            bbox=(0, 0, 100, 10),
            is_display=True,
            raw_chars="x2+y2=1",
            latex="x^2 + y^2 = 1",
        )
        result = patch_markdown([page_md], [region])
        assert "$$x^2 + y^2 = 1$$" in result

    def test_region_without_latex_is_skipped(self) -> None:
        page_md = "The equation _x_ [2] + _y_ [2] = 1 is a circle."
        region = FormulaRegion(
            page_num=0,
            bbox=(0, 0, 100, 10),
            is_display=False,
            raw_chars="x2+y2=1",
            latex="",  # No OCR result
        )
        result = patch_markdown([page_md], [region])
        # Original text unchanged
        assert result == page_md

    def test_multiple_pages_joined(self) -> None:
        pages = ["Page 1 content", "Page 2 content"]
        result = patch_markdown(pages, [])
        assert "Page 1 content\nPage 2 content" == result

    def test_unmatched_region_leaves_text_unchanged(self) -> None:
        page_md = "Some text without formulas."
        region = FormulaRegion(
            page_num=0,
            bbox=(0, 0, 100, 10),
            is_display=False,
            raw_chars="xyz123",
            latex="x + y + z",
        )
        result = patch_markdown([page_md], [region])
        assert result == page_md
