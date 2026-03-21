import json
import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.ids import generate_id
from maas.services.bootstrap import bootstrap_project
from maas.services.notifications import queue_notification_event


class OperatorInboxApiTest(unittest.TestCase):
    def test_operator_inbox_aggregates_review_stale_recovery_policy_and_notification_attention(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Operator Inbox Test", description="operator inbox", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_row = connection.execute(
                    "SELECT project_id, config_json FROM projects LIMIT 1"
                ).fetchone()
                project_id = project_row["project_id"]
                tasks = connection.execute(
                    """
                    SELECT task_id, assigned_agent_id, title
                    FROM tasks
                    ORDER BY created_at ASC
                    LIMIT 3
                    """
                ).fetchall()
                review_task = tasks[0]
                recovery_task = tasks[1]
                stale_run_task = tasks[2]

                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'review', priority = 60, review_state = 'review_requested'
                    WHERE task_id = ?
                    """,
                    (review_task["task_id"],),
                )
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'blocked', review_state = 'session_failed'
                    WHERE task_id = ?
                    """,
                    (recovery_task["task_id"],),
                )
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'in_progress'
                    WHERE task_id = ?
                    """,
                    (stale_run_task["task_id"],),
                )

                session_id = generate_id("sess")
                connection.execute(
                    """
                    INSERT INTO sessions (
                        session_id, project_id, agent_id, task_id, status, provider_type, progress_pct,
                        status_message, last_heartbeat_at, started_at, ended_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, 'active', 'openai_codex', 35,
                        'Codex is stalled on a long-running branch', DATETIME('now', '-180 seconds'),
                        CURRENT_TIMESTAMP, NULL, CURRENT_TIMESTAMP
                    )
                    """,
                    (session_id, project_id, stale_run_task["assigned_agent_id"], stale_run_task["task_id"]),
                )
                connection.execute(
                    """
                    INSERT INTO activity_log (
                        activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
                    ) VALUES (?, ?, ?, ?, 'provider_adapter_started', 'runtime', ?, ?, 'info')
                    """,
                    (
                        generate_id("act"),
                        project_id,
                        stale_run_task["assigned_agent_id"],
                        stale_run_task["task_id"],
                        "Codex adapter started live execution.",
                        json.dumps(
                            {
                                "session_id": session_id,
                                "execution_mode": "codex_cli",
                                "external_runtime": "codex_cli",
                            }
                        ),
                    ),
                )

                config = json.loads(project_row["config_json"] or "{}")
                config["autopilot"] = {
                    "enabled": True,
                    "interval_seconds": 15,
                    "allocate_limit": 4,
                    "provider_job_limit": 2,
                    "auto_launch_assigned_work": True,
                    "process_notifications": True,
                    "notification_batch_limit": 2,
                }
                config["provider_capacity"] = {
                    "queue_mode": "paused",
                    "max_running_jobs": 0,
                    "preferred_provider_id": "openai_codex",
                }
                config["onboarding"] = {
                    "mode": "brownfield",
                    "review_status": "review_pending",
                    "review_task_id": review_task["task_id"],
                }
                config["notifications"] = {
                    "webhook_urls": ["https://example.test/hooks/maas"],
                    "minimum_severity": "warning",
                    "enabled_events": ["escalation_requested"],
                }
                connection.execute(
                    "UPDATE projects SET config_json = ? WHERE project_id = ?",
                    (json.dumps(config), project_id),
                )

                notification_id = queue_notification_event(
                    connection,
                    project_id,
                    "escalation_requested",
                    "critical",
                    "Escalation requested",
                    "Operator input needed.",
                    resource_type="task",
                    resource_id=review_task["task_id"],
                    payload={"reason": "operator inbox"},
                )[0]
                connection.execute(
                    """
                    UPDATE notification_outbox
                    SET status = 'failed',
                        attempts = 5,
                        last_error = 'webhook offline',
                        next_attempt_at = NULL,
                        last_attempt_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE notification_id = ?
                    """,
                    (notification_id,),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.get("/api/operator-inbox", params={"project_id": project_id})
            self.assertEqual(response.status_code, 200)
            payload = response.json()

            self.assertEqual(payload["project_id"], project_id)
            self.assertGreaterEqual(payload["summary"]["review"], 1)
            self.assertEqual(payload["summary"]["stale_runs"], 1)
            self.assertGreaterEqual(payload["summary"]["blocked_recovery"], 1)
            self.assertGreaterEqual(payload["summary"]["policy_conflicts"], 3)
            self.assertEqual(payload["summary"]["notification_failures"], 1)

            review_ids = {item["resource_id"] for item in payload["buckets"]["review"]}
            stale_run_ids = {item["resource_id"] for item in payload["buckets"]["stale_runs"]}
            blocked_recovery_ids = {item["resource_id"] for item in payload["buckets"]["blocked_recovery"]}
            self.assertIn(review_task["task_id"], review_ids)
            self.assertIn(session_id, stale_run_ids)
            self.assertIn(recovery_task["task_id"], blocked_recovery_ids)

            conflict_subtypes = {item["subtype"] for item in payload["buckets"]["policy_conflicts"]}
            self.assertIn("autopilot_paused_queue", conflict_subtypes)
            self.assertIn("autopilot_zero_capacity", conflict_subtypes)
            self.assertIn("brownfield_review_pending", conflict_subtypes)

            notification_item = payload["buckets"]["notification_failures"][0]
            self.assertEqual(notification_item["subtype"], "retry_exhausted")
            self.assertEqual(notification_item["metadata"]["delivery_state"], "retry_exhausted")
            self.assertTrue(notification_item["metadata"]["retry_budget_exhausted"])


if __name__ == "__main__":
    unittest.main()
