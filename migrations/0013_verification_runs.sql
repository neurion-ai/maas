CREATE TABLE IF NOT EXISTS verification_runs (
    verification_run_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    command TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('passed', 'failed', 'timed_out')),
    exit_code INTEGER,
    output_excerpt TEXT NOT NULL DEFAULT '',
    artifact_id TEXT REFERENCES artifacts(artifact_id) ON DELETE SET NULL,
    actor_id TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_verification_runs_task
ON verification_runs(project_id, task_id, finished_at);
