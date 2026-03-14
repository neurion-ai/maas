import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect
from maas.services.bootstrap import bootstrap_project
from maas.ids import generate_id
from maas.services.lifecycle import heartbeat
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
                failure = connection.execute(
                    """
                    SELECT failure_type
                    FROM failure_log
                    WHERE task_id = (
                        SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'
                    )
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(len(supervisor_result["stale_sessions"]), 1)
            self.assertIsNotNone(session)
            self.assertEqual(task["status"], "blocked")
            self.assertEqual(task["review_state"], "stale_session")
            self.assertEqual(agent["status"], "error")
            self.assertIsNone(agent["current_task_id"])
            self.assertEqual(failure["failure_type"], "session_timed_out")

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

    def test_stale_session_does_not_clobber_agent_with_other_active_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor Duplicate Session Test",
                description="Supervisor duplicate session test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                stale_session_id = connection.execute(
                    "SELECT session_id FROM sessions WHERE task_id = ? AND status = 'active'",
                    (task_id,),
                ).fetchone()["session_id"]
                healthy_session_id = generate_id("sess")
                connection.execute(
                    """
                    INSERT INTO sessions (
                        session_id, project_id, agent_id, task_id, status, provider_type, progress_pct, status_message
                    ) VALUES (?, ?, ?, ?, 'active', 'python_script', 65, ?)
                    """,
                    (
                        healthy_session_id,
                        project_id,
                        "agent_builder",
                        task_id,
                        "Second active session for duplicate-session regression test",
                    ),
                )
                heartbeat(connection, healthy_session_id, 70, "Healthy duplicate session heartbeat")
                connection.execute(
                    """
                    UPDATE sessions
                    SET last_heartbeat_at = '2000-01-01 00:00:00'
                    WHERE session_id = ?
                    """,
                    (stale_session_id,),
                )
                connection.commit()

                supervisor_result = run_supervisor_once(connection, stale_after_seconds=90, allocate_limit=0)
                agent = connection.execute(
                    "SELECT status, current_task_id FROM agents WHERE agent_id = 'agent_builder'"
                ).fetchone()
                task = connection.execute(
                    "SELECT status, review_state FROM tasks WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                healthy_session = connection.execute(
                    "SELECT status FROM sessions WHERE session_id = ?",
                    (healthy_session_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(len(supervisor_result["stale_sessions"]), 1)
            self.assertEqual(agent["status"], "running")
            self.assertEqual(agent["current_task_id"], task_id)
            self.assertEqual(task["status"], "in_progress")
            self.assertIsNone(task["review_state"])
            self.assertEqual(healthy_session["status"], "active")

    def test_supervisor_raises_repeated_failure_alert_for_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor Repeated Failure Test",
                description="Supervisor repeated failure test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    INSERT INTO failure_log (
                        failure_id, project_id, task_id, session_id, agent_id, failure_type, summary, detail_json
                    )
                    SELECT ?, project_id, ?, session_id, agent_id, 'session_failed', 'Earlier failure', '{}'
                    FROM sessions
                    WHERE task_id = ?
                    LIMIT 1
                    """,
                    (generate_id("fail"), task_id, task_id),
                )
                connection.execute(
                    """
                    UPDATE sessions
                    SET last_heartbeat_at = '2000-01-01 00:00:00'
                    WHERE task_id = ? AND status = 'active'
                    """,
                    (task_id,),
                )
                connection.commit()

                supervisor_result = run_supervisor_once(connection, stale_after_seconds=90, allocate_limit=0)
                repeated_alert = connection.execute(
                    """
                    SELECT title, severity
                    FROM alerts
                    WHERE title = 'Repeated task failures'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(repeated_alert["title"], "Repeated task failures")
            self.assertEqual(repeated_alert["severity"], "critical")
            self.assertIsNotNone(supervisor_result["stale_sessions"][0]["repeated_failure_alert"])

    def test_cancelled_sessions_do_not_count_toward_repeated_failure_alerts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor Cancelled Failure Test",
                description="Supervisor cancelled failure test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    INSERT INTO failure_log (
                        failure_id, project_id, task_id, session_id, agent_id, failure_type, summary, detail_json
                    )
                    SELECT ?, project_id, ?, session_id, agent_id, 'session_cancelled', 'Operator cancelled work', '{}'
                    FROM sessions
                    WHERE task_id = ?
                    LIMIT 1
                    """,
                    (generate_id("fail"), task_id, task_id),
                )
                connection.execute(
                    """
                    UPDATE sessions
                    SET last_heartbeat_at = '2000-01-01 00:00:00'
                    WHERE task_id = ? AND status = 'active'
                    """,
                    (task_id,),
                )
                connection.commit()

                supervisor_result = run_supervisor_once(connection, stale_after_seconds=90, allocate_limit=0)
                repeated_alert = connection.execute(
                    """
                    SELECT alert_id
                    FROM alerts
                    WHERE title = 'Repeated task failures'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ).fetchone()
            finally:
                connection.close()

            self.assertIsNone(repeated_alert)
            self.assertIsNone(supervisor_result["stale_sessions"][0]["repeated_failure_alert"])


if __name__ == "__main__":
    unittest.main()
