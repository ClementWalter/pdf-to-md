# PRD: pdf2md — PDF to Markdown conversion service

## Context

There is no simple, URL-addressable way to get a markdown representation of a PDF hosted on the web. Researchers, developers, and LLM pipelines regularly need structured text from PDFs but must download files, run local tools, and manage outputs manually. **pdf2md** solves this by providing a stateless URL convention: given a PDF at `https://site.com/path/file.pdf`, navigating to `{DOMAIN}/site.com/path/file.pdf` returns the markdown.

---

## 1. Product Overview

**One-liner:** A web service that converts any publicly-accessible PDF to markdown via a simple URL rewrite.

**URL convention:**
```
https://{DOMAIN}/<origin-host>/<path-to-pdf>
```
Example: `https://{DOMAIN}/arxiv.org/pdf/2301.00001v1.pdf` converts `https://arxiv.org/pdf/2301.00001v1.pdf`.

The domain name is configurable via environment variable (`PDF2MD_DOMAIN`). No domain has been purchased yet.

**Primary audience:** AI agents and LLM pipelines that need to read PDFs from the web.

---

## 2. User Stories

| # | As a… | I want to… | So that… |
|---|-------|-----------|----------|
| 1 | AI agent | Prepend `{DOMAIN}/` to any PDF URL and get markdown back | I can ingest PDF content into my context without manual conversion |
| 2 | Developer | Hit a URL and get raw markdown of a PDF | I can pipe PDF content into LLM pipelines |
| 3 | API consumer | `GET /<pdf-url>` and receive markdown with metadata | I can integrate PDF conversion into my toolchain |
| 4 | Return visitor | Get instant results for a previously-converted PDF | I don't wait for re-processing |

---

## 3. Functional Requirements

### 3.1 Core conversion

| ID | Requirement | Priority |
|----|------------|----------|
| F1 | Accept any publicly-accessible PDF URL via the URL path | P0 |
| F2 | Download the PDF, convert to markdown using **Marker** | P0 |
| F3 | Preserve text with full accuracy (no hallucinated content) | P0 |
| F4 | Detect and convert mathematical formulas to LaTeX (`$...$` / `$$...$$`) | P0 |
| F5 | Extract images, store them, and replace with accessible URLs | P0 |
| F6 | Preserve document structure: headings, lists, tables, code blocks | P0 |

### 3.2 URL routing

| ID | Requirement | Priority |
|----|------------|----------|
| R1 | `GET /` → returns a plain markdown file (`text/markdown`) explaining how to use the service (prepend `{DOMAIN}/` to a PDF URL) | P0 |
| R2 | `GET /<host>/<path>` → returns raw markdown (`text/markdown`) of the converted PDF | P0 |
| R3 | `GET /images/<hash>/<filename>` → serves extracted images | P0 |

There is no landing page, no HTML rendering, no frontend. Every response is either `text/markdown` or an image. This is a service for machines (AI agents), not humans.

### 3.3 Image handling

| ID | Requirement | Priority |
|----|------------|----------|
| I1 | Extracted images stored under `/images/<hash>/<image-name>.png` | P0 |
| I2 | Markdown references images via relative URLs: `![alt](/images/<hash>/fig1.png)` | P0 |
| I3 | Image URLs are stable — same PDF always produces same image paths | P0 |
| I4 | Images served with long cache headers (`Cache-Control: public, max-age=31536000`) | P1 |

### 3.4 Caching

| ID | Requirement | Priority |
|----|------------|----------|
| C1 | Cache conversion results (markdown + images) on disk | P0 |
| C2 | Cache key = SHA-256 of the normalized source PDF URL | P0 |
| C3 | Return cached result on subsequent requests (< 100ms) | P0 |
| C4 | Cache entries expire after 30 days (configurable via `PDF2MD_CACHE_TTL_DAYS`) | P2 |
| C5 | `?refresh=true` query param to force re-conversion | P2 |

---

## 4. Non-Functional Requirements

| ID | Requirement | Target |
|----|------------|--------|
| N1 | Conversion latency | < 30s for a 20-page PDF |
| N2 | Concurrent conversions | At least 4 simultaneous |
| N3 | Max PDF size | 50 MB |
| N4 | Uptime | 99% (non-critical service) |
| N5 | No authentication required | Public service |
| N6 | Domain configurable | Via `PDF2MD_DOMAIN` env var |

---

## 5. Technical Architecture

### 5.1 Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Web framework | **FastAPI** + Uvicorn | Async, fast, auto-docs, Python ecosystem |
| PDF engine | **Marker** (`marker-pdf`) | Fastest open-source, good LaTeX, low hallucination |
| Cache / storage | Local filesystem initially, Scaleway Object Storage (S3-compatible) for prod | Simple, durable |
| Deployment | **Scaleway** container (Docker) | Existing infra, EU hosting |
| Domain | Configurable (`PDF2MD_DOMAIN` env var) | TBD — not purchased yet |

### 5.2 Request flow

```
Client request: GET /arxiv.org/pdf/2301.00001v1.pdf
        │
        ▼
   ┌─────────┐
   │ FastAPI  │──── Check cache (SHA-256 of URL)
   │ Router   │         │
   └─────────┘    ┌─────┴──────┐
                  │ Cache HIT  │ → Return cached markdown (text/markdown)
                  │ Cache MISS │
                  └─────┬──────┘
                        │
                  Download PDF from https://arxiv.org/pdf/2301.00001v1.pdf
                        │
                  ┌─────▼──────┐
                  │   Marker   │ → Convert PDF to markdown
                  │   Engine   │ → Extract images
                  └─────┬──────┘
                        │
                  Store markdown + images in cache
                        │
                  Return markdown (text/markdown)
```

