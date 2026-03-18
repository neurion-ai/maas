import json
import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.services.bootstrap import bootstrap_project


class TimelineApiTest(unittest.TestCase):
    def test_timeline_endpoint_combines_incident_sources_for_task_scope(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Timeline Test", description="timeline test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute("SELECT task_id FROM tasks ORDER BY created_at ASC LIMIT 1").fetchone()["task_id"]
                connection.execute(
                    """
                    INSERT INTO activity_log (
                        activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
                    ) VALUES ('act_timeline', ?, 'agent_allocator', ?, 'timeline_marker', 'runtime', 'Timeline activity marker', '{"session_id":"sess_timeline"}', 'info')
                    """,
                    (project_id, task_id),
                )
                connection.execute(
                    """
                    INSERT INTO audit_trail (
                        audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
                    ) VALUES ('audit_timeline', ?, 'agent_allocator', 'halt_task', 'task', ?, '{}')
                    """,
                    (project_id, task_id),
                )
                connection.execute(
                    """
                    INSERT INTO sessions (
                        session_id, project_id, agent_id, task_id, status, provider_type, progress_pct, status_message, ended_at
                    ) VALUES ('sess_timeline', ?, 'agent_allocator', ?, 'completed', 'python_script', 100, 'Timeline session', CURRENT_TIMESTAMP)
                    """,
                    (project_id, task_id),
                )
                connection.execute(
                    """
                    INSERT INTO failure_log (
                        failure_id, project_id, task_id, session_id, agent_id, failure_type, summary, detail_json
                    ) VALUES ('failure_timeline', ?, ?, 'sess_timeline', 'agent_allocator', 'session_failed', 'Timeline failure', '{"kind":"runtime"}')
                    """,
                    (project_id, task_id),
                )
                connection.execute(
                    """
                    INSERT INTO dead_letter_queue (
                        dlq_id, project_id, task_id, failure_id, reason, detail_json
                    ) VALUES ('dlq_timeline', ?, ?, 'failure_timeline', 'retry_budget_exhausted', '{"retry_count":3}')
                    """,
                    (project_id, task_id),
                )
                connection.execute(
                    """
                    INSERT INTO escalation_queue (
                        escalation_id, project_id, requested_by, action_type, resource_type, resource_id, payload_json, reason, status
                    ) VALUES ('esc_timeline', ?, 'agent_allocator', 'halt_task', 'task', ?, '{}', 'timeline escalation', 'open')
                    """,
                    (project_id, task_id),
                )
                connection.execute(
                    """
                    INSERT INTO provider_job_queue (
                        job_id, project_id, provider_id, task_id, agent_id, status, queued_by
                    ) VALUES ('job_timeline', ?, 'python_script', ?, 'agent_allocator', 'queued', 'agent_allocator')
                    """,
                    (project_id, task_id),
                )
                connection.execute(
                    """
                    INSERT INTO notification_outbox (
                        notification_id, project_id, target_url, event_type, severity, title, body, payload_json, resource_type, resource_id, status
                    ) VALUES ('notif_timeline', ?, 'https://example.test/hooks/maas', 'escalation_requested', 'warning', 'Timeline notification', 'timeline notification', '{}', 'task', ?, 'queued')
                    """,
                    (project_id, task_id),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.get("/api/timeline", params={"task_id": task_id, "limit": 50})
            self.assertEqual(response.status_code, 200)
            payload = response.json()

            sources = {item["source"] for item in payload["events"]}
            self.assertTrue({"activity", "audit", "session", "failure", "dead_letter", "escalation", "provider_job", "notification"}.issubset(sources))
            self.assertEqual(payload["filters"]["task_id"], task_id)
            self.assertEqual(payload["summary"]["total_events"], len(payload["events"]))

    def test_timeline_endpoint_supports_replay_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Timeline Order Test", description="timeline order test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute("SELECT task_id FROM tasks ORDER BY created_at ASC LIMIT 1").fetchone()["task_id"]
                connection.execute(
                    """
                    INSERT INTO activity_log (
                        activity_id, project_id, task_id, action, category, description, severity, created_at
                    ) VALUES
                        ('act_timeline_old', ?, ?, 'older_marker', 'runtime', 'Older marker', 'info', '2026-01-01 00:00:00'),
                        ('act_timeline_new', ?, ?, 'newer_marker', 'runtime', 'Newer marker', 'info', '2026-01-02 00:00:00')
                    """,
                    (project_id, task_id, project_id, task_id),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            asc_payload = client.get("/api/timeline", params={"task_id": task_id, "order": "asc", "limit": 10}).json()
            desc_payload = client.get("/api/timeline", params={"task_id": task_id, "order": "desc", "limit": 10}).json()

            asc_activity = [item for item in asc_payload["events"] if item["source"] == "activity"]
            desc_activity = [item for item in desc_payload["events"] if item["source"] == "activity"]
            self.assertEqual(asc_activity[0]["event_id"], "act_timeline_old")
            self.assertEqual(desc_activity[0]["event_id"], "act_timeline_new")


if __name__ == "__main__":
    unittest.main()
