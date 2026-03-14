"""Board read models."""

from datetime import datetime

from maas.constants import BOARD_COLUMNS


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


def fetch_board(connection, filters=None):
    failure_rows = connection.execute(
        """
        SELECT task_id, COUNT(*) AS failure_count, MAX(created_at) AS latest_failure_at
        FROM failure_log
        WHERE task_id IS NOT NULL
        GROUP BY task_id
        """
    ).fetchall()
    failures_by_task = {row["task_id"]: dict(row) for row in failure_rows}

    capability_rows = connection.execute(
        """
        SELECT task_id, agent_id, capability
        FROM task_capability_grants
        WHERE revoked_at IS NULL
        ORDER BY created_at ASC
        """
    ).fetchall()
    capabilities_by_task = {}
    for row in capability_rows:
        capabilities_by_task.setdefault(row["task_id"], []).append(
            {"agent_id": row["agent_id"], "capability": row["capability"]}
        )

    rows = connection.execute(
        """
        SELECT
            tasks.task_id,
            tasks.title,
            tasks.description,
            tasks.status,
            tasks.priority,
            tasks.retry_count,
            tasks.last_retry_at,
            tasks.last_retry_reason,
            tasks.progress_pct,
            tasks.review_state,
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
        ORDER BY tasks.priority DESC, tasks.created_at ASC
        """
    ).fetchall()

    cards_by_status = {}
    filtered_rows = [row for row in rows if _matches_filters(row, filters or {})]
    for row in filtered_rows:
        age_minutes = _age_minutes(row["created_at"])
        column_key = _board_column_key(row["status"])
        card = {
            "task_id": row["task_id"],
            "title": row["title"],
            "description": row["description"],
            "status": row["status"],
            "priority": row["priority"],
            "progress_pct": row["progress_pct"],
            "retry_count": row["retry_count"],
            "last_retry_at": row["last_retry_at"],
            "last_retry_reason": row["last_retry_reason"],
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
        }
        cards_by_status.setdefault(column_key, []).append(card)

    active_agents = connection.execute(
        "SELECT COUNT(*) AS count FROM agents WHERE status = 'running'"
    ).fetchone()["count"]

    columns = []
    for status, label in BOARD_COLUMNS:
        columns.append(
            {
                "key": status,
                "title": label,
                "tasks": cards_by_status.get(status, []),
            }
        )

    agent_options = connection.execute(
        """
        SELECT agent_id AS id, display_name AS label
        FROM agents
        ORDER BY display_name ASC
        """
    ).fetchall()
    goal_options = connection.execute(
        """
        SELECT goal_id AS id, title AS label
        FROM goals
        ORDER BY priority DESC, created_at ASC
        """
    ).fetchall()

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
