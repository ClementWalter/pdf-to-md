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

    def __init__(self, cache_dir: Path, ttl_days: int = 0) -> None:
        self._cache_dir = cache_dir
        # 0 means keep forever — no expiration
        self._ttl_seconds = ttl_days * 86400 if ttl_days > 0 else 0
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

        created_at = meta.get("created_at", 0)

        # TTL check — skip when ttl_seconds is 0 (keep forever)
        if self._ttl_seconds > 0 and time.time() - created_at > self._ttl_seconds:
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

        self._increment_counter()
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

    def stats(self) -> dict:
        """Return usage statistics: total reads and current cache size."""
        stats_path = self._cache_dir / "_stats.json"
        data = {}
        if stats_path.exists():
            try:
                data = json.loads(stats_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        # Count current valid cache entries (directories with meta.json)
        cached = sum(
            1
            for d in self._cache_dir.iterdir()
            if d.is_dir() and (d / "meta.json").exists()
        )

        return {
            "total_conversions": data.get("total_conversions", 0),
            "total_reads": data.get("total_reads", 0),
            "cached_pdfs": cached,
        }

    def record_read(self) -> None:
        """Increment the total reads counter — called on every successful PDF response."""
        self._update_stat("total_reads")

    def _increment_counter(self) -> None:
        """Increment the total conversions counter — called on fresh conversions only."""
        self._update_stat("total_conversions")

    def _update_stat(self, key: str) -> None:
        """Atomically increment a named counter in the stats file."""
        stats_path = self._cache_dir / "_stats.json"
        data = {}
        if stats_path.exists():
            try:
                data = json.loads(stats_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        data[key] = data.get(key, 0) + 1
        stats_path.write_text(json.dumps(data))

    def _evict(self, cache_key: str) -> None:
        """Remove a cache entry from disk."""
        entry_dir = self._entry_dir(cache_key)
        if entry_dir.exists():
            shutil.rmtree(entry_dir)
            logger.info("Evicted cache entry %s", cache_key)
