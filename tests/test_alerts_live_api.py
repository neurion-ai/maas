import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.services.bootstrap import bootstrap_project
from maas.services.escalations import request_escalation
from maas.services.live import build_live_snapshot


class AlertsAndLiveApiTest(unittest.TestCase):
    def test_alert_actions_and_live_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Live Test", description="Live test", project_type="custom")
            client = TestClient(create_app(tmpdir))
            connection = connect(project_paths(tmpdir))
            try:
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    INSERT INTO failure_log (
                        failure_id, project_id, task_id, session_id, agent_id, failure_type, summary, detail_json
                    )
                    SELECT 'fail_demo', project_id, ?, session_id, agent_id, 'session_failed', 'Demo failure', '{}'
                    FROM sessions
                    WHERE task_id = ?
                    LIMIT 1
                    """,
                    (task_id, task_id),
                )
                connection.commit()
            finally:
                connection.close()

            live_response = client.get("/api/live")
            self.assertEqual(live_response.status_code, 200)
            live_payload = live_response.json()
            self.assertIn("counts", live_payload)
            self.assertIn("revision", live_payload)
            self.assertEqual(live_payload["counts"]["failures_total"], 1)

            alerts_response = client.get("/api/alerts")
            self.assertEqual(alerts_response.status_code, 200)
            alerts_payload = alerts_response.json()
            self.assertGreaterEqual(alerts_payload["summary"]["open"], 1)
            alert_id = alerts_payload["alerts"][0]["alert_id"]

            ack_response = client.post(
                "/api/alerts/{0}/actions/acknowledge".format(alert_id),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(ack_response.status_code, 200)

            resolved_response = client.post(
                "/api/alerts/{0}/actions/resolve".format(alert_id),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(resolved_response.status_code, 200)

            refreshed = client.get("/api/alerts").json()
            matching = [alert for alert in refreshed["alerts"] if alert["alert_id"] == alert_id]
            self.assertEqual(matching[0]["status"], "resolved")

            failures_response = client.get("/api/failures")
            self.assertEqual(failures_response.status_code, 200)
            failures_payload = failures_response.json()
            self.assertEqual(failures_payload["summary"]["total_failures"], 1)
            self.assertEqual(failures_payload["recent"][0]["failure_type"], "session_failed")

    def test_live_snapshot_includes_open_escalation_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Live Escalation Test", description="Live escalation test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE status = 'ready' LIMIT 1"
                ).fetchone()["task_id"]
                request_escalation(
                    connection,
                    project_id=project_id,
                    actor_id="agent_builder",
                    action_type="halt_task",
                    resource_type="task",
                    resource_id=task_id,
                    reason="Need operator approval",
                )
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            live_payload = client.get("/api/live").json()

            self.assertEqual(live_payload["counts"]["escalations_open"], 1)
            self.assertIsNotNone(live_payload["revision"]["latest_escalation"])

    def test_live_snapshot_does_not_load_full_escalation_queue_for_open_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Live Query Test", description="Live query test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                with patch("maas.services.live.count_open_escalations", return_value=7), patch(
                    "maas.services.live.fetch_escalations",
                    side_effect=AssertionError("build_live_snapshot should not fetch the full escalation queue"),
                    create=True,
                ):
                    snapshot = build_live_snapshot(connection)
            finally:
                connection.close()

            self.assertEqual(snapshot["counts"]["escalations_open"], 7)

    def test_alert_action_requires_board_permission(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Alert Permission Test", description="Alert permission test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            alerts_payload = client.get("/api/alerts").json()
            alert_id = alerts_payload["alerts"][0]["alert_id"]

            denied_response = client.post(
                "/api/alerts/{0}/actions/acknowledge".format(alert_id),
                json={"actor_id": "agent_builder"},
            )
            self.assertEqual(denied_response.status_code, 403)

            connection = connect(project_paths(tmpdir))
            try:
                audit_row = connection.execute(
                    """
                    SELECT action_type, detail_json
                    FROM audit_trail
                    WHERE actor_id = 'agent_builder'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(audit_row["action_type"], "permission_denied")
            self.assertIn("update_alert_status", audit_row["detail_json"])

    def test_alerts_include_operator_actions_for_recoverable_failure_cases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(
                tmpdir,
                name="Alert Operator Actions Test",
                description="Alert operator actions test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_failure_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()["task_id"]
                repeated_failure_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Define project workspace contracts'"
                ).fetchone()["task_id"]
                stale_agent_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'blocked', review_state = 'session_failed'
                    WHERE task_id IN (?, ?)
                    """,
                    (task_failure_id, repeated_failure_task_id),
                )
                connection.execute(
                    """
                    UPDATE agents
                    SET status = 'error', current_task_id = NULL
                    WHERE agent_id = 'agent_reviewer'
                    """
                )
                connection.execute(
                    """
                    INSERT INTO alerts (
                        alert_id, project_id, severity, title, description, status
                    ) VALUES
                        ('alert_task_failure', ?, 'warning', 'Task session failed', ?, 'open'),
                        ('alert_repeated_failure', ?, 'critical', 'Repeated task failures', ?, 'open'),
                        ('alert_stale_agent', ?, 'warning', 'Stale agent heartbeat', ?, 'open')
                    """,
                    (
                        project_id,
                        "Task {0} failed in session sess_failure_123. Session crashed".format(task_failure_id),
                        project_id,
                        "Task {0} (Retry-heavy task) has failed 3 times. Latest failure: Timeout".format(
                            repeated_failure_task_id
                        ),
                        project_id,
                        "Agent agent_reviewer stopped heartbeating for task {0}.".format(stale_agent_task_id),
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            alerts_payload = client.get("/api/alerts").json()
            alerts_by_id = {alert["alert_id"]: alert for alert in alerts_payload["alerts"]}
            provider_pending = [
                alert for alert in alerts_payload["alerts"] if alert["title"] == "Provider adapters pending"
            ][0]

            self.assertNotIn("operator_action", provider_pending)
            self.assertEqual(
                alerts_by_id["alert_task_failure"]["operator_action"],
                {
                    "action": "recover_task",
                    "label": "Recover task",
                    "resource_type": "task",
                    "resource_id": task_failure_id,
                },
            )
            self.assertEqual(
                alerts_by_id["alert_repeated_failure"]["operator_action"],
                {
                    "action": "resolve_repeated_failures",
                    "label": "Resolve repeated failures",
                    "resource_type": "task",
                    "resource_id": repeated_failure_task_id,
                },
            )
            self.assertEqual(
                alerts_by_id["alert_stale_agent"]["operator_action"],
                {
                    "action": "recover_agent",
                    "label": "Recover agent",
                    "resource_type": "agent",
                    "resource_id": "agent_reviewer",
                    "related_task_id": stale_agent_task_id,
                },
            )


if __name__ == "__main__":
    unittest.main()
