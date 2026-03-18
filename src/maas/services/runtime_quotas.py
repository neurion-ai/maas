"""Project-level runtime quota policy and enforcement."""

import json

from maas.ids import generate_id
from maas.services.projects import resolve_project, resolve_project_id
from maas.services.security import ensure_board_action_allowed


DEFAULT_RUNTIME_QUOTAS = {
    "daily_run_limit": 0,
    "daily_live_run_limit": 0,
    "daily_runtime_seconds_limit": 0,
    "max_task_session_attempts": 0,
}


def _load_project_config(raw_config):
    try:
        config = json.loads(raw_config or "{}")
    except ValueError:
        return {}
    return config if isinstance(config, dict) else {}


def _normalize_int(value, field_name, minimum=0):
    if isinstance(value, bool):
        raise ValueError("{0} must be an integer.".format(field_name))
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        raise ValueError("{0} must be an integer.".format(field_name))
    if normalized < minimum:
        raise ValueError("{0} must be at least {1}.".format(field_name, minimum))
    return normalized


def default_runtime_quotas():
    return dict(DEFAULT_RUNTIME_QUOTAS)


def normalize_runtime_quotas(policy=None):
    requested = policy or {}
    return {
        "daily_run_limit": _normalize_int(
            requested.get("daily_run_limit", DEFAULT_RUNTIME_QUOTAS["daily_run_limit"]),
            "daily_run_limit",
        ),
        "daily_live_run_limit": _normalize_int(
            requested.get("daily_live_run_limit", DEFAULT_RUNTIME_QUOTAS["daily_live_run_limit"]),
            "daily_live_run_limit",
        ),
        "daily_runtime_seconds_limit": _normalize_int(
            requested.get("daily_runtime_seconds_limit", DEFAULT_RUNTIME_QUOTAS["daily_runtime_seconds_limit"]),
            "daily_runtime_seconds_limit",
        ),
        "max_task_session_attempts": _normalize_int(
            requested.get("max_task_session_attempts", DEFAULT_RUNTIME_QUOTAS["max_task_session_attempts"]),
            "max_task_session_attempts",
        ),
    }


def runtime_quotas_from_row(project_row):
    if project_row is None:
        return default_runtime_quotas()
    config = _load_project_config(project_row["config_json"])
    return normalize_runtime_quotas(config.get("runtime_quotas") or {})


def fetch_project_runtime_quotas(connection, project_id=None):
    project_row = resolve_project(connection, project_id, include_archived=False)
    if project_row is None:
        raise ValueError("project not found")
    return runtime_quotas_from_row(project_row)


def update_project_runtime_quotas(connection, project_id, actor_id, policy):
    resolved_project_id = resolve_project_id(connection, project_id, include_archived=False)
    if resolved_project_id is None:
        raise ValueError("project not found")
    ensure_board_action_allowed(
        connection,
        actor_id,
        resolved_project_id,
        "configure_runtime_quotas",
        "project",
        resolved_project_id,
    )
    normalized = normalize_runtime_quotas(policy)
    connection.execute(
        """
        UPDATE projects
        SET config_json = json_set(
                json_set(
                    json_set(
                        json_set(
                            CASE
                                WHEN json_valid(config_json) THEN config_json
                                ELSE '{}'
                            END,
                            '$.runtime_quotas.daily_run_limit',
                            ?
                        ),
                        '$.runtime_quotas.daily_live_run_limit',
                        ?
                    ),
                    '$.runtime_quotas.daily_runtime_seconds_limit',
                    ?
                ),
                '$.runtime_quotas.max_task_session_attempts',
                ?
            ),
            updated_at = CURRENT_TIMESTAMP
        WHERE project_id = ?
        """,
        (
            normalized["daily_run_limit"],
            normalized["daily_live_run_limit"],
            normalized["daily_runtime_seconds_limit"],
            normalized["max_task_session_attempts"],
            resolved_project_id,
        ),
    )
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, 'configure_runtime_quotas', 'project', ?, ?)
        """,
        (
            generate_id("audit"),
            resolved_project_id,
            actor_id,
            resolved_project_id,
            json.dumps(normalized),
        ),
    )
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, action, category, description, details_json, severity
        ) VALUES (?, ?, 'runtime_quotas_updated', 'projects', ?, ?, 'info')
        """,
        (
            generate_id("act"),
            resolved_project_id,
            "Runtime quotas updated.",
            json.dumps(normalized),
        ),
    )
    connection.commit()
    return {"project_id": resolved_project_id, "runtime_quotas": normalized}


