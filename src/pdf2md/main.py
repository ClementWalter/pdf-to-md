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
from fastapi.responses import HTMLResponse, PlainTextResponse

from pdf2md.cache import DiskCache, url_to_cache_key
from pdf2md.config import Settings
from pdf2md.converter import ConversionError, ConversionTimeoutError, convert_pdf
from pdf2md.downloader import (
    DownloadError,
    download_pdf,
    normalize_url,
)
from pdf2md.landing import render_landing

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
async def root() -> HTMLResponse:
    """Return the HTML landing page."""
    settings = _get_settings()
    return HTMLResponse(render_landing(settings.domain))


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


@app.get("/llms.txt")
async def llms_txt() -> Response:
    """Serve llms.txt — concise LLM-friendly site description per llmstxt.org."""
    settings = _get_settings()
    content = (
        "# unpdf.it\n\n"
        "> Convert any publicly accessible PDF to clean markdown via URL rewrite. "
        "No API key, no upload. Built for AI agents.\n\n"
        "## API\n\n"
        f"Prepend `https://{settings.domain}/` to any PDF URL (without its protocol):\n\n"
        f"- `https://arxiv.org/pdf/2301.00001v1.pdf` → `https://{settings.domain}/arxiv.org/pdf/2301.00001v1.pdf`\n\n"
        "The response is `text/markdown` with headers `X-Page-Count`, `X-Cached`, `X-Conversion-Time-Ms`.\n\n"
        "## Resources\n\n"
        f"- [SKILL.md](https://{settings.domain}/skill): Agent Skills standard skill definition\n"
        f"- [Full docs](https://{settings.domain}/llms-full.txt): Detailed API reference\n"
        "- [Source](https://github.com/ClementWalter/pdf-to-md): GitHub repository\n\n"
        "## Optional\n\n"
        "- Images extracted from PDFs are served at `/images/<cache_key>/<filename>`\n"
        "- Add `?refresh=true` to bypass cache\n"
        "- Max PDF size: 50 MB\n"
        "- Cache TTL: 30 days\n"
    )
    return _markdown_response(content)


@app.get("/llms-full.txt")
async def llms_full_txt() -> Response:
    """Serve llms-full.txt — detailed LLM-friendly API reference."""
    settings = _get_settings()
    content = (
        "# unpdf.it — Full Documentation\n\n"
        "> Convert any publicly accessible PDF to clean markdown via URL rewrite. "
        "No API key required. Free during beta.\n\n"
        "## How to use\n\n"
        "Take any PDF URL, strip the `https://` prefix, and prepend "
        f"`https://{settings.domain}/`.\n\n"
        "### Example\n\n"
        "```\n"
        "Input:  https://arxiv.org/pdf/2301.00001v1.pdf\n"
        f"Output: https://{settings.domain}/arxiv.org/pdf/2301.00001v1.pdf\n"
        "```\n\n"
        "### Response format\n\n"
        "- Content-Type: `text/markdown; charset=utf-8`\n"
        "- Headers:\n"
        "  - `X-Source-URL`: the original PDF URL\n"
        "  - `X-Page-Count`: number of pages in the PDF\n"
        "  - `X-Cached`: `true` if served from cache, `false` if freshly converted\n"
        "  - `X-Conversion-Time-Ms`: conversion time in milliseconds (0 if cached)\n\n"
        "### Endpoints\n\n"
        f"| Method | Path | Description |\n"
        f"|--------|------|-------------|\n"
        f"| GET | `/` | HTML landing page |\n"
        f"| GET | `/health` | Liveness probe, returns `ok` |\n"
        f"| GET | `/skill` | Agent Skills SKILL.md definition |\n"
        f"| GET | `/llms.txt` | LLM-friendly site summary |\n"
        f"| GET | `/llms-full.txt` | This file — full API reference |\n"
        f"| GET | `/images/<key>/<file>` | Serve extracted image from cache |\n"
        f"| GET | `/<host>/<path>` | Convert PDF at `https://<host>/<path>` to markdown |\n\n"
        "### Query parameters\n\n"
        "- `?refresh=true`: bypass cache and re-convert the PDF\n"
        "- All other query parameters are forwarded to the source PDF URL\n\n"
        "### Error responses\n\n"
        "Errors are returned as `text/markdown` with format:\n\n"
        "```markdown\n"
        "# Error\n\n"
        "<error message>\n"
        "```\n\n"
        "| Status | Meaning |\n"
        "|--------|---------|\n"
        "| 400 | Invalid URL or corrupt PDF |\n"
        "| 404 | PDF not found at source URL |\n"
        "| 413 | PDF exceeds 50 MB size limit |\n"
        "| 502 | Source server error |\n"
        "| 504 | Conversion timed out |\n\n"
        "### Limits\n\n"
        "- Max PDF size: 50 MB\n"
        "- Conversion timeout: 120 seconds\n"
        "- Download timeout: 30 seconds\n"
        "- Cache TTL: 30 days\n"
        "- No authentication required\n"
        "- No rate limit (fair use)\n\n"
        "### Install as agent skill\n\n"
        f"The SKILL.md at `https://{settings.domain}/skill` follows the "
        "[Agent Skills](https://agentskills.io) open standard. Install it with:\n\n"
        "```bash\n"
        "# Claude Code\n"
        f"mkdir -p ~/.claude/skills/unpdf && curl -s https://{settings.domain}/skill > ~/.claude/skills/unpdf/SKILL.md\n\n"
        "# Cursor\n"
        f"mkdir -p .cursor/skills/unpdf && curl -s https://{settings.domain}/skill > .cursor/skills/unpdf/SKILL.md\n\n"
        "# Windsurf\n"
        f"mkdir -p .windsurf/skills/unpdf && curl -s https://{settings.domain}/skill > .windsurf/skills/unpdf/SKILL.md\n\n"
        "# GitHub Copilot\n"
        f"mkdir -p .github/skills/unpdf && curl -s https://{settings.domain}/skill > .github/skills/unpdf/SKILL.md\n"
        "```\n\n"
        "### Tech stack\n\n"
        "- [pymupdf4llm](https://github.com/pymupdf/RAG): rule-based PDF to markdown (no ML models)\n"
        "- [FastAPI](https://fastapi.tiangolo.com/): async web framework\n"
        "- [httpx](https://www.python-httpx.org/): async HTTP client for PDF downloads\n"
        "- [Scaleway Serverless Containers](https://www.scaleway.com/en/serverless-containers/): scale-to-zero deployment\n\n"
        "### Source\n\n"
        "- GitHub: https://github.com/ClementWalter/pdf-to-md\n"
    )
    return _markdown_response(content)


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
