import os
import subprocess
import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.services.bootstrap import bootstrap_project


def _init_git_repo(root, extra_files=None):
    extra_files = extra_files or {}
    for relative_path, content in extra_files.items():
        full_path = os.path.join(root, relative_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as handle:
            handle.write(content)
    subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "MAAS Tests"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class GitWorkspaceApiTest(unittest.TestCase):
    def test_prepare_git_workspace_and_refresh_diff(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = os.path.join(tmpdir, "workspace")
            repo_root = os.path.join(tmpdir, "repo")
            os.makedirs(workspace_root, exist_ok=True)
            os.makedirs(repo_root, exist_ok=True)
            bootstrap_project(workspace_root, name="Primary Project", description="primary", project_type="custom")
            _init_git_repo(
                repo_root,
                {
                    "README.md": "# Imported repo\n",
                    "src/app.py": "print('ok')\n",
                },
            )

            client = TestClient(create_app(workspace_root))
            project_payload = client.post(
                "/api/projects",
                json={
                    "actor_id": "agent_allocator",
                    "name": "Imported Repo",
                    "description": "brownfield import",
                    "project_type": "custom",
                    "mode": "brownfield",
                    "source_root": repo_root,
                },
            ).json()
            project_id = project_payload["project"]["project_id"]

            connection = connect(project_paths(workspace_root))
            try:
                task_row = connection.execute(
                    """
                    SELECT task_id
                    FROM tasks
                    WHERE project_id = ?
                      AND title LIKE 'Map imported source area:%'
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (project_id,),
                ).fetchone()
            finally:
                connection.close()

            prepare_response = client.post(
                f"/api/tasks/{task_row['task_id']}/actions/prepare-git-workspace",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(prepare_response.status_code, 200)
            prepare_payload = prepare_response.json()
            self.assertTrue(os.path.isdir(prepare_payload["worktree_path"]))
            self.assertTrue(prepare_payload["branch_name"].startswith("maas/"))

            with open(os.path.join(prepare_payload["worktree_path"], "src", "app.py"), "a", encoding="utf-8") as handle:
                handle.write("print('changed')\n")

            refresh_response = client.post(
                f"/api/tasks/{task_row['task_id']}/actions/refresh-git-diff",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(refresh_response.status_code, 200)
            refresh_payload = refresh_response.json()
            self.assertGreaterEqual(refresh_payload["dirty_file_count"], 1)
            self.assertIsNotNone(refresh_payload["last_diff_artifact_id"])

            detail_response = client.get(f"/api/tasks/{task_row['task_id']}/git-workspace")
            self.assertEqual(detail_response.status_code, 200)
            detail_payload = detail_response.json()
            self.assertIn("src/app.py", detail_payload["changed_files"])

            connection = connect(project_paths(workspace_root))
            try:
                artifact_row = connection.execute(
                    """
                    SELECT artifact_type, path
                    FROM artifacts
                    WHERE artifact_id = ?
                    """,
                    (refresh_payload["last_diff_artifact_id"],),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(artifact_row["artifact_type"], "git_diff")
            self.assertTrue(os.path.exists(artifact_row["path"]))

    def test_prepare_git_workspace_reports_operation_metadata_and_reuses_existing_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = os.path.join(tmpdir, "workspace")
            repo_root = os.path.join(tmpdir, "repo")
            os.makedirs(workspace_root, exist_ok=True)
            os.makedirs(repo_root, exist_ok=True)
            bootstrap_project(workspace_root, name="Primary Project", description="primary", project_type="custom")
            _init_git_repo(
                repo_root,
                {
                    "README.md": "# Imported repo\n",
                    "src/app.py": "print('ok')\n",
                },
            )

            client = TestClient(create_app(workspace_root))
            project_payload = client.post(
                "/api/projects",
                json={
                    "actor_id": "agent_allocator",
                    "name": "Imported Repo",
                    "description": "brownfield import",
                    "project_type": "custom",
                    "mode": "brownfield",
                    "source_root": repo_root,
                },
            ).json()
            project_id = project_payload["project"]["project_id"]

            connection = connect(project_paths(workspace_root))
            try:
                task_row = connection.execute(
                    """
                    SELECT task_id
                    FROM tasks
                    WHERE project_id = ?
                      AND title LIKE 'Map imported source area:%'
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (project_id,),
                ).fetchone()
            finally:
                connection.close()

            first = client.post(
                f"/api/tasks/{task_row['task_id']}/actions/prepare-git-workspace",
                json={"actor_id": "agent_allocator"},
            )
            second = client.post(
                f"/api/tasks/{task_row['task_id']}/actions/prepare-git-workspace",
                json={"actor_id": "agent_allocator"},
            )

            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            self.assertEqual(first.json()["workspace_id"], second.json()["workspace_id"])
            self.assertEqual(second.json()["operation_state"], "succeeded")
            self.assertTrue(second.json()["retryable"])
            self.assertFalse(second.json()["terminal_failure"])
            self.assertEqual(second.json()["base_ref"], first.json()["head_commit"])
            self.assertNotEqual(second.json()["base_ref"], second.json()["branch_name"])
            self.assertEqual(second.json()["last_external_result"]["prepare_state"], "ready")
            self.assertEqual(second.json()["last_external_result"]["last_prepare_mode"], "reused")
            self.assertGreaterEqual(second.json()["last_external_result"]["prepare_attempts"], 2)

    def test_prepare_git_workspace_marks_failed_when_path_exists_without_git_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = os.path.join(tmpdir, "workspace")
            repo_root = os.path.join(tmpdir, "repo")
            os.makedirs(workspace_root, exist_ok=True)
            os.makedirs(repo_root, exist_ok=True)
            bootstrap_project(workspace_root, name="Primary Project", description="primary", project_type="custom")
            _init_git_repo(
                repo_root,
                {
                    "README.md": "# Imported repo\n",
                    "src/app.py": "print('ok')\n",
                },
            )

            client = TestClient(create_app(workspace_root))
            project_payload = client.post(
                "/api/projects",
                json={
                    "actor_id": "agent_allocator",
                    "name": "Imported Repo",
                    "description": "brownfield import",
                    "project_type": "custom",
                    "mode": "brownfield",
                    "source_root": repo_root,
                },
            ).json()
            project_id = project_payload["project"]["project_id"]
            paths = project_paths(workspace_root)

            connection = connect(paths)
            try:
                task_row = connection.execute(
                    """
                    SELECT task_id
                    FROM tasks
                    WHERE project_id = ?
                      AND title LIKE 'Map imported source area:%'
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (project_id,),
                ).fetchone()
            finally:
                connection.close()

            expected_path = paths.task_git_worktree(project_id, task_row["task_id"])
            os.makedirs(expected_path, exist_ok=True)
            with open(os.path.join(expected_path, "not-a-worktree.txt"), "w", encoding="utf-8") as handle:
                handle.write("stale path\n")

            response = client.post(
                f"/api/tasks/{task_row['task_id']}/actions/prepare-git-workspace",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("not a managed git worktree", response.json()["detail"])

            detail_response = client.get(f"/api/tasks/{task_row['task_id']}/git-workspace")
            self.assertEqual(detail_response.status_code, 200)
            detail_payload = detail_response.json()
            self.assertEqual(detail_payload["operation_state"], "failed_terminal")
            self.assertFalse(detail_payload["retryable"])
            self.assertTrue(detail_payload["terminal_failure"])
            self.assertEqual(detail_payload["last_external_result"]["prepare_state"], "failed")
            self.assertIn("not a managed git worktree", detail_payload["last_external_result"]["last_prepare_error"])

    def test_prepare_git_workspace_rejects_non_git_source_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = os.path.join(tmpdir, "workspace")
            repo_root = os.path.join(tmpdir, "repo")
            os.makedirs(workspace_root, exist_ok=True)
            os.makedirs(repo_root, exist_ok=True)
            with open(os.path.join(repo_root, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("# not git\n")
            bootstrap_project(workspace_root, name="Primary Project", description="primary", project_type="custom")

            client = TestClient(create_app(workspace_root))
            project_payload = client.post(
                "/api/projects",
                json={
                    "actor_id": "agent_allocator",
                    "name": "Imported Repo",
                    "description": "brownfield import",
                    "project_type": "custom",
                    "mode": "brownfield",
                    "source_root": repo_root,
                },
            ).json()
            project_id = project_payload["project"]["project_id"]

            connection = connect(project_paths(workspace_root))
            try:
                task_row = connection.execute(
                    """
                    SELECT task_id
                    FROM tasks
                    WHERE project_id = ?
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (project_id,),
                ).fetchone()
            finally:
                connection.close()

            response = client.post(
                f"/api/tasks/{task_row['task_id']}/actions/prepare-git-workspace",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("git repository", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
