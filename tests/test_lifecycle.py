import tempfile
import unittest

from maas.db import connect
from maas.services.bootstrap import bootstrap_project
from maas.services.lifecycle import end_session, start_session


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


if __name__ == "__main__":
    unittest.main()
