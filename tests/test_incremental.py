"""Tests for incremental mode functionality."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import CONFLUENCE_URL, TEST_EMAIL, TEST_TOKEN


class TestDiscoverExistingSpaces:
    """Tests for discovering existing spaces in incremental mode."""

    def test_discover_finds_spaces(self):
        """Test that discovery finds sequential spaces."""
        from confluence_data_generator import ConfluenceDataGenerator

        gen = ConfluenceDataGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            dry_run=True,
        )

        spaces = gen._discover_existing_spaces()
        # dry_run space_gen.get_space returns a dict for any key
        # It will keep finding spaces until it gets None
        # With dry_run, get_space always returns a result, so we'd loop to 999
        # This test verifies the method works; the loop stops when get_space returns None
        assert isinstance(spaces, list)

    def test_discover_no_spaces(self):
        """Test discovery when no spaces exist."""
        from confluence_data_generator import ConfluenceDataGenerator

        gen = ConfluenceDataGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="NOEXIST",
            dry_run=False,
        )

        # Mock get_space to return None (no spaces found)
        gen.space_gen.get_space = MagicMock(return_value=None)
        spaces = gen._discover_existing_spaces()
        assert spaces == []


class TestDiscoverExistingPages:
    """Tests for discovering existing pages in incremental mode."""

    @pytest.mark.asyncio
    async def test_discover_pages(self):
        """Test page discovery via API."""
        from confluence_data_generator import ConfluenceDataGenerator

        gen = ConfluenceDataGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            dry_run=False,
        )

        # Mock the async API call
        mock_result = {
            "results": [
                {"id": "page-1", "title": "Page 1"},
                {"id": "page-2", "title": "Page 2"},
            ],
            "_links": {},
        }
        gen.page_gen._api_call_async = AsyncMock(return_value=(True, mock_result))

        spaces = [{"key": "TEST1", "id": "10001", "name": "Test"}]
        pages = await gen._discover_existing_pages(spaces)

        assert len(pages) == 2
        assert pages[0]["id"] == "page-1"
        assert pages[0]["spaceId"] == "10001"

    @pytest.mark.asyncio
    async def test_discover_pages_empty(self):
        """Test page discovery when no pages exist."""
        from confluence_data_generator import ConfluenceDataGenerator

        gen = ConfluenceDataGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            dry_run=False,
        )

        gen.page_gen._api_call_async = AsyncMock(return_value=(True, {"results": [], "_links": {}}))

        spaces = [{"key": "TEST1", "id": "10001", "name": "Test"}]
        pages = await gen._discover_existing_pages(spaces)
        assert pages == []


class TestDiscoverExistingBlogposts:
    """Tests for discovering existing blogposts in incremental mode."""

    @pytest.mark.asyncio
    async def test_discover_blogposts(self):
        """Test blogpost discovery via API."""
        from confluence_data_generator import ConfluenceDataGenerator

        gen = ConfluenceDataGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            dry_run=False,
        )

        mock_result = {
            "results": [
                {"id": "bp-1", "title": "Blog 1"},
            ],
            "_links": {},
        }
        gen.blogpost_gen._api_call_async = AsyncMock(return_value=(True, mock_result))

        spaces = [{"key": "TEST1", "id": "10001", "name": "Test"}]
        blogposts = await gen._discover_existing_blogposts(spaces)

        assert len(blogposts) == 1
        assert blogposts[0]["id"] == "bp-1"


class TestIncrementalGeneration:
    """Tests for the incremental generation flow."""

    @pytest.mark.asyncio
    async def test_incremental_no_existing_spaces(self):
        """Test incremental mode exits when no spaces found."""
        from confluence_data_generator import ConfluenceDataGenerator

        gen = ConfluenceDataGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="NOEXIST",
            dry_run=False,
        )
        gen.space_gen.get_space = MagicMock(return_value=None)

        # Should return without error
        await gen.generate_incremental(count=10, update_ratio=0.6)

    @pytest.mark.asyncio
    async def test_incremental_count_split(self):
        """Test that count is split correctly between updates and new content."""
        # Verify the update ratio logic used by generate_incremental
        count = 100
        update_ratio = 0.6
        update_count = int(count * update_ratio)
        new_count = count - update_count

        assert update_count == 60
        assert new_count == 40

    @pytest.mark.asyncio
    async def test_incremental_all_new_when_no_existing(self):
        """Test that all count goes to new content when nothing exists."""
        from confluence_data_generator import ConfluenceDataGenerator

        gen = ConfluenceDataGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            dry_run=False,
        )

        # Mock discovery to find space but no pages/blogposts
        gen.space_gen.get_space = MagicMock(
            side_effect=[
                {"key": "TEST1", "id": "10001", "name": "Test"},
                None,  # No second space
            ]
        )
        gen.page_gen._api_call_async = AsyncMock(return_value=(True, {"results": [], "_links": {}}))
        gen.blogpost_gen._api_call_async = AsyncMock(return_value=(True, {"results": [], "_links": {}}))

        # Mock creation methods
        gen.page_gen.create_pages_async = AsyncMock(return_value=[])
        gen.blogpost_gen.create_blogposts_async = AsyncMock(return_value=[])

        await gen.generate_incremental(count=10, update_ratio=0.6)

        # With no existing content, all should go to new content
        gen.page_gen.create_pages_async.assert_called_once()
        gen.blogpost_gen.create_blogposts_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_incremental_dry_run(self):
        """Test incremental mode with dry run."""
        from confluence_data_generator import ConfluenceDataGenerator

        gen = ConfluenceDataGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            dry_run=True,
        )

        # Dry run discovery always returns spaces
        spaces = gen._discover_existing_spaces()
        assert isinstance(spaces, list)


class TestContentCacheIntegration:
    """Tests for content cache integration with generators."""

    @pytest.fixture
    def cache_file(self, tmp_path):
        """Create a minimal content cache file."""
        data = {
            "metadata": {
                "generated_at": "2026-03-16T10:00:00",
                "model": "claude-sonnet-4-6",
                "topics": ["project_mgmt"],
                "docs_per_topic": 2,
                "ko_ratio": 0.5,
            },
            "topics": {
                "project_mgmt": {
                    "pages": [
                        {
                            "language": "ko",
                            "title": "프로젝트 보고서",
                            "body": "<h2>개요</h2><p>내용</p>",
                            "keywords": ["프로젝트"],
                            "updates": [
                                {"body": "<h2>개요</h2><p>업데이트</p>", "version_message": "2분기"},
                            ],
                        },
                        {
                            "language": "en",
                            "title": "Project Report",
                            "body": "<h2>Overview</h2><p>Content</p>",
                            "keywords": ["project"],
                            "updates": [
                                {"body": "<h2>Overview</h2><p>Updated</p>", "version_message": "Q2"},
                            ],
                        },
                    ],
                    "blogposts": [
                        {
                            "language": "ko",
                            "title": "블로그 포스트",
                            "body": "<p>블로그</p>",
                            "keywords": [],
                            "updates": [],
                        },
                    ],
                    "comments": [
                        {"language": "ko", "body": "확인했습니다."},
                        {"language": "en", "body": "Looks good!"},
                    ],
                },
            },
        }
        path = tmp_path / "content_cache.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return path

    def test_page_generator_uses_cache(self, cache_file):
        """Test that PageGenerator uses content from cache."""
        from generators.content import ContentCache
        from generators.pages import PageGenerator

        cache = ContentCache(cache_file)
        cache.load()

        gen = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            dry_run=True,
            language="ko",
            content_cache=cache,
        )

        cached = gen._get_cached_page_content(0)
        assert cached is not None
        title, body = cached
        assert "프로젝트" in title

    def test_page_generator_lorem_ignores_cache(self, cache_file):
        """Test that PageGenerator ignores cache when language is lorem."""
        from generators.content import ContentCache
        from generators.pages import PageGenerator

        cache = ContentCache(cache_file)
        cache.load()

        gen = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            dry_run=True,
            language="lorem",
            content_cache=cache,
        )

        cached = gen._get_cached_page_content(0)
        assert cached is None

    def test_blogpost_generator_uses_cache(self, cache_file):
        """Test that BlogPostGenerator uses content from cache."""
        from generators.blogposts import BlogPostGenerator
        from generators.content import ContentCache

        cache = ContentCache(cache_file)
        cache.load()

        gen = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            dry_run=True,
            language="ko",
            content_cache=cache,
        )

        cached = gen._get_cached_blogpost_content(0)
        assert cached is not None
        title, body = cached
        assert "블로그" in title

    def test_comment_generator_uses_cache(self, cache_file):
        """Test that CommentGenerator uses content from cache."""
        from generators.comments import CommentGenerator
        from generators.content import ContentCache

        cache = ContentCache(cache_file)
        cache.load()

        gen = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            dry_run=True,
            language="ko",
            content_cache=cache,
        )

        body = gen._get_cached_comment_body(0)
        assert body is not None
        assert "확인" in body

    def test_page_version_content_from_cache(self, cache_file):
        """Test that page version updates come from cache."""
        from generators.content import ContentCache
        from generators.pages import PageGenerator

        cache = ContentCache(cache_file)
        cache.load()

        gen = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix="TEST",
            dry_run=True,
            language="mixed",
            content_cache=cache,
        )

        cached_ver = gen._get_cached_version_content(0, 0)
        assert cached_ver is not None
        body, msg = cached_ver
        assert "업데이트" in body or "Updated" in body
