import json
import tempfile
import time
import threading
import unittest
from unittest import mock

from maas.db import connect, project_paths
from maas.services.autopilot import (
    _load_cycle_policy,
    _run_orchestrator_with_lease_refresh,
    claim_autopilot_runtime_lease,
    fetch_autopilot_status,
    normalize_autopilot_policy,
    record_autopilot_runtime_result,
    release_autopilot_runtime_lease,
)
from maas.services.bootstrap import bootstrap_project


class AutopilotRuntimeTest(unittest.TestCase):
    def _project_id(self, connection):
        return connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]

    def test_autopilot_runtime_lease_blocks_second_holder_until_expiry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Autopilot Lease Test", description="lease test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = self._project_id(connection)
                policy = normalize_autopilot_policy({"enabled": True, "interval_seconds": 9})

                first = claim_autopilot_runtime_lease(connection, project_id, "lease_a", "worker-a", policy)
                self.assertIsNotNone(first)
                self.assertEqual(first["lease_owner"], "worker-a")

                second = claim_autopilot_runtime_lease(connection, project_id, "lease_b", "worker-b", policy)
                self.assertIsNone(second)

                connection.execute(
                    "UPDATE autopilot_runtime SET lease_expires_at = DATETIME('now', '-1 second') WHERE project_id = ?",
                    (project_id,),
                )
                connection.commit()

                third = claim_autopilot_runtime_lease(connection, project_id, "lease_b", "worker-b", policy)
                self.assertIsNotNone(third)
                self.assertEqual(third["lease_owner"], "worker-b")
                self.assertTrue(third["lease_active"])
            finally:
                connection.close()

    def test_autopilot_status_reads_durable_runtime_without_local_loop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Autopilot Status Test", description="status test", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_id = self._project_id(connection)
                project_row = connection.execute(
                    "SELECT config_json FROM projects WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
                config = json.loads(project_row["config_json"] or "{}")
                config["autopilot"] = normalize_autopilot_policy({"enabled": True, "interval_seconds": 9})
                connection.execute(
                    "UPDATE projects SET config_json = ? WHERE project_id = ?",
                    (json.dumps(config), project_id),
                )
                connection.commit()

                policy = normalize_autopilot_policy({"enabled": True, "interval_seconds": 9})
                claim_autopilot_runtime_lease(connection, project_id, "lease_remote", "remote-worker", policy)
                record_autopilot_runtime_result(
                    connection,
                    project_id,
                    "lease_remote",
                    policy,
                    summary={"assigned_count": 2, "notifications_processed": 1},
                )

                payload = fetch_autopilot_status(connection, paths, project_id)
                self.assertEqual(payload["project_id"], project_id)
                self.assertTrue(payload["runtime"]["running"])
                self.assertEqual(payload["runtime"]["runtime_status"], "running")
                self.assertEqual(payload["runtime"]["lease_owner"], "remote-worker")
                self.assertFalse(payload["runtime"]["holder_is_local"])
                self.assertEqual(payload["runtime"]["last_summary"]["assigned_count"], 2)
                self.assertEqual(payload["runtime"]["last_summary"]["notifications_processed"], 1)

                release_autopilot_runtime_lease(connection, project_id, lease_token="lease_remote", status="stopped")
            finally:
                connection.close()

    def test_load_cycle_policy_prefers_persisted_project_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Autopilot Policy Test", description="policy test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = self._project_id(connection)
                row = connection.execute(
                    "SELECT config_json FROM projects WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
                config = json.loads(row["config_json"] or "{}")
                config["autopilot"] = normalize_autopilot_policy({"enabled": False, "interval_seconds": 27})
                connection.execute(
                    "UPDATE projects SET config_json = ? WHERE project_id = ?",
                    (json.dumps(config), project_id),
                )
                connection.commit()

                loaded = _load_cycle_policy(
                    connection,
                    project_id,
                    normalize_autopilot_policy({"enabled": True, "interval_seconds": 9}),
                )

                self.assertFalse(loaded["enabled"])
                self.assertEqual(loaded["interval_seconds"], 27)
            finally:
                connection.close()

    def test_run_orchestrator_with_lease_refresh_keeps_lease_alive_during_long_cycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Autopilot Lease Refresh Test", description="lease refresh", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_id = self._project_id(connection)
                policy = normalize_autopilot_policy({"enabled": True, "interval_seconds": 1})
                with mock.patch("maas.services.autopilot.AUTOPILOT_LEASE_MIN_SECONDS", 1):
                    claimed = claim_autopilot_runtime_lease(connection, project_id, "lease_refresh", "worker-a", policy)
                    self.assertIsNotNone(claimed)

                    helper_errors = []

                    def run_helper():
                        try:
                            _run_orchestrator_with_lease_refresh(tmpdir, project_id, "lease_refresh", policy)
                        except Exception as exc:  # pragma: no cover - test assertion path
                            helper_errors.append(exc)

                    thread = threading.Thread(
                        target=run_helper,
                        daemon=True,
                    )
                    with mock.patch(
                        "maas.services.autopilot.run_orchestrator_once",
                        side_effect=lambda *args, **kwargs: (time.sleep(4), {"assigned_count": 0})[1],
                    ):
                        thread.start()
                        time.sleep(2.2)
                        competing = claim_autopilot_runtime_lease(connection, project_id, "lease_other", "worker-b", policy)
                        thread.join()

                    self.assertIsNone(competing)
                    self.assertEqual(helper_errors, [])
                    runtime = fetch_autopilot_status(connection, paths, project_id)
                    self.assertEqual(runtime["runtime"]["lease_owner"], "worker-a")
                    self.assertTrue(runtime["runtime"]["running"])
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
