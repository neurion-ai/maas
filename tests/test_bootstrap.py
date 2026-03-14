import os
import sqlite3
import tempfile
import unittest

from maas.db import connect, ensure_meta_tables, migration_dir, run_migrations
from maas.paths import ProjectPaths
from maas.services.lifecycle import heartbeat
from maas.services.bootstrap import bootstrap_project


class BootstrapProjectTest(unittest.TestCase):
    def test_bootstrap_creates_config_workspace_and_seeded_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Test MAAS", description="Bootstrap test", project_type="custom")
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "project.yaml")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, ".maas", "state.db")))
            self.assertTrue(os.path.exists(result["paths"].understanding_path))

            connection = sqlite3.connect(result["paths"].db_path)
            project_count = connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
            task_count = connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            connection.close()

            self.assertEqual(project_count, 1)
            self.assertGreaterEqual(task_count, 6)

    def test_migration_backfills_capabilities_for_existing_active_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = ProjectPaths(tmpdir)
            paths.ensure_directories()

            bootstrap_db = sqlite3.connect(paths.db_path)
            try:
                ensure_meta_tables(bootstrap_db)
                with open(
                    os.path.join(migration_dir(tmpdir), "0001_initial.sql"),
                    "r",
                    encoding="utf-8",
                ) as handle:
                    bootstrap_db.executescript(handle.read())
                bootstrap_db.execute("INSERT INTO schema_migrations (version) VALUES ('0001_initial.sql')")
                bootstrap_db.execute(
                    """
                    INSERT INTO projects (project_id, name, description, project_type, config_json)
                    VALUES ('proj_legacy', 'Legacy Project', 'legacy', 'custom', '{}')
                    """
                )
                bootstrap_db.execute(
                    """
                    INSERT INTO agents (
                        agent_id, project_id, role, display_name, status, current_task_id, permissions_json, last_heartbeat_at
                    ) VALUES (
                        'agent_builder', 'proj_legacy', 'builder', 'Builder', 'running', 'task_active', '{}', CURRENT_TIMESTAMP
                    )
                    """
                )
                bootstrap_db.execute(
                    """
                    INSERT INTO tasks (
                        task_id, project_id, title, description, status, priority, assigned_agent_id,
                        acceptance_criteria_json, progress_pct, last_heartbeat_at
                    ) VALUES (
                        'task_active', 'proj_legacy', 'Legacy task', 'pre-0002 task', 'in_progress', 80,
                        'agent_builder', '[]', 40, CURRENT_TIMESTAMP
                    )
                    """
                )
                bootstrap_db.execute(
                    """
                    INSERT INTO sessions (
                        session_id, project_id, agent_id, task_id, status, provider_type,
                        progress_pct, status_message, last_heartbeat_at
                    ) VALUES (
                        'sess_legacy', 'proj_legacy', 'agent_builder', 'task_active', 'active',
                        'python_script', 40, 'Legacy in-flight session', CURRENT_TIMESTAMP
                    )
                    """
                )
                bootstrap_db.commit()
            finally:
                bootstrap_db.close()

            run_migrations(tmpdir, paths)

            connection = connect(paths)
            try:
                grant_count = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM task_capability_grants
                    WHERE task_id = 'task_active'
                      AND agent_id = 'agent_builder'
                      AND revoked_at IS NULL
                    """
                ).fetchone()["count"]
                heartbeat(connection, "sess_legacy", 55, "Post-migration heartbeat")
                task_progress = connection.execute(
                    "SELECT progress_pct FROM tasks WHERE task_id = 'task_active'"
                ).fetchone()["progress_pct"]
            finally:
                connection.close()

            self.assertEqual(grant_count, 5)
            self.assertEqual(task_progress, 55)


if __name__ == "__main__":
    unittest.main()
