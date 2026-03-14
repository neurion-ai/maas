"""Simple supervisor loop for stale sessions and task alerts."""

from datetime import datetime, timedelta

from maas.constants import HEARTBEAT_STALE_SECONDS
from maas.ids import generate_id


def run_supervisor_once(connection, stale_after_seconds=HEARTBEAT_STALE_SECONDS):
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
        findings.append({"session_id": row["session_id"], "task_id": row["task_id"]})

    connection.commit()
    return findings

