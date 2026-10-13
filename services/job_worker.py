"""
Job Worker Service — Persistent Background Execution & Crash Recovery.

Decouples video processing, transcription, OCR, and AI analysis from the HTTP request cycle.
Persists job state transitions in SQLite, maintains heartbeats, recovers orphaned jobs across
server restarts, and handles transient API retries with backoff.
"""

import os
import sys
import time
import json
import uuid
import shutil
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, Any

from database.db import (
    claim_next_job, update_video_status, update_video_fields,
    update_job_heartbeat, recover_orphaned_jobs, get_video,
    create_discovered_tool,
)

logger = logging.getLogger(__name__)


def is_transient_error(exc: Exception) -> bool:
    """Classify if an exception is transient (network/rate limit/timeout) vs permanent."""
    err_str = str(exc).lower()
    transient_indicators = [
        "timeout", "timed out", "connection error", "connection reset",
        "rate limit", "429", "502", "503", "504", "bad gateway",
        "service unavailable", "gateway timeout", "temporary failure",
    ]
    for ind in transient_indicators:
        if ind in err_str:
            return True
    # Import check for known transient request exceptions
    try:
        import requests
        if isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
            return True
        if isinstance(exc, requests.exceptions.HTTPError):
            if exc.response is not None and exc.response.status_code in (429, 502, 503, 504):
                return True
    except Exception:
        pass
    return False


def save_analysis_store(video_id: int, payload: dict, data_dir: Path) -> str:
    """Persist transcript, segments, skills, and summary to JSON file."""
    transcripts_dir = data_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    target = transcripts_dir / f"{video_id}.json"
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    update_video_fields(video_id, transcript_path=str(target))
    return str(target)