def _count_sessions_today(connection, project_id):
    row = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM sessions
        WHERE project_id = ?
          AND date(started_at) = date('now')
        """,
        (project_id,),
    ).fetchone()
    return row["count"] if row is not None else 0


def _count_live_runs_today(connection, project_id):
    row = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM activity_log
        WHERE project_id = ?
          AND action = 'provider_adapter_started'
          AND date(created_at) = date('now')
          AND COALESCE(json_extract(details_json, '$.execution_mode'), 'local_simulation') != 'local_simulation'
        """,
        (project_id,),
    ).fetchone()
    return row["count"] if row is not None else 0


def _sum_runtime_seconds_today(connection, project_id):
    row = connection.execute(
        """
        SELECT COALESCE(
            SUM(
                CASE
                    WHEN julianday(COALESCE(ended_at, CURRENT_TIMESTAMP)) > julianday(started_at)
                    THEN CAST((julianday(COALESCE(ended_at, CURRENT_TIMESTAMP)) - julianday(started_at)) * 86400 AS INTEGER)
                    ELSE 0
                END
            ),
            0
        ) AS total_seconds
        FROM sessions
        WHERE project_id = ?
          AND date(started_at) = date('now')
        """,
        (project_id,),
    ).fetchone()
    return row["total_seconds"] if row is not None else 0


def _count_task_session_attempts(connection, project_id, task_id):
    row = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM sessions
        WHERE project_id = ?
          AND task_id = ?
        """,
        (project_id, task_id),
    ).fetchone()
    return row["count"] if row is not None else 0


def runtime_quota_snapshot(connection, project_id, task_id=None):
    policy = fetch_project_runtime_quotas(connection, project_id)
    usage = {
        "runs_today": _count_sessions_today(connection, project_id),
        "live_runs_today": _count_live_runs_today(connection, project_id),
        "runtime_seconds_today": _sum_runtime_seconds_today(connection, project_id),
        "task_session_attempts": _count_task_session_attempts(connection, project_id, task_id) if task_id else None,
    }
    return {"policy": policy, "usage": usage}


def ensure_runtime_quotas_allow_provider_run(connection, project_id, task_id, execution_mode):
    snapshot = runtime_quota_snapshot(connection, project_id, task_id=task_id)
    policy = snapshot["policy"]
    usage = snapshot["usage"]
    if policy["daily_run_limit"] and usage["runs_today"] >= policy["daily_run_limit"]:
        raise ValueError("Daily provider run quota reached for this project.")
    if (
        execution_mode != "local_simulation"
        and policy["daily_live_run_limit"]
        and usage["live_runs_today"] >= policy["daily_live_run_limit"]
    ):
        raise ValueError("Daily live-provider quota reached for this project.")
    if (
        policy["daily_runtime_seconds_limit"]
        and usage["runtime_seconds_today"] >= policy["daily_runtime_seconds_limit"]
    ):
        raise ValueError("Daily runtime quota reached for this project.")
    if (
        task_id
        and policy["max_task_session_attempts"]
        and (usage["task_session_attempts"] or 0) >= policy["max_task_session_attempts"]
    ):
        raise ValueError("Task session-attempt quota reached for this task.")
    return snapshot
