import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect
from maas.services.bootstrap import bootstrap_project
from maas.services.scheduler import allocate_ready_tasks, assign_next_task


class AllocatorApiTest(unittest.TestCase):
    def test_allocate_ready_tasks_assigns_idle_agents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Allocator Test", description="Allocator test", project_type="custom")
            connection = connect(result["paths"])
            try:
                allocation_result = allocate_ready_tasks(connection, actor_id="system_allocator")
                researcher_task = connection.execute(
                    "SELECT status, assigned_agent_id FROM tasks WHERE title = 'Define project workspace contracts'"
                ).fetchone()
                allocator_task = connection.execute(
                    "SELECT status, assigned_agent_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(allocation_result["assigned_count"], 2)
            self.assertEqual(researcher_task["status"], "assigned")
            self.assertEqual(researcher_task["assigned_agent_id"], "agent_researcher")
            self.assertEqual(allocator_task["status"], "assigned")
            self.assertEqual(allocator_task["assigned_agent_id"], "agent_allocator")

    def test_allocator_api_endpoints_assign_tasks_and_reject_busy_agents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Allocator API Test", description="Allocator API test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            allocate_response = client.post("/api/tasks/actions/allocate-ready", json={"actor_id": "system_allocator"})
            self.assertEqual(allocate_response.status_code, 200)
            self.assertEqual(allocate_response.json()["assigned_count"], 2)

            assign_busy_response = client.post(
                "/api/agents/agent_builder/actions/assign-next",
                json={"actor_id": "operator_1"},
            )
            self.assertEqual(assign_busy_response.status_code, 400)
            self.assertIn("not idle", assign_busy_response.json()["detail"])

    def test_assign_next_task_returns_none_when_no_work_is_available(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Allocator Empty Test", description="Allocator empty test", project_type="custom")
            connection = connect(result["paths"])
            try:
                connection.execute(
                    "UPDATE tasks SET status = 'done' WHERE status IN ('planned', 'ready', 'assigned')"
                )
                connection.commit()
                result_payload = assign_next_task(connection, "agent_researcher", actor_id="system_allocator")
            finally:
                connection.close()

            self.assertFalse(result_payload["assigned"])
            self.assertIsNone(result_payload["task_id"])

    def test_assign_next_task_prioritizes_reserved_ready_task_for_same_agent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Allocator Sticky Test",
                description="Allocator sticky test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                reserved_task = connection.execute(
                    "SELECT task_id, title FROM tasks WHERE title = 'Define project workspace contracts'"
                ).fetchone()
                higher_priority_task = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'ready', assigned_agent_id = 'agent_researcher'
                    WHERE task_id = ?
                    """,
                    (reserved_task["task_id"],),
                )
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'ready', assigned_agent_id = NULL, priority = 99
                    WHERE task_id = ?
                    """,
                    (higher_priority_task["task_id"],),
                )
                connection.commit()

                result_payload = assign_next_task(connection, "agent_researcher", actor_id="system_allocator")
            finally:
                connection.close()

            self.assertTrue(result_payload["assigned"])
            self.assertEqual(result_payload["task_id"], reserved_task["task_id"])

    def test_allocate_ready_tasks_respects_zero_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Allocator Limit Test",
                description="Allocator limit test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                result_payload = allocate_ready_tasks(connection, actor_id="system_allocator", limit=0)
                assigned_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM tasks WHERE status = 'assigned'"
                ).fetchone()["count"]
            finally:
                connection.close()

            self.assertEqual(result_payload["assigned_count"], 0)
            self.assertEqual(result_payload["allocations"], [])
            self.assertEqual(assigned_count, 0)


if __name__ == "__main__":
    unittest.main()
