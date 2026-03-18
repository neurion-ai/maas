"""Supervisor orchestration pass for stale sessions, ready refresh, and allocation."""

from datetime import datetime, timedelta
import json

from maas.constants import HEARTBEAT_STALE_SECONDS
from maas.ids import generate_id
from maas.services.dead_letter import upsert_dead_letter_entry
from maas.services.failure_memory import (
    maybe_raise_repeated_failure_alert,
    quarantine_session_artifacts,
    record_failure,
    resolve_repeated_failure_alerts,
)
from maas.services.projects import list_projects, resolve_project_id
from maas.services.recovery_policy import (
    fetch_auto_recovery_candidate_tasks,
    fetch_project_recovery_policy,
    retry_deadline,
    task_timed_out_retry_limit,
    timed_out_retry_cooldown_seconds,
)
from maas.services.scheduler import allocate_ready_tasks, refresh_ready_tasks
from maas.services.security import revoke_task_capabilities
from maas.services.steering import _recover_and_requeue_task


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


def _maybe_route_timed_out_task_to_dlq(connection, project_id, task_id, actor_id, failure_id):
    task = connection.execute(
        """
        SELECT task_id, project_id, assigned_agent_id, status, retry_count, auto_retry_limit
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if task is None or task["status"] != "in_progress":
        return None

    recovery_policy = fetch_project_recovery_policy(connection, project_id)
    if not recovery_policy["auto_dlq_retry_exhausted_tasks"]:
        return None
    if not recovery_policy["auto_retry_timeout_sessions"]:
        return None

    retry_limit = task_timed_out_retry_limit(task, recovery_policy)
    if retry_limit <= 0 or task["retry_count"] < retry_limit:
        return None

    connection.execute(
        """
        UPDATE tasks
        SET status = 'blocked',
            review_state = 'needs_replan',
            next_retry_at = NULL,
            next_retry_reason = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ? AND status = 'in_progress'
        """,
        (task_id,),
    )
    dlq_id = upsert_dead_letter_entry(
        connection,
        project_id,
        task_id,
        "retry_budget_exhausted",
        failure_id=failure_id,
        detail={
            "failure_type": "session_timed_out",
            "retry_count": task["retry_count"],
            "retry_limit": retry_limit,
            "source": "timed_out_session_auto_retry",
        },
    )
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
        ) VALUES (?, ?, ?, ?, 'task_dead_lettered', 'supervisor', ?, ?, 'warning')
        """,
        (
            generate_id("act"),
            project_id,
            task["assigned_agent_id"],
            task_id,
            "Task routed to the dead-letter queue after timed-out-session retry budget exhaustion.",
            json.dumps({"dlq_id": dlq_id, "retry_limit": retry_limit, "retry_count": task["retry_count"]}),
        ),
    )
    resolve_repeated_failure_alerts(
        connection,
        project_id,
        task_id,
        actor_id,
        resolution_reason="task_dead_lettered",
    )
    return {"task_id": task_id, "dlq_id": dlq_id, "retry_limit": retry_limit, "retry_count": task["retry_count"]}


def _handle_stale_sessions(connection, stale_after_seconds, project_paths=None, project_id=None):
    stale_before = datetime.utcnow() - timedelta(seconds=stale_after_seconds)
    query = """
        SELECT session_id, project_id, agent_id, task_id
        FROM sessions
        WHERE status = 'active'
          AND last_heartbeat_at IS NOT NULL
          AND last_heartbeat_at < ?
    """
    parameters = [stale_before.strftime("%Y-%m-%d %H:%M:%S")]
    if project_id is not None:
        query += "\n  AND project_id = ?"
        parameters.append(project_id)
    stale_rows = connection.execute(query, tuple(parameters)).fetchall()

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
        revoke_task_capabilities(
            connection,
            row["project_id"],
            row["task_id"],
            agent_id=row["agent_id"],
            reason="session_timed_out",
            revoked_by="system_supervisor",
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
        dead_letter = None
        if not has_other_task_session:
            auto_retry = _maybe_auto_retry_timed_out_task(
                connection,
                row["project_id"],
                row["task_id"],
                actor_id="system_supervisor",
            )
            if auto_retry is None:
                dead_letter = _maybe_route_timed_out_task_to_dlq(
                    connection,
                    row["project_id"],
                    row["task_id"],
                    actor_id="system_supervisor",
                    failure_id=failure_id,
                )
            if auto_retry is None and dead_letter is None:
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
                "dead_lettered": dead_letter is not None,
                "retry_count": None if auto_retry is None else auto_retry["retry_count"],
                "next_retry_at": None if auto_retry is None else auto_retry["next_retry_at"],
            }
        )

    return findings


