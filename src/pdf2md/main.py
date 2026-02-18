"""FastAPI application and route definitions for pdf2md.

Routes:
    GET /                           → usage instructions (text/markdown)
    GET /images/<hash>/<filename>   → serve cached extracted image
    GET /<host>/<path>              → convert PDF and return markdown
"""

import asyncio
import logging
import mimetypes
import time
from functools import lru_cache

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse

from pdf2md.cache import DiskCache, url_to_cache_key
from pdf2md.config import Settings
from pdf2md.converter import ConversionError, ConversionTimeoutError, convert_pdf
from pdf2md.downloader import (
    DownloadError,
    download_pdf,
    normalize_url,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="pdf2md",
    description="Convert any PDF to markdown by URL rewrite",
    docs_url=None,  # No Swagger UI — this is a machine-to-machine service
    redoc_url=None,
)

# Deduplication locks: prevent redundant parallel conversions of the same URL
_conversion_locks: dict[str, asyncio.Lock] = {}


@lru_cache
def _get_settings() -> Settings:
    return Settings()


@lru_cache
def _get_cache() -> DiskCache:
    settings = _get_settings()
    return DiskCache(settings.cache_dir, ttl_days=settings.cache_ttl_days)


def _markdown_response(content: str, status_code: int = 200, headers: dict | None = None) -> Response:
    """Build a text/markdown response — all responses are markdown per PRD."""
    return Response(
        content=content,
        status_code=status_code,
        media_type="text/markdown; charset=utf-8",
        headers=headers or {},
    )


def _error_md(message: str) -> str:
    """Format an error as markdown per PRD section 6."""
    return f"# Error\n\n{message}"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> PlainTextResponse:
    """Liveness probe for container orchestrators."""
    return PlainTextResponse("ok")


@app.get("/")
async def root() -> Response:
    """Return usage instructions as text/markdown."""
    settings = _get_settings()
    body = (
        "# unpdf.it\n\n"
        "Convert any PDF to markdown by prepending this domain to the PDF URL.\n\n"
        "## Usage\n\n"
        "Given a PDF at:\n"
        "  https://arxiv.org/pdf/2301.00001v1.pdf\n\n"
        "Get its markdown at:\n"
        f"  https://{settings.domain}/arxiv.org/pdf/2301.00001v1.pdf\n\n"
        "Images are extracted and available at their referenced URLs within the markdown.\n\n"
        "## Add as an AI Agent Skill\n\n"
        "unpdf.it follows the [Agent Skills](https://agentskills.io) open standard.\n"
        "Install it so your AI coding agent automatically converts PDFs to markdown.\n\n"
        "### Claude Code\n\n"
        "```bash\n"
        "mkdir -p ~/.claude/skills/unpdf\n"
        f"curl -s https://{settings.domain}/skill > ~/.claude/skills/unpdf/SKILL.md\n"
        "```\n\n"
        "### OpenClaw\n\n"
        "```bash\n"
        "mkdir -p ~/.openclaw/skills/unpdf\n"
        f"curl -s https://{settings.domain}/skill > ~/.openclaw/skills/unpdf/SKILL.md\n"
        "```\n\n"
        "Once installed, your agent will use unpdf.it whenever it encounters a PDF URL.\n"
        f"View the skill definition at: https://{settings.domain}/skill\n"
    )
    return _markdown_response(body)


# Skill definition served as raw markdown for agent consumption
_SKILL_MD = """\
---
name: unpdf
description: >
  Convert PDF URLs to markdown using unpdf.it. Use when the user shares a PDF
  link, asks to read/summarize/analyze a PDF, or when you encounter a .pdf URL
  that needs to be read. Converts any publicly accessible PDF to clean markdown.
allowed-tools: WebFetch
user-invocable: true
argument-hint: "<pdf-url>"
---

# unpdf.it - PDF to Markdown

When you encounter a PDF URL or the user asks you to read a PDF, convert it
to markdown using unpdf.it instead of trying to download and parse it yourself.

## How it works

Strip the protocol (`https://` or `http://`) from the PDF URL and prepend
`https://unpdf.it/`:

| Original PDF URL | unpdf.it URL |
|---|---|
| `https://arxiv.org/pdf/2301.00001v1.pdf` | `https://unpdf.it/arxiv.org/pdf/2301.00001v1.pdf` |
| `https://example.com/report.pdf` | `https://unpdf.it/example.com/report.pdf` |

## Steps

1. Take the PDF URL (from the user's message, a webpage, or a reference)
2. Remove the `https://` prefix
3. Fetch `https://unpdf.it/<host>/<path>` using WebFetch
4. The response is clean markdown with headings, tables, and image references

## Example

User says: "Read https://arxiv.org/pdf/2301.00001v1.pdf"

Use WebFetch with:
- URL: `https://unpdf.it/arxiv.org/pdf/2301.00001v1.pdf`
- Prompt: "Return the full markdown content of this document"

## When to use

- User shares a `.pdf` link and asks to read, summarize, or analyze it
- You find a PDF reference while researching and need its content
- Any publicly accessible PDF URL needs to be converted to text

## Limitations

- Only works with publicly accessible URLs (not local files or authenticated PDFs)
- For local PDF files, use the built-in Read tool instead (Claude can read PDFs natively)
"""


