"""Tests for the content generation module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from generators.content import (
    TOPIC_IDS,
    TOPIC_MAP,
    TOPICS,
    ContentCache,
    ContentGenerator,
)

# ========== ContentCache Tests ==========


class TestContentCache:
    """Tests for ContentCache loading and content retrieval."""

    @pytest.fixture
    def sample_cache_data(self):
        """Create sample cache data."""
        return {
            "metadata": {
                "generated_at": "2026-03-16T10:00:00",
                "model": "claude-sonnet-4-6",
                "topics": ["project_mgmt", "marketing"],
                "docs_per_topic": 4,
                "ko_ratio": 0.7,
            },
            "topics": {
                "project_mgmt": {
                    "pages": [
                        {
                            "language": "ko",
                            "title": "2026년 프로젝트 현황",
                            "body": "<h2>개요</h2><p>내용</p>",
                            "keywords": ["프로젝트", "진행"],
                            "updates": [
                                {"body": "<h2>개요</h2><p>업데이트</p>", "version_message": "2분기 반영"},
                                {"body": "<h2>개요</h2><p>최종</p>", "version_message": "최종본"},
                            ],
                        },
                        {
                            "language": "en",
                            "title": "Q1 Project Status",
                            "body": "<h2>Overview</h2><p>Content</p>",
                            "keywords": ["project", "status"],
                            "updates": [
                                {"body": "<h2>Overview</h2><p>Updated</p>", "version_message": "Q2 update"},
                            ],
                        },
                    ],
                    "blogposts": [
                        {
                            "language": "ko",
                            "title": "프로젝트 블로그",
                            "body": "<p>블로그 내용</p>",
                            "keywords": ["블로그"],
                            "updates": [],
                        },
                    ],
                    "comments": [
                        {"language": "ko", "body": "확인 부탁드립니다."},
                        {"language": "en", "body": "Looks good!"},
                    ],
                },
                "marketing": {
                    "pages": [
                        {
                            "language": "ko",
                            "title": "마케팅 전략 보고서",
                            "body": "<p>마케팅</p>",
                            "keywords": ["마케팅"],
                            "updates": [],
                        },
                    ],
                    "blogposts": [],
                    "comments": [],
                },
            },
        }

    @pytest.fixture
    def cache_file(self, tmp_path, sample_cache_data):
        """Write sample cache to a temp file."""
        path = tmp_path / "content_cache.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sample_cache_data, f, ensure_ascii=False)
        return path

    def test_load_success(self, cache_file):
        cache = ContentCache(cache_file)
        assert cache.load() is True

    def test_load_file_not_found(self, tmp_path):
        cache = ContentCache(tmp_path / "nonexistent.json")
        assert cache.load() is False

    def test_load_invalid_json(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid json")
        cache = ContentCache(bad_file)
        assert cache.load() is False

    def test_topics_property(self, cache_file):
        cache = ContentCache(cache_file)
        cache.load()
        assert cache.topics == ["project_mgmt", "marketing"]

    def test_topics_empty_without_load(self):
        cache = ContentCache(Path("nonexistent"))
        assert cache.topics == []

    def test_get_content_pages(self, cache_file):
        cache = ContentCache(cache_file)
        cache.load()
        content = cache.get_content("project_mgmt", "pages", 0)
        assert content is not None
        assert content["language"] == "ko"
        assert content["title"] == "2026년 프로젝트 현황"

    def test_get_content_index_wraps(self, cache_file):
        cache = ContentCache(cache_file)
        cache.load()
        # project_mgmt has 2 pages, index 2 should wrap to index 0
        content = cache.get_content("project_mgmt", "pages", 2)
        assert content is not None
        assert content["language"] == "ko"  # Same as index 0

    def test_get_content_comments(self, cache_file):
        cache = ContentCache(cache_file)
        cache.load()
        content = cache.get_content("project_mgmt", "comments", 1)
        assert content is not None
        assert content["language"] == "en"
        assert content["body"] == "Looks good!"

    def test_get_content_unknown_topic(self, cache_file):
        cache = ContentCache(cache_file)
        cache.load()
        assert cache.get_content("unknown_topic", "pages", 0) is None

    def test_get_content_empty_type(self, cache_file):
        cache = ContentCache(cache_file)
        cache.load()
        # marketing has no blogposts
        assert cache.get_content("marketing", "blogposts", 0) is None

    def test_get_content_without_load(self):
        cache = ContentCache(Path("nonexistent"))
        assert cache.get_content("any", "pages", 0) is None

    def test_get_content_by_language_ko(self, cache_file):
        cache = ContentCache(cache_file)
        cache.load()
        content = cache.get_content_by_language("project_mgmt", "pages", 0, "ko")
        assert content is not None
        assert content["language"] == "ko"

    def test_get_content_by_language_en(self, cache_file):
        cache = ContentCache(cache_file)
        cache.load()
        content = cache.get_content_by_language("project_mgmt", "pages", 0, "en")
        assert content is not None
        assert content["language"] == "en"

    def test_get_content_by_language_mixed(self, cache_file):
        cache = ContentCache(cache_file)
        cache.load()
        # mixed just uses modular index
        content = cache.get_content_by_language("project_mgmt", "pages", 0, "mixed")
        assert content is not None

    def test_get_content_by_language_fallback(self, cache_file):
        cache = ContentCache(cache_file)
        cache.load()
        # marketing only has ko pages, requesting en should fallback
        content = cache.get_content_by_language("marketing", "pages", 0, "en")
        assert content is not None
        assert content["language"] == "ko"  # Fallback to available content

    def test_get_content_by_language_without_load(self):
        cache = ContentCache(Path("nonexistent"))
        assert cache.get_content_by_language("any", "pages", 0, "ko") is None


# ========== ContentGenerator Tests ==========


class TestContentGenerator:
    """Tests for ContentGenerator with mocked Claude API."""

    @pytest.fixture
    def mock_anthropic(self):
        """Mock the anthropic module."""
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            import anthropic

            mock_client = MagicMock()
            anthropic.Anthropic.return_value = mock_client
            yield mock_client

    def test_init_requires_anthropic(self):
        """Test that init raises ImportError if anthropic not installed."""
        with patch.dict("sys.modules", {"anthropic": None}):
            with pytest.raises(ImportError, match="anthropic package is required"):
                ContentGenerator(api_key="test-key")

    def test_generate_documents_success(self, mock_anthropic, tmp_path):
        """Test document generation with mocked Claude response."""
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text=json.dumps(
                    [
                        {
                            "title": "Test Document",
                            "body": "<h2>Test</h2><p>Content</p>",
                            "keywords": ["test"],
                            "updates": [{"body": "<p>Update</p>", "version_message": "Updated"}],
                        }
                    ]
                )
            )
        ]
        mock_anthropic.messages.create.return_value = mock_response

        gen = ContentGenerator.__new__(ContentGenerator)
        gen.client = mock_anthropic
        gen.model = "claude-sonnet-4-6"
        gen.cache_dir = tmp_path
        gen.cache_path = tmp_path / "content_cache.json"

        topic = {"id": "development", "ko": "소프트웨어 개발", "en": "Software Development"}
        docs = gen._generate_documents(topic, "en", 1)

        assert len(docs) == 1
        assert docs[0]["title"] == "Test Document"
        assert docs[0]["language"] == "en"

    def test_generate_documents_invalid_json(self, mock_anthropic, tmp_path):
        """Test that invalid JSON from Claude is handled gracefully."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="not valid json")]
        mock_anthropic.messages.create.return_value = mock_response

        gen = ContentGenerator.__new__(ContentGenerator)
        gen.client = mock_anthropic
        gen.model = "claude-sonnet-4-6"
        gen.cache_dir = tmp_path
        gen.cache_path = tmp_path / "content_cache.json"

        topic = {"id": "development", "ko": "소프트웨어 개발", "en": "Software Development"}
        docs = gen._generate_documents(topic, "en", 1)
        assert docs == []

    def test_generate_comments_success(self, mock_anthropic, tmp_path):
        """Test comment generation with mocked Claude response."""
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text=json.dumps(
                    [
                        {"body": "Great work!"},
                        {"body": "확인했습니다."},
                    ]
                )
            )
        ]
        mock_anthropic.messages.create.return_value = mock_response

        gen = ContentGenerator.__new__(ContentGenerator)
        gen.client = mock_anthropic
        gen.model = "claude-sonnet-4-6"
        gen.cache_dir = tmp_path
        gen.cache_path = tmp_path / "content_cache.json"

        topic = {"id": "hr", "ko": "인사/채용", "en": "HR & Recruiting"}
        comments = gen._generate_comments(topic, "ko", 2)

        assert len(comments) == 2
        assert comments[0]["language"] == "ko"

    def test_save_cache_atomic(self, mock_anthropic, tmp_path):
        """Test that cache is saved atomically (temp file + replace)."""
        gen = ContentGenerator.__new__(ContentGenerator)
        gen.client = mock_anthropic
        gen.model = "claude-sonnet-4-6"
        gen.cache_dir = tmp_path
        gen.cache_path = tmp_path / "content_cache.json"

        data = {"metadata": {"topics": []}, "topics": {}}
        gen._save_cache(data)

        assert gen.cache_path.exists()
        loaded = json.loads(gen.cache_path.read_text())
        assert loaded == data
        # Temp file should not remain
        assert not (tmp_path / "content_cache.tmp").exists()

    def test_generate_corpus_creates_cache(self, mock_anthropic, tmp_path):
        """Test end-to-end corpus generation creates cache file."""
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text=json.dumps(
                    [
                        {
                            "title": "Doc 1",
                            "body": "<p>Body</p>",
                            "keywords": ["test"],
                            "updates": [],
                        }
                    ]
                )
            )
        ]
        mock_anthropic.messages.create.return_value = mock_response

        gen = ContentGenerator.__new__(ContentGenerator)
        gen.client = mock_anthropic
        gen.model = "claude-sonnet-4-6"
        gen.cache_dir = tmp_path
        gen.cache_path = tmp_path / "content_cache.json"

        result = gen.generate_corpus(num_topics=1, docs_per_topic=2, ko_ratio=0.5, comments_per_topic=2)

        assert "metadata" in result
        assert "topics" in result
        assert gen.cache_path.exists()
        assert result["metadata"]["topics"] == ["project_mgmt"]


# ========== Topic Definitions Tests ==========


class TestTopicDefinitions:
    """Tests for topic definitions."""

    def test_topic_count(self):
        assert len(TOPICS) == 10

    def test_topic_ids_match(self):
        assert TOPIC_IDS == [t["id"] for t in TOPICS]

    def test_topic_map_complete(self):
        for topic in TOPICS:
            assert topic["id"] in TOPIC_MAP
            assert TOPIC_MAP[topic["id"]]["ko"]
            assert TOPIC_MAP[topic["id"]]["en"]

    def test_topic_ids_unique(self):
        assert len(set(TOPIC_IDS)) == len(TOPIC_IDS)
