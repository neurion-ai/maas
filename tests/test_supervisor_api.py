import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect
from maas.services.bootstrap import bootstrap_project
from maas.supervisor import run_supervisor_once


class SupervisorApiTest(unittest.TestCase):
    def test_supervisor_refreshes_ready_tasks_and_allocates_idle_agents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Supervisor Test", description="Supervisor test", project_type="custom")
            connection = connect(result["paths"])
            try:
                supervisor_result = run_supervisor_once(connection)
                planned_task = connection.execute(
                    "SELECT status, assigned_agent_id FROM tasks WHERE title = 'Define project workspace contracts'"
                ).fetchone()
                ready_task = connection.execute(
                    "SELECT status, assigned_agent_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(supervisor_result["assigned_count"], 2)
            self.assertGreaterEqual(len(supervisor_result["ready_changes"]), 1)
            self.assertEqual(planned_task["status"], "assigned")
            self.assertEqual(planned_task["assigned_agent_id"], "agent_researcher")
            self.assertEqual(ready_task["status"], "assigned")
            self.assertEqual(ready_task["assigned_agent_id"], "agent_allocator")

    def test_supervisor_marks_stale_sessions_and_agents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor Stale Test",
                description="Supervisor stale test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                connection.execute(
                    """
                    UPDATE sessions
                    SET last_heartbeat_at = '2000-01-01 00:00:00'
                    WHERE status = 'active'
                    """
                )
                connection.commit()

                supervisor_result = run_supervisor_once(connection, stale_after_seconds=90, allocate_limit=0)
                session = connection.execute(
                    "SELECT status FROM sessions WHERE status = 'timed_out'"
                ).fetchone()
                task = connection.execute(
                    "SELECT status, review_state FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()
                agent = connection.execute(
                    "SELECT status, current_task_id FROM agents WHERE agent_id = 'agent_builder'"
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(len(supervisor_result["stale_sessions"]), 1)
            self.assertIsNotNone(session)
            self.assertEqual(task["status"], "blocked")
            self.assertEqual(task["review_state"], "stale_session")
            self.assertEqual(agent["status"], "error")
            self.assertIsNone(agent["current_task_id"])

    def test_supervisor_api_endpoint_runs_pass(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Supervisor API Test", description="Supervisor API test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            response = client.post("/api/supervisor/run", json={"allocate_limit": 1})
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertIn("ready_changes", payload)
            self.assertIn("allocations", payload)
            self.assertEqual(payload["assigned_count"], 1)


if __name__ == "__main__":
    unittest.main()