def _auto_recover_blocked_tasks(connection, project_id=None):
    resolved_project_id = resolve_project_id(connection, project_id) if project_id is not None else resolve_project_id(connection)
    if resolved_project_id is None:
        return []

    policy = fetch_project_recovery_policy(connection, resolved_project_id)
    if not policy["auto_recover_blocked_tasks"]:
        return []

    findings = []
    for candidate in fetch_auto_recovery_candidate_tasks(connection, project_id=resolved_project_id, limit=None):
        task = connection.execute(
            """
            SELECT task_id, project_id, assigned_agent_id, status, review_state
            FROM tasks
            WHERE task_id = ?
            """,
            (candidate["task_id"],),
        ).fetchone()
        if task is None:
            continue
        refreshed_task = _recover_and_requeue_task(
            connection,
            task,
            actor_id="agent_allocator",
            consume_retry_reason="blocked_task_auto_recovered",
        )
        findings.append(
            {
                "task_id": task["task_id"],
                "status": refreshed_task["status"],
                "review_state": refreshed_task["review_state"],
                "next_retry_at": refreshed_task["next_retry_at"],
                "next_retry_reason": refreshed_task["next_retry_reason"],
            }
        )
    return findings


def _active_project_ids(connection, project_id=None):
    if project_id is not None:
        resolved_project_id = resolve_project_id(connection, project_id)
        if resolved_project_id is None:
            raise ValueError("project not found")
        return [resolved_project_id]
    return [item["project_id"] for item in list_projects(connection, include_archived=False)]


def run_supervisor_once(
    connection,
    stale_after_seconds=HEARTBEAT_STALE_SECONDS,
    allocate_limit=None,
    project_paths=None,
    project_id=None,
):
    remaining_limit = allocate_limit
    project_runs = []
    ready_changes = []
    allocations = []
    stale_sessions = []
    auto_recovered_tasks = []

    for scoped_project_id in _active_project_ids(connection, project_id=project_id):
        project_ready_changes = refresh_ready_tasks(connection, commit=False, project_id=scoped_project_id)
        project_allocation_result = allocate_ready_tasks(
            connection,
            actor_id="system_supervisor",
            limit=remaining_limit,
            project_id=scoped_project_id,
        )
        project_stale_sessions = _handle_stale_sessions(
            connection,
            stale_after_seconds,
            project_paths=project_paths,
            project_id=scoped_project_id,
        )
        project_auto_recovered_tasks = _auto_recover_blocked_tasks(connection, project_id=scoped_project_id)
        if any(item.get("auto_retried") for item in project_stale_sessions) or project_auto_recovered_tasks:
            project_ready_changes.extend(
                refresh_ready_tasks(connection, commit=False, project_id=scoped_project_id)
            )
            retry_limit = remaining_limit
            if retry_limit is not None:
                retry_limit = max(retry_limit - project_allocation_result["assigned_count"], 0)
            retry_allocations = allocate_ready_tasks(
                connection,
                actor_id="system_supervisor",
                limit=retry_limit,
                project_id=scoped_project_id,
            )
            project_allocation_result = {
                "allocations": project_allocation_result["allocations"] + retry_allocations["allocations"],
                "assigned_count": project_allocation_result["assigned_count"] + retry_allocations["assigned_count"],
            }

        if remaining_limit is not None:
            remaining_limit = max(remaining_limit - project_allocation_result["assigned_count"], 0)

        ready_changes.extend(project_ready_changes)
        allocations.extend(project_allocation_result["allocations"])
        stale_sessions.extend(project_stale_sessions)
        auto_recovered_tasks.extend(project_auto_recovered_tasks)
        project_runs.append(
            {
                "project_id": scoped_project_id,
                "ready_changes": project_ready_changes,
                "allocations": project_allocation_result["allocations"],
                "assigned_count": project_allocation_result["assigned_count"],
                "stale_sessions": project_stale_sessions,
                "auto_recovered_tasks": project_auto_recovered_tasks,
            }
        )

    connection.commit()
    return {
        "ready_changes": ready_changes,
        "allocations": allocations,
        "assigned_count": len([item for item in allocations if item.get("assigned")]),
        "stale_sessions": stale_sessions,
        "auto_recovered_tasks": auto_recovered_tasks,
        "project_runs": project_runs,
    }
