CREATE TABLE IF NOT EXISTS dead_letter_queue (
    dlq_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    failure_id TEXT REFERENCES failure_log(failure_id) ON DELETE SET NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
    detail_json TEXT NOT NULL DEFAULT '{}',
    resolution_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_dead_letter_queue_project_status_created
ON dead_letter_queue(project_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_dead_letter_queue_task_status
ON dead_letter_queue(task_id, status);
