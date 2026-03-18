import json
import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.services.bootstrap import bootstrap_project


class ProjectsApiTest(unittest.TestCase):
    def _create_brownfield_repo(self, root):
        os.makedirs(os.path.join(root, "src"), exist_ok=True)
        os.makedirs(os.path.join(root, "tests"), exist_ok=True)
        with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as handle:
            handle.write("# Imported Repo\n\nExisting brownfield project.\n")
        with open(os.path.join(root, "pyproject.toml"), "w", encoding="utf-8") as handle:
            handle.write(
                """
[project]
name = "imported-repo"

[project.scripts]
lint = "imported:lint"
""".strip()
            )
        with open(os.path.join(root, "src", "app.py"), "w", encoding="utf-8") as handle:
            handle.write("print('hello')\n")
        with open(os.path.join(root, "tests", "test_app.py"), "w", encoding="utf-8") as handle:
            handle.write("def test_ok():\n    assert True\n")

    def test_projects_endpoint_lists_multiple_projects(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(tmpdir))

            response = client.post(
                "/api/projects",
                json={
                    "actor_id": "agent_allocator",
                    "name": "Second Project",
                    "description": "secondary",
                    "project_type": "custom",
                    "mode": "greenfield",
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = client.get("/api/projects").json()

            self.assertEqual(len(payload["projects"]), 2)
            self.assertEqual(payload["projects"][0]["name"], "Primary Project")
            self.assertEqual(payload["projects"][1]["name"], "Second Project")
            self.assertEqual(payload["projects"][1]["state"], "active")
            self.assertEqual(payload["projects"][1]["onboarding_mode"], "greenfield")

    def test_project_create_endpoint_imports_brownfield_repo_and_writes_project_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = os.path.join(tmpdir, "workspace")
            repo_root = os.path.join(tmpdir, "imported-repo")
            os.makedirs(workspace_root, exist_ok=True)
            os.makedirs(repo_root, exist_ok=True)
            self._create_brownfield_repo(repo_root)
            bootstrap_project(workspace_root, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(workspace_root))

            response = client.post(
                "/api/projects",
                json={
                    "actor_id": "agent_allocator",
                    "name": "Imported Repo",
                    "description": "brownfield import",
                    "project_type": "custom",
                    "mode": "auto",
                    "source_root": repo_root,
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            project_id = payload["project"]["project_id"]

            self.assertEqual(payload["mode"], "brownfield")
            self.assertEqual(payload["project"]["source_root"], os.path.abspath(repo_root))
            self.assertTrue(os.path.exists(payload["metadata"]["understanding_path"]))
            self.assertTrue(os.path.exists(payload["metadata"]["discovery_path"]))

            with open(payload["metadata"]["discovery_path"], "r", encoding="utf-8") as handle:
                discovery = json.load(handle)
            self.assertEqual(discovery["primary_language"], "python")
            self.assertTrue(any(item["name"] == "src" for item in discovery["codebase_map"]))

            overview_payload = client.get("/api/overview", params={"project_id": project_id}).json()
            self.assertEqual(overview_payload["project"]["name"], "Imported Repo")
            self.assertEqual(overview_payload["onboarding"]["mode"], "brownfield")
            self.assertEqual(overview_payload["onboarding"]["pending_gated_tasks"], 5)

    def test_core_read_models_can_be_scoped_to_selected_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(tmpdir))

            create_response = client.post(
                "/api/projects",
                json={
                    "actor_id": "agent_allocator",
                    "name": "Second Project",
                    "description": "secondary",
                    "project_type": "custom",
                    "mode": "greenfield",
                },
            )
            second_project_id = create_response.json()["project"]["project_id"]

            connection = connect(project_paths(tmpdir))
            try:
                agent_id = connection.execute(
                    "SELECT agent_id FROM agents WHERE project_id = ? AND role = 'allocator'",
                    (second_project_id,),
                ).fetchone()["agent_id"]
                task_id = connection.execute(
                    """
                    SELECT task_id
                    FROM tasks
                    WHERE project_id = ? AND title = 'Wire the scheduler and board read model'
                    """,
                    (second_project_id,),
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'in_progress',
                        assigned_agent_id = ?,
                        progress_pct = 30,
                        last_heartbeat_at = CURRENT_TIMESTAMP
                    WHERE task_id = ?
                    """,
                    (agent_id, task_id),
                )
                connection.execute(
                    """
                    INSERT INTO activity_log (
                        activity_id, project_id, agent_id, task_id, action, category, description, severity
                    ) VALUES ('act_second_project', ?, ?, ?, 'project_marker', 'steering', 'Second project activity marker', 'info')
                    """,
                    (second_project_id, agent_id, task_id),
                )
                connection.execute(
                    """
                    INSERT INTO alerts (
                        alert_id, project_id, severity, title, description, status
                    ) VALUES ('alert_second_project', ?, 'warning', 'Second project alert', 'Scoped alert', 'open')
                    """,
                    (second_project_id,),
                )
                connection.commit()
            finally:
                connection.close()

            overview_payload = client.get("/api/overview", params={"project_id": second_project_id}).json()
            board_payload = client.get("/api/board", params={"project_id": second_project_id}).json()
            live_payload = client.get("/api/live", params={"project_id": second_project_id}).json()
            activity_payload = client.get("/api/activity", params={"project_id": second_project_id}).json()

            self.assertEqual(overview_payload["project"]["name"], "Second Project")
            self.assertTrue(
                any(
                    task["title"] == "Wire the scheduler and board read model"
                    for column in board_payload["columns"]
                    for task in column["tasks"]
                )
            )
            self.assertEqual(live_payload["counts"]["alerts_open"], 2)
            self.assertTrue(any(item["description"] == "Second project activity marker" for item in activity_payload))

    def test_project_archive_and_restore_controls_selection_scope(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(tmpdir))
            second_project = client.post(
                "/api/projects",
                json={
                    "actor_id": "agent_allocator",
                    "name": "Second Project",
                    "description": "secondary",
                    "project_type": "custom",
                    "mode": "greenfield",
                },
            ).json()["project"]

            archive_response = client.post(
                "/api/projects/{0}/actions/archive".format(second_project["project_id"]),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(archive_response.status_code, 200)
            self.assertEqual(archive_response.json()["state"], "archived")

            projects_payload = client.get("/api/projects").json()["projects"]
            archived_project = next(project for project in projects_payload if project["project_id"] == second_project["project_id"])
            self.assertEqual(archived_project["state"], "archived")
            overview_response = client.get("/api/overview", params={"project_id": second_project["project_id"]})
            self.assertEqual(overview_response.status_code, 404)

            restore_response = client.post(
                "/api/projects/{0}/actions/restore".format(second_project["project_id"]),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(restore_response.status_code, 200)
            self.assertEqual(restore_response.json()["state"], "active")

    def test_last_active_project_cannot_be_archived(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(tmpdir))
            project_id = client.get("/api/projects").json()["projects"][0]["project_id"]

            response = client.post(
                "/api/projects/{0}/actions/archive".format(project_id),
                json={"actor_id": "agent_allocator"},
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("last active project", response.json()["detail"])

    def test_created_project_accepts_stable_operator_aliases_for_board_actions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(tmpdir))
            second_project_id = client.post(
                "/api/projects",
                json={
                    "actor_id": "agent_allocator",
                    "name": "Second Project",
                    "description": "secondary",
                    "project_type": "custom",
                    "mode": "greenfield",
                },
            ).json()["project"]["project_id"]

            connection = connect(project_paths(tmpdir))
            try:
                task_id = connection.execute(
                    """
                    SELECT task_id
                    FROM tasks
                    WHERE project_id = ?
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (second_project_id,),
                ).fetchone()["task_id"]
            finally:
                connection.close()

            response = client.post(
                "/api/tasks/{0}/actions/set-retry-limit".format(task_id),
                json={"actor_id": "agent_allocator", "auto_retry_limit": 2},
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["auto_retry_limit"], 2)

    def test_default_recovery_policy_scope_skips_archived_projects(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(tmpdir))
            second_project_id = client.post(
                "/api/projects",
                json={
                    "actor_id": "agent_allocator",
                    "name": "Second Project",
                    "description": "secondary",
                    "project_type": "custom",
                    "mode": "greenfield",
                },
            ).json()["project"]["project_id"]

            first_project_id = client.get("/api/projects").json()["projects"][0]["project_id"]
            connection = connect(project_paths(tmpdir))
            try:
                connection.execute(
                    """
                    UPDATE sessions
                    SET status = 'completed', ended_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                    WHERE project_id = ? AND status = 'active'
                    """,
                    (first_project_id,),
                )
                connection.commit()
            finally:
                connection.close()

            archive_response = client.post(
                "/api/projects/{0}/actions/archive".format(first_project_id),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(archive_response.status_code, 200)

            recovery_payload = client.get("/api/recovery-policy").json()
            self.assertEqual(recovery_payload["project_id"], second_project_id)
