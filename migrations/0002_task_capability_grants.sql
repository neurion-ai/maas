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

WITH execution_targets AS (
    SELECT DISTINCT project_id, task_id, assigned_agent_id AS agent_id
    FROM tasks
    WHERE assigned_agent_id IS NOT NULL
      AND status IN ('planned', 'ready', 'assigned', 'in_progress', 'blocked')

    UNION

    SELECT DISTINCT project_id, task_id, agent_id
    FROM sessions
    WHERE status = 'active'
      AND task_id IS NOT NULL
),
capabilities(capability) AS (
    VALUES
        ('execute'),
        ('heartbeat'),
        ('activity_write'),
        ('artifact_write'),
        ('complete_session')
)
INSERT INTO task_capability_grants (
    grant_id,
    project_id,
    task_id,
    agent_id,
    capability,
    granted_by
)
SELECT
    'grant_backfill_' || lower(hex(randomblob(8))),
    execution_targets.project_id,
    execution_targets.task_id,
    execution_targets.agent_id,
    capabilities.capability,
    'system_migration'
FROM execution_targets
CROSS JOIN capabilities
WHERE NOT EXISTS (
    SELECT 1
    FROM task_capability_grants existing
    WHERE existing.project_id = execution_targets.project_id
      AND existing.task_id = execution_targets.task_id
      AND existing.agent_id = execution_targets.agent_id
      AND existing.capability = capabilities.capability
      AND existing.revoked_at IS NULL
);
