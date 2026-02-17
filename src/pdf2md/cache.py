"""Disk-based cache for converted markdown and extracted images.

Cache layout on disk::

    <cache_dir>/
        <sha256_hex>/
            result.md          # converted markdown
            images/            # extracted images
                fig1.png
                fig2.png
            meta.json          # metadata: source URL, timestamp, page count
"""

import hashlib
import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Represents a cached conversion result."""

    markdown: str
    images_dir: Path
    page_count: int
    source_url: str
    created_at: float = field(default_factory=time.time)


def url_to_cache_key(url: str) -> str:
    """Compute a deterministic cache key from a normalized URL.

    Uses SHA-256 so that the same URL always maps to the same directory.
    """
    return hashlib.sha256(url.encode()).hexdigest()


class DiskCache:
    """Read/write conversion results on the local filesystem."""

    def __init__(self, cache_dir: Path, ttl_days: int = 30) -> None:
        self._cache_dir = cache_dir
        self._ttl_seconds = ttl_days * 86400
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _entry_dir(self, cache_key: str) -> Path:
        return self._cache_dir / cache_key

    def get(self, url: str) -> CacheEntry | None:
        """Return the cached result for *url*, or ``None`` on miss / expiry."""
        cache_key = url_to_cache_key(url)
        entry_dir = self._entry_dir(cache_key)
        meta_path = entry_dir / "meta.json"
        md_path = entry_dir / "result.md"

        if not md_path.exists() or not meta_path.exists():
            return None

        try:
            meta = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Corrupt cache metadata for %s — treating as miss", cache_key)
            return None

        # TTL check
        created_at = meta.get("created_at", 0)
        if time.time() - created_at > self._ttl_seconds:
            logger.info("Cache entry expired for %s", url)
            self._evict(cache_key)
            return None

        return CacheEntry(
            markdown=md_path.read_text(),
            images_dir=entry_dir / "images",
            page_count=meta.get("page_count", 0),
            source_url=meta.get("source_url", url),
            created_at=created_at,
        )

    def put(
        self,
        url: str,
        markdown: str,
        images: dict[str, bytes],
        page_count: int,
    ) -> CacheEntry:
        """Store a conversion result on disk and return the cache entry."""
        cache_key = url_to_cache_key(url)
        entry_dir = self._entry_dir(cache_key)

        # Wipe any prior partial entry
        if entry_dir.exists():
            shutil.rmtree(entry_dir)

        entry_dir.mkdir(parents=True)
        images_dir = entry_dir / "images"
        images_dir.mkdir()

        # Write markdown
        (entry_dir / "result.md").write_text(markdown)

        # Write images
        for filename, data in images.items():
            (images_dir / filename).write_bytes(data)

        # Write metadata
        now = time.time()
        meta = {
            "source_url": url,
            "created_at": now,
            "page_count": page_count,
            "image_count": len(images),
        }
        (entry_dir / "meta.json").write_text(json.dumps(meta))

        logger.info("Cached conversion for %s (%d pages, %d images)", url, page_count, len(images))

        return CacheEntry(
            markdown=markdown,
            images_dir=images_dir,
            page_count=page_count,
            source_url=url,
            created_at=now,
        )

    def image_path(self, cache_key: str, filename: str) -> Path | None:
        """Return the filesystem path for a cached image, or None if missing."""
        path = self._entry_dir(cache_key) / "images" / filename
        return path if path.exists() else None

    def _evict(self, cache_key: str) -> None:
        """Remove a cache entry from disk."""
        entry_dir = self._entry_dir(cache_key)
        if entry_dir.exists():
            shutil.rmtree(entry_dir)
            logger.info("Evicted cache entry %s", cache_key)
