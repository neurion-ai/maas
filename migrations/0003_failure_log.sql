CREATE TABLE IF NOT EXISTS failure_log (
    failure_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    session_id TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
    agent_id TEXT REFERENCES agents(agent_id) ON DELETE SET NULL,
    failure_type TEXT NOT NULL CHECK (failure_type IN (
        'session_failed',
        'session_timed_out',
        'session_cancelled',
        'capability_denied'
    )),
    summary TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_failure_log_task_created
ON failure_log(task_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_failure_log_project_created
ON failure_log(project_id, created_at DESC);
