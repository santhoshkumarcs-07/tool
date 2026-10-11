"""
Database module for Tool Discovery.

Handles SQLite connection, schema initialization, and provides
parameterized query helpers. All SQL uses parameterized queries
to prevent injection.
"""

import os
import sqlite3
import json
from pathlib import Path
from contextlib import contextmanager


DATABASE_DIR = Path(__file__).parent
SCHEMA_PATH = DATABASE_DIR / "schema.sql"
DEFAULT_DB_PATH = DATABASE_DIR.parent / "data" / "tool_discovery.db"


def get_db_path() -> Path:
    """Get the database file path from environment or use default."""
    env_db = os.environ.get("DATABASE_PATH")
    if env_db:
        return Path(env_db)
    data_dir = os.environ.get("DATA_DIR", "data")
    db_path = Path(data_dir) / "tool_discovery.db"
    if not db_path.is_absolute():
        db_path = DATABASE_DIR.parent / db_path
    return db_path



def init_db(db_path: Path | str = None) -> None:
    """Initialize the database with the schema."""
    if db_path is None:
        db_path = get_db_path()
    else:
        db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(db_path) as conn:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()


@contextmanager
def get_connection(db_path: Path | str = None):
    """Context manager for database connections with row factory."""
    if db_path is None:
        db_path = get_db_path()
    else:
        db_path = Path(db_path)

    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


# --- Video Operations ---

def create_video(source_type: str, source_url: str = None,
                 original_filename: str = None, title: str = None,
                 stored_filename: str = None, duration_seconds: float = None) -> int:
    """Insert a new video/analysis record. Returns the new row ID."""
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO videos (source_type, source_url, original_filename, stored_filename, title, duration_seconds)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (source_type, source_url, original_filename, stored_filename, title, duration_seconds),
        )
        conn.commit()
        return cursor.lastrowid


def update_video_status(video_id: int, status: str,
                        error_message: str = None) -> None:
    """Update the processing status of a video record."""
    with get_connection() as conn:
        conn.execute(
            """UPDATE videos
               SET status = ?, error_message = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (status, error_message, video_id),
        )
        conn.commit()


def update_video_fields(video_id: int, **kwargs) -> None:
    """Update arbitrary fields on a video record."""
    allowed = {
        "title", "duration_seconds", "status", "error_message",
        "transcript_path", "stored_filename",
    }
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [video_id]
    with get_connection() as conn:
        conn.execute(
            f"UPDATE videos SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            values,
        )
        conn.commit()


def get_video(video_id: int) -> dict | None:
    """Fetch a single video by ID."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        return dict(row) if row else None


def get_recent_videos(limit: int = 20) -> list[dict]:
    """Fetch the most recent video analyses."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM videos ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# --- Discovered Tool Operations ---

def create_discovered_tool(video_id: int, tool_data: dict) -> int:
    """Insert a discovered tool record. Returns the new row ID."""
    json_fields = ("capabilities", "requirements", "setup_steps", "target_applications")
    for field in json_fields:
        val = tool_data.get(field)
        if isinstance(val, (list, dict)):
            tool_data[field] = json.dumps(val)

    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO discovered_tools
               (video_id, name, category, purpose, capabilities,
                evidence_excerpt, video_timestamp, mention_type,
                official_website, documentation_url, repository_url,
                requirements, setup_steps, target_applications, uncertainties)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                video_id,
                tool_data.get("name"),
                tool_data.get("category"),
                tool_data.get("purpose"),
                tool_data.get("capabilities"),
                tool_data.get("evidence_excerpt"),
                tool_data.get("video_timestamp"),
                tool_data.get("mention_type"),
                tool_data.get("official_website"),
                tool_data.get("documentation_url"),
                tool_data.get("repository_url"),
                tool_data.get("requirements"),
                tool_data.get("setup_steps"),
                tool_data.get("target_applications"),
                tool_data.get("uncertainties"),
            ),
        )
        conn.commit()
        return cursor.lastrowid


def get_tools_for_video(video_id: int) -> list[dict]:
    """Fetch all discovered tools for a given video analysis."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM discovered_tools WHERE video_id = ? ORDER BY id", (video_id,)
        ).fetchall()
        tools = [dict(r) for r in rows]
        json_fields = ("capabilities", "requirements", "setup_steps", "target_applications")
        for tool in tools:
            for field in json_fields:
                if tool.get(field) and isinstance(tool[field], str):
                    try:
                        tool[field] = json.loads(tool[field])
                    except json.JSONDecodeError:
                        pass
        return tools


