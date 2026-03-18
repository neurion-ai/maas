CREATE TABLE IF NOT EXISTS provider_workers (
    worker_id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(project_id) ON DELETE SET NULL,
    provider_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('idle', 'busy', 'offline')),
    current_job_id TEXT REFERENCES provider_job_queue(job_id) ON DELETE SET NULL,
    last_job_id TEXT REFERENCES provider_job_queue(job_id) ON DELETE SET NULL,
    last_job_status TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    heartbeat_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_provider_workers_project_status
ON provider_workers(project_id, status, heartbeat_at DESC);

CREATE INDEX IF NOT EXISTS idx_provider_workers_provider_status
ON provider_workers(provider_id, status, heartbeat_at DESC);
