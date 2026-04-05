import subprocess
import tempfile
import unittest
from unittest import mock

from maas.db import connect, project_paths
from maas.services.autopilot import update_project_autopilot_policy
from maas.services.bootstrap import bootstrap_project
from maas.services.codex_mvp import fetch_system_diagnostics
from maas.services.trust_gate import fetch_project_unattended_trust, update_project_unattended_mode
from maas.services.trust_runs import execute_trust_run


def _init_git_repo(root):
    subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "MAAS Tests"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class TrustGateApiTest(unittest.TestCase):
    def test_trust_gate_reports_missing_evidence_and_disabled_autopilot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Trust Gate Missing Test", description="trust gate missing", project_type="custom")
            _init_git_repo(tmpdir)
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                payload = fetch_project_unattended_trust(connection, paths, project_id)
            finally:
                connection.close()

            self.assertFalse(payload["eligible"])
            self.assertEqual(payload["status"], "unverified")
            blocker_codes = {item["code"] for item in payload["blockers"]}
            self.assertIn("trust_evidence_missing", blocker_codes)
            self.assertIn("autopilot_disabled", blocker_codes)

    def test_passing_trust_run_makes_project_eligible_and_arms_unattended_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Trust Gate Eligible Test", description="trust gate eligible", project_type="custom")
            _init_git_repo(tmpdir)
            paths = project_paths(tmpdir)
            connection = connect(paths)
            git_snapshot = {
                "is_git_repo": True,
                "branch": "feature/trust-gate",
                "default_branch": "main",
                "dirty": False,
                "gh_installed": True,
            }
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                update_project_autopilot_policy(connection, paths, project_id, "agent_allocator", {"enabled": True})
                with mock.patch("maas.services.delivery._git_repo_snapshot", return_value=git_snapshot):
                    trust_run = execute_trust_run(connection, paths, project_id, cycle_limit=6, sleep_seconds=0)
                gate = fetch_project_unattended_trust(connection, paths, project_id)
                armed = update_project_unattended_mode(connection, paths, project_id, "agent_allocator", True)
                diagnostics = fetch_system_diagnostics(connection, project_id, project_paths=paths)
            finally:
                connection.close()

            self.assertEqual(trust_run["report"]["status"], "passed")
            self.assertTrue(gate["eligible"])
            self.assertEqual(gate["status"], "eligible")
            self.assertEqual(armed["status"], "armed")
            self.assertTrue(armed["unattended_mode_requested"])
            self.assertIsNotNone(diagnostics["trust_gate"])
            self.assertEqual(diagnostics["trust_gate"]["status"], "armed")

    def test_update_unattended_mode_rejects_ineligible_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Trust Gate Reject Test", description="trust gate reject", project_type="custom")
            _init_git_repo(tmpdir)
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                with self.assertRaises(ValueError):
                    update_project_unattended_mode(connection, paths, project_id, "agent_allocator", True)
            finally:
                connection.close()
