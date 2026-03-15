import json
import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect
from maas.services.bootstrap import bootstrap_project
from maas.services.lifecycle import end_session
from maas.services.scheduler import evaluate_task, refresh_ready_tasks, resolve_ready_tasks


class SchedulerApiTest(unittest.TestCase):
    def test_evaluate_task_supports_artifact_db_query_and_test_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Scheduler Test", description="Scheduler test", project_type="custom")
            connection = connect(result["paths"])
            try:
                artifact_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Define project workspace contracts'"
                ).fetchone()["task_id"]
                artifact_path = os.path.join(tmpdir, ".maas", "artifacts", "workspace-contract.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("workspace contract ready\n")
                connection.execute(
                    """
                    UPDATE tasks
                    SET acceptance_criteria_json = ?
                    WHERE task_id = ?
                    """,
                    (json.dumps([{"type": "artifact_exists", "path": artifact_path}]), artifact_task_id),
                )

                query_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Bootstrap migration runner'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET acceptance_criteria_json = ?
                    WHERE task_id = ?
                    """,
                    (
                        json.dumps(
                            [
                                {
                                    "type": "db_query",
                                    "query": "SELECT COUNT(*) FROM tasks WHERE status = 'done'",
                                    "op": ">=",
                                    "value": 1,
                                }
                            ]
                        ),
                        query_task_id,
                    ),
                )

                command_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET acceptance_criteria_json = ?
                    WHERE task_id = ?
                    """,
                    (json.dumps([{"type": "test_passes", "command": "true"}]), command_task_id),
                )
                connection.commit()

                artifact_result = evaluate_task(connection, result["paths"], artifact_task_id)
                query_result = evaluate_task(connection, result["paths"], query_task_id)
                command_result = evaluate_task(connection, result["paths"], command_task_id)
            finally:
                connection.close()

            self.assertTrue(artifact_result["overall_passed"])
            self.assertTrue(query_result["overall_passed"])
            self.assertTrue(command_result["overall_passed"])

    def test_evaluate_task_returns_failed_result_for_invalid_query_and_timeout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Scheduler Failure Test",
                description="Scheduler failure test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                invalid_query_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Bootstrap migration runner'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET acceptance_criteria_json = ?
                    WHERE task_id = ?
                    """,
                    (
                        json.dumps(
                            [
                                {
                                    "type": "db_query",
                                    "query": "SELECT missing_column FROM not_a_real_table",
                                    "op": ">=",
                                    "value": 1,
                                }
                            ]
                        ),
                        invalid_query_task_id,
                    ),
                )

                timeout_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET acceptance_criteria_json = ?
                    WHERE task_id = ?
                    """,
                    (
                        json.dumps(
                            [
                                {
                                    "type": "test_passes",
                                    "command": "python3 -c 'import time; time.sleep(1)'",
                                    "timeout_seconds": 0,
                                }
                            ]
                        ),
                        timeout_task_id,
                    ),
                )
                connection.commit()

                invalid_query_result = evaluate_task(connection, result["paths"], invalid_query_task_id)
                timeout_result = evaluate_task(connection, result["paths"], timeout_task_id)
            finally:
                connection.close()

            self.assertFalse(invalid_query_result["overall_passed"])
            self.assertIn("Query failed:", invalid_query_result["results"][0]["reason"])
            self.assertFalse(timeout_result["overall_passed"])
            self.assertIn("timed out", timeout_result["results"][0]["reason"])

    def test_refresh_ready_updates_blocked_and_unblocked_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Ready Test", description="Ready test", project_type="custom")
            connection = connect(result["paths"])
            try:
                changed = refresh_ready_tasks(connection)
                ready_tasks = resolve_ready_tasks(connection)
                ready_ids = {task["task_id"] for task in ready_tasks}
                ready_titles = {task["title"] for task in ready_tasks}
            finally:
                connection.close()

            self.assertGreaterEqual(len(changed), 1)
            self.assertIn("Define project workspace contracts", ready_titles)
            self.assertNotIn("Implement FastAPI board endpoint", ready_titles)
            self.assertTrue(any(change["status"] == "ready" for change in changed))

    def test_refresh_ready_preserves_manual_blocks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Manual Block Test", description="Manual block test", project_type="custom")
            connection = connect(result["paths"])
            try:
                blocked_task = connection.execute(
                    "SELECT task_id, status, review_state FROM tasks WHERE title = 'Integrate provider adapters'"
                ).fetchone()
                changed = refresh_ready_tasks(connection)
                refreshed = connection.execute(
                    "SELECT status, review_state FROM tasks WHERE task_id = ?",
                    (blocked_task["task_id"],),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(blocked_task["status"], "blocked")
            self.assertEqual(refreshed["status"], "blocked")
            self.assertIsNone(refreshed["review_state"])
            self.assertFalse(any(change["task_id"] == blocked_task["task_id"] for change in changed))

    def test_refresh_ready_restores_assigned_tasks_after_dependency_clears(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Assigned Restore Test", description="Assigned restore test", project_type="custom")
            connection = connect(result["paths"])
            try:
                target_task = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()
                blocker_task = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'blocked', review_state = 'blocked_by_dependency'
                    WHERE task_id = ?
                    """,
                    (target_task["task_id"],),
                )
                connection.execute(
                    "UPDATE tasks SET status = 'done' WHERE task_id = ?",
                    (blocker_task["task_id"],),
                )
                connection.commit()

                changed = refresh_ready_tasks(connection)
                refreshed = connection.execute(
                    "SELECT status, review_state, assigned_agent_id FROM tasks WHERE task_id = ?",
                    (target_task["task_id"],),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(refreshed["status"], "assigned")
            self.assertIsNone(refreshed["review_state"])
            self.assertIsNotNone(refreshed["assigned_agent_id"])

    def test_refresh_ready_honors_retry_backoff_until_timestamp_expires(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Retry Cooldown Test", description="Retry cooldown test", project_type="custom")
            connection = connect(result["paths"])
            try:
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Define project workspace contracts'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'planned',
                        review_state = 'retry_backoff',
                        next_retry_at = '2999-01-01 00:00:00',
                        next_retry_reason = 'recover_and_requeue'
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
                connection.commit()

                changed_before = refresh_ready_tasks(connection)
                not_ready_yet = connection.execute(
                    """
                    SELECT status, review_state, next_retry_at, next_retry_reason
                    FROM tasks
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
                ready_ids_before = {task["task_id"] for task in resolve_ready_tasks(connection)}

                connection.execute(
                    """
                    UPDATE tasks
                    SET next_retry_at = '2000-01-01 00:00:00'
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
                connection.commit()

                changed_after = refresh_ready_tasks(connection)
                ready_now = connection.execute(
                    """
                    SELECT status, review_state, next_retry_at, next_retry_reason
                    FROM tasks
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
                ready_ids_after = {task["task_id"] for task in resolve_ready_tasks(connection)}
            finally:
                connection.close()

            self.assertFalse(any(change["task_id"] == task_id for change in changed_before))
            self.assertEqual(not_ready_yet["status"], "planned")
            self.assertEqual(not_ready_yet["review_state"], "retry_backoff")
            self.assertNotIn(task_id, ready_ids_before)
            self.assertTrue(any(change["task_id"] == task_id and change["status"] == "ready" for change in changed_after))
            self.assertEqual(ready_now["status"], "ready")
            self.assertIsNone(ready_now["review_state"])
            self.assertIsNone(ready_now["next_retry_at"])
            self.assertIsNone(ready_now["next_retry_reason"])
            self.assertIn(task_id, ready_ids_after)

    def test_recover_and_requeue_stays_blocked_when_dependency_is_still_open(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Recover And Requeue Dependency Test",
                description="Recover and requeue with dependency still open",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                session_id = connection.execute(
                    "SELECT session_id FROM sessions WHERE task_id = ? AND status = 'active'",
                    (task_id,),
                ).fetchone()["session_id"]
                end_session(connection, session_id, "failed", "Recoverable failure")
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            recover_response = client.post(
                "/api/tasks/{0}/actions/recover-and-requeue".format(task_id),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(recover_response.status_code, 200)
            self.assertEqual(recover_response.json()["status"], "blocked")
            self.assertEqual(recover_response.json()["review_state"], "blocked_by_dependency")

    def test_scheduler_api_endpoints_work(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Scheduler API Test", description="API scheduler test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            refresh_response = client.post("/api/tasks/actions/refresh-ready")
            self.assertEqual(refresh_response.status_code, 200)
            refresh_payload = refresh_response.json()
            self.assertIn("tasks", refresh_payload)

            ready_response = client.get("/api/tasks/ready")
            self.assertEqual(ready_response.status_code, 200)
            self.assertIn("tasks", ready_response.json())

            connection = connect(result["paths"])
            try:
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Bootstrap migration runner'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET acceptance_criteria_json = ?
                    WHERE task_id = ?
                    """,
                    (
                        json.dumps(
                            [
                                {
                                    "type": "db_query",
                                    "query": "SELECT COUNT(*) FROM tasks WHERE status = 'done'",
                                    "op": ">=",
                                    "value": 1,
                                }
                            ]
                        ),
                        task_id,
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            evaluate_response = client.post("/api/tasks/{0}/actions/evaluate".format(task_id))
            self.assertEqual(evaluate_response.status_code, 200)
            self.assertTrue(evaluate_response.json()["overall_passed"])


if __name__ == "__main__":
    unittest.main()
