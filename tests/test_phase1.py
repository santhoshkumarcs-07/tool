"""
Phase 1 Tests — Foundation

Tests cover:
- Health check endpoint
- Dashboard API
- Config status API
- Static file serving
- Database initialization and basic CRUD
"""

import os
import sys
import json
import tempfile
from pathlib import Path

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from database.db import (
    init_db, get_connection, get_db_path,
    create_video, get_video, get_recent_videos,
    update_video_status, get_dashboard_stats,
    create_discovered_tool, get_tools_for_video,
    save_tool, get_saved_tools, delete_saved_tool,
)


@pytest.fixture(autouse=True)
def _temp_data_dir(tmp_path, monkeypatch):
    """Use a temporary directory for data and database in every test."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    init_db()
    yield


@pytest.fixture
def app():
    """Create the Flask app for testing."""
    application = create_app(test_config={"TESTING": True})
    return application


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


# ── Health Check ──────────────────────────────────────────────

class TestHealthCheck:
    def test_health_returns_ok(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_health_returns_json(self, client):
        resp = client.get("/api/health")
        assert resp.content_type.startswith("application/json")


# ── Static File Serving ──────────────────────────────────────

class TestStaticFiles:
    def test_index_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Tool Discovery" in resp.data

    def test_css(self, client):
        resp = client.get("/style.css")
        assert resp.status_code == 200
        assert b"--bg-deepest" in resp.data

    def test_js(self, client):
        resp = client.get("/script.js")
        assert resp.status_code == 200
        assert b"DOMContentLoaded" in resp.data


# ── Dashboard API ─────────────────────────────────────────────

class TestDashboardAPI:
    def test_dashboard_returns_stats(self, client):
        resp = client.get("/api/dashboard")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "stats" in data
        assert "recent_analyses" in data
        assert data["stats"]["total_analyses"] == 0

    def test_dashboard_with_data(self, client):
        # Insert a video directly
        vid = create_video("text", title="Test Analysis")
        update_video_status(vid, "completed")
        resp = client.get("/api/dashboard")
        data = resp.get_json()
        assert data["stats"]["total_analyses"] == 1
        assert data["stats"]["completed_analyses"] == 1
        assert len(data["recent_analyses"]) == 1


# ── Config Status API ─────────────────────────────────────────

class TestConfigStatus:
    def test_config_status_default(self, client):
        resp = client.get("/api/config/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "llm_provider" in data
        assert "llm_configured" in data
        assert isinstance(data["max_upload_mb"], int)

    def test_config_hides_api_key(self, client):
        resp = client.get("/api/config/status")
        data = resp.get_json()
        text = json.dumps(data)
        assert "api_key" not in text.lower() or "your-api-key" not in text


# ── Database CRUD ─────────────────────────────────────────────

class TestDatabase:
    def test_create_and_get_video(self):
        vid = create_video("youtube", source_url="https://youtube.com/watch?v=test")
        assert vid > 0
        video = get_video(vid)
        assert video is not None
        assert video["source_type"] == "youtube"
        assert video["status"] == "pending"

    def test_create_video_with_stored_filename(self):
        vid = create_video(
            "upload",
            original_filename="demo.mp4",
            stored_filename="uuid_demo.mp4",
            title="demo.mp4",
        )
        assert vid > 0
        video = get_video(vid)
        assert video is not None
        assert video["original_filename"] == "demo.mp4"
        assert video["stored_filename"] == "uuid_demo.mp4"
        assert video["title"] == "demo.mp4"

    def test_update_video_status(self):
        vid = create_video("upload")
        update_video_status(vid, "completed")
        video = get_video(vid)
        assert video["status"] == "completed"

    def test_update_video_status_with_error(self):
        vid = create_video("upload")
        update_video_status(vid, "failed", "Something went wrong")
        video = get_video(vid)
        assert video["status"] == "failed"
        assert video["error_message"] == "Something went wrong"

    def test_recent_videos(self):
        for i in range(5):
            create_video("text", title=f"Analysis {i}")
        recent = get_recent_videos(limit=3)
        assert len(recent) == 3

    def test_create_discovered_tool(self):
        vid = create_video("text")
        tool_id = create_discovered_tool(vid, {
            "name": "Cursor",
            "category": "ai-tool",
            "purpose": "AI-powered code editor",
            "capabilities": ["code completion", "chat"],
            "evidence_excerpt": "Then I switched to Cursor...",
            "mention_type": "explicit",
        })
        assert tool_id > 0
        tools = get_tools_for_video(vid)
        assert len(tools) == 1
        assert tools[0]["name"] == "Cursor"
        assert isinstance(tools[0]["capabilities"], list)

    def test_save_and_list_tools(self):
        vid = create_video("text")
        dt_id = create_discovered_tool(vid, {
            "name": "Copilot",
            "category": "ai-tool",
            "purpose": "AI pair programmer",
        })
        st_id = save_tool(discovered_tool_id=dt_id, tool_data={
            "name": "Copilot",
            "category": "ai-tool",
            "purpose": "AI pair programmer",
            "personal_notes": "Works great with VS Code",
        })
        assert st_id > 0
        saved = get_saved_tools()
        assert len(saved) == 1
        assert saved[0]["personal_notes"] == "Works great with VS Code"

    def test_delete_saved_tool(self):
        st_id = save_tool(tool_data={"name": "Test Tool", "category": "dev-tool"})
        assert delete_saved_tool(st_id) is True
        saved = get_saved_tools()
        assert len(saved) == 0

    def test_search_saved_tools(self):
        save_tool(tool_data={"name": "Alpha", "purpose": "Testing alpha"})
        save_tool(tool_data={"name": "Beta", "purpose": "Testing beta"})
        results = get_saved_tools(search="alpha")
        assert len(results) == 1
        assert results[0]["name"] == "Alpha"

    def test_dashboard_stats(self):
        vid = create_video("text")
        update_video_status(vid, "completed")
        create_discovered_tool(vid, {"name": "Tool A"})
        save_tool(tool_data={"name": "Tool A"})
        stats = get_dashboard_stats()
        assert stats["total_analyses"] == 1
        assert stats["completed_analyses"] == 1
        assert stats["total_discovered_tools"] == 1
        assert stats["total_saved_tools"] == 1


# ── Error Handling ────────────────────────────────────────────

class TestErrorHandling:
    def test_404(self, client):
        resp = client.get("/api/nonexistent")
        assert resp.status_code == 404
        data = resp.get_json()
        assert "error" in data
