import json
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.ids import generate_id
from maas.services.autopilot import _AUTOPILOT_THREADS
from maas.services.bootstrap import bootstrap_project
from maas.services.provider_runtime import queue_provider_task
from maas.services.security import TASK_EXECUTION_CAPABILITIES, grant_task_capabilities


class ProjectsApiTest(unittest.TestCase):
    def _insert_assigned_task(self, connection, project_id, goal_id, agent_id, title):
        task_id = generate_id("task")
        connection.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, goal_id, title, description, status, priority, assigned_agent_id, acceptance_criteria_json
            ) VALUES (?, ?, ?, ?, '', 'assigned', 70, ?, '[]')
            """,
            (task_id, project_id, goal_id, title, agent_id),
        )
        grant_task_capabilities(
            connection,
            project_id,
            task_id,
            agent_id,
            TASK_EXECUTION_CAPABILITIES,
            granted_by="test_setup",
        )
        return task_id

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

    def test_project_templates_are_listed_and_can_seed_project_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(tmpdir))

            templates_response = client.get("/api/projects/templates")
            self.assertEqual(templates_response.status_code, 200)
            templates_payload = templates_response.json()
            template_ids = {item["id"] for item in templates_payload["templates"]}
            self.assertIn("scratch-codex", template_ids)
            self.assertIn("import-codex", template_ids)
            self.assertIn("research-loop", template_ids)

            create_response = client.post(
                "/api/projects",
                json={
                    "actor_id": "agent_allocator",
                    "name": "Research Loop",
                    "description": "research template",
                    "project_type": "research",
                    "mode": "greenfield",
                    "template_id": "research-loop",
                },
            )
            self.assertEqual(create_response.status_code, 200)
            create_payload = create_response.json()
            self.assertEqual(create_payload["metadata"]["template_id"], "research-loop")
            self.assertTrue(create_payload["metadata"]["generated_source_root"])

            project_id = create_payload["project"]["project_id"]
            portfolio_payload = client.get("/api/portfolio").json()
            project_row = next(item for item in portfolio_payload["projects"] if item["project_id"] == project_id)
            self.assertEqual(project_row["provider_capacity"]["preferred_provider_id"], "openai_codex")
            self.assertEqual(project_row["provider_capacity"]["max_running_jobs"], 3)
            self.assertEqual(project_row["review_policy"]["max_priority_for_auto_approve"], 55)

    def test_update_autopilot_persists_and_status_endpoint_reflects_it(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            with TestClient(create_app(tmpdir)) as client:
                project_id = client.get("/api/projects").json()["projects"][0]["project_id"]

                response = client.post(
                    f"/api/projects/{project_id}/actions/update-autopilot",
                    json={
                        "actor_id": "agent_allocator",
                        "enabled": True,
                        "interval_seconds": 9,
                        "allocate_limit": 3,
                        "provider_job_limit": 2,
                        "auto_launch_assigned_work": True,
                        "process_notifications": False,
                        "notification_batch_limit": 1,
                        "schedule_window_start_hour_utc": 8,
                        "schedule_window_end_hour_utc": 18,
                        "stop_when_doctor_blocked": True,
                        "max_review_queue": 4,
                        "max_blocked_queue": 3,
                        "max_idle_cycles_before_alert": 7,
                        "max_stale_runs": 2,
                        "max_repeated_failure_incidents": 3,
                        "max_notification_failures": 4,
                    },
                )
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertTrue(payload["policy"]["enabled"])
                self.assertEqual(payload["policy"]["interval_seconds"], 9)
                self.assertEqual(payload["policy"]["allocate_limit"], 3)
                self.assertFalse(payload["policy"]["process_notifications"])
                self.assertEqual(payload["policy"]["schedule_window_start_hour_utc"], 8)
                self.assertEqual(payload["policy"]["max_review_queue"], 4)
                self.assertEqual(payload["policy"]["max_stale_runs"], 2)
                self.assertEqual(payload["policy"]["max_repeated_failure_incidents"], 3)
                self.assertEqual(payload["policy"]["max_notification_failures"], 4)

                status_response = client.get("/api/autopilot/status", params={"project_id": project_id})
                self.assertEqual(status_response.status_code, 200)
                status_payload = status_response.json()
                self.assertEqual(status_payload["project_id"], project_id)
                self.assertTrue(status_payload["policy"]["enabled"])
                self.assertEqual(status_payload["policy"]["interval_seconds"], 9)
                self.assertEqual(status_payload["policy"]["provider_job_limit"], 2)
                self.assertEqual(status_payload["policy"]["max_stale_runs"], 2)
                self.assertEqual(status_payload["policy"]["max_repeated_failure_incidents"], 3)
                self.assertEqual(status_payload["policy"]["max_notification_failures"], 4)
                self.assertFalse(status_payload["policy"]["process_notifications"])
                self.assertEqual(status_payload["policy"]["schedule_window_end_hour_utc"], 18)
                self.assertEqual(status_payload["policy"]["max_blocked_queue"], 3)
                self.assertTrue(status_payload["runtime"]["enabled"])

    def test_archiving_project_stops_autopilot_loop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(tmpdir))
            projects_payload = client.get("/api/projects").json()["projects"]
            project_id = projects_payload[0]["project_id"]
            connection = connect(project_paths(tmpdir))
            try:
                connection.execute("UPDATE tasks SET status = 'done', review_state = 'approved' WHERE project_id = ?", (project_id,))
                connection.execute(
                    "UPDATE sessions SET status = 'completed', ended_at = CURRENT_TIMESTAMP WHERE project_id = ? AND status = 'active'",
                    (project_id,),
                )
                connection.commit()
            finally:
                connection.close()

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
            self.assertEqual(create_response.status_code, 200)

            response = client.post(
                f"/api/projects/{project_id}/actions/update-autopilot",
                json={
                    "actor_id": "agent_allocator",
                    "enabled": True,
                    "interval_seconds": 9,
                    "allocate_limit": 2,
                    "provider_job_limit": 1,
                    "auto_launch_assigned_work": True,
                    "process_notifications": False,
                    "notification_batch_limit": 1,
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn((tmpdir, project_id), _AUTOPILOT_THREADS)

            archive_response = client.post(
                f"/api/projects/{project_id}/actions/archive",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(archive_response.status_code, 200)
            self.assertNotIn((tmpdir, project_id), _AUTOPILOT_THREADS)

    def test_greenfield_create_can_provision_a_fresh_workspace_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(tmpdir))

            response = client.post(
                "/api/projects",
                json={
                    "actor_id": "agent_allocator",
                    "name": "Fresh Workspace",
                    "description": "greenfield",
                    "project_type": "custom",
                    "mode": "greenfield",
                    "create_source_root": True,
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["metadata"]["generated_source_root"])
            self.assertTrue(os.path.isdir(payload["metadata"]["source_root"]))
            self.assertIn(os.path.join(tmpdir, "workspaces"), payload["metadata"]["source_root"])

    def test_delete_project_removes_generated_workspace_and_project_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(tmpdir))

            create_response = client.post(
                "/api/projects",
                json={
                    "actor_id": "agent_allocator",
                    "name": "Disposable Workspace",
                    "description": "greenfield",
                    "project_type": "custom",
                    "mode": "greenfield",
                    "create_source_root": True,
                },
            )
            self.assertEqual(create_response.status_code, 200)
            payload = create_response.json()
            project_id = payload["project"]["project_id"]
            source_root = payload["metadata"]["source_root"]

            delete_response = client.post(
                f"/api/projects/{project_id}/actions/delete",
                json={"actor_id": "agent_allocator"},
            )

            self.assertEqual(delete_response.status_code, 200)
            self.assertEqual(delete_response.json()["state"], "deleted")
            self.assertFalse(os.path.exists(source_root))

            projects_payload = client.get("/api/projects").json()
            self.assertFalse(any(project["project_id"] == project_id for project in projects_payload["projects"]))

    def test_clone_project_creates_a_fresh_workspace_copy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(tmpdir))

            create_response = client.post(
                "/api/projects",
                json={
                    "actor_id": "agent_allocator",
                    "name": "Fresh Workspace",
                    "description": "greenfield",
                    "project_type": "custom",
                    "mode": "greenfield",
                    "create_source_root": True,
                },
            )
            self.assertEqual(create_response.status_code, 200)
            created = create_response.json()
            project_id = created["project"]["project_id"]
            original_source_root = created["metadata"]["source_root"]

            clone_response = client.post(
                f"/api/projects/{project_id}/actions/clone",
                json={"actor_id": "agent_allocator", "name": "Fresh Workspace Clone"},
            )

            self.assertEqual(clone_response.status_code, 200)
            clone_payload = clone_response.json()
            self.assertEqual(clone_payload["project"]["name"], "Fresh Workspace Clone")
            self.assertNotEqual(clone_payload["project"]["project_id"], project_id)
            self.assertTrue(clone_payload["metadata"]["generated_source_root"])
            self.assertNotEqual(clone_payload["metadata"]["source_root"], original_source_root)
            self.assertEqual(clone_payload["metadata"]["cloned_from_project_id"], project_id)
            self.assertTrue(os.path.isdir(clone_payload["metadata"]["source_root"]))

    def test_clone_project_resets_brownfield_onboarding_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = os.path.join(tmpdir, "workspace")
            repo_root = os.path.join(tmpdir, "imported-repo")
            os.makedirs(workspace_root, exist_ok=True)
            os.makedirs(repo_root, exist_ok=True)
            self._create_brownfield_repo(repo_root)
            bootstrap_project(workspace_root, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(workspace_root))

            create_response = client.post(
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
            self.assertEqual(create_response.status_code, 200)
            source_project_id = create_response.json()["project"]["project_id"]

            connection = connect(project_paths(workspace_root))
            try:
                source_row = connection.execute(
                    "SELECT config_json FROM projects WHERE project_id = ?",
                    (source_project_id,),
                ).fetchone()
                source_config = json.loads(source_row["config_json"])
                onboarding = dict(source_config.get("onboarding") or {})
                onboarding.update(
                    {
                        "review_status": "approved",
                        "review_required": False,
                        "review_task_id": "task_stale_review",
                        "review_task_status": "done",
                        "review_task_review_state": "approved",
                        "pending_gated_tasks": 7,
                        "last_scanned_at": "2026-03-20T12:00:00Z",
                        "last_scanned_by": "agent_reviewer",
                        "drift_summary": {"detected": True},
                        "reviewed_by": "agent_reviewer",
                        "reviewed_at": "2026-03-20T12:00:00Z",
                    }
                )
                source_config["onboarding"] = onboarding
                connection.execute(
                    "UPDATE projects SET config_json = ? WHERE project_id = ?",
                    (json.dumps(source_config), source_project_id),
                )
                connection.commit()
            finally:
                connection.close()

            clone_response = client.post(
                f"/api/projects/{source_project_id}/actions/clone",
                json={"actor_id": "agent_allocator", "name": "Imported Repo Clone"},
            )
            self.assertEqual(clone_response.status_code, 200)
            clone_project_id = clone_response.json()["project"]["project_id"]

            connection = connect(project_paths(workspace_root))
            try:
                clone_row = connection.execute(
                    "SELECT config_json FROM projects WHERE project_id = ?",
                    (clone_project_id,),
                ).fetchone()
                clone_config = json.loads(clone_row["config_json"])
            finally:
                connection.close()

            clone_onboarding = clone_config["onboarding"]
            self.assertEqual(clone_onboarding["mode"], "brownfield")
            self.assertEqual(clone_onboarding["review_status"], "review_pending")
            self.assertTrue(clone_onboarding["review_required"])
            self.assertIsNone(clone_onboarding["review_task_id"])
            self.assertIsNone(clone_onboarding["review_task_status"])
            self.assertIsNone(clone_onboarding["review_task_review_state"])
            self.assertEqual(clone_onboarding["pending_gated_tasks"], 0)
            self.assertIsNone(clone_onboarding["last_scanned_at"])
            self.assertIsNone(clone_onboarding["last_scanned_by"])
            self.assertIsNone(clone_onboarding["drift_summary"])
            self.assertIsNone(clone_onboarding["reviewed_by"])
            self.assertIsNone(clone_onboarding["reviewed_at"])

    def test_clone_project_resets_live_control_posture(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(tmpdir))

            create_response = client.post(
                "/api/projects",
                json={
                    "actor_id": "agent_allocator",
                    "name": "Live Workspace",
                    "description": "live posture",
                    "project_type": "custom",
                    "mode": "greenfield",
                    "create_source_root": True,
                },
            )
            self.assertEqual(create_response.status_code, 200)
            source_project_id = create_response.json()["project"]["project_id"]

            connection = connect(project_paths(tmpdir))
            try:
                source_row = connection.execute(
                    "SELECT config_json FROM projects WHERE project_id = ?",
                    (source_project_id,),
                ).fetchone()
                source_config = json.loads(source_row["config_json"] or "{}")
                source_config["autopilot"] = {
                    **(source_config.get("autopilot") or {}),
                    "enabled": True,
                    "process_notifications": True,
                }
                source_config["provider_capacity"] = {
                    **(source_config.get("provider_capacity") or {}),
                    "queue_mode": "running",
                    "max_running_jobs": 3,
                    "preferred_provider_id": "openai_codex",
                }
                source_config["notifications"] = {
                    "webhook_urls": ["https://example.test/hooks/live"],
                    "minimum_severity": "warning",
                    "enabled_events": ["escalation_requested"],
                }
                connection.execute(
                    "UPDATE projects SET config_json = ? WHERE project_id = ?",
                    (json.dumps(source_config), source_project_id),
                )
                connection.commit()
            finally:
                connection.close()

            clone_response = client.post(
                f"/api/projects/{source_project_id}/actions/clone",
                json={"actor_id": "agent_allocator", "name": "Live Workspace Clone"},
            )
            self.assertEqual(clone_response.status_code, 200)
            clone_project_id = clone_response.json()["project"]["project_id"]

            connection = connect(project_paths(tmpdir))
            try:
                clone_row = connection.execute(
                    "SELECT config_json FROM projects WHERE project_id = ?",
                    (clone_project_id,),
                ).fetchone()
                clone_config = json.loads(clone_row["config_json"] or "{}")
            finally:
                connection.close()

            self.assertFalse((clone_config.get("autopilot") or {}).get("enabled"))
            self.assertEqual((clone_config.get("provider_capacity") or {}).get("queue_mode"), "paused")
            self.assertEqual((clone_config.get("provider_capacity") or {}).get("max_running_jobs"), 3)
            self.assertEqual((clone_config.get("provider_capacity") or {}).get("preferred_provider_id"), "openai_codex")
            self.assertEqual((clone_config.get("notifications") or {}).get("webhook_urls"), [])

    def test_delete_project_rejects_projects_with_queued_provider_jobs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(tmpdir))

            create_response = client.post(
                "/api/projects",
                json={
                    "actor_id": "agent_allocator",
                    "name": "Queued Workspace",
                    "description": "greenfield",
                    "project_type": "custom",
                    "mode": "greenfield",
                    "create_source_root": True,
                },
            )
            self.assertEqual(create_response.status_code, 200)
            payload = create_response.json()
            project_id = payload["project"]["project_id"]

            connection = connect(project_paths(tmpdir))
            try:
                goal_id = connection.execute(
                    "SELECT goal_id FROM goals WHERE project_id = ? ORDER BY created_at ASC LIMIT 1",
                    (project_id,),
                ).fetchone()["goal_id"]
                task_id = self._insert_assigned_task(
                    connection,
                    project_id,
                    goal_id,
                    "agent_reviewer",
                    "Queued provider work",
                )
                queue_provider_task(
                    connection,
                    project_paths(tmpdir),
                    provider_id="python_script",
                    actor_id="agent_allocator",
                    project_id=project_id,
                    agent_id="agent_reviewer",
                    task_id=task_id,
                )
                connection.commit()
            finally:
                connection.close()

            delete_response = client.post(
                f"/api/projects/{project_id}/actions/delete",
                json={"actor_id": "agent_allocator"},
            )

            self.assertEqual(delete_response.status_code, 400)
            self.assertEqual(
                delete_response.json()["detail"],
                "cannot delete a project with queued or running provider jobs",
            )

            projects_payload = client.get("/api/projects").json()
            self.assertTrue(any(project["project_id"] == project_id for project in projects_payload["projects"]))

    def test_system_pick_directory_endpoint_returns_native_picker_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(tmpdir))

            with patch("maas.api.pick_directory_via_native_dialog", return_value={"cancelled": False, "path": "/tmp/repo"}):
                response = client.post("/api/system/actions/pick-directory")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"cancelled": False, "path": "/tmp/repo"})

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

    def test_brownfield_rescan_reopens_review_when_repo_drift_is_detected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = os.path.join(tmpdir, "workspace")
            repo_root = os.path.join(tmpdir, "imported-repo")
            os.makedirs(workspace_root, exist_ok=True)
            os.makedirs(repo_root, exist_ok=True)
            self._create_brownfield_repo(repo_root)
            bootstrap_project(workspace_root, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(workspace_root))

            project_payload = client.post(
                "/api/projects",
                json={
                    "actor_id": "agent_allocator",
                    "name": "Imported Repo",
                    "description": "brownfield import",
                    "project_type": "custom",
                    "mode": "auto",
                    "source_root": repo_root,
                },
            ).json()
            project_id = project_payload["project"]["project_id"]

            connection = connect(project_paths(workspace_root))
            try:
                project_row = connection.execute(
                    "SELECT config_json FROM projects WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
                config = json.loads(project_row["config_json"] or "{}")
                config["onboarding"]["review_status"] = "approved"
                connection.execute(
                    "UPDATE projects SET config_json = ? WHERE project_id = ?",
                    (json.dumps(config), project_id),
                )
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'done',
                        review_state = 'approved',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE project_id = ? AND title = 'Review imported project understanding'
                    """,
                    (project_id,),
                )
                connection.execute(
                    """
                    UPDATE alerts
                    SET status = 'resolved'
                    WHERE project_id = ?
                      AND title = 'Brownfield onboarding review pending'
                    """,
                    (project_id,),
                )
                connection.commit()
            finally:
                connection.close()

            os.makedirs(os.path.join(repo_root, "docs"), exist_ok=True)
            with open(os.path.join(repo_root, "docs", "guide.md"), "w", encoding="utf-8") as handle:
                handle.write("# Drifted docs\n")

            response = client.post(
                f"/api/projects/{project_id}/actions/rescan-brownfield",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()

            self.assertTrue(payload["drift"]["detected"])
            self.assertEqual(payload["review_status"], "review_pending")
            self.assertEqual(payload["review_task_status"], "review")
            self.assertIn("docs", payload["drift"]["repo_areas_added"])

            overview_payload = client.get("/api/overview", params={"project_id": project_id}).json()
            self.assertEqual(overview_payload["onboarding"]["review_status"], "review_pending")
            self.assertTrue(overview_payload["onboarding"]["drift_summary"]["detected"])
            self.assertIn("docs", overview_payload["onboarding"]["drift_summary"]["repo_areas_added"])
            self.assertIsNotNone(overview_payload["onboarding"]["last_scanned_at"])

            connection = connect(project_paths(workspace_root))
            try:
                alert = connection.execute(
                    """
                    SELECT status
                    FROM alerts
                    WHERE project_id = ?
                      AND title = 'Brownfield onboarding review pending'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (project_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(alert["status"], "open")

    def test_update_onboarding_review_persists_overrides_and_reopens_review(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = os.path.join(tmpdir, "workspace")
            repo_root = os.path.join(tmpdir, "imported-repo")
            os.makedirs(workspace_root, exist_ok=True)
            os.makedirs(repo_root, exist_ok=True)
            self._create_brownfield_repo(repo_root)
            bootstrap_project(workspace_root, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(workspace_root))

            project_payload = client.post(
                "/api/projects",
                json={
                    "actor_id": "agent_allocator",
                    "name": "Imported Repo",
                    "description": "brownfield import",
                    "project_type": "custom",
                    "mode": "auto",
                    "source_root": repo_root,
                },
            ).json()
            project_id = project_payload["project"]["project_id"]

            response = client.post(
                f"/api/projects/{project_id}/actions/update-onboarding-review",
                json={
                    "actor_id": "agent_allocator",
                    "ignored_paths": ["tests"],
                    "accepted_workflow_labels": ["python_script:lint"],
                    "accepted_runbook_labels": ["python_script:lint"],
                },
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()

            self.assertEqual(payload["review_status"], "review_pending")
            self.assertEqual(payload["review_overrides"]["ignored_paths"], ["tests"])
            self.assertEqual(payload["review_overrides"]["accepted_workflow_labels"], ["python_script:lint"])
            self.assertEqual(payload["review_overrides"]["accepted_runbook_labels"], ["python_script:lint"])

            overview_payload = client.get("/api/overview", params={"project_id": project_id}).json()
            self.assertEqual(overview_payload["onboarding"]["review_status"], "review_pending")
            self.assertEqual(overview_payload["onboarding"]["review_overrides"]["ignored_paths"], ["tests"])

    def test_update_scheduler_policy_persists_and_is_visible_in_portfolio(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(tmpdir))
            project_id = client.get("/api/projects").json()["projects"][0]["project_id"]

            response = client.post(
                f"/api/projects/{project_id}/actions/update-scheduler-policy",
                json={
                    "actor_id": "agent_allocator",
                    "fair_share_weight": 3,
                    "max_active_sessions": 4,
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json()["scheduler_policy"],
                {"fair_share_weight": 3, "max_active_sessions": 4},
            )

            portfolio_payload = client.get("/api/portfolio").json()
            project_row = next(item for item in portfolio_payload["projects"] if item["project_id"] == project_id)
            self.assertEqual(project_row["scheduler_policy"]["fair_share_weight"], 3)
            self.assertEqual(project_row["scheduler_policy"]["max_active_sessions"], 4)
            self.assertFalse(project_row["at_scheduler_capacity"])

    def test_update_provider_capacity_persists_and_is_visible_in_portfolio(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(tmpdir))
            project_id = client.get("/api/projects").json()["projects"][0]["project_id"]

            response = client.post(
                f"/api/projects/{project_id}/actions/update-provider-capacity",
                json={
                    "actor_id": "agent_allocator",
                    "queue_mode": "draining",
                    "max_running_jobs": 1,
                    "preferred_provider_id": "python_script",
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json()["provider_capacity"],
                {"queue_mode": "draining", "max_running_jobs": 1, "preferred_provider_id": "python_script"},
            )

            portfolio_payload = client.get("/api/portfolio").json()
            project_row = next(item for item in portfolio_payload["projects"] if item["project_id"] == project_id)
            self.assertEqual(project_row["provider_capacity"]["queue_mode"], "draining")
            self.assertEqual(project_row["provider_capacity"]["max_running_jobs"], 1)
            self.assertEqual(project_row["provider_capacity"]["preferred_provider_id"], "python_script")

    def test_update_review_policy_persists_and_is_visible_in_portfolio(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(tmpdir))
            project_id = client.get("/api/projects").json()["projects"][0]["project_id"]

            response = client.post(
                f"/api/projects/{project_id}/actions/update-review-policy",
                json={
                    "actor_id": "agent_allocator",
                    "auto_approve_low_risk": False,
                    "max_priority_for_auto_approve": 55,
                    "require_verification_pass": True,
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json()["review_policy"],
                {
                    "auto_approve_low_risk": False,
                    "max_priority_for_auto_approve": 55,
                    "require_verification_pass": True,
                },
            )

            portfolio_payload = client.get("/api/portfolio").json()
            project_row = next(item for item in portfolio_payload["projects"] if item["project_id"] == project_id)
            self.assertEqual(project_row["review_policy"]["auto_approve_low_risk"], False)
            self.assertEqual(project_row["review_policy"]["max_priority_for_auto_approve"], 55)
            self.assertEqual(project_row["review_policy"]["require_verification_pass"], True)

    def test_update_review_policy_returns_403_for_unauthorized_actor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(tmpdir))
            project_id = client.get("/api/projects").json()["projects"][0]["project_id"]

            response = client.post(
                f"/api/projects/{project_id}/actions/update-review-policy",
                json={
                    "actor_id": "not_a_real_actor",
                    "auto_approve_low_risk": False,
                    "max_priority_for_auto_approve": 55,
                    "require_verification_pass": True,
                },
            )

            self.assertEqual(response.status_code, 403)

    def test_update_risk_policy_persists_and_is_visible_in_portfolio(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(tmpdir))
            project_id = client.get("/api/projects").json()["projects"][0]["project_id"]

            response = client.post(
                f"/api/projects/{project_id}/actions/update-risk-policy",
                json={
                    "actor_id": "agent_allocator",
                    "priority_threshold": 95,
                    "sensitive_path_prefixes": ["src/payments", "infra"],
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json()["risk_policy"],
                {"priority_threshold": 95, "sensitive_path_prefixes": ["src/payments", "infra"]},
            )

            portfolio_payload = client.get("/api/portfolio").json()
            project_row = next(item for item in portfolio_payload["projects"] if item["project_id"] == project_id)
            self.assertEqual(project_row["risk_policy"]["priority_threshold"], 95)
            self.assertEqual(project_row["risk_policy"]["sensitive_path_prefixes"], ["src/payments", "infra"])

    def test_update_runtime_quotas_persist_and_are_visible_in_portfolio(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(tmpdir))
            project_id = client.get("/api/projects").json()["projects"][0]["project_id"]

            response = client.post(
                f"/api/projects/{project_id}/actions/update-runtime-quotas",
                json={
                    "actor_id": "agent_allocator",
                    "daily_run_limit": 4,
                    "daily_live_run_limit": 2,
                    "daily_runtime_seconds_limit": 1800,
                    "max_task_session_attempts": 3,
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json()["runtime_quotas"],
                {
                    "daily_run_limit": 4,
                    "daily_live_run_limit": 2,
                    "daily_runtime_seconds_limit": 1800,
                    "max_task_session_attempts": 3,
                },
            )

            portfolio_payload = client.get("/api/portfolio").json()
            project_row = next(item for item in portfolio_payload["projects"] if item["project_id"] == project_id)
            self.assertEqual(project_row["runtime_quotas"]["daily_run_limit"], 4)
            self.assertEqual(project_row["runtime_quotas"]["daily_live_run_limit"], 2)
            self.assertEqual(project_row["runtime_quotas"]["daily_runtime_seconds_limit"], 1800)
            self.assertEqual(project_row["runtime_quotas"]["max_task_session_attempts"], 3)

    def test_update_notification_policy_persists_and_is_visible_in_portfolio(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(tmpdir))
            project_id = client.get("/api/projects").json()["projects"][0]["project_id"]

            response = client.post(
                f"/api/projects/{project_id}/actions/update-notification-policy",
                json={
                    "actor_id": "agent_allocator",
                    "webhook_urls": ["https://example.test/maas"],
                    "minimum_severity": "critical",
                    "enabled_events": ["escalation_requested", "circuit_breaker_opened"],
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json()["notification_policy"],
                {
                    "webhook_urls": ["https://example.test/maas"],
                    "minimum_severity": "critical",
                    "enabled_events": ["escalation_requested", "circuit_breaker_opened"],
                },
            )

            portfolio_payload = client.get("/api/portfolio").json()
            project_row = next(item for item in portfolio_payload["projects"] if item["project_id"] == project_id)
            self.assertEqual(project_row["notification_policy"]["webhook_urls"], ["https://example.test/maas"])
            self.assertEqual(project_row["notification_policy"]["minimum_severity"], "critical")

    def test_refresh_repo_plan_endpoint_preserves_progressed_synthesized_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_brownfield_repo(tmpdir)
            bootstrap_project(tmpdir, name="Repo Plan Refresh Test", description="repo plan refresh", project_type="custom")
            client = TestClient(create_app(tmpdir))

            overview_payload = client.get("/api/overview").json()
            project_id = overview_payload["project"]["project_id"]
            review_task_id = overview_payload["onboarding"]["review_task_id"]

            approve_response = client.post(
                f"/api/tasks/{review_task_id}/actions/review",
                json={"actor_id": "agent_reviewer", "decision": "approve"},
            )
            self.assertEqual(approve_response.status_code, 200)

            connection = connect(project_paths(tmpdir))
            try:
                synthesized_task_id = connection.execute(
                    """
                    SELECT task_id
                    FROM tasks
                    WHERE project_id = ?
                      AND synthesis_origin = 'repo_grounded_plan'
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (project_id,),
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'review',
                        review_state = 'awaiting_review',
                        description = 'operator-owned synthesized task'
                    WHERE task_id = ?
                    """,
                    (synthesized_task_id,),
                )
                connection.commit()
            finally:
                connection.close()

            refresh_response = client.post(
                f"/api/projects/{project_id}/actions/refresh-repo-plan",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(refresh_response.status_code, 200)
            payload = refresh_response.json()
            self.assertIn(synthesized_task_id, payload["skipped_task_ids"])
            self.assertGreater(payload["preview"]["generated_task_count"], 0)

            connection = connect(project_paths(tmpdir))
            try:
                task_row = connection.execute(
                    "SELECT status, description FROM tasks WHERE task_id = ?",
                    (synthesized_task_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(task_row["status"], "review")
            self.assertEqual(task_row["description"], "operator-owned synthesized task")

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
            portfolio_payload = client.get("/api/portfolio").json()["projects"]
            archived_portfolio_project = next(
                project for project in portfolio_payload if project["project_id"] == second_project["project_id"]
            )
            self.assertEqual(archived_portfolio_project["state"], "archived")
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
