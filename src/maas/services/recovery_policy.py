"""Helpers for project-level recovery and retry policy."""

import json


DEFAULT_RECOVERY_POLICY = {
    "auto_retry_timeout_sessions": False,
    "max_timed_out_retries": 1,
}


def fetch_project_recovery_policy(connection, project_id):
    row = connection.execute(
        """
        SELECT config_json
        FROM projects
        WHERE project_id = ?
        """,
        (project_id,),
    ).fetchone()
    if row is None:
        return dict(DEFAULT_RECOVERY_POLICY)

    try:
        config = json.loads(row["config_json"] or "{}")
    except json.JSONDecodeError:
        config = {}

    recovery = config.get("recovery") or {}
    return {
        "auto_retry_timeout_sessions": bool(
            recovery.get("auto_retry_timeout_sessions", DEFAULT_RECOVERY_POLICY["auto_retry_timeout_sessions"])
        ),
        "max_timed_out_retries": int(
            recovery.get("max_timed_out_retries", DEFAULT_RECOVERY_POLICY["max_timed_out_retries"])
        ),
    }


def task_timed_out_retry_limit(task_row, project_policy):
    if task_row["auto_retry_limit"] is not None:
        return int(task_row["auto_retry_limit"])
    return int(project_policy["max_timed_out_retries"])
