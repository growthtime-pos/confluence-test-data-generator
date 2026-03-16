"""
AI-powered content generation module.

Uses the Claude API (Anthropic) to pre-generate high-quality Korean/English
content for Confluence pages, blogposts, and comments. Content is cached to
a JSON file so that the API is only called once; subsequent runs pull from
the cache.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ========== Topic Definitions ==========

TOPICS = [
    {
        "id": "project_mgmt",
        "ko": "프로젝트 관리",
        "en": "Project Management",
    },
    {
        "id": "marketing",
        "ko": "마케팅 전략",
        "en": "Marketing Strategy",
    },
    {
        "id": "hr",
        "ko": "인사/채용",
        "en": "HR & Recruiting",
    },
    {
        "id": "finance",
        "ko": "재무/회계",
        "en": "Finance & Accounting",
    },
    {
        "id": "operations",
        "ko": "운영/프로세스",
        "en": "Operations",
    },
    {
        "id": "development",
        "ko": "소프트웨어 개발",
        "en": "Software Development",
    },
    {
        "id": "infrastructure",
        "ko": "인프라/클라우드",
        "en": "Infrastructure & Cloud",
    },
    {
        "id": "security",
        "ko": "정보보안",
        "en": "Information Security",
    },
    {
        "id": "data_engineering",
        "ko": "데이터 엔지니어링",
        "en": "Data Engineering",
    },
    {
        "id": "devops",
        "ko": "DevOps/CI/CD",
        "en": "DevOps & CI/CD",
    },
]

TOPIC_IDS = [t["id"] for t in TOPICS]

# Mapping from topic_id to topic info for quick lookup
TOPIC_MAP = {t["id"]: t for t in TOPICS}

GENERATION_PROMPT = """\
당신은 Confluence 위키에 올라갈 업무 문서를 작성하는 역할입니다.
주제: {topic_name}
언어: {language_instruction}

다음 형식으로 {count}개의 문서를 생성해주세요.

각 문서는:
1. 제목 (구체적이고 검색 가능한, 50자 이내)
2. 본문 (Confluence storage format HTML, 2-5 단락, <h2> 등 사용)
3. 키워드 (3-5개, 다른 문서와 연관 검색이 가능하도록)
4. 업데이트 버전 2개 (원본 내용을 수정/보완한 버전, 각각 body와 version_message 포함)

문서 간에 키워드가 자연스럽게 겹치도록 해주세요.
같은 주제 내 문서들은 서로 참조할 수 있는 내용이어야 합니다.

반드시 아래 JSON 형식으로만 출력하세요 (다른 텍스트 없이):
[
  {{
    "title": "...",
    "body": "<h2>...</h2><p>...</p>",
    "keywords": ["kw1", "kw2", "kw3"],
    "updates": [
      {{"body": "<h2>...</h2><p>...</p>", "version_message": "..."}},
      {{"body": "<h2>...</h2><p>...</p>", "version_message": "..."}}
    ]
  }}
]
"""

COMMENT_PROMPT = """\
Confluence 위키 댓글을 생성해주세요.
주제: {topic_name}
언어: {language_instruction}

{count}개의 댓글을 생성합니다. 각 댓글은 업무 문서에 달리는 현실적인 리뷰/피드백 댓글입니다.

