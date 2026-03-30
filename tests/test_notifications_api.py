import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.services.bootstrap import bootstrap_project
from maas.services.notifications import queue_notification_event


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
            self.assertEqual(payload["operation_state"], "succeeded")
            self.assertFalse(payload["retryable"])
            self.assertFalse(payload["terminal_failure"])
            self.assertEqual(payload["last_external_result"]["last_response_code"], 204)

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
            self.assertEqual(payload["operation_state"], "failed_retryable")
            self.assertTrue(payload["retryable"])
            self.assertFalse(payload["terminal_failure"])
            self.assertIn("delivery blew up", payload["last_external_result"]["last_error"])

            portfolio_payload = client.get("/api/portfolio").json()
            self.assertEqual(portfolio_payload["summary"]["failed_notifications"], 1)

    def test_process_notification_is_idempotent_after_sent_delivery(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Notification Idempotent Test", description="notification idempotent", project_type="custom")
            client = TestClient(create_app(tmpdir))

            _project_id, notification_id = self._seed_escalation_notification(client, tmpdir)

            response_mock = mock.MagicMock()
            response_mock.status = 204
            response_mock.read.return_value = b""
            context_manager = mock.MagicMock()
            context_manager.__enter__.return_value = response_mock
            context_manager.__exit__.return_value = False

            with mock.patch("maas.services.notifications.request.urlopen", return_value=context_manager) as urlopen_mock:
                first = client.post(
                    f"/api/notifications/{notification_id}/actions/process",
                    json={"actor_id": "agent_allocator"},
                )
                second = client.post(
                    f"/api/notifications/{notification_id}/actions/process",
                    json={"actor_id": "agent_allocator"},
                )

            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            self.assertEqual(urlopen_mock.call_count, 1)
            self.assertEqual(second.json()["status"], "sent")
            self.assertEqual(second.json()["attempts"], 1)
            self.assertEqual(second.json()["operation_state"], "succeeded")

    def test_process_next_notification_skips_actively_claimed_item(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Notification Claim Skip Test", description="notification claim skip", project_type="custom")
            client = TestClient(create_app(tmpdir))
            project_id = client.get("/api/projects").json()["projects"][0]["project_id"]
            self._configure_notifications(client, project_id, enabled_events=["escalation_requested"])

            connection = connect(project_paths(tmpdir))
            try:
                first_id = queue_notification_event(
                    connection,
                    project_id,
                    "escalation_requested",
                    "critical",
                    "Escalation requested",
                    "First queued item.",
                    resource_type="task",
                    resource_id="task_first",
                    payload={"reason": "first"},
                )[0]
                second_id = queue_notification_event(
                    connection,
                    project_id,
                    "escalation_requested",
                    "critical",
                    "Escalation requested",
                    "Second queued item.",
                    resource_type="task",
                    resource_id="task_second",
                    payload={"reason": "second"},
                )[0]
                connection.execute(
                    """
                    UPDATE notification_outbox
                    SET processing_token = 'notifop_claimed',
                        processing_started_at = CURRENT_TIMESTAMP
                    WHERE notification_id = ?
                    """,
                    (first_id,),
                )
                connection.commit()
            finally:
                connection.close()

            response_mock = mock.MagicMock()
            response_mock.status = 204
            response_mock.read.return_value = b""
            context_manager = mock.MagicMock()
            context_manager.__enter__.return_value = response_mock
            context_manager.__exit__.return_value = False

            with mock.patch("maas.services.notifications.request.urlopen", return_value=context_manager):
                processed = client.post(
                    "/api/notifications/actions/process-next",
                    json={"actor_id": "agent_allocator", "project_id": project_id},
                )

            self.assertEqual(processed.status_code, 200)
            self.assertTrue(processed.json()["processed"])
            self.assertEqual(processed.json()["notification"]["notification_id"], second_id)

            notifications = client.get("/api/notifications", params={"project_id": project_id}).json()["notifications"]
            by_id = {item["notification_id"]: item for item in notifications}
            self.assertEqual(by_id[first_id]["operation_state"], "running")
            self.assertFalse(by_id[first_id]["retryable"])
            self.assertEqual(by_id[second_id]["status"], "sent")

    def test_process_next_notification_scans_past_more_than_ten_claimed_items(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Notification Claim Backlog Test", description="notification claim backlog", project_type="custom")
            client = TestClient(create_app(tmpdir))
            project_id = client.get("/api/projects").json()["projects"][0]["project_id"]
            self._configure_notifications(client, project_id, enabled_events=["escalation_requested"])

            connection = connect(project_paths(tmpdir))
            try:
                claimed_ids = []
                for index in range(11):
                    claimed_ids.append(
                        queue_notification_event(
                            connection,
                            project_id,
                            "escalation_requested",
                            "critical",
                            "Escalation requested",
                            "Claimed backlog item.",
                            resource_type="task",
                            resource_id=f"task_claimed_{index}",
                            payload={"index": index},
                        )[0]
                    )
                claimable_id = queue_notification_event(
                    connection,
                    project_id,
                    "escalation_requested",
                    "critical",
                    "Escalation requested",
                    "Claimable backlog item.",
                    resource_type="task",
                    resource_id="task_claimable",
                    payload={"index": 99},
                )[0]
                connection.executemany(
                    """
                    UPDATE notification_outbox
                    SET processing_token = ?,
                        processing_started_at = CURRENT_TIMESTAMP
                    WHERE notification_id = ?
                    """,
                    [(f"notifop_claimed_{index}", notification_id) for index, notification_id in enumerate(claimed_ids)],
                )
                connection.commit()
            finally:
                connection.close()

            response_mock = mock.MagicMock()
            response_mock.status = 204
            response_mock.read.return_value = b""
            context_manager = mock.MagicMock()
            context_manager.__enter__.return_value = response_mock
            context_manager.__exit__.return_value = False

            with mock.patch("maas.services.notifications.request.urlopen", return_value=context_manager):
                processed = client.post(
                    "/api/notifications/actions/process-next",
                    json={"actor_id": "agent_allocator", "project_id": project_id},
                )

            self.assertEqual(processed.status_code, 200)
            self.assertTrue(processed.json()["processed"])
            self.assertEqual(processed.json()["notification"]["notification_id"], claimable_id)

    def test_duplicate_notification_event_reuses_existing_outbox_item(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Notification Dedupe Test", description="notification dedupe", project_type="custom")
            client = TestClient(create_app(tmpdir))
            project_id = client.get("/api/projects").json()["projects"][0]["project_id"]
            self._configure_notifications(client, project_id, enabled_events=["escalation_requested"])

            connection = connect(project_paths(tmpdir))
            try:
                first_ids = queue_notification_event(
                    connection,
                    project_id,
                    "escalation_requested",
                    "critical",
                    "Escalation requested",
                    "Operator input needed.",
                    resource_type="task",
                    resource_id="task_demo",
                    payload={"reason": "same"},
                )
                second_ids = queue_notification_event(
                    connection,
                    project_id,
                    "escalation_requested",
                    "critical",
                    "Escalation requested",
                    "Operator input needed.",
                    resource_type="task",
                    resource_id="task_demo",
                    payload={"reason": "same"},
                )
                connection.commit()

                notifications = connection.execute(
                    "SELECT notification_id FROM notification_outbox WHERE project_id = ?",
                    (project_id,),
                ).fetchall()
            finally:
                connection.close()

            self.assertEqual(first_ids, second_ids)
            self.assertEqual(len(notifications), 1)

    def test_failed_notification_waits_for_retry_window_and_duplicate_event_requeues_it(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Notification Retry Test", description="notification retry", project_type="custom")
            client = TestClient(create_app(tmpdir))
            project_id = client.get("/api/projects").json()["projects"][0]["project_id"]
            self._configure_notifications(client, project_id, enabled_events=["escalation_requested"])

            connection = connect(project_paths(tmpdir))
            try:
                notification_id = queue_notification_event(
                    connection,
                    project_id,
                    "escalation_requested",
                    "critical",
                    "Escalation requested",
                    "Operator input needed.",
                    resource_type="task",
                    resource_id="task_demo",
                    payload={"reason": "retry"},
                )[0]
                connection.commit()
            finally:
                connection.close()

            with mock.patch(
                "maas.services.notifications.request.urlopen",
                side_effect=RuntimeError("delivery blew up"),
            ):
                response = client.post(
                    f"/api/notifications/{notification_id}/actions/process",
                    json={"actor_id": "agent_allocator"},
                )

            self.assertEqual(response.status_code, 200)
            failed_payload = response.json()
            self.assertEqual(failed_payload["status"], "failed")
            self.assertIsNotNone(failed_payload["next_attempt_at"])

            immediate_retry = client.post(
                "/api/notifications/actions/process-next",
                json={"actor_id": "agent_allocator", "project_id": project_id},
            )
            self.assertEqual(immediate_retry.status_code, 200)
            self.assertFalse(immediate_retry.json()["processed"])

            connection = connect(project_paths(tmpdir))
            try:
                duplicate_ids = queue_notification_event(
                    connection,
                    project_id,
                    "escalation_requested",
                    "critical",
                    "Escalation requested",
                    "Operator input needed.",
                    resource_type="task",
                    resource_id="task_demo",
                    payload={"reason": "retry"},
                )
                connection.commit()
            finally:
                connection.close()

            self.assertEqual(duplicate_ids, [notification_id])
            refreshed = client.get("/api/notifications").json()["notifications"][0]
            self.assertEqual(refreshed["notification_id"], notification_id)
            self.assertEqual(refreshed["status"], "queued")
            self.assertEqual(refreshed["attempts"], 1)

            response_mock = mock.MagicMock()
            response_mock.status = 204
            response_mock.read.return_value = b""
            context_manager = mock.MagicMock()
            context_manager.__enter__.return_value = response_mock
            context_manager.__exit__.return_value = False

            with mock.patch("maas.services.notifications.request.urlopen", return_value=context_manager):
                retried = client.post(
                    "/api/notifications/actions/process-next",
                    json={"actor_id": "agent_allocator", "project_id": project_id},
                )

            self.assertEqual(retried.status_code, 200)
            self.assertTrue(retried.json()["processed"])
            self.assertEqual(retried.json()["notification"]["notification_id"], notification_id)
            self.assertEqual(retried.json()["notification"]["status"], "sent")

    def test_notifications_endpoint_exposes_retry_budget_and_skips_exhausted_automatic_retries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Notification Exhaustion Test", description="notification exhaustion", project_type="custom")
            client = TestClient(create_app(tmpdir))
            project_id = client.get("/api/projects").json()["projects"][0]["project_id"]
            self._configure_notifications(client, project_id, enabled_events=["escalation_requested"])

            connection = connect(project_paths(tmpdir))
            try:
                notification_id = queue_notification_event(
                    connection,
                    project_id,
                    "escalation_requested",
                    "critical",
                    "Escalation requested",
                    "Operator input needed.",
                    resource_type="task",
                    resource_id="task_demo",
                    payload={"reason": "exhaust"},
                )[0]
                connection.commit()
            finally:
                connection.close()

            with mock.patch(
                "maas.services.notifications.request.urlopen",
                side_effect=RuntimeError("delivery blew up"),
            ):
                for _ in range(5):
                    response = client.post(
                        f"/api/notifications/{notification_id}/actions/process",
                        json={"actor_id": "agent_allocator"},
                    )
                    self.assertEqual(response.status_code, 200)

            payload = client.get("/api/notifications", params={"project_id": project_id}).json()
            self.assertEqual(payload["summary"]["retry_exhausted"], 1)
            self.assertEqual(payload["summary"]["max_attempts"], 5)

            item = payload["notifications"][0]
            self.assertEqual(item["notification_id"], notification_id)
            self.assertEqual(item["status"], "failed")
            self.assertEqual(item["delivery_state"], "retry_exhausted")
            self.assertEqual(item["retry_budget_remaining"], 0)
            self.assertTrue(item["retry_budget_exhausted"])
            self.assertIsNone(item["next_attempt_at"])

            digest = payload["digests"]["attention"][0]
            self.assertEqual(digest["dedupe_key"], item["dedupe_key"])
            self.assertEqual(digest["delivery_state"], "retry_exhausted")
            self.assertTrue(digest["retry_budget_exhausted"])

            automatic_retry = client.post(
                "/api/notifications/actions/process-next",
                json={"actor_id": "agent_allocator", "project_id": project_id},
            )
            self.assertEqual(automatic_retry.status_code, 200)
            self.assertFalse(automatic_retry.json()["processed"])

            connection = connect(project_paths(tmpdir))
            try:
                duplicate_ids = queue_notification_event(
                    connection,
                    project_id,
                    "escalation_requested",
                    "critical",
                    "Escalation requested",
                    "Operator input needed.",
                    resource_type="task",
                    resource_id="task_demo",
                    payload={"reason": "exhaust"},
                )
                connection.commit()
            finally:
                connection.close()

            self.assertEqual(duplicate_ids, [notification_id])
            refreshed = client.get("/api/notifications", params={"project_id": project_id}).json()["notifications"][0]
            self.assertEqual(refreshed["status"], "failed")
            self.assertEqual(refreshed["delivery_state"], "retry_exhausted")
            self.assertEqual(refreshed["attempts"], 5)
            self.assertIsNone(refreshed["next_attempt_at"])


if __name__ == "__main__":
    unittest.main()
