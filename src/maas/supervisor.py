"""Supervisor orchestration pass for stale sessions, ready refresh, and allocation."""

from datetime import datetime, timedelta
import json

from maas.constants import HEARTBEAT_STALE_SECONDS
from maas.ids import generate_id
from maas.services.recovery_policy import (
    fetch_project_recovery_policy,
    retry_deadline,
    task_timed_out_retry_limit,
    timed_out_retry_cooldown_seconds,
)
from maas.services.failure_memory import maybe_raise_repeated_failure_alert, quarantine_session_artifacts, record_failure
from maas.services.scheduler import allocate_ready_tasks, refresh_ready_tasks
from maas.services.security import revoke_task_capabilities


def _audit_auto_retry(connection, project_id, task_id, actor_id, detail):
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, 'auto_retry_task', 'task', ?, ?)
        """,
        (
            generate_id("audit"),
            project_id,
            actor_id,
            task_id,
            json.dumps(detail),
        ),
    )


def _activity_auto_retry(connection, project_id, agent_id, task_id, description, details):
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
        ) VALUES (?, ?, ?, ?, 'task_auto_retried', 'resilience', ?, ?, 'warning')
        """,
        (
            generate_id("act"),
            project_id,
            agent_id,
            task_id,
            description,
            json.dumps(details),
        ),
    )


