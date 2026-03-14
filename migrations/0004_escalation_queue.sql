CREATE TABLE IF NOT EXISTS escalation_queue (
    escalation_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    requested_by TEXT NOT NULL,
    action_type TEXT NOT NULL CHECK (action_type IN (
        'halt_task',
        'reassign_task',
        'pause_agent',
        'resume_agent'
    )),
    resource_type TEXT NOT NULL CHECK (resource_type IN ('task', 'agent')),
    resource_id TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('open', 'approved', 'rejected')),
    resolved_by TEXT,
    resolution_note TEXT,
    resolved_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_escalation_queue_status_created
ON escalation_queue(status, created_at DESC);
