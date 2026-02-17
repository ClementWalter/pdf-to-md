"""Application settings loaded from environment variables via pydantic-settings."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All configuration for pdf2md, loaded from env vars with sensible defaults.

    Environment variable prefix: ``PDF2MD_``
    """

    model_config = {"env_prefix": "PDF2MD_"}

    # Public domain name used in usage text and image URLs
    domain: str = "localhost:8000"

    # Local filesystem path for the conversion cache
    cache_dir: Path = Path("./cache")

    # Reject PDFs larger than this (megabytes)
    max_pdf_size_mb: int = 50

    # Number of days before cached conversions expire
    cache_ttl_days: int = 30

    # Timeout in seconds for downloading source PDFs
    download_timeout: int = 30

    # Timeout in seconds for Marker conversion
    conversion_timeout: int = 120

    @property
    def max_pdf_size_bytes(self) -> int:
        """Max PDF size expressed in bytes for comparison with Content-Length."""
        return self.max_pdf_size_mb * 1024 * 1024


def get_settings() -> Settings:
    """Factory that creates a Settings instance (useful for FastAPI dependency injection)."""
    return Settings()
