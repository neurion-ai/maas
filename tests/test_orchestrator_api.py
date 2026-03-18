import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.ids import generate_id
from maas.services.bootstrap import bootstrap_project
from maas.services.provider_runtime import queue_provider_task
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


class OrchestratorApiTest(unittest.TestCase):
    def test_orchestrator_run_processes_provider_jobs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Orchestrator Test",
                description="orchestrator test",
                project_type="custom",
            )
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute(
                    "SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1"
                ).fetchone()["goal_id"]
                task_id = _insert_assigned_task(
                    connection,
                    project_id,
                    goal_id,
                    "agent_reviewer",
                    "Queued provider work for orchestrator",
                )
                queued_job = queue_provider_task(
                    connection,
                    paths,
                    provider_id="python_script",
                    actor_id="agent_allocator",
                    project_id=project_id,
                    agent_id="agent_reviewer",
                    task_id=task_id,
                )
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.post(
                "/api/orchestrator/run",
                json={"allocate_limit": 2, "provider_job_limit": 2},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["provider_jobs_processed"], 1)
            self.assertTrue(
                any(
                    any(job["job_id"] == queued_job["job_id"] for job in project_run["processed_jobs"])
                    for project_run in payload["project_runs"]
                )
            )

            connection = connect(paths)
            try:
                job_row = connection.execute(
                    "SELECT status, session_id FROM provider_job_queue WHERE job_id = ?",
                    (queued_job["job_id"],),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(job_row["status"], "completed")
            self.assertIsNotNone(job_row["session_id"])


if __name__ == "__main__":
    unittest.main()
