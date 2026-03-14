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


def fetch_board(connection):
    rows = connection.execute(
        """
        SELECT
            tasks.task_id,
            tasks.title,
            tasks.description,
            tasks.status,
            tasks.priority,
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
    for row in rows:
        age_minutes = _age_minutes(row["created_at"])
        card = {
            "task_id": row["task_id"],
            "title": row["title"],
            "description": row["description"],
            "status": row["status"],
            "priority": row["priority"],
            "progress_pct": row["progress_pct"],
            "review_state": row["review_state"],
            "goal": {"id": row["goal_id"], "title": row["goal_title"]},
            "agent": {
                "id": row["agent_id"],
                "name": row["agent_name"],
                "status": row["agent_status"],
            },
            "heartbeat_age_seconds": _age_seconds(row["last_heartbeat_at"]),
            "age_hours": round(age_minutes / 60.0, 1) if age_minutes is not None else None,
        }
        cards_by_status.setdefault(row["status"], []).append(card)

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

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "columns": columns,
        "summary": {
            "total_tasks": len(rows),
            "active_agents": active_agents,
            "active_tasks": len(cards_by_status.get("in_progress", [])),
            "review_tasks": len(cards_by_status.get("review", [])),
            "blocked_tasks": len(cards_by_status.get("blocked", [])),
        },
        "filters": ["agent", "goal", "priority", "blocked_only", "review_only"],
    }
