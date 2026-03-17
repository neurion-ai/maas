import json
import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.services.bootstrap import bootstrap_project
from maas.services.lifecycle import end_session, start_session


class BoardApiActionsTest(unittest.TestCase):
    def _seed_brownfield_repo(self, project_root):
        import os

        os.makedirs(os.path.join(project_root, "src"), exist_ok=True)
        with open(os.path.join(project_root, "README.md"), "w", encoding="utf-8") as handle:
            handle.write("# Imported Project\n")
        with open(os.path.join(project_root, "src", "app.py"), "w", encoding="utf-8") as handle:
            handle.write("print('hello')\n")

    def _update_recovery_config(self, project_root, **recovery_updates):
        connection = connect(project_paths(project_root))
        try:
            project = connection.execute(
                "SELECT project_id, config_json FROM projects LIMIT 1"
            ).fetchone()
            config = json.loads(project["config_json"] or "{}")
            recovery = dict(config.get("recovery") or {})
            recovery.update(recovery_updates)
            config["recovery"] = recovery
            connection.execute(
                "UPDATE projects SET config_json = ? WHERE project_id = ?",
                (json.dumps(config), project["project_id"]),
            )
            connection.commit()
        finally:
            connection.close()

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

    def test_approving_brownfield_review_releases_gated_tasks_and_resolves_alert(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._seed_brownfield_repo(tmpdir)
            bootstrap_project(tmpdir, name="Brownfield Approval Test", description="brownfield review", project_type="custom")
            client = TestClient(create_app(tmpdir))

            review_payload = client.get("/api/board", params={"search": "Review imported project understanding"}).json()
            review_task = [
                task
                for column in review_payload["columns"]
                for task in column["tasks"]
                if task["title"] == "Review imported project understanding"
            ][0]

            response = client.post(
                f"/api/tasks/{review_task['task_id']}/actions/review",
                json={"actor_id": "agent_reviewer", "decision": "approve"},
            )
            self.assertEqual(response.status_code, 200)

            connection = connect(project_paths(tmpdir))
            try:
                config = json.loads(connection.execute("SELECT config_json FROM projects LIMIT 1").fetchone()["config_json"])
                released_tasks = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM tasks
                    WHERE review_state = 'awaiting_onboarding_approval'
                    """
                ).fetchone()["count"]
                open_alerts = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM alerts
                    WHERE title = 'Brownfield onboarding review pending' AND status != 'resolved'
                    """
                ).fetchone()["count"]
                ready_or_planned = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM tasks
                    WHERE title != 'Review imported project understanding'
                      AND status IN ('ready', 'planned', 'blocked')
                    """
                ).fetchone()["count"]
            finally:
                connection.close()

            self.assertEqual(config["onboarding"]["review_status"], "approved")
            self.assertEqual(released_tasks, 0)
            self.assertEqual(open_alerts, 0)
            self.assertEqual(ready_or_planned, 4)

    def test_rejecting_brownfield_review_keeps_imported_tasks_gated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._seed_brownfield_repo(tmpdir)
            bootstrap_project(tmpdir, name="Brownfield Reject Test", description="brownfield reject", project_type="custom")
            client = TestClient(create_app(tmpdir))

            review_payload = client.get("/api/board", params={"search": "Review imported project understanding"}).json()
            review_task = [
                task
                for column in review_payload["columns"]
                for task in column["tasks"]
                if task["title"] == "Review imported project understanding"
            ][0]

            response = client.post(
                f"/api/tasks/{review_task['task_id']}/actions/review",
                json={"actor_id": "agent_reviewer", "decision": "reject"},
            )
            self.assertEqual(response.status_code, 200)

            board_payload = client.get("/api/board", params={"search": "Review imported project understanding"}).json()
            updated_review_task = [
                task
                for column in board_payload["columns"]
                for task in column["tasks"]
                if task["title"] == "Review imported project understanding"
            ][0]

            connection = connect(project_paths(tmpdir))
            try:
                config = json.loads(connection.execute("SELECT config_json FROM projects LIMIT 1").fetchone()["config_json"])
                gated_tasks = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM tasks
                    WHERE review_state = 'awaiting_onboarding_approval'
                      AND status = 'blocked'
                    """
                ).fetchone()["count"]
            finally:
                connection.close()

            self.assertEqual(updated_review_task["status"], "review")
            self.assertEqual(updated_review_task["review_state"], "changes_requested")
            self.assertEqual(config["onboarding"]["review_status"], "changes_requested")
            self.assertEqual(gated_tasks, 4)

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

    def test_set_task_retry_limit_updates_board_card_and_can_clear(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Retry Limit Test", description="Retry limit steering", project_type="custom")
            client = TestClient(create_app(tmpdir))

            board_payload = client.get("/api/board", params={"search": "Wire the scheduler and board read model"}).json()
            task = [
                item
                for column in board_payload["columns"]
                for item in column["tasks"]
                if item["title"] == "Wire the scheduler and board read model"
            ][0]

            set_response = client.post(
                "/api/tasks/{0}/actions/set-retry-limit".format(task["task_id"]),
                json={"actor_id": "agent_allocator", "auto_retry_limit": 3},
            )
            self.assertEqual(set_response.status_code, 200)
            self.assertEqual(set_response.json()["auto_retry_limit"], 3)

            after_set = client.get("/api/board", params={"search": "Wire the scheduler and board read model"}).json()
            updated_task = [
                item
                for column in after_set["columns"]
                for item in column["tasks"]
                if item["task_id"] == task["task_id"]
            ][0]
            self.assertEqual(updated_task["auto_retry_limit"], 3)

            clear_response = client.post(
                "/api/tasks/{0}/actions/set-retry-limit".format(task["task_id"]),
                json={"actor_id": "agent_allocator", "auto_retry_limit": None},
            )
            self.assertEqual(clear_response.status_code, 200)
            self.assertIsNone(clear_response.json()["auto_retry_limit"])

            after_clear = client.get("/api/board", params={"search": "Wire the scheduler and board read model"}).json()
            cleared_task = [
                item
                for column in after_clear["columns"]
                for item in column["tasks"]
                if item["task_id"] == task["task_id"]
            ][0]
            self.assertIsNone(cleared_task["auto_retry_limit"])

    def test_set_task_retry_limit_rejects_invalid_values_and_permissions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Retry Limit Test", description="Retry limit steering", project_type="custom")
            client = TestClient(create_app(tmpdir))
            task_payload = client.get("/api/board", params={"search": "Wire the scheduler and board read model"}).json()
            task_id = [
                item["task_id"]
                for column in task_payload["columns"]
                for item in column["tasks"]
                if item["title"] == "Wire the scheduler and board read model"
            ][0]

            invalid_response = client.post(
                "/api/tasks/{0}/actions/set-retry-limit".format(task_id),
                json={"actor_id": "agent_allocator", "auto_retry_limit": -1},
            )
            self.assertEqual(invalid_response.status_code, 400)
            self.assertIn("Retry limit", invalid_response.json()["detail"])

            forbidden_response = client.post(
                "/api/tasks/{0}/actions/set-retry-limit".format(task_id),
                json={"actor_id": "agent_researcher", "auto_retry_limit": 2},
            )
            self.assertEqual(forbidden_response.status_code, 403)

    def test_release_retry_backoff_returns_task_to_ready_when_unblocked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Release Backoff Test", description="Release retry backoff", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'planned',
                        review_state = 'retry_backoff',
                        next_retry_at = '2099-01-01 00:00:00',
                        next_retry_reason = 'session_failed'
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.post(
                "/api/tasks/{0}/actions/release-retry-backoff".format(task_id),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "ready")
            self.assertIsNone(payload["review_state"])
            self.assertIsNone(payload["next_retry_at"])
            self.assertIsNone(payload["next_retry_reason"])

    def test_release_retry_backoff_respects_dependency_blockers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Release Backoff Blocked Test", description="Release retry backoff blocked", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'planned',
                        review_state = 'retry_backoff',
                        next_retry_at = '2099-01-01 00:00:00',
                        next_retry_reason = 'session_timed_out'
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.post(
                "/api/tasks/{0}/actions/release-retry-backoff".format(task_id),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["review_state"], "blocked_by_dependency")
            self.assertIsNone(payload["next_retry_at"])
            self.assertIsNone(payload["next_retry_reason"])

    def test_reset_retry_state_clears_history_and_releases_ready_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Reset Retry State Test", description="Reset retry state", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'planned',
                        review_state = 'retry_backoff',
                        retry_count = 2,
                        last_retry_at = CURRENT_TIMESTAMP,
                        last_retry_reason = 'session_failed',
                        next_retry_at = '2099-01-01 00:00:00',
                        next_retry_reason = 'session_failed'
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.post(
                "/api/tasks/{0}/actions/reset-retry-state".format(task_id),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "ready")
            self.assertIsNone(payload["review_state"])
            self.assertEqual(payload["retry_count"], 0)
            self.assertIsNone(payload["last_retry_at"])
            self.assertIsNone(payload["last_retry_reason"])
            self.assertIsNone(payload["next_retry_at"])
            self.assertIsNone(payload["next_retry_reason"])

    def test_reset_retry_state_rejects_clean_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Reset Retry State Clean Test", description="Reset retry state clean", project_type="custom")
            client = TestClient(create_app(tmpdir))
            board_payload = client.get("/api/board", params={"search": "Wire the scheduler and board read model"}).json()
            task_id = [
                item
                for column in board_payload["columns"]
                for item in column["tasks"]
                if item["title"] == "Wire the scheduler and board read model"
            ][0]["task_id"]

            response = client.post(
                "/api/tasks/{0}/actions/reset-retry-state".format(task_id),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("no retry state", response.json()["detail"])

    def test_mark_for_replan_and_finish_replan_move_task_through_replanning_queue(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Replan Task Test", description="Replan task steering", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'planned',
                        review_state = 'retry_backoff',
                        retry_count = 2,
                        next_retry_at = '2099-01-01 00:00:00',
                        next_retry_reason = 'session_failed'
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            mark_response = client.post(
                f"/api/tasks/{task_id}/actions/mark-for-replan",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(mark_response.status_code, 200)
            self.assertEqual(mark_response.json()["status"], "blocked")
            self.assertEqual(mark_response.json()["review_state"], "needs_replan")

            connection = connect(project_paths(tmpdir))
            try:
                task_after_mark = connection.execute(
                    """
                    SELECT status, review_state, assigned_agent_id, next_retry_at, next_retry_reason
                    FROM tasks
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(task_after_mark["status"], "blocked")
            self.assertEqual(task_after_mark["review_state"], "needs_replan")
            self.assertIsNone(task_after_mark["assigned_agent_id"])
            self.assertIsNone(task_after_mark["next_retry_at"])
            self.assertIsNone(task_after_mark["next_retry_reason"])

            finish_response = client.post(
                f"/api/tasks/{task_id}/actions/finish-replan",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(finish_response.status_code, 200)
            self.assertEqual(finish_response.json()["status"], "ready")
            self.assertIsNone(finish_response.json()["review_state"])

            connection = connect(project_paths(tmpdir))
            try:
                task_after_finish = connection.execute(
                    "SELECT status, review_state FROM tasks WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(task_after_finish["status"], "ready")
            self.assertIsNone(task_after_finish["review_state"])

    def test_mark_for_replan_allows_tasks_waiting_only_on_next_retry_deadline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Replan Task Test", description="Replan task steering", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Define project workspace contracts'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'planned',
                        review_state = NULL,
                        retry_count = 0,
                        next_retry_at = '2099-01-01 00:00:00',
                        next_retry_reason = 'recover_and_requeue'
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.post(
                f"/api/tasks/{task_id}/actions/mark-for-replan",
                json={"actor_id": "agent_allocator"},
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "blocked")
            self.assertEqual(response.json()["review_state"], "needs_replan")

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
                session_failed_alert = connection.execute(
                    """
                    SELECT status
                    FROM alerts
                    WHERE title = 'Task session failed'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
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
            self.assertEqual(session_failed_alert["status"], "resolved")

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

    def test_recover_task_resolves_matching_repeated_failure_alerts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Recover Alert Resolution Test",
                description="Resolve repeated failure alert when recovering task",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()["task_id"]
                other_task = connection.execute(
                    "SELECT task_id, title FROM tasks WHERE title = 'Define project workspace contracts'"
                ).fetchone()
                connection.execute(
                    """
                    INSERT INTO alerts (
                        alert_id, project_id, severity, title, description, status
                    ) VALUES ('alert_other_task', ?, 'critical', 'Repeated task failures', ?, 'open')
                    """,
                    (
                        project_id,
                        "Task {0} ({1}) has failed 2 times. Latest failure: refer to {2}".format(
                            other_task["task_id"],
                            other_task["title"],
                            task_id,
                        ),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO failure_log (
                        failure_id, project_id, task_id, failure_type, summary, detail_json
                    ) VALUES ('fail_previous', ?, ?, 'session_failed', 'Earlier failure', '{}')
                    """,
                    (project_id, task_id),
                )
                connection.commit()

                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_allocator",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting repeated failure test",
                )
                end_session(connection, session_id, "failed", "Repeated failure")

                repeated_alerts = [
                    dict(row)
                    for row in connection.execute(
                        """
                        SELECT alert_id, description, status
                        FROM alerts
                        WHERE title = 'Repeated task failures'
                        ORDER BY created_at ASC
                        """
                    ).fetchall()
                ]
                primary_alert = [
                    alert for alert in repeated_alerts if alert["description"].startswith("Task {0} (".format(task_id))
                ][0]
                other_alert = [
                    alert
                    for alert in repeated_alerts
                    if alert["description"].startswith("Task {0} (".format(other_task["task_id"]))
                ][0]
            finally:
                connection.close()

            self.assertEqual(primary_alert["status"], "open")
            self.assertEqual(other_alert["status"], "open")

            client = TestClient(create_app(tmpdir))
            recover_response = client.post(
                "/api/tasks/{0}/actions/recover".format(task_id),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(recover_response.status_code, 200)

            alerts_payload = client.get("/api/alerts").json()
            matching_primary = [alert for alert in alerts_payload["alerts"] if alert["alert_id"] == primary_alert["alert_id"]][0]
            matching_other = [alert for alert in alerts_payload["alerts"] if alert["alert_id"] == other_alert["alert_id"]][0]
            self.assertEqual(matching_primary["status"], "resolved")
            self.assertEqual(matching_other["status"], "open")

    def test_resolve_repeated_failures_action_resolves_incident_without_recovering_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Repeated Failure Triage Test",
                description="Resolve repeated failure incident without recovering task",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    INSERT INTO failure_log (
                        failure_id, project_id, task_id, failure_type, summary, detail_json
                    ) VALUES ('fail_previous', ?, ?, 'session_failed', 'Earlier failure', '{}')
                    """,
                    (project_id, task_id),
                )
                connection.commit()

                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_allocator",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting repeated failure triage test",
                )
                end_session(connection, session_id, "failed", "Repeated failure")

                repeated_alert = connection.execute(
                    """
                    SELECT alert_id, status
                    FROM alerts
                    WHERE title = 'Repeated task failures'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(repeated_alert["status"], "open")

            client = TestClient(create_app(tmpdir))
            resolve_response = client.post(
                "/api/tasks/{0}/actions/resolve-repeated-failures".format(task_id),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(resolve_response.status_code, 200)
            self.assertEqual(resolve_response.json()["resolved_count"], 1)
            self.assertEqual(resolve_response.json()["status"], "blocked")

            connection = connect(project_paths(tmpdir))
            try:
                task = connection.execute(
                    "SELECT status, review_state FROM tasks WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                resolved_alert = connection.execute(
                    """
                    SELECT status
                    FROM alerts
                    WHERE alert_id = ?
                    """,
                    (repeated_alert["alert_id"],),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(task["status"], "blocked")
            self.assertEqual(task["review_state"], "session_failed")
            self.assertEqual(resolved_alert["status"], "resolved")

    def test_recover_and_requeue_applies_retry_backoff_before_returning_to_ready_queue(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Recover And Requeue Test",
                description="Recover failure-blocked task directly to ready",
                project_type="custom",
            )
            self._update_recovery_config(
                tmpdir,
                recover_and_requeue_cooldown_seconds=30,
                retry_backoff_multiplier=2,
                retry_backoff_max_seconds=900,
            )
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
                    status_message="Starting recover-and-requeue test",
                )
                end_session(connection, session_id, "failed", "Recoverable failure")
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            recover_response = client.post(
                "/api/tasks/{0}/actions/recover-and-requeue".format(task_id),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(recover_response.status_code, 200)
            self.assertEqual(recover_response.json()["status"], "planned")
            self.assertEqual(recover_response.json()["review_state"], "retry_backoff")
            self.assertEqual(recover_response.json()["next_retry_reason"], "recover_and_requeue")
            self.assertIsNotNone(recover_response.json()["next_retry_at"])

            connection = connect(project_paths(tmpdir))
            try:
                recovered_task = connection.execute(
                    """
                    SELECT
                        status,
                        assigned_agent_id,
                        review_state,
                        progress_pct,
                        last_heartbeat_at,
                        next_retry_at,
                        next_retry_reason
                    FROM tasks
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
                session_failed_alert = connection.execute(
                    """
                    SELECT status
                    FROM alerts
                    WHERE title = 'Task session failed'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ).fetchone()
                connection.execute(
                    """
                    UPDATE tasks
                    SET next_retry_at = '2000-01-01 00:00:00'
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
                connection.commit()
            finally:
                connection.close()

            refresh_response = client.post("/api/tasks/actions/refresh-ready")
            self.assertEqual(refresh_response.status_code, 200)

            connection = connect(project_paths(tmpdir))
            try:
                task_after_cooldown = connection.execute(
                    """
                    SELECT status, review_state, next_retry_at, next_retry_reason
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
            self.assertEqual(recovered_task["review_state"], "retry_backoff")
            self.assertEqual(recovered_task["progress_pct"], 0)
            self.assertIsNone(recovered_task["last_heartbeat_at"])
            self.assertIsNotNone(recovered_task["next_retry_at"])
            self.assertEqual(recovered_task["next_retry_reason"], "recover_and_requeue")
            self.assertEqual(capabilities_response.json()["grants"], [])
            self.assertEqual(session_failed_alert["status"], "resolved")
            self.assertEqual(task_after_cooldown["status"], "ready")
            self.assertIsNone(task_after_cooldown["review_state"])
            self.assertIsNone(task_after_cooldown["next_retry_at"])
            self.assertIsNone(task_after_cooldown["next_retry_reason"])

    def test_recover_and_requeue_without_cooldown_returns_ready_without_retry_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Recover And Requeue No Cooldown Test",
                description="Recover failure-blocked task without retry cooldown",
                project_type="custom",
            )
            self._update_recovery_config(
                tmpdir,
                recover_and_requeue_cooldown_seconds=0,
                retry_backoff_multiplier=2,
                retry_backoff_max_seconds=900,
            )
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
                    status_message="Starting recover-and-requeue no cooldown test",
                )
                end_session(connection, session_id, "failed", "Recoverable failure")
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            recover_response = client.post(
                "/api/tasks/{0}/actions/recover-and-requeue".format(task_id),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(recover_response.status_code, 200)
            self.assertEqual(recover_response.json()["status"], "ready")
            self.assertIsNone(recover_response.json()["review_state"])
            self.assertIsNone(recover_response.json()["next_retry_at"])
            self.assertIsNone(recover_response.json()["next_retry_reason"])

            connection = connect(project_paths(tmpdir))
            try:
                recovered_task = connection.execute(
                    """
                    SELECT status, review_state, next_retry_at, next_retry_reason
                    FROM tasks
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(recovered_task["status"], "ready")
            self.assertIsNone(recovered_task["review_state"])
            self.assertIsNone(recovered_task["next_retry_at"])
            self.assertIsNone(recovered_task["next_retry_reason"])

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
