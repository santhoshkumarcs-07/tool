"""
Tool Discovery — Flask Application

Personal AI tool discovery and installation assistant.
Analyzes video content to discover AI tools, developer utilities,
MCP servers, coding agents, and automation tools.
Supports OpenRouter exclusive free models and One-Click AI App integration.
"""

import os
import sys
import uuid
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from werkzeug.utils import secure_filename

from flask import (
    Flask, jsonify, request, send_from_directory, abort, session
)
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

logger = logging.getLogger(__name__)

from database.db import (
    init_db, get_dashboard_stats, get_recent_videos,
    create_video, update_video_status, update_video_fields,
    get_video, create_discovered_tool, get_tools_for_video,
    get_discovered_tool, save_tool, get_saved_tools, get_saved_tool,
    update_saved_tool, delete_saved_tool,
    create_install_job, get_install_job, update_install_job_status,
)
from services.job_worker import get_global_worker


def create_app(test_config: dict = None) -> Flask:
    """Application factory."""
    app = Flask(
        __name__,
        static_folder="static",
        template_folder="templates",
    )

    # Configuration
    app.config["SECRET_KEY"] = os.environ.get(
        "FLASK_SECRET_KEY"
    ) or os.environ.get("SECRET_KEY") or "prod-secure-token-tool-discovery-2026"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if os.environ.get("FLASK_ENV") == "production" or os.environ.get("ENABLE_HTTPS", "").lower() == "true":
        app.config["SESSION_COOKIE_SECURE"] = True

    app.config["MAX_CONTENT_LENGTH"] = (
        int(os.environ.get("MAX_UPLOAD_SIZE_MB", 500)) * 1024 * 1024
    )
    app.config["DATA_DIR"] = os.environ.get("DATA_DIR", "data")

    if test_config:
        app.config.update(test_config)

    # Ensure data directories exist
    data_dir = Path(app.config["DATA_DIR"])
    if not data_dir.is_absolute():
        data_dir = Path(__file__).parent / data_dir
    for subdir in ("uploads", "transcripts", "frames", "audio"):
        (data_dir / subdir).mkdir(parents=True, exist_ok=True)
    app.config["DATA_DIR_RESOLVED"] = str(data_dir)

    # Initialize database
    init_db()

    # Initialize and start persistent JobWorker
    worker = get_global_worker(data_dir=data_dir)
    app.worker = worker
    if not app.config.get("TESTING"):
        worker.start()

    # ── Security & Session Isolation Middleware ─────────────────────

    @app.before_request
    def ensure_user_session():
        if "user_id" not in session:
            session["user_id"] = str(uuid.uuid4())

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    def get_current_user_id() -> str:
        return session.get("user_id") or request.headers.get("X-User-ID") or "default"

    # ── Serve the SPA frontend ──────────────────────────────────────

    @app.route("/")
    def serve_index():
        return send_from_directory(Path(__file__).parent, "index.html")

    @app.route("/style.css")
    def serve_css():
        return send_from_directory(Path(__file__).parent, "style.css")

    @app.route("/script.js")
    def serve_js():
        return send_from_directory(
            Path(__file__).parent, "script.js", mimetype="application/javascript"
        )

    # ── API Routes ──────────────────────────────────────────────────

    @app.route("/api/health")
    def health_check():
        """Health check endpoint — verifies server, database, storage, and worker."""
        from services.llm_provider import is_configured
        from database.db import check_db_health
        from services.video_service import check_disk_space

        db_health = check_db_health()
        data_dir_res = app.config.get("DATA_DIR_RESOLVED", "data")
        has_space, free_mb = check_disk_space(data_dir_res, min_free_mb=50)
        worker_status = worker.get_status()

        is_healthy = db_health.get("healthy", False) and has_space

        health_data = {
            "status": "ok" if is_healthy else "degraded",
            "version": "0.4.0",
            "gateway": "openrouter",
            "llm_configured": is_configured(),
            "database": {
                "status": "healthy" if db_health.get("healthy") else "unhealthy",
                "queued_jobs": db_health.get("queued_jobs", 0),
                "processing_jobs": db_health.get("processing_jobs", 0),
            },
            "storage": {
                "status": "healthy" if has_space else "low_disk_space",
                "free_mb": free_mb,
            },
            "worker": {
                "is_alive": worker_status.get("is_alive", False),
                "current_job_id": worker_status.get("current_job_id"),
                "jobs_processed": worker_status.get("jobs_processed", 0),
            },
        }
        status_code = 200 if is_healthy else 503
        return jsonify(health_data), status_code

    @app.route("/api/backup", methods=["POST"])
    def trigger_backup():
        """Trigger an online database backup point-in-time."""
        from database.db import backup_database
        try:
            backup_path = backup_database()
            return jsonify({
                "status": "ok",
                "message": "Database backup completed successfully.",
                "backup_file": backup_path.name,
                "backup_path": str(backup_path),
            }), 200
        except Exception as e:
            logger.exception(f"Database backup failed: {e}")
            return jsonify({"error": f"Backup failed: {str(e)}"}), 500

    @app.route("/api/dashboard")
    def dashboard():
        """Dashboard data: stats and recent analyses."""
        stats = get_dashboard_stats()
        user_id = get_current_user_id()
        recent = get_recent_videos(limit=10, user_id=user_id)
        return jsonify({
            "stats": stats,
            "recent_analyses": recent,
        })

    @app.route("/api/config/status")
    def config_status():
        """Return non-sensitive configuration status."""
        from services.llm_provider import get_llm_config, is_configured
        cfg = get_llm_config()
        return jsonify({
            "llm_provider": "openrouter",
            "llm_model": cfg["model"],
            "llm_configured": is_configured(),
            "max_upload_mb": int(os.environ.get("MAX_UPLOAD_SIZE_MB", 500)),
            "max_duration_seconds": int(os.environ.get("MAX_VIDEO_DURATION_SECONDS", 1200)),
        })

    @app.route("/api/models/free")
    def list_free_models():
        """Fetch available free OpenRouter models."""
        from services.llm_provider import fetch_free_models
        models = fetch_free_models()
        return jsonify({"models": models})

    # ── Companion Agent Status ──────────────────────────────────────

    @app.route("/api/companion/status")
    def companion_status():
        """Check status and capabilities of the Local Companion Service."""
        from services.companion_service import check_companion_health
        health = check_companion_health()
        return jsonify(health)

    # ── Analysis Helpers & Persistence ──────────────────────────────

    def save_analysis_store(video_id: int, payload: dict) -> str:
        """Persist transcript, segments, skills, and summary to JSON file."""
        data_dir = Path(app.config["DATA_DIR_RESOLVED"])
        transcripts_dir = data_dir / "transcripts"
        transcripts_dir.mkdir(parents=True, exist_ok=True)
        target = transcripts_dir / f"{video_id}.json"
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        update_video_fields(video_id, transcript_path=str(target))
        return str(target)

    def load_analysis_store(video_id: int) -> dict:
        """Load stored analysis payload if available."""
        data_dir = Path(app.config["DATA_DIR_RESOLVED"])
        target = data_dir / "transcripts" / f"{video_id}.json"
        if target.exists():
            try:
                return json.loads(target.read_text(encoding="utf-8"))
            except Exception:
                pass

        try:
            video = get_video(video_id)
            if video and video.get("transcript_path"):
                p = Path(video["transcript_path"])
                if p.exists():
                    return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass

        return {}

    # ── Background Job Executors ────────────────────────────────────

    def execute_url_analysis(video_id: int, url: str) -> dict:
        """Background executor for video URL analysis."""
        from services.video_service import process_url
        from services.extraction_service import extract_video_intelligence
        from services.verification_service import verify_tool

        try:
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
            })

            update_video_status(video_id, "completed")
            return {
                "video_id": video_id,
                "title": title,
                "source_type": info["source_type"],
                "source_url": url,
                "tools_count": len(tools),
                "tools": tools,
                "skills": skills,
                "summary": summary,
                "key_takeaways": key_takeaways,
                "transcript": transcript_text,
                "segments": segments,
            }
        except Exception as e:
            logger.exception(f"URL analysis failed for video {video_id}: {e}")
            update_video_status(video_id, "failed", str(e))
            raise

    def execute_upload_analysis(video_id: int, upload_path: Path, filename: str, stored_name: str) -> dict:
        """Background executor for video upload transcription and analysis."""
        from services.transcription_service import extract_audio, transcribe_audio_file
        from services.extraction_service import extract_video_intelligence
        from services.verification_service import verify_tool
        from services.video_service import extract_video_visual_context

        data_dir = Path(app.config["DATA_DIR_RESOLVED"])
        audio_dir = data_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_path = audio_dir / f"{uuid.uuid4().hex}.wav"

        try:
            update_video_status(video_id, "transcribing")
            extract_audio(str(upload_path), str(audio_path))
            trans_res = transcribe_audio_file(str(audio_path))
            full_text = trans_res.get("full_text", "")
            segments = trans_res.get("segments", [])

            # Extract visible code, commands, and tools from video frames
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
            })

            update_video_status(video_id, "completed")
            return {
                "video_id": video_id,
                "title": filename,
                "source_type": "upload",
                "stored_filename": stored_name,
                "media_url": f"/api/media/{stored_name}",
                "tools_count": len(tools),
                "tools": tools,
                "skills": skills,
                "summary": summary,
                "key_takeaways": key_takeaways,
                "transcript": full_text,
                "segments": segments,
            }
        except Exception as e:
            logger.exception(f"Upload analysis failed for video {video_id}: {e}")
            update_video_status(video_id, "failed", str(e))
            raise
        finally:
            # Clean up temporary WAV extract to conserve disk space
            if audio_path and audio_path.exists():
                try:
                    audio_path.unlink()
                except Exception:
                    pass

    # ── Analysis Routes ─────────────────────────────────────────────

    @app.route("/api/analyze/text", methods=["POST"])
    def analyze_text():
        """Extract tools and skills from pasted transcript text."""
        from services.extraction_service import extract_video_intelligence
        from services.verification_service import verify_tool
        from services.llm_provider import LLMError

        data = request.get_json(silent=True)
        if not data or not data.get("transcript"):
            return jsonify({"error": "No transcript text provided."}), 400

        transcript = str(data["transcript"]).strip()
        if len(transcript) < 20:
            return jsonify({"error": "Transcript is too short to analyze."}), 400

        user_id = get_current_user_id()
        video_id = create_video("text", title="Text Analysis", user_id=user_id)
        update_video_status(video_id, "analyzing")

        try:
            intel = extract_video_intelligence(transcript)
            tools = intel.get("tools", [])
            skills = intel.get("skills", [])
            summary = intel.get("summary", "")
            key_takeaways = intel.get("key_takeaways", [])
        except LLMError as e:
            update_video_status(video_id, "failed", str(e))
            return jsonify({"error": str(e)}), 502
        except Exception as e:
            update_video_status(video_id, "failed", f"Analysis error: {str(e)}")
            return jsonify({"error": str(e)}), 500

        # Verify and save tools
        for tool_data in tools:
            v_res = verify_tool(tool_data)
            tool_data["verified"] = v_res["verified"]
            tool_data["verification_details"] = v_res["verification_details"]
            tool_id = create_discovered_tool(video_id, tool_data)
            tool_data["id"] = tool_id

        # Approximate line-by-line segments for pasted text
        segments = []
        for idx, line in enumerate(transcript.split("\n")):
            line = line.strip()
            if line:
                segments.append({"start": idx * 4.0, "end": (idx + 1) * 4.0, "text": line})

        save_analysis_store(video_id, {
            "transcript": transcript,
            "segments": segments,
            "skills": skills,
            "summary": summary,
            "key_takeaways": key_takeaways,
            "tools": tools,
        })

        update_video_status(video_id, "completed")

        return jsonify({
            "video_id": video_id,
            "title": "Text Analysis",
            "source_type": "text",
            "tools_count": len(tools),
            "tools": tools,
            "skills": skills,
            "summary": summary,
            "key_takeaways": key_takeaways,
            "transcript": transcript,
            "segments": segments,
        })

    @app.route("/api/analyze/url", methods=["POST"])
    def analyze_url():
        """Visit video URL, transcribe speech, and discover tools & skills."""
        from services.video_service import process_url, VideoIngestionError
        from services.llm_provider import LLMError

        data = request.get_json(silent=True)
        if not data or not data.get("url"):
            return jsonify({"error": "Video URL is required."}), 400

        url = str(data["url"]).strip()
        user_id = get_current_user_id()
        source_type = "instagram" if "instagram" in url else "youtube"
        video_id = create_video(source_type, source_url=url, title=url, user_id=user_id)

        is_async = (
            request.args.get("async", "").lower() in ("true", "1") or
            request.headers.get("X-Async-Job", "").lower() in ("true", "1")
        )

        if is_async:
            worker.notify()
            return jsonify({
                "video_id": video_id,
                "job_id": video_id,
                "status": "pending",
                "source_url": url,
                "message": "Video URL queued for background analysis.",
            }), 202

        try:
            result = execute_url_analysis(video_id, url)
            return jsonify(result), 200
        except VideoIngestionError as e:
            return jsonify({"error": str(e)}), 400
        except LLMError as e:
            return jsonify({"error": str(e)}), 502
        except Exception as e:
            return jsonify({"error": f"URL analysis error: {str(e)}"}), 500

    @app.route("/api/analyze/upload", methods=["POST"])
    def analyze_upload():
        """Upload and transcribe local video or screen recording."""
        from services.video_service import validate_uploaded_video, VideoIngestionError
        from services.transcription_service import TranscriptionError
        from services.llm_provider import LLMError

        if "video" not in request.files:
            return jsonify({"error": "No video file provided."}), 400

        file = request.files["video"]
        if not file.filename:
            return jsonify({"error": "Empty filename."}), 400

        filename = secure_filename(file.filename)
        max_mb = int(os.environ.get("MAX_UPLOAD_SIZE_MB", 500))

        data_dir = Path(app.config["DATA_DIR_RESOLVED"])
        uploads_dir = data_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}_{filename}"
        upload_path = uploads_dir / stored_name
        file.save(upload_path)

        file_size = os.path.getsize(upload_path)
        try:
            validate_uploaded_video(filename, file_size, max_size_mb=max_mb, storage_dir=str(data_dir))
        except VideoIngestionError as e:
            if upload_path.exists():
                upload_path.unlink()
            return jsonify({"error": str(e)}), 400

        user_id = get_current_user_id()
        video_id = create_video("upload", original_filename=filename, stored_filename=stored_name, title=filename, user_id=user_id)

        is_async = (
            request.args.get("async", "").lower() in ("true", "1") or
            request.headers.get("X-Async-Job", "").lower() in ("true", "1")
        )

        if is_async:
            worker.notify()
            return jsonify({
                "video_id": video_id,
                "job_id": video_id,
                "status": "pending",
                "title": filename,
                "source_type": "upload",
                "stored_filename": stored_name,
                "media_url": f"/api/media/{stored_name}",
                "message": "Video uploaded and processing started in background.",
            }), 202

        try:
            result = execute_upload_analysis(video_id, upload_path, filename, stored_name)
            return jsonify(result), 200
        except VideoIngestionError as e:
            return jsonify({"error": str(e)}), 400
        except TranscriptionError as e:
            return jsonify({"error": str(e)}), 400
        except LLMError as e:
            return jsonify({"error": str(e)}), 502
        except Exception as e:
            return jsonify({"error": f"Upload processing error: {str(e)}"}), 500

    @app.route("/api/analysis/<int:video_id>")
    def get_analysis(video_id):
        """Get complete results for an analysis."""
        video = get_video(video_id)
        if not video:
            return jsonify({"error": "Analysis not found."}), 404

        tools = get_tools_for_video(video_id)
        store = load_analysis_store(video_id)
        if not tools and store.get("tools"):
            tools = store["tools"]

        stored_fn = video.get("stored_filename")
        media_url = f"/api/media/{stored_fn}" if stored_fn else None

        transcript = store.get("transcript", "")
        segments = store.get("segments", [])

        # Graceful fallback: If transcript is missing, reconstruct from tools evidence excerpts
        if not transcript:
            evidence_parts = []
            for idx, t in enumerate(tools):
                ex = t.get("evidence_excerpt")
                if ex:
                    evidence_parts.append(f"{t['name']}: {ex}")
                    if not segments:
                        segments.append({"start": idx * 15.0, "end": (idx + 1) * 15.0, "text": f"{t['name']}: {ex}"})
            if evidence_parts:
                transcript = "\n\n".join(evidence_parts)
            elif video.get("title"):
                transcript = f"Video Content Overview: {video['title']}"

        return jsonify({
            "video_id": video_id,
            "title": video.get("title", "Analysis"),
            "status": video["status"],
            "source_type": video["source_type"],
            "source_url": video.get("source_url"),
            "stored_filename": stored_fn,
            "media_url": media_url,
            "tools_count": len(tools),
            "tools": tools,
            "skills": store.get("skills", []),
            "summary": store.get("summary", ""),
            "key_takeaways": store.get("key_takeaways", []),
            "transcript": transcript,
            "segments": segments,
            "error_message": video.get("error_message"),
        })

    @app.route("/api/media/<path:filename>")
    def serve_media(filename):
        """Stream stored recorded / uploaded videos to browser player safely."""
        # Sanitize against path traversal attacks
        safe_name = os.path.basename(filename)
        if ".." in filename or safe_name != filename:
            abort(400)
        data_dir = Path(app.config["DATA_DIR_RESOLVED"])
        uploads_dir = data_dir / "uploads"
        return send_from_directory(uploads_dir, safe_name)

    @app.route("/api/video/ask", methods=["POST"])
    def ask_video():
        """Ask AI a question about the video transcript (ScreenApp AI Q&A)."""
        from services.extraction_service import answer_video_question
        req = request.get_json(silent=True) or {}
        video_id = req.get("video_id")
        question = req.get("question", "").strip()
        transcript = req.get("transcript", "").strip()

        if not question:
            return jsonify({"error": "Question is required."}), 400

        tools = []
        if video_id:
            store = load_analysis_store(video_id)
            if not transcript:
                transcript = store.get("transcript", "")
            if not transcript:
                video = get_video(video_id)
                if video and video.get("source_url"):
                    transcript = f"Video URL: {video['source_url']}"
            tools = get_tools_for_video(video_id)

        if not transcript:
            return jsonify({"error": "No transcript available for this video."}), 404

        answer = answer_video_question(transcript, question, tools)
        return jsonify({"answer": answer})

    # ── Library Routes ──────────────────────────────────────────────

    @app.route("/api/library")
    def list_library():
        """List saved tools with optional search and category filter."""
        search = request.args.get("search", "").strip()
        category = request.args.get("category", "").strip()
        user_id = get_current_user_id()
        tools = get_saved_tools(
            search=search or None,
            category=category or None,
            user_id=user_id,
        )
        return jsonify({"tools": tools})

    @app.route("/api/library/save", methods=["POST"])
    def save_to_library():
        """Save a discovered tool to the personal library."""
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "No data provided."}), 400

        user_id = get_current_user_id()
        discovered_id = data.get("discovered_tool_id")
        if discovered_id:
            dt = get_discovered_tool(discovered_id)
            if not dt:
                return jsonify({"error": "Discovered tool not found."}), 404
            tool_data = {
                "name": dt["name"],
                "category": dt.get("category"),
                "purpose": dt.get("purpose"),
                "capabilities": dt.get("capabilities"),
                "official_website": dt.get("official_website"),
                "documentation_url": dt.get("documentation_url"),
                "repository_url": dt.get("repository_url"),
                "requirements": dt.get("requirements"),
                "setup_steps": dt.get("setup_steps"),
                "target_applications": dt.get("target_applications"),
            }
            saved_id = save_tool(discovered_tool_id=discovered_id, tool_data=tool_data, user_id=user_id)
        else:
            if not data.get("name"):
                return jsonify({"error": "Tool name is required."}), 400
            saved_id = save_tool(tool_data=data, user_id=user_id)

        return jsonify({"id": saved_id, "message": "Tool saved to library."})

    @app.route("/api/library/<int:tool_id>", methods=["GET"])
    def get_library_tool(tool_id):
        """Get a single saved tool."""
        tool = get_saved_tool(tool_id)
        if not tool:
            return jsonify({"error": "Tool not found."}), 404
        return jsonify(tool)

    @app.route("/api/library/<int:tool_id>", methods=["PUT"])
    def update_library_tool(tool_id):
        """Update a saved tool's fields (e.g., notes)."""
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "No data provided."}), 400
        updated = update_saved_tool(tool_id, **data)
        if not updated:
            return jsonify({"error": "Tool not found or no valid fields."}), 404
        return jsonify({"message": "Tool updated."})

    @app.route("/api/library/<int:tool_id>", methods=["DELETE"])
    def delete_library_tool(tool_id):
        """Remove a tool from the library."""
        deleted = delete_saved_tool(tool_id)
        if not deleted:
            return jsonify({"error": "Tool not found."}), 404
        return jsonify({"message": "Tool removed from library."})

    # ── AI App Integration & One-Click Installation ────────────────

    @app.route("/api/install/plan", methods=["POST"])
    def plan_installation():
        """
        Generate structured installation plan for target application.
        Expects JSON: { "tool": {...} or "tool_id": ..., "target": "vscode" | "claude-code" }
        """
        from services.configuration_service import generate_install_plan, ConfigError

        data = request.get_json(silent=True) or {}
        target = data.get("target", "vscode").strip()
        tool_data = data.get("tool")

        if not tool_data and data.get("tool_id"):
            tool_data = get_saved_tool(data["tool_id"])
        elif not tool_data and data.get("discovered_tool_id"):
            tool_data = get_discovered_tool(data["discovered_tool_id"])

        if not tool_data:
            return jsonify({"error": "Tool information is required."}), 400

        try:
            plan = generate_install_plan(tool_data, target)
            job_id = create_install_job(
                tool_name=plan["tool_name"],
                target_app=target,
                integration_type=plan["integration_type"],
                plan_data=plan,
                status="ready"
            )
            plan["job_id"] = job_id
            return jsonify(plan)
        except ConfigError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/install/approve", methods=["POST"])
    def approve_and_install():
        """
        Execute an approved action via the Local Companion Service.
        Requires explicit user approval in the request payload.
        """
        from services.companion_service import execute_approved_action

        data = request.get_json(silent=True) or {}
        job_id = data.get("job_id")
        user_approved = bool(data.get("approved", False))
        payload = data.get("companion_payload", {})

        if not user_approved:
            return jsonify({
                "status": "Awaiting approval",
                "message": "User approval is required before running installation actions."
            }), 400

        if not payload:
            return jsonify({
                "status": "Manual setup required",
                "message": "This tool requires manual installation. Use the copyable instructions."
            }), 200

        if job_id:
            update_install_job_status(job_id, "installing")

        result = execute_approved_action(payload, user_approved=True)

        if job_id:
            # Map status string to valid DB status
            status_map = {
                "Installed and verified": "installed_verified",
                "Failed": "failed",
                "Manual setup required": "manual_required",
                "Awaiting approval": "awaiting_approval",
            }
            db_status = status_map.get(result.get("status"), "failed")
            update_install_job_status(job_id, db_status, log=result.get("execution_log", ""))

        return jsonify(result)

    @app.route("/api/install/job/<int:job_id>")
    def check_install_job(job_id):
        """Fetch the current state and execution logs of an install job."""
        job = get_install_job(job_id)
        if not job:
            return jsonify({"error": "Install job not found."}), 404
        return jsonify(job)

    # ── Legacy Configuration Route ──────────────────────────────────

    @app.route("/api/configurations/generate", methods=["POST"])
    def generate_configuration():
        """Generate setup instructions for a saved tool + target app."""
        from services.configuration_service import generate_config, ConfigError

        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "No data provided."}), 400

        tool_id = data.get("tool_id")
        target = data.get("target", "").strip()

        if not tool_id or not target:
            return jsonify({"error": "tool_id and target are required."}), 400

        tool = get_saved_tool(tool_id)
        if not tool:
            return jsonify({"error": "Saved tool not found."}), 404

        try:
            result = generate_config(tool, target)
            return jsonify(result)
        except ConfigError as e:
            return jsonify({"error": str(e)}), 400

    # ── Error Handlers ──────────────────────────────────────────────

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(413)
    def too_large(e):
        return jsonify({"error": "File too large"}), 413

    @app.errorhandler(500)
    def server_error(e):
        return jsonify({"error": "Internal server error"}), 500

    return app


# ── Entry Point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app = create_app()
    print(f"  Tool Discovery running at http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)
