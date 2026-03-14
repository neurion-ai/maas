import json
import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.ids import generate_id
from maas.services.bootstrap import bootstrap_project
from maas.services.security import TASK_EXECUTION_CAPABILITIES, grant_task_capabilities


def _insert_assigned_task(connection, project_id, goal_id, agent_id, title):
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


class ProviderRuntimeTest(unittest.TestCase):
    def test_providers_endpoint_reports_runtime_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Endpoint Test", description="Provider endpoint test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            payload = client.get("/api/providers").json()
            provider_ids = {provider["id"] for provider in payload["providers"]}

            self.assertEqual(provider_ids, {"python_script", "claude_code", "openai_codex"})
            self.assertTrue(all(provider["supports_worker_execution"] for provider in payload["providers"]))
            self.assertTrue(all(provider["execution_mode"] == "local_simulation" for provider in payload["providers"]))

    def test_provider_run_task_executes_each_adapter_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Runtime Test", description="Provider runtime test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                provider_tasks = {
                    "python_script": _insert_assigned_task(
                        connection, project_id, goal_id, "agent_allocator", "Run Python Script adapter"
                    ),
                    "claude_code": _insert_assigned_task(
                        connection, project_id, goal_id, "agent_researcher", "Run Claude Code adapter"
                    ),
                    "openai_codex": _insert_assigned_task(
                        connection, project_id, goal_id, "agent_reviewer", "Run OpenAI Codex adapter"
                    ),
                }
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            agent_by_provider = {
                "python_script": "agent_allocator",
                "claude_code": "agent_researcher",
                "openai_codex": "agent_reviewer",
            }

            for provider_id, task_id in provider_tasks.items():
                response = client.post(
                    "/api/providers/{0}/actions/run-task".format(provider_id),
                    json={
                        "project_id": project_id,
                        "agent_id": agent_by_provider[provider_id],
                        "task_id": task_id,
                    },
                )
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["provider"]["id"], provider_id)

            connection = connect(project_paths(tmpdir))
            try:
                for provider_id, task_id in provider_tasks.items():
                    session = connection.execute(
                        """
                        SELECT provider_type, status
                        FROM sessions
                        WHERE task_id = ?
                        ORDER BY started_at DESC
                        LIMIT 1
                        """,
                        (task_id,),
                    ).fetchone()
                    task = connection.execute(
                        "SELECT status FROM tasks WHERE task_id = ?",
                        (task_id,),
                    ).fetchone()
                    artifact = connection.execute(
                        """
                        SELECT artifact_type, metadata_json
                        FROM artifacts
                        WHERE task_id = ?
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        (task_id,),
                    ).fetchone()
                    activity_count = connection.execute(
                        """
                        SELECT COUNT(*) AS count
                        FROM activity_log
                        WHERE task_id = ? AND action IN ('provider_adapter_started', 'provider_adapter_completed')
                        """,
                        (task_id,),
                    ).fetchone()["count"]

                    self.assertEqual(session["provider_type"], provider_id)
                    self.assertEqual(session["status"], "completed")
                    self.assertEqual(task["status"], "review")
                    self.assertEqual(json.loads(artifact["metadata_json"])["provider_type"], provider_id)
                    self.assertGreaterEqual(activity_count, 2)
            finally:
                connection.close()

    def test_lifecycle_start_rejects_unknown_provider(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Validation Test", description="Provider validation test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE status = 'ready' LIMIT 1"
                ).fetchone()["task_id"]
            finally:
                connection.close()

            response = client.post(
                "/api/lifecycle/start",
                json={
                    "project_id": project_id,
                    "agent_id": "agent_allocator",
                    "task_id": task_id,
                    "provider_type": "unknown_provider",
                    "status_message": "test",
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("Unsupported provider type", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
