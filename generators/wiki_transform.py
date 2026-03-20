from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import quote, urlencode

import requests


@dataclass(slots=True)
class DocumentSection:
    heading: str
    paragraphs: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SourceDocument:
    title: str
    source_name: str
    source_url: str
    summary: str = ""
    sections: list[DocumentSection] = field(default_factory=list)


class WikipediaSourceAdapter:
    def __init__(self, language: str = "en", timeout: int = 30):
        self.language = language
        self.timeout = timeout
        self.headers = {
            "User-Agent": "confluence-test-data-generator/1.0 (wiki preview)",
            "Accept": "application/json",
        }

    def fetch_document(self, title: str) -> SourceDocument:
        safe_title = title.replace(" ", "_")
        summary_payload = self._get_json(
            f"https://{self.language}.wikipedia.org/api/rest_v1/page/summary/{quote(safe_title)}"
        )
        parse_payload = self._get_json(self._build_parse_url(safe_title))

        summary = _normalize_text(str(summary_payload.get("extract", "")))
        document_title = str(summary_payload.get("title", title))
        source_url = str(summary_payload.get("content_urls", {}).get("desktop", {}).get("page", ""))
        sections = self._extract_sections(parse_payload)

        if not summary and not sections:
            raise RuntimeError(f"Wikipedia document was empty for title: {title}")
        if not sections and summary:
            sections = [DocumentSection(heading="Overview", paragraphs=[summary])]

        return SourceDocument(
            title=document_title,
            source_name="wikipedia",
            source_url=source_url,
            summary=summary,
            sections=sections,
        )

    def _build_parse_url(self, safe_title: str) -> str:
        params = urlencode(
            {
                "action": "parse",
                "page": safe_title,
                "prop": "text|sections",
                "format": "json",
                "formatversion": 2,
            }
        )
        return f"https://{self.language}.wikipedia.org/w/api.php?{params}"

    def _get_json(self, url: str) -> dict:
        response = requests.get(url, timeout=self.timeout, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def _extract_sections(self, payload: dict) -> list[DocumentSection]:
        sections: list[DocumentSection] = []
        parse = payload.get("parse", {})
        section_meta = parse.get("sections", [])
        parser = _WikipediaParseHtmlParser()
        parser.feed(str(parse.get("text", "")))
        parser.close()

        for index, item in enumerate(section_meta):
            heading = _normalize_text(str(item.get("line", "")))
            if not heading:
                continue
            parsed = parser.sections[index] if index < len(parser.sections) else {"paragraphs": [], "bullets": []}
            section = DocumentSection(
                heading=heading,
                paragraphs=parsed.get("paragraphs", [])[:3],
                bullets=parsed.get("bullets", [])[:5],
            )
            if section.paragraphs or section.bullets:
                sections.append(section)
        return sections[:6]


class NamuWikiSourceAdapter:
    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    def fetch_document(self, title: str) -> SourceDocument:
        url = f"https://namu.wiki/w/{quote(title)}"
        response = requests.get(url, timeout=self.timeout, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        parser = _NamuWikiHtmlParser()
        parser.feed(response.text)
        parser.close()

        document_title = (parser.title or title).replace(" - 나무위키", "").strip()
        sections: list[DocumentSection] = []
        for section in parser.sections:
            raw_heading = section.get("heading", "Overview")
            raw_paragraphs = section.get("paragraphs", [])
            raw_bullets = section.get("bullets", [])
            heading = _normalize_text(str(raw_heading or "Overview"))
            paragraph_values = raw_paragraphs if isinstance(raw_paragraphs, list) else []
            bullet_values = raw_bullets if isinstance(raw_bullets, list) else []
            paragraphs = [str(value) for value in paragraph_values if not _is_namuwiki_boilerplate(str(value))]
            bullets = [str(value) for value in bullet_values if not _is_namuwiki_boilerplate(str(value))]
            if paragraphs or bullets:
                sections.append(DocumentSection(heading=heading, paragraphs=paragraphs[:3], bullets=bullets[:6]))

        summary = ""
        if parser.description and not _is_namuwiki_boilerplate(parser.description):
            summary = _normalize_text(parser.description)
            if not sections:
                sections.append(DocumentSection(heading="Overview", paragraphs=[summary]))

        if not sections:
            raise RuntimeError(f"NamuWiki document was empty for title: {title}")

        sections = _polish_namuwiki_sections(sections)
        if not summary:
            summary = sections[0].paragraphs[0] if sections[0].paragraphs else ""
        return SourceDocument(
            title=document_title,
            source_name="namuwiki",
            source_url=url,
            summary=summary,
            sections=sections[:6],
        )


class ConfluenceStorageRenderer:
    def render(self, document: SourceDocument) -> str:
        parts = [f"<h1>{html.escape(document.title)}</h1>"]
        if document.summary:
            parts.append(f"<p>{html.escape(document.summary)}</p>")

        for section in document.sections:
            parts.append(f"<h2>{html.escape(section.heading)}</h2>")
            for paragraph in section.paragraphs:
                parts.append(f"<p>{html.escape(paragraph)}</p>")
            if section.bullets:
                parts.append("<ul>")
                parts.extend(f"<li>{html.escape(item)}</li>" for item in section.bullets)
                parts.append("</ul>")

        if document.source_url:
            parts.append(f"<p>Source: {html.escape(document.source_url)}</p>")
        return "".join(parts)


def fetch_source_document(provider: str, title: str, language: str = "en") -> SourceDocument:
    normalized = provider.lower().strip()
    if normalized == "wikipedia":
        return WikipediaSourceAdapter(language=language).fetch_document(title)
    if normalized == "namuwiki":
        return NamuWikiSourceAdapter().fetch_document(title)
    raise ValueError(f"Unsupported source provider: {provider}")


def _normalize_text(value: str) -> str:
    text = re.sub(r"\[[^\]]+\]", " ", value)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _is_namuwiki_boilerplate(value: str) -> bool:
    normalized = _normalize_text(value)
    boilerplate_markers = [
        "CC BY-NC-SA",
        "나무위키는 백과사전이 아니며",
        "여러분이 직접 문서를 고칠 수 있으며",
        "이 저작물은",
        "기여하신 문서의 저작권",
        "문서 조회수 확인중",
        "최근 수정 시각",
        "reCAPTCHA",
        "hCaptcha",
        "Privacy Policy",
        "Terms of Service",
    ]
    return any(marker in normalized for marker in boilerplate_markers)


def _polish_namuwiki_sections(sections: list[DocumentSection]) -> list[DocumentSection]:
    polished: list[DocumentSection] = []
    for index, section in enumerate(sections):
        paragraphs = list(section.paragraphs)
        bullets = list(section.bullets)

        if index == 0 and section.heading == "Overview" and len(sections) > 1:
            if not bullets or bullets == ["백업/복원"]:
                continue

        if not paragraphs and bullets:
            paragraphs.append(bullets.pop(0))

        if len(bullets) > 3:
            bullets = bullets[:3]

        polished.append(
            DocumentSection(
                heading=section.heading,
                paragraphs=paragraphs[:3],
                bullets=bullets,
            )
        )

    return polished[:6]


def _parse_html_section(heading: str, html_text: str) -> DocumentSection:
    parser = _SimpleHtmlDocumentParser()
    parser.feed(html_text)
    paragraphs = [_normalize_text(value) for value in parser.paragraphs if _normalize_text(value)]
    bullets = [_normalize_text(value) for value in parser.bullets if _normalize_text(value)]
    return DocumentSection(heading=heading, paragraphs=paragraphs[:3], bullets=bullets[:5])


class _SimpleHtmlDocumentParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.description = ""
        self.paragraphs: list[str] = []
        self.bullets: list[str] = []
        self._text_parts: list[str] = []
        self._active_tag = ""

    def handle_starttag(self, tag: str, attrs):
        if tag == "meta":
            attrs_dict = dict(attrs)
            if attrs_dict.get("property") == "og:description":
                self.description = attrs_dict.get("content", "")
        if tag in {"title", "p", "li"}:
            self._active_tag = tag
            self._text_parts = []

    def handle_data(self, data: str):
        if self._active_tag:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str):
        if tag != self._active_tag:
            return
        text = _normalize_text("".join(self._text_parts))
        if not text:
            self._active_tag = ""
            self._text_parts = []
            return
        if tag == "title":
            self.title = text
        elif tag == "p":
            self.paragraphs.append(text)
        elif tag == "li":
            self.bullets.append(text)
        self._active_tag = ""
        self._text_parts = []


class _WikipediaParseHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sections: list[dict[str, list[str]]] = []
        self._current: dict[str, list[str]] | None = None
        self._text_parts: list[str] = []
        self._active_tag = ""
        self._in_headline = False

    def handle_starttag(self, tag: str, attrs):
        attrs_dict = dict(attrs)
        if tag == "h2":
            self._flush_section()
            self._current = {"paragraphs": [], "bullets": []}
        elif tag == "span" and attrs_dict.get("class") == "mw-headline":
            self._in_headline = True
        elif tag in {"p", "li"}:
            self._active_tag = tag
            self._text_parts = []

    def handle_data(self, data: str):
        if self._in_headline:
            return
        if self._active_tag:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str):
        if tag == "span" and self._in_headline:
            self._in_headline = False
            return
        if tag == "h2":
            return
        if tag != self._active_tag or self._current is None:
            return
        text = _normalize_text("".join(self._text_parts))
        if text:
            bucket = "paragraphs" if tag == "p" else "bullets"
            self._current[bucket].append(text)
        self._active_tag = ""
        self._text_parts = []

    def close(self):
        super().close()
        self._flush_section()

    def _flush_section(self):
        if self._current and (self._current["paragraphs"] or self._current["bullets"]):
            self.sections.append(self._current)
        self._current = None


