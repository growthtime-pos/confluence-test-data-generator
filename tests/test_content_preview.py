import json
import sys
import types
from pathlib import Path

from confluence_data_generator import (
    build_content_preview_manifest,
    build_single_content_preview,
    calculate_counts,
    main,
)
from generators.content import (
    GeminiContentProvider,
    LocalLlmContentProvider,
    LoremContentProvider,
    StructuredContentProvider,
    create_content_provider,
)


def install_fake_gemini_sdk(monkeypatch, response_text):
    captured: dict[str, object] = {}
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    responses = list(response_text) if isinstance(response_text, list) else [response_text]

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            captured["model"] = model
            captured["contents"] = contents
            captured["config"] = config
            captured["call_count"] = int(captured.get("call_count", 0)) + 1
            current = responses.pop(0) if len(responses) > 1 else responses[0]
            return types.SimpleNamespace(text=current)

    class FakeClient:
        def __init__(self, *, api_key):
            captured["api_key"] = api_key
            self.models = FakeModels()

    fake_types = types.SimpleNamespace(GenerateContentConfig=lambda **kwargs: types.SimpleNamespace(**kwargs))
    fake_genai = types.SimpleNamespace(Client=FakeClient, types=fake_types)
    fake_google = types.ModuleType("google")
    fake_google.genai = fake_genai

    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    return captured


def install_fake_local_llm(monkeypatch, response_text):
    responses = list(response_text) if isinstance(response_text, list) else [response_text]
    captured: dict[str, object] = {}

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return {"response": self.payload}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        captured["call_count"] = int(captured.get("call_count", 0)) + 1
        current = responses.pop(0) if len(responses) > 1 else responses[0]
        if callable(current):
            current = current(json["prompt"])
        return FakeResponse(current)

    monkeypatch.setattr("generators.content.requests.post", fake_post)
    return captured


