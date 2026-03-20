import json
from pathlib import Path

from confluence_data_generator import build_wiki_source_preview, main
from generators.wiki_transform import (
    ConfluenceStorageRenderer,
    DocumentSection,
    NamuWikiSourceAdapter,
    SourceDocument,
    WikipediaSourceAdapter,
    _normalize_text,
)


class FakeResponse:
    def __init__(self, payload, text: str = ""):
        self.payload = payload
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class TestWikiTransform:
    def test_normalize_text_collapses_whitespace(self):
        assert _normalize_text("Alpha\n\n  Beta\tGamma [1]") == "Alpha Beta Gamma"

    def test_confluence_storage_renderer_renders_sections(self):
        document = SourceDocument(
            title="Restore Readiness",
            source_name="wikipedia",
            source_url="https://en.wikipedia.org/wiki/Disaster_recovery",
            summary="Short summary.",
            sections=[
                DocumentSection(
                    heading="Overview",
                    paragraphs=["First paragraph.", "Second paragraph."],
                    bullets=["Audit backups", "Verify failover"],
                )
            ],
        )

        rendered = ConfluenceStorageRenderer().render(document)

        assert "<h1>Restore Readiness</h1>" in rendered
        assert "<h2>Overview</h2>" in rendered
        assert "<ul>" in rendered
        assert "Source:" in rendered

    def test_wikipedia_adapter_extracts_sections(self, monkeypatch):
        summary_payload = {
            "title": "Disaster recovery",
            "extract": "Disaster recovery is the process of regaining access.",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Disaster_recovery"}},
        }
        sections_payload = {
            "parse": {
                "sections": [
                    {"line": "History"},
                    {"line": "Practice"},
                ],
                "text": (
                    "<h2><span class='mw-headline'>History</span></h2>"
                    "<p>Recovery planning started in mainframes.</p>"
                    "<ul><li>Early backups</li></ul>"
                    "<h2><span class='mw-headline'>Practice</span></h2>"
                    "<p>Modern teams automate drills.</p>"
                    "<p>They also test restores.</p>"
                ),
            }
        }
        calls = []

        def fake_get(url, timeout, headers=None):
            calls.append(url)
            if "summary" in url:
                return FakeResponse(summary_payload)
            return FakeResponse(sections_payload)

        monkeypatch.setattr("generators.wiki_transform.requests.get", fake_get)

        document = WikipediaSourceAdapter().fetch_document("Disaster recovery")

        assert len(calls) == 2
        assert document.title == "Disaster recovery"
        assert document.sections[0].heading == "History"
        assert document.sections[0].bullets == ["Early backups"]
        assert document.sections[1].paragraphs[0] == "Modern teams automate drills."

    def test_namuwiki_adapter_extracts_basic_content(self, monkeypatch):
        html = """
        <html><head><title>백업 - 나무위키</title></head>
        <body>
        <meta property="og:description" content="백업은 데이터 보호를 위한 기본 절차다.">
        <h2><a id='s-1' href='#toc'>1.</a> <span>개요<span><a href='/edit'>[편집]</a></span></span></h2>
        <p>정기적인 복구 훈련이 필요하다.</p>
        <ul><li>오프사이트 보관</li><li>복구 검증</li></ul>
        <h2><a id='s-2' href='#toc'>2.</a> <span>관련 개념<span><a href='/edit'>[편집]</a></span></span></h2>
        <p>복구 계획은 백업과 함께 관리된다.</p>
        </body></html>
        """

        def fake_get(url, timeout, headers=None):
            return FakeResponse({}, text=html)

        monkeypatch.setattr("generators.wiki_transform.requests.get", fake_get)

        document = NamuWikiSourceAdapter().fetch_document("백업")

        assert document.source_name == "namuwiki"
        assert document.sections[0].heading == "개요"
        assert document.summary == "백업은 데이터 보호를 위한 기본 절차다."
        assert document.sections[0].paragraphs[0] == "정기적인 복구 훈련이 필요하다."
        assert document.sections[0].bullets[0] == "오프사이트 보관"
        assert document.sections[1].heading == "관련 개념"

    def test_build_wiki_source_preview(self, monkeypatch):
        summary_payload = {
            "title": "Disaster recovery",
            "extract": "Disaster recovery is the process of regaining access.",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Disaster_recovery"}},
        }
        sections_payload = {
            "parse": {
                "sections": [{"line": "History"}],
                "text": (
                    "<h2><span class='mw-headline'>History</span></h2>"
                    "<p>Recovery planning started in mainframes.</p>"
                    "<ul><li>Early backups</li></ul>"
                ),
            }
        }

        def fake_get(url, timeout, headers=None):
            if "summary" in url:
                return FakeResponse(summary_payload)
            return FakeResponse(sections_payload)

        monkeypatch.setattr("generators.wiki_transform.requests.get", fake_get)

        manifest = build_wiki_source_preview("wikipedia", "Disaster recovery", "en")

        assert manifest["mode"] == "preview-source"
        assert manifest["sample"]["sourceProvider"] == "wikipedia"
        assert manifest["sample"]["quality"]["hasHeadings"] is True

    def test_main_source_preview_writes_manifest(self, monkeypatch, tmp_path, capsys):
        output_path = tmp_path / "source-preview.json"
        summary_payload = {
            "title": "Disaster recovery",
            "extract": "Disaster recovery is the process of regaining access.",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Disaster_recovery"}},
        }
        sections_payload = {
            "parse": {
                "sections": [{"line": "History"}],
                "text": (
                    "<h2><span class='mw-headline'>History</span></h2>"
                    "<p>Recovery planning started in mainframes.</p>"
                    "<ul><li>Early backups</li></ul>"
                ),
            }
        }

        def fake_get(url, timeout, headers=None):
            if "summary" in url:
                return FakeResponse(summary_payload)
            return FakeResponse(sections_payload)

        monkeypatch.setattr("generators.wiki_transform.requests.get", fake_get)
        monkeypatch.setattr(
            "sys.argv",
            [
                "confluence_data_generator.py",
                "--count",
                "1",
                "--source-provider",
                "wikipedia",
                "--source-title",
                "Disaster recovery",
                "--preview-output",
                str(output_path),
            ],
        )

        main()

        captured = capsys.readouterr()
        assert "Preview manifest written to" in captured.out

        data = json.loads(Path(output_path).read_text(encoding="utf-8"))
        assert data["mode"] == "preview-source"
        assert data["sample"]["sectionCount"] == 1
