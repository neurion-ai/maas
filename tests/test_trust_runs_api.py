import os
import subprocess
import tempfile
import unittest
from unittest import mock

from maas.db import connect, project_paths
from maas.services.bootstrap import bootstrap_project
from maas.services.codex_mvp import fetch_system_diagnostics
from maas.services.delivery import sync_github_pr
from maas.services.fault_injection import schedule_fault_injection
from maas.services.trust_runs import execute_trust_run
def _init_git_repo(root):
    subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "MAAS Tests"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class TrustRunsApiTest(unittest.TestCase):
    def test_execute_trust_run_records_persisted_report_and_incidents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Trust Run Test", description="trust run", project_type="custom")
            _init_git_repo(tmpdir)
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                git_snapshot = {
                    "is_git_repo": True,
                    "branch": "feature/trust-run",
                    "default_branch": "main",
                    "dirty": False,
                    "gh_installed": True,
                }
                with mock.patch("maas.services.delivery._git_repo_snapshot", return_value=git_snapshot):
                    payload = execute_trust_run(
                        connection,
                        paths,
                        project_id,
                        cycle_limit=6,
                        sleep_seconds=0,
                    )
                diagnostics = fetch_system_diagnostics(connection, project_id, project_paths=paths)
            finally:
                connection.close()

            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["completed_cycles"], 6)
            self.assertGreaterEqual(payload["report"]["faults_applied"], 5)
            self.assertGreaterEqual(payload["incident_count"], 1)
            self.assertTrue(any(item["incident_kind"] == "stop_state" for item in payload["incidents"]))
            self.assertIsNotNone(diagnostics["trust_run"])
            self.assertEqual(diagnostics["trust_run"]["trust_run_id"], payload["trust_run_id"])
            self.assertEqual(diagnostics["trust_run"]["report"]["completed_cycles"], 6)

    def test_execute_trust_run_updates_latest_trust_report_for_shorter_cycle_plan(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Trust Summary Test", description="trust summary", project_type="custom")
            _init_git_repo(tmpdir)
            paths = project_paths(tmpdir)
            connection = connect(paths)
            git_snapshot = {
                "is_git_repo": True,
                "branch": "feature/trust-summary",
                "default_branch": "main",
                "dirty": False,
                "gh_installed": True,
            }
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                with mock.patch("maas.services.delivery._git_repo_snapshot", return_value=git_snapshot):
                    payload = execute_trust_run(
                        connection,
                        paths,
                        project_id,
                        cycle_limit=4,
                        sleep_seconds=0,
                    )
                diagnostics = fetch_system_diagnostics(connection, project_id, project_paths=paths)
            finally:
                connection.close()

            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["completed_cycles"], 4)
            self.assertEqual(diagnostics["trust_run"]["trust_run_id"], payload["trust_run_id"])
            self.assertEqual(diagnostics["trust_run"]["report"]["completed_cycles"], 4)
            self.assertLessEqual(diagnostics["trust_run"]["report"]["faults_applied"], 4)

    def test_injected_delivery_sync_failure_stops_before_external_gh_commands(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Trust Delivery Fault Test", description="trust delivery fault", project_type="custom")
            _init_git_repo(tmpdir)
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task = connection.execute(
                    """
                    SELECT task_id, project_id
                    FROM tasks
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'review',
                        review_state = 'review_requested',
                        acceptance_criteria_json = '[{\"type\":\"test_passes\",\"command\":\"pytest tests/test_trust.py\"}]'
                    WHERE task_id = ?
                    """,
                    (task["task_id"],),
                )
                artifact_dir = os.path.join(paths.artifacts_dir, task["project_id"], "trust-delivery")
                os.makedirs(artifact_dir, exist_ok=True)
                artifact_path = os.path.join(artifact_dir, "delivery.diff")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("diff --git a/app.py b/app.py\n+print('trust delivery')\n")
                connection.execute(
                    """
                    INSERT INTO artifacts (
                        artifact_id, project_id, task_id, session_id, artifact_type, path, metadata_json
                    ) VALUES ('art_trust_delivery', ?, ?, NULL, 'git_diff', ?, '{}')
                    """,
                    (task["project_id"], task["task_id"], artifact_path),
                )
                connection.execute(
                    """
                    INSERT INTO verification_runs (
                        verification_run_id, project_id, task_id, command, status, exit_code, output_excerpt,
                        artifact_id, actor_id, started_at, finished_at
                    ) VALUES (
                        'vrf_trust_delivery', ?, ?, 'pytest tests/test_trust.py', 'passed', 0, 'trust ok',
                        NULL, 'agent_reviewer', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """,
                    (task["project_id"], task["task_id"]),
                )
                schedule_fault_injection(
                    connection,
                    task["project_id"],
                    "delivery",
                    "sync",
                    target_resource_type="task",
                    target_resource_id=task["task_id"],
                    payload={"summary": "Injected GitHub delivery sync failure."},
                    status="pending",
                )
                connection.commit()

                git_snapshot = {
                    "is_git_repo": True,
                    "branch": "feature/trust-delivery",
                    "default_branch": "main",
                    "dirty": False,
                    "gh_installed": True,
                }
                with mock.patch("maas.services.delivery._git_repo_snapshot", return_value=git_snapshot), mock.patch(
                    "maas.services.delivery.subprocess.run",
                    side_effect=AssertionError("gh should not be called when delivery sync fault is injected"),
                ):
                    with self.assertRaises(RuntimeError):
                        sync_github_pr(
                            connection,
                            paths,
                            task_id=task["task_id"],
                            actor_id="agent_allocator",
                            project_id=task["project_id"],
                        )
            finally:
                connection.close()
