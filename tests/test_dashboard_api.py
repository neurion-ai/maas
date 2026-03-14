import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.services.bootstrap import bootstrap_project


class DashboardApiTest(unittest.TestCase):
    def test_overview_and_goal_tree_shapes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Dashboard Test", description="Dashboard test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            overview = client.get("/api/overview")
            self.assertEqual(overview.status_code, 200)
            overview_payload = overview.json()
            self.assertEqual(overview_payload["project"]["name"], "Dashboard Test")
            self.assertGreaterEqual(overview_payload["summary"]["tasks_total"], 1)
            self.assertIn("active_work", overview_payload)
            self.assertIn("recent_activity", overview_payload)

            goal_tree = client.get("/api/goals/tree")
            self.assertEqual(goal_tree.status_code, 200)
            goal_tree_payload = goal_tree.json()
            self.assertGreaterEqual(goal_tree_payload["total_goals"], 1)
            self.assertGreaterEqual(len(goal_tree_payload["roots"]), 1)
            self.assertIn("children", goal_tree_payload["roots"][0])

    def test_agent_roster_is_enriched(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Roster Test", description="Roster test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            roster = client.get("/api/agents")
            self.assertEqual(roster.status_code, 200)
            payload = roster.json()
            self.assertIn("agents", payload)
            self.assertGreaterEqual(len(payload["agents"]), 1)
            self.assertIn("display_name", payload["agents"][0])
            self.assertIn("heartbeat_age_seconds", payload["agents"][0])


if __name__ == "__main__":
    unittest.main()
