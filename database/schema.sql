-- Tool Discovery Database Schema

-- Videos and analysis jobs
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT DEFAULT 'default',
    source_type TEXT NOT NULL CHECK(source_type IN ('youtube', 'instagram', 'upload', 'text')),
    source_url TEXT,
    original_filename TEXT,
    stored_filename TEXT,
    title TEXT,
    duration_seconds REAL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'downloading', 'transcribing', 'analyzing', 'completed', 'failed')),
    error_message TEXT,
    transcript_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Discovered tools from analysis
CREATE TABLE IF NOT EXISTS discovered_tools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    category TEXT,
    purpose TEXT,
    capabilities TEXT,  -- JSON array
    evidence_excerpt TEXT,
    video_timestamp TEXT,
    mention_type TEXT CHECK(mention_type IN ('explicit', 'inferred')),
    official_website TEXT,
    documentation_url TEXT,
    repository_url TEXT,
    requirements TEXT,  -- JSON array
    setup_steps TEXT,   -- JSON array
    target_applications TEXT,  -- JSON array
    uncertainties TEXT,
    verified INTEGER DEFAULT 0,
    verification_details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE
);

-- Personal library of saved tools
CREATE TABLE IF NOT EXISTS saved_tools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT DEFAULT 'default',
    discovered_tool_id INTEGER,
    name TEXT NOT NULL,
    category TEXT,
    purpose TEXT,
    capabilities TEXT,       -- JSON array
    official_website TEXT,
    documentation_url TEXT,
    repository_url TEXT,
    requirements TEXT,       -- JSON array
    setup_steps TEXT,        -- JSON array
    target_applications TEXT, -- JSON array
    personal_notes TEXT,
    tags TEXT,               -- JSON array
    saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (discovered_tool_id) REFERENCES discovered_tools(id) ON DELETE SET NULL
);

-- Evidence linking tools to video moments
CREATE TABLE IF NOT EXISTS tool_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discovered_tool_id INTEGER NOT NULL,
    video_id INTEGER NOT NULL,
    evidence_type TEXT CHECK(evidence_type IN ('transcript', 'ocr', 'caption')),
    content TEXT NOT NULL,
    timestamp_start TEXT,
    timestamp_end TEXT,
    confidence TEXT CHECK(confidence IN ('high', 'medium', 'low')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (discovered_tool_id) REFERENCES discovered_tools(id) ON DELETE CASCADE,
    FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE
);

-- Generated configurations
CREATE TABLE IF NOT EXISTS configurations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    saved_tool_id INTEGER NOT NULL,
    target_application TEXT NOT NULL,
    config_content TEXT NOT NULL,
    instructions TEXT,
    dependencies TEXT,       -- JSON array
    documentation_link TEXT,
    warnings TEXT,           -- JSON array
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (saved_tool_id) REFERENCES saved_tools(id) ON DELETE CASCADE
);

-- One-Click AI Application Install Jobs
CREATE TABLE IF NOT EXISTS install_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name TEXT NOT NULL,
    target_app TEXT NOT NULL,
    integration_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ready'
        CHECK(status IN ('ready', 'awaiting_approval', 'installing', 'installed_verified', 'failed', 'manual_required')),
    plan_json TEXT NOT NULL,
    execution_log TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
CREATE INDEX IF NOT EXISTS idx_videos_created ON videos(created_at);
CREATE INDEX IF NOT EXISTS idx_discovered_tools_video ON discovered_tools(video_id);
CREATE INDEX IF NOT EXISTS idx_discovered_tools_name ON discovered_tools(name);
CREATE INDEX IF NOT EXISTS idx_saved_tools_name ON saved_tools(name);
CREATE INDEX IF NOT EXISTS idx_saved_tools_category ON saved_tools(category);
CREATE INDEX IF NOT EXISTS idx_tool_evidence_tool ON tool_evidence(discovered_tool_id);
CREATE INDEX IF NOT EXISTS idx_configurations_tool ON configurations(saved_tool_id);
CREATE INDEX IF NOT EXISTS idx_install_jobs_status ON install_jobs(status);
