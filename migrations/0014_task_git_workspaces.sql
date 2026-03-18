CREATE TABLE IF NOT EXISTS task_git_workspaces (
    workspace_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    task_id TEXT NOT NULL UNIQUE REFERENCES tasks(task_id) ON DELETE CASCADE,
    repo_root TEXT NOT NULL,
    branch_name TEXT NOT NULL,
    worktree_path TEXT NOT NULL,
    base_ref TEXT,
    head_commit TEXT,
    dirty_file_count INTEGER NOT NULL DEFAULT 0,
    change_summary TEXT,
    last_diff_artifact_id TEXT REFERENCES artifacts(artifact_id),
    prepared_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_task_git_workspaces_project
ON task_git_workspaces(project_id, updated_at DESC);