반드시 아래 JSON 형식으로만 출력하세요 (다른 텍스트 없이):
[
  {{"body": "댓글 내용"}},
  {{"body": "댓글 내용"}}
]
"""


class ContentCache:
    """Loads and provides access to pre-generated content from a cache file.

    The cache is a JSON file with topic-keyed content including pages,
    blogposts, and comments. Content is selected deterministically by
    index (modular wrapping when index exceeds cache size).
    """

    def __init__(self, cache_path: Path | str):
        self.cache_path = Path(cache_path)
        self._data: dict[str, Any] | None = None

    def load(self) -> bool:
        """Load cache from disk. Returns True if successful."""
        if not self.cache_path.exists():
            logger.error(f"Content cache not found: {self.cache_path}")
            return False
        try:
            with open(self.cache_path) as f:
                self._data = json.load(f)
            topics = self._data.get("metadata", {}).get("topics", [])
            logger.info(f"Loaded content cache: {len(topics)} topics from {self.cache_path}")
            return True
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load content cache: {e}")
            return False

    @property
    def topics(self) -> list[str]:
        """Return list of topic IDs in the cache."""
        if not self._data:
            return []
        return self._data.get("metadata", {}).get("topics", [])

    def get_content(self, topic: str, content_type: str, index: int) -> dict | None:
        """Get content from cache by topic, type, and index.

        Args:
            topic: Topic ID (e.g. 'project_mgmt')
            content_type: 'pages', 'blogposts', or 'comments'
            index: Item index (wraps around via modulo)

        Returns:
            Content dict or None if not available.
        """
        if not self._data:
            return None
        topic_data = self._data.get("topics", {}).get(topic)
        if not topic_data:
            return None
        items = topic_data.get(content_type, [])
        if not items:
            return None
        return items[index % len(items)]

    def get_content_by_language(self, topic: str, content_type: str, index: int, language: str) -> dict | None:
        """Get content filtered by language preference.

        For 'mixed' language, uses index to alternate. For 'ko' or 'en',
        filters to that language and wraps index within the filtered set.
        """
        if not self._data:
            return None
        topic_data = self._data.get("topics", {}).get(topic)
        if not topic_data:
            return None
        items = topic_data.get(content_type, [])
        if not items:
            return None

        if language == "mixed":
            return items[index % len(items)]

        # Filter by language
        filtered = [item for item in items if item.get("language") == language]
        if not filtered:
            # Fallback to any available content
            return items[index % len(items)]
        return filtered[index % len(filtered)]


class ContentGenerator:
    """Generates topic-based content using the Claude API and saves to a JSON cache.

    Intended to be run once (or infrequently). Subsequent data generation
    runs read from the cache via ContentCache.
    """

    DEFAULT_CACHE_FILE = "content_cache.json"
    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(self, api_key: str, cache_dir: Path | str = Path("."), model: str | None = None):
        try:
            import anthropic
        except ImportError as err:
            raise ImportError(
                "anthropic package is required for content generation. Install with: pip install anthropic"
            ) from err

        self.client = anthropic.Anthropic(api_key=api_key)
        self.cache_dir = Path(cache_dir)
        self.cache_path = self.cache_dir / self.DEFAULT_CACHE_FILE
        self.model = model or self.DEFAULT_MODEL

    def generate_corpus(
        self,
        num_topics: int = 10,
        docs_per_topic: int = 20,
        ko_ratio: float = 0.7,
        comments_per_topic: int = 10,
    ) -> dict:
        """Generate a full content corpus and save to cache.

        Args:
            num_topics: Number of topics to generate (max 10)
            docs_per_topic: Documents per topic (split between pages/blogposts)
            ko_ratio: Ratio of Korean vs English content (0.0 - 1.0)
            comments_per_topic: Number of comments per topic

        Returns:
            The complete cache data dict
        """
        topics_to_use = TOPICS[:num_topics]
        topic_ids = [t["id"] for t in topics_to_use]

        logger.info(
            f"Generating content for {len(topics_to_use)} topics, {docs_per_topic} docs/topic, ko_ratio={ko_ratio}"
        )

        cache_data: dict[str, Any] = {
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "model": self.model,
                "topics": topic_ids,
                "docs_per_topic": docs_per_topic,
                "ko_ratio": ko_ratio,
            },
            "topics": {},
        }

        for topic in topics_to_use:
            topic_id = topic["id"]
            logger.info(f"Generating content for topic: {topic_id}")

            # Split docs between pages and blogposts (70/30)
            page_count = max(1, int(docs_per_topic * 0.7))
            blogpost_count = max(1, docs_per_topic - page_count)

            # Split by language
            ko_pages = max(1, int(page_count * ko_ratio))
            en_pages = max(1, page_count - ko_pages)
            ko_blogs = max(1, int(blogpost_count * ko_ratio))
            en_blogs = max(1, blogpost_count - ko_blogs)

            pages = []
            blogposts = []
            comments = []

            # Generate Korean pages
            if ko_pages > 0:
                pages.extend(self._generate_documents(topic, "ko", ko_pages))

            # Generate English pages
            if en_pages > 0:
                pages.extend(self._generate_documents(topic, "en", en_pages))

            # Generate Korean blogposts
            if ko_blogs > 0:
                blogposts.extend(self._generate_documents(topic, "ko", ko_blogs))

            # Generate English blogposts
            if en_blogs > 0:
                blogposts.extend(self._generate_documents(topic, "en", en_blogs))

            # Generate comments
            ko_comments = max(1, int(comments_per_topic * ko_ratio))
            en_comments = max(1, comments_per_topic - ko_comments)
            comments.extend(self._generate_comments(topic, "ko", ko_comments))
            comments.extend(self._generate_comments(topic, "en", en_comments))

            cache_data["topics"][topic_id] = {
                "pages": pages,
                "blogposts": blogposts,
                "comments": comments,
            }

        # Save to file
        self._save_cache(cache_data)
        logger.info(f"Content cache saved to {self.cache_path}")
        return cache_data

    def _generate_documents(self, topic: dict, language: str, count: int) -> list[dict]:
        """Generate documents for a topic in a specific language via Claude API."""
        topic_name = topic["ko"] if language == "ko" else topic["en"]
        lang_instruction = "한국어로 작성" if language == "ko" else "Write in English"

        prompt = GENERATION_PROMPT.format(
            topic_name=topic_name,
            language_instruction=lang_instruction,
            count=count,
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            content_text = response.content[0].text

            docs = json.loads(content_text)

            # Tag each doc with language
            for doc in docs:
                doc["language"] = language

            logger.info(f"  Generated {len(docs)} {language} documents for {topic['id']}")
            return docs

        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error(f"Failed to parse Claude response for {topic['id']} ({language}): {e}")
            return []
        except Exception as e:
            logger.error(f"Claude API call failed for {topic['id']} ({language}): {e}")
            return []

    def _generate_comments(self, topic: dict, language: str, count: int) -> list[dict]:
        """Generate comments for a topic in a specific language via Claude API."""
        topic_name = topic["ko"] if language == "ko" else topic["en"]
        lang_instruction = "한국어로 작성" if language == "ko" else "Write in English"

        prompt = COMMENT_PROMPT.format(
            topic_name=topic_name,
            language_instruction=lang_instruction,
            count=count,
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            content_text = response.content[0].text

            comments = json.loads(content_text)

            for comment in comments:
                comment["language"] = language

            logger.info(f"  Generated {len(comments)} {language} comments for {topic['id']}")
            return comments

        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error(f"Failed to parse comment response for {topic['id']} ({language}): {e}")
            return []
        except Exception as e:
            logger.error(f"Claude API call failed for comments {topic['id']} ({language}): {e}")
            return []

    def _save_cache(self, data: dict) -> None:
        """Save cache data to JSON file atomically."""
        temp_path = self.cache_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        temp_path.replace(self.cache_path)
