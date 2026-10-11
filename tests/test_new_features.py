"""
Tests for New Features:
- OpenRouter free model gateway & fallback
- Video service (YouTube & Instagram validation, upload safety)
- Verification service (trusted domains & accessibility)
- AI App Installation plan generator & adapters
- Local Companion Service (security checks & execution)
- New API routes (/api/models/free, /api/install/plan, /api/install/approve)
"""

import pytest
from unittest.mock import patch, MagicMock
from app import create_app
from database.db import init_db
from services.llm_provider import fetch_free_models, call_llm, LLMError, DEFAULT_FREE_MODELS
from services.video_service import (
    is_safe_url, identify_source_type, extract_youtube_video_id,
    process_url, validate_uploaded_video, VideoIngestionError
)
from services.verification_service import is_trusted_domain, verify_tool
from services.configuration_service import generate_install_plan, ConfigError
from services.companion_service import (
    check_companion_health, validate_safe_identifier,
    execute_approved_action, CompanionSecurityError
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    test_db = tmp_path / "test_features.db"
    monkeypatch.setenv("DATABASE_PATH", str(test_db))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": str(test_db),
        "DATA_DIR": str(tmp_path / "data"),
    })
    init_db(test_db)
    with app.test_client() as client:
        yield client



# ── 1. OpenRouter Provider Tests ──────────────────────────────

class TestOpenRouterGateway:
    def test_default_free_models_exist(self):
        assert len(DEFAULT_FREE_MODELS) >= 3
        assert DEFAULT_FREE_MODELS[0] == "openrouter/free"
        for m in DEFAULT_FREE_MODELS:
            assert m == "openrouter/free" or m.endswith(":free")


    @patch("requests.get")
    def test_fetch_free_models_filtering(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {
                    "id": "meta-llama/llama-3.3-70b-instruct:free",
                    "name": "Llama 3.3 70B (Free)",
                    "pricing": {"prompt": "0", "completion": "0"},
                },
                {
                    "id": "openai/gpt-4o",
                    "name": "GPT-4o",
                    "pricing": {"prompt": "0.000005", "completion": "0.000015"},
                },
            ]
        }
        mock_get.return_value = mock_resp

        models = fetch_free_models("fake-key")
        assert len(models) == 2
        assert models[0]["id"] == "openrouter/free"
        assert models[1]["id"] == "meta-llama/llama-3.3-70b-instruct:free"


    @patch("requests.post")
    def test_fallback_between_free_models_on_rate_limit(self, mock_post):
        # 1st call: 429 rate limit; 2nd call: 200 success
        mock_429 = MagicMock()
        mock_429.status_code = 429

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {
            "choices": [{"message": {"content": "Fallback free model output"}}]
        }

        mock_post.side_effect = [mock_429, mock_200]

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            output = call_llm("sys", "user")
            assert output == "Fallback free model output"
            assert mock_post.call_count == 2

    @patch("requests.post")
    def test_fallback_between_free_models_on_non_json_output(self, mock_post):
        # 1st model outputs only safety check text "User Safety: safe"
        mock_safety = MagicMock()
        mock_safety.status_code = 200
        mock_safety.json.return_value = {
            "choices": [{"message": {"content": "User Safety: safe"}}]
        }

        # 2nd model successfully outputs valid JSON
        mock_valid_json = MagicMock()
        mock_valid_json.status_code = 200
        mock_valid_json.json.return_value = {
            "choices": [{"message": {"content": '{"summary": "ok", "tools": []}'}}]
        }

        mock_post.side_effect = [mock_safety, mock_valid_json]

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            output = call_llm("sys", "user", require_json=True)
            assert '{"summary": "ok"' in output
            assert mock_post.call_count == 2



# ── 2. Video Service Tests ────────────────────────────────────

class TestVideoService:
    def test_is_safe_url(self):
        assert is_safe_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert not is_safe_url("http://127.0.0.1:8080")
        assert not is_safe_url("http://localhost/secret")
        assert not is_safe_url("http://192.168.1.1/admin")
        assert not is_safe_url("ftp://example.com")

    def test_identify_source_type(self):
        assert identify_source_type("https://www.youtube.com/watch?v=abc") == "youtube"
        assert identify_source_type("https://youtu.be/abc") == "youtube"
        assert identify_source_type("https://www.instagram.com/reel/xyz/") == "instagram"
        assert identify_source_type("https://vimeo.com/123") == "unsupported"

    def test_extract_youtube_video_id(self):
        assert extract_youtube_video_id("https://www.youtube.com/watch?v=abc12345") == "abc12345"
        assert extract_youtube_video_id("https://youtu.be/shortId") == "shortId"
        assert extract_youtube_video_id("https://www.youtube.com/shorts/shortsId") == "shortsId"

    @patch("services.video_service.fetch_instagram_content")
    def test_instagram_reel_direct_extraction(self, mock_fetch):
        mock_fetch.return_value = {
            "source_type": "instagram",
            "title": "Awesome AI Tool Reel",
            "transcript": "Title: Awesome AI Tool Reel\n\nCaption: Check out this amazing MCP tool uv and ripgrep!",
            "segments": [],
        }
        res = process_url("https://www.instagram.com/reel/C8XYZ123/")
        assert res["source_type"] == "instagram"
        assert "ripgrep" in res["transcript"]
        assert res["title"] == "Awesome AI Tool Reel"


    def test_validate_uploaded_video(self):
        # Valid extension & size
        validate_uploaded_video("demo.mp4", 1024 * 1024, max_size_mb=500)
        # Invalid extension
        with pytest.raises(VideoIngestionError):
            validate_uploaded_video("script.sh", 1024)
        # Exceeds max size
        with pytest.raises(VideoIngestionError):
            validate_uploaded_video("huge.mp4", 600 * 1024 * 1024, max_size_mb=500)


