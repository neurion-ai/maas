"""Dashboard read models for overview, goal tree, and roster surfaces."""

from datetime import datetime
import json

from maas.services.escalations import fetch_escalations
from maas.services.failure_memory import enrich_failures_with_quarantine, fetch_repeated_failure_tasks, repeated_failure_task_count


BROWNFIELD_REVIEW_TASK_TITLE = "Review imported project understanding"
BROWNFIELD_PENDING_REVIEW_STATE = "awaiting_onboarding_approval"


def _parse_timestamp(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _age_seconds(value):
    parsed = _parse_timestamp(value)
    if parsed is None:
        return None
    return int((datetime.utcnow() - parsed).total_seconds())


def _load_project_config(raw_config):
    try:
        config = json.loads(raw_config or "{}")
    except ValueError:
        return {}
    return config if isinstance(config, dict) else {}


def _derive_onboarding_state(connection, project_row):
    if project_row is None:
        return None

    config = _load_project_config(project_row["config_json"])
    onboarding = dict(config.get("onboarding") or {})
    mode = onboarding.get("mode") or "greenfield"

    if mode != "brownfield":
        return {
            "mode": mode,
            "review_status": onboarding.get("review_status") or "not_applicable",
            "review_required": False,
            "discovery_summary": onboarding.get("discovery_summary") or {},
            "review_task_id": None,
            "review_task_status": None,
            "review_task_review_state": None,
            "pending_gated_tasks": 0,
            "reviewed_by": onboarding.get("reviewed_by"),
            "reviewed_at": onboarding.get("reviewed_at"),
        }

    review_task = connection.execute(
        """
        SELECT task_id, status, review_state
        FROM tasks
        WHERE project_id = ? AND title = ?
        ORDER BY created_at ASC
        LIMIT 1
        """,
        (project_row["project_id"], BROWNFIELD_REVIEW_TASK_TITLE),
    ).fetchone()
    pending_gated_tasks = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM tasks
        WHERE project_id = ?
          AND status = 'blocked'
          AND review_state = ?
        """,
        (project_row["project_id"], BROWNFIELD_PENDING_REVIEW_STATE),
    ).fetchone()["count"]

    review_status = onboarding.get("review_status")
    if not review_status:
        if review_task is None:
            review_status = "review_pending"
        elif review_task["status"] == "done" or review_task["review_state"] == "approved":
            review_status = "approved"
        elif review_task["review_state"] == "changes_requested":
            review_status = "changes_requested"
        else:
            review_status = "review_pending"

    return {
        "mode": "brownfield",
        "review_status": review_status,
        "review_required": review_status != "approved",
        "discovery_summary": onboarding.get("discovery_summary") or {},
        "review_task_id": review_task["task_id"] if review_task else onboarding.get("review_task_id"),
        "review_task_status": review_task["status"] if review_task else None,
        "review_task_review_state": review_task["review_state"] if review_task else None,
        "pending_gated_tasks": pending_gated_tasks,
        "reviewed_by": onboarding.get("reviewed_by"),
        "reviewed_at": onboarding.get("reviewed_at"),
    }


def fetch_overview(connection):
    project = connection.execute(
        """
        SELECT project_id, name, description, project_type, config_json
        FROM projects
        ORDER BY created_at ASC
        LIMIT 1
        """
    ).fetchone()
    onboarding = _derive_onboarding_state(connection, project)

    task_counts = {
        row["status"]: row["count"]
        for row in connection.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM tasks
            GROUP BY status
            """
        ).fetchall()
    }
    goal_counts = {
        row["status"]: row["count"]
        for row in connection.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM goals
            GROUP BY status
            """
        ).fetchall()
    }
    alert_counts = {
        row["severity"]: row["count"]
        for row in connection.execute(
            """
            SELECT severity, COUNT(*) AS count
            FROM alerts
            WHERE status = 'open'
            GROUP BY severity
            """
        ).fetchall()
    }

    active_tasks = [
        dict(row)
        for row in connection.execute(
            """
            SELECT
                tasks.task_id,
                tasks.title,
                tasks.status,
                tasks.priority,
                tasks.retry_count,
                tasks.last_retry_reason,
                tasks.next_retry_at,
                tasks.next_retry_reason,
                goals.title AS goal_title,
                agents.display_name AS agent_name
            FROM tasks
            LEFT JOIN goals ON goals.goal_id = tasks.goal_id
            LEFT JOIN agents ON agents.agent_id = tasks.assigned_agent_id
            WHERE tasks.status IN ('in_progress', 'review', 'blocked')
            ORDER BY tasks.priority DESC, tasks.created_at ASC
            LIMIT 6
            """
        ).fetchall()
    ]

    recent_activity = [
        dict(row)
        for row in connection.execute(
            """
            SELECT action, description, severity, created_at
            FROM activity_log
            ORDER BY created_at DESC
            LIMIT 8
            """
        ).fetchall()
    ]
    recent_failures = [
        dict(row)
        for row in connection.execute(
            """
            SELECT
                failure_log.failure_id,
                failure_log.task_id,
                failure_log.session_id,
                failure_log.failure_type,
                failure_log.summary,
                failure_log.created_at,
                tasks.title AS task_title,
                tasks.status AS task_status,
                tasks.review_state AS task_review_state
            FROM failure_log
            LEFT JOIN tasks ON tasks.task_id = failure_log.task_id
            ORDER BY failure_log.created_at DESC
            LIMIT 5
            """
        ).fetchall()
    ]
    recent_failures = enrich_failures_with_quarantine(connection, recent_failures)
    repeated_failure_tasks = fetch_repeated_failure_tasks(connection, limit=5)
    escalation_summary = fetch_escalations(connection)["summary"]

    return {
        "project": (
            {
                "project_id": project["project_id"],
                "name": project["name"],
                "description": project["description"],
                "project_type": project["project_type"],
            }
            if project
            else None
        ),
        "onboarding": onboarding,
        "summary": {
            "tasks_total": sum(task_counts.values()),
            "tasks_in_progress": task_counts.get("in_progress", 0),
            "tasks_review": task_counts.get("review", 0),
            "tasks_blocked": task_counts.get("blocked", 0),
            "goals_total": sum(goal_counts.values()),
            "goals_active": goal_counts.get("active", 0),
            "alerts_open": sum(alert_counts.values()),
            "alerts_critical": alert_counts.get("critical", 0),
            "escalations_open": escalation_summary["open"],
            "failures_total": connection.execute(
                "SELECT COUNT(*) AS count FROM failure_log"
            ).fetchone()["count"],
            "repeated_failure_tasks": repeated_failure_task_count(connection),
            "agents_running": connection.execute(
                "SELECT COUNT(*) AS count FROM agents WHERE status = 'running'"
            ).fetchone()["count"],
        },
        "active_work": active_tasks,
        "recent_activity": recent_activity,
        "recent_failures": recent_failures,
        "repeated_failures": repeated_failure_tasks,
    }


def fetch_goal_tree(connection):
    goal_rows = connection.execute(
        """
        SELECT goal_id, parent_goal_id, title, description, status, goal_type, priority
        FROM goals
        ORDER BY priority DESC, created_at ASC
        """
    ).fetchall()
    task_rows = connection.execute(
        """
        SELECT goal_id, status, COUNT(*) AS count
        FROM tasks
        GROUP BY goal_id, status
        """
    ).fetchall()

    task_counts_by_goal = {}
    for row in task_rows:
        task_counts_by_goal.setdefault(row["goal_id"], {})[row["status"]] = row["count"]

    nodes = {}
    roots = []
    for row in goal_rows:
        node = {
            "goal_id": row["goal_id"],
            "parent_goal_id": row["parent_goal_id"],
            "title": row["title"],
            "description": row["description"],
            "status": row["status"],
            "goal_type": row["goal_type"],
            "priority": row["priority"],
            "task_counts": task_counts_by_goal.get(row["goal_id"], {}),
            "children": [],
        }
        nodes[row["goal_id"]] = node

    for node in nodes.values():
        parent_goal_id = node["parent_goal_id"]
        if parent_goal_id and parent_goal_id in nodes:
            nodes[parent_goal_id]["children"].append(node)
        else:
            roots.append(node)

    return {"roots": roots, "total_goals": len(goal_rows)}


def fetch_agent_roster(connection):
    rows = connection.execute(
        """
        SELECT
            agents.agent_id,
            agents.role,
            agents.display_name,
            agents.status,
            agents.current_task_id,
            agents.last_heartbeat_at,
            tasks.title AS current_task_title
        FROM agents
        LEFT JOIN tasks ON tasks.task_id = agents.current_task_id
        ORDER BY agents.display_name ASC
        """
    ).fetchall()

    agents = []
    for row in rows:
        agents.append(
            {
                "agent_id": row["agent_id"],
                "role": row["role"],
                "display_name": row["display_name"],
                "status": row["status"],
                "current_task_id": row["current_task_id"],
                "current_task_title": row["current_task_title"],
                "heartbeat_age_seconds": _age_seconds(row["last_heartbeat_at"]),
            }
        )
    return {"agents": agents}