def _maybe_auto_retry_timed_out_task(connection, project_id, task_id, actor_id):
    task = connection.execute(
        """
        SELECT task_id, project_id, assigned_agent_id, status, retry_count, auto_retry_limit
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if task is None:
        return None
    if task["status"] != "in_progress":
        return None

    recovery_policy = fetch_project_recovery_policy(connection, project_id)
    if not recovery_policy["auto_retry_timeout_sessions"]:
        return None

    retry_limit = task_timed_out_retry_limit(task, recovery_policy)
    if retry_limit <= 0 or task["retry_count"] >= retry_limit:
        return None

    if task["assigned_agent_id"]:
        revoke_task_capabilities(
            connection,
            project_id,
            task_id,
            agent_id=task["assigned_agent_id"],
            reason="task_auto_retried",
            revoked_by=actor_id,
        )

    next_retry_count = task["retry_count"] + 1
    cooldown_seconds = timed_out_retry_cooldown_seconds(recovery_policy, next_retry_count)
    next_retry_at = retry_deadline(cooldown_seconds)
    connection.execute(
        """
        UPDATE tasks
        SET status = 'planned',
            assigned_agent_id = NULL,
            progress_pct = 0,
            review_state = NULL,
            last_heartbeat_at = NULL,
            retry_count = ?,
            last_retry_at = CURRENT_TIMESTAMP,
            last_retry_reason = 'session_timed_out',
            next_retry_at = ?,
            next_retry_reason = CASE WHEN ? IS NULL THEN NULL ELSE 'session_timed_out' END,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ?
        """,
        (next_retry_count, next_retry_at, next_retry_at, task_id),
    )
    _audit_auto_retry(
        connection,
        project_id,
        task_id,
        actor_id,
        {
            "failure_type": "session_timed_out",
            "retry_count": next_retry_count,
            "retry_limit": retry_limit,
            "cooldown_seconds": cooldown_seconds,
            "next_retry_at": next_retry_at,
        },
    )
    _activity_auto_retry(
        connection,
        project_id,
        task["assigned_agent_id"],
        task_id,
        "Task returned to the planning queue for automatic retry after a timed-out session.",
        {
            "failure_type": "session_timed_out",
            "retry_count": next_retry_count,
            "retry_limit": retry_limit,
            "cooldown_seconds": cooldown_seconds,
            "next_retry_at": next_retry_at,
        },
    )
    return {
        "task_id": task_id,
        "retry_count": next_retry_count,
        "retry_limit": retry_limit,
        "next_retry_at": next_retry_at,
    }


def _handle_stale_sessions(connection, stale_after_seconds, project_paths=None):
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
        has_other_agent_session = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM sessions
            WHERE agent_id = ?
              AND status = 'active'
              AND session_id != ?
            """,
            (row["agent_id"], row["session_id"]),
        ).fetchone()["count"] > 0
        has_other_task_session = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM sessions
            WHERE task_id = ?
              AND status = 'active'
              AND session_id != ?
            """,
            (row["task_id"], row["session_id"]),
        ).fetchone()["count"] > 0

        if not has_other_agent_session:
            connection.execute(
                """
                UPDATE agents
                SET status = 'error', current_task_id = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE agent_id = ? AND current_task_id = ?
                """,
                (row["agent_id"], row["task_id"]),
            )
        auto_retry = None
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
        failure_id = record_failure(
            connection,
            row["project_id"],
            "session_timed_out",
            "Session {0} timed out waiting for heartbeat.".format(row["session_id"]),
            task_id=row["task_id"],
            session_id=row["session_id"],
            agent_id=row["agent_id"],
            details={"reason": "stale_heartbeat"},
        )
        repeated_alert = maybe_raise_repeated_failure_alert(
            connection,
            row["project_id"],
            row["task_id"],
            "Session {0} timed out waiting for heartbeat.".format(row["session_id"]),
        )
        quarantined_artifacts = quarantine_session_artifacts(
            connection,
            project_paths,
            row["session_id"],
            reason="session_timed_out",
            project_id=row["project_id"],
            task_id=row["task_id"],
            failure_id=failure_id,
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
        if quarantined_artifacts:
            connection.execute(
                """
                INSERT INTO activity_log (
                    activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
                ) VALUES (?, ?, ?, ?, 'artifacts_quarantined', 'resilience', ?, ?, 'warning')
                """,
                (
                    generate_id("act"),
                    row["project_id"],
                    row["agent_id"],
                    row["task_id"],
                    "Quarantined session artifacts after stale-session timeout.",
                    json.dumps({"session_id": row["session_id"], "artifacts": quarantined_artifacts}),
                ),
            )
        if not has_other_task_session:
            auto_retry = _maybe_auto_retry_timed_out_task(
                connection,
                row["project_id"],
                row["task_id"],
                actor_id="system_supervisor",
            )
            if auto_retry is None:
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'blocked', review_state = 'stale_session', updated_at = CURRENT_TIMESTAMP
                    WHERE task_id = ? AND status = 'in_progress'
                    """,
                    (row["task_id"],),
                )
        findings.append(
            {
                "session_id": row["session_id"],
                "task_id": row["task_id"],
                "repeated_failure_alert": repeated_alert,
                "quarantined_artifacts": quarantined_artifacts,
                "auto_retried": auto_retry is not None,
                "retry_count": None if auto_retry is None else auto_retry["retry_count"],
                "next_retry_at": None if auto_retry is None else auto_retry["next_retry_at"],
            }
        )

    return findings


def run_supervisor_once(connection, stale_after_seconds=HEARTBEAT_STALE_SECONDS, allocate_limit=None, project_paths=None):
    ready_changes = refresh_ready_tasks(connection)
    allocation_result = allocate_ready_tasks(connection, actor_id="system_supervisor", limit=allocate_limit)
    stale_sessions = _handle_stale_sessions(connection, stale_after_seconds, project_paths=project_paths)
    if any(item.get("auto_retried") for item in stale_sessions):
        ready_changes.extend(refresh_ready_tasks(connection))
        remaining_limit = None
        if allocate_limit is not None:
            remaining_limit = max(allocate_limit - allocation_result["assigned_count"], 0)
        retry_allocations = allocate_ready_tasks(connection, actor_id="system_supervisor", limit=remaining_limit)
        allocation_result = {
            "allocations": allocation_result["allocations"] + retry_allocations["allocations"],
            "assigned_count": allocation_result["assigned_count"] + retry_allocations["assigned_count"],
        }
    connection.commit()
    return {
        "ready_changes": ready_changes,
        "allocations": allocation_result["allocations"],
        "assigned_count": allocation_result["assigned_count"],
        "stale_sessions": stale_sessions,
    }
