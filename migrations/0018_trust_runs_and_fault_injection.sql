CREATE TABLE IF NOT EXISTS trust_runs (
    trust_run_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    actor_id TEXT NOT NULL,
    profile TEXT NOT NULL DEFAULT 'default',
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
    cycle_limit INTEGER NOT NULL DEFAULT 6,
    completed_cycles INTEGER NOT NULL DEFAULT 0,
    sleep_seconds INTEGER NOT NULL DEFAULT 0,
    config_json TEXT NOT NULL DEFAULT '{}',
    summary_json TEXT NOT NULL DEFAULT '{}',
    report_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TEXT,
    last_cycle_started_at TEXT,
    last_cycle_finished_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_trust_runs_project_started
ON trust_runs(project_id, started_at DESC);

CREATE TABLE IF NOT EXISTS fault_injections (
    injection_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    trust_run_id TEXT REFERENCES trust_runs(trust_run_id) ON DELETE CASCADE,
    cycle_index INTEGER,
    domain TEXT NOT NULL,
    action TEXT NOT NULL,
    target_resource_type TEXT,
    target_resource_id TEXT,
    mode TEXT NOT NULL DEFAULT 'once' CHECK (mode IN ('once', 'persistent')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('scheduled', 'pending', 'applied', 'skipped')),
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    applied_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_fault_injections_project_status
ON fault_injections(project_id, status, cycle_index, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_fault_injections_trust_run
ON fault_injections(trust_run_id, cycle_index, status, created_at DESC);

CREATE TABLE IF NOT EXISTS trust_run_incidents (
    replay_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    trust_run_id TEXT NOT NULL REFERENCES trust_runs(trust_run_id) ON DELETE CASCADE,
    incident_kind TEXT NOT NULL,
    incident_key TEXT NOT NULL,
    source_type TEXT,
    source_id TEXT,
    summary TEXT NOT NULL,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    replay_payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_trust_run_incidents_unique
ON trust_run_incidents(trust_run_id, incident_key);

CREATE INDEX IF NOT EXISTS idx_trust_run_incidents_project_created
ON trust_run_incidents(project_id, created_at DESC);
