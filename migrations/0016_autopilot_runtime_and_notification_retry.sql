CREATE TABLE IF NOT EXISTS autopilot_runtime (
    project_id TEXT PRIMARY KEY REFERENCES projects(project_id) ON DELETE CASCADE,
    lease_token TEXT,
    lease_owner TEXT,
    lease_acquired_at TEXT,
    lease_expires_at TEXT,
    last_heartbeat_at TEXT,
    last_summary_json TEXT NOT NULL DEFAULT '{}',
    last_error TEXT,
    loop_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'idle' CHECK (status IN ('idle', 'running', 'waiting', 'stopped', 'error')),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_autopilot_runtime_lease_expires
ON autopilot_runtime(lease_expires_at);

ALTER TABLE notification_outbox ADD COLUMN dedupe_key TEXT;
ALTER TABLE notification_outbox ADD COLUMN next_attempt_at TEXT;
ALTER TABLE notification_outbox ADD COLUMN last_attempt_at TEXT;

UPDATE notification_outbox
SET dedupe_key = notification_id
WHERE dedupe_key IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_outbox_active_dedupe
ON notification_outbox(dedupe_key)
WHERE dedupe_key IS NOT NULL AND status IN ('queued', 'failed');

CREATE INDEX IF NOT EXISTS idx_notification_outbox_status_next_attempt
ON notification_outbox(status, next_attempt_at, created_at DESC);
