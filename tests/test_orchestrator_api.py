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
    def test_orchestrator_run_auto_launches_codex_work_when_requested(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(
                tmpdir,
                name="Orchestrator Codex Launch Test",
                description="orchestrator codex launch test",
                project_type="custom",
            )
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute(
                    "SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1"
                ).fetchone()["goal_id"]
                connection.execute("UPDATE tasks SET status = 'done', review_state = 'approved'")
                task_id = _insert_assigned_task(
                    connection,
                    project_id,
                    goal_id,
                    "agent_reviewer",
                    "Auto launch Codex work",
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.post(
                "/api/orchestrator/run",
                json={"allocate_limit": 0, "provider_job_limit": 2, "auto_launch_assigned_work": True},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["provider_jobs_queued"], 1)
            self.assertEqual(payload["provider_jobs_processed"], 1)
            self.assertTrue(
                any(
                    any(job["task_id"] == task_id and job["provider_id"] == "openai_codex" for job in project_run["queued_jobs"])
                    for project_run in payload["project_runs"]
                )
            )

            connection = connect(paths)
            try:
                job_row = connection.execute(
                    """
                    SELECT provider_id, status, session_id
                    FROM provider_job_queue
                    WHERE task_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (task_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(job_row["provider_id"], "openai_codex")
            self.assertEqual(job_row["status"], "completed")
            self.assertIsNotNone(job_row["session_id"])

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

    def test_orchestrator_honors_provider_queue_pause_and_limit_controls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Orchestrator Queue Controls Test",
                description="orchestrator queue control test",
                project_type="custom",
            )
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute(
                    "SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1"
                ).fetchone()["goal_id"]
                first_task_id = _insert_assigned_task(
                    connection,
                    project_id,
                    goal_id,
                    "agent_reviewer",
                    "Queued provider work one",
                )
                second_task_id = _insert_assigned_task(
                    connection,
                    project_id,
                    goal_id,
                    "agent_reviewer",
                    "Queued provider work two",
                )
                first_job = queue_provider_task(
                    connection,
                    paths,
                    provider_id="python_script",
                    actor_id="agent_allocator",
                    project_id=project_id,
                    agent_id="agent_reviewer",
                    task_id=first_task_id,
                )
                second_job = queue_provider_task(
                    connection,
                    paths,
                    provider_id="python_script",
                    actor_id="agent_allocator",
                    project_id=project_id,
                    agent_id="agent_reviewer",
                    task_id=second_task_id,
                )
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            paused_response = client.post(
                "/api/providers/python_script/actions/set-settings",
                json={"actor_id": "agent_allocator", "settings": {"queue_paused": True, "job_limit_per_pass": 1}},
            )
            self.assertEqual(paused_response.status_code, 200)

            paused_run = client.post(
                "/api/orchestrator/run",
                json={"allocate_limit": 2, "provider_job_limit": 3},
            ).json()
            self.assertEqual(paused_run["provider_jobs_processed"], 0)

            resumed_response = client.post(
                "/api/providers/python_script/actions/set-settings",
                json={"actor_id": "agent_allocator", "settings": {"queue_paused": False, "job_limit_per_pass": 1}},
            )
            self.assertEqual(resumed_response.status_code, 200)

            limited_run = client.post(
                "/api/orchestrator/run",
                json={"allocate_limit": 2, "provider_job_limit": 3},
            ).json()
            self.assertEqual(limited_run["provider_jobs_processed"], 1)

            connection = connect(paths)
            try:
                statuses = {
                    row["job_id"]: row["status"]
                    for row in connection.execute(
                        "SELECT job_id, status FROM provider_job_queue ORDER BY created_at ASC"
                    ).fetchall()
                }
            finally:
                connection.close()

            self.assertEqual(statuses[first_job["job_id"]], "completed")
            self.assertEqual(statuses[second_job["job_id"]], "queued")


if __name__ == "__main__":
    unittest.main()
