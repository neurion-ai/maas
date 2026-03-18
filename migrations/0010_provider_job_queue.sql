CREATE TABLE IF NOT EXISTS provider_job_queue (
    job_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    provider_id TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    queued_by TEXT NOT NULL,
    worker_id TEXT,
    artifact_path TEXT,
    session_id TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
    artifact_id TEXT REFERENCES artifacts(artifact_id) ON DELETE SET NULL,
    result_json TEXT NOT NULL DEFAULT '{}',
    error_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_provider_job_queue_project_status_created
ON provider_job_queue(project_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_provider_job_queue_provider_status_created
ON provider_job_queue(provider_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_provider_job_queue_task_status
ON provider_job_queue(task_id, status);
