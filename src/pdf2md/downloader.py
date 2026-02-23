"""Download files from the web with size validation.

Supports both PDF-specific downloads (with magic-bytes check) and generic file
downloads for non-PDF types routed through MarkItDown.
"""

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


class DownloadError(Exception):
    """Base class for download failures — carries an HTTP status code for the client."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class FileTooLargeError(DownloadError):
    """The source file exceeds the configured size limit."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=413)


class FileNotFoundError_(DownloadError):
    """The upstream server returned 404 for the file URL."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=404)


class InvalidFileURLError(DownloadError):
    """The URL doesn't point to a valid file (wrong content-type, etc.)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=400)


# Backward-compatible aliases for PDF-specific error names
PDFTooLargeError = FileTooLargeError
PDFNotFoundError = FileNotFoundError_
InvalidPDFURLError = InvalidFileURLError


class DownloadTimeoutError(DownloadError):
    """The download timed out."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=504)


@dataclass
class DownloadResult:
    """Successful PDF download payload."""

    content: bytes
    content_type: str
    source_url: str


def normalize_url(host: str, path: str) -> str:
    """Build the source ``https://`` URL from the host and path segments.

    Always upgrades to HTTPS as per PRD requirement.
    """
    return f"https://{host}/{path}"


async def download_pdf(
    url: str,
    *,
    max_size_bytes: int,
    timeout: int,
) -> DownloadResult:
    """Fetch a PDF from *url* with validation.

    Raises domain-specific exceptions that map to HTTP error codes.
    """
    logger.info("Downloading PDF from %s", url)

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(timeout),
        ) as client:
            # Stream so we can check Content-Length before downloading the body
            async with client.stream("GET", url) as response:
                if response.status_code == 404:
                    raise PDFNotFoundError("PDF not found at source URL.")

                if response.status_code in (401, 403):
                    raise DownloadError(
                        "Could not download PDF. It may not be publicly accessible.",
                        status_code=502,
                    )

                if response.status_code >= 400:
                    raise DownloadError(
                        f"Could not download PDF. Upstream returned HTTP {response.status_code}.",
                        status_code=502,
                    )

                # Size guard via Content-Length header (if present)
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > max_size_bytes:
                    max_mb = max_size_bytes // (1024 * 1024)
                    raise PDFTooLargeError(
                        f"PDF exceeds maximum size of {max_mb}MB."
                    )

                # Read the full body
                content = await response.aread()

    except httpx.TimeoutException as exc:
        raise DownloadTimeoutError("Conversion timed out.") from exc
    except httpx.ConnectError as exc:
        raise DownloadError(
            "Could not download PDF. It may not be publicly accessible.",
            status_code=502,
        ) from exc
    except DownloadError:
        raise
    except httpx.HTTPError as exc:
        raise DownloadError(
            "Could not download PDF. It may not be publicly accessible.",
            status_code=502,
        ) from exc

    # Post-download size check (in case Content-Length was absent or lied)
    if len(content) > max_size_bytes:
        max_mb = max_size_bytes // (1024 * 1024)
        raise PDFTooLargeError(f"PDF exceeds maximum size of {max_mb}MB.")

    # Validate that the content looks like a PDF
    if not content.startswith(b"%PDF"):
        raise InvalidPDFURLError("URL does not point to a valid PDF.")

    return DownloadResult(
        content=content,
        content_type=response.headers.get("content-type", "application/pdf"),
        source_url=url,
    )


async def download_file(
    url: str,
    *,
    max_size_bytes: int,
    timeout: int,
) -> DownloadResult:
    """Fetch any file from *url* with size validation (no magic-bytes check).

    Used for non-PDF file types that are routed through MarkItDown.
    """
    logger.info("Downloading file from %s", url)

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(timeout),
        ) as client:
            async with client.stream("GET", url) as response:
                if response.status_code == 404:
                    raise FileNotFoundError_("File not found at source URL.")

                if response.status_code in (401, 403):
                    raise DownloadError(
                        "Could not download file. It may not be publicly accessible.",
                        status_code=502,
                    )

                if response.status_code >= 400:
                    raise DownloadError(
                        f"Could not download file. Upstream returned HTTP {response.status_code}.",
                        status_code=502,
                    )

                # Size guard via Content-Length header (if present)
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > max_size_bytes:
                    max_mb = max_size_bytes // (1024 * 1024)
                    raise FileTooLargeError(
                        f"File exceeds maximum size of {max_mb}MB."
                    )

                content = await response.aread()

    except httpx.TimeoutException as exc:
        raise DownloadTimeoutError("Download timed out.") from exc
    except httpx.ConnectError as exc:
        raise DownloadError(
            "Could not download file. It may not be publicly accessible.",
            status_code=502,
        ) from exc
    except DownloadError:
        raise
    except httpx.HTTPError as exc:
        raise DownloadError(
            "Could not download file. It may not be publicly accessible.",
            status_code=502,
        ) from exc

    # Post-download size check (in case Content-Length was absent or lied)
    if len(content) > max_size_bytes:
        max_mb = max_size_bytes // (1024 * 1024)
        raise FileTooLargeError(f"File exceeds maximum size of {max_mb}MB.")

    return DownloadResult(
        content=content,
        content_type=response.headers.get("content-type", "application/octet-stream"),
        source_url=url,
    )
