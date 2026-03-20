"""Project-level provider queue capacity policy."""

import json

from maas.config import DEFAULT_PROVIDER_SETTINGS
from maas.ids import generate_id
from maas.services.projects import resolve_project, resolve_project_id
from maas.services.security import ensure_board_action_allowed


DEFAULT_QUEUE_MODE = "running"
DEFAULT_MAX_RUNNING_JOBS = 2
QUEUE_MODES = {"running", "draining", "paused"}


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


def default_queue_capacity_policy():
    return {
        "queue_mode": DEFAULT_QUEUE_MODE,
        "max_running_jobs": DEFAULT_MAX_RUNNING_JOBS,
        "preferred_provider_id": "openai_codex",
    }


def normalize_queue_capacity_policy(policy=None):
    requested = policy or {}
    queue_mode = (requested.get("queue_mode") or DEFAULT_QUEUE_MODE).strip().lower()
    if queue_mode not in QUEUE_MODES:
        raise ValueError("queue_mode must be one of: draining, paused, running.")
    preferred_provider_id = requested.get("preferred_provider_id")
    if preferred_provider_id is None:
        normalized_provider_id = default_queue_capacity_policy()["preferred_provider_id"]
    elif not isinstance(preferred_provider_id, str):
        raise ValueError("preferred_provider_id must be a provider id string or null.")
    else:
        normalized_provider_id = preferred_provider_id.strip() or None
    if normalized_provider_id is not None and normalized_provider_id not in DEFAULT_PROVIDER_SETTINGS:
        raise ValueError("preferred_provider_id must reference a supported provider.")
    return {
        "queue_mode": queue_mode,
        "max_running_jobs": _normalize_int(
            requested.get("max_running_jobs", DEFAULT_MAX_RUNNING_JOBS),
            "max_running_jobs",
            minimum=0,
        ),
        "preferred_provider_id": normalized_provider_id,
    }


def queue_capacity_policy_from_row(project_row):
    if project_row is None:
        return default_queue_capacity_policy()
    config = _load_project_config(project_row["config_json"])
    raw_policy = config.get("provider_capacity") or {}
    return normalize_queue_capacity_policy(
        {
            "queue_mode": raw_policy.get("queue_mode", DEFAULT_QUEUE_MODE),
            "max_running_jobs": raw_policy.get("max_running_jobs", DEFAULT_MAX_RUNNING_JOBS),
            "preferred_provider_id": raw_policy.get("preferred_provider_id", default_queue_capacity_policy()["preferred_provider_id"]),
        }
    )


def fetch_project_queue_capacity_policy(connection, project_id=None):
    project_row = resolve_project(connection, project_id, include_archived=False)
    if project_row is None:
        raise ValueError("project not found")
    return queue_capacity_policy_from_row(project_row)


def update_project_queue_capacity_policy(connection, project_id, actor_id, policy):
    resolved_project_id = resolve_project_id(connection, project_id, include_archived=False)
    if resolved_project_id is None:
        raise ValueError("project not found")
    ensure_board_action_allowed(
        connection,
        actor_id,
        resolved_project_id,
        "configure_provider_capacity",
        "project",
        resolved_project_id,
    )
    normalized = normalize_queue_capacity_policy(policy)
    connection.execute(
        """
        UPDATE projects
        SET config_json = json_set(
                json_set(
                    json_set(
                        CASE
                            WHEN json_valid(config_json) THEN config_json
                            ELSE '{}'
                        END,
                        '$.provider_capacity.queue_mode',
                        ?
                    ),
                    '$.provider_capacity.max_running_jobs',
                    ?
                ),
                '$.provider_capacity.preferred_provider_id',
                ?
            ),
            updated_at = CURRENT_TIMESTAMP
        WHERE project_id = ?
        """,
        (
            normalized["queue_mode"],
            normalized["max_running_jobs"],
            normalized["preferred_provider_id"],
            resolved_project_id,
        ),
    )
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, 'configure_provider_capacity', 'project', ?, ?)
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
        ) VALUES (?, ?, 'provider_capacity_updated', 'projects', ?, ?, 'info')
        """,
        (
            generate_id("act"),
            resolved_project_id,
            "Provider queue capacity policy updated.",
            json.dumps(normalized),
        ),
    )
    connection.commit()
    return {"project_id": resolved_project_id, "provider_capacity": normalized}


def queue_capacity_snapshot(connection, project_id):
    project_row = resolve_project(connection, project_id, include_archived=True)
    if project_row is None:
        raise ValueError("project not found")
    policy = queue_capacity_policy_from_row(project_row)
    counts_row = connection.execute(
        """
        SELECT
            SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) AS queued_jobs,
            SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running_jobs
        FROM provider_job_queue
        WHERE project_id = ?
        """,
        (project_id,),
    ).fetchone()
    queued_jobs = counts_row["queued_jobs"] or 0
    running_jobs = counts_row["running_jobs"] or 0
    can_start_queued = policy["queue_mode"] in {"running", "draining"} and running_jobs < policy["max_running_jobs"]
    can_launch_new = policy["queue_mode"] == "running" and running_jobs < policy["max_running_jobs"]
    return {
        **policy,
        "queued_jobs": queued_jobs,
        "running_jobs": running_jobs,
        "at_capacity": running_jobs >= policy["max_running_jobs"],
        "can_start_jobs": can_start_queued,
        "can_launch_jobs": can_launch_new,
    }


def can_start_provider_jobs(connection, project_id, include_draining=True):
    snapshot = queue_capacity_snapshot(connection, project_id)
    if snapshot["queue_mode"] == "paused":
        return False, snapshot
    if snapshot["queue_mode"] == "draining" and not include_draining:
        return False, snapshot
    if snapshot["running_jobs"] >= snapshot["max_running_jobs"]:
        return False, snapshot
    return True, snapshot
