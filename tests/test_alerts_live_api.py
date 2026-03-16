import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.services.bootstrap import bootstrap_project
from maas.services.escalations import request_escalation
from maas.services.lifecycle import end_session, produce_artifact, start_session
from maas.services.live import build_live_snapshot


class AlertsAndLiveApiTest(unittest.TestCase):
    def _update_recovery_config(self, project_root, **recovery_updates):
        connection = connect(project_paths(project_root))
        try:
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
        finally:
            connection.close()

    def test_alert_actions_and_live_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Live Test", description="Live test", project_type="custom")
            client = TestClient(create_app(tmpdir))
            connection = connect(project_paths(tmpdir))
            try:
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    INSERT INTO failure_log (
                        failure_id, project_id, task_id, session_id, agent_id, failure_type, summary, detail_json
                    )
                    SELECT 'fail_demo', project_id, ?, session_id, agent_id, 'session_failed', 'Demo failure', '{}'
                    FROM sessions
                    WHERE task_id = ?
                    LIMIT 1
                    """,
                    (task_id, task_id),
                )
                connection.commit()
            finally:
                connection.close()

            live_response = client.get("/api/live")
            self.assertEqual(live_response.status_code, 200)
            live_payload = live_response.json()
            self.assertIn("counts", live_payload)
            self.assertIn("revision", live_payload)
            self.assertEqual(live_payload["counts"]["failures_total"], 1)

            alerts_response = client.get("/api/alerts")
            self.assertEqual(alerts_response.status_code, 200)
            alerts_payload = alerts_response.json()
            self.assertGreaterEqual(alerts_payload["summary"]["open"], 1)
            alert_id = alerts_payload["alerts"][0]["alert_id"]

            ack_response = client.post(
                "/api/alerts/{0}/actions/acknowledge".format(alert_id),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(ack_response.status_code, 200)

            resolved_response = client.post(
                "/api/alerts/{0}/actions/resolve".format(alert_id),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(resolved_response.status_code, 200)

            refreshed = client.get("/api/alerts").json()
            matching = [alert for alert in refreshed["alerts"] if alert["alert_id"] == alert_id]
            self.assertEqual(matching[0]["status"], "resolved")

            failures_response = client.get("/api/failures")
            self.assertEqual(failures_response.status_code, 200)
            failures_payload = failures_response.json()
            self.assertEqual(failures_payload["summary"]["total_failures"], 1)
            self.assertEqual(failures_payload["recent"][0]["failure_type"], "session_failed")

    def test_failures_api_exposes_quarantined_artifacts_for_failed_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Failure Quarantine API Test", description="Failure quarantine api test", project_type="custom")
            connection = connect(project_paths(tmpdir))
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
                    status_message="Starting failure quarantine api test",
                )
                artifact_path = os.path.join(result["paths"].artifacts_dir, "failure-api-note.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("quarantine api\n")
                produce_artifact(
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
                    "Failure with quarantined artifact",
                    project_paths=result["paths"],
                )
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            failures_payload = client.get("/api/failures").json()
            recent_failure = failures_payload["recent"][0]

            self.assertEqual(recent_failure["failure_type"], "session_failed")
            self.assertEqual(recent_failure["quarantined_artifact_count"], 1)
            self.assertEqual(recent_failure["quarantined_artifacts"][0]["quarantined_from_path"], artifact_path)

    def test_failures_api_prefers_restore_and_requeue_for_recoverable_quarantined_failures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Failure Operator Action Queue Test",
                description="Failure operator action queue test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
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
                    status_message="Starting failure operator action queue test",
                )
                artifact_path = os.path.join(result["paths"].artifacts_dir, "failure-operator-action-queue.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("queue action\n")
                produce_artifact(
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
                    "Failure with recoverable quarantined artifacts",
                    project_paths=result["paths"],
                )
                queue_id = connection.execute(
                    "SELECT queue_id FROM quarantine_queue WHERE session_id = ?",
                    (session_id,),
                ).fetchone()["queue_id"]
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            recent_failure = client.get("/api/failures").json()["recent"][0]

            self.assertEqual(
                recent_failure["operator_action"],
                {
                    "action": "restore_and_requeue_quarantine_entry",
                    "label": "Restore + requeue",
                    "resource_type": "quarantine",
                    "resource_id": queue_id,
                    "related_task_id": task_id,
                },
            )
            self.assertEqual(
                recent_failure["secondary_operator_action"],
                {
                    "action": "dismiss_quarantine_entry",
                    "label": "Dismiss",
                    "resource_type": "quarantine",
                    "resource_id": queue_id,
                    "related_task_id": task_id,
                },
            )

    def test_failures_api_uses_recover_and_requeue_for_recoverable_nonquarantined_failures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(
                tmpdir,
                name="Failure Operator Action Recover Test",
                description="Failure operator action recover test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
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
                    status_message="Starting failure operator action recover test",
                )
                end_session(connection, session_id, "failed", "Failure without artifacts")
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            recent_failure = client.get("/api/failures").json()["recent"][0]

            self.assertEqual(
                recent_failure["operator_action"],
                {
                    "action": "recover_and_requeue_task",
                    "label": "Recover + requeue",
                    "resource_type": "task",
                    "resource_id": task_id,
                },
            )

    def test_failures_api_uses_restore_for_open_quarantine_when_task_is_not_recoverable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Failure Operator Action Restore Test",
                description="Failure operator action restore test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
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
                    status_message="Starting failure operator action restore test",
                )
                artifact_path = os.path.join(result["paths"].artifacts_dir, "failure-operator-action-restore.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("restore action\n")
                produce_artifact(
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
                    "Failure with open quarantine but nonrecoverable task state",
                    project_paths=result["paths"],
                )
                failure_id = connection.execute(
                    "SELECT failure_id FROM failure_log WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
                    (session_id,),
                ).fetchone()["failure_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET review_state = 'blocked_by_dependency'
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            recent_failure = client.get("/api/failures").json()["recent"][0]

            self.assertEqual(
                recent_failure["operator_action"],
                {
                    "action": "restore_failure_artifacts",
                    "label": "Restore artifacts",
                    "resource_type": "failure",
                    "resource_id": failure_id,
                    "related_task_id": task_id,
                },
            )
            self.assertEqual(
                recent_failure["secondary_operator_action"],
                {
                    "action": "dismiss_quarantine_entry",
                    "label": "Dismiss",
                    "resource_type": "quarantine",
                    "resource_id": recent_failure["quarantine_queue_id"],
                    "related_task_id": task_id,
                },
            )

    def test_failures_api_uses_reopen_for_dismissed_quarantine_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Failure Operator Action Reopen Test",
                description="Failure operator action reopen test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
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
                    status_message="Starting failure operator action reopen test",
                )
                artifact_path = os.path.join(result["paths"].artifacts_dir, "failure-operator-action-reopen.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("reopen action\n")
                produce_artifact(
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
                    "Failure with dismissed quarantine entry",
                    project_paths=result["paths"],
                )
                queue_id = connection.execute(
                    "SELECT queue_id FROM quarantine_queue WHERE session_id = ?",
                    (session_id,),
                ).fetchone()["queue_id"]
                connection.execute(
                    """
                    UPDATE quarantine_queue
                    SET status = 'dismissed', resolution_note = 'quarantine_dismissed', resolved_at = CURRENT_TIMESTAMP
                    WHERE queue_id = ?
                    """,
                    (queue_id,),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            recent_failure = client.get("/api/failures").json()["recent"][0]

            self.assertEqual(
                recent_failure["operator_action"],
                {
                    "action": "reopen_quarantine_entry",
                    "label": "Reopen",
                    "resource_type": "quarantine",
                    "resource_id": queue_id,
                    "related_task_id": task_id,
                },
            )
            self.assertNotIn("secondary_operator_action", recent_failure)

    def test_failures_api_exposes_repeated_failure_operator_action_when_alert_is_open(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(
                tmpdir,
                name="Repeated Failure Action Test",
                description="Repeated failure action test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Define project workspace contracts'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    INSERT INTO failure_log (
                        failure_id, project_id, task_id, failure_type, summary, detail_json
                    ) VALUES
                        ('fail_repeat_one', ?, ?, 'session_failed', 'First repeated failure', '{}'),
                        ('fail_repeat_two', ?, ?, 'session_failed', 'Second repeated failure', '{}')
                    """,
                    (project_id, task_id, project_id, task_id),
                )
                connection.execute(
                    """
                    INSERT INTO alerts (
                        alert_id, project_id, severity, title, description, status
                    ) VALUES (
                        'alert_repeated_failure_section',
                        ?,
                        'critical',
                        'Repeated task failures',
                        ?,
                        'open'
                    )
                    """,
                    (
                        project_id,
                        "Task {0} (Define project workspace contracts) has failed 2 times. Latest failure: Second repeated failure".format(
                            task_id
                        ),
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            repeated_task = client.get("/api/failures").json()["repeated_tasks"][0]

            self.assertEqual(
                repeated_task["operator_action"],
                {
                    "action": "resolve_repeated_failures",
                    "label": "Resolve repeated failures",
                    "resource_type": "task",
                    "resource_id": task_id,
                },
            )

    def test_failures_api_omits_repeated_failure_operator_action_without_open_alert(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(
                tmpdir,
                name="Repeated Failure No Action Test",
                description="Repeated failure no action test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Define project workspace contracts'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    INSERT INTO failure_log (
                        failure_id, project_id, task_id, failure_type, summary, detail_json
                    ) VALUES
                        ('fail_repeat_three', ?, ?, 'session_failed', 'First repeated failure', '{}'),
                        ('fail_repeat_four', ?, ?, 'session_failed', 'Second repeated failure', '{}')
                    """,
                    (project_id, task_id, project_id, task_id),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            repeated_task = client.get("/api/failures").json()["repeated_tasks"][0]

            self.assertNotIn("operator_action", repeated_task)

    def test_failed_session_auto_retry_resolves_task_failure_alert(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Auto Retry Alert Resolution Test",
                description="Auto retry alert resolution test",
                project_type="custom",
            )
            self._update_recovery_config(
                tmpdir,
                auto_retry_failed_sessions=True,
                max_failed_session_retries=1,
                failed_session_retry_cooldown_seconds=45,
            )
            connection = connect(project_paths(tmpdir))
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
                    status_message="Starting auto retry alert resolution test",
                )
                end_session(connection, session_id, "failed", "Retryable failed session")
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            alerts_payload = client.get("/api/alerts").json()
            matching_alerts = [
                alert
                for alert in alerts_payload["alerts"]
                if alert["title"] == "Task session failed"
            ]

            self.assertEqual(len(matching_alerts), 1)
            self.assertEqual(matching_alerts[0]["status"], "resolved")
            self.assertNotIn("operator_action", matching_alerts[0])

    def test_quarantine_api_lists_open_entries_for_failed_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Quarantine Queue API Test",
                description="Quarantine queue api test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
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
                    status_message="Starting quarantine queue api test",
                )
                artifact_path = os.path.join(result["paths"].artifacts_dir, "quarantine-queue-note.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("queue me\n")
                produce_artifact(
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
                    "Failure queued for quarantine review",
                    project_paths=result["paths"],
                )
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            quarantine_payload = client.get("/api/quarantine").json()
            queue_entry = quarantine_payload["entries"][0]

            self.assertEqual(quarantine_payload["summary"]["open"], 1)
            self.assertEqual(queue_entry["status"], "open")
            self.assertEqual(queue_entry["artifact_count"], 1)
            self.assertEqual(queue_entry["failure_type"], "session_failed")
            self.assertEqual(queue_entry["quarantined_artifacts"][0]["quarantined_from_path"], artifact_path)

    def test_quarantine_api_persists_backfilled_legacy_queue_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Quarantine Backfill API Test",
                description="Quarantine backfill api test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
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
                    status_message="Starting quarantine backfill api test",
                )
                artifact_path = os.path.join(result["paths"].artifacts_dir, "quarantine-backfill-note.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("backfill me\n")
                produce_artifact(
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
                    "Failure that needs queue backfill persistence",
                    project_paths=result["paths"],
                )
                connection.execute("DELETE FROM quarantine_queue WHERE session_id = ?", (session_id,))
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            first_payload = client.get("/api/quarantine").json()
            backfilled_entry = first_payload["entries"][0]

            connection = connect(project_paths(tmpdir))
            try:
                persisted_row = connection.execute(
                    """
                    SELECT queue_id, status
                    FROM quarantine_queue
                    WHERE session_id = ?
                    """,
                    (session_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(backfilled_entry["queue_id"], persisted_row["queue_id"])
            self.assertEqual(persisted_row["status"], "open")

            restore_response = client.post(
                "/api/quarantine/{0}/actions/restore".format(backfilled_entry["queue_id"]),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(restore_response.status_code, 200)
            self.assertEqual(restore_response.json()["status"], "restored")

    def test_failures_api_exposes_retry_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Failure Retry API Test", description="Failure retry api test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET retry_count = 1,
                        last_retry_at = CURRENT_TIMESTAMP,
                        last_retry_reason = 'session_timed_out',
                        next_retry_at = '2999-01-01 00:00:00',
                        next_retry_reason = 'session_timed_out'
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
                connection.execute(
                    """
                    INSERT INTO failure_log (
                        failure_id, project_id, task_id, session_id, agent_id, failure_type, summary, detail_json
                    )
                    SELECT ?, project_id, ?, session_id, agent_id, 'session_timed_out', 'Retry-visible failure', '{}'
                    FROM sessions
                    WHERE task_id = ?
                    LIMIT 1
                    """,
                    ("fail_retry_visible", task_id, task_id),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            failures_payload = client.get("/api/failures").json()
            recent_failure = failures_payload["recent"][0]

            self.assertEqual(recent_failure["failure_type"], "session_timed_out")
            self.assertEqual(recent_failure["retry_count"], 1)
            self.assertEqual(recent_failure["last_retry_reason"], "session_timed_out")
            self.assertIsNotNone(recent_failure["last_retry_at"])
            self.assertEqual(recent_failure["next_retry_at"], "2999-01-01 00:00:00")
            self.assertEqual(recent_failure["next_retry_reason"], "session_timed_out")

    def test_quarantine_restore_action_restores_quarantined_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Quarantine Restore API Test",
                description="Quarantine restore api test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
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
                    status_message="Starting quarantine restore api test",
                )
                artifact_path = os.path.join(result["paths"].artifacts_dir, "quarantine-restore-note.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("restore queue entry\n")
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
                    "Failure with queue restore coverage",
                    project_paths=result["paths"],
                )
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            queue_entry = client.get("/api/quarantine").json()["entries"][0]
            restore_response = client.post(
                "/api/quarantine/{0}/actions/restore".format(queue_entry["queue_id"]),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(restore_response.status_code, 200)
            self.assertEqual(restore_response.json()["status"], "restored")
            self.assertEqual(restore_response.json()["restored_count"], 1)

            connection = connect(project_paths(tmpdir))
            try:
                artifact = connection.execute(
                    """
                    SELECT path, metadata_json
                    FROM artifacts
                    WHERE artifact_id = ?
                    """,
                    (artifact_id,),
                ).fetchone()
                queue_row = connection.execute(
                    """
                    SELECT status, resolved_at
                    FROM quarantine_queue
                    WHERE queue_id = ?
                    """,
                    (queue_entry["queue_id"],),
                ).fetchone()
            finally:
                connection.close()

            metadata = json.loads(artifact["metadata_json"] or "{}")
            self.assertEqual(artifact["path"], artifact_path)
            self.assertTrue(metadata["restored_from_quarantine"])
            self.assertEqual(queue_row["status"], "restored")
            self.assertIsNotNone(queue_row["resolved_at"])
            self.assertTrue(os.path.exists(artifact_path))

    def test_quarantine_restore_and_requeue_action_restores_files_and_requeues_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Quarantine Restore Requeue API Test",
                description="Quarantine restore requeue api test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
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
                    status_message="Starting quarantine restore requeue api test",
                )
                artifact_path = os.path.join(result["paths"].artifacts_dir, "quarantine-restore-requeue-note.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("restore and requeue queue entry\n")
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
                    "Failure with queue restore and requeue coverage",
                    project_paths=result["paths"],
                )
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            queue_entry = client.get("/api/quarantine").json()["entries"][0]
            restore_response = client.post(
                "/api/quarantine/{0}/actions/restore-and-requeue".format(queue_entry["queue_id"]),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(restore_response.status_code, 200)
            self.assertEqual(restore_response.json()["status"], "restored")
            self.assertEqual(restore_response.json()["restored_count"], 1)
            self.assertEqual(restore_response.json()["task_id"], task_id)
            self.assertEqual(restore_response.json()["task_status"], "planned")
            self.assertEqual(restore_response.json()["task_review_state"], "retry_backoff")

            connection = connect(project_paths(tmpdir))
            try:
                artifact = connection.execute(
                    """
                    SELECT path, metadata_json
                    FROM artifacts
                    WHERE artifact_id = ?
                    """,
                    (artifact_id,),
                ).fetchone()
                task = connection.execute(
                    """
                    SELECT status, review_state, next_retry_at, next_retry_reason
                    FROM tasks
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
                queue_row = connection.execute(
                    """
                    SELECT status, resolved_at
                    FROM quarantine_queue
                    WHERE queue_id = ?
                    """,
                    (queue_entry["queue_id"],),
                ).fetchone()
            finally:
                connection.close()

            metadata = json.loads(artifact["metadata_json"] or "{}")
            self.assertEqual(artifact["path"], artifact_path)
            self.assertTrue(metadata["restored_from_quarantine"])
            self.assertEqual(task["status"], "planned")
            self.assertEqual(task["review_state"], "retry_backoff")
            self.assertIsNotNone(task["next_retry_at"])
            self.assertEqual(task["next_retry_reason"], "recover_and_requeue")
            self.assertEqual(queue_row["status"], "restored")
            self.assertIsNotNone(queue_row["resolved_at"])
            self.assertTrue(os.path.exists(artifact_path))

    def test_quarantine_restore_and_requeue_action_rejects_nonrecoverable_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Quarantine Restore Requeue Guard Test",
                description="Quarantine restore requeue guard test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
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
                    status_message="Starting quarantine restore requeue guard test",
                )
                artifact_path = os.path.join(result["paths"].artifacts_dir, "quarantine-restore-requeue-guard.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("guard queue entry\n")
                produce_artifact(
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
                    "Failure with queue restore and requeue guard coverage",
                    project_paths=result["paths"],
                )
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'ready', review_state = NULL
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            queue_entry = client.get("/api/quarantine").json()["entries"][0]
            restore_response = client.post(
                "/api/quarantine/{0}/actions/restore-and-requeue".format(queue_entry["queue_id"]),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(restore_response.status_code, 400)
            self.assertIn("recover", restore_response.json()["detail"])

    def test_restore_failure_artifacts_action_restores_quarantined_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Failure Restore API Test",
                description="Failure restore api test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
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
                    status_message="Starting failure restore api test",
                )
                artifact_path = os.path.join(result["paths"].artifacts_dir, "failure-restore-note.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("restore me\n")
                artifact_id = produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    artifact_type="note",
                    path=artifact_path,
                )
                connection.execute(
                    """
                    INSERT INTO artifacts (
                        artifact_id, project_id, task_id, session_id, artifact_type, path, metadata_json
                    )
                    SELECT ?, project_id, task_id, session_id, artifact_type, path, metadata_json
                    FROM artifacts
                    WHERE artifact_id = ?
                    """,
                    ("artifact_duplicate_restore", artifact_id),
                )
                end_session(
                    connection,
                    session_id,
                    "failed",
                    "Failure with restorably quarantined artifacts",
                    project_paths=result["paths"],
                )
                failure_id = connection.execute(
                    """
                    SELECT failure_id
                    FROM failure_log
                    WHERE session_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (session_id,),
                ).fetchone()["failure_id"]
                quarantine_path = connection.execute(
                    """
                    SELECT path
                    FROM artifacts
                    WHERE session_id = ?
                    ORDER BY artifact_id ASC
                    LIMIT 1
                    """,
                    (session_id,),
                ).fetchone()["path"]
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            restore_response = client.post(
                "/api/failures/{0}/actions/restore-artifacts".format(failure_id),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(restore_response.status_code, 200)
            self.assertEqual(restore_response.json()["restored_count"], 2)

            connection = connect(project_paths(tmpdir))
            try:
                artifacts = connection.execute(
                    """
                    SELECT artifact_id, path, metadata_json
                    FROM artifacts
                    WHERE session_id = ?
                    ORDER BY artifact_id ASC
                    """,
                    (session_id,),
                ).fetchall()
                restore_activity = connection.execute(
                    """
                    SELECT action
                    FROM activity_log
                    WHERE task_id = ? AND action = 'artifacts_restored'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (task_id,),
                ).fetchone()
                queue_row = connection.execute(
                    """
                    SELECT status, resolved_at
                    FROM quarantine_queue
                    WHERE session_id = ?
                    """,
                    (session_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual([artifact["path"] for artifact in artifacts], [artifact_path, artifact_path])
            for artifact in artifacts:
                metadata = json.loads(artifact["metadata_json"] or "{}")
                self.assertFalse(metadata.get("quarantined"))
                self.assertNotIn("quarantine_reason", metadata)
                self.assertNotIn("quarantined_from_path", metadata)
                self.assertTrue(metadata.get("restored_from_quarantine"))
            self.assertTrue(os.path.exists(artifact_path))
            self.assertFalse(os.path.exists(quarantine_path))
            self.assertEqual(restore_activity["action"], "artifacts_restored")
            self.assertEqual(queue_row["status"], "restored")
            self.assertIsNotNone(queue_row["resolved_at"])

    def test_quarantine_dismiss_action_marks_entry_dismissed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Quarantine Dismiss API Test",
                description="Quarantine dismiss api test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
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
                    status_message="Starting quarantine dismiss api test",
                )
                artifact_path = os.path.join(result["paths"].artifacts_dir, "quarantine-dismiss-note.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("dismiss queue entry\n")
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
                    "Failure with queue dismiss coverage",
                    project_paths=result["paths"],
                )
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            queue_entry = client.get("/api/quarantine").json()["entries"][0]
            dismiss_response = client.post(
                "/api/quarantine/{0}/actions/dismiss".format(queue_entry["queue_id"]),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(dismiss_response.status_code, 200)
            self.assertEqual(dismiss_response.json()["status"], "dismissed")

            connection = connect(project_paths(tmpdir))
            try:
                artifact = connection.execute(
                    """
                    SELECT path, metadata_json
                    FROM artifacts
                    WHERE artifact_id = ?
                    """,
                    (artifact_id,),
                ).fetchone()
                queue_row = connection.execute(
                    """
                    SELECT status, resolution_note, resolved_at
                    FROM quarantine_queue
                    WHERE queue_id = ?
                    """,
                    (queue_entry["queue_id"],),
                ).fetchone()
            finally:
                connection.close()

            metadata = json.loads(artifact["metadata_json"] or "{}")
            self.assertTrue(metadata["quarantined"])
            self.assertEqual(queue_row["status"], "dismissed")
            self.assertEqual(queue_row["resolution_note"], "quarantine_dismissed")
            self.assertIsNotNone(queue_row["resolved_at"])
            self.assertTrue(os.path.exists(artifact["path"]))
            self.assertFalse(os.path.exists(artifact_path))

    def test_quarantine_reopen_action_returns_dismissed_entry_to_open(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Quarantine Reopen API Test",
                description="Quarantine reopen api test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
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
                    status_message="Starting quarantine reopen api test",
                )
                artifact_path = os.path.join(result["paths"].artifacts_dir, "quarantine-reopen-note.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("reopen queue entry\n")
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
                    "Failure with queue reopen coverage",
                    project_paths=result["paths"],
                )
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            queue_entry = client.get("/api/quarantine").json()["entries"][0]
            dismiss_response = client.post(
                "/api/quarantine/{0}/actions/dismiss".format(queue_entry["queue_id"]),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(dismiss_response.status_code, 200)

            reopen_response = client.post(
                "/api/quarantine/{0}/actions/reopen".format(queue_entry["queue_id"]),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(reopen_response.status_code, 200)
            self.assertEqual(reopen_response.json()["status"], "open")

            queue_payload = client.get("/api/quarantine").json()
            reopened_entry = [entry for entry in queue_payload["entries"] if entry["queue_id"] == queue_entry["queue_id"]][0]
            self.assertEqual(reopened_entry["status"], "open")
            self.assertEqual(queue_payload["summary"]["open"], 1)
            self.assertEqual(queue_payload["summary"]["dismissed"], 0)

            connection = connect(project_paths(tmpdir))
            try:
                artifact = connection.execute(
                    """
                    SELECT path, metadata_json
                    FROM artifacts
                    WHERE artifact_id = ?
                    """,
                    (artifact_id,),
                ).fetchone()
                queue_row = connection.execute(
                    """
                    SELECT status, resolution_note, resolved_at
                    FROM quarantine_queue
                    WHERE queue_id = ?
                    """,
                    (queue_entry["queue_id"],),
                ).fetchone()
                reopen_activity = connection.execute(
                    """
                    SELECT action
                    FROM activity_log
                    WHERE task_id = ? AND action = 'quarantine_reopened'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (task_id,),
                ).fetchone()
            finally:
                connection.close()

            metadata = json.loads(artifact["metadata_json"] or "{}")
            self.assertTrue(metadata["quarantined"])
            self.assertEqual(queue_row["status"], "open")
            self.assertEqual(queue_row["resolution_note"], "")
            self.assertIsNone(queue_row["resolved_at"])
            self.assertEqual(reopen_activity["action"], "quarantine_reopened")
            self.assertTrue(os.path.exists(artifact["path"]))
            self.assertFalse(os.path.exists(artifact_path))

    def test_quarantine_reopen_action_rejects_nondismissed_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Quarantine Reopen Guard Test",
                description="Quarantine reopen guard test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
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
                    status_message="Starting quarantine reopen guard test",
                )
                artifact_path = os.path.join(result["paths"].artifacts_dir, "quarantine-reopen-guard-note.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("open queue entry\n")
                produce_artifact(
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
                    "Failure with queue reopen guard coverage",
                    project_paths=result["paths"],
                )
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            queue_entry = client.get("/api/quarantine").json()["entries"][0]
            reopen_response = client.post(
                "/api/quarantine/{0}/actions/reopen".format(queue_entry["queue_id"]),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(reopen_response.status_code, 400)
            self.assertIn("dismissed", reopen_response.json()["detail"])

    def test_restore_failure_artifacts_action_rejects_existing_destination(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Failure Restore Conflict Test",
                description="Failure restore conflict test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
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
                    status_message="Starting failure restore conflict test",
                )
                artifact_path = os.path.join(result["paths"].artifacts_dir, "failure-restore-conflict.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("quarantine me\n")
                produce_artifact(
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
                    "Failure with restore conflict",
                    project_paths=result["paths"],
                )
                failure_id = connection.execute(
                    """
                    SELECT failure_id
                    FROM failure_log
                    WHERE session_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (session_id,),
                ).fetchone()["failure_id"]
                quarantined_artifact = connection.execute(
                    """
                    SELECT path, metadata_json
                    FROM artifacts
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (session_id,),
                ).fetchone()
            finally:
                connection.close()

            with open(artifact_path, "w", encoding="utf-8") as handle:
                handle.write("existing destination\n")

            client = TestClient(create_app(tmpdir))
            restore_response = client.post(
                "/api/failures/{0}/actions/restore-artifacts".format(failure_id),
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(restore_response.status_code, 400)
            self.assertIn("Restore destination already exists", restore_response.json()["detail"])

            connection = connect(project_paths(tmpdir))
            try:
                artifact_row = connection.execute(
                    """
                    SELECT path, metadata_json
                    FROM artifacts
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (session_id,),
                ).fetchone()
            finally:
                connection.close()

            metadata = json.loads(artifact_row["metadata_json"] or "{}")
            self.assertEqual(artifact_row["path"], quarantined_artifact["path"])
            self.assertTrue(metadata["quarantined"])
            self.assertTrue(os.path.exists(quarantined_artifact["path"]))
            with open(artifact_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "existing destination\n")

    def test_restore_failure_artifacts_rolls_back_partial_moves_when_restore_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Failure Restore Rollback Test",
                description="Failure restore rollback test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
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
                    status_message="Starting failure restore rollback test",
                )
                artifact_path_one = os.path.join(result["paths"].artifacts_dir, "failure-restore-rollback-one.txt")
                artifact_path_two = os.path.join(result["paths"].artifacts_dir, "failure-restore-rollback-two.txt")
                with open(artifact_path_one, "w", encoding="utf-8") as handle:
                    handle.write("rollback one\n")
                with open(artifact_path_two, "w", encoding="utf-8") as handle:
                    handle.write("rollback two\n")
                produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    artifact_type="note",
                    path=artifact_path_one,
                )
                produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    artifact_type="note",
                    path=artifact_path_two,
                )
                end_session(
                    connection,
                    session_id,
                    "failed",
                    "Failure with rollback restore coverage",
                    project_paths=result["paths"],
                )
                failure_id = connection.execute(
                    """
                    SELECT failure_id
                    FROM failure_log
                    WHERE session_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (session_id,),
                ).fetchone()["failure_id"]
                quarantined_before = connection.execute(
                    """
                    SELECT artifact_id, path, metadata_json
                    FROM artifacts
                    WHERE session_id = ?
                    ORDER BY artifact_id ASC
                    """,
                    (session_id,),
                ).fetchall()
            finally:
                connection.close()

            move_calls = {"count": 0}
            real_move = shutil.move

            def flaky_move(source_path, destination_path, *args, **kwargs):
                move_calls["count"] += 1
                if move_calls["count"] == 2:
                    raise OSError("simulated restore failure")
                return real_move(source_path, destination_path, *args, **kwargs)

            client = TestClient(create_app(tmpdir), raise_server_exceptions=False)
            with patch("maas.services.failure_memory.shutil.move", side_effect=flaky_move):
                restore_response = client.post(
                    "/api/failures/{0}/actions/restore-artifacts".format(failure_id),
                    json={"actor_id": "agent_allocator"},
                )

            self.assertEqual(restore_response.status_code, 500)

            connection = connect(project_paths(tmpdir))
            try:
                quarantined_after = connection.execute(
                    """
                    SELECT artifact_id, path, metadata_json
                    FROM artifacts
                    WHERE session_id = ?
                    ORDER BY artifact_id ASC
                    """,
                    (session_id,),
                ).fetchall()
            finally:
                connection.close()

            self.assertEqual(
                [artifact["path"] for artifact in quarantined_after],
                [artifact["path"] for artifact in quarantined_before],
            )
            for artifact in quarantined_after:
                metadata = json.loads(artifact["metadata_json"] or "{}")
                self.assertTrue(metadata["quarantined"])
                self.assertTrue(os.path.exists(artifact["path"]))
            self.assertFalse(os.path.exists(artifact_path_one))
            self.assertFalse(os.path.exists(artifact_path_two))

    def test_live_snapshot_includes_open_escalation_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Live Escalation Test", description="Live escalation test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE status = 'ready' LIMIT 1"
                ).fetchone()["task_id"]
                request_escalation(
                    connection,
                    project_id=project_id,
                    actor_id="agent_builder",
                    action_type="halt_task",
                    resource_type="task",
                    resource_id=task_id,
                    reason="Need operator approval",
                )
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            live_payload = client.get("/api/live").json()

            self.assertEqual(live_payload["counts"]["escalations_open"], 1)
            self.assertIsNotNone(live_payload["revision"]["latest_escalation"])

    def test_live_snapshot_does_not_load_full_escalation_queue_for_open_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Live Query Test", description="Live query test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                with patch("maas.services.live.count_open_escalations", return_value=7), patch(
                    "maas.services.live.fetch_escalations",
                    side_effect=AssertionError("build_live_snapshot should not fetch the full escalation queue"),
                    create=True,
                ):
                    snapshot = build_live_snapshot(connection)
            finally:
                connection.close()

            self.assertEqual(snapshot["counts"]["escalations_open"], 7)

    def test_alert_action_requires_board_permission(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Alert Permission Test", description="Alert permission test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            alerts_payload = client.get("/api/alerts").json()
            alert_id = alerts_payload["alerts"][0]["alert_id"]

            denied_response = client.post(
                "/api/alerts/{0}/actions/acknowledge".format(alert_id),
                json={"actor_id": "agent_builder"},
            )
            self.assertEqual(denied_response.status_code, 403)

            connection = connect(project_paths(tmpdir))
            try:
                audit_row = connection.execute(
                    """
                    SELECT action_type, detail_json
                    FROM audit_trail
                    WHERE actor_id = 'agent_builder'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(audit_row["action_type"], "permission_denied")
            self.assertIn("update_alert_status", audit_row["detail_json"])

    def test_alerts_include_operator_actions_for_recoverable_failure_cases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(
                tmpdir,
                name="Alert Operator Actions Test",
                description="Alert operator actions test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_failure_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()["task_id"]
                repeated_failure_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Define project workspace contracts'"
                ).fetchone()["task_id"]
                stale_agent_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'blocked', review_state = 'session_failed'
                    WHERE task_id IN (?, ?)
                    """,
                    (task_failure_id, repeated_failure_task_id),
                )
                connection.execute(
                    """
                    UPDATE agents
                    SET status = 'error', current_task_id = NULL
                    WHERE agent_id = 'agent_reviewer'
                    """
                )
                connection.execute(
                    """
                    INSERT INTO alerts (
                        alert_id, project_id, severity, title, description, status
                    ) VALUES
                        ('alert_task_failure', ?, 'warning', 'Task session failed', ?, 'open'),
                        ('alert_repeated_failure', ?, 'critical', 'Repeated task failures', ?, 'open'),
                        ('alert_stale_agent', ?, 'warning', 'Stale agent heartbeat', ?, 'open')
                    """,
                    (
                        project_id,
                        "Task {0} failed in session sess_failure_123. Session crashed".format(task_failure_id),
                        project_id,
                        "Task {0} (Retry-heavy task) has failed 3 times. Latest failure: Timeout".format(
                            repeated_failure_task_id
                        ),
                        project_id,
                        "Agent agent_reviewer stopped heartbeating for task {0}.".format(stale_agent_task_id),
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            alerts_payload = client.get("/api/alerts").json()
            alerts_by_id = {alert["alert_id"]: alert for alert in alerts_payload["alerts"]}
            provider_pending = [
                alert for alert in alerts_payload["alerts"] if alert["title"] == "Broader provider integrations pending"
            ][0]

            self.assertNotIn("operator_action", provider_pending)
            self.assertEqual(
                alerts_by_id["alert_task_failure"]["operator_action"],
                {
                    "action": "recover_task",
                    "label": "Recover task",
                    "resource_type": "task",
                    "resource_id": task_failure_id,
                },
            )
            self.assertEqual(
                alerts_by_id["alert_repeated_failure"]["operator_action"],
                {
                    "action": "resolve_repeated_failures",
                    "label": "Resolve repeated failures",
                    "resource_type": "task",
                    "resource_id": repeated_failure_task_id,
                },
            )
            self.assertEqual(
                alerts_by_id["alert_stale_agent"]["operator_action"],
                {
                    "action": "recover_agent",
                    "label": "Recover agent",
                    "resource_type": "agent",
                    "resource_id": "agent_reviewer",
                    "related_task_id": stale_agent_task_id,
                },
            )


if __name__ == "__main__":
    unittest.main()