def get_discovered_tool(tool_id: int) -> dict | None:
    """Fetch a single discovered tool by ID."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM discovered_tools WHERE id = ?", (tool_id,)
        ).fetchone()
        if not row:
            return None
        tool = dict(row)
        json_fields = ("capabilities", "requirements", "setup_steps", "target_applications")
        for field in json_fields:
            if tool.get(field) and isinstance(tool[field], str):
                try:
                    tool[field] = json.loads(tool[field])
                except json.JSONDecodeError:
                    pass
        return tool


# --- Saved Tool (Library) Operations ---

def save_tool(discovered_tool_id: int = None, tool_data: dict = None) -> int:
    """Save a tool to the personal library. Returns the new row ID."""
    if tool_data is None:
        tool_data = {}

    json_fields = ("capabilities", "requirements", "setup_steps", "target_applications", "tags")
    for field in json_fields:
        val = tool_data.get(field)
        if isinstance(val, (list, dict)):
            tool_data[field] = json.dumps(val)

    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO saved_tools
               (discovered_tool_id, name, category, purpose, capabilities,
                official_website, documentation_url, repository_url,
                requirements, setup_steps, target_applications, personal_notes, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                discovered_tool_id,
                tool_data.get("name"),
                tool_data.get("category"),
                tool_data.get("purpose"),
                tool_data.get("capabilities"),
                tool_data.get("official_website"),
                tool_data.get("documentation_url"),
                tool_data.get("repository_url"),
                tool_data.get("requirements"),
                tool_data.get("setup_steps"),
                tool_data.get("target_applications"),
                tool_data.get("personal_notes"),
                tool_data.get("tags"),
            ),
        )
        conn.commit()
        return cursor.lastrowid


def get_saved_tools(search: str = None, category: str = None) -> list[dict]:
    """Fetch saved tools with optional search and category filter."""
    query = "SELECT * FROM saved_tools WHERE 1=1"
    params = []
    if search:
        query += " AND (name LIKE ? OR purpose LIKE ? OR personal_notes LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like])
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY saved_at DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        tools = [dict(r) for r in rows]
        json_fields = ("capabilities", "requirements", "setup_steps", "target_applications", "tags")
        for tool in tools:
            for field in json_fields:
                if tool.get(field) and isinstance(tool[field], str):
                    try:
                        tool[field] = json.loads(tool[field])
                    except json.JSONDecodeError:
                        pass
        return tools


def get_saved_tool(tool_id: int) -> dict | None:
    """Fetch a single saved tool by ID."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM saved_tools WHERE id = ?", (tool_id,)
        ).fetchone()
        if not row:
            return None
        tool = dict(row)
        json_fields = ("capabilities", "requirements", "setup_steps", "target_applications", "tags")
        for field in json_fields:
            if tool.get(field) and isinstance(tool[field], str):
                try:
                    tool[field] = json.loads(tool[field])
                except json.JSONDecodeError:
                    pass
        return tool


def update_saved_tool(tool_id: int, **kwargs) -> bool:
    """Update fields on a saved tool. Returns True if the row existed."""
    allowed = {
        "name", "category", "purpose", "capabilities",
        "official_website", "documentation_url", "repository_url",
        "requirements", "setup_steps", "target_applications",
        "personal_notes", "tags",
    }
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return False
    json_fields = ("capabilities", "requirements", "setup_steps", "target_applications", "tags")
    for f in json_fields:
        if f in fields and isinstance(fields[f], (list, dict)):
            fields[f] = json.dumps(fields[f])

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [tool_id]
    with get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE saved_tools SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            values,
        )
        conn.commit()
        return cursor.rowcount > 0


def delete_saved_tool(tool_id: int) -> bool:
    """Remove a tool from the personal library. Returns True if deleted."""
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM saved_tools WHERE id = ?", (tool_id,))
        conn.commit()
        return cursor.rowcount > 0


# --- Dashboard Stats ---

def get_dashboard_stats() -> dict:
    """Get counts for the dashboard overview."""
    with get_connection() as conn:
        total_analyses = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        completed = conn.execute(
            "SELECT COUNT(*) FROM videos WHERE status = 'completed'"
        ).fetchone()[0]
        total_discovered = conn.execute(
            "SELECT COUNT(*) FROM discovered_tools"
        ).fetchone()[0]
        total_saved = conn.execute("SELECT COUNT(*) FROM saved_tools").fetchone()[0]
        return {
            "total_analyses": total_analyses,
            "completed_analyses": completed,
            "total_discovered_tools": total_discovered,
            "total_saved_tools": total_saved,
        }


# --- Install Jobs ---

def create_install_job(tool_name: str, target_app: str, integration_type: str, plan_data: dict, status: str = "ready") -> int:
    """Create a new install job record."""
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO install_jobs (tool_name, target_app, integration_type, plan_json, status)
               VALUES (?, ?, ?, ?, ?)""",
            (tool_name, target_app, integration_type, json.dumps(plan_data), status),
        )
        conn.commit()
        return cursor.lastrowid


def get_install_job(job_id: int) -> dict | None:
    """Fetch an install job by ID."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM install_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        job = dict(row)
        if job.get("plan_json"):
            try:
                job["plan"] = json.loads(job["plan_json"])
            except Exception:
                job["plan"] = {}
        return job


def update_install_job_status(job_id: int, status: str, log: str = None) -> bool:
    """Update status and execution log of an install job."""
    with get_connection() as conn:
        if log is not None:
            cursor = conn.execute(
                """UPDATE install_jobs SET status = ?, execution_log = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                (status, log, job_id),
            )
        else:
            cursor = conn.execute(
                """UPDATE install_jobs SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                (status, job_id),
            )
        conn.commit()
        return cursor.rowcount > 0