class TestContentProviders:
    def test_structured_provider_is_deterministic(self):
        provider_a = StructuredContentProvider(seed=123)
        provider_b = StructuredContentProvider(seed=123)

        body_a = provider_a.generate_storage_value("page", "TESTDATA Page 1", metadata={"space_id": "10001"})
        body_b = provider_b.generate_storage_value("page", "TESTDATA Page 1", metadata={"space_id": "10001"})

        assert body_a == body_b
        assert "<h2>" in body_a
        assert "<table>" in body_a

    def test_lorem_provider_factory(self):
        provider = create_content_provider("lorem", seed=7)

        assert isinstance(provider, LoremContentProvider)
        assert provider.name == "lorem"

    def test_gemini_provider_factory(self):
        provider = create_content_provider("gemini", seed=7, api_key="test-key", model="gemini-test")

        assert isinstance(provider, GeminiContentProvider)
        assert provider.name == "gemini"
        assert provider.model == "gemini-test"

    def test_local_llm_provider_factory(self):
        provider = create_content_provider("local-llm", seed=7, model="qwen-test", base_url="http://localhost:11434")

        assert isinstance(provider, LocalLlmContentProvider)
        assert provider.name == "local-llm"
        assert provider.model == "qwen-test"
        assert provider.base_url == "http://localhost:11434"

    def test_local_llm_provider_generates_storage_value(self, monkeypatch):
        captured = install_fake_local_llm(
            monkeypatch,
            "<h2>Overview</h2><p>Generated locally with realistic structure and enough detail for validation.</p><h2>Current State</h2><p>The document is ready for publishing and team review.</p><ul><li>Confirm backups</li></ul><table><tbody><tr><th>Area</th><th>Status</th></tr><tr><td>Docs</td><td>Ready</td></tr></tbody></table>",
        )
        provider = LocalLlmContentProvider(seed=13, model="qwen-test", base_url="http://localhost:11434")

        body = provider.generate_storage_value("page", "TESTDATA Page 1", metadata={"space_id": "10001"})

        assert "<h2>Overview</h2>" in body
        assert captured["url"] == "http://localhost:11434/api/generate"
        assert captured["json"]["model"] == "qwen-test"

    def test_gemini_provider_falls_back_without_api_key(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        provider = GeminiContentProvider(seed=7)

        text = provider.generate_text(kind="page", title="Missing key")

        assert provider.last_generation_used_fallback is True
        assert "GEMINI_API_KEY" in provider.last_fallback_reason
        assert text

    def test_gemini_provider_generates_storage_value(self, monkeypatch):
        captured = install_fake_gemini_sdk(
            monkeypatch,
            "<h2>Overview</h2><p>Generated from Gemini.</p><h2>Status</h2><ul><li>Ready</li></ul><table><tbody><tr><th>Area</th><th>Status</th></tr><tr><td>Docs</td><td>Ready</td></tr></tbody></table>",
        )
        provider = GeminiContentProvider(seed=13, api_key="test-key", model="gemini-test")

        body = provider.generate_storage_value("page", "TESTDATA Page 1", metadata={"space_id": "10001"})

        assert "<h2>Overview</h2>" in body
        assert captured["api_key"] == "test-key"
        assert captured["model"] == "gemini-test"
        assert "Confluence storage-style XHTML" in captured["contents"]

    def test_gemini_provider_specializes_page_prompt(self, monkeypatch):
        captured = install_fake_gemini_sdk(monkeypatch, "<h2>Overview</h2><p>Generated from Gemini.</p>")
        provider = GeminiContentProvider(seed=13, api_key="test-key", model="gemini-test")

        provider.generate_storage_value("page", "Migration Readiness", metadata={"space_id": "10001"})

        assert "Overview, Current State, Decisions, Next Steps" in captured["contents"]
        assert "engineering wiki page" in captured["contents"]

    def test_gemini_provider_specializes_template_prompt(self, monkeypatch):
        captured = install_fake_gemini_sdk(monkeypatch, "<h2>Purpose</h2><p>Generated from Gemini.</p>")
        provider = GeminiContentProvider(seed=13, api_key="test-key", model="gemini-test")

        provider.generate_storage_value("template", "Runbook Template", metadata={"space_key": "OPS"})

        assert "Purpose, How To Use, Required Fields, Review Notes" in captured["contents"]
        assert "reusable template" in captured["contents"]

    def test_gemini_provider_specializes_inline_comment_prompt(self, monkeypatch):
        captured = install_fake_gemini_sdk(monkeypatch, "<p>Generated from Gemini.</p>")
        provider = GeminiContentProvider(seed=13, api_key="test-key", model="gemini-test")

        provider.generate_storage_value("inline_comment", "Inline Comment 1", metadata={"page_id": "123"})

        assert "targeted feedback on a specific sentence or claim" in captured["contents"]
        assert "one paragraph wrapped in <p> tags" in captured["contents"]

    def test_gemini_provider_specializes_attachment_text_prompt(self, monkeypatch):
        captured = install_fake_gemini_sdk(monkeypatch, "Attachment summary line")
        provider = GeminiContentProvider(seed=13, api_key="test-key", model="gemini-test")

        provider.generate_text(5, 15, kind="attachment_text", title="testdata_file.txt")

        assert "internal text attachment" in captured["contents"]
        assert "plain text only" in captured["contents"]

    def test_gemini_provider_falls_back_to_structured(self, monkeypatch):
        class FailingModels:
            def generate_content(self, **kwargs):
                raise RuntimeError("upstream failure")

        class FailingClient:
            def __init__(self, *, api_key):
                self.models = FailingModels()

        fake_types = types.SimpleNamespace(GenerateContentConfig=lambda **kwargs: types.SimpleNamespace(**kwargs))
        fake_genai = types.SimpleNamespace(Client=FailingClient, types=fake_types)
        fake_google = types.ModuleType("google")
        fake_google.genai = fake_genai
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setitem(sys.modules, "google", fake_google)
        monkeypatch.setitem(sys.modules, "google.genai", fake_genai)

        provider = GeminiContentProvider(seed=13, model="gemini-test")

        body = provider.generate_storage_value("page", "TESTDATA Page 1", metadata={"space_id": "10001"})

        assert provider.last_generation_used_fallback is True
        assert "RuntimeError" in provider.last_fallback_reason
        assert "<h2>" in body

    def test_gemini_provider_retries_truncated_storage_response(self, monkeypatch):
        captured = install_fake_gemini_sdk(
            monkeypatch,
            [
                "<h2>Overview</h2><p>This document outlines",
                "<h2>Overview</h2><p>Generated from Gemini.</p><h2>Current State</h2><p>Service readiness is being reviewed.</p><ul><li>Confirm backups</li></ul><table><tbody><tr><th>Area</th><th>Status</th></tr><tr><td>Restore</td><td>Ready</td></tr></tbody></table>",
            ],
        )
        provider = GeminiContentProvider(seed=13, api_key="test-key", model="gemini-test")

        body = provider.generate_storage_value("page", "Restore Readiness Review", metadata={"space_id": "10001"})

        assert captured["call_count"] == 2
        assert provider.last_generation_used_fallback is False
        assert "<table>" in body

    def test_gemini_provider_falls_back_after_invalid_storage_retries(self, monkeypatch):
        install_fake_gemini_sdk(
            monkeypatch,
            [
                "<ac:page><p>bad</p>",
                "<h2>Overview</h2><p>still too short",
                "<h2>Overview</h2><p>still too short",
            ],
        )
        provider = GeminiContentProvider(seed=13, api_key="test-key", model="gemini-test")

        body = provider.generate_storage_value("page", "Restore Readiness Review", metadata={"space_id": "10001"})

        assert provider.last_generation_used_fallback is True
        assert "failed validation" in provider.last_fallback_reason
        assert "<table>" in body


class TestPreviewManifest:
    @staticmethod
    def _local_llm_response(prompt: str) -> str:
        if "Return only one paragraph wrapped in <p> tags" in prompt:
            return "<p>This review comment identifies a specific issue that should be fixed before publication.</p>"
        if "plain text only" in prompt:
            return "This attachment line contains enough useful words"
        return (
            "<h2>Overview</h2><p>Generated locally with realistic structure and enough detail for validation.</p>"
            "<h2>Current State</h2><p>The document is ready for publishing and team review.</p>"
            "<ul><li>Confirm backups</li></ul>"
            "<table><tbody><tr><th>Area</th><th>Status</th></tr><tr><td>Docs</td><td>Ready</td></tr></tbody></table>"
        )

    def test_build_single_content_preview_page(self):
        manifest = build_single_content_preview(
            preview_type="page",
            prefix="TESTDATA",
            content_provider_name="structured",
            content_seed=99,
            gemini_model="gemini-2.5-flash",
            local_llm_model="qwen-test",
            local_llm_url="http://127.0.0.1:11434",
        )

        assert manifest["mode"] == "preview-one"
        assert manifest["previewType"] == "page"
        assert manifest["sample"]["title"]
        assert manifest["sample"]["quality"]["hasHeadings"] is True

    def test_build_single_content_preview_attachment(self):
        manifest = build_single_content_preview(
            preview_type="attachment",
            prefix="TESTDATA",
            content_provider_name="structured",
            content_seed=99,
            gemini_model="gemini-2.5-flash",
            local_llm_model="qwen-test",
            local_llm_url="http://127.0.0.1:11434",
        )

        assert manifest["mode"] == "preview-one"
        assert manifest["previewType"] == "attachment"
        assert manifest["sample"]["preview"]
        assert manifest["sample"]["quality"]["characters"] > 0

    def test_build_content_preview_manifest(self):
        counts = calculate_counts(100, "small", content_only=False)

        manifest = build_content_preview_manifest(
            prefix="TESTDATA",
            size_bucket="small",
            content_count=100,
            counts=counts,
            content_only=False,
            content_provider_name="structured",
            content_seed=99,
            gemini_model="gemini-2.5-flash",
            local_llm_model="qwen-test",
            local_llm_url="http://127.0.0.1:11434",
        )

        assert manifest["mode"] == "preview-content"
        assert manifest["contentProvider"] == "structured"
        assert manifest["samples"]["pages"]
        assert "<h2>" in manifest["samples"]["pages"][0]["body"]
        assert manifest["samples"]["attachment"] is not None
        assert manifest["samples"]["pages"][0]["quality"]["hasHeadings"] is True
        assert manifest["samples"]["attachment"]["quality"]["characters"] > 0

    def test_build_gemini_preview_manifest(self, monkeypatch):
        counts = calculate_counts(25, "small", content_only=True)
        install_fake_gemini_sdk(monkeypatch, "<h2>Overview</h2><p>Gemini preview body.</p>")

        manifest = build_content_preview_manifest(
            prefix="TESTDATA",
            size_bucket="small",
            content_count=25,
            counts=counts,
            content_only=True,
            content_provider_name="gemini",
            content_seed=42,
            gemini_model="gemini-test",
            local_llm_model="qwen-test",
            local_llm_url="http://127.0.0.1:11434",
        )

        assert manifest["contentProvider"] == "gemini"
        assert manifest["contentModel"] == "gemini-test"
        assert "<h2>Overview</h2>" in manifest["samples"]["pages"][0]["body"]
        assert manifest["samples"]["pages"][0]["quality"]["hasHeadings"] is True
        assert isinstance(manifest["contentFallback"]["used"], bool)

    def test_build_gemini_preview_manifest_records_fallback(self, monkeypatch):
        class FailingModels:
            def generate_content(self, **kwargs):
                raise RuntimeError("preview failure")

        class FailingClient:
            def __init__(self, *, api_key):
                self.models = FailingModels()

        fake_types = types.SimpleNamespace(GenerateContentConfig=lambda **kwargs: types.SimpleNamespace(**kwargs))
        fake_genai = types.SimpleNamespace(Client=FailingClient, types=fake_types)
        fake_google = types.ModuleType("google")
        fake_google.genai = fake_genai
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setitem(sys.modules, "google", fake_google)
        monkeypatch.setitem(sys.modules, "google.genai", fake_genai)

        counts = calculate_counts(25, "small", content_only=True)
        manifest = build_content_preview_manifest(
            prefix="TESTDATA",
            size_bucket="small",
            content_count=25,
            counts=counts,
            content_only=True,
            content_provider_name="gemini",
            content_seed=42,
            gemini_model="gemini-test",
            local_llm_model="qwen-test",
            local_llm_url="http://127.0.0.1:11434",
        )

        assert manifest["contentFallback"]["used"] is True
        assert "preview failure" in manifest["contentFallback"]["reason"]
        assert manifest["samples"]["pages"][0]["quality"]["hasHeadings"] is True

    def test_main_preview_writes_manifest(self, monkeypatch, tmp_path, capsys):
        output_path = tmp_path / "preview.json"
        monkeypatch.setattr(
            "sys.argv",
            [
                "confluence_data_generator.py",
                "--count",
                "25",
                "--preview-content",
                "--preview-output",
                str(output_path),
                "--content-provider",
                "local-llm",
                "--content-seed",
                "11",
                "--local-llm-model",
                "qwen-test",
            ],
        )
        install_fake_local_llm(
            monkeypatch,
            self._local_llm_response,
        )

        main()

        captured = capsys.readouterr()
        assert "Preview manifest written to" in captured.out

        data = json.loads(Path(output_path).read_text(encoding="utf-8"))
        assert data["mode"] == "preview-content"
        assert data["contentSeed"] == 11
        assert data["samples"]["spaces"]

    def test_main_preview_one_writes_manifest(self, monkeypatch, tmp_path, capsys):
        output_path = tmp_path / "single-preview.json"
        monkeypatch.setattr(
            "sys.argv",
            [
                "confluence_data_generator.py",
                "--count",
                "25",
                "--preview-one",
                "page",
                "--preview-output",
                str(output_path),
                "--content-provider",
                "local-llm",
            ],
        )
        install_fake_local_llm(
            monkeypatch,
            self._local_llm_response,
        )

        main()

        captured = capsys.readouterr()
        assert "Preview manifest written to" in captured.out

        data = json.loads(Path(output_path).read_text(encoding="utf-8"))
        assert data["mode"] == "preview-one"
        assert data["previewType"] == "page"
        assert data["sample"]["quality"]["hasHeadings"] is True
