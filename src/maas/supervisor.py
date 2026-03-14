"""Supervisor orchestration pass for stale sessions, ready refresh, and allocation."""

from datetime import datetime, timedelta
import json

from maas.constants import HEARTBEAT_STALE_SECONDS
from maas.ids import generate_id
from maas.services.scheduler import allocate_ready_tasks, refresh_ready_tasks


def _handle_stale_sessions(connection, stale_after_seconds):
    stale_before = datetime.utcnow() - timedelta(seconds=stale_after_seconds)
    stale_rows = connection.execute(
        """
        SELECT session_id, project_id, agent_id, task_id
        FROM sessions
        WHERE status = 'active'
          AND last_heartbeat_at IS NOT NULL
          AND last_heartbeat_at < ?
        """,
        (stale_before.strftime("%Y-%m-%d %H:%M:%S"),),
    ).fetchall()

    findings = []
    for row in stale_rows:
        connection.execute(
            """
            UPDATE sessions
            SET status = 'timed_out', updated_at = CURRENT_TIMESTAMP
            WHERE session_id = ?
            """,
            (row["session_id"],),
        )
        connection.execute(
            """
            UPDATE agents
            SET status = 'error', current_task_id = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE agent_id = ?
            """,
            (row["agent_id"],),
        )
        connection.execute(
            """
            UPDATE tasks
            SET status = 'blocked', review_state = 'stale_session', updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ? AND status = 'in_progress'
            """,
            (row["task_id"],),
        )
        connection.execute(
            """
            INSERT INTO alerts (
                alert_id, project_id, severity, title, description, status
            ) VALUES (?, ?, 'warning', 'Stale agent heartbeat', ?, 'open')
            """,
            (
                generate_id("alert"),
                row["project_id"],
                "Agent {0} stopped heartbeating for task {1}.".format(row["agent_id"], row["task_id"]),
            ),
        )
        connection.execute(
            """
            INSERT INTO activity_log (
                activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
            ) VALUES (?, ?, ?, ?, 'session_timed_out', 'supervisor', ?, ?, 'warning')
            """,
            (
                generate_id("act"),
                row["project_id"],
                row["agent_id"],
                row["task_id"],
                "Supervisor marked session {0} as timed out.".format(row["session_id"]),
                json.dumps({"session_id": row["session_id"]}),
            ),
        )
        findings.append({"session_id": row["session_id"], "task_id": row["task_id"]})

    return findings


def run_supervisor_once(connection, stale_after_seconds=HEARTBEAT_STALE_SECONDS, allocate_limit=None):
    ready_changes = refresh_ready_tasks(connection)
    allocation_result = allocate_ready_tasks(connection, actor_id="system_supervisor", limit=allocate_limit)
    stale_sessions = _handle_stale_sessions(connection, stale_after_seconds)
    connection.commit()
    return {
        "ready_changes": ready_changes,
        "allocations": allocation_result["allocations"],
        "assigned_count": allocation_result["assigned_count"],
        "stale_sessions": stale_sessions,
    }
