CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    project_type TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS goals (
    goal_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    parent_goal_id TEXT REFERENCES goals(goal_id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('proposed', 'approved', 'active', 'blocked', 'completed', 'failed', 'abandoned')),
    goal_type TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 50,
    acceptance_criteria_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('idle', 'running', 'paused', 'error', 'disabled')),
    current_task_id TEXT,
    permissions_json TEXT NOT NULL DEFAULT '{}',
    last_heartbeat_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    goal_id TEXT REFERENCES goals(goal_id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('planned', 'ready', 'assigned', 'in_progress', 'review', 'blocked', 'done', 'cancelled')),
    priority INTEGER NOT NULL DEFAULT 50,
    assigned_agent_id TEXT REFERENCES agents(agent_id) ON DELETE SET NULL,
    acceptance_criteria_json TEXT NOT NULL DEFAULT '[]',
    progress_pct INTEGER NOT NULL DEFAULT 0,
    review_state TEXT,
    last_heartbeat_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS task_dependencies (
    dependency_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    source_task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    target_task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    dependency_type TEXT NOT NULL CHECK (dependency_type IN ('blocks', 'informs', 'conflicts')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'completed', 'failed', 'timed_out', 'cancelled')),
    provider_type TEXT NOT NULL,
    progress_pct INTEGER NOT NULL DEFAULT 0,
    status_message TEXT NOT NULL DEFAULT '',
    last_heartbeat_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    session_id TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
    artifact_type TEXT NOT NULL,
    path TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS activity_log (
    activity_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    agent_id TEXT REFERENCES agents(agent_id) ON DELETE SET NULL,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'acknowledged', 'resolved')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_trail (
    audit_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    actor_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_goal ON tasks(goal_id);
CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
