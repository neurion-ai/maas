"""Board read models."""

from datetime import datetime
import json
import os

from maas.constants import BOARD_COLUMNS
from maas.services.codex_mvp import issue_key_lookup
from maas.services.git_workspaces import fetch_latest_git_workspace_by_task
from maas.services.scheduler import adaptive_replan_feedback, describe_task_scheduler, scheduler_decisions_for_tasks
from maas.services.verification import fetch_latest_verification_by_task


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
    return status


def _parse_acceptance_criteria(raw_value):
    try:
        parsed = json.loads(raw_value or "[]")
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _scoped_paths_from_acceptance(raw_value):
    scoped_paths = []
    seen = set()
    for criterion in _parse_acceptance_criteria(raw_value):
        if criterion.get("type") != "source_path_exists":
            continue
        raw_paths = criterion.get("paths") or []
        if isinstance(raw_paths, str):
            raw_paths = [raw_paths]
        for path in raw_paths:
            if not path or path in seen:
                continue
            seen.add(path)
            scoped_paths.append(path)
    return scoped_paths


def _validation_commands_from_acceptance(raw_value):
    commands = []
    seen = set()
    for criterion in _parse_acceptance_criteria(raw_value):
        if criterion.get("type") != "test_passes":
            continue
        command = (criterion.get("command") or "").strip()
        if not command or command in seen:
            continue
        seen.add(command)
        commands.append(command)
    return commands


def _project_supports_git_workspaces(connection, project_id):
    project_row = connection.execute(
        """
        SELECT source_root
        FROM projects
        WHERE project_id = ?
        """,
        (project_id,),
    ).fetchone()
    source_root = os.path.abspath((project_row["source_root"] if project_row else "") or "")
    if not source_root:
        return False
    return os.path.exists(os.path.join(source_root, ".git"))


def fetch_board(connection, filters=None, project_id=None):
    issue_keys = issue_key_lookup(connection, project_id)
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
            tasks.project_id,
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
            tasks.acceptance_criteria_json,
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
    scheduler_rows = []
    for row in rows:
        item = dict(row)
        failure = failures_by_task.get(row["task_id"], {})
        item["failure_count"] = failure.get("failure_count", 0)
        item["latest_failure_at"] = failure.get("latest_failure_at")
        scheduler_rows.append(item)

    scheduler_decisions = scheduler_decisions_for_tasks(scheduler_rows, agent_rows)
    latest_verification_by_task = fetch_latest_verification_by_task(connection, project_id=project_id)
    git_workspaces_by_task = fetch_latest_git_workspace_by_task(connection, project_id=project_id)

    cards_by_status = {}
    filtered_rows = [row for row in scheduler_rows if _matches_filters(row, filters or {})]
    git_supported_by_project = {}
    for row in filtered_rows:
        age_minutes = _age_minutes(row["created_at"])
        column_key = _board_column_key(row["status"])
        scheduler = describe_task_scheduler(row, scheduler_decisions.get(row["task_id"]))
        replan_feedback = adaptive_replan_feedback(row)
        latest_verification = latest_verification_by_task.get(row["task_id"]) or {}
        git_workspace = git_workspaces_by_task.get(row["task_id"]) or {}
        if row["project_id"] not in git_supported_by_project:
            git_supported_by_project[row["project_id"]] = _project_supports_git_workspaces(connection, row["project_id"])
        card = {
            "task_id": row["task_id"],
            "issue_key": issue_keys.get(row["task_id"]),
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
            "failure_count": row.get("failure_count", 0),
            "latest_failure_at": row.get("latest_failure_at"),
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
            "replan_strategy": replan_feedback.get("replan_strategy") if replan_feedback else None,
            "replan_summary": replan_feedback.get("replan_summary") if replan_feedback else None,
            "scoped_paths": _scoped_paths_from_acceptance(row["acceptance_criteria_json"]),
            "validation_commands": _validation_commands_from_acceptance(row["acceptance_criteria_json"]),
            "has_verification_recipe": bool(_validation_commands_from_acceptance(row["acceptance_criteria_json"])),
            "latest_verification_status": latest_verification.get("status"),
            "latest_verification_at": latest_verification.get("finished_at"),
            "latest_verification_command": latest_verification.get("command"),
            "git_workspace_supported": git_supported_by_project.get(row["project_id"], False),
            "git_workspace_prepared": bool(git_workspace),
            "git_workspace_branch": git_workspace.get("branch_name"),
            "git_workspace_dirty_files": git_workspace.get("dirty_file_count", 0),
            "git_workspace_change_summary": git_workspace.get("change_summary"),
            "git_workspace_last_diff_at": git_workspace.get("updated_at"),
            "git_workspace_diff_artifact_id": git_workspace.get("last_diff_artifact_id"),
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
            "assigned_tasks": len(cards_by_status.get("assigned", [])),
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
