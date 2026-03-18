import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect
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
                connection.execute(
                    """
                    INSERT INTO alerts (
                        alert_id, project_id, severity, title, description, status
                    ) VALUES ('alert_portfolio_critical', ?, 'critical', 'Critical provider outage', 'portfolio critical test', 'open')
                    """,
                    (primary_project_id,),
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

            self.assertEqual(secondary["health"], "healthy")
            self.assertEqual(secondary["open_alerts"], 0)
            self.assertEqual(secondary["blocked_tasks"], 0)


if __name__ == "__main__":
    unittest.main()
