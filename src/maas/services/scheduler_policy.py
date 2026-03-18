"""Project-level scheduling fairness and capacity policy."""

import json

from maas.ids import generate_id
from maas.services.projects import resolve_project, resolve_project_id
from maas.services.security import ensure_board_action_allowed


DEFAULT_FAIR_SHARE_WEIGHT = 1
DEFAULT_MAX_ACTIVE_SESSIONS = 2


def _load_project_config(raw_config):
    try:
        config = json.loads(raw_config or "{}")
    except ValueError:
        return {}
    return config if isinstance(config, dict) else {}


def _normalize_int(value, field_name, minimum=1):
    if isinstance(value, bool):
        raise ValueError("{0} must be an integer.".format(field_name))
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        raise ValueError("{0} must be an integer.".format(field_name))
    if normalized < minimum:
        raise ValueError("{0} must be at least {1}.".format(field_name, minimum))
    return normalized


def default_scheduler_policy():
    return {
        "fair_share_weight": DEFAULT_FAIR_SHARE_WEIGHT,
        "max_active_sessions": DEFAULT_MAX_ACTIVE_SESSIONS,
    }


def normalize_scheduler_policy(policy=None):
    requested = policy or {}
    return {
        "fair_share_weight": _normalize_int(
            requested.get("fair_share_weight", DEFAULT_FAIR_SHARE_WEIGHT),
            "fair_share_weight",
        ),
        "max_active_sessions": _normalize_int(
            requested.get("max_active_sessions", DEFAULT_MAX_ACTIVE_SESSIONS),
            "max_active_sessions",
        ),
    }


def scheduler_policy_from_row(project_row):
    if project_row is None:
        return default_scheduler_policy()
    config = _load_project_config(project_row["config_json"])
    scheduler = config.get("scheduler") or {}
    return normalize_scheduler_policy(
        {
            "fair_share_weight": scheduler.get("fair_share_weight", DEFAULT_FAIR_SHARE_WEIGHT),
            "max_active_sessions": scheduler.get("max_active_sessions", DEFAULT_MAX_ACTIVE_SESSIONS),
        }
    )


def fetch_project_scheduler_policy(connection, project_id=None):
    project_row = resolve_project(connection, project_id, include_archived=False)
    if project_row is None:
        raise ValueError("project not found")
    return scheduler_policy_from_row(project_row)


def update_project_scheduler_policy(connection, project_id, actor_id, policy):
    resolved_project_id = resolve_project_id(connection, project_id, include_archived=False)
    if resolved_project_id is None:
        raise ValueError("project not found")
    ensure_board_action_allowed(
        connection,
        actor_id,
        resolved_project_id,
        "configure_scheduler_policy",
        "project",
        resolved_project_id,
    )
    normalized_policy = normalize_scheduler_policy(policy)
    path_weight = "$.scheduler.fair_share_weight"
    path_sessions = "$.scheduler.max_active_sessions"
    connection.execute(
        """
        UPDATE projects
        SET config_json = json_set(
                json_set(
                    CASE
                        WHEN json_valid(config_json) THEN config_json
                        ELSE '{}'
                    END,
                    ?,
                    ?
                ),
                ?,
                ?
            ),
            updated_at = CURRENT_TIMESTAMP
        WHERE project_id = ?
        """,
        (
            path_weight,
            normalized_policy["fair_share_weight"],
            path_sessions,
            normalized_policy["max_active_sessions"],
            resolved_project_id,
        ),
    )
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, 'configure_scheduler_policy', 'project', ?, ?)
        """,
        (
            generate_id("audit"),
            resolved_project_id,
            actor_id,
            resolved_project_id,
            json.dumps(normalized_policy),
        ),
    )
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, action, category, description, details_json, severity
        ) VALUES (?, ?, 'scheduler_policy_updated', 'projects', ?, ?, 'info')
        """,
        (
            generate_id("act"),
            resolved_project_id,
            "Scheduler fairness and capacity policy updated.",
            json.dumps(normalized_policy),
        ),
    )
    connection.commit()
    return {"project_id": resolved_project_id, "scheduler_policy": normalized_policy}
