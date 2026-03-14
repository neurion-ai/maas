CREATE TABLE IF NOT EXISTS task_capability_grants (
    grant_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    capability TEXT NOT NULL CHECK (capability IN (
        'execute',
        'heartbeat',
        'activity_write',
        'artifact_write',
        'complete_session'
    )),
    granted_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TEXT,
    revoked_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_task_capability_grants_active
ON task_capability_grants(task_id, agent_id, capability, revoked_at);
