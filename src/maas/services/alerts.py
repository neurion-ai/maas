"""Alert read models and steering actions."""

import json
import re

from maas.ids import generate_id
from maas.services.security import ensure_board_action_allowed


TASK_SESSION_FAILED_PATTERN = re.compile(r"^Task (?P<task_id>\S+) failed in session (?P<session_id>\S+)\.")
REPEATED_TASK_FAILURE_PATTERN = re.compile(r"^Task (?P<task_id>\S+) \(")
STALE_AGENT_HEARTBEAT_PATTERN = re.compile(
    r"^Agent (?P<agent_id>\S+) stopped heartbeating for task (?P<task_id>\S+)\."
)
RECOVERABLE_FAILURE_REVIEW_STATES = ("session_failed", "stale_session")


def _escape_like(value):
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _can_recover_task(connection, task_id):
    task = connection.execute(
        """
        SELECT status, review_state
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if task is None:
        return False
    return task["status"] == "blocked" and task["review_state"] in RECOVERABLE_FAILURE_REVIEW_STATES


def _can_resolve_repeated_failures(connection, task_id):
    task = connection.execute(
        """
        SELECT task_id
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    return task is not None


def _can_recover_agent(connection, agent_id):
    agent = connection.execute(
        """
        SELECT status, current_task_id
        FROM agents
        WHERE agent_id = ?
        """,
        (agent_id,),
    ).fetchone()
    if agent is None:
        return False
    if agent["status"] != "error" or agent["current_task_id"] is not None:
        return False
    active_session = connection.execute(
        """
        SELECT session_id
        FROM sessions
        WHERE agent_id = ? AND status = 'active'
        LIMIT 1
        """,
        (agent_id,),
    ).fetchone()
    return active_session is None


def infer_operator_action(connection, title, description):
    if title == "Task session failed":
        match = TASK_SESSION_FAILED_PATTERN.match(description)
        if match is not None and _can_recover_task(connection, match.group("task_id")):
            return {
                "action": "recover_task",
                "label": "Recover task",
                "resource_type": "task",
                "resource_id": match.group("task_id"),
            }
    if title == "Repeated task failures":
        match = REPEATED_TASK_FAILURE_PATTERN.match(description)
        if match is not None and _can_resolve_repeated_failures(connection, match.group("task_id")):
            return {
                "action": "resolve_repeated_failures",
                "label": "Resolve repeated failures",
                "resource_type": "task",
                "resource_id": match.group("task_id"),
            }
    if title == "Stale agent heartbeat":
        match = STALE_AGENT_HEARTBEAT_PATTERN.match(description)
        if match is not None and _can_recover_agent(connection, match.group("agent_id")):
            return {
                "action": "recover_agent",
                "label": "Recover agent",
                "resource_type": "agent",
                "resource_id": match.group("agent_id"),
                "related_task_id": match.group("task_id"),
            }
    return None


def _record_alert_status_change(connection, project_id, actor_id, alert_id, status, reason=None):
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, ?, 'alert', ?, ?)
        """,
        (
            generate_id("audit"),
            project_id,
            actor_id,
            "alert_status_updated",
            alert_id,
            json.dumps({"status": status, "reason": reason}),
        ),
    )


def _log_alert_resolution_activity(connection, project_id, actor_id, task_id, action, description, details):
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
        ) VALUES (?, ?, ?, ?, ?, 'steering', ?, ?, 'info')
        """,
        (
            generate_id("act"),
            project_id,
            actor_id,
            task_id,
            action,
            description,
            json.dumps(details),
        ),
    )


def _resolve_alerts_by_query(connection, query, params, project_id, actor_id, reason, task_id, activity_action, activity_description):
    rows = connection.execute(query, params).fetchall()
    resolved_alert_ids = []
    for row in rows:
        connection.execute(
            "UPDATE alerts SET status = 'resolved' WHERE alert_id = ?",
            (row["alert_id"],),
        )
        _record_alert_status_change(connection, project_id, actor_id, row["alert_id"], "resolved", reason=reason)
        resolved_alert_ids.append(row["alert_id"])

    if resolved_alert_ids:
        _log_alert_resolution_activity(
            connection,
            project_id,
            actor_id,
            task_id,
            activity_action,
            activity_description,
            {"alert_ids": resolved_alert_ids, "reason": reason},
        )

    return resolved_alert_ids


