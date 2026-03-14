CREATE TABLE IF NOT EXISTS quarantine_queue (
    queue_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    session_id TEXT NOT NULL UNIQUE REFERENCES sessions(session_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    failure_id TEXT REFERENCES failure_log(failure_id) ON DELETE SET NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'restored', 'dismissed')) DEFAULT 'open',
    reason TEXT NOT NULL DEFAULT '',
    artifact_count INTEGER NOT NULL DEFAULT 0,
    resolution_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_quarantine_queue_project_status
ON quarantine_queue(project_id, status, created_at DESC);
