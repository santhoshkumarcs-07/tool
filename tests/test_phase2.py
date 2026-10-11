"""
Phase 2 Tests — LLM proof of concept

Tests cover:
- Text analysis endpoint with mocked LLM
- Extraction service with mocked LLM
- Pydantic validation of tool records
- Error handling for LLM failures
- Analysis retrieval
- Library CRUD via API
- Configuration generation
"""

import os
import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from database.db import (
    init_db, create_video, create_discovered_tool, save_tool,
    get_saved_tools, get_tools_for_video,
)
from services.extraction_service import ExtractedTool, extract_tools_from_text
from services.llm_provider import extract_json_from_response, LLMError
from services.configuration_service import generate_config, ConfigError


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _temp_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    init_db()
    yield


@pytest.fixture
def app():
    return create_app(test_config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


# ── Sample LLM Response ──────────────────────────────────────

SAMPLE_LLM_RESPONSE = json.dumps([
    {
        "name": "Cursor",
        "category": "ai-tool",
        "purpose": "AI-powered code editor with built-in AI assistance",
        "capabilities": ["code completion", "chat", "inline editing"],
        "evidence_excerpt": "I've been using Cursor for the past month and it's amazing",
        "video_timestamp": "2:30",
        "mention_type": "explicit",
        "official_website": "https://cursor.sh",
        "documentation_url": "https://docs.cursor.sh",
        "repository_url": None,
        "requirements": ["Node.js 18+"],
        "setup_steps": ["Download from cursor.sh", "Install the application", "Sign in"],
        "target_applications": ["VS Code"],
        "uncertainties": None
    },
    {
        "name": "v0",
        "category": "ai-tool",
        "purpose": "AI-powered UI generation tool by Vercel",
        "capabilities": ["UI generation", "React component creation"],
        "evidence_excerpt": "and then I used v0 to generate the frontend",
        "video_timestamp": "5:15",
        "mention_type": "explicit",
        "official_website": "https://v0.dev",
        "documentation_url": None,
        "repository_url": None,
        "requirements": [],
        "setup_steps": ["Visit v0.dev", "Sign in with Vercel account"],
        "target_applications": [],
        "uncertainties": "Pricing model may have changed"
    }
])

SAMPLE_TRANSCRIPT = """
Hey everyone, in this video I want to show you some incredible AI tools
that I've been using lately. First up is Cursor - I've been using Cursor
for the past month and it's amazing. It's basically VS Code but with
AI built right in. It has code completion, chat, and inline editing.
You can download it from cursor.sh.

Next, I want to talk about v0 by Vercel. I used v0 to generate the
frontend for my latest project. You just describe what you want and
it generates React components for you. Just visit v0.dev to try it out.
"""


# ── Extraction Service Tests ─────────────────────────────────

class TestExtractionService:
    @patch("services.extraction_service.call_llm")
    def test_extract_tools_success(self, mock_call):
        mock_call.return_value = SAMPLE_LLM_RESPONSE
        tools = extract_tools_from_text(SAMPLE_TRANSCRIPT)
        assert len(tools) == 2
        assert tools[0]["name"] == "Cursor"
        assert tools[0]["category"] == "ai-tool"
        assert tools[0]["mention_type"] == "explicit"
        assert tools[1]["name"] == "v0"

    @patch("services.extraction_service.call_llm")
    def test_extract_tools_empty_result(self, mock_call):
        mock_call.return_value = "[]"
        tools = extract_tools_from_text(SAMPLE_TRANSCRIPT)
        assert tools == []

    @patch("services.extraction_service.call_llm")
    def test_extract_tools_with_markdown_fences(self, mock_call):
        mock_call.return_value = f"```json\n{SAMPLE_LLM_RESPONSE}\n```"
        tools = extract_tools_from_text(SAMPLE_TRANSCRIPT)
        assert len(tools) == 2

    @patch("services.extraction_service.call_llm")
    def test_extract_tools_invalid_json(self, mock_call):
        mock_call.return_value = "This is not JSON at all"
        with pytest.raises(LLMError, match="Failed to parse JSON"):
            extract_tools_from_text(SAMPLE_TRANSCRIPT)

    @patch("services.extraction_service.call_llm")
    def test_extract_tools_partial_valid(self, mock_call):
        """One valid tool and one invalid — should salvage what's possible."""
        mock_call.return_value = json.dumps([
            {"name": "ValidTool", "category": "dev-tool"},
            {"not_a_name": "missing name field"},  # no name at all
        ])
        tools = extract_tools_from_text(SAMPLE_TRANSCRIPT)
        assert len(tools) >= 1
        assert tools[0]["name"] == "ValidTool"

    def test_extract_tools_empty_transcript(self):
        with pytest.raises(ValueError, match="empty"):
            extract_tools_from_text("")


# ── Pydantic Model Tests ─────────────────────────────────────

class TestExtractedToolModel:
    def test_valid_tool(self):
        tool = ExtractedTool(
            name="TestTool",
            category="dev-tool",
            purpose="Testing",
            mention_type="explicit",
        )
        assert tool.name == "TestTool"
        assert tool.category == "dev-tool"

    def test_category_normalization(self):
        tool = ExtractedTool(name="T", category="AI Tool")
        assert tool.category == "ai-tool"

    def test_unknown_category_becomes_other(self):
        tool = ExtractedTool(name="T", category="random-thing")
        assert tool.category == "other"

    def test_mention_type_validation(self):
        tool = ExtractedTool(name="T", mention_type="banana")
        assert tool.mention_type == "inferred"

    def test_name_required(self):
        with pytest.raises(Exception):
            ExtractedTool(name="", category="dev-tool")


# ── JSON Extraction Tests ────────────────────────────────────

class TestJsonExtraction:
    def test_plain_json(self):
        result = extract_json_from_response('[{"name": "test"}]')
        assert result == [{"name": "test"}]

    def test_markdown_wrapped(self):
        result = extract_json_from_response('```json\n[{"a": 1}]\n```')
        assert result == [{"a": 1}]

    def test_json_with_surrounding_text(self):
        result = extract_json_from_response('Here are the results:\n[{"name": "x"}]\n\nDone!')
        assert result == [{"name": "x"}]

    def test_json_with_user_safety_prefix(self):
        result = extract_json_from_response('User Safety: safe\n\n```json\n[{"name": "ToolA"}]\n```')
        assert result == [{"name": "ToolA"}]

    def test_json_with_user_safety_prefix_raw(self):
        result = extract_json_from_response('User Safety: safe\n\n{"name": "ToolB"}')
        assert result == {"name": "ToolB"}

    def test_json_with_think_tags(self):
        result = extract_json_from_response('<think>Thinking about video tools...</think>\n```json\n[{"name": "ToolC"}]\n```')
        assert result == [{"name": "ToolC"}]

    def test_invalid_json_raises(self):
        with pytest.raises(LLMError):
            extract_json_from_response("not json")

    def test_only_safety_prefix_raises(self):
        with pytest.raises(LLMError, match="Failed to parse JSON"):
            extract_json_from_response("User Safety: safe")


# ── Text Analysis API Tests ──────────────────────────────────

class TestAnalyzeTextAPI:
    @patch("services.extraction_service.call_llm")
    def test_analyze_text_success(self, mock_call, client):
        mock_call.return_value = SAMPLE_LLM_RESPONSE
        resp = client.post("/api/analyze/text", json={
            "transcript": SAMPLE_TRANSCRIPT,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["tools_count"] == 2
        assert data["video_id"] is not None
        assert len(data["tools"]) == 2
        assert data["tools"][0]["name"] == "Cursor"

    def test_analyze_text_empty(self, client):
        resp = client.post("/api/analyze/text", json={"transcript": ""})
        assert resp.status_code == 400

    def test_analyze_text_too_short(self, client):
        resp = client.post("/api/analyze/text", json={"transcript": "short"})
        assert resp.status_code == 400

    def test_analyze_text_no_body(self, client):
        resp = client.post("/api/analyze/text",
                          content_type="application/json",
                          data="{}")
        assert resp.status_code == 400

    @patch("services.extraction_service.call_llm")
    def test_analyze_text_llm_error(self, mock_call, client):
        mock_call.side_effect = LLMError("API key not configured")
        resp = client.post("/api/analyze/text", json={
            "transcript": SAMPLE_TRANSCRIPT,
        })
        assert resp.status_code == 502
        assert "API key" in resp.get_json()["error"]


# ── Analysis Retrieval Tests ─────────────────────────────────

class TestAnalysisRetrieval:
    def test_get_analysis_not_found(self, client):
        resp = client.get("/api/analysis/999")
        assert resp.status_code == 404

    @patch("services.extraction_service.call_llm")
    def test_get_analysis_after_creation(self, mock_call, client):
        mock_call.return_value = SAMPLE_LLM_RESPONSE
        # Create analysis
        resp = client.post("/api/analyze/text", json={
            "transcript": SAMPLE_TRANSCRIPT,
        })
        vid = resp.get_json()["video_id"]
        # Retrieve it
        resp2 = client.get(f"/api/analysis/{vid}")
        assert resp2.status_code == 200
        data = resp2.get_json()
        assert data["tools_count"] == 2
        assert data["status"] == "completed"


# ── Library API Tests ─────────────────────────────────────────

class TestLibraryAPI:
    @patch("services.extraction_service.call_llm")
    def test_save_discovered_tool(self, mock_call, client):
        mock_call.return_value = SAMPLE_LLM_RESPONSE
        # Analyze
        resp = client.post("/api/analyze/text", json={"transcript": SAMPLE_TRANSCRIPT})
        tools = resp.get_json()["tools"]
        # Save first tool
        resp2 = client.post("/api/library/save", json={
            "discovered_tool_id": tools[0]["id"],
        })
        assert resp2.status_code == 200
        assert resp2.get_json()["id"] is not None

    def test_save_manual_tool(self, client):
        resp = client.post("/api/library/save", json={
            "name": "Manual Tool",
            "category": "dev-tool",
            "purpose": "Manually added",
        })
        assert resp.status_code == 200

    def test_list_library(self, client):
        # Add a tool
        client.post("/api/library/save", json={"name": "TestTool"})
        resp = client.get("/api/library")
        assert resp.status_code == 200
        assert len(resp.get_json()["tools"]) == 1

    def test_search_library(self, client):
        client.post("/api/library/save", json={"name": "Alpha", "purpose": "First"})
        client.post("/api/library/save", json={"name": "Beta", "purpose": "Second"})
        resp = client.get("/api/library?search=alpha")
        assert len(resp.get_json()["tools"]) == 1

    def test_delete_from_library(self, client):
        resp = client.post("/api/library/save", json={"name": "Deletable"})
        tool_id = resp.get_json()["id"]
        resp2 = client.delete(f"/api/library/{tool_id}")
        assert resp2.status_code == 200
        # Verify gone
        resp3 = client.get("/api/library")
        assert len(resp3.get_json()["tools"]) == 0

    def test_update_library_notes(self, client):
        resp = client.post("/api/library/save", json={"name": "NoteTest"})
        tool_id = resp.get_json()["id"]
        resp2 = client.put(f"/api/library/{tool_id}",
                          json={"personal_notes": "Great tool!"})
        assert resp2.status_code == 200


# ── Configuration API Tests ──────────────────────────────────

class TestConfigurationAPI:
    def test_generate_vscode_config(self, client):
        resp = client.post("/api/library/save", json={
            "name": "test-mcp-server",
            "category": "mcp-server",
            "purpose": "A test MCP server",
        })
        tool_id = resp.get_json()["id"]
        resp2 = client.post("/api/configurations/generate", json={
            "tool_id": tool_id,
            "target": "vscode",
        })
        assert resp2.status_code == 200
        data = resp2.get_json()
        assert data["target_label"] == "VS Code"
        assert data["config_content"] is not None
        assert "mcp" in data["config_content"]

    def test_generate_claude_code_config(self, client):
        resp = client.post("/api/library/save", json={
            "name": "test-tool",
            "category": "mcp-server",
        })
        tool_id = resp.get_json()["id"]
        resp2 = client.post("/api/configurations/generate", json={
            "tool_id": tool_id,
            "target": "claude-code",
        })
        assert resp2.status_code == 200
        data = resp2.get_json()
        assert data["target_label"] == "Claude Code"

    def test_unsupported_target(self, client):
        resp = client.post("/api/library/save", json={"name": "T"})
        tool_id = resp.get_json()["id"]
        resp2 = client.post("/api/configurations/generate", json={
            "tool_id": tool_id,
            "target": "unknown-editor",
        })
        assert resp2.status_code == 400

    def test_generate_config_missing_tool(self, client):
        resp = client.post("/api/configurations/generate", json={
            "tool_id": 999,
            "target": "vscode",
        })
        assert resp.status_code == 404


# ── Configuration Service Unit Tests ─────────────────────────

class TestConfigurationService:
    def test_vscode_mcp_config(self):
        tool = {"name": "My Server", "category": "mcp-server", "purpose": "Test"}
        result = generate_config(tool, "vscode")
        assert result["target_label"] == "VS Code"
        assert "mcp" in result["config_content"]
        assert len(result["warnings"]) > 0

    def test_claude_code_mcp_config(self):
        tool = {"name": "My Server", "category": "mcp-server"}
        result = generate_config(tool, "claude-code")
        assert "mcpServers" in result["config_content"]

    def test_vscode_extension_config(self):
        tool = {"name": "Copilot", "category": "ai-tool", "purpose": "AI pair programmer"}
        result = generate_config(tool, "vscode")
        assert "Extensions" in result["instructions"] or "extension" in result["config_content"].lower()

    def test_unsupported_target_raises(self):
        with pytest.raises(ConfigError):
            generate_config({"name": "X"}, "notepad")
