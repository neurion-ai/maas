import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.services.bootstrap import bootstrap_project


class VerificationApiTest(unittest.TestCase):
    def _create_brownfield_repo(self, root):
        os.makedirs(os.path.join(root, "src"), exist_ok=True)
        with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as handle:
            handle.write("# Imported Repo\n")
        with open(os.path.join(root, "pyproject.toml"), "w", encoding="utf-8") as handle:
            handle.write("[project]\nname='imported-repo'\n")
        with open(os.path.join(root, "src", "app.py"), "w", encoding="utf-8") as handle:
            handle.write("print('hello')\n")

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

    def test_run_verification_can_auto_approve_low_risk_review_work(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Verification Auto Review Test", description="auto review", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task_row = connection.execute(
                    """
                    SELECT task_id
                    FROM tasks
                    WHERE title = 'Validate seeded lifecycle semantics'
                    """
                ).fetchone()
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'review',
                        review_state = 'awaiting_review',
                        priority = 45,
                        acceptance_criteria_json = '[{"type":"test_passes","command":"python -c \\"print(123)\\"","timeout_seconds":30}]'
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
            self.assertEqual(payload["auto_review"]["decision"], "approve")

            connection = connect(paths)
            try:
                updated_task = connection.execute(
                    "SELECT status, review_state FROM tasks WHERE task_id = ?",
                    (task_row["task_id"],),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(updated_task["status"], "done")
            self.assertEqual(updated_task["review_state"], "approved")

    def test_run_verification_keeps_high_priority_review_work_manual(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Verification Manual Review Test", description="manual review", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task_row = connection.execute(
                    """
                    SELECT task_id
                    FROM tasks
                    WHERE title = 'Validate seeded lifecycle semantics'
                    """
                ).fetchone()
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'review',
                        review_state = 'awaiting_review',
                        priority = 95,
                        acceptance_criteria_json = '[{"type":"test_passes","command":"python -c \\"print(123)\\"","timeout_seconds":30}]'
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
            self.assertEqual(payload["auto_review"]["decision"], "manual_review")

            connection = connect(paths)
            try:
                updated_task = connection.execute(
                    "SELECT status, review_state FROM tasks WHERE task_id = ?",
                    (task_row["task_id"],),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(updated_task["status"], "review")
            self.assertEqual(updated_task["review_state"], "awaiting_review")

    def test_run_verification_keeps_brownfield_onboarding_review_manual(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = os.path.join(tmpdir, "workspace")
            repo_root = os.path.join(tmpdir, "repo")
            os.makedirs(workspace_root, exist_ok=True)
            os.makedirs(repo_root, exist_ok=True)
            self._create_brownfield_repo(repo_root)
            bootstrap_project(workspace_root, name="Primary Project", description="primary", project_type="custom")
            client = TestClient(create_app(workspace_root))

            create_response = client.post(
                "/api/projects",
                json={
                    "actor_id": "agent_allocator",
                    "name": "Imported",
                    "description": "brownfield",
                    "project_type": "custom",
                    "mode": "brownfield",
                    "source_root": repo_root,
                },
            )
            self.assertEqual(create_response.status_code, 200)
            project_id = create_response.json()["project"]["project_id"]

            paths = project_paths(workspace_root)
            connection = connect(paths)
            try:
                task_row = connection.execute(
                    """
                    SELECT task_id
                    FROM tasks
                    WHERE project_id = ? AND title = 'Review imported project understanding'
                    """,
                    (project_id,),
                ).fetchone()
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'review',
                        review_state = 'awaiting_review',
                        priority = 1,
                        acceptance_criteria_json = '[{"type":"test_passes","command":"python -c \\"print(123)\\"","timeout_seconds":30}]'
                    WHERE task_id = ?
                    """,
                    (task_row["task_id"],),
                )
                connection.commit()
            finally:
                connection.close()

            run_response = client.post(
                f"/api/tasks/{task_row['task_id']}/actions/run-verification",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(run_response.status_code, 200)
            payload = run_response.json()
            self.assertEqual(payload["auto_review"]["decision"], "manual_review")

            connection = connect(paths)
            try:
                updated_task = connection.execute(
                    "SELECT status, review_state FROM tasks WHERE task_id = ?",
                    (task_row["task_id"],),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(updated_task["status"], "review")
            self.assertEqual(updated_task["review_state"], "awaiting_review")


if __name__ == "__main__":
    unittest.main()
