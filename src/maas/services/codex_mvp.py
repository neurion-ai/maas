"""Codex MVP read models."""

import json
import os

from maas.services.artifacts import fetch_artifacts
from maas.services.git_workspaces import fetch_task_git_workspace
from maas.services.timeline import fetch_incident_timeline
from maas.services.verification import fetch_verification_runs


RUN_CONSOLE_PREVIEW_MAX_CHARS = 6000


def _tail_console_preview(path):
    if not path or not os.path.exists(path) or not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            read_start = max(size - (RUN_CONSOLE_PREVIEW_MAX_CHARS * 4), 0)
            handle.seek(read_start)
            payload = handle.read()
    except OSError:
        return None
    content = payload.decode("utf-8", errors="ignore")
    truncated = len(content) > RUN_CONSOLE_PREVIEW_MAX_CHARS
    if truncated:
        content = content[-RUN_CONSOLE_PREVIEW_MAX_CHARS:]
    return {
        "path": path,
        "content": content,
        "truncated": truncated,
    }


def _load_json(value):
    try:
        payload = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def issue_key_lookup(connection, project_id=None):
    query = """
        SELECT task_id
        FROM tasks
    """
    params = []
    if project_id is not None:
        query += "\nWHERE project_id = ?"
        params.append(project_id)
    query += "\nORDER BY created_at ASC, task_id ASC"
    rows = connection.execute(query, tuple(params)).fetchall()
    return {
        row["task_id"]: "ISS-{0}".format(str(index + 1).zfill(4))
        for index, row in enumerate(rows)
    }


def _task_link(row, issue_keys):
    dependency_type = row["dependency_type"] if "dependency_type" in row.keys() else None
    return {
        "task_id": row["task_id"],
        "issue_key": issue_keys.get(row["task_id"]),
        "title": row["title"],
        "status": row["status"],
        "priority": row["priority"],
        "review_state": row["review_state"],
        "goal_id": row["goal_id"],
        "goal_title": row["goal_title"],
        "agent_id": row["agent_id"],
        "agent_name": row["agent_name"],
        "dependency_type": dependency_type,
    }


def _task_relationships(connection, project_id, task_id, goal_id, issue_keys):
    depends_on_rows = connection.execute(
        """
        SELECT
            tasks.task_id,
            tasks.title,
            tasks.status,
            tasks.priority,
            tasks.review_state,
            tasks.goal_id,
            goals.title AS goal_title,
            tasks.assigned_agent_id AS agent_id,
            agents.display_name AS agent_name,
            td.dependency_type
        FROM task_dependencies td
        JOIN tasks ON tasks.task_id = td.source_task_id
        LEFT JOIN goals ON goals.goal_id = tasks.goal_id
        LEFT JOIN agents ON agents.agent_id = tasks.assigned_agent_id
        WHERE td.project_id = ?
          AND td.target_task_id = ?
        ORDER BY
            CASE td.dependency_type
                WHEN 'blocks' THEN 0
                WHEN 'conflicts' THEN 1
                ELSE 2
            END,
            tasks.priority DESC,
            tasks.created_at ASC
        LIMIT 12
        """,
        (project_id, task_id),
    ).fetchall()

    unlocks_rows = connection.execute(
        """
        SELECT
            tasks.task_id,
            tasks.title,
            tasks.status,
            tasks.priority,
            tasks.review_state,
            tasks.goal_id,
            goals.title AS goal_title,
            tasks.assigned_agent_id AS agent_id,
            agents.display_name AS agent_name,
            td.dependency_type
        FROM task_dependencies td
        JOIN tasks ON tasks.task_id = td.target_task_id
        LEFT JOIN goals ON goals.goal_id = tasks.goal_id
        LEFT JOIN agents ON agents.agent_id = tasks.assigned_agent_id
        WHERE td.project_id = ?
          AND td.source_task_id = ?
        ORDER BY
            CASE td.dependency_type
                WHEN 'blocks' THEN 0
                WHEN 'conflicts' THEN 1
                ELSE 2
            END,
            tasks.priority DESC,
            tasks.created_at ASC
        LIMIT 12
        """,
        (project_id, task_id),
    ).fetchall()

    related_rows = []
    if goal_id:
        related_rows = connection.execute(
            """
            SELECT
                tasks.task_id,
                tasks.title,
                tasks.status,
                tasks.priority,
                tasks.review_state,
                tasks.goal_id,
                goals.title AS goal_title,
                tasks.assigned_agent_id AS agent_id,
                agents.display_name AS agent_name
            FROM tasks
            LEFT JOIN goals ON goals.goal_id = tasks.goal_id
            LEFT JOIN agents ON agents.agent_id = tasks.assigned_agent_id
            WHERE tasks.project_id = ?
              AND tasks.goal_id = ?
              AND tasks.task_id != ?
            ORDER BY
                CASE tasks.status
                    WHEN 'in_progress' THEN 0
                    WHEN 'review' THEN 1
                    WHEN 'blocked' THEN 2
                    WHEN 'assigned' THEN 3
                    WHEN 'ready' THEN 4
                    WHEN 'planned' THEN 5
                    ELSE 6
                END,
                tasks.priority DESC,
                tasks.created_at ASC
            LIMIT 12
            """,
            (project_id, goal_id, task_id),
        ).fetchall()

    return {
        "depends_on": [_task_link(row, issue_keys) for row in depends_on_rows],
        "unlocks": [_task_link(row, issue_keys) for row in unlocks_rows],
        "related": [_task_link(row, issue_keys) for row in related_rows],
    }


