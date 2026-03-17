import json
import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.services.bootstrap import bootstrap_project
from maas.services.failure_memory import fetch_repeated_failure_tasks
from maas.services.lifecycle import end_session, produce_artifact, start_session


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

    def test_recovery_policy_endpoint_includes_task_overrides_retry_history_and_active_backoff_tasks(self):
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
            self.assertEqual(payload["summary"]["tasks_with_retry_history"], 1)

            override_items = {item["task_id"]: item for item in payload["task_retry_overrides"]}
            self.assertEqual(override_items[override_task_id]["auto_retry_limit"], 5)
            self.assertEqual(override_items[override_task_id]["title"], "Wire the scheduler and board read model")

            retry_history_items = {item["task_id"]: item for item in payload["task_retry_history"]}
            self.assertEqual(retry_history_items[backoff_task_id]["retry_count"], 1)
            self.assertEqual(retry_history_items[backoff_task_id]["last_retry_reason"], None)

            backoff_items = {item["task_id"]: item for item in payload["active_retry_backoff"]}
            self.assertEqual(backoff_items[backoff_task_id]["review_state"], "retry_backoff")
            self.assertEqual(backoff_items[backoff_task_id]["next_retry_reason"], "session_timed_out")

    def test_recovery_policy_endpoint_includes_replanning_candidates_and_needs_replan_queue(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Recovery Policy Test", description="Recovery policy test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                candidate_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()["task_id"]
                needs_replan_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'planned',
                        review_state = 'retry_backoff',
                        retry_count = 1,
                        next_retry_at = '2099-01-01 00:00:00',
                        next_retry_reason = 'session_failed'
                    WHERE task_id = ?
                    """,
                    (candidate_task_id,),
                )
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'blocked',
                        review_state = 'needs_replan',
                        retry_count = 2
                    WHERE task_id = ?
                    """,
                    (needs_replan_task_id,),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            payload = client.get("/api/recovery-policy").json()

            self.assertEqual(payload["summary"]["replanning_candidates"], 1)
            self.assertEqual(payload["summary"]["needs_replan_tasks"], 1)

            candidate_items = {item["task_id"]: item for item in payload["replanning_candidates"]}
            self.assertIn(candidate_task_id, candidate_items)
            self.assertEqual(candidate_items[candidate_task_id]["review_state"], "retry_backoff")
            self.assertIn("replan", candidate_items[candidate_task_id]["replan_reason"].lower())

            needs_replan_items = {item["task_id"]: item for item in payload["needs_replan_tasks"]}
            self.assertIn(needs_replan_task_id, needs_replan_items)
            self.assertEqual(needs_replan_items[needs_replan_task_id]["review_state"], "needs_replan")
            self.assertIn("manual replanning", needs_replan_items[needs_replan_task_id]["replan_reason"].lower())

    def test_recovery_policy_endpoint_includes_recoverable_blocked_tasks_and_open_quarantine_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Recovery Policy Test", description="Recovery policy test", project_type="custom")
            connection = connect(result["paths"])
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE status = 'ready' LIMIT 1"
                ).fetchone()["task_id"]
                artifact_path = os.path.join(result["paths"].artifacts_dir, "recovery-policy-test.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("quarantine me")
                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_allocator",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting recovery policy queue test",
                )
                produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    artifact_type="note",
                    path=artifact_path,
                )
                end_session(connection, session_id, "failed", "Recovery policy queue test failure", project_paths=result["paths"])
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            payload = client.get("/api/recovery-policy").json()

            self.assertEqual(payload["summary"]["recoverable_blocked_tasks"], 1)
            self.assertEqual(payload["summary"]["open_quarantine_entries"], 1)

            recoverable_items = {item["task_id"]: item for item in payload["recoverable_blocked_tasks"]}
            self.assertEqual(recoverable_items[task_id]["status"], "blocked")
            self.assertEqual(recoverable_items[task_id]["review_state"], "session_failed")

            quarantine_entries = payload["open_quarantine_entries"]
            self.assertEqual(len(quarantine_entries), 1)
            self.assertEqual(quarantine_entries[0]["task_id"], task_id)
            self.assertEqual(quarantine_entries[0]["status"], "open")
            self.assertEqual(quarantine_entries[0]["artifact_count"], 1)
            self.assertEqual(quarantine_entries[0]["task_review_state"], "session_failed")

    def test_recovery_policy_endpoint_includes_open_failure_alerts_and_repeated_failure_incidents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Recovery Policy Test", description="Recovery policy test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_failure_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()["task_id"]
                repeated_failure_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Define project workspace contracts'"
                ).fetchone()["task_id"]
                stale_agent_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'blocked', review_state = 'session_failed'
                    WHERE task_id = ?
                    """,
                    (task_failure_id,),
                )
                connection.execute(
                    """
                    UPDATE agents
                    SET status = 'error', current_task_id = NULL
                    WHERE agent_id = 'agent_reviewer'
                    """
                )
                connection.execute(
                    """
                    INSERT INTO failure_log (
                        failure_id, project_id, task_id, session_id, agent_id, failure_type, summary, detail_json
                    ) VALUES
                        ('fail_repeat_1', ?, ?, NULL, 'agent_allocator', 'session_failed', 'Repeated failure 1', '{}'),
                        ('fail_repeat_2', ?, ?, NULL, 'agent_allocator', 'session_failed', 'Repeated failure 2', '{}'),
                        ('fail_repeat_3', ?, ?, NULL, 'agent_allocator', 'session_failed', 'Repeated failure 3', '{}')
                    """,
                    (
                        project_id,
                        repeated_failure_task_id,
                        project_id,
                        repeated_failure_task_id,
                        project_id,
                        repeated_failure_task_id,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO alerts (
                        alert_id, project_id, severity, title, description, status
                    ) VALUES
                        ('alert_recovery_task_failure', ?, 'warning', 'Task session failed', ?, 'open'),
                        ('alert_recovery_repeated_failure', ?, 'critical', 'Repeated task failures', ?, 'open'),
                        ('alert_recovery_stale_agent', ?, 'warning', 'Stale agent heartbeat', ?, 'open')
                    """,
                    (
                        project_id,
                        "Task {0} failed in session sess_recovery_123. Session crashed".format(task_failure_id),
                        project_id,
                        "Task {0} (Define project workspace contracts) has failed 3 times. Latest failure: Repeated failure 3".format(
                            repeated_failure_task_id
                        ),
                        project_id,
                        "Agent agent_reviewer stopped heartbeating for task {0}.".format(stale_agent_task_id),
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            payload = client.get("/api/recovery-policy").json()

            self.assertEqual(payload["summary"]["open_failure_alerts"], 1)
            self.assertEqual(payload["summary"]["open_repeated_failure_alerts"], 1)
            self.assertEqual(payload["summary"]["open_stale_agent_alerts"], 1)
            self.assertEqual(
                payload["open_failure_alerts"][0]["operator_action"],
                {
                    "action": "recover_task",
                    "label": "Recover task",
                    "resource_type": "task",
                    "resource_id": task_failure_id,
                },
            )
            self.assertEqual(
                payload["repeated_failure_incidents"][0]["operator_action"],
                {
                    "action": "resolve_repeated_failures",
                    "label": "Resolve repeated failures",
                    "resource_type": "task",
                    "resource_id": repeated_failure_task_id,
                },
            )
            self.assertEqual(
                payload["open_stale_agent_alerts"][0]["operator_action"],
                {
                    "action": "recover_agent",
                    "label": "Recover agent",
                    "resource_type": "agent",
                    "resource_id": "agent_reviewer",
                    "related_task_id": stale_agent_task_id,
                },
            )

    def test_fetch_repeated_failure_tasks_actionable_only_applies_limit_after_action_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Recovery Policy Test", description="Recovery policy test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                high_count_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()["task_id"]
                actionable_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Define project workspace contracts'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    INSERT INTO failure_log (
                        failure_id, project_id, task_id, session_id, agent_id, failure_type, summary, detail_json
                    ) VALUES
                        ('fail_high_1', ?, ?, NULL, 'agent_allocator', 'session_failed', 'High count 1', '{}'),
                        ('fail_high_2', ?, ?, NULL, 'agent_allocator', 'session_failed', 'High count 2', '{}'),
                        ('fail_high_3', ?, ?, NULL, 'agent_allocator', 'session_failed', 'High count 3', '{}'),
                        ('fail_high_4', ?, ?, NULL, 'agent_allocator', 'session_failed', 'High count 4', '{}'),
                        ('fail_action_1', ?, ?, NULL, 'agent_allocator', 'session_failed', 'Actionable 1', '{}'),
                        ('fail_action_2', ?, ?, NULL, 'agent_allocator', 'session_failed', 'Actionable 2', '{}'),
                        ('fail_action_3', ?, ?, NULL, 'agent_allocator', 'session_failed', 'Actionable 3', '{}')
                    """,
                    (
                        project_id,
                        high_count_task_id,
                        project_id,
                        high_count_task_id,
                        project_id,
                        high_count_task_id,
                        project_id,
                        high_count_task_id,
                        project_id,
                        actionable_task_id,
                        project_id,
                        actionable_task_id,
                        project_id,
                        actionable_task_id,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO alerts (
                        alert_id, project_id, severity, title, description, status
                    ) VALUES
                        ('alert_actionable_repeat', ?, 'critical', 'Repeated task failures', ?, 'open')
                    """,
                    (
                        project_id,
                        "Task {0} (Define project workspace contracts) has failed 3 times. Latest failure: Actionable 3".format(
                            actionable_task_id
                        ),
                    ),
                )
                connection.commit()

                tasks = fetch_repeated_failure_tasks(
                    connection,
                    limit=1,
                    project_id=project_id,
                    actionable_only=True,
                )
            finally:
                connection.close()

            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0]["task_id"], actionable_task_id)
            self.assertEqual(
                tasks[0]["operator_action"],
                {
                    "action": "resolve_repeated_failures",
                    "label": "Resolve repeated failures",
                    "resource_type": "task",
                    "resource_id": actionable_task_id,
                },
            )

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
                        auto_retry_limit = 4,
                        retry_count = 2
                    WHERE task_id = ?
                    """,
                    (done_task_id,),
                )
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'cancelled',
                        auto_retry_limit = 2,
                        retry_count = 1,
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
            self.assertEqual(payload["summary"]["tasks_with_retry_history"], 0)
            override_task_ids = {item["task_id"] for item in payload["task_retry_overrides"]}
            retry_history_task_ids = {item["task_id"] for item in payload["task_retry_history"]}
            backoff_task_ids = {item["task_id"] for item in payload["active_retry_backoff"]}
            self.assertNotIn(done_task_id, override_task_ids)
            self.assertNotIn(cancelled_task_id, override_task_ids)
            self.assertNotIn(done_task_id, retry_history_task_ids)
            self.assertNotIn(cancelled_task_id, retry_history_task_ids)
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
