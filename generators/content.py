from __future__ import annotations

import hashlib
import html
import logging
import os
import random
from abc import ABC, abstractmethod
from typing import Any

import requests


class ContentProvider(ABC):
    def __init__(self, seed: int = 42):
        self.seed = seed

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def generate_text(
        self,
        min_words: int = 5,
        max_words: int = 20,
        *,
        kind: str = "generic",
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    def generate_storage_value(
        self,
        content_type: str,
        title: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        raise NotImplementedError


class LoremContentProvider(ContentProvider):
    _TEXT_POOL_SIZE = 1000
    _LOREM_WORDS = [
        "lorem",
        "ipsum",
        "dolor",
        "sit",
        "amet",
        "consectetur",
        "adipiscing",
        "elit",
        "sed",
        "do",
        "eiusmod",
        "tempor",
        "incididunt",
        "ut",
        "labore",
        "et",
        "dolore",
        "magna",
        "aliqua",
        "enim",
        "ad",
        "minim",
        "veniam",
        "quis",
        "nostrud",
        "exercitation",
        "ullamco",
        "laboris",
        "nisi",
        "aliquip",
        "ex",
        "ea",
        "commodo",
        "consequat",
        "duis",
        "aute",
        "irure",
        "in",
        "reprehenderit",
        "voluptate",
        "velit",
        "esse",
        "cillum",
        "fugiat",
        "nulla",
        "pariatur",
        "excepteur",
        "sint",
        "occaecat",
        "cupidatat",
        "non",
        "proident",
        "sunt",
        "culpa",
        "qui",
        "officia",
        "deserunt",
        "mollit",
        "anim",
        "id",
        "est",
        "laborum",
    ]

    def __init__(self, seed: int = 42):
        super().__init__(seed)
        self._pool = self._build_pool()

    @property
    def name(self) -> str:
        return "lorem"

    def _rng(self, *parts: Any) -> random.Random:
        payload = ":".join([str(self.seed), *[str(part) for part in parts]])
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return random.Random(int(digest[:16], 16))

    def _build_pool(self) -> dict[str, list[str]]:
        pool = {"short": [], "medium": [], "long": []}
        for category, limits in (("short", (3, 10)), ("medium", (5, 15)), ("long", (10, 30))):
            rng = self._rng("pool", category)
            low, high = limits
            for _ in range(self._TEXT_POOL_SIZE):
                word_count = rng.randint(low, high)
                text = " ".join(rng.choices(self._LOREM_WORDS, k=word_count)).capitalize()
                pool[category].append(text)
        return pool

    def generate_text(
        self,
        min_words: int = 5,
        max_words: int = 20,
        *,
        kind: str = "generic",
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        avg_words = (min_words + max_words) // 2
        if avg_words <= 7:
            category = "short"
        elif avg_words <= 12:
            category = "medium"
        else:
            category = "long"
        rng = self._rng("choice", category, kind, title, metadata or {})
        return rng.choice(self._pool[category])

    def generate_storage_value(
        self,
        content_type: str,
        title: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        escaped = html.escape(self.generate_text(10, 30, kind=content_type, title=title, metadata=metadata))
        return f"<p>{escaped}</p>"


class StructuredContentProvider(ContentProvider):
    _TOPICS = [
        "backup retention",
        "space provisioning",
        "restore readiness",
        "search indexing",
        "incident coordination",
        "release validation",
        "migration rehearsal",
        "permission hygiene",
        "template governance",
        "knowledge curation",
    ]
    _TEAMS = [
        "Platform Engineering",
        "Site Reliability",
        "Knowledge Systems",
        "Enterprise Tools",
        "Migration Operations",
        "Support Enablement",
    ]
    _OWNERS = ["Alex Kim", "Sam Park", "Jordan Lee", "Taylor Choi", "Morgan Han", "Casey Lim"]
    _STATUSES = ["Planned", "In Progress", "At Risk", "Validated", "Ready for rollout"]
    _ACTIONS = [
        "Audit content ownership",
        "Validate restore checkpoints",
        "Publish migration checklist",
        "Normalize page labels",
        "Review attachment growth",
        "Document rollback steps",
    ]
    _RISKS = [
        "legacy permissions drift",
        "missing ownership metadata",
        "stale templates in active spaces",
        "manual restore steps without validation",
        "high attachment churn during cutover",
    ]
    _HEADINGS = {
        "page": ["Overview", "Current State", "Action Plan", "Open Questions"],
        "blogpost": ["Summary", "Highlights", "Impact", "Next Steps"],
        "template": ["Purpose", "How To Use", "Suggested Sections", "Review Notes"],
        "comment": ["Feedback"],
    }

    @property
    def name(self) -> str:
        return "structured"

    def _rng(self, *parts: Any) -> random.Random:
        payload = ":".join([str(self.seed), *[str(part) for part in parts]])
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return random.Random(int(digest[:16], 16))

    def _pick(self, values: list[str], rng: random.Random) -> str:
        return values[rng.randrange(len(values))]

    def _sentence(self, rng: random.Random, topic: str, title: str, emphasis: str) -> str:
        team = self._pick(self._TEAMS, rng)
        owner = self._pick(self._OWNERS, rng)
        status = self._pick(self._STATUSES, rng).lower()
        fragments = [
            f"{title} tracks {topic} work owned by {team}",
            f"The current focus is {emphasis} so the next review can stay {status}",
            f"{owner} is responsible for turning this into an operational baseline",
        ]
        return ". ".join(fragments) + "."

    def generate_text(
        self,
        min_words: int = 5,
        max_words: int = 20,
        *,
        kind: str = "generic",
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        metadata = metadata or {}
        rng = self._rng("text", kind, title, metadata)
        topic = metadata.get("topic") or self._pick(self._TOPICS, rng)
        emphasis = self._pick(self._ACTIONS, rng).lower()
        if max_words <= 8:
            return f"{topic.title()} for {self._pick(self._TEAMS, rng)}"
        sentences = max(1, min(3, (min_words + max_words) // 10))
        body = [self._sentence(rng, topic, title or topic.title(), emphasis)]
        for _ in range(sentences - 1):
            risk = self._pick(self._RISKS, rng)
            body.append(f"The main watch item is {risk}, so the plan includes a short validation loop before rollout.")
        return " ".join(body)

    def _paragraph(self, rng: random.Random, heading: str, title: str, topic: str) -> str:
        action = self._pick(self._ACTIONS, rng).lower()
        owner = self._pick(self._OWNERS, rng)
        return (
            f"{heading} for {title} is centered on {topic}. "
            f"The working team will {action} and hand review notes to {owner} before the next checkpoint."
        )

    def _bullet_list(self, rng: random.Random) -> str:
        items = rng.sample(self._ACTIONS, k=3)
        return "".join(f"<li>{html.escape(item)}</li>" for item in items)

    def _status_table(self, rng: random.Random) -> str:
        rows = []
        for _ in range(3):
            rows.append(
                "<tr>"
                f"<td>{html.escape(self._pick(self._TEAMS, rng))}</td>"
                f"<td>{html.escape(self._pick(self._STATUSES, rng))}</td>"
                f"<td>{html.escape(self._pick(self._OWNERS, rng))}</td>"
                "</tr>"
            )
        return "<table><tbody><tr><th>Area</th><th>Status</th><th>Owner</th></tr>" + "".join(rows) + "</tbody></table>"

    def generate_storage_value(
        self,
        content_type: str,
        title: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        metadata = metadata or {}
        rng = self._rng("storage", content_type, title, metadata)
        topic = metadata.get("topic") or self._pick(self._TOPICS, rng)

        if content_type in {"footer_comment", "inline_comment", "comment"}:
            sentence = self.generate_text(8, 16, kind=content_type, title=title, metadata=metadata)
            return f"<p>{html.escape(sentence)}</p>"

        headings = self._HEADINGS.get(content_type, self._HEADINGS["page"])
        parts = []
        for heading in headings[:2]:
            parts.append(f"<h2>{html.escape(heading)}</h2>")
            parts.append(f"<p>{html.escape(self._paragraph(rng, heading, title, topic))}</p>")
        parts.append("<h2>Key Actions</h2>")
        parts.append(f"<ul>{self._bullet_list(rng)}</ul>")
        parts.append("<h2>Status Snapshot</h2>")
        parts.append(self._status_table(rng))
        return "".join(parts)


class GeminiContentProvider(ContentProvider):
    _TEXT_INSTRUCTIONS = {
        "space_description": "Describe the purpose of a Confluence space in one short internal-summary paragraph.",
        "page_property": "Write a concise metadata-style description for a page property value.",
        "blogpost_property": "Write a concise metadata-style description for a blog post property value.",
        "attachment_json": "Write a short JSON-safe string value suitable for a synthetic attachment payload.",
        "attachment_csv": "Write a short CSV-safe value without commas or quotes.",
        "attachment_text": "Write one short line that could plausibly appear in an internal text attachment.",
        "footer_comment": "Write a brief footer comment that sounds like actionable reviewer feedback.",
        "inline_comment": "Write a brief inline comment that references a specific wording or detail needing revision.",
        "comment": "Write a short comment update that reads like a new version of prior feedback.",
    }
    _STORAGE_INSTRUCTIONS = {
        "page": {
            "sections": "Use sections like Overview, Current State, Decisions, Next Steps.",
            "tone": "Make it read like an engineering wiki page for an internal initiative.",
        },
        "blogpost": {
            "sections": "Use sections like Summary, Highlights, Impact, Follow-up.",
            "tone": "Make it read like a team update post for internal stakeholders.",
        },
        "template": {
            "sections": "Use sections like Purpose, How To Use, Required Fields, Review Notes.",
            "tone": "Make it read like a reusable template intended for other teams to copy.",
        },
        "footer_comment": {
            "sections": "Return a single short paragraph only.",
            "tone": "Make it sound like concise reviewer feedback left after reading the document.",
        },
        "inline_comment": {
            "sections": "Return a single short paragraph only.",
            "tone": "Make it sound like targeted feedback on a specific sentence or claim.",
        },
        "comment": {
            "sections": "Return a single short paragraph only.",
            "tone": "Make it sound like a revision note on an existing comment thread.",
        },
    }

    def __init__(
        self,
        seed: int = 42,
        *,
        api_key: str | None = None,
        model: str = "gemini-2.5-flash",
        max_retries: int = 3,
    ):
        super().__init__(seed)
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.model = model
        self.max_retries = max_retries
        self._client: Any | None = None
        self._types: Any | None = None
        self._fallback = StructuredContentProvider(seed=seed)
        self.last_generation_used_fallback = False
        self.last_fallback_reason = ""
        self.logger = logging.getLogger(__name__)

    @property
    def name(self) -> str:
        return "gemini"

    def _load_sdk(self) -> tuple[Any, Any]:
        try:
            from google import genai
            from google.genai import types
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Gemini content provider requires the 'google-genai' package. Install requirements.txt or pip install google-genai."
            ) from exc
        return genai, types

    def _get_client(self) -> tuple[Any, Any]:
        if self._client is not None and self._types is not None:
            return self._client, self._types
        if not self.api_key:
            raise RuntimeError("Gemini content provider requires GEMINI_API_KEY or GOOGLE_API_KEY.")
        genai, types = self._load_sdk()
        self._client = genai.Client(api_key=self.api_key)
        self._types = types
        return self._client, self._types

    def _content_seed(self, kind: str, title: str, metadata: dict[str, Any] | None) -> int:
        payload = ":".join([str(self.seed), kind, title, str(metadata or {})])
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) % (2**31 - 1)

    def _generate(self, prompt: str, *, kind: str, title: str, metadata: dict[str, Any] | None, max_tokens: int) -> str:
        client, types = self._get_client()
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                top_p=0.9,
                candidate_count=1,
                max_output_tokens=max_tokens,
                seed=self._content_seed(kind, title, metadata),
            ),
        )
        text = (getattr(response, "text", "") or "").strip()
        if not text:
            raise RuntimeError("Gemini content provider returned empty content.")
        return text

    def _validate_text_response(self, text: str, *, min_words: int) -> None:
        stripped = text.strip()
        words = [word for word in stripped.replace("\n", " ").split() if word]
        if len(words) < min_words:
            raise RuntimeError(f"Gemini content too short: expected at least {min_words} words, got {len(words)}")
        if stripped.endswith(("<", "</", "<p", "<h2", "<ac:")):
            raise RuntimeError("Gemini content appears truncated at the end of the response")

    def _validate_storage_response(self, text: str, *, content_type: str) -> None:
        stripped = text.strip()
        if "<ac:" in stripped:
            raise RuntimeError("Gemini content used forbidden ac:* tags")
        if content_type in {"footer_comment", "inline_comment", "comment"}:
            if not (stripped.startswith("<p>") and stripped.endswith("</p>")):
                raise RuntimeError("Gemini comment response must be a complete <p>...</p> block")
            if stripped.count("<p>") != stripped.count("</p>"):
                raise RuntimeError("Gemini comment response has unbalanced paragraph tags")
            return

        required_pairs = [("<h2>", "</h2>"), ("<p>", "</p>"), ("<ul>", "</ul>"), ("<table>", "</table>")]
        for open_tag, close_tag in required_pairs:
            if open_tag not in stripped or close_tag not in stripped:
                raise RuntimeError(f"Gemini storage response missing required tag pair {open_tag}...{close_tag}")
        if stripped.count("<h2>") < 2 or stripped.count("<p>") < 2:
            raise RuntimeError("Gemini storage response is incomplete; expected multiple sections and paragraphs")
        if stripped.count("<li>") < 1 or stripped.count("<tr>") < 2:
            raise RuntimeError("Gemini storage response is incomplete; expected list and table rows")
        if len(stripped) < 220:
            raise RuntimeError("Gemini storage response is too short to be a complete document snippet")

    def _generate_validated(
        self,
        prompt: str,
        *,
        kind: str,
        title: str,
        metadata: dict[str, Any] | None,
        max_tokens: int,
        validator,
    ) -> str:
        last_error: RuntimeError | None = None
        for attempt in range(1, self.max_retries + 1):
            text = self._generate(prompt, kind=kind, title=title, metadata=metadata, max_tokens=max_tokens)
            try:
                validator(text)
                return text
            except RuntimeError as exc:
                last_error = exc
                if attempt == self.max_retries:
                    break
                self.logger.warning(
                    "Gemini content validation failed for %s on attempt %s/%s: %s",
                    kind,
                    attempt,
                    self.max_retries,
                    exc,
                )
        raise RuntimeError(f"Gemini content failed validation after {self.max_retries} attempts: {last_error}")

    def _build_text_prompt(
        self,
        *,
        kind: str,
        title: str,
        metadata: dict[str, Any] | None,
        word_target: int,
    ) -> str:
        instruction = self._TEXT_INSTRUCTIONS.get(
            kind,
            "Write one concise Confluence-ready sentence or short paragraph for internal engineering documentation.",
        )
        context = f"Context type: {kind}. Title: {title or 'Untitled'}."
        metadata_clause = f" Metadata: {metadata}." if metadata else ""
        return (
            f"{instruction} Aim for about {word_target} words. {context}{metadata_clause} "
            "Keep it specific, realistic, and plain text only. Do not use markdown bullets, numbering, or code fences."
        )

    def _build_storage_prompt(
        self,
        *,
        content_type: str,
        title: str,
        metadata: dict[str, Any] | None,
    ) -> str:
        profile = self._STORAGE_INSTRUCTIONS.get(content_type, self._STORAGE_INSTRUCTIONS["page"])
        metadata_clause = f" Metadata: {metadata}." if metadata else ""
        base = (
            "Generate valid Confluence storage-style XHTML using only these tags: "
            "<h2>, <p>, <ul>, <li>, <table>, <tbody>, <tr>, <th>, <td>. "
            f"Document type: {content_type}. Title: {title}.{metadata_clause} "
            f"{profile['sections']} {profile['tone']} "
        )
        if content_type in {"footer_comment", "inline_comment", "comment"}:
            return base + "Return only one paragraph wrapped in <p> tags, with no markdown fences or explanation."
        return (
            base + "Include 2-3 sections, one bullet list, and one small table. "
            "Return only XHTML with no markdown fences or explanation."
        )

    def _with_fallback(self, fallback_fn, *, action: str) -> str:
        self.last_generation_used_fallback = False
        self.last_fallback_reason = ""
        try:
            return fallback_fn()
        except Exception as exc:
            self.last_generation_used_fallback = True
            self.last_fallback_reason = f"{type(exc).__name__}: {exc}"
            self.logger.warning(
                "Gemini content generation failed for %s; falling back to structured provider: %s", action, exc
            )
            return ""

    def generate_text(
        self,
        min_words: int = 5,
        max_words: int = 20,
        *,
        kind: str = "generic",
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        word_target = max(min_words, min(max_words, max(8, (min_words + max_words) // 2)))
        prompt = self._build_text_prompt(kind=kind, title=title, metadata=metadata, word_target=word_target)

        generated = self._with_fallback(
            lambda: self._generate_validated(
                prompt,
                kind=kind,
                title=title,
                metadata=metadata,
                max_tokens=max(96, word_target * 6),
                validator=lambda text: self._validate_text_response(text, min_words=max(4, min_words)),
            ),
            action=f"text:{kind}",
        )
        if generated:
            return generated
        return self._fallback.generate_text(min_words, max_words, kind=kind, title=title, metadata=metadata)

    def generate_storage_value(
        self,
        content_type: str,
        title: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        prompt = self._build_storage_prompt(content_type=content_type, title=title, metadata=metadata)

        text = self._with_fallback(
            lambda: self._generate_validated(
                prompt,
                kind=content_type,
                title=title,
                metadata=metadata,
                max_tokens=900,
                validator=lambda value: self._validate_storage_response(value, content_type=content_type),
            ),
            action=f"storage:{content_type}",
        )
        if not text:
            return self._fallback.generate_storage_value(content_type, title, metadata=metadata)
        if "<" not in text:
            return f"<p>{html.escape(text)}</p>"
        return text


class LocalLlmContentProvider(GeminiContentProvider):
    def __init__(
        self,
        seed: int = 42,
        *,
        model: str = "qwen2.5:14b-instruct",
        base_url: str = "http://127.0.0.1:11434",
        max_retries: int = 3,
    ):
        super().__init__(seed=seed, api_key="local", model=model, max_retries=max_retries)
        self.base_url = base_url.rstrip("/")

    @property
    def name(self) -> str:
        return "local-llm"

    def _with_fallback(self, fallback_fn, *, action: str) -> str:
        self.last_generation_used_fallback = False
        self.last_fallback_reason = ""
        return fallback_fn()

    def _generate(self, prompt: str, *, kind: str, title: str, metadata: dict[str, Any] | None, max_tokens: int) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "top_p": 0.9,
                "seed": self._content_seed(kind, title, metadata),
                "num_predict": max_tokens,
            },
        }
        try:
            response = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=120)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Local LLM request failed: {exc}") from exc

        data = response.json()
        text = str(data.get("response", "")).strip()
        if not text:
            raise RuntimeError("Local LLM provider returned empty content.")
        return text


def create_content_provider(
    name: str,
    seed: int = 42,
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> ContentProvider:
    normalized = name.lower().strip()
    if normalized == "lorem":
        return LoremContentProvider(seed=seed)
    if normalized == "structured":
        return StructuredContentProvider(seed=seed)
    if normalized == "gemini":
        return GeminiContentProvider(seed=seed, api_key=api_key, model=model or "gemini-2.5-flash")
    if normalized == "local-llm":
        return LocalLlmContentProvider(
            seed=seed,
            model=model or "qwen2.5:14b-instruct",
            base_url=base_url or "http://127.0.0.1:11434",
        )
    raise ValueError(f"Unsupported content provider: {name}")
