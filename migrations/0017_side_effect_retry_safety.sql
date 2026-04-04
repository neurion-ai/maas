ALTER TABLE notification_outbox ADD COLUMN processing_token TEXT;
ALTER TABLE notification_outbox ADD COLUMN processing_started_at TEXT;

CREATE INDEX IF NOT EXISTS idx_notification_outbox_processing
ON notification_outbox(processing_token, processing_started_at);

ALTER TABLE task_git_workspaces ADD COLUMN prepare_state TEXT NOT NULL DEFAULT 'ready';
ALTER TABLE task_git_workspaces ADD COLUMN prepare_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE task_git_workspaces ADD COLUMN last_prepare_error TEXT;
ALTER TABLE task_git_workspaces ADD COLUMN last_prepare_started_at TEXT;
ALTER TABLE task_git_workspaces ADD COLUMN last_prepare_finished_at TEXT;
ALTER TABLE task_git_workspaces ADD COLUMN last_prepare_mode TEXT;

UPDATE task_git_workspaces
SET prepare_state = COALESCE(prepare_state, 'ready'),
    prepare_attempts = CASE
        WHEN prepare_attempts IS NULL OR prepare_attempts = 0 THEN 1
        ELSE prepare_attempts
    END,
    last_prepare_finished_at = COALESCE(last_prepare_finished_at, updated_at, prepared_at),
    last_prepare_mode = COALESCE(last_prepare_mode, 'prepared')
WHERE prepare_state IS NULL
   OR prepare_attempts IS NULL
   OR last_prepare_finished_at IS NULL
   OR last_prepare_mode IS NULL;

CREATE INDEX IF NOT EXISTS idx_task_git_workspaces_prepare_state
ON task_git_workspaces(project_id, prepare_state, updated_at DESC);
