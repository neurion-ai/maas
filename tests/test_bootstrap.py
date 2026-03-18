import os
import sqlite3
import tempfile
import unittest
import json

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
            self.assertEqual(result["mode"], "greenfield")

            connection = sqlite3.connect(result["paths"].db_path)
            project_count = connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
            task_count = connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            connection.close()

            self.assertEqual(project_count, 1)
            self.assertGreaterEqual(task_count, 6)

    def test_bootstrap_auto_detects_brownfield_and_imports_repo_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "tests"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "docs"), exist_ok=True)
            with open(os.path.join(tmpdir, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("# Example Project\n\nThis is an existing repo.\n")
            with open(os.path.join(tmpdir, "pyproject.toml"), "w", encoding="utf-8") as handle:
                handle.write(
                    """
[project]
name = "example-project"
requires-python = ">=3.11"

[project.scripts]
lint = "example:main"
""".strip()
                )
            with open(os.path.join(tmpdir, "Makefile"), "w", encoding="utf-8") as handle:
                handle.write("test:\n\tpytest\n")
            with open(os.path.join(tmpdir, "src", "app.py"), "w", encoding="utf-8") as handle:
                handle.write("print('hello')\n")
            with open(os.path.join(tmpdir, "tests", "test_app.py"), "w", encoding="utf-8") as handle:
                handle.write("def test_ok():\n    assert True\n")

            result = bootstrap_project(tmpdir, name="Imported Repo", description="Brownfield test", project_type="custom")

            self.assertEqual(result["mode"], "brownfield")
            self.assertTrue(os.path.exists(result["paths"].discovery_path))

            with open(result["paths"].discovery_path, "r", encoding="utf-8") as handle:
                discovery = json.load(handle)
            self.assertEqual(discovery["primary_language"], "python")
            self.assertIn("pyproject.toml", discovery["package_managers"])
            self.assertTrue(any(signal["name"] == "lint" for signal in discovery["workflow_signals"]))

            with open(result["paths"].understanding_path, "r", encoding="utf-8") as handle:
                understanding = handle.read()
            self.assertIn("Onboarding Mode: brownfield", understanding)
            self.assertIn("Example Project", understanding)

            connection = sqlite3.connect(result["paths"].db_path)
            try:
                task_titles = [
                    row[0]
                    for row in connection.execute(
                        "SELECT title FROM tasks ORDER BY priority DESC, title"
                    ).fetchall()
                ]
                session_count = connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                config_json = connection.execute("SELECT config_json FROM projects").fetchone()[0]
                blocked_gated_count = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM tasks
                    WHERE status = 'blocked' AND review_state = 'awaiting_onboarding_approval'
                    """
                ).fetchone()[0]
                map_task_description = connection.execute(
                    "SELECT description FROM tasks WHERE title = 'Map imported source area: src'"
                ).fetchone()[0]
                workflow_criteria_json = connection.execute(
                    "SELECT acceptance_criteria_json FROM tasks WHERE title = 'Validate imported workflow: test'"
                ).fetchone()[0]
                map_task_criteria_json = connection.execute(
                    "SELECT acceptance_criteria_json FROM tasks WHERE title = 'Map imported source area: src'"
                ).fetchone()[0]
            finally:
                connection.close()

            config = json.loads(config_json)
            workflow_criteria = json.loads(workflow_criteria_json)
            map_task_criteria = json.loads(map_task_criteria_json)
            workflow_paths = next(
                criterion["paths"]
                for criterion in workflow_criteria
                if criterion["type"] == "source_path_exists"
            )
            workflow_command = next(
                criterion["command"]
                for criterion in workflow_criteria
                if criterion["type"] == "test_passes"
            )
            map_task_paths = next(
                criterion["paths"]
                for criterion in map_task_criteria
                if criterion["type"] == "source_path_exists"
            )
            self.assertEqual(config["onboarding"]["mode"], "brownfield")
            self.assertEqual(config["onboarding"]["review_status"], "review_pending")
            self.assertEqual(session_count, 0)
            self.assertEqual(blocked_gated_count, 6)
            self.assertIn("python_script:lint", config["onboarding"]["discovery_summary"]["workflow_labels"])
            self.assertIn("make_target:test", config["onboarding"]["discovery_summary"]["workflow_labels"])
            self.assertEqual(
                config["onboarding"]["discovery_summary"]["workflow_details"][0]["path"],
                "pyproject.toml",
            )
            self.assertIn(
                "example:main",
                config["onboarding"]["discovery_summary"]["workflow_details"][0]["detail"],
            )
            self.assertIn("src", config["onboarding"]["discovery_summary"]["repo_areas"])
            self.assertEqual(
                config["onboarding"]["discovery_summary"]["codebase_map"][0]["name"],
                "src",
            )
            self.assertEqual(
                config["onboarding"]["discovery_summary"]["codebase_map"][0]["kind"],
                "source",
            )
            self.assertIn(
                "src/app.py",
                config["onboarding"]["discovery_summary"]["codebase_map"][0]["sample_files"],
            )
            self.assertEqual(
                config["onboarding"]["discovery_summary"]["codebase_map"][1]["kind"],
                "tests",
            )
            self.assertIn("Review imported project understanding", task_titles)
            self.assertIn("Validate imported workflow: lint", task_titles)
            self.assertIn("src/app.py", map_task_description)
            self.assertIn("Validate imported workflow: test", task_titles)
            self.assertIn("Map imported source area: src", task_titles)
            self.assertIn("Map imported test surface: tests", task_titles)
            self.assertIn("Align runtime and provider settings with existing tooling", task_titles)
            self.assertIn("Makefile", workflow_paths)
            self.assertEqual(workflow_command, "make test")
            self.assertIn("src/app.py", map_task_paths)

    def test_bootstrap_auto_detects_brownfield_from_hidden_repo_signals(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".github", "workflows"), exist_ok=True)
            with open(
                os.path.join(tmpdir, ".github", "workflows", "ci.yml"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("name: ci\n")

            result = bootstrap_project(
                tmpdir,
                name="Hidden Signal Repo",
                description="Hidden signal brownfield test",
                project_type="custom",
            )

            self.assertEqual(result["mode"], "brownfield")
            self.assertTrue(os.path.exists(result["paths"].discovery_path))

            with open(result["paths"].discovery_path, "r", encoding="utf-8") as handle:
                discovery = json.load(handle)
            self.assertTrue(
                any(item["path"] == ".github/workflows" for item in discovery["notable_files"])
            )
            self.assertTrue(
                any(signal.get("path") == ".github/workflows/ci.yml" for signal in discovery["workflow_signals"])
            )
            connection = sqlite3.connect(result["paths"].db_path)
            try:
                task_titles = [row[0] for row in connection.execute("SELECT title FROM tasks").fetchall()]
            finally:
                connection.close()
            self.assertIn("Validate imported workflow: ci", task_titles)

    def test_bootstrap_ignores_non_mapping_github_workflow_yaml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".github", "workflows"), exist_ok=True)
            with open(
                os.path.join(tmpdir, ".github", "workflows", "invalid.yml"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("- just\n- a\n- list\n")

            result = bootstrap_project(
                tmpdir,
                name="Non Mapping Workflow Repo",
                description="Non mapping workflow test",
                project_type="custom",
            )

            self.assertEqual(result["mode"], "brownfield")
            self.assertTrue(os.path.exists(result["paths"].discovery_path))

            with open(result["paths"].discovery_path, "r", encoding="utf-8") as handle:
                discovery = json.load(handle)
            self.assertTrue(
                any(signal.get("path") == ".github/workflows/invalid.yml" for signal in discovery["workflow_signals"])
            )
            self.assertEqual(discovery["codebase_map"][0]["name"], ".github")
            self.assertEqual(discovery["codebase_map"][0]["kind"], "automation")

    def test_bootstrap_keeps_top_level_directories_when_root_files_dominate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
            with open(os.path.join(tmpdir, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("# Root-heavy repo\n")
            for index in range(5):
                with open(os.path.join(tmpdir, "file{0}.txt".format(index)), "w", encoding="utf-8") as handle:
                    handle.write("root file {0}\n".format(index))
            with open(os.path.join(tmpdir, "src", "app.py"), "w", encoding="utf-8") as handle:
                handle.write("print('hello')\n")

            result = bootstrap_project(
                tmpdir,
                name="Root Heavy Repo",
                description="Top-level directory ranking test",
                project_type="custom",
            )

            with open(result["paths"].discovery_path, "r", encoding="utf-8") as handle:
                discovery = json.load(handle)

            self.assertTrue(any(item["name"] == "src" for item in discovery["top_level_dirs"]))

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
