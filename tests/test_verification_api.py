import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.services.bootstrap import bootstrap_project


class VerificationApiTest(unittest.TestCase):
    def test_run_verification_records_evidence_and_lists_runs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Verification API Test", description="verification", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task_row = connection.execute(
                    """
                    SELECT task_id
                    FROM tasks
                    WHERE title = 'Implement FastAPI board endpoint'
                    """
                ).fetchone()
                connection.execute(
                    """
                    UPDATE tasks
                    SET acceptance_criteria_json = '[{"type":"test_passes","command":"python -c \\"print(123)\\"","timeout_seconds":30}]'
                    WHERE task_id = ?
                    """,
                    (task_row["task_id"],),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            run_response = client.post(
                f"/api/tasks/{task_row['task_id']}/actions/run-verification",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(run_response.status_code, 200)
            payload = run_response.json()
            self.assertTrue(payload["overall_passed"])
            self.assertEqual(len(payload["runs"]), 1)
            self.assertEqual(payload["runs"][0]["status"], "passed")
            self.assertTrue(os.path.exists(payload["runs"][0]["log_path"]))

            list_response = client.get("/api/verifications", params={"task_id": task_row["task_id"]})
            self.assertEqual(list_response.status_code, 200)
            listed = list_response.json()["runs"]
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["status"], "passed")
            self.assertEqual(listed[0]["task_id"], task_row["task_id"])

            connection = connect(paths)
            try:
                artifact_row = connection.execute(
                    """
                    SELECT artifact_type, path
                    FROM artifacts
                    WHERE task_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (task_row["task_id"],),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(artifact_row["artifact_type"], "verification_log")
            self.assertTrue(os.path.exists(artifact_row["path"]))

    def test_run_verification_reports_failed_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Verification Failure Test", description="verification failure", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task_row = connection.execute(
                    """
                    SELECT task_id
                    FROM tasks
                    WHERE title = 'Implement FastAPI board endpoint'
                    """
                ).fetchone()
                connection.execute(
                    """
                    UPDATE tasks
                    SET acceptance_criteria_json = '[{"type":"test_passes","command":"python -c \\"import sys; sys.exit(7)\\"","timeout_seconds":30}]'
                    WHERE task_id = ?
                    """,
                    (task_row["task_id"],),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            run_response = client.post(
                f"/api/tasks/{task_row['task_id']}/actions/run-verification",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(run_response.status_code, 200)
            payload = run_response.json()
            self.assertFalse(payload["overall_passed"])
            self.assertEqual(payload["runs"][0]["status"], "failed")
            self.assertEqual(payload["runs"][0]["exit_code"], 7)


if __name__ == "__main__":
    unittest.main()
