ALTER TABLE tasks ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN auto_retry_limit INTEGER;
ALTER TABLE tasks ADD COLUMN last_retry_at TEXT;
ALTER TABLE tasks ADD COLUMN last_retry_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_tasks_retry_state
ON tasks(status, retry_count, last_retry_at);
