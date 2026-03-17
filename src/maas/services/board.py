"""Board read models."""

from datetime import datetime

from maas.constants import BOARD_COLUMNS
from maas.services.scheduler import describe_task_scheduler, scheduler_decisions_for_tasks


def _parse_timestamp(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _age_minutes(value):
    created_at = _parse_timestamp(value)
    if created_at is None:
        return None
    return int((datetime.utcnow() - created_at).total_seconds() // 60)


def _age_seconds(value):
    created_at = _parse_timestamp(value)
    if created_at is None:
        return None
    return int((datetime.utcnow() - created_at).total_seconds())


def _matches_filters(row, filters):
    if not filters:
        return True

    search = (filters.get("search") or "").strip().lower()
    if search:
        haystack = " ".join(
            [
                row["task_id"] or "",
                row["title"] or "",
                row["description"] or "",
                row["goal_title"] or "",
                row["agent_name"] or "",
            ]
        ).lower()
        if search not in haystack:
            return False

    agent_id = filters.get("agent_id")
    if agent_id and row["agent_id"] != agent_id:
        return False

    goal_id = filters.get("goal_id")
    if goal_id and row["goal_id"] != goal_id:
        return False

    priority_min = filters.get("priority_min")
    if priority_min is not None and row["priority"] < priority_min:
        return False

    if filters.get("blocked_only") and row["status"] != "blocked":
        return False

    if filters.get("review_only") and row["status"] != "review":
        return False

    return True


def _board_column_key(status):
    if status == "assigned":
        return "ready"
    return status


def fetch_board(connection, filters=None, project_id=None):
    failure_query = """
        SELECT task_id, COUNT(*) AS failure_count, MAX(created_at) AS latest_failure_at
        FROM failure_log
        WHERE task_id IS NOT NULL
    """
    failure_params = []
    if project_id is not None:
        failure_query += "\n  AND project_id = ?"
        failure_params.append(project_id)
    failure_query += "\nGROUP BY task_id"
    failure_rows = connection.execute(
        failure_query,
        tuple(failure_params),
    ).fetchall()
    failures_by_task = {row["task_id"]: dict(row) for row in failure_rows}

    capability_query = """
        SELECT task_capability_grants.task_id, task_capability_grants.agent_id, task_capability_grants.capability
        FROM task_capability_grants
        JOIN tasks ON tasks.task_id = task_capability_grants.task_id
        WHERE task_capability_grants.revoked_at IS NULL
    """
    capability_params = []
    if project_id is not None:
        capability_query += "\n  AND tasks.project_id = ?"
        capability_params.append(project_id)
    capability_query += "\nORDER BY task_capability_grants.created_at ASC"
    capability_rows = connection.execute(
        capability_query,
        tuple(capability_params),
    ).fetchall()
    capabilities_by_task = {}
    for row in capability_rows:
        capabilities_by_task.setdefault(row["task_id"], []).append(
            {"agent_id": row["agent_id"], "capability": row["capability"]}
        )

    agent_query = """
        SELECT agent_id, project_id, role, display_name, status, current_task_id
        FROM agents
    """
    agent_params = []
    if project_id is not None:
        agent_query += "\nWHERE project_id = ?"
        agent_params.append(project_id)
    agent_query += "\nORDER BY display_name ASC"
    agent_rows = connection.execute(
        agent_query,
        tuple(agent_params),
    ).fetchall()

    task_query = """
        SELECT
            tasks.task_id,
            tasks.title,
            tasks.description,
            tasks.status,
            tasks.priority,
            tasks.retry_count,
            tasks.auto_retry_limit,
            tasks.last_retry_at,
            tasks.last_retry_reason,
            tasks.next_retry_at,
            tasks.next_retry_reason,
            tasks.progress_pct,
            tasks.review_state,
            tasks.assigned_agent_id,
            tasks.created_at,
            tasks.updated_at,
            tasks.last_heartbeat_at,
            goals.goal_id,
            goals.title AS goal_title,
            agents.agent_id,
            agents.display_name AS agent_name,
            agents.status AS agent_status
        FROM tasks
        LEFT JOIN goals ON goals.goal_id = tasks.goal_id
        LEFT JOIN agents ON agents.agent_id = tasks.assigned_agent_id
    """
    task_params = []
    if project_id is not None:
        task_query += "\nWHERE tasks.project_id = ?"
        task_params.append(project_id)
    task_query += "\nORDER BY tasks.priority DESC, tasks.created_at ASC"
    rows = connection.execute(
        task_query,
        tuple(task_params),
    ).fetchall()

    scheduler_decisions = scheduler_decisions_for_tasks(rows, agent_rows)

    cards_by_status = {}
    filtered_rows = [row for row in rows if _matches_filters(row, filters or {})]
    for row in filtered_rows:
        age_minutes = _age_minutes(row["created_at"])
        column_key = _board_column_key(row["status"])
        scheduler = describe_task_scheduler(row, scheduler_decisions.get(row["task_id"]))
        card = {
            "task_id": row["task_id"],
            "title": row["title"],
            "description": row["description"],
            "status": row["status"],
            "priority": row["priority"],
            "progress_pct": row["progress_pct"],
            "retry_count": row["retry_count"],
            "auto_retry_limit": row["auto_retry_limit"],
            "last_retry_at": row["last_retry_at"],
            "last_retry_reason": row["last_retry_reason"],
            "next_retry_at": row["next_retry_at"],
            "next_retry_reason": row["next_retry_reason"],
            "review_state": row["review_state"],
            "goal": {"id": row["goal_id"], "title": row["goal_title"]},
            "agent": {
                "id": row["agent_id"],
                "name": row["agent_name"],
                "status": row["agent_status"],
            },
            "capabilities": capabilities_by_task.get(row["task_id"], []),
            "failure_count": failures_by_task.get(row["task_id"], {}).get("failure_count", 0),
            "latest_failure_at": failures_by_task.get(row["task_id"], {}).get("latest_failure_at"),
            "heartbeat_age_seconds": _age_seconds(row["last_heartbeat_at"]),
            "age_hours": round(age_minutes / 60.0, 1) if age_minutes is not None else None,
            "scheduler_status": scheduler.get("scheduler_status"),
            "scheduler_summary": scheduler.get("scheduler_summary"),
            "scheduler_score": scheduler.get("scheduler_score"),
            "scheduler_rank": scheduler.get("scheduler_rank"),
            "scheduler_agent": (
                {
                    "id": scheduler.get("scheduler_agent_id"),
                    "name": scheduler.get("scheduler_agent_name"),
                }
                if scheduler.get("scheduler_agent_id")
                else None
            ),
            "scheduler_factors": scheduler.get("scheduler_factors", []),
        }
        cards_by_status.setdefault(column_key, []).append(card)

    active_agents_query = "SELECT COUNT(*) AS count FROM agents WHERE status = 'running'"
    active_agents_params = []
    if project_id is not None:
        active_agents_query += " AND project_id = ?"
        active_agents_params.append(project_id)
    active_agents = connection.execute(active_agents_query, tuple(active_agents_params)).fetchone()["count"]

    columns = []
    for status, label in BOARD_COLUMNS:
        columns.append(
            {
                "key": status,
                "title": label,
                "tasks": cards_by_status.get(status, []),
            }
        )

    agent_options_query = """
        SELECT agent_id AS id, display_name AS label
        FROM agents
    """
    goal_options_query = """
        SELECT goal_id AS id, title AS label
        FROM goals
    """
    options_params = []
    if project_id is not None:
        agent_options_query += "\nWHERE project_id = ?"
        goal_options_query += "\nWHERE project_id = ?"
        options_params.append(project_id)
    agent_options_query += "\nORDER BY display_name ASC"
    goal_options_query += "\nORDER BY priority DESC, created_at ASC"
    agent_options = connection.execute(agent_options_query, tuple(options_params)).fetchall()
    goal_options = connection.execute(goal_options_query, tuple(options_params)).fetchall()

    selected_filters = {
        "search": (filters or {}).get("search") or "",
        "agent_id": (filters or {}).get("agent_id"),
        "goal_id": (filters or {}).get("goal_id"),
        "priority_min": (filters or {}).get("priority_min"),
        "blocked_only": bool((filters or {}).get("blocked_only")),
        "review_only": bool((filters or {}).get("review_only")),
    }

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "columns": columns,
        "summary": {
            "total_tasks": len(filtered_rows),
            "active_agents": active_agents,
            "active_tasks": len(cards_by_status.get("in_progress", [])),
            "review_tasks": len(cards_by_status.get("review", [])),
            "blocked_tasks": len(cards_by_status.get("blocked", [])),
        },
        "filters": ["agent", "goal", "priority", "blocked_only", "review_only"],
        "filter_options": {
            "agents": [dict(row) for row in agent_options],
            "goals": [dict(row) for row in goal_options],
            "priority_min_values": [0, 50, 75, 90],
        },
        "selected_filters": selected_filters,
    }
