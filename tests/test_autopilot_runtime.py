import json
import tempfile
import time
import threading
import unittest
from unittest import mock

from maas.db import connect, project_paths
from maas.services.autopilot import (
    _apply_idle_cycle_governance,
    _load_cycle_policy,
    _run_orchestrator_with_lease_refresh,
    claim_autopilot_runtime_lease,
    fetch_autopilot_status,
    normalize_autopilot_policy,
    record_autopilot_runtime_result,
    release_autopilot_runtime_lease,
)
from maas.services.bootstrap import bootstrap_project
from maas.services.notifications import fetch_notification_outbox, queue_notification_event


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

    def test_idle_cycle_governance_triggers_notification_on_threshold_crossing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Autopilot Idle Alert Test", description="idle alert", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = self._project_id(connection)
                row = connection.execute(
                    "SELECT config_json FROM projects WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
                config = json.loads(row["config_json"] or "{}")
                config["notifications"] = {
                    "webhook_urls": ["https://example.test/maas"],
                    "minimum_severity": "warning",
                    "enabled_events": ["escalation_requested"],
                }
                connection.execute(
                    "UPDATE projects SET config_json = ? WHERE project_id = ?",
                    (json.dumps(config), project_id),
                )
                connection.commit()
                policy = normalize_autopilot_policy(
                    {"enabled": True, "interval_seconds": 9, "max_idle_cycles_before_alert": 2}
                )
                first_summary = _apply_idle_cycle_governance(
                    connection,
                    project_id,
                    policy,
                    {
                        "assigned_count": 0,
                        "provider_jobs_queued": 0,
                        "provider_jobs_processed": 0,
                        "provider_jobs_dispatched": 0,
                        "notifications_processed": 0,
                        "why_idle": "No runnable work exists.",
                        "governance_gate": {"blocked": False, "reason": None},
                    },
                    {},
                )
                self.assertEqual(first_summary["consecutive_idle_cycles"], 1)
                self.assertFalse(first_summary["idle_alert_triggered"])
                self.assertEqual(fetch_notification_outbox(connection, project_id=project_id), [])

                second_summary = _apply_idle_cycle_governance(
                    connection,
                    project_id,
                    policy,
                    {
                        "assigned_count": 0,
                        "provider_jobs_queued": 0,
                        "provider_jobs_processed": 0,
                        "provider_jobs_dispatched": 0,
                        "notifications_processed": 0,
                        "why_idle": "No runnable work exists.",
                        "governance_gate": {"blocked": False, "reason": None},
                    },
                    first_summary,
                )
                self.assertEqual(second_summary["consecutive_idle_cycles"], 2)
                self.assertTrue(second_summary["idle_alert_triggered"])
                notifications = fetch_notification_outbox(connection, project_id=project_id)
                self.assertEqual(len(notifications), 1)

                third_summary = _apply_idle_cycle_governance(
                    connection,
                    project_id,
                    policy,
                    {
                        "assigned_count": 0,
                        "provider_jobs_queued": 0,
                        "provider_jobs_processed": 0,
                        "provider_jobs_dispatched": 0,
                        "notifications_processed": 0,
                        "why_idle": "No runnable work exists.",
                        "governance_gate": {"blocked": False, "reason": None},
                    },
                    second_summary,
                )
                self.assertEqual(third_summary["consecutive_idle_cycles"], 3)
                self.assertFalse(third_summary["idle_alert_triggered"])
                notifications = fetch_notification_outbox(connection, project_id=project_id)
                self.assertEqual(len(notifications), 1)
            finally:
                connection.close()

    def test_autopilot_governance_surfaces_richer_pressure_signals(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Autopilot Governance Test", description="governance test", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_id = self._project_id(connection)
                task = connection.execute(
                    """
                    SELECT task_id
                    FROM tasks
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                agent_id = connection.execute(
                    "SELECT agent_id FROM agents ORDER BY created_at ASC LIMIT 1"
                ).fetchone()["agent_id"]
                project_row = connection.execute(
                    "SELECT config_json FROM projects WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
                config = json.loads(project_row["config_json"] or "{}")
                config["autopilot"] = normalize_autopilot_policy(
                    {
                        "enabled": True,
                        "interval_seconds": 9,
                        "stop_when_doctor_blocked": False,
                        "max_stale_runs": 1,
                        "max_repeated_failure_incidents": 1,
                        "max_notification_failures": 1,
                    }
                )
                config["notifications"] = {
                    "webhook_urls": ["https://example.test/maas"],
                    "minimum_severity": "warning",
                    "enabled_events": ["escalation_requested"],
                }
                connection.execute(
                    "UPDATE projects SET config_json = ? WHERE project_id = ?",
                    (json.dumps(config), project_id),
                )
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'in_progress',
                        assigned_agent_id = ?
                    WHERE task_id = ?
                    """,
                    (agent_id, task["task_id"]),
                )
                connection.execute(
                    """
                    INSERT INTO sessions (
                        session_id, project_id, agent_id, task_id, status, provider_type, progress_pct,
                        status_message, last_heartbeat_at, started_at, ended_at, updated_at
                    ) VALUES (
                        'sess_governance', ?, ?, ?, 'active', 'openai_codex', 35,
                        'Working through governance test', DATETIME('now', '-180 seconds'), DATETIME('now', '-20 minutes'), NULL, CURRENT_TIMESTAMP
                    )
                    """,
                    (project_id, agent_id, task["task_id"]),
                )
                connection.execute(
                    """
                    INSERT INTO failure_log (
                        failure_id, project_id, task_id, session_id, agent_id, failure_type, summary, detail_json
                    ) VALUES
                        ('fail_gov_1', ?, ?, NULL, ?, 'session_failed', 'First failure', '{}'),
                        ('fail_gov_2', ?, ?, NULL, ?, 'session_failed', 'Second failure', '{}')
                    """,
                    (project_id, task["task_id"], agent_id, project_id, task["task_id"], agent_id),
                )
                connection.execute(
                    """
                    INSERT INTO alerts (
                        alert_id, project_id, severity, title, description, status
                    ) VALUES ('alert_gov_repeat', ?, 'critical', 'Repeated task failures', ?, 'open')
                    """,
                    (
                        project_id,
                        "Task {0} (Governance task) has failed 2 times. Latest failure: Second failure".format(
                            task["task_id"]
                        ),
                    ),
                )
                queue_notification_event(
                    connection,
                    project_id,
                    "escalation_requested",
                    "warning",
                    "Governance notification",
                    "Testing failed notification pressure",
                    resource_type="project",
                    resource_id=project_id,
                )
                connection.execute(
                    "UPDATE notification_outbox SET status = 'failed' WHERE project_id = ?",
                    (project_id,),
                )
                connection.commit()

                with mock.patch(
                    "maas.services.environment_doctor.fetch_environment_doctor",
                    return_value={
                        "summary": {
                            "status": "ready",
                            "detail": "Doctor is ready.",
                        },
                        "progress": {"status": "running"},
                    },
                ):
                    payload = fetch_autopilot_status(connection, paths, project_id)
            finally:
                connection.close()

            gate = payload["governance_gate"]
            self.assertTrue(gate["blocked"])
            signal_map = {item["code"]: item for item in gate["signals"]}
            self.assertIn("stale_run_limit", signal_map)
            self.assertIn("repeated_failure_limit", signal_map)
            self.assertIn("notification_failure_limit", signal_map)
            self.assertTrue(signal_map["stale_run_limit"]["blocking"])
            self.assertEqual(
                signal_map["repeated_failure_limit"]["operator_actions"][0]["action"],
                "resolve_repeated_failures",
            )
            self.assertEqual(gate["thresholds"]["max_stale_runs"], 1)
            self.assertEqual(gate["thresholds"]["max_repeated_failure_incidents"], 1)

    def test_autopilot_governance_thresholds_do_not_emit_zero_count_pressure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Autopilot Quiet Governance Test", description="quiet governance", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_id = self._project_id(connection)
                row = connection.execute(
                    "SELECT config_json FROM projects WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
                config = json.loads(row["config_json"] or "{}")
                config["autopilot"] = normalize_autopilot_policy(
                    {
                        "enabled": True,
                        "interval_seconds": 9,
                        "stop_when_doctor_blocked": False,
                        "max_review_queue": 2,
                        "max_blocked_queue": 2,
                        "max_stale_runs": 1,
                        "max_repeated_failure_incidents": 1,
                        "max_notification_failures": 1,
                    }
                )
                connection.execute(
                    "UPDATE projects SET config_json = ? WHERE project_id = ?",
                    (json.dumps(config), project_id),
                )
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'ready',
                        assigned_agent_id = NULL
                    WHERE project_id = ?
                    """,
                    (project_id,),
                )
                connection.commit()

                with mock.patch(
                    "maas.services.environment_doctor.fetch_environment_doctor",
                    return_value={
                        "summary": {
                            "status": "ready",
                            "detail": "Doctor is ready.",
                        },
                        "progress": {"status": "running"},
                    },
                ):
                    payload = fetch_autopilot_status(connection, paths, project_id)
            finally:
                connection.close()

            gate = payload["governance_gate"]
            self.assertFalse(gate["blocked"])
            self.assertEqual(gate["signals"], [])
            self.assertEqual(gate["summary"], "Autopilot governance thresholds are clear.")


if __name__ == "__main__":
    unittest.main()
