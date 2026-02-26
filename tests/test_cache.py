"""Tests for pdf2md.cache — disk-based conversion cache."""

import json
import time

import pytest

from pdf2md.cache import DiskCache, url_to_cache_key


@pytest.fixture()
def cache_dir(tmp_path):
    """Provide a temporary directory for cache tests."""
    return tmp_path / "cache"


@pytest.fixture()
def cache(cache_dir):
    """Provide a DiskCache instance backed by a temp directory."""
    return DiskCache(cache_dir)


class TestUrlToCacheKey:
    """Verify deterministic hashing of URLs."""

    def test_same_url_produces_same_key(self) -> None:
        url = "https://example.com/doc.pdf"
        assert url_to_cache_key(url) == url_to_cache_key(url)

    def test_different_urls_produce_different_keys(self) -> None:
        key1 = url_to_cache_key("https://example.com/a.pdf")
        key2 = url_to_cache_key("https://example.com/b.pdf")
        assert key1 != key2

    def test_key_is_hex_sha256(self) -> None:
        key = url_to_cache_key("https://example.com/doc.pdf")
        assert len(key) == 64  # SHA-256 hex digest length


class TestDiskCacheMiss:
    """Verify cache miss behavior."""

    def test_get_returns_none_for_unknown_url(self, cache) -> None:
        assert cache.get("https://example.com/not-cached.pdf") is None

    def test_get_returns_none_for_missing_entry(self, cache) -> None:
        assert cache.get("https://never.seen/file.pdf") is None


class TestDiskCachePutAndGet:
    """Verify round-trip cache storage and retrieval."""

    def test_put_then_get_returns_markdown(self, cache) -> None:
        url = "https://example.com/doc.pdf"
        cache.put(url, "# Hello", {}, page_count=1)
        entry = cache.get(url)
        assert entry.markdown == "# Hello"

    def test_put_then_get_returns_page_count(self, cache) -> None:
        url = "https://example.com/doc.pdf"
        cache.put(url, "content", {}, page_count=5)
        entry = cache.get(url)
        assert entry.page_count == 5

    def test_put_then_get_returns_source_url(self, cache) -> None:
        url = "https://example.com/doc.pdf"
        cache.put(url, "content", {}, page_count=1)
        entry = cache.get(url)
        assert entry.source_url == url

    def test_put_stores_images_on_disk(self, cache, cache_dir) -> None:
        url = "https://example.com/doc.pdf"
        images = {"fig1.png": b"\x89PNG_FAKE_DATA"}
        cache.put(url, "# With Image", images, page_count=1)
        entry = cache.get(url)
        assert (entry.images_dir / "fig1.png").exists()

    def test_put_overwrites_existing_entry(self, cache) -> None:
        url = "https://example.com/doc.pdf"
        cache.put(url, "version 1", {}, page_count=1)
        cache.put(url, "version 2", {}, page_count=2)
        entry = cache.get(url)
        assert entry.markdown == "version 2"


class TestDiskCacheTTL:
    """Verify cache expiration when TTL is enabled."""

    def test_expired_entry_returns_none_when_ttl_enabled(self, cache_dir) -> None:
        # Create a cache with 1-day TTL to test expiration still works when enabled
        cache = DiskCache(cache_dir, ttl_days=1)
        url = "https://example.com/doc.pdf"

        # Manually write an entry with a timestamp beyond TTL
        key = url_to_cache_key(url)
        entry_dir = cache_dir / key
        entry_dir.mkdir(parents=True)
        (entry_dir / "result.md").write_text("old content")
        (entry_dir / "images").mkdir()
        meta = {"source_url": url, "created_at": time.time() - 86401, "page_count": 1, "image_count": 0}
        (entry_dir / "meta.json").write_text(json.dumps(meta))

        assert cache.get(url) is None

    def test_old_entry_persists_when_ttl_disabled(self, cache_dir) -> None:
        # Default ttl_days=0 means keep forever
        cache = DiskCache(cache_dir)
        url = "https://example.com/doc.pdf"

        # Manually write an entry with a very old timestamp
        key = url_to_cache_key(url)
        entry_dir = cache_dir / key
        entry_dir.mkdir(parents=True)
        (entry_dir / "result.md").write_text("ancient content")
        (entry_dir / "images").mkdir()
        meta = {"source_url": url, "created_at": 0, "page_count": 1, "image_count": 0}
        (entry_dir / "meta.json").write_text(json.dumps(meta))

        entry = cache.get(url)
        assert entry is not None
        assert entry.markdown == "ancient content"


class TestDiskCacheImagePath:
    """Verify image path lookup."""

    def test_image_path_returns_path_when_exists(self, cache) -> None:
        url = "https://example.com/doc.pdf"
        images = {"fig1.png": b"\x89PNG_DATA"}
        cache.put(url, "# Doc", images, page_count=1)
        key = url_to_cache_key(url)
        path = cache.image_path(key, "fig1.png")
        assert path is not None

    def test_image_path_returns_none_when_missing(self, cache) -> None:
        assert cache.image_path("nonexistent_key", "nope.png") is None


class TestDiskCacheStats:
    """Verify usage statistics tracking."""

    def test_stats_starts_at_zero_conversions(self, cache) -> None:
        assert cache.stats()["total_conversions"] == 0

    def test_stats_starts_at_zero_reads(self, cache) -> None:
        assert cache.stats()["total_reads"] == 0

    def test_stats_conversions_increments_on_put(self, cache) -> None:
        cache.put("https://example.com/a.pdf", "# A", {}, page_count=1)
        assert cache.stats()["total_conversions"] == 1

    def test_stats_conversions_increments_multiple_times(self, cache) -> None:
        cache.put("https://example.com/a.pdf", "# A", {}, page_count=1)
        cache.put("https://example.com/b.pdf", "# B", {}, page_count=2)
        assert cache.stats()["total_conversions"] == 2

    def test_stats_cached_pdfs_counts_entries(self, cache) -> None:
        cache.put("https://example.com/a.pdf", "# A", {}, page_count=1)
        cache.put("https://example.com/b.pdf", "# B", {}, page_count=1)
        assert cache.stats()["cached_pdfs"] == 2

    def test_record_read_increments_total_reads(self, cache) -> None:
        cache.record_read()
        assert cache.stats()["total_reads"] == 1

    def test_record_read_increments_multiple_times(self, cache) -> None:
        cache.record_read()
        cache.record_read()
        cache.record_read()
        assert cache.stats()["total_reads"] == 3

    def test_record_read_independent_of_conversions(self, cache) -> None:
        cache.put("https://example.com/a.pdf", "# A", {}, page_count=1)
        cache.record_read()
        cache.record_read()
        assert cache.stats()["total_conversions"] == 1

    def test_put_does_not_increment_reads(self, cache) -> None:
        cache.put("https://example.com/a.pdf", "# A", {}, page_count=1)
        assert cache.stats()["total_reads"] == 0