### 5.3 Project structure

```
pdf-to-md/
├── pyproject.toml              # Project config, dependencies
├── Dockerfile
├── docker-compose.yml
├── PRD.md                      # This document
├── src/
│   └── pdf2md/
│       ├── __init__.py
│       ├── main.py             # FastAPI app, routes
│       ├── converter.py        # Marker wrapper, PDF→MD logic
│       ├── cache.py            # Cache read/write (disk / S3)
│       ├── downloader.py       # PDF fetching with validation
│       └── config.py           # Settings via pydantic-settings
├── tests/
│   ├── test_converter.py
│   ├── test_cache.py
│   ├── test_downloader.py
│   └── test_routes.py
└── .github/
    └── workflows/
        └── deploy.yml          # CI/CD to Scaleway
```

### 5.4 Configuration

All configuration via environment variables (with sensible defaults):

| Variable | Default | Description |
|----------|---------|-------------|
| `PDF2MD_DOMAIN` | `localhost:8000` | Public domain name (used in image URLs) |
| `PDF2MD_CACHE_DIR` | `./cache` | Local cache directory path |
| `PDF2MD_MAX_PDF_SIZE_MB` | `50` | Max allowed PDF size in MB |
| `PDF2MD_CACHE_TTL_DAYS` | `30` | Cache expiration in days |
| `PDF2MD_DOWNLOAD_TIMEOUT` | `30` | PDF download timeout in seconds |
| `PDF2MD_CONVERSION_TIMEOUT` | `120` | Marker conversion timeout in seconds |

---

## 6. API Specification

### `GET /`

Returns a plain markdown file explaining how to use the service.

**Response:** `200 OK` with `Content-Type: text/markdown`

```markdown
# pdf2md

Convert any PDF to markdown by prepending this domain to the PDF URL.

## Usage

Given a PDF at:
  https://arxiv.org/pdf/2301.00001v1.pdf

Get its markdown at:
  https://{DOMAIN}/arxiv.org/pdf/2301.00001v1.pdf

Images are extracted and available at their referenced URLs within the markdown.
```

### `GET /<host>/<path>`

Downloads the PDF at `https://<host>/<path>`, converts it, and returns raw markdown.

**Response:** `200 OK` with `Content-Type: text/markdown; charset=utf-8`

**Headers:**
- `X-Source-URL: https://<host>/<path>` — the original PDF URL
- `X-Cached: true|false` — whether the result was served from cache
- `X-Conversion-Time-Ms: 4200` — conversion time (0 if cached)
- `X-Page-Count: 12` — number of pages in the PDF

### `GET /images/<hash>/<filename>`

Serves a previously extracted image.

**Response:** `200 OK` with appropriate `Content-Type` (e.g., `image/png`)

### Error responses

| Status | Condition | Response body (text/markdown) |
|--------|-----------|-------------------------------|
| `400` | Invalid URL or not a PDF | `# Error\n\nURL does not point to a valid PDF.` |
| `404` | Source PDF not found (upstream 404) | `# Error\n\nPDF not found at source URL.` |
| `413` | PDF exceeds size limit | `# Error\n\nPDF exceeds maximum size of {MAX}MB.` |
| `502` | Failed to download source PDF | `# Error\n\nCould not download PDF. It may not be publicly accessible.` |
| `504` | Conversion timed out | `# Error\n\nConversion timed out.` |

Error responses are also `text/markdown` for consistency — agents can always parse the response the same way.

---

## 7. Edge Cases & Constraints

| Case | Handling |
|------|----------|
| PDF behind authentication | Return 502 — "PDF is not publicly accessible" |
| Scanned PDF (image-only) | Marker has OCR support; best-effort conversion |
| Corrupted PDF | Return 400 — "Could not parse PDF" |
| Very large PDF (> 50 MB) | Reject with 413 |
| Non-PDF URL | Return 400 — "URL does not point to a valid PDF" |
| Concurrent requests for same PDF | First request converts, others wait on the same result (dedup lock) |
| URL with query params | `{DOMAIN}/site.com/file.pdf?token=x` → fetch `https://site.com/file.pdf?token=x` |
| URL with port | `{DOMAIN}/site.com:8080/file.pdf` → fetch `https://site.com:8080/file.pdf` |
| `http://` source | Always upgrade to `https://` when fetching the source PDF |

---

## 8. Future Considerations (Out of Scope for V1)

- Rate limiting / abuse prevention
- User accounts and conversion history
- Webhook/callback for async conversion of large files
- Support for DOCX, PPTX, EPUB input
- Custom conversion options (e.g., skip images, page range)
- Browser extension for one-click conversion
- API key for programmatic access with higher limits
- HTML-rendered view of the markdown
- JSON API endpoint with structured metadata

---

## 9. Success Metrics

| Metric | Target |
|--------|--------|
| Conversion accuracy (text) | > 95% character-level accuracy on standard PDFs |
| LaTeX detection | > 80% of formulas correctly converted |
| P95 latency (cached) | < 200ms |
| P95 latency (uncached, 10-page PDF) | < 15s |

---

## 10. Open Questions

1. **Domain**: `pdf2md.com` availability and alternatives (`pdf2md.io`, `pdftomd.com`, `topdf.md`, etc.)
2. **Abuse prevention**: Should V1 have any rate limiting or is it fully open?
3. **Protocol**: Should we support fetching `http://` sources or always enforce `https://`?
4. **Image format**: Should images always be converted to PNG or preserved in their original format?