def resolve_task_session_failed_alerts(
    connection,
    project_id,
    task_id,
    actor_id,
    reason,
    activity_description="Task failure alerts resolved after task recovery.",
):
    return _resolve_alerts_by_query(
        connection,
        """
        SELECT alert_id
        FROM alerts
        WHERE project_id = ?
          AND status IN ('open', 'acknowledged')
          AND title = 'Task session failed'
          AND description LIKE ?
          ESCAPE '\\'
        """,
        (project_id, "Task {0} failed in session %".format(_escape_like(task_id))),
        project_id,
        actor_id,
        reason,
        task_id,
        "task_failure_alert_resolved",
        activity_description,
    )


def resolve_stale_heartbeat_alerts(connection, project_id, agent_id, actor_id, reason):
    return _resolve_alerts_by_query(
        connection,
        """
        SELECT alert_id
        FROM alerts
        WHERE project_id = ?
          AND status IN ('open', 'acknowledged')
          AND title = 'Stale agent heartbeat'
          AND description LIKE ?
          ESCAPE '\\'
        """,
        (project_id, "Agent {0} stopped heartbeating for task %".format(_escape_like(agent_id))),
        project_id,
        actor_id,
        reason,
        None,
        "stale_heartbeat_alert_resolved",
        "Stale heartbeat alerts resolved after agent recovery.",
    )


def fetch_alerts(connection):
    rows = connection.execute(
        """
        SELECT alert_id, project_id, severity, title, description, status, created_at
        FROM alerts
        ORDER BY
            CASE status WHEN 'open' THEN 0 WHEN 'acknowledged' THEN 1 ELSE 2 END,
            CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
            created_at DESC
        """
    ).fetchall()

    grouped = {"open": [], "acknowledged": [], "resolved": []}
    for row in rows:
        alert = dict(row)
        operator_action = infer_operator_action(connection, alert["title"], alert["description"])
        if operator_action is not None:
            alert["operator_action"] = operator_action
        grouped.setdefault(alert["status"], []).append(alert)

    return {
        "alerts": [alert for alerts in grouped.values() for alert in alerts],
        "grouped": grouped,
        "summary": {
            "open": len(grouped.get("open", [])),
            "acknowledged": len(grouped.get("acknowledged", [])),
            "resolved": len(grouped.get("resolved", [])),
            "critical_open": len(
                [alert for alert in grouped.get("open", []) if alert["severity"] == "critical"]
            ),
            "repeated_failure_open": len(
                [
                    alert
                    for alert in grouped.get("open", [])
                    if alert["title"] == "Repeated task failures"
                ]
            ),
        },
    }


def update_alert_status(connection, alert_id, actor_id, status):
    alert = connection.execute(
        "SELECT alert_id, project_id, status FROM alerts WHERE alert_id = ?",
        (alert_id,),
    ).fetchone()
    if alert is None:
        raise ValueError("Alert not found")
    ensure_board_action_allowed(connection, actor_id, alert["project_id"], "update_alert_status", "alert", alert_id)
    if status not in ("acknowledged", "resolved"):
        raise ValueError("Unsupported alert status")
    if alert["status"] == status:
        return {"alert_id": alert_id, "status": status}

    connection.execute(
        "UPDATE alerts SET status = ? WHERE alert_id = ?",
        (status, alert_id),
    )
    _record_alert_status_change(connection, alert["project_id"], actor_id, alert_id, status)
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, action, category, description, details_json, severity
        ) VALUES (?, ?, 'alert_status_updated', 'steering', ?, ?, 'info')
        """,
        (
            generate_id("act"),
            alert["project_id"],
            "Alert {0} moved to {1}.".format(alert_id, status),
            json.dumps({"alert_id": alert_id, "status": status}),
        ),
    )
    connection.commit()
    return {"alert_id": alert_id, "status": status}