class JobWorker:
    """Persistent background worker loop."""

    def __init__(self, data_dir: Optional[Path] = None, poll_interval: float = 1.0):
        self.data_dir = data_dir or (Path(__file__).parent.parent / "data")
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._wakeup_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._current_job_id: Optional[int] = None
        self._jobs_processed = 0
        self._lock = threading.Lock()

    def start(self):
        """Start the worker thread after performing crash recovery."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            # Run crash recovery for orphaned jobs from previous server restarts
            try:
                recovered = recover_orphaned_jobs()
                if recovered:
                    logger.info(f"Crash recovery: restored/handled {len(recovered)} orphaned jobs: {recovered}")
            except Exception as e:
                logger.warning(f"Error during job recovery on startup: {e}")

            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="JobWorkerThread")
            self._thread.start()
            logger.info("Persistent JobWorker started successfully.")

    def stop(self, timeout: float = 5.0):
        """Signal worker to stop and wait for completion."""
        self._stop_event.set()
        self._wakeup_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        logger.info("JobWorker stopped.")

    def is_alive(self) -> bool:
        """Check if worker thread is active."""
        return self._thread is not None and self._thread.is_alive()

    def notify(self):
        """Wake worker immediately when a new job is queued."""
        self._wakeup_event.set()

    def get_status(self) -> Dict[str, Any]:
        """Introspect current worker state."""
        return {
            "is_alive": self.is_alive(),
            "current_job_id": self._current_job_id,
            "jobs_processed": self._jobs_processed,
        }

    def _run_loop(self):
        """Main worker loop."""
        while not self._stop_event.is_set():
            try:
                job = claim_next_job()
                if job:
                    self._process_claimed_job(job)
                    self._jobs_processed += 1
                else:
                    # Wait for notification or timeout
                    self._wakeup_event.wait(timeout=self.poll_interval)
                    self._wakeup_event.clear()
            except Exception as e:
                logger.exception(f"Unexpected error in JobWorker loop: {e}")
                time.sleep(1.0)

    def _process_claimed_job(self, job: dict):
        """Process a claimed job record."""
        video_id = job["id"]
        source_type = job["source_type"]
        self._current_job_id = video_id

        # Start periodic heartbeat
        heartbeat_stop = threading.Event()
        def _heartbeat_worker():
            while not heartbeat_stop.wait(10.0):
                try:
                    update_job_heartbeat(video_id)
                except Exception:
                    pass

        hb_thread = threading.Thread(target=_heartbeat_worker, daemon=True)
        hb_thread.start()

        try:
            if source_type in ("youtube", "instagram"):
                self._execute_url_job(video_id, job["source_url"])
            elif source_type == "upload":
                stored_fn = job.get("stored_filename")
                orig_fn = job.get("original_filename") or stored_fn or "uploaded_video.mp4"
                upload_path = self.data_dir / "uploads" / stored_fn
                self._execute_upload_job(video_id, upload_path, orig_fn, stored_fn)
            elif source_type == "text":
                # If text analysis was queued asynchronously
                self._execute_text_job(video_id)
            else:
                update_video_status(video_id, "failed", f"Unsupported source type: {source_type}", error_type="permanent")
        except Exception as e:
            self._handle_job_error(video_id, job, e)
        finally:
            heartbeat_stop.set()
            hb_thread.join(timeout=1.0)
            self._current_job_id = None

    def _execute_url_job(self, video_id: int, url: str):
        """Execute URL ingestion and analysis."""
        from services.video_service import process_url
        from services.extraction_service import extract_video_intelligence
        from services.verification_service import verify_tool

        update_video_status(video_id, "downloading")
        info = process_url(url)
        title = info.get("title", url)
        update_video_fields(video_id, title=title)

        transcript_text = info.get("transcript", "")
        segments = info.get("segments", [])

        update_video_status(video_id, "analyzing")
        intel = extract_video_intelligence(transcript_text)
        tools = intel.get("tools", [])
        skills = intel.get("skills", [])
        summary = intel.get("summary", "")
        key_takeaways = intel.get("key_takeaways", [])

        for tool_data in tools:
            v_res = verify_tool(tool_data)
            tool_data["verified"] = v_res["verified"]
            tool_data["verification_details"] = v_res["verification_details"]
            tool_id = create_discovered_tool(video_id, tool_data)
            tool_data["id"] = tool_id

        save_analysis_store(video_id, {
            "transcript": transcript_text,
            "segments": segments,
            "skills": skills,
            "summary": summary,
            "key_takeaways": key_takeaways,
            "video_id_code": info.get("video_id"),
            "tools": tools,
        }, self.data_dir)

        update_video_status(video_id, "completed")
        logger.info(f"URL analysis completed for video {video_id}")

    def _execute_upload_job(self, video_id: int, upload_path: Path, filename: str, stored_name: str):
        """Execute video upload transcription, visual OCR, and intelligence extraction."""
        from services.transcription_service import extract_audio, transcribe_audio_file
        from services.extraction_service import extract_video_intelligence
        from services.verification_service import verify_tool
        from services.video_service import extract_video_visual_context

        if not upload_path.exists():
            update_video_status(video_id, "failed", f"Uploaded media file not found: {upload_path.name}", error_type="permanent")
            return

        audio_dir = self.data_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_path = audio_dir / f"{uuid.uuid4().hex}.wav"

        try:
            update_video_status(video_id, "transcribing")
            extract_audio(str(upload_path), str(audio_path))
            trans_res = transcribe_audio_file(str(audio_path))
            full_text = trans_res.get("full_text", "")
            segments = trans_res.get("segments", [])

            # Extract visual context from frames
            visual_ctx = extract_video_visual_context(str(upload_path))
            if visual_ctx:
                full_text = full_text + visual_ctx

            update_video_status(video_id, "analyzing")
            intel = extract_video_intelligence(full_text)
            tools = intel.get("tools", [])
            skills = intel.get("skills", [])
            summary = intel.get("summary", "")
            key_takeaways = intel.get("key_takeaways", [])

            for tool_data in tools:
                v_res = verify_tool(tool_data)
                tool_data["verified"] = v_res["verified"]
                tool_data["verification_details"] = v_res["verification_details"]
                tool_id = create_discovered_tool(video_id, tool_data)
                tool_data["id"] = tool_id

            save_analysis_store(video_id, {
                "transcript": full_text,
                "segments": segments,
                "skills": skills,
                "summary": summary,
                "key_takeaways": key_takeaways,
                "tools": tools,
            }, self.data_dir)

            update_video_status(video_id, "completed")
            logger.info(f"Upload analysis completed for video {video_id}")
        finally:
            if audio_path and audio_path.exists():
                try:
                    audio_path.unlink()
                except Exception:
                    pass

    def _execute_text_job(self, video_id: int):
        """Execute queued text intelligence extraction."""
        from services.extraction_service import extract_video_intelligence
        from services.verification_service import verify_tool

        video = get_video(video_id)
        if not video:
            return
        # If text was staged in transcript_path
        transcript_text = ""
        if video.get("transcript_path"):
            p = Path(video["transcript_path"])
            if p.exists():
                try:
                    payload = json.loads(p.read_text(encoding="utf-8"))
                    transcript_text = payload.get("transcript", "")
                except Exception:
                    pass

        if not transcript_text:
            transcript_text = video.get("title", "")

        update_video_status(video_id, "analyzing")
        intel = extract_video_intelligence(transcript_text)
        tools = intel.get("tools", [])
        skills = intel.get("skills", [])
        summary = intel.get("summary", "")
        key_takeaways = intel.get("key_takeaways", [])

        for tool_data in tools:
            v_res = verify_tool(tool_data)
            tool_data["verified"] = v_res["verified"]
            tool_data["verification_details"] = v_res["verification_details"]
            tool_id = create_discovered_tool(video_id, tool_data)
            tool_data["id"] = tool_id

        save_analysis_store(video_id, {
            "transcript": transcript_text,
            "segments": [],
            "skills": skills,
            "summary": summary,
            "key_takeaways": key_takeaways,
            "tools": tools,
        }, self.data_dir)

        update_video_status(video_id, "completed")

    def _handle_job_error(self, video_id: int, job: dict, exc: Exception):
        """Classify and handle job failure with retry or termination."""
        retries = job.get("retry_count", 0) or 0
        max_retries = job.get("max_retries", 3) or 3
        transient = is_transient_error(exc)

        logger.exception(f"Job {video_id} encountered exception: {exc}")

        if transient and retries < max_retries:
            next_retry = retries + 1
            backoff_secs = min(2 ** next_retry, 30)
            logger.warning(
                f"Job {video_id} failed with transient error: {exc}. "
                f"Re-queuing (attempt {next_retry}/{max_retries}) with {backoff_secs}s backoff."
            )
            update_video_fields(
                video_id,
                status="queued",
                retry_count=next_retry,
                error_type="transient",
                error_message=f"Attempt {next_retry} failed ({str(exc)[:150]}). Queued for retry.",
                heartbeat_at=None,
            )
            time.sleep(backoff_secs)
        else:
            err_msg = str(exc)
            logger.error(f"Job {video_id} permanently failed: {err_msg}")
            update_video_status(video_id, "failed", err_msg, error_type="permanent")


# Global singleton instance for easy app integration
_global_worker: Optional[JobWorker] = None


def get_global_worker(data_dir: Optional[Path] = None) -> JobWorker:
    """Retrieve or initialize the global JobWorker instance."""
    global _global_worker
    if _global_worker is None:
        _global_worker = JobWorker(data_dir=data_dir)
    return _global_worker