# ── 3. Verification Service Tests ─────────────────────────────

class TestVerificationService:
    def test_trusted_domains(self):
        assert is_trusted_domain("https://github.com/astral-sh/uv")
        assert is_trusted_domain("https://docs.anthropic.com/en/docs/claude-code")
        assert not is_trusted_domain("https://random-scam-site.org")

    def test_verify_tool_without_urls(self):
        tool = {"name": "TestTool"}
        res = verify_tool(tool)
        assert res["verified"] == 0
        assert res["confidence"] == "unverified"


# ── 4. AI App Installation Plan Tests ─────────────────────────

class TestInstallationPlanning:
    def test_vscode_mcp_plan(self):
        tool = {
            "name": "SQLite MCP",
            "category": "mcp-server",
            "purpose": "Database inspection for coding agents",
            "requirements": ["Node.js >= 18"],
        }
        plan = generate_install_plan(tool, "vscode")
        assert plan["target_app"] == "vscode"
        assert plan["integration_type"] == "mcp-server"
        assert "mcp" in plan["config_changes"]["snippet"].lower()
        assert plan["companion_payload"]["action"] == "add_vscode_mcp"
        assert "copyable_prompt" in plan

    def test_claude_code_mcp_plan(self):
        tool = {
            "name": "Postgres MCP",
            "category": "mcp-server",
            "purpose": "Database server",
        }
        plan = generate_install_plan(tool, "claude-code")
        assert plan["target_app"] == "claude-code"
        assert plan["integration_type"] == "mcp-server"
        assert any("claude mcp add" in c for c in plan["commands"])
        assert plan["companion_payload"]["action"] == "add_claude_mcp"

    def test_unsupported_target(self):
        with pytest.raises(ConfigError):
            generate_install_plan({"name": "tool"}, "cursor-ide")


# ── 5. Companion Security & Execution Tests ───────────────────

class TestCompanionService:
    def test_validate_safe_identifier(self):
        validate_safe_identifier("my-server", "server_name")
        validate_safe_identifier("@modelcontextprotocol/server-sqlite", "package")
        with pytest.raises(CompanionSecurityError):
            validate_safe_identifier("server; rm -rf /", "server_name")
        with pytest.raises(CompanionSecurityError):
            validate_safe_identifier("server && whoami", "server_name")

    def test_requires_user_approval(self):
        payload = {"action": "install_vscode_extension", "extension_id": "ms-python.python"}
        res = execute_approved_action(payload, user_approved=False)
        assert res["status"] == "Awaiting approval"

    def test_companion_health(self):
        health = check_companion_health()
        assert health["status"] == "online"
        assert "has_python" in health


# ── 6. New API Routes Tests ───────────────────────────────────

class TestNewApiRoutes:
    def test_models_free_endpoint(self, client):
        resp = client.get("/api/models/free")
        assert resp.status_code == 200
        data = resp.json
        assert "models" in data
        assert len(data["models"]) > 0

    def test_companion_status_endpoint(self, client):
        resp = client.get("/api/companion/status")
        assert resp.status_code == 200
        assert resp.json["status"] == "online"

    def test_install_plan_endpoint(self, client):
        payload = {
            "tool": {
                "name": "Super Linter",
                "category": "dev-tool",
                "purpose": "Automated code formatting"
            },
            "target": "vscode"
        }
        resp = client.post("/api/install/plan", json=payload)
        assert resp.status_code == 200
        data = resp.json
        assert "job_id" in data
        assert data["tool_name"] == "Super Linter"
        assert "copyable_prompt" in data

    def test_install_approve_without_flag_fails(self, client):
        resp = client.post("/api/install/approve", json={"approved": False})
        assert resp.status_code == 400

    def test_security_headers_present(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "SAMEORIGIN"
        assert resp.headers.get("X-XSS-Protection") == "1; mode=block"
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_media_path_traversal_blocked(self, client):
        resp = client.get("/api/media/../../etc/passwd")
        assert resp.status_code in (400, 404)

    def test_async_url_analysis_returns_202(self, client):
        resp = client.post("/api/analyze/url?async=1", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
        assert resp.status_code == 202
        data = resp.json
        assert "video_id" in data
        assert data["status"] == "pending"

    def test_user_session_isolation(self, client):
        # Client 1 saves a tool
        client.post("/api/library/save", json={"name": "User1PrivateTool", "purpose": "Private Tool"})
        resp1 = client.get("/api/library")
        tool_names = [t["name"] for t in resp1.json["tools"]]
        assert "User1PrivateTool" in tool_names