@app.get("/skill")
async def skill() -> Response:
    """Serve the SKILL.md file for agent skill installation."""
    return _markdown_response(_SKILL_MD)


@app.get("/images/{cache_key}/{filename:path}")
async def serve_image(cache_key: str, filename: str) -> Response:
    """Serve a previously extracted image from the cache."""
    cache = _get_cache()
    image_path = cache.image_path(cache_key, filename)
    if image_path is None:
        return _markdown_response(_error_md("Image not found."), status_code=404)

    content_type, _ = mimetypes.guess_type(filename)
    content_type = content_type or "application/octet-stream"

    return Response(
        content=image_path.read_bytes(),
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=31536000"},
    )


@app.get("/{full_path:path}")
async def convert(full_path: str, request: Request) -> Response:
    """Download, convert, and return the markdown for a PDF at the given URL path."""
    settings = _get_settings()
    cache = _get_cache()

    # Parse host from the path: first segment is the host, rest is the path
    parts = full_path.split("/", 1)
    if len(parts) < 2 or not parts[0]:
        return _markdown_response(
            _error_md("URL does not point to a valid PDF."),
            status_code=400,
        )

    host = parts[0]
    path = parts[1]

    # Preserve query parameters from the original request
    query_string = str(request.query_params)
    refresh = request.query_params.get("refresh") == "true"

    # Build the source URL (always HTTPS)
    source_url = normalize_url(host, path)
    if query_string and not refresh:
        # Include query params in source URL (but strip our own ?refresh=true)
        source_url = f"{source_url}?{query_string}"
    elif query_string:
        # Remove refresh=true from query string before building source URL
        filtered = "&".join(
            p for p in query_string.split("&") if not p.startswith("refresh=")
        )
        if filtered:
            source_url = f"{source_url}?{filtered}"

    # Check cache (unless ?refresh=true)
    if not refresh:
        entry = cache.get(source_url)
        if entry is not None:
            logger.info("Cache hit for %s", source_url)
            return _markdown_response(
                entry.markdown,
                headers={
                    "X-Source-URL": source_url,
                    "X-Cached": "true",
                    "X-Conversion-Time-Ms": "0",
                    "X-Page-Count": str(entry.page_count),
                },
            )

    # Deduplication: if another request is already converting this URL, wait
    cache_key = url_to_cache_key(source_url)
    if cache_key not in _conversion_locks:
        _conversion_locks[cache_key] = asyncio.Lock()
    lock = _conversion_locks[cache_key]

    async with lock:
        # Re-check cache — another request may have just populated it
        if not refresh:
            entry = cache.get(source_url)
            if entry is not None:
                return _markdown_response(
                    entry.markdown,
                    headers={
                        "X-Source-URL": source_url,
                        "X-Cached": "true",
                        "X-Conversion-Time-Ms": "0",
                        "X-Page-Count": str(entry.page_count),
                    },
                )

        # Download
        try:
            download_result = await download_pdf(
                source_url,
                max_size_bytes=settings.max_pdf_size_bytes,
                timeout=settings.download_timeout,
            )
        except DownloadError as exc:
            return _markdown_response(
                _error_md(str(exc)),
                status_code=exc.status_code,
            )

        # Convert
        start = time.monotonic()
        try:
            conversion = await convert_pdf(
                download_result.content,
                timeout=settings.conversion_timeout,
                cache_key=cache_key,
            )
        except ConversionTimeoutError as exc:
            return _markdown_response(
                _error_md(str(exc)),
                status_code=exc.status_code,
            )
        except ConversionError as exc:
            return _markdown_response(
                _error_md(str(exc)),
                status_code=exc.status_code,
            )
        elapsed_ms = int((time.monotonic() - start) * 1000)

        # Rewrite image paths in markdown to point to our /images/ endpoint
        markdown = conversion.markdown
        for image_name in conversion.images:
            markdown = markdown.replace(
                image_name,
                f"/images/{cache_key}/{image_name}",
            )

        # Store in cache
        entry = cache.put(
            url=source_url,
            markdown=markdown,
            images=conversion.images,
            page_count=conversion.page_count,
        )

    # Clean up lock if no one else is waiting
    if not lock.locked():
        _conversion_locks.pop(cache_key, None)

    return _markdown_response(
        markdown,
        headers={
            "X-Source-URL": source_url,
            "X-Cached": "false",
            "X-Conversion-Time-Ms": str(elapsed_ms),
            "X-Page-Count": str(conversion.page_count),
        },
    )
