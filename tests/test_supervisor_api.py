import json
import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect
from maas.services.bootstrap import bootstrap_project
from maas.ids import generate_id
from maas.services.alerts import fetch_alerts
from maas.services.lifecycle import end_session, heartbeat, produce_artifact
from maas.services.projects import create_project, resolve_project_id
from maas.supervisor import run_supervisor_once


class SupervisorApiTest(unittest.TestCase):
    def _update_recovery_config(self, connection, project_id=None, **updates):
        resolved_project_id = project_id or resolve_project_id(connection)
        project = connection.execute(
            "SELECT project_id, config_json FROM projects WHERE project_id = ?",
            (resolved_project_id,),
        ).fetchone()
        config = json.loads(project["config_json"] or "{}")
        recovery = {
            "auto_retry_timeout_sessions": True,
            "auto_retry_failed_sessions": False,
            "auto_recover_blocked_tasks": False,
            "max_timed_out_retries": 1,
            "max_failed_session_retries": 1,
            "timed_out_retry_cooldown_seconds": 60,
            "failed_session_retry_cooldown_seconds": 120,
            "recover_and_requeue_cooldown_seconds": 30,
            "retry_backoff_multiplier": 2,
            "retry_backoff_max_seconds": 900,
        }
        recovery.update(updates)
        config["recovery"] = recovery
        connection.execute(
            "UPDATE projects SET config_json = ? WHERE project_id = ?",
            (json.dumps(config), project["project_id"]),
        )

    def _enable_timeout_auto_retry(self, connection, max_retries=1, cooldown_seconds=60, project_id=None):
        self._update_recovery_config(
            connection,
            project_id=project_id,
            auto_retry_timeout_sessions=True,
            max_timed_out_retries=max_retries,
            timed_out_retry_cooldown_seconds=cooldown_seconds,
        )

    def _enable_blocked_task_auto_recovery(self, connection, cooldown_seconds=30, project_id=None):
        self._update_recovery_config(
            connection,
            project_id=project_id,
            auto_retry_timeout_sessions=False,
            auto_recover_blocked_tasks=True,
            recover_and_requeue_cooldown_seconds=cooldown_seconds,
        )

    def test_supervisor_refreshes_ready_tasks_and_allocates_idle_agents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Supervisor Test", description="Supervisor test", project_type="custom")
            connection = connect(result["paths"])
            try:
                supervisor_result = run_supervisor_once(connection)
                planned_task = connection.execute(
                    "SELECT status, assigned_agent_id FROM tasks WHERE title = 'Define project workspace contracts'"
                ).fetchone()
                ready_task = connection.execute(
                    "SELECT status, assigned_agent_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(supervisor_result["assigned_count"], 2)
            self.assertGreaterEqual(len(supervisor_result["ready_changes"]), 1)
            self.assertEqual(planned_task["status"], "assigned")
            self.assertEqual(planned_task["assigned_agent_id"], "agent_researcher")
            self.assertEqual(ready_task["status"], "assigned")
            self.assertEqual(ready_task["assigned_agent_id"], "agent_allocator")

    def test_supervisor_marks_stale_sessions_and_agents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor Stale Test",
                description="Supervisor stale test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                connection.execute(
                    """
                    UPDATE sessions
                    SET last_heartbeat_at = '2000-01-01 00:00:00'
                    WHERE status = 'active'
                    """
                )
                connection.commit()

                supervisor_result = run_supervisor_once(connection, stale_after_seconds=90, allocate_limit=0)
                session = connection.execute(
                    "SELECT status FROM sessions WHERE status = 'timed_out'"
                ).fetchone()
                task = connection.execute(
                    "SELECT status, review_state FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()
                agent = connection.execute(
                    "SELECT status, current_task_id FROM agents WHERE agent_id = 'agent_builder'"
                ).fetchone()
                failure = connection.execute(
                    """
                    SELECT failure_type
                    FROM failure_log
                    WHERE task_id = (
                        SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'
                    )
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(len(supervisor_result["stale_sessions"]), 1)
            self.assertIsNotNone(session)
            self.assertEqual(task["status"], "blocked")
            self.assertEqual(task["review_state"], "stale_session")
            self.assertEqual(agent["status"], "error")
            self.assertIsNone(agent["current_task_id"])
            self.assertEqual(failure["failure_type"], "session_timed_out")

    def test_supervisor_auto_retries_timed_out_session_when_policy_allows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor Auto Retry Test",
                description="Supervisor auto retry test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                self._enable_timeout_auto_retry(connection, max_retries=1)
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                blocker_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()["task_id"]
                connection.execute(
                    "UPDATE tasks SET status = 'done' WHERE task_id = ?",
                    (blocker_task_id,),
                )
                connection.execute(
                    """
                    UPDATE sessions
                    SET last_heartbeat_at = '2000-01-01 00:00:00'
                    WHERE task_id = ? AND status = 'active'
                    """,
                    (task_id,),
                )
                connection.commit()

                supervisor_result = run_supervisor_once(connection, stale_after_seconds=90, allocate_limit=0)
                task = connection.execute(
                    """
                    SELECT
                        status,
                        review_state,
                        assigned_agent_id,
                        retry_count,
                        last_retry_reason,
                        next_retry_at,
                        next_retry_reason
                    FROM tasks
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
                agent = connection.execute(
                    "SELECT status, current_task_id FROM agents WHERE agent_id = 'agent_builder'"
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(len(supervisor_result["stale_sessions"]), 1)
            self.assertTrue(supervisor_result["stale_sessions"][0]["auto_retried"])
            self.assertEqual(supervisor_result["stale_sessions"][0]["retry_count"], 1)
            self.assertEqual(task["status"], "planned")
            self.assertEqual(task["review_state"], "retry_backoff")
            self.assertIsNone(task["assigned_agent_id"])
            self.assertEqual(task["retry_count"], 1)
            self.assertEqual(task["last_retry_reason"], "session_timed_out")
            self.assertEqual(task["next_retry_reason"], "session_timed_out")
            self.assertIsNotNone(task["next_retry_at"])
            self.assertEqual(supervisor_result["stale_sessions"][0]["next_retry_at"], task["next_retry_at"])
            self.assertEqual(agent["status"], "error")
            self.assertIsNone(agent["current_task_id"])

    def test_supervisor_does_not_auto_retry_operator_paused_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor Paused Task Test",
                description="Supervisor paused task test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                self._enable_timeout_auto_retry(connection, max_retries=1)
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE sessions
                    SET last_heartbeat_at = '2000-01-01 00:00:00'
                    WHERE task_id = ? AND status = 'active'
                    """,
                    (task_id,),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            pause_response = client.post(
                "/api/agents/agent_builder/actions/pause",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(pause_response.status_code, 200)

            connection = connect(result["paths"])
            try:
                supervisor_result = run_supervisor_once(connection, stale_after_seconds=90, allocate_limit=0)
                task = connection.execute(
                    """
                    SELECT status, review_state, retry_count, last_retry_reason
                    FROM tasks
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertFalse(supervisor_result["stale_sessions"][0]["auto_retried"])
            self.assertEqual(task["status"], "blocked")
            self.assertEqual(task["review_state"], "paused_by_operator")
            self.assertEqual(task["retry_count"], 0)
            self.assertIsNone(task["last_retry_reason"])

    def test_supervisor_auto_retry_uses_task_retry_limit_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor Retry Override Test",
                description="Supervisor retry override test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                self._enable_timeout_auto_retry(connection, max_retries=0)
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                blocker_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()["task_id"]
                connection.execute("UPDATE tasks SET status = 'done' WHERE task_id = ?", (blocker_task_id,))
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            override_response = client.post(
                "/api/tasks/{0}/actions/set-retry-limit".format(task_id),
                json={"actor_id": "agent_allocator", "auto_retry_limit": 2},
            )
            self.assertEqual(override_response.status_code, 200)

            connection = connect(result["paths"])
            try:
                connection.execute(
                    """
                    UPDATE sessions
                    SET last_heartbeat_at = '2000-01-01 00:00:00'
                    WHERE task_id = ? AND status = 'active'
                    """,
                    (task_id,),
                )
                connection.commit()

                supervisor_result = run_supervisor_once(connection, stale_after_seconds=90, allocate_limit=0)
                task = connection.execute(
                    """
                    SELECT status, review_state, retry_count, auto_retry_limit, last_retry_reason
                    FROM tasks
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertTrue(supervisor_result["stale_sessions"][0]["auto_retried"])
            self.assertEqual(task["status"], "planned")
            self.assertEqual(task["review_state"], "retry_backoff")
            self.assertEqual(task["retry_count"], 1)
            self.assertEqual(task["auto_retry_limit"], 2)
            self.assertEqual(task["last_retry_reason"], "session_timed_out")

    def test_supervisor_leaves_timed_out_task_blocked_when_retry_budget_is_exhausted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor Retry Budget Test",
                description="Supervisor retry budget test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                self._enable_timeout_auto_retry(connection, max_retries=1)
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET retry_count = 1, last_retry_reason = 'session_timed_out'
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
                connection.execute(
                    """
                    UPDATE sessions
                    SET last_heartbeat_at = '2000-01-01 00:00:00'
                    WHERE task_id = ? AND status = 'active'
                    """,
                    (task_id,),
                )
                connection.commit()

                supervisor_result = run_supervisor_once(connection, stale_after_seconds=90, allocate_limit=0)
                task = connection.execute(
                    """
                    SELECT status, review_state, retry_count, last_retry_reason
                    FROM tasks
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertFalse(supervisor_result["stale_sessions"][0]["auto_retried"])
            self.assertEqual(task["status"], "blocked")
            self.assertEqual(task["review_state"], "stale_session")
            self.assertEqual(task["retry_count"], 1)
            self.assertEqual(task["last_retry_reason"], "session_timed_out")

    def test_supervisor_routes_timed_out_task_to_dead_letter_queue_when_retry_budget_is_exhausted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor DLQ Test",
                description="Supervisor DLQ test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                self._update_recovery_config(
                    connection,
                    auto_retry_timeout_sessions=True,
                    auto_dlq_retry_exhausted_tasks=True,
                    max_timed_out_retries=1,
                    timed_out_retry_cooldown_seconds=60,
                )
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET retry_count = 1, last_retry_reason = 'session_timed_out'
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
                connection.execute(
                    """
                    UPDATE sessions
                    SET last_heartbeat_at = '2000-01-01 00:00:00'
                    WHERE task_id = ? AND status = 'active'
                    """,
                    (task_id,),
                )
                connection.commit()

                supervisor_result = run_supervisor_once(connection, stale_after_seconds=90, allocate_limit=0)
                task = connection.execute(
                    """
                    SELECT status, review_state, retry_count, last_retry_reason, next_retry_at, next_retry_reason
                    FROM tasks
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
                dead_letter = connection.execute(
                    """
                    SELECT reason, status, detail_json
                    FROM dead_letter_queue
                    WHERE task_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (task_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertFalse(supervisor_result["stale_sessions"][0]["auto_retried"])
            self.assertTrue(supervisor_result["stale_sessions"][0]["dead_lettered"])
            self.assertEqual(task["status"], "blocked")
            self.assertEqual(task["review_state"], "needs_replan")
            self.assertEqual(task["retry_count"], 1)
            self.assertEqual(task["last_retry_reason"], "session_timed_out")
            self.assertIsNone(task["next_retry_at"])
            self.assertIsNone(task["next_retry_reason"])
            self.assertEqual(dead_letter["reason"], "retry_budget_exhausted")
            self.assertEqual(dead_letter["status"], "open")
            self.assertEqual(json.loads(dead_letter["detail_json"])["failure_type"], "session_timed_out")

    def test_supervisor_opens_circuit_breaker_when_timeout_retry_budget_is_exhausted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor Circuit Breaker Test",
                description="Supervisor circuit breaker test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                self._update_recovery_config(
                    connection,
                    auto_retry_timeout_sessions=True,
                    auto_dlq_retry_exhausted_tasks=True,
                    auto_open_task_circuit_breakers=True,
                    max_timed_out_retries=1,
                    timed_out_retry_cooldown_seconds=60,
                )
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET retry_count = 1, last_retry_reason = 'session_timed_out'
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
                connection.execute(
                    """
                    UPDATE sessions
                    SET last_heartbeat_at = '2000-01-01 00:00:00'
                    WHERE task_id = ? AND status = 'active'
                    """,
                    (task_id,),
                )
                connection.commit()

                supervisor_result = run_supervisor_once(connection, stale_after_seconds=90, allocate_limit=0)
                task = connection.execute(
                    """
                    SELECT status, review_state, retry_count, last_retry_reason, next_retry_at, next_retry_reason
                    FROM tasks
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
                dead_letters = connection.execute(
                    """
                    SELECT reason, status, detail_json
                    FROM dead_letter_queue
                    WHERE task_id = ?
                    ORDER BY created_at ASC
                    """,
                    (task_id,),
                ).fetchall()
            finally:
                connection.close()

            self.assertFalse(supervisor_result["stale_sessions"][0]["auto_retried"])
            self.assertTrue(supervisor_result["stale_sessions"][0]["dead_lettered"])
            self.assertEqual(task["status"], "blocked")
            self.assertEqual(task["review_state"], "circuit_breaker_open")
            self.assertEqual(task["retry_count"], 1)
            self.assertEqual(task["last_retry_reason"], "session_timed_out")
            self.assertIsNone(task["next_retry_at"])
            self.assertIsNone(task["next_retry_reason"])
            self.assertEqual([item["reason"] for item in dead_letters], ["retry_budget_exhausted", "circuit_breaker_open"])
            self.assertEqual(dead_letters[0]["status"], "open")
            self.assertEqual(dead_letters[1]["status"], "open")
            self.assertEqual(json.loads(dead_letters[0]["detail_json"])["failure_type"], "session_timed_out")
            self.assertEqual(
                json.loads(dead_letters[1]["detail_json"]),
                {
                    "trigger": "retry_budget_exhausted",
                    "failure_count": None,
                    "threshold": 3,
                    "retry_limit": 1,
                    "retry_count": 1,
                },
            )

    def test_supervisor_auto_recovers_safe_blocked_failed_task_when_policy_allows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor Auto Recover Blocked Test",
                description="Auto recover blocked task",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                self._enable_blocked_task_auto_recovery(connection, cooldown_seconds=0)
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                session_id = connection.execute(
                    "SELECT session_id FROM sessions WHERE task_id = ? AND status = 'active'",
                    (task_id,),
                ).fetchone()["session_id"]
                blocker_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()["task_id"]
                connection.execute("UPDATE tasks SET status = 'done' WHERE task_id = ?", (blocker_task_id,))
                connection.commit()
                end_session(connection, session_id, "failed", "Auto recover candidate", project_paths=None)

                supervisor_result = run_supervisor_once(connection, allocate_limit=0)
                task = connection.execute(
                    """
                    SELECT status, review_state, retry_count, last_retry_reason, next_retry_at, next_retry_reason
                    FROM tasks
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
                failure_alert = connection.execute(
                    """
                    SELECT status
                    FROM alerts
                    WHERE title = 'Task session failed' AND description LIKE ?
                    """,
                    (f"Task {task_id} failed in session %",),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(len(supervisor_result["auto_recovered_tasks"]), 1)
            self.assertEqual(supervisor_result["auto_recovered_tasks"][0]["task_id"], task_id)
            self.assertEqual(task["status"], "ready")
            self.assertIsNone(task["review_state"])
            self.assertEqual(task["retry_count"], 1)
            self.assertEqual(task["last_retry_reason"], "blocked_task_auto_recovered")
            self.assertIsNone(task["next_retry_at"])
            self.assertIsNone(task["next_retry_reason"])
            self.assertEqual(failure_alert["status"], "resolved")

    def test_supervisor_does_not_auto_recover_blocked_task_with_open_quarantine(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor Auto Recover Quarantine Test",
                description="Blocked task with quarantine should stay blocked",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                self._enable_blocked_task_auto_recovery(connection, cooldown_seconds=0)
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                session_id = connection.execute(
                    "SELECT session_id FROM sessions WHERE task_id = ? AND status = 'active'",
                    (task_id,),
                ).fetchone()["session_id"]
                artifact_path = os.path.join(result["paths"].artifacts_dir, "supervisor-auto-recover.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("keep quarantined")
                produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    artifact_type="note",
                    path=artifact_path,
                )
                connection.commit()
                end_session(connection, session_id, "failed", "Blocked by quarantine", project_paths=result["paths"])

                supervisor_result = run_supervisor_once(connection, allocate_limit=0)
                task = connection.execute(
                    "SELECT status, review_state FROM tasks WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(supervisor_result["auto_recovered_tasks"], [])
            self.assertEqual(task["status"], "blocked")
            self.assertEqual(task["review_state"], "session_failed")

    def test_supervisor_auto_recover_stops_once_blocked_task_retry_budget_is_consumed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor Auto Recover Budget Test",
                description="Blocked task auto recovery should respect retry budget",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                self._update_recovery_config(
                    connection,
                    auto_retry_timeout_sessions=False,
                    auto_recover_blocked_tasks=True,
                    max_failed_session_retries=1,
                    recover_and_requeue_cooldown_seconds=0,
                )
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'blocked',
                        review_state = 'session_failed',
                        retry_count = 1,
                        last_retry_reason = 'blocked_task_auto_recovered'
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
                connection.commit()

                supervisor_result = run_supervisor_once(connection, allocate_limit=0)
                task = connection.execute(
                    """
                    SELECT status, review_state, retry_count, last_retry_reason
                    FROM tasks
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(supervisor_result["auto_recovered_tasks"], [])
            self.assertEqual(task["status"], "blocked")
            self.assertEqual(task["review_state"], "session_failed")
            self.assertEqual(task["retry_count"], 1)
            self.assertEqual(task["last_retry_reason"], "blocked_task_auto_recovered")

    def test_supervisor_auto_routes_clear_circuit_breaker_to_replan_when_policy_allows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor Auto Replan Test",
                description="Auto route circuit breaker to replanning",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                self._update_recovery_config(
                    connection,
                    project_id=project_id,
                    auto_retry_timeout_sessions=False,
                    auto_route_circuit_breakers_to_replan=True,
                    circuit_breaker_replan_after_seconds=0,
                )
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'blocked',
                        review_state = 'circuit_breaker_open',
                        retry_count = 3,
                        last_retry_reason = 'session_failed'
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
                connection.execute(
                    """
                    INSERT INTO dead_letter_queue (
                        dlq_id, project_id, task_id, reason, detail_json
                    ) VALUES ('dlq_supervisor_auto_replan', ?, ?, 'circuit_breaker_open', '{"trigger":"repeated_failures","failure_count":3,"threshold":3}')
                    """,
                    (project_id, task_id),
                )
                connection.commit()

                supervisor_result = run_supervisor_once(connection, allocate_limit=0)
                task = connection.execute(
                    "SELECT status, review_state, next_retry_at FROM tasks WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                dead_letter = connection.execute(
                    """
                    SELECT status, resolution_note
                    FROM dead_letter_queue
                    WHERE dlq_id = 'dlq_supervisor_auto_replan'
                    """
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(len(supervisor_result["auto_replanned_tasks"]), 1)
            self.assertEqual(supervisor_result["auto_replanned_tasks"][0]["task_id"], task_id)
            self.assertEqual(task["status"], "blocked")
            self.assertEqual(task["review_state"], "needs_replan")
            self.assertIsNone(task["next_retry_at"])
            self.assertEqual(dead_letter["status"], "resolved")
            self.assertEqual(dead_letter["resolution_note"], "auto_marked_for_replan")

    def test_recover_action_can_requeue_stale_session_task_without_resetting_agent_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor Recover Test",
                description="Recover stale-session task",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE sessions
                    SET last_heartbeat_at = '2000-01-01 00:00:00'
                    WHERE task_id = ? AND status = 'active'
                    """,
                    (task_id,),
                )
                connection.commit()
                run_supervisor_once(connection, stale_after_seconds=90, allocate_limit=0)
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            recover_response = client.post(
                "/api/tasks/{0}/actions/recover".format(task_id),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(recover_response.status_code, 200)

            connection = connect(result["paths"])
            try:
                task = connection.execute(
                    "SELECT status, assigned_agent_id, review_state FROM tasks WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                agent = connection.execute(
                    "SELECT status, current_task_id FROM agents WHERE agent_id = 'agent_builder'"
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(task["status"], "planned")
            self.assertIsNone(task["assigned_agent_id"])
            self.assertIsNone(task["review_state"])
            self.assertEqual(agent["status"], "error")
            self.assertIsNone(agent["current_task_id"])

    def test_agent_recover_action_returns_error_agent_to_idle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Agent Recover Test",
                description="Recover timed-out agent",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                connection.execute(
                    """
                    UPDATE sessions
                    SET last_heartbeat_at = '2000-01-01 00:00:00'
                    WHERE agent_id = 'agent_builder' AND status = 'active'
                    """
                )
                connection.commit()
                run_supervisor_once(connection, stale_after_seconds=90, allocate_limit=0)
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            recover_response = client.post(
                "/api/agents/agent_builder/actions/recover",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(recover_response.status_code, 200)
            self.assertEqual(recover_response.json()["status"], "idle")

            connection = connect(result["paths"])
            try:
                agent = connection.execute(
                    "SELECT status, current_task_id FROM agents WHERE agent_id = 'agent_builder'"
                ).fetchone()
                stale_alert = connection.execute(
                    """
                    SELECT status
                    FROM alerts
                    WHERE title = 'Stale agent heartbeat'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(agent["status"], "idle")
            self.assertIsNone(agent["current_task_id"])
            self.assertEqual(stale_alert["status"], "resolved")

    def test_agent_recover_rejects_non_error_agents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(
                tmpdir,
                name="Agent Recover Guard Test",
                description="Reject invalid agent recover path",
                project_type="custom",
            )
            client = TestClient(create_app(tmpdir))

            recover_response = client.post(
                "/api/agents/agent_reviewer/actions/recover",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(recover_response.status_code, 400)

    def test_supervisor_api_endpoint_runs_pass(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Supervisor API Test", description="Supervisor API test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            response = client.post("/api/supervisor/run", json={"allocate_limit": 1})
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertIn("ready_changes", payload)
            self.assertIn("allocations", payload)
            self.assertEqual(payload["assigned_count"], 1)
            self.assertIn("project_runs", payload)
            self.assertEqual(len(payload["project_runs"]), 1)

    def test_supervisor_api_can_scope_run_to_selected_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor Scoped API Test",
                description="Supervisor scoped API test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                primary_project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                second_project_id = create_project(
                    connection,
                    result["paths"],
                    actor_id="agent_allocator",
                    name="Second Project",
                    description="secondary",
                    project_type="custom",
                    mode="greenfield",
                )["project"]["project_id"]
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.post(
                "/api/supervisor/run",
                json={"allocate_limit": 2, "project_id": primary_project_id},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()

            connection = connect(result["paths"])
            try:
                primary_assigned = connection.execute(
                    "SELECT COUNT(*) AS count FROM tasks WHERE project_id = ? AND status = 'assigned'",
                    (primary_project_id,),
                ).fetchone()["count"]
                second_assigned = connection.execute(
                    "SELECT COUNT(*) AS count FROM tasks WHERE project_id = ? AND status = 'assigned'",
                    (second_project_id,),
                ).fetchone()["count"]
            finally:
                connection.close()

            self.assertEqual(payload["assigned_count"], 2)
            self.assertEqual([item["project_id"] for item in payload["project_runs"]], [primary_project_id])
            self.assertGreater(primary_assigned, 0)
            self.assertEqual(second_assigned, 0)

    def test_supervisor_default_run_iterates_all_active_projects(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor Multi Project Test",
                description="Supervisor multi project test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                primary_project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                second_project_id = create_project(
                    connection,
                    result["paths"],
                    actor_id="agent_allocator",
                    name="Second Project",
                    description="secondary",
                    project_type="custom",
                    mode="greenfield",
                )["project"]["project_id"]

                supervisor_result = run_supervisor_once(connection, allocate_limit=4, project_paths=result["paths"])
                primary_assigned = connection.execute(
                    "SELECT COUNT(*) AS count FROM tasks WHERE project_id = ? AND status = 'assigned'",
                    (primary_project_id,),
                ).fetchone()["count"]
                second_assigned = connection.execute(
                    "SELECT COUNT(*) AS count FROM tasks WHERE project_id = ? AND status = 'assigned'",
                    (second_project_id,),
                ).fetchone()["count"]
            finally:
                connection.close()

            project_ids = [item["project_id"] for item in supervisor_result["project_runs"]]
            self.assertEqual(project_ids, [primary_project_id, second_project_id])
            self.assertEqual(supervisor_result["assigned_count"], 4)
            self.assertGreater(primary_assigned, 0)
            self.assertGreater(second_assigned, 0)

    def test_stale_session_does_not_clobber_agent_with_other_active_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor Duplicate Session Test",
                description="Supervisor duplicate session test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                stale_session_id = connection.execute(
                    "SELECT session_id FROM sessions WHERE task_id = ? AND status = 'active'",
                    (task_id,),
                ).fetchone()["session_id"]
                healthy_session_id = generate_id("sess")
                connection.execute(
                    """
                    INSERT INTO sessions (
                        session_id, project_id, agent_id, task_id, status, provider_type, progress_pct, status_message
                    ) VALUES (?, ?, ?, ?, 'active', 'python_script', 65, ?)
                    """,
                    (
                        healthy_session_id,
                        project_id,
                        "agent_builder",
                        task_id,
                        "Second active session for duplicate-session regression test",
                    ),
                )
                heartbeat(connection, healthy_session_id, 70, "Healthy duplicate session heartbeat")
                connection.execute(
                    """
                    UPDATE sessions
                    SET last_heartbeat_at = '2000-01-01 00:00:00'
                    WHERE session_id = ?
                    """,
                    (stale_session_id,),
                )
                connection.commit()

                supervisor_result = run_supervisor_once(connection, stale_after_seconds=90, allocate_limit=0)
                agent = connection.execute(
                    "SELECT status, current_task_id FROM agents WHERE agent_id = 'agent_builder'"
                ).fetchone()
                task = connection.execute(
                    "SELECT status, review_state FROM tasks WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                healthy_session = connection.execute(
                    "SELECT status FROM sessions WHERE session_id = ?",
                    (healthy_session_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(len(supervisor_result["stale_sessions"]), 1)
            self.assertEqual(agent["status"], "running")
            self.assertEqual(agent["current_task_id"], task_id)
            self.assertEqual(task["status"], "in_progress")
            self.assertIsNone(task["review_state"])
            self.assertEqual(healthy_session["status"], "active")

    def test_supervisor_raises_repeated_failure_alert_for_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor Repeated Failure Test",
                description="Supervisor repeated failure test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    INSERT INTO failure_log (
                        failure_id, project_id, task_id, session_id, agent_id, failure_type, summary, detail_json
                    )
                    SELECT ?, project_id, ?, session_id, agent_id, 'session_failed', 'Earlier failure', '{}'
                    FROM sessions
                    WHERE task_id = ?
                    LIMIT 1
                    """,
                    (generate_id("fail"), task_id, task_id),
                )
                connection.execute(
                    """
                    UPDATE sessions
                    SET last_heartbeat_at = '2000-01-01 00:00:00'
                    WHERE task_id = ? AND status = 'active'
                    """,
                    (task_id,),
                )
                connection.commit()

                supervisor_result = run_supervisor_once(connection, stale_after_seconds=90, allocate_limit=0)
                repeated_alert = connection.execute(
                    """
                    SELECT title, severity
                    FROM alerts
                    WHERE title = 'Repeated task failures'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(repeated_alert["title"], "Repeated task failures")
            self.assertEqual(repeated_alert["severity"], "critical")
            self.assertIsNotNone(supervisor_result["stale_sessions"][0]["repeated_failure_alert"])

    def test_stale_heartbeat_alert_omits_recover_agent_action_while_agent_stays_running(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor Stale Alert Action Test",
                description="Supervisor stale alert action test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                stale_session_id = connection.execute(
                    "SELECT session_id FROM sessions WHERE task_id = ? AND status = 'active'",
                    (task_id,),
                ).fetchone()["session_id"]
                healthy_session_id = generate_id("sess")
                connection.execute(
                    """
                    INSERT INTO sessions (
                        session_id, project_id, agent_id, task_id, status, provider_type, progress_pct, status_message
                    ) VALUES (?, ?, ?, ?, 'active', 'python_script', 65, ?)
                    """,
                    (
                        healthy_session_id,
                        project_id,
                        "agent_builder",
                        task_id,
                        "Second active session for stale-alert operator-action regression test",
                    ),
                )
                heartbeat(connection, healthy_session_id, 70, "Healthy duplicate session heartbeat")
                connection.execute(
                    """
                    UPDATE sessions
                    SET last_heartbeat_at = '2000-01-01 00:00:00'
                    WHERE session_id = ?
                    """,
                    (stale_session_id,),
                )
                connection.commit()

                run_supervisor_once(connection, stale_after_seconds=90, allocate_limit=0)
                alert_payload = fetch_alerts(connection)
            finally:
                connection.close()

            stale_alert = [alert for alert in alert_payload["alerts"] if alert["title"] == "Stale agent heartbeat"][0]
            self.assertNotIn("operator_action", stale_alert)

    def test_supervisor_quarantines_artifacts_for_timed_out_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor Quarantine Test",
                description="Supervisor quarantine test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                session_id = connection.execute(
                    "SELECT session_id FROM sessions WHERE task_id = ? AND status = 'active'",
                    (task_id,),
                ).fetchone()["session_id"]
                artifact_path = os.path.join(result["paths"].artifacts_dir, "stale-session-note.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("stale artifact\n")
                artifact_id = produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    artifact_type="note",
                    path=artifact_path,
                )
                connection.execute(
                    """
                    UPDATE sessions
                    SET last_heartbeat_at = '2000-01-01 00:00:00'
                    WHERE session_id = ?
                    """,
                    (session_id,),
                )
                connection.commit()

                supervisor_result = run_supervisor_once(
                    connection,
                    stale_after_seconds=90,
                    allocate_limit=0,
                    project_paths=result["paths"],
                )
                artifact = connection.execute(
                    """
                    SELECT path, metadata_json
                    FROM artifacts
                    WHERE artifact_id = ?
                    """,
                    (artifact_id,),
                ).fetchone()
                queue_row = connection.execute(
                    """
                    SELECT session_id, status, artifact_count, reason
                    FROM quarantine_queue
                    WHERE session_id = ?
                    """,
                    (session_id,),
                ).fetchone()
            finally:
                connection.close()

            metadata = json.loads(artifact["metadata_json"])
            self.assertEqual(len(supervisor_result["stale_sessions"]), 1)
            self.assertEqual(len(supervisor_result["stale_sessions"][0]["quarantined_artifacts"]), 1)
            self.assertFalse(os.path.exists(artifact_path))
            self.assertTrue(os.path.exists(artifact["path"]))
            self.assertTrue(
                os.path.commonpath([os.path.abspath(result["paths"].quarantine_dir), os.path.abspath(artifact["path"])])
                == os.path.abspath(result["paths"].quarantine_dir)
            )
            self.assertTrue(metadata["quarantined"])
            self.assertEqual(metadata["quarantine_reason"], "session_timed_out")
            self.assertEqual(metadata["quarantined_from_path"], artifact_path)
            self.assertEqual(queue_row["session_id"], session_id)
            self.assertEqual(queue_row["status"], "open")
            self.assertEqual(queue_row["artifact_count"], 1)
            self.assertEqual(queue_row["reason"], "session_timed_out")

    def test_cancelled_sessions_do_not_count_toward_repeated_failure_alerts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor Cancelled Failure Test",
                description="Supervisor cancelled failure test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    INSERT INTO failure_log (
                        failure_id, project_id, task_id, session_id, agent_id, failure_type, summary, detail_json
                    )
                    SELECT ?, project_id, ?, session_id, agent_id, 'session_cancelled', 'Operator cancelled work', '{}'
                    FROM sessions
                    WHERE task_id = ?
                    LIMIT 1
                    """,
                    (generate_id("fail"), task_id, task_id),
                )
                connection.execute(
                    """
                    UPDATE sessions
                    SET last_heartbeat_at = '2000-01-01 00:00:00'
                    WHERE task_id = ? AND status = 'active'
                    """,
                    (task_id,),
                )
                connection.commit()

                supervisor_result = run_supervisor_once(connection, stale_after_seconds=90, allocate_limit=0)
                repeated_alert = connection.execute(
                    """
                    SELECT alert_id
                    FROM alerts
                    WHERE title = 'Repeated task failures'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ).fetchone()
            finally:
                connection.close()

            self.assertIsNone(repeated_alert)
            self.assertIsNone(supervisor_result["stale_sessions"][0]["repeated_failure_alert"])

    def test_supervisor_default_project_scope_skips_archived_projects(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Supervisor Project Scope Test",
                description="Supervisor project scope test",
                project_type="custom",
            )
            client = TestClient(create_app(tmpdir))
            second_project_id = client.post(
                "/api/projects",
                json={
                    "actor_id": "agent_allocator",
                    "name": "Second Project",
                    "description": "secondary",
                    "project_type": "custom",
                    "mode": "greenfield",
                },
            ).json()["project"]["project_id"]

            connection = connect(result["paths"])
            try:
                first_project_id = resolve_project_id(connection)
                connection.execute(
                    """
                    UPDATE sessions
                    SET status = 'completed', ended_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                    WHERE project_id = ? AND status = 'active'
                    """,
                    (first_project_id,),
                )
                first_task_id = connection.execute(
                    """
                    SELECT task_id
                    FROM tasks
                    WHERE project_id = ? AND title = 'Define project workspace contracts'
                    """,
                    (first_project_id,),
                ).fetchone()["task_id"]
                second_task_id = connection.execute(
                    """
                    SELECT task_id
                    FROM tasks
                    WHERE project_id = ? AND title = 'Define project workspace contracts'
                    """,
                    (second_project_id,),
                ).fetchone()["task_id"]
                self._enable_blocked_task_auto_recovery(connection, cooldown_seconds=0, project_id=first_project_id)
                self._enable_blocked_task_auto_recovery(connection, cooldown_seconds=0, project_id=second_project_id)
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'blocked', review_state = 'session_failed'
                    WHERE task_id IN (?, ?)
                    """,
                    (first_task_id, second_task_id),
                )
                connection.commit()
            finally:
                connection.close()

            archive_response = client.post(
                "/api/projects/{0}/actions/archive".format(first_project_id),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(archive_response.status_code, 200)

            connection = connect(result["paths"])
            try:
                supervisor_result = run_supervisor_once(connection, allocate_limit=0)
                first_task = connection.execute(
                    "SELECT status, review_state FROM tasks WHERE task_id = ?",
                    (first_task_id,),
                ).fetchone()
                second_task = connection.execute(
                    "SELECT status, review_state FROM tasks WHERE task_id = ?",
                    (second_task_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(len(supervisor_result["auto_recovered_tasks"]), 1)
            self.assertEqual(supervisor_result["auto_recovered_tasks"][0]["task_id"], second_task_id)
            self.assertEqual(first_task["status"], "blocked")
            self.assertEqual(first_task["review_state"], "session_failed")
            self.assertIn(second_task["status"], ("planned", "ready"))


if __name__ == "__main__":
    unittest.main()