def _task_runs(connection, project_id, task_id):
    rows = connection.execute(
        """
        SELECT
            sessions.session_id,
            sessions.agent_id,
            agents.display_name AS agent_name,
            sessions.provider_type,
            sessions.status,
            sessions.progress_pct,
            sessions.status_message,
            sessions.last_heartbeat_at,
            sessions.started_at,
            sessions.ended_at
        FROM sessions
        LEFT JOIN agents ON agents.agent_id = sessions.agent_id
        WHERE sessions.project_id = ?
          AND sessions.task_id = ?
        ORDER BY sessions.started_at DESC, sessions.rowid DESC
        LIMIT 12
        """,
        (project_id, task_id),
    ).fetchall()
    return [
        {
            "session_id": row["session_id"],
            "agent_id": row["agent_id"],
            "agent_name": row["agent_name"],
            "provider_type": row["provider_type"],
            "status": row["status"],
            "progress_pct": row["progress_pct"],
            "status_message": row["status_message"],
            "last_heartbeat_at": row["last_heartbeat_at"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
        }
        for row in rows
    ]


def _session_activity(connection, project_id, task_id, session_id, limit=12):
    rows = connection.execute(
        """
        SELECT activity_id, action, description, severity, created_at, details_json
        FROM activity_log
        WHERE project_id = ?
          AND task_id = ?
          AND json_extract(details_json, '$.session_id') = ?
        ORDER BY created_at DESC, rowid DESC
        LIMIT ?
        """,
        (project_id, task_id, session_id, limit),
    ).fetchall()
    items = []
    for row in rows:
        details = _load_json(row["details_json"])
        items.append(
            {
                "activity_id": row["activity_id"],
                "action": row["action"],
                "description": row["description"],
                "severity": row["severity"],
                "created_at": row["created_at"],
                "details": details,
            }
        )
    return items


def _session_start_details(connection, project_id, task_id, session_id):
    row = connection.execute(
        """
        SELECT details_json
        FROM activity_log
        WHERE project_id = ?
          AND task_id = ?
          AND action = 'provider_adapter_started'
          AND json_extract(details_json, '$.session_id') = ?
        ORDER BY created_at ASC, rowid ASC
        LIMIT 1
        """,
        (project_id, task_id, session_id),
    ).fetchone()
    if row is None:
        return {}
    return _load_json(row["details_json"])


def _issue_run_console(connection, project_paths, project_id, task_id, runs):
    if not runs:
        return None
    active_run = next((run for run in runs if run["status"] == "active"), None)
    focus_run = active_run or runs[0]
    session_id = focus_run["session_id"]
    envelope_root = project_paths.runtime_envelope_root(project_id, session_id)
    output_preview = _tail_console_preview(os.path.join(envelope_root, "runtime-output.txt"))
    stdout_preview = _tail_console_preview(os.path.join(envelope_root, "stdout.log"))
    stderr_preview = _tail_console_preview(os.path.join(envelope_root, "stderr.log"))
    activity = _session_activity(connection, project_id, task_id, session_id)
    start_details = _session_start_details(connection, project_id, task_id, session_id)
    return {
        "session_id": session_id,
        "agent_id": focus_run["agent_id"],
        "agent_name": focus_run["agent_name"],
        "provider_type": focus_run["provider_type"],
        "status": focus_run["status"],
        "progress_pct": focus_run["progress_pct"],
        "status_message": focus_run["status_message"],
        "last_heartbeat_at": focus_run["last_heartbeat_at"],
        "started_at": focus_run["started_at"],
        "ended_at": focus_run["ended_at"],
        "is_live": focus_run["status"] == "active",
        "timeout_seconds": start_details.get("timeout_seconds"),
        "command": start_details.get("command"),
        "runtime_root": start_details.get("runtime_root") or envelope_root,
        "output_preview": output_preview,
        "stdout_preview": stdout_preview,
        "stderr_preview": stderr_preview,
        "activity": activity,
    }


def _agent_owned_issues(connection, project_id, agent_id, issue_keys):
    rows = connection.execute(
        """
        SELECT
            tasks.task_id,
            tasks.title,
            tasks.status,
            tasks.priority,
            tasks.review_state,
            tasks.progress_pct,
            tasks.created_at,
            goals.goal_id,
            goals.title AS goal_title
        FROM tasks
        LEFT JOIN goals ON goals.goal_id = tasks.goal_id
        WHERE tasks.project_id = ?
          AND tasks.assigned_agent_id = ?
        ORDER BY
            CASE tasks.status
                WHEN 'in_progress' THEN 0
                WHEN 'review' THEN 1
                WHEN 'blocked' THEN 2
                WHEN 'assigned' THEN 3
                WHEN 'ready' THEN 4
                WHEN 'planned' THEN 5
                WHEN 'done' THEN 6
                ELSE 7
            END,
            tasks.priority DESC,
            tasks.created_at ASC
        LIMIT 20
        """,
        (project_id, agent_id),
    ).fetchall()
    return [
        {
            "task_id": row["task_id"],
            "issue_key": issue_keys.get(row["task_id"]),
            "title": row["title"],
            "status": row["status"],
            "priority": row["priority"],
            "review_state": row["review_state"],
            "progress_pct": row["progress_pct"],
            "created_at": row["created_at"],
            "goal_id": row["goal_id"],
            "goal_title": row["goal_title"],
        }
        for row in rows
    ]


def _agent_runs(connection, project_id, agent_id):
    rows = connection.execute(
        """
        SELECT
            sessions.session_id,
            sessions.task_id,
            sessions.provider_type,
            sessions.status,
            sessions.progress_pct,
            sessions.status_message,
            sessions.last_heartbeat_at,
            sessions.started_at,
            sessions.ended_at,
            tasks.title AS task_title
        FROM sessions
        LEFT JOIN tasks ON tasks.task_id = sessions.task_id
        WHERE sessions.project_id = ?
          AND sessions.agent_id = ?
        ORDER BY sessions.started_at DESC, sessions.rowid DESC
        LIMIT 12
        """,
        (project_id, agent_id),
    ).fetchall()
    return [dict(row) for row in rows]


def fetch_agent_detail(connection, project_id, agent_id):
    agent_row = connection.execute(
        """
        SELECT
            agents.agent_id,
            agents.project_id,
            agents.role,
            agents.display_name,
            agents.status,
            agents.current_task_id,
            agents.last_heartbeat_at,
            tasks.title AS current_task_title
        FROM agents
        LEFT JOIN tasks ON tasks.task_id = agents.current_task_id
        WHERE agents.project_id = ?
          AND agents.agent_id = ?
        """,
        (project_id, agent_id),
    ).fetchone()
    if agent_row is None:
        return None

    issue_keys = issue_key_lookup(connection, project_id)
    history = fetch_incident_timeline(connection, project_id=project_id, agent_id=agent_id, limit=30, order="desc")["events"]

    return {
        "agent": {
            "agent_id": agent_row["agent_id"],
            "role": agent_row["role"],
            "display_name": agent_row["display_name"],
            "status": agent_row["status"],
            "current_task_id": agent_row["current_task_id"],
            "current_task_title": agent_row["current_task_title"],
            "current_issue_key": issue_keys.get(agent_row["current_task_id"]) if agent_row["current_task_id"] else None,
            "last_heartbeat_at": agent_row["last_heartbeat_at"],
        },
        "owned_issues": _agent_owned_issues(connection, project_id, agent_id, issue_keys),
        "runs": _agent_runs(connection, project_id, agent_id),
        "history": history,
    }


def fetch_issue_detail(connection, project_paths, project_id, task_id):
    issue_keys = issue_key_lookup(connection, project_id)
    task_row = connection.execute(
        """
        SELECT
            tasks.task_id,
            tasks.project_id,
            tasks.goal_id,
            tasks.title,
            tasks.description,
            tasks.status,
            tasks.priority,
            tasks.review_state,
            tasks.progress_pct,
            tasks.retry_count,
            tasks.auto_retry_limit,
            tasks.last_retry_at,
            tasks.last_retry_reason,
            tasks.next_retry_at,
            tasks.next_retry_reason,
            tasks.last_heartbeat_at,
            tasks.created_at,
            tasks.updated_at,
            goals.title AS goal_title,
            tasks.assigned_agent_id AS agent_id,
            agents.display_name AS agent_name,
            agents.status AS agent_status
        FROM tasks
        LEFT JOIN goals ON goals.goal_id = tasks.goal_id
        LEFT JOIN agents ON agents.agent_id = tasks.assigned_agent_id
        WHERE tasks.project_id = ?
          AND tasks.task_id = ?
        """,
        (project_id, task_id),
    ).fetchone()
    if task_row is None:
        return None

    relationships = _task_relationships(connection, project_id, task_id, task_row["goal_id"], issue_keys)
    runs = _task_runs(connection, project_id, task_id)
    run_console = _issue_run_console(connection, project_paths, project_id, task_id, runs)
    history = fetch_incident_timeline(connection, project_id=project_id, task_id=task_id, limit=30, order="desc")["events"]
    verification_runs = fetch_verification_runs(connection, project_id=project_id, task_id=task_id, limit=10)
    git_workspace = fetch_task_git_workspace(connection, task_id)
    artifact_payload = fetch_artifacts(
        connection,
        project_paths,
        limit=10,
        offset=0,
        filters={"task_id": task_id},
        project_id=project_id,
    )

    return {
        "task": {
            "task_id": task_row["task_id"],
            "issue_key": issue_keys.get(task_row["task_id"]),
            "title": task_row["title"],
            "description": task_row["description"],
            "status": task_row["status"],
            "priority": task_row["priority"],
            "review_state": task_row["review_state"],
            "progress_pct": task_row["progress_pct"],
            "retry_count": task_row["retry_count"],
            "auto_retry_limit": task_row["auto_retry_limit"],
            "last_retry_at": task_row["last_retry_at"],
            "last_retry_reason": task_row["last_retry_reason"],
            "next_retry_at": task_row["next_retry_at"],
            "next_retry_reason": task_row["next_retry_reason"],
            "last_heartbeat_at": task_row["last_heartbeat_at"],
            "created_at": task_row["created_at"],
            "updated_at": task_row["updated_at"],
            "goal_id": task_row["goal_id"],
            "goal_title": task_row["goal_title"],
            "agent_id": task_row["agent_id"],
            "agent_name": task_row["agent_name"],
            "agent_status": task_row["agent_status"],
        },
        "relationships": relationships,
        "runs": runs,
        "run_console": run_console,
        "history": history,
        "artifacts": artifact_payload["items"],
        "artifact_summary": artifact_payload["summary"],
        "verification_runs": verification_runs,
        "git_workspace": git_workspace,
    }
