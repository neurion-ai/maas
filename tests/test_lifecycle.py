import json
import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect
from maas.services.bootstrap import bootstrap_project
from maas.services.lifecycle import end_session, heartbeat, log_activity, produce_artifact, start_session
from maas.services.security import revoke_task_capabilities


class LifecycleStateTransitionTest(unittest.TestCase):
    def _update_recovery_config(self, connection, **recovery_updates):
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

    def test_completed_session_moves_ready_task_into_review(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Lifecycle Test", description="Lifecycle test", project_type="custom")
            connection = connect(result["paths"])
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE status = 'ready' LIMIT 1"
                ).fetchone()["task_id"]

                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_allocator",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting lifecycle test",
                )
                end_session(connection, session_id, "completed", "Completed lifecycle test")
                status = connection.execute(
                    "SELECT status FROM tasks WHERE task_id = ?",
                    (task_id,),
                ).fetchone()["status"]
            finally:
                connection.close()

            self.assertEqual(status, "review")

    def test_start_session_respects_existing_assignment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Lifecycle Assignment Test", description="Lifecycle assignment test", project_type="custom")
            connection = connect(result["paths"])
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'assigned', assigned_agent_id = 'agent_allocator'
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
                connection.commit()

                with self.assertRaisesRegex(ValueError, "assigned to another agent"):
                    start_session(
                        connection,
                        project_id=project_id,
                        agent_id="agent_researcher",
                        task_id=task_id,
                        provider_type="python_script",
                        status_message="Attempting to steal assignment",
                    )
            finally:
                connection.close()

    def test_start_session_requires_execute_capability(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Lifecycle Capability Test",
                description="Lifecycle capability test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE status = 'ready' LIMIT 1"
                ).fetchone()["task_id"]
                revoke_task_capabilities(
                    connection,
                    project_id,
                    task_id,
                    agent_id="agent_allocator",
                    reason="test_revocation",
                    revoked_by="test_runner",
                )
                connection.commit()

                with self.assertRaisesRegex(PermissionError, "not allowed"):
                    start_session(
                        connection,
                        project_id=project_id,
                        agent_id="agent_allocator",
                        task_id=task_id,
                        provider_type="python_script",
                        status_message="Starting without grant",
                    )
            finally:
                connection.close()

    def test_runtime_actions_require_active_task_capabilities(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Lifecycle Runtime Capability Test",
                description="Lifecycle runtime capability test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE status = 'ready' LIMIT 1"
                ).fetchone()["task_id"]
                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_allocator",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting lifecycle capability test",
                )

                heartbeat(connection, session_id, 25, "Still running")
                log_activity(
                    connection,
                    project_id=project_id,
                    agent_id="agent_allocator",
                    task_id=task_id,
                    action="progress_note",
                    category="runtime",
                    description="Made progress",
                )
                artifact_id = produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    artifact_type="note",
                    path=".maas/artifacts/runtime-note.txt",
                )
                self.assertTrue(artifact_id.startswith("art_"))

                end_session(connection, session_id, "completed", "Done")

                with self.assertRaisesRegex(ValueError, "active"):
                    produce_artifact(
                        connection,
                        project_id=project_id,
                        session_id=session_id,
                        task_id=task_id,
                        artifact_type="note",
                        path=".maas/artifacts/after-end.txt",
                    )
            finally:
                connection.close()

    def test_failed_session_creates_failure_memory_and_blocks_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Lifecycle Failure Test",
                description="Lifecycle failure test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE status = 'ready' LIMIT 1"
                ).fetchone()["task_id"]
                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_allocator",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting lifecycle failure test",
                )

                end_session(connection, session_id, "failed", "Unit test simulated failure")

                task = connection.execute(
                    "SELECT status, review_state FROM tasks WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                failure = connection.execute(
                    """
                    SELECT failure_type, summary
                    FROM failure_log
                    WHERE task_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (task_id,),
                ).fetchone()
                alert = connection.execute(
                    """
                    SELECT title
                    FROM alerts
                    WHERE title = 'Task session failed'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(task["status"], "blocked")
            self.assertEqual(task["review_state"], "session_failed")
            self.assertEqual(failure["failure_type"], "session_failed")
            self.assertIn("Unit test simulated failure", failure["summary"])
            self.assertEqual(alert["title"], "Task session failed")

    def test_failed_session_auto_retries_when_policy_allows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Lifecycle Failed Retry Test",
                description="Lifecycle failed retry test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                self._update_recovery_config(
                    connection,
                    auto_retry_failed_sessions=True,
                    max_failed_session_retries=1,
                    failed_session_retry_cooldown_seconds=45,
                    retry_backoff_multiplier=2,
                    retry_backoff_max_seconds=900,
                )
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE status = 'ready' LIMIT 1"
                ).fetchone()["task_id"]
                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_allocator",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting lifecycle failed retry test",
                )

                end_session(connection, session_id, "failed", "Retryable lifecycle failure")

                task = connection.execute(
                    """
                    SELECT status, review_state, assigned_agent_id, retry_count, last_retry_reason, next_retry_at, next_retry_reason
                    FROM tasks
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
                failure = connection.execute(
                    """
                    SELECT failure_type, summary
                    FROM failure_log
                    WHERE task_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (task_id,),
                ).fetchone()
                auto_retry_audit = connection.execute(
                    """
                    SELECT detail_json
                    FROM audit_trail
                    WHERE resource_id = ? AND action_type = 'auto_retry_task'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (task_id,),
                ).fetchone()
                alert = connection.execute(
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

            self.assertEqual(task["status"], "planned")
            self.assertEqual(task["review_state"], "retry_backoff")
            self.assertIsNone(task["assigned_agent_id"])
            self.assertEqual(task["retry_count"], 1)
            self.assertEqual(task["last_retry_reason"], "session_failed")
            self.assertEqual(task["next_retry_reason"], "session_failed")
            self.assertIsNotNone(task["next_retry_at"])
            self.assertEqual(failure["failure_type"], "session_failed")
            self.assertIn("Retryable lifecycle failure", failure["summary"])
            self.assertIsNotNone(auto_retry_audit)
            self.assertEqual(json.loads(auto_retry_audit["detail_json"])["failure_type"], "session_failed")
            self.assertEqual(alert["status"], "resolved")

    def test_failed_session_auto_retry_without_cooldown_returns_ready(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Lifecycle Failed Retry Ready Test",
                description="Lifecycle failed retry ready test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                self._update_recovery_config(
                    connection,
                    auto_retry_failed_sessions=True,
                    max_failed_session_retries=1,
                    failed_session_retry_cooldown_seconds=0,
                )
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Define project workspace contracts'"
                ).fetchone()["task_id"]
                blocker_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Bootstrap migration runner'"
                ).fetchone()["task_id"]
                connection.execute("UPDATE tasks SET status = 'done' WHERE task_id = ?", (blocker_task_id,))
                connection.commit()
                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_researcher",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting lifecycle failed retry ready test",
                )

                end_session(connection, session_id, "failed", "Retry immediately")

                task = connection.execute(
                    """
                    SELECT status, review_state, retry_count, next_retry_at, next_retry_reason
                    FROM tasks
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(task["status"], "ready")
            self.assertIsNone(task["review_state"])
            self.assertEqual(task["retry_count"], 1)
            self.assertIsNone(task["next_retry_at"])
            self.assertIsNone(task["next_retry_reason"])

    def test_failed_session_auto_retry_respects_task_retry_limit_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Lifecycle Failed Retry Override Test",
                description="Lifecycle failed retry override test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                self._update_recovery_config(
                    connection,
                    auto_retry_failed_sessions=True,
                    max_failed_session_retries=3,
                    failed_session_retry_cooldown_seconds=45,
                )
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE status = 'ready' LIMIT 1"
                ).fetchone()["task_id"]
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            override_response = client.post(
                "/api/tasks/{0}/actions/set-retry-limit".format(task_id),
                json={"actor_id": "agent_allocator", "auto_retry_limit": 0},
            )
            self.assertEqual(override_response.status_code, 200)

            connection = connect(result["paths"])
            try:
                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_allocator",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting lifecycle failed retry override test",
                )

                end_session(connection, session_id, "failed", "Override disabled retries")

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

            self.assertEqual(task["status"], "blocked")
            self.assertEqual(task["review_state"], "session_failed")
            self.assertEqual(task["retry_count"], 0)
            self.assertEqual(task["auto_retry_limit"], 0)
            self.assertIsNone(task["last_retry_reason"])

    def test_failed_session_stays_blocked_when_failed_retry_budget_is_exhausted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Lifecycle Failed Retry Limit Test",
                description="Lifecycle failed retry limit test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                self._update_recovery_config(
                    connection,
                    auto_retry_failed_sessions=True,
                    max_failed_session_retries=1,
                    failed_session_retry_cooldown_seconds=45,
                )
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE status = 'ready' LIMIT 1"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET retry_count = 1, last_retry_reason = 'session_failed'
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
                connection.commit()
                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_allocator",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting lifecycle failed retry limit test",
                )

                end_session(connection, session_id, "failed", "No retry budget remaining")

                task = connection.execute(
                    """
                    SELECT status, review_state, retry_count, last_retry_reason, next_retry_at, next_retry_reason
                    FROM tasks
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
                alert = connection.execute(
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

            self.assertEqual(task["status"], "blocked")
            self.assertEqual(task["review_state"], "session_failed")
            self.assertEqual(task["retry_count"], 1)
            self.assertEqual(task["last_retry_reason"], "session_failed")
            self.assertIsNone(task["next_retry_at"])
            self.assertIsNone(task["next_retry_reason"])
            self.assertEqual(alert["status"], "open")

    def test_reset_retry_state_restores_failed_session_auto_retry_budget(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Lifecycle Reset Retry State Test",
                description="Lifecycle reset retry state test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                self._update_recovery_config(
                    connection,
                    auto_retry_failed_sessions=True,
                    max_failed_session_retries=1,
                    failed_session_retry_cooldown_seconds=45,
                )
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE status = 'ready' LIMIT 1"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET retry_count = 1, last_retry_reason = 'session_failed'
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            reset_response = client.post(
                "/api/tasks/{0}/actions/reset-retry-state".format(task_id),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(reset_response.status_code, 200)
            self.assertEqual(reset_response.json()["retry_count"], 0)

            connection = connect(result["paths"])
            try:
                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_allocator",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting lifecycle reset retry state test",
                )

                end_session(connection, session_id, "failed", "Retry budget restored")

                task = connection.execute(
                    """
                    SELECT status, review_state, retry_count, last_retry_reason, next_retry_at, next_retry_reason
                    FROM tasks
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(task["status"], "planned")
            self.assertEqual(task["review_state"], "retry_backoff")
            self.assertEqual(task["retry_count"], 1)
            self.assertEqual(task["last_retry_reason"], "session_failed")
            self.assertIsNotNone(task["next_retry_at"])
            self.assertEqual(task["next_retry_reason"], "session_failed")

    def test_failed_session_quarantines_session_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Lifecycle Quarantine Test",
                description="Lifecycle quarantine test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE status = 'ready' LIMIT 1"
                ).fetchone()["task_id"]
                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_allocator",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting lifecycle quarantine test",
                )
                artifact_path = os.path.join(result["paths"].artifacts_dir, "quarantine-note.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("quarantine me\n")
                artifact_id = produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    artifact_type="note",
                    path=artifact_path,
                )

                end_session(
                    connection,
                    session_id,
                    "failed",
                    "Unit test simulated failure with artifact",
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
            finally:
                connection.close()

            metadata = json.loads(artifact["metadata_json"])
            self.assertFalse(os.path.exists(artifact_path))
            self.assertTrue(os.path.exists(artifact["path"]))
            self.assertTrue(
                os.path.commonpath([os.path.abspath(result["paths"].quarantine_dir), os.path.abspath(artifact["path"])])
                == os.path.abspath(result["paths"].quarantine_dir)
            )
            self.assertTrue(metadata["quarantined"])
            self.assertEqual(metadata["quarantine_reason"], "session_failed")
            self.assertEqual(metadata["quarantined_from_path"], artifact_path)

    def test_failed_session_quarantines_duplicate_artifact_rows_for_same_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Lifecycle Duplicate Quarantine Test",
                description="Lifecycle duplicate quarantine test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE status = 'ready' LIMIT 1"
                ).fetchone()["task_id"]
                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_allocator",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting duplicate quarantine test",
                )
                artifact_path = os.path.join(result["paths"].artifacts_dir, "duplicate-quarantine-note.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("duplicate quarantine me\n")
                first_artifact_id = produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    artifact_type="note",
                    path=artifact_path,
                )
                second_artifact_id = produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    artifact_type="note_copy",
                    path=artifact_path,
                )

                end_session(
                    connection,
                    session_id,
                    "failed",
                    "Unit test simulated failure with duplicate artifacts",
                    project_paths=result["paths"],
                )

                artifacts = connection.execute(
                    """
                    SELECT artifact_id, path, metadata_json
                    FROM artifacts
                    WHERE artifact_id IN (?, ?)
                    ORDER BY artifact_id ASC
                    """,
                    (first_artifact_id, second_artifact_id),
                ).fetchall()
            finally:
                connection.close()

            self.assertFalse(os.path.exists(artifact_path))
            self.assertEqual(len(artifacts), 2)
            self.assertEqual(artifacts[0]["path"], artifacts[1]["path"])
            self.assertTrue(os.path.exists(artifacts[0]["path"]))
            for artifact in artifacts:
                metadata = json.loads(artifact["metadata_json"])
                self.assertTrue(metadata["quarantined"])
                self.assertEqual(metadata["quarantine_reason"], "session_failed")
                self.assertEqual(metadata["quarantined_from_path"], artifact_path)


if __name__ == "__main__":
    unittest.main()
