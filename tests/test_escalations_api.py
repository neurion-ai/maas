import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.services.bootstrap import bootstrap_project


class EscalationsApiTest(unittest.TestCase):
    def _project_id(self, client):
        return client.get("/api/overview").json()["project"]["project_id"]

    def _task_by_title(self, client, title):
        board_payload = client.get("/api/board", params={"search": title}).json()
        return [
            item
            for column in board_payload["columns"]
            for item in column["tasks"]
            if item["title"] == title
        ][0]

    def test_request_and_approve_halt_escalation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Escalation Test", description="Escalation test", project_type="custom")
            client = TestClient(create_app(tmpdir))
            project_id = self._project_id(client)
            task = self._task_by_title(client, "Implement FastAPI board endpoint")

            request_response = client.post(
                "/api/escalations/request",
                json={
                    "project_id": project_id,
                    "actor_id": "agent_builder",
                    "action_type": "halt_task",
                    "resource_type": "task",
                    "resource_id": task["task_id"],
                    "reason": "Need operator halt approval",
                    "payload": {},
                },
            )
            self.assertEqual(request_response.status_code, 200)
            escalation_id = request_response.json()["escalation_id"]

            approve_response = client.post(
                "/api/escalations/{0}/actions/approve".format(escalation_id),
                json={"actor_id": "agent_allocator", "resolution_note": "Approved halt"},
            )
            self.assertEqual(approve_response.status_code, 200)

            escalations_payload = client.get("/api/escalations").json()
            self.assertEqual(escalations_payload["summary"]["approved"], 1)
            halted_board = client.get("/api/board", params={"search": "Implement FastAPI board endpoint"}).json()
            halted = [
                item
                for column in halted_board["columns"]
                for item in column["tasks"]
                if item["task_id"] == task["task_id"]
            ][0]
            self.assertEqual(halted["status"], "cancelled")

    def test_reject_escalation_and_permission_gate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Escalation Reject Test", description="Escalation reject test", project_type="custom")
            client = TestClient(create_app(tmpdir))
            project_id = client.get("/api/overview").json()["project"]["project_id"]

            request_response = client.post(
                "/api/escalations/request",
                json={
                    "project_id": project_id,
                    "actor_id": "agent_builder",
                    "action_type": "pause_agent",
                    "resource_type": "agent",
                    "resource_id": "agent_builder",
                    "reason": "Operator decision required",
                    "payload": {},
                },
            )
            self.assertEqual(request_response.status_code, 200)
            escalation_id = request_response.json()["escalation_id"]

            denied_response = client.post(
                "/api/escalations/{0}/actions/reject".format(escalation_id),
                json={"actor_id": "agent_builder", "resolution_note": "Self-reject"},
            )
            self.assertEqual(denied_response.status_code, 403)

            reject_response = client.post(
                "/api/escalations/{0}/actions/reject".format(escalation_id),
                json={"actor_id": "agent_allocator", "resolution_note": "Rejected"},
            )
            self.assertEqual(reject_response.status_code, 200)

            payload = client.get("/api/escalations").json()
            self.assertEqual(payload["summary"]["rejected"], 1)
            self.assertEqual(payload["summary"]["open"], 0)

    def test_reassign_escalation_requires_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Escalation Payload Test", description="Escalation payload test", project_type="custom")
            client = TestClient(create_app(tmpdir))
            project_id = self._project_id(client)
            connection = connect(project_paths(tmpdir))
            try:
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE status = 'ready' LIMIT 1"
                ).fetchone()["task_id"]
            finally:
                connection.close()

            response = client.post(
                "/api/escalations/request",
                json={
                    "project_id": project_id,
                    "actor_id": "agent_builder",
                    "action_type": "reassign_task",
                    "resource_type": "task",
                    "resource_id": task_id,
                    "reason": "Need reassignment",
                    "payload": {},
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("agent_id", response.json()["detail"])

    def test_request_reassign_escalation_requires_existing_target_agent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Escalation Target Test", description="Escalation target test", project_type="custom")
            client = TestClient(create_app(tmpdir))
            project_id = self._project_id(client)
            task = self._task_by_title(client, "Wire the scheduler and board read model")

            response = client.post(
                "/api/escalations/request",
                json={
                    "project_id": project_id,
                    "actor_id": "agent_builder",
                    "action_type": "reassign_task",
                    "resource_type": "task",
                    "resource_id": task["task_id"],
                    "reason": "Need a different worker",
                    "payload": {"agent_id": "agent_missing"},
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("target", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
