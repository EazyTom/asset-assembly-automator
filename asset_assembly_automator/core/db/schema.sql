-- Asset Assembly Automator schema v1

PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    pipeline_type TEXT NOT NULL DEFAULT 'character',
    unity_project_path TEXT,
    output_root TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pipelines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    asset_name TEXT NOT NULL,
    asset_kind TEXT NOT NULL DEFAULT 'character',
    current_stage TEXT NOT NULL DEFAULT 'draft',
    status TEXT NOT NULL DEFAULT 'active',
    selected_concept_provider TEXT,
    selected_concept_asset_id INTEGER,
    rig_provider TEXT NOT NULL DEFAULT 'meshy',
    poly_budget TEXT NOT NULL DEFAULT 'hero',
    multi_view INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pipeline_stages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_id INTEGER NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    stage_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT,
    completed_at TEXT,
    duration_ms INTEGER,
    error_message TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS pipeline_timing_stats (
    pipeline_id INTEGER PRIMARY KEY REFERENCES pipelines(id) ON DELETE CASCADE,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now')),
    trigger TEXT NOT NULL DEFAULT 'unity_import',
    pipeline_wall_ms INTEGER,
    stage_total_ms INTEGER,
    meshy_total_ms INTEGER,
    concept_ms INTEGER,
    magnific_ms INTEGER,
    unity_stage_ms INTEGER,
    unity_csharp_ms INTEGER,
    stage_durations_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_id INTEGER NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    stage_id INTEGER REFERENCES pipeline_stages(id),
    provider TEXT NOT NULL,
    template_id TEXT,
    final_text TEXT NOT NULL,
    template_vars_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_id INTEGER NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    stage_id INTEGER REFERENCES pipeline_stages(id),
    asset_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    thumb_path TEXT,
    provider TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS external_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_id INTEGER NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    task_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    face_count INTEGER,
    credits_used REAL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    submitted_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS animation_selections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_id INTEGER NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    action_id INTEGER NOT NULL,
    action_name TEXT NOT NULL,
    meshy_anim_task_id TEXT,
    is_default_included INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS log_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_id INTEGER NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    stage_id INTEGER REFERENCES pipeline_stages(id),
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    context_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'global',
    PRIMARY KEY (key, scope)
);

CREATE INDEX IF NOT EXISTS idx_pipelines_status ON pipelines(status);
CREATE INDEX IF NOT EXISTS idx_pipelines_project ON pipelines(project_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_stages_pipeline ON pipeline_stages(pipeline_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_stages_name ON pipeline_stages(pipeline_id, stage_name, id DESC);
CREATE INDEX IF NOT EXISTS idx_external_jobs_pipeline ON external_jobs(pipeline_id);
CREATE INDEX IF NOT EXISTS idx_log_entries_pipeline ON log_entries(pipeline_id, id);
CREATE INDEX IF NOT EXISTS idx_log_entries_stage ON log_entries(stage_id);
CREATE INDEX IF NOT EXISTS idx_assets_pipeline ON assets(pipeline_id);
CREATE INDEX IF NOT EXISTS idx_assets_type ON assets(pipeline_id, asset_type);
