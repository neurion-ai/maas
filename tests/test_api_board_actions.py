import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.services.bootstrap import bootstrap_project
from maas.services.lifecycle import end_session, start_session


class BoardApiActionsTest(unittest.TestCase):
    def test_board_filters_and_review_action(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="API Test", description="API board actions", project_type="custom")
            client = TestClient(create_app(tmpdir))

            response = client.get("/api/board", params={"review_only": "true"})
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["summary"]["review_tasks"], 1)
            self.assertEqual(payload["summary"]["total_tasks"], 1)
            self.assertTrue(payload["selected_filters"]["review_only"])

            review_task_id = payload["columns"][3]["tasks"][0]["task_id"]
            action_response = client.post(
                "/api/tasks/{0}/actions/review".format(review_task_id),
                json={"actor_id": "agent_reviewer", "decision": "approve"},
            )
            self.assertEqual(action_response.status_code, 200)

            after_response = client.get("/api/board", params={"search": "Validate seeded lifecycle semantics"})
            self.assertEqual(after_response.status_code, 200)
            after_payload = after_response.json()
            matching_cards = [
                task
                for column in after_payload["columns"]
                for task in column["tasks"]
                if task["task_id"] == review_task_id
            ]
            self.assertEqual(len(matching_cards), 1)
            self.assertEqual(matching_cards[0]["status"], "done")

    def test_rejected_review_task_returns_to_assignable_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Reject Test", description="Reject review path", project_type="custom")
            client = TestClient(create_app(tmpdir))

            response = client.get("/api/board", params={"review_only": "true"})
            self.assertEqual(response.status_code, 200)
            review_task_id = response.json()["columns"][3]["tasks"][0]["task_id"]

            reject_response = client.post(
                "/api/tasks/{0}/actions/review".format(review_task_id),
                json={"actor_id": "agent_reviewer", "decision": "reject"},
            )
            self.assertEqual(reject_response.status_code, 200)

            after_response = client.get("/api/board", params={"search": "Validate seeded lifecycle semantics"})
            self.assertEqual(after_response.status_code, 200)
            matching_cards = [
                task
                for column in after_response.json()["columns"]
                for task in column["tasks"]
                if task["task_id"] == review_task_id
            ]
            self.assertEqual(len(matching_cards), 1)
            self.assertEqual(matching_cards[0]["status"], "planned")
            self.assertEqual(matching_cards[0]["review_state"], "changes_requested")

    def test_pause_resume_and_reprioritize_actions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Steering Test", description="Operator actions", project_type="custom")
            client = TestClient(create_app(tmpdir))

            board_response = client.get("/api/board")
            self.assertEqual(board_response.status_code, 200)
            payload = board_response.json()
            in_progress_task = payload["columns"][2]["tasks"][0]

            pause_response = client.post(
                "/api/agents/agent_builder/actions/pause",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(pause_response.status_code, 200)

            blocked_board = client.get("/api/board", params={"blocked_only": "true"}).json()
            blocked_task_ids = {
                task["task_id"]
                for column in blocked_board["columns"]
                for task in column["tasks"]
            }
            self.assertIn(in_progress_task["task_id"], blocked_task_ids)

            reprioritize_response = client.post(
                "/api/tasks/{0}/actions/reprioritize".format(in_progress_task["task_id"]),
                json={"actor_id": "agent_allocator", "priority": 97},
            )
            self.assertEqual(reprioritize_response.status_code, 200)

            resume_response = client.post(
                "/api/agents/agent_builder/actions/resume",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(resume_response.status_code, 200)

            search_payload = client.get(
                "/api/board",
                params={"search": "Implement FastAPI board endpoint"},
            ).json()
            matching_cards = [
                task
                for column in search_payload["columns"]
                for task in column["tasks"]
                if task["task_id"] == in_progress_task["task_id"]
            ]
            self.assertEqual(len(matching_cards), 1)
            self.assertEqual(matching_cards[0]["priority"], 97)
            self.assertEqual(matching_cards[0]["status"], "in_progress")

    def test_reassign_and_halt_actions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Reassign Halt Test", description="Reassign and halt", project_type="custom")
            client = TestClient(create_app(tmpdir))

            board_payload = client.get("/api/board", params={"search": "Define project workspace contracts"}).json()
            task = [
                task
                for column in board_payload["columns"]
                for task in column["tasks"]
                if task["title"] == "Define project workspace contracts"
            ][0]

            reassign_response = client.post(
                "/api/tasks/{0}/actions/reassign".format(task["task_id"]),
                json={"actor_id": "agent_allocator", "agent_id": "agent_builder"},
            )
            self.assertEqual(reassign_response.status_code, 200)

            after_reassign = client.get("/api/board", params={"search": "Define project workspace contracts"}).json()
            reassigned_card = [
                task
                for column in after_reassign["columns"]
                for task in column["tasks"]
                if task["title"] == "Define project workspace contracts"
            ][0]
            self.assertEqual(reassigned_card["agent"]["id"], "agent_builder")
            self.assertTrue(
                all(grant["agent_id"] == "agent_builder" for grant in reassigned_card["capabilities"])
            )

            in_progress_board = client.get("/api/board", params={"search": "Implement FastAPI board endpoint"}).json()
            in_progress_task = [
                task
                for column in in_progress_board["columns"]
                for task in column["tasks"]
                if task["title"] == "Implement FastAPI board endpoint"
            ][0]

            invalid_reassign_response = client.post(
                "/api/tasks/{0}/actions/reassign".format(in_progress_task["task_id"]),
                json={"actor_id": "agent_allocator", "agent_id": "agent_researcher"},
            )
            self.assertEqual(invalid_reassign_response.status_code, 400)

            halt_response = client.post(
                "/api/tasks/{0}/actions/halt".format(in_progress_task["task_id"]),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(halt_response.status_code, 200)

            halted_board = client.get("/api/board", params={"search": "Implement FastAPI board endpoint"}).json()
            halted_card = [
                task
                for column in halted_board["columns"]
                for task in column["tasks"]
                if task["title"] == "Implement FastAPI board endpoint"
            ][0]
            self.assertEqual(halted_card["status"], "cancelled")
            self.assertEqual(halted_card["review_state"], "halted_by_operator")
            self.assertEqual(halted_card["capabilities"], [])

    def test_recover_failed_task_returns_it_to_planned_queue(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Recover Task Test", description="Recover failure-blocked task", project_type="custom")
            connection = connect(result["paths"])
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()["task_id"]
                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_allocator",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting recovery test",
                )
                end_session(connection, session_id, "failed", "Recoverable failure")
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            recover_response = client.post(
                "/api/tasks/{0}/actions/recover".format(task_id),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(recover_response.status_code, 200)
            self.assertEqual(recover_response.json()["status"], "planned")

            connection = connect(project_paths(tmpdir))
            try:
                recovered_task = connection.execute(
                    """
                    SELECT status, assigned_agent_id, review_state, progress_pct, last_heartbeat_at
                    FROM tasks
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
            finally:
                connection.close()

            capabilities_response = client.get("/api/tasks/{0}/capabilities".format(task_id))
            self.assertEqual(capabilities_response.status_code, 200)
            self.assertEqual(recovered_task["status"], "planned")
            self.assertIsNone(recovered_task["assigned_agent_id"])
            self.assertIsNone(recovered_task["review_state"])
            self.assertEqual(recovered_task["progress_pct"], 0)
            self.assertIsNone(recovered_task["last_heartbeat_at"])
            self.assertEqual(capabilities_response.json()["grants"], [])

    def test_recover_rejects_non_failure_blocked_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Recover Guard Test", description="Reject invalid recover path", project_type="custom")
            client = TestClient(create_app(tmpdir))

            pause_response = client.post(
                "/api/agents/agent_builder/actions/pause",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(pause_response.status_code, 200)

            blocked_task = client.get("/api/board", params={"search": "Implement FastAPI board endpoint"}).json()
            task_id = [
                task
                for column in blocked_task["columns"]
                for task in column["tasks"]
                if task["title"] == "Implement FastAPI board endpoint"
            ][0]["task_id"]

            recover_response = client.post(
                "/api/tasks/{0}/actions/recover".format(task_id),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(recover_response.status_code, 400)

    def test_halt_preserves_paused_agent_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Pause Halt Test", description="Pause then halt", project_type="custom")
            client = TestClient(create_app(tmpdir))

            pause_response = client.post(
                "/api/agents/agent_builder/actions/pause",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(pause_response.status_code, 200)

            halted_task = client.get("/api/board", params={"search": "Implement FastAPI board endpoint"}).json()
            blocked_card = [
                task
                for column in halted_task["columns"]
                for task in column["tasks"]
                if task["title"] == "Implement FastAPI board endpoint"
            ][0]

            halt_response = client.post(
                "/api/tasks/{0}/actions/halt".format(blocked_card["task_id"]),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(halt_response.status_code, 200)

            agents_payload = client.get("/api/agents").json()
            builder = [agent for agent in agents_payload["agents"] if agent["agent_id"] == "agent_builder"][0]
            self.assertEqual(builder["status"], "paused")
            self.assertIsNone(builder["current_task_id"])

    def test_denied_board_action_returns_403_and_is_audited(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Permission Test", description="Permission test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            board_payload = client.get("/api/board", params={"review_only": "true"}).json()
            review_task = board_payload["columns"][3]["tasks"][0]

            denied_response = client.post(
                "/api/tasks/{0}/actions/review".format(review_task["task_id"]),
                json={"actor_id": "agent_builder", "decision": "approve"},
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
            self.assertIn("review_task", audit_row["detail_json"])

    def test_spoofed_system_actor_is_denied(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Spoof Test", description="Spoof test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            board_payload = client.get("/api/board", params={"review_only": "true"}).json()
            review_task = board_payload["columns"][3]["tasks"][0]

            denied_response = client.post(
                "/api/tasks/{0}/actions/review".format(review_task["task_id"]),
                json={"actor_id": "system_supervisor", "decision": "approve"},
            )
            self.assertEqual(denied_response.status_code, 403)

    def test_task_capabilities_endpoint_returns_active_grants(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Capability Endpoint Test", description="Capability endpoint", project_type="custom")
            client = TestClient(create_app(tmpdir))

            board_payload = client.get("/api/board", params={"search": "Wire the scheduler and board read model"}).json()
            task = [
                task
                for column in board_payload["columns"]
                for task in column["tasks"]
                if task["title"] == "Wire the scheduler and board read model"
            ][0]

            response = client.get("/api/tasks/{0}/capabilities".format(task["task_id"]))
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["task_id"], task["task_id"])
            self.assertEqual(len(payload["grants"]), 5)


if __name__ == "__main__":
    unittest.main()