class _NamuWikiHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.description = ""
        self.sections: list[dict[str, str | list[str]]] = []
        self._current: dict[str, str | list[str]] | None = None
        self._text_parts: list[str] = []
        self._active_tag = ""
        self._in_edit_link = False

    def handle_starttag(self, tag: str, attrs):
        attrs_dict = dict(attrs)
        if tag == "meta" and attrs_dict.get("property") == "og:description":
            self.description = attrs_dict.get("content", "")
            return
        if tag == "h2":
            self._flush_section()
            self._current = {"heading": "", "paragraphs": [], "bullets": []}
            self._active_tag = "h2"
            self._text_parts = []
            return
        if tag == "a" and self._active_tag == "h2":
            self._in_edit_link = True
            return
        if tag in {"title", "p", "li"}:
            if self._current is None:
                self._current = {"heading": "Overview", "paragraphs": [], "bullets": []}
            self._active_tag = tag
            self._text_parts = []

    def handle_data(self, data: str):
        if self._in_edit_link:
            return
        if self._active_tag:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str):
        if tag == "a" and self._in_edit_link:
            self._in_edit_link = False
            return
        if tag != self._active_tag:
            return

        text = _normalize_text("".join(self._text_parts))
        if text:
            if tag == "title":
                self.title = text
            elif tag == "h2" and self._current is not None:
                self._current["heading"] = text
            elif tag == "p" and self._current is not None:
                paragraphs = self._current["paragraphs"]
                if isinstance(paragraphs, list):
                    paragraphs.append(text)
            elif tag == "li" and self._current is not None:
                bullets = self._current["bullets"]
                if isinstance(bullets, list):
                    bullets.append(text)

        self._active_tag = ""
        self._text_parts = []

    def close(self):
        super().close()
        self._flush_section()

    def _flush_section(self):
        if self._current and (self._current["paragraphs"] or self._current["bullets"]):
            if not self._current["heading"]:
                self._current["heading"] = "Overview"
            self.sections.append(self._current)
        self._current = None
