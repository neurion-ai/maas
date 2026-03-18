import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.services.bootstrap import bootstrap_project


class NotificationsApiTest(unittest.TestCase):
    def _configure_notifications(self, client, project_id, *, minimum_severity="warning", enabled_events=None):
        response = client.post(
            f"/api/projects/{project_id}/actions/update-notification-policy",
            json={
                "actor_id": "agent_allocator",
                "webhook_urls": ["https://example.test/hooks/maas"],
                "minimum_severity": minimum_severity,
                "enabled_events": enabled_events or ["escalation_requested", "dead_letter_opened", "circuit_breaker_opened"],
            },
        )
        self.assertEqual(response.status_code, 200)

    def _seed_escalation_notification(self, client, project_root):
        connection = connect(project_paths(project_root))
        try:
            project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
            task_id = connection.execute(
                "SELECT task_id FROM tasks WHERE project_id = ? ORDER BY created_at ASC LIMIT 1",
                (project_id,),
            ).fetchone()["task_id"]
        finally:
            connection.close()

        self._configure_notifications(client, project_id, enabled_events=["escalation_requested"])
        escalation_response = client.post(
            "/api/escalations/request",
            json={
                "project_id": project_id,
                "actor_id": "agent_allocator",
                "action_type": "halt_task",
                "resource_type": "task",
                "resource_id": task_id,
                "reason": "notification test",
                "payload": {},
            },
        )
        self.assertEqual(escalation_response.status_code, 200)
        notifications_payload = client.get("/api/notifications").json()["notifications"]
        self.assertEqual(len(notifications_payload), 1)
        return project_id, notifications_payload[0]["notification_id"]

    def test_escalation_request_queues_notification_and_portfolio_surfaces_it(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Notification Test", description="notification test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            _project_id, notification_id = self._seed_escalation_notification(client, tmpdir)

            notifications_payload = client.get("/api/notifications").json()["notifications"]
            self.assertEqual(notifications_payload[0]["notification_id"], notification_id)
            self.assertEqual(notifications_payload[0]["event_type"], "escalation_requested")
            self.assertEqual(notifications_payload[0]["status"], "queued")

            portfolio_payload = client.get("/api/portfolio").json()
            self.assertEqual(portfolio_payload["summary"]["queued_notifications"], 1)
            self.assertEqual(portfolio_payload["summary"]["failed_notifications"], 0)
            self.assertEqual(len(portfolio_payload["command_center"]["notification_deliveries"]), 1)

    def test_process_notification_marks_delivery_sent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Notification Delivery Test", description="notification delivery", project_type="custom")
            client = TestClient(create_app(tmpdir))

            _project_id, notification_id = self._seed_escalation_notification(client, tmpdir)

            response_mock = mock.MagicMock()
            response_mock.status = 204
            response_mock.read.return_value = b""
            context_manager = mock.MagicMock()
            context_manager.__enter__.return_value = response_mock
            context_manager.__exit__.return_value = False

            with mock.patch("maas.services.notifications.request.urlopen", return_value=context_manager):
                response = client.post(
                    f"/api/notifications/{notification_id}/actions/process",
                    json={"actor_id": "agent_allocator"},
                )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "sent")
            self.assertEqual(payload["last_response_code"], 204)

            portfolio_payload = client.get("/api/portfolio").json()
            self.assertEqual(portfolio_payload["summary"]["queued_notifications"], 0)

    def test_failed_notification_delivery_stays_visible_for_retry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Notification Failure Test", description="notification failure", project_type="custom")
            client = TestClient(create_app(tmpdir))

            _project_id, notification_id = self._seed_escalation_notification(client, tmpdir)

            with mock.patch(
                "maas.services.notifications.request.urlopen",
                side_effect=RuntimeError("delivery blew up"),
            ):
                response = client.post(
                    f"/api/notifications/{notification_id}/actions/process",
                    json={"actor_id": "agent_allocator"},
                )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "failed")
            self.assertIn("delivery blew up", payload["last_error"])

            portfolio_payload = client.get("/api/portfolio").json()
            self.assertEqual(portfolio_payload["summary"]["failed_notifications"], 1)


if __name__ == "__main__":
    unittest.main()
