ALTER TABLE tasks ADD COLUMN synthesis_origin TEXT;
ALTER TABLE tasks ADD COLUMN synthesis_key TEXT;

CREATE INDEX IF NOT EXISTS idx_tasks_synthesis_origin
ON tasks(project_id, synthesis_origin, synthesis_key);
