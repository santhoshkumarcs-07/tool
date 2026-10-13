"""
Reliability and Failure Recovery Tests.

Tests cover:
- Crash and restart recovery for orphaned jobs
- SQLite online backup and restore verification
- Deep health check endpoint (healthy and degraded states)
- Atomic job claiming and state machine transitions
- SSRF and private IP blocking
- Storage limit validation
- Transient vs. permanent error classification
"""

import os
import sys
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from database.db import (
    init_db, get_connection, get_db_path,
    create_video, get_video, update_video_status,
    claim_next_job, recover_orphaned_jobs,
    backup_database, check_db_health,
)
from services.job_worker import is_transient_error, JobWorker
from services.video_service import is_safe_url, validate_uploaded_video, VideoIngestionError


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
    """Create Flask application in TESTING mode."""
    return create_app(test_config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


# ── 1. Crash and Restart Recovery Tests ────────────────────────

class TestCrashAndRestartRecovery:
    def test_orphaned_jobs_recovered_on_restart(self):
        """Simulate a server crash while jobs were in active execution states."""
        # Create 3 jobs in active states
        v1 = create_video("youtube", source_url="https://youtube.com/watch?v=1", status="downloading")
        v2 = create_video("upload", original_filename="screen.mp4", status="transcribing")
        v3 = create_video("text", title="Text analysis", status="analyzing")

        # Run recovery routine (simulates server boot)
        recovered = recover_orphaned_jobs()
        assert len(recovered) == 3
        assert v1 in recovered
        assert v2 in recovered
        assert v3 in recovered

        # Verify all jobs were reset to 'queued' with incremented retry count
        for vid in (v1, v2, v3):
            video = get_video(vid)
            assert video["status"] == "queued"
            assert video["retry_count"] == 1
            assert video["error_type"] == "transient"
            assert "Recovered after server restart" in video["error_message"]

    def test_orphaned_jobs_fail_when_max_retries_exceeded(self):
        """Jobs that crash repeatedly and exceed max_retries are marked permanently failed."""
        v = create_video("youtube", source_url="https://youtube.com/watch?v=crash", status="transcribing", max_retries=2)

        # First crash and recovery
        recover_orphaned_jobs()
        assert get_video(v)["status"] == "queued"
        assert get_video(v)["retry_count"] == 1

        # Simulate job claimed again, crashes again
        update_video_status(v, "analyzing")
        recover_orphaned_jobs()
        assert get_video(v)["status"] == "queued"
        assert get_video(v)["retry_count"] == 2

        # Simulate job claimed again, crashes a third time (exceeds max_retries=2)
        update_video_status(v, "transcribing")
        recover_orphaned_jobs()
        video = get_video(v)
        assert video["status"] == "failed"
        assert video["error_type"] == "permanent"
        assert "exceeded max retries" in video["error_message"]


# ── 2. Database Backup & Restore Tests ─────────────────────────

class TestDatabaseBackupAndRestore:
    def test_online_backup_and_restore(self, tmp_path):
        """Verify online SQLite point-in-time backup can be created and read."""
        # Insert test data
        vid = create_video("youtube", source_url="https://youtube.com/watch?v=backup_test", title="Backup Test")
        assert vid is not None

        # Execute online backup
        backup_dir = tmp_path / "backups"
        backup_file = backup_database(backup_dir=backup_dir)

        assert backup_file.exists()
        assert backup_file.stat().st_size > 0

        # Connect to the backup file and verify integrity & data presence
        backup_conn = sqlite3.connect(str(backup_file))
        try:
            backup_conn.row_factory = sqlite3.Row
            row = backup_conn.execute("SELECT * FROM videos WHERE id = ?", (vid,)).fetchone()
            assert row is not None
            assert row["title"] == "Backup Test"
            assert row["source_url"] == "https://youtube.com/watch?v=backup_test"

            # Check pragma integrity on backup file
            integrity = backup_conn.execute("PRAGMA quick_check").fetchone()[0]
            assert integrity.lower() == "ok"
        finally:
            backup_conn.close()

    def test_backup_endpoint(self, client):
        """Test the POST /api/backup endpoint."""
        resp = client.post("/api/backup")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "backup_file" in data


# ── 3. Deep Health Check Diagnostics ──────────────────────────

class TestDeepHealthCheck:
    def test_health_check_healthy(self, client):
        """Healthy server reports 200 OK with detailed diagnostics."""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["version"] == "0.4.0"
        assert data["database"]["status"] == "healthy"
        assert data["storage"]["status"] == "healthy"
        assert "free_mb" in data["storage"]
        assert "worker" in data

    def test_health_check_degraded_on_db_failure(self, client):
        """If database probe fails, health check returns 503 degraded."""
        with patch("database.db.check_db_health", return_value={"healthy": False, "error": "Disk locked"}):
            resp = client.get("/api/health")
            assert resp.status_code == 503
            data = resp.get_json()
            assert data["status"] == "degraded"
            assert data["database"]["status"] == "unhealthy"

    def test_health_check_degraded_on_low_disk(self, client):
        """If disk space is dangerously low, health check returns 503 degraded."""
        with patch("services.video_service.check_disk_space", return_value=(False, 10)):
            resp = client.get("/api/health")
            assert resp.status_code == 503
            data = resp.get_json()
            assert data["status"] == "degraded"
            assert data["storage"]["status"] == "low_disk_space"


# ── 4. Atomic Job Claiming & Queue State Machine ──────────────

class TestAtomicJobClaiming:
    def test_claim_next_job_fifo(self):
        """Worker claims oldest queued job first and transitions atomically."""
        v1 = create_video("youtube", source_url="https://youtube.com/watch?v=first", status="queued")
        v2 = create_video("upload", original_filename="second.mp4", status="queued")

        # Claim first job
        job1 = claim_next_job()
        assert job1 is not None
        assert job1["id"] == v1
        assert job1["status"] == "downloading"
        assert job1["heartbeat_at"] is not None

        # Claim second job
        job2 = claim_next_job()
        assert job2 is not None
        assert job2["id"] == v2
        assert job2["status"] == "transcribing"  # upload moves to transcribing

        # No more queued jobs
        job3 = claim_next_job()
        assert job3 is None


# ── 5. SSRF and URL Protection Tests ──────────────────────────

class TestSSRFAndUrlProtection:
    def test_blocks_private_and_loopback_ips(self):
        """SSRF protection blocks internal networks, cloud metadata, and loopbacks."""
        forbidden_urls = [
            "http://127.0.0.1:5000/api/secret",
            "http://localhost:8080/metrics",
            "http://0.0.0.0/",
            "http://10.0.0.1/admin",
            "http://192.168.1.1/router",
            "http://172.16.0.1/internal",
            "http://169.254.169.254/latest/meta-data/",
            "http://metadata.google.internal/computeMetadata/v1/",
            "ftp://youtube.com/watch?v=123",  # Non-HTTP(S)
        ]
        for url in forbidden_urls:
            assert is_safe_url(url) is False, f"Expected {url} to be blocked by is_safe_url"

    def test_allows_public_urls(self):
        """Valid public video platforms pass URL check."""
        allowed_urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.instagram.com/reel/C3x8Y9zL_1A/",
        ]
        for url in allowed_urls:
            assert is_safe_url(url) is True, f"Expected {url} to be allowed"


