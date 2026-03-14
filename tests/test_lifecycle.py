import json
import os
import tempfile
import unittest

from maas.db import connect
from maas.services.bootstrap import bootstrap_project
from maas.services.lifecycle import end_session, heartbeat, log_activity, produce_artifact, start_session
from maas.services.security import revoke_task_capabilities


class LifecycleStateTransitionTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
