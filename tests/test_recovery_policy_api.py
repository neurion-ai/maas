import json
import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.services.bootstrap import bootstrap_project


class RecoveryPolicyApiTest(unittest.TestCase):
    def test_recovery_policy_endpoint_reports_defaults_and_preview(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Recovery Policy Test", description="Recovery policy test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            response = client.get("/api/recovery-policy")
            self.assertEqual(response.status_code, 200)
            payload = response.json()

            self.assertFalse(payload["policy"]["auto_retry_timeout_sessions"])
            self.assertFalse(payload["policy"]["auto_retry_failed_sessions"])
            self.assertEqual(payload["policy"]["max_timed_out_retries"], 1)
            self.assertEqual(payload["policy"]["retry_backoff_multiplier"], 2)
            self.assertEqual(payload["summary"]["retry_backoff_tasks"], 0)
            self.assertEqual(payload["summary"]["open_quarantine_entries"], 0)
            self.assertEqual(
                payload["backoff_preview"]["timed_out_retry_delays"],
                [{"attempt": 1, "delay_seconds": 60}],
            )
            self.assertEqual(
                payload["backoff_preview"]["recover_and_requeue_delays"],
                [
                    {"attempt": 1, "delay_seconds": 30},
                    {"attempt": 2, "delay_seconds": 60},
                    {"attempt": 3, "delay_seconds": 120},
                ],
            )

    def test_recovery_policy_update_persists_and_preserves_provider_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Recovery Policy Test", description="Recovery policy test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project = connection.execute("SELECT project_id, config_json FROM projects LIMIT 1").fetchone()
                config = json.loads(project["config_json"] or "{}")
                config.setdefault("providers", {})["openai_codex"] = {
                    "mode": "codex_cli",
                    "cli_command": "codex",
                    "timeout_seconds": 120,
                    "sandbox": "workspace-write",
                    "model": "gpt-5-codex",
                }
                connection.execute(
                    "UPDATE projects SET config_json = ? WHERE project_id = ?",
                    (json.dumps(config), project["project_id"]),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.post(
                "/api/recovery-policy/actions/set",
                json={
                    "actor_id": "agent_allocator",
                    "policy": {
                        "auto_retry_timeout_sessions": True,
                        "auto_retry_failed_sessions": True,
                        "max_timed_out_retries": 3,
                        "max_failed_session_retries": 2,
                        "timed_out_retry_cooldown_seconds": 30,
                        "failed_session_retry_cooldown_seconds": 20,
                        "recover_and_requeue_cooldown_seconds": 15,
                        "retry_backoff_multiplier": 3,
                        "retry_backoff_max_seconds": 120,
                    },
                },
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["policy"]["auto_retry_timeout_sessions"])
            self.assertTrue(payload["policy"]["auto_retry_failed_sessions"])
            self.assertEqual(payload["policy"]["max_timed_out_retries"], 3)
            self.assertEqual(payload["policy"]["retry_backoff_max_seconds"], 120)
            self.assertEqual(
                payload["backoff_preview"]["timed_out_retry_delays"],
                [
                    {"attempt": 1, "delay_seconds": 30},
                    {"attempt": 2, "delay_seconds": 90},
                    {"attempt": 3, "delay_seconds": 120},
                ],
            )
            self.assertEqual(
                payload["backoff_preview"]["failed_session_retry_delays"],
                [
                    {"attempt": 1, "delay_seconds": 20},
                    {"attempt": 2, "delay_seconds": 60},
                ],
            )

            connection = connect(project_paths(tmpdir))
            try:
                stored = connection.execute("SELECT config_json FROM projects LIMIT 1").fetchone()
                config = json.loads(stored["config_json"] or "{}")
            finally:
                connection.close()

            self.assertEqual(config["providers"]["openai_codex"]["mode"], "codex_cli")
            self.assertEqual(config["providers"]["openai_codex"]["model"], "gpt-5-codex")
            self.assertEqual(config["recovery"]["retry_backoff_multiplier"], 3)

    def test_recovery_policy_endpoint_includes_task_overrides_and_active_backoff_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Recovery Policy Test", description="Recovery policy test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                override_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()["task_id"]
                backoff_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET auto_retry_limit = 5
                    WHERE task_id = ?
                    """,
                    (override_task_id,),
                )
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'planned',
                        review_state = 'retry_backoff',
                        retry_count = 1,
                        next_retry_at = '2099-01-01 00:00:00',
                        next_retry_reason = 'session_timed_out'
                    WHERE task_id = ?
                    """,
                    (backoff_task_id,),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            payload = client.get("/api/recovery-policy").json()

            self.assertEqual(payload["summary"]["tasks_with_retry_overrides"], 1)
            self.assertEqual(payload["summary"]["retry_backoff_tasks"], 1)

            override_items = {item["task_id"]: item for item in payload["task_retry_overrides"]}
            self.assertEqual(override_items[override_task_id]["auto_retry_limit"], 5)
            self.assertEqual(override_items[override_task_id]["title"], "Wire the scheduler and board read model")

            backoff_items = {item["task_id"]: item for item in payload["active_retry_backoff"]}
            self.assertEqual(backoff_items[backoff_task_id]["review_state"], "retry_backoff")
            self.assertEqual(backoff_items[backoff_task_id]["next_retry_reason"], "session_timed_out")

    def test_recovery_policy_endpoint_excludes_terminal_tasks_from_override_and_backoff_lists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Recovery Policy Test", description="Recovery policy test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                done_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Bootstrap migration runner'"
                ).fetchone()["task_id"]
                cancelled_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Integrate provider adapters'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'done',
                        auto_retry_limit = 4
                    WHERE task_id = ?
                    """,
                    (done_task_id,),
                )
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'cancelled',
                        auto_retry_limit = 2,
                        next_retry_at = '2099-01-01 00:00:00',
                        next_retry_reason = 'session_failed'
                    WHERE task_id = ?
                    """,
                    (cancelled_task_id,),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            payload = client.get("/api/recovery-policy").json()

            self.assertEqual(payload["summary"]["tasks_with_retry_overrides"], 0)
            override_task_ids = {item["task_id"] for item in payload["task_retry_overrides"]}
            backoff_task_ids = {item["task_id"] for item in payload["active_retry_backoff"]}
            self.assertNotIn(done_task_id, override_task_ids)
            self.assertNotIn(cancelled_task_id, override_task_ids)
            self.assertNotIn(done_task_id, backoff_task_ids)
            self.assertNotIn(cancelled_task_id, backoff_task_ids)

    def test_recovery_policy_update_rejects_invalid_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Recovery Policy Test", description="Recovery policy test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            response = client.post(
                "/api/recovery-policy/actions/set",
                json={
                    "actor_id": "agent_allocator",
                    "policy": {
                        "retry_backoff_multiplier": 0,
                    },
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("retry_backoff_multiplier", response.json()["detail"])

            response = client.post(
                "/api/recovery-policy/actions/set",
                json={
                    "actor_id": "agent_allocator",
                    "policy": {
                        "max_timed_out_retries": 1.9,
                    },
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("max_timed_out_retries", response.json()["detail"])

            response = client.post(
                "/api/recovery-policy/actions/set",
                json={
                    "actor_id": "agent_allocator",
                    "policy": {
                        "auto_retry_timeout_sessions": "sometimes",
                    },
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("auto_retry_timeout_sessions", response.json()["detail"])

    def test_recovery_policy_update_requires_board_action_permission(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Recovery Policy Test", description="Recovery policy test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            response = client.post(
                "/api/recovery-policy/actions/set",
                json={
                    "actor_id": "agent_researcher",
                    "policy": {
                        "auto_retry_failed_sessions": True,
                    },
                },
            )
            self.assertEqual(response.status_code, 403)
            self.assertIn("board actions", response.json()["detail"].lower())
