import tempfile
import unittest
from unittest import mock

from maas.db import connect, project_paths
from maas.services.bootstrap import bootstrap_project
from maas.services.codex_mvp import fetch_system_diagnostics
from maas.services.projects import create_project
from maas.services.reconciliation import reconcile_project_truth
from maas.services.theater import fetch_theater


class ReconciliationApiTest(unittest.TestCase):
    def test_reconcile_project_truth_repairs_stale_task_and_missing_agent_assignments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Reconcile Service Test", description="reconcile service", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                tasks = connection.execute(
                    """
                    SELECT task_id, project_id, assigned_agent_id
                    FROM tasks
                    ORDER BY created_at ASC
                    LIMIT 3
                    """
                ).fetchall()
                stale_task = tasks[0]
                missing_agent_task = tasks[1]
                held_task = tasks[2]
                agent_id = stale_task["assigned_agent_id"] or connection.execute(
                    "SELECT agent_id FROM agents ORDER BY created_at ASC LIMIT 1"
                ).fetchone()["agent_id"]
                missing_agent_id = connection.execute(
                    """
                    SELECT agent_id
                    FROM agents
                    WHERE project_id = ?
                      AND agent_id != ?
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (stale_task["project_id"], agent_id),
                ).fetchone()["agent_id"]
                other_project_id = create_project(
                    connection,
                    paths,
                    "agent_allocator",
                    "Reconcile Secondary",
                    "secondary",
                    project_type="custom",
                    mode="greenfield",
                    create_source_root=True,
                )["project"]["project_id"]

                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'in_progress',
                        assigned_agent_id = ?
                    WHERE task_id = ?
                    """,
                    (agent_id, stale_task["task_id"]),
                )
                connection.execute(
                    """
                    UPDATE agents
                    SET status = 'running',
                        current_task_id = ?
                    WHERE agent_id = ?
                    """,
                    (stale_task["task_id"], agent_id),
                )
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'in_progress',
                        assigned_agent_id = ?
                    WHERE task_id = ?
                    """,
                    (missing_agent_id, missing_agent_task["task_id"]),
                )
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'blocked',
                        review_state = 'changes_requested',
                        assigned_agent_id = ?
                    WHERE task_id = ?
                    """,
                    (missing_agent_id, held_task["task_id"]),
                )
                connection.execute(
                    """
                    UPDATE agents
                    SET project_id = ?
                    WHERE agent_id = ?
                    """,
                    (other_project_id, missing_agent_id),
                )
                connection.commit()

                payload = reconcile_project_truth(
                    connection,
                    paths,
                    project_id=stale_task["project_id"],
                )

                stale_task_row = connection.execute(
                    "SELECT status, assigned_agent_id FROM tasks WHERE task_id = ?",
                    (stale_task["task_id"],),
                ).fetchone()
                missing_agent_task_row = connection.execute(
                    "SELECT status, assigned_agent_id FROM tasks WHERE task_id = ?",
                    (missing_agent_task["task_id"],),
                ).fetchone()
                held_task_row = connection.execute(
                    "SELECT status, review_state, assigned_agent_id FROM tasks WHERE task_id = ?",
                    (held_task["task_id"],),
                ).fetchone()
                agent_row = connection.execute(
                    "SELECT status, current_task_id FROM agents WHERE agent_id = ?",
                    (agent_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(payload["summary"]["repaired_count"], 4)
            self.assertIsNotNone(payload["latest_reconciled_at"])
            self.assertEqual(stale_task_row["status"], "assigned")
            self.assertEqual(stale_task_row["assigned_agent_id"], agent_id)
            self.assertEqual(missing_agent_task_row["status"], "ready")
            self.assertIsNone(missing_agent_task_row["assigned_agent_id"])
            self.assertEqual(held_task_row["status"], "blocked")
            self.assertEqual(held_task_row["review_state"], "changes_requested")
            self.assertIsNone(held_task_row["assigned_agent_id"])
            self.assertEqual(agent_row["status"], "idle")
            self.assertIsNone(agent_row["current_task_id"])

    def test_system_diagnostics_and_theater_surface_truth_warnings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Truth Warning Test", description="truth warning", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task = connection.execute(
                    """
                    SELECT task_id, project_id, assigned_agent_id
                    FROM tasks
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                agent_id = task["assigned_agent_id"] or connection.execute(
                    "SELECT agent_id FROM agents ORDER BY created_at ASC LIMIT 1"
                ).fetchone()["agent_id"]
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
                    UPDATE agents
                    SET status = 'running',
                        current_task_id = ?
                    WHERE agent_id = ?
                    """,
                    (task["task_id"], agent_id),
                )
                connection.commit()

                diagnostics = fetch_system_diagnostics(connection, task["project_id"], project_paths=paths)
                theater = fetch_theater(connection, paths, project_id=task["project_id"])
            finally:
                connection.close()

            self.assertEqual(diagnostics["truth"]["summary"]["repairable_count"], 2)
            self.assertEqual(diagnostics["summary"]["truth_warnings"], 2)
            self.assertEqual(theater["summary"]["truth_warnings"], 2)
            self.assertIsNone(theater["summary"]["reconciled_at"])

    def test_reconcile_project_truth_clears_diagnostics_drift_after_repair(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Reconcile Action Test", description="reconcile action", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task = connection.execute(
                    """
                    SELECT task_id, project_id, assigned_agent_id
                    FROM tasks
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                agent_id = task["assigned_agent_id"] or connection.execute(
                    "SELECT agent_id FROM agents ORDER BY created_at ASC LIMIT 1"
                ).fetchone()["agent_id"]
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
                    UPDATE agents
                    SET status = 'running',
                        current_task_id = ?
                    WHERE agent_id = ?
                    """,
                    (task["task_id"], agent_id),
                )
                connection.commit()

                payload = reconcile_project_truth(
                    connection,
                    paths,
                    project_id=task["project_id"],
                )
                diagnostics = fetch_system_diagnostics(connection, task["project_id"], project_paths=paths)
            finally:
                connection.close()

            self.assertEqual(payload["summary"]["repaired_count"], 2)
            self.assertIsNotNone(diagnostics["truth"]["latest_reconciled_at"])
            self.assertEqual(diagnostics["summary"]["truth_warnings"], 0)

    def test_reconcile_project_truth_reports_project_board_sync(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Board Sync Test", description="board sync", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                with mock.patch(
                    "maas.services.reconciliation.maybe_sync_github_project_truth",
                    return_value={
                        "enabled": True,
                        "skipped": False,
                        "updated_count": 2,
                        "updates": [
                            {"issue_number": 127, "field_name": "PR", "from": "Open", "to": "Merged"},
                            {"issue_number": 127, "field_name": "Code Review", "from": "Pending", "to": "Passed"},
                        ],
                        "warnings": [],
                        "synced_at": "2026-04-04T00:00:00Z",
                    },
                ):
                    payload = reconcile_project_truth(connection, paths, project_id=project_id)
            finally:
                connection.close()

            self.assertEqual(payload["summary"]["project_board_sync_count"], 2)
            self.assertEqual(payload["project_board_sync"]["updated_count"], 2)

    def test_reconcile_project_truth_does_not_revive_operator_paused_task_from_active_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Paused Session Test", description="paused session", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task = connection.execute(
                    """
                    SELECT task_id, project_id, assigned_agent_id
                    FROM tasks
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                agent_id = task["assigned_agent_id"] or connection.execute(
                    "SELECT agent_id FROM agents ORDER BY created_at ASC LIMIT 1"
                ).fetchone()["agent_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'blocked',
                        review_state = 'paused_by_operator',
                        assigned_agent_id = ?
                    WHERE task_id = ?
                    """,
                    (agent_id, task["task_id"]),
                )
                connection.execute(
                    """
                    UPDATE agents
                    SET status = 'paused',
                        current_task_id = ?
                    WHERE agent_id = ?
                    """,
                    (task["task_id"], agent_id),
                )
                connection.execute(
                    """
                    INSERT INTO sessions (
                        session_id, project_id, agent_id, task_id, status, provider_type, progress_pct,
                        status_message, last_heartbeat_at, started_at, ended_at, updated_at
                    ) VALUES (
                        'sess_paused_truth', ?, ?, ?, 'active', 'openai_codex', 42,
                        'Paused by operator', CURRENT_TIMESTAMP, DATETIME('now', '-5 minutes'), NULL, CURRENT_TIMESTAMP
                    )
                    """,
                    (task["project_id"], agent_id, task["task_id"]),
                )
                connection.commit()

                payload = reconcile_project_truth(connection, paths, project_id=task["project_id"])
                task_row = connection.execute(
                    "SELECT status, review_state, assigned_agent_id FROM tasks WHERE task_id = ?",
                    (task["task_id"],),
                ).fetchone()
                agent_row = connection.execute(
                    "SELECT status, current_task_id FROM agents WHERE agent_id = ?",
                    (agent_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(payload["summary"]["repaired_count"], 0)
            warning_codes = {item["code"] for item in payload["warnings"]}
            self.assertIn("active_session_conflicts_with_task_state", warning_codes)
            self.assertEqual(task_row["status"], "blocked")
            self.assertEqual(task_row["review_state"], "paused_by_operator")
            self.assertEqual(task_row["assigned_agent_id"], agent_id)
            self.assertEqual(agent_row["status"], "paused")
            self.assertEqual(agent_row["current_task_id"], task["task_id"])

    def test_reconcile_project_truth_keeps_paused_agent_and_duplicate_sessions_unmodified(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Duplicate Session Test", description="duplicate sessions", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                tasks = connection.execute(
                    """
                    SELECT task_id, project_id, assigned_agent_id
                    FROM tasks
                    ORDER BY created_at ASC
                    LIMIT 2
                    """
                ).fetchall()
                paused_task = tasks[0]
                duplicate_task = tasks[1]
                paused_agent_id = paused_task["assigned_agent_id"] or connection.execute(
                    "SELECT agent_id FROM agents ORDER BY created_at ASC LIMIT 1"
                ).fetchone()["agent_id"]
                duplicate_agent_id = connection.execute(
                    """
                    SELECT agent_id
                    FROM agents
                    WHERE project_id = ?
                      AND agent_id != ?
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (paused_task["project_id"], paused_agent_id),
                ).fetchone()["agent_id"]

                connection.execute(
                    """
                    UPDATE agents
                    SET status = 'paused',
                        current_task_id = ?
                    WHERE agent_id = ?
                    """,
                    (paused_task["task_id"], paused_agent_id),
                )
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'blocked',
                        review_state = 'paused_by_operator',
                        assigned_agent_id = ?
                    WHERE task_id = ?
                    """,
                    (paused_agent_id, paused_task["task_id"]),
                )
                connection.execute(
                    """
                    UPDATE agents
                    SET status = 'running',
                        current_task_id = NULL
                    WHERE agent_id = ?
                    """,
                    (duplicate_agent_id,),
                )
                connection.execute(
                    """
                    INSERT INTO sessions (
                        session_id, project_id, agent_id, task_id, status, provider_type, progress_pct,
                        status_message, last_heartbeat_at, started_at, ended_at, updated_at
                    ) VALUES
                        ('sess_duplicate_one', ?, ?, ?, 'active', 'openai_codex', 20,
                         'duplicate one', CURRENT_TIMESTAMP, DATETIME('now', '-5 minutes'), NULL, CURRENT_TIMESTAMP),
                        ('sess_duplicate_two', ?, ?, ?, 'active', 'openai_codex', 25,
                         'duplicate two', CURRENT_TIMESTAMP, DATETIME('now', '-4 minutes'), NULL, CURRENT_TIMESTAMP)
                    """,
                    (
                        paused_task["project_id"],
                        duplicate_agent_id,
                        duplicate_task["task_id"],
                        paused_task["project_id"],
                        duplicate_agent_id,
                        duplicate_task["task_id"],
                    ),
                )
                connection.commit()

                payload = reconcile_project_truth(connection, paths, project_id=paused_task["project_id"])
                paused_agent_row = connection.execute(
                    "SELECT status, current_task_id FROM agents WHERE agent_id = ?",
                    (paused_agent_id,),
                ).fetchone()
                duplicate_agent_row = connection.execute(
                    "SELECT status, current_task_id FROM agents WHERE agent_id = ?",
                    (duplicate_agent_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(payload["summary"]["repaired_count"], 0)
            warning_codes = {item["code"] for item in payload["warnings"]}
            self.assertIn("duplicate_active_task_sessions", warning_codes)
            self.assertIn("duplicate_active_agent_sessions", warning_codes)
            self.assertEqual(paused_agent_row["status"], "paused")
            self.assertEqual(paused_agent_row["current_task_id"], paused_task["task_id"])
            self.assertEqual(duplicate_agent_row["status"], "running")
            self.assertIsNone(duplicate_agent_row["current_task_id"])


if __name__ == "__main__":
    unittest.main()