# ── 6. Storage Protection Tests ───────────────────────────────

class TestStorageProtection:
    def test_reject_upload_when_disk_full(self, tmp_path):
        """Upload validation rejects files when server disk space is below limit."""
        with patch("services.video_service.check_disk_space", return_value=(False, 20)):
            with pytest.raises(VideoIngestionError) as exc_info:
                validate_uploaded_video("video.mp4", 1024 * 1024, max_size_mb=500, storage_dir=str(tmp_path))
            assert "disk space is nearly full" in str(exc_info.value).lower()


# ── 7. Transient vs. Permanent Error Classification ───────────

class TestErrorClassification:
    def test_identifies_transient_errors(self):
        """Transient errors are identified for automatic retry."""
        transient_exceptions = [
            Exception("Connection timed out after 30 seconds"),
            Exception("HTTP 429 Too Many Requests"),
            Exception("HTTP 502 Bad Gateway"),
            Exception("HTTP 503 Service Unavailable"),
            Exception("Connection reset by peer"),
        ]
        for exc in transient_exceptions:
            assert is_transient_error(exc) is True

    def test_identifies_permanent_errors(self):
        """Permanent errors terminate immediately without retries."""
        permanent_exceptions = [
            VideoIngestionError("Unsupported video format .exe"),
            VideoIngestionError("Could not extract YouTube video ID"),
            ValueError("Invalid syntax in prompt"),
        ]
        for exc in permanent_exceptions:
            assert is_transient_error(exc) is False
