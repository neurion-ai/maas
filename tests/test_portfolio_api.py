import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect
from maas.ids import generate_id
from maas.services.bootstrap import bootstrap_project
from maas.services.projects import create_project


class PortfolioApiTest(unittest.TestCase):
    def test_portfolio_rolls_up_cross_project_health(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Portfolio Primary",
                description="portfolio primary",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                primary_project_id = connection.execute(
                    "SELECT project_id FROM projects ORDER BY created_at ASC LIMIT 1"
                ).fetchone()["project_id"]
                second_project = create_project(
                    connection,
                    result["paths"],
                    actor_id="agent_allocator",
                    name="Portfolio Secondary",
                    description="portfolio secondary",
                    project_type="custom",
                    mode="greenfield",
                )
                second_project_id = second_project["project"]["project_id"]
                second_task_id = connection.execute(
                    """
                    SELECT task_id
                    FROM tasks
                    WHERE project_id = ?
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (second_project_id,),
                ).fetchone()["task_id"]
                second_agent_id = connection.execute(
                    "SELECT agent_id FROM agents WHERE project_id = ? ORDER BY created_at ASC LIMIT 1",
                    (second_project_id,),
                ).fetchone()["agent_id"]
                connection.execute(
                    """
                    INSERT INTO alerts (
                        alert_id, project_id, severity, title, description, status
                    ) VALUES ('alert_portfolio_critical', ?, 'critical', 'Critical provider outage', 'portfolio critical test', 'open')
                    """,
                    (primary_project_id,),
                )
                connection.execute(
                    """
                    INSERT INTO escalation_queue (
                        escalation_id, project_id, requested_by, action_type, resource_type, resource_id, payload_json, reason, status
                    ) VALUES (?, ?, 'agent_allocator', 'halt_task', 'task', ?, '{}', 'portfolio escalation', 'open')
                    """,
                    (generate_id("esc"), primary_project_id, second_task_id),
                )
                connection.execute(
                    """
                    INSERT INTO provider_job_queue (
                        job_id, project_id, provider_id, task_id, agent_id, status, queued_by
                    ) VALUES (?, ?, 'python_script', ?, ?, 'queued', 'agent_allocator')
                    """,
                    (generate_id("job"), second_project_id, second_task_id, second_agent_id),
                )
                connection.execute(
                    """
                    INSERT INTO dead_letter_queue (
                        dlq_id, project_id, task_id, reason, detail_json, status
                    ) VALUES (?, ?, ?, 'retry_budget_exhausted', '{}', 'open')
                    """,
                    (generate_id("dlq"), second_project_id, second_task_id),
                )
                primary_failure_task_id = connection.execute(
                    """
                    SELECT task_id
                    FROM tasks
                    WHERE project_id = ?
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (primary_project_id,),
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'blocked', review_state = 'awaiting_dependency'
                    WHERE task_id = ?
                    """,
                    (primary_failure_task_id,),
                )
                connection.execute(
                    """
                    INSERT INTO failure_log (
                        failure_id, project_id, task_id, session_id, agent_id, failure_type, summary, detail_json
                    ) VALUES (?, ?, ?, NULL, NULL, 'session_failed', 'portfolio failure test', '{}')
                    """,
                    (generate_id("fail"), primary_project_id, primary_failure_task_id),
                )
                connection.execute(
                    "UPDATE alerts SET status = 'resolved' WHERE project_id = ?",
                    (second_project_id,),
                )
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'done',
                        review_state = NULL,
                        assigned_agent_id = NULL,
                        next_retry_at = NULL,
                        next_retry_reason = NULL
                    WHERE project_id = ?
                      AND status IN ('planned', 'ready', 'assigned', 'blocked', 'review')
                    """,
                    (second_project_id,),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.get("/api/portfolio")
            self.assertEqual(response.status_code, 200)
            payload = response.json()

            self.assertEqual(payload["summary"]["active_projects"], 2)
            self.assertEqual(payload["summary"]["archived_projects"], 0)
            self.assertEqual(len(payload["projects"]), 2)

            primary = next(item for item in payload["projects"] if item["project_id"] == primary_project_id)
            secondary = next(item for item in payload["projects"] if item["project_id"] == second_project_id)

            self.assertEqual(primary["health"], "critical")
            self.assertGreaterEqual(primary["critical_alerts"], 1)
            self.assertGreaterEqual(primary["provider_readiness"]["ready"], 1)

            self.assertEqual(secondary["health"], "critical")
            self.assertEqual(secondary["open_alerts"], 0)
            self.assertEqual(secondary["blocked_tasks"], 0)
            self.assertIn("review_queue_count", primary)
            self.assertIn("blocked_failure_count", primary)
            self.assertIn("suspect_run_count", primary)
            self.assertIn("stale_agent_count", primary)
            self.assertEqual(payload["summary"]["open_escalations"], 1)
            self.assertEqual(payload["summary"]["queued_provider_jobs"], 1)
            self.assertEqual(len(payload["command_center"]["open_escalations"]), 1)
            self.assertEqual(len(payload["command_center"]["queued_provider_jobs"]), 1)
            self.assertEqual(len(payload["command_center"]["open_dead_letter_entries"]), 1)
            self.assertIn("review_queue", payload["summary"])
            self.assertIn("blocked_failures", payload["summary"])
            self.assertIn("suspect_runs", payload["summary"])
            self.assertIn("stale_agents", payload["summary"])
            self.assertIn("review_queue", payload["command_center"])
            self.assertIn("blocked_failures", payload["command_center"])
            self.assertIn("suspect_runs", payload["command_center"])
            self.assertEqual(payload["command_center"]["open_escalations"][0]["project_name"], "Portfolio Primary")
            self.assertEqual(payload["command_center"]["queued_provider_jobs"][0]["project_name"], "Portfolio Secondary")
            self.assertEqual(primary["blocked_failure_count"], 1)
            self.assertEqual(payload["summary"]["blocked_failures"], len(payload["command_center"]["blocked_failures"]))


if __name__ == "__main__":
    unittest.main()
