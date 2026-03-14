import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.services.bootstrap import bootstrap_project


class AlertsAndLiveApiTest(unittest.TestCase):
    def test_alert_actions_and_live_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Live Test", description="Live test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            live_response = client.get("/api/live")
            self.assertEqual(live_response.status_code, 200)
            live_payload = live_response.json()
            self.assertIn("counts", live_payload)
            self.assertIn("revision", live_payload)

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


if __name__ == "__main__":
    unittest.main()
