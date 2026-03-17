ALTER TABLE projects ADD COLUMN state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'archived'));
ALTER TABLE projects ADD COLUMN archived_at TEXT;
ALTER TABLE projects ADD COLUMN source_root TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_projects_state ON projects(state);
