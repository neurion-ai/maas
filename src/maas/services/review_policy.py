"""Project review policy and low-risk auto-advance helpers."""

import json

from maas.services.bootstrap import BROWNFIELD_REVIEW_TASK_TITLE
from maas.ids import generate_id
from maas.services.projects import resolve_project, resolve_project_id
from maas.services.security import ensure_board_action_allowed


def default_review_policy():
    return {
        "auto_approve_low_risk": True,
        "max_priority_for_auto_approve": 69,
        "require_verification_pass": True,
    }


def normalize_review_policy(policy=None):
    requested = policy or {}
    defaults = default_review_policy()

    auto_approve_low_risk = requested.get("auto_approve_low_risk", defaults["auto_approve_low_risk"])
    max_priority_for_auto_approve = requested.get(
        "max_priority_for_auto_approve",
        defaults["max_priority_for_auto_approve"],
    )
    require_verification_pass = requested.get("require_verification_pass", defaults["require_verification_pass"])

    if not isinstance(auto_approve_low_risk, bool):
        raise ValueError("auto_approve_low_risk must be a boolean")
    if isinstance(max_priority_for_auto_approve, bool) or not isinstance(max_priority_for_auto_approve, int):
        raise ValueError("max_priority_for_auto_approve must be an integer")
    if max_priority_for_auto_approve < 0:
        raise ValueError("max_priority_for_auto_approve must be zero or greater")
    if not isinstance(require_verification_pass, bool):
        raise ValueError("require_verification_pass must be a boolean")

    return {
        "auto_approve_low_risk": auto_approve_low_risk,
        "max_priority_for_auto_approve": max_priority_for_auto_approve,
        "require_verification_pass": require_verification_pass,
    }


def review_policy_from_row(project_row):
    defaults = default_review_policy()
    if project_row is None:
        return defaults
    try:
        config = json.loads(project_row["config_json"] or "{}")
    except (TypeError, ValueError):
        return defaults
    if not isinstance(config, dict):
        return defaults
    raw_policy = config.get("review_policy") or {}
    return normalize_review_policy(raw_policy)


def fetch_project_review_policy(connection, project_id):
    project_row = resolve_project(connection, project_id, include_archived=False)
    if project_row is None:
        raise ValueError("project not found")
    return review_policy_from_row(project_row)


def update_project_review_policy(connection, actor_id, updates, project_id=None):
    resolved_project_id = resolve_project_id(connection, project_id, include_archived=False)
    if resolved_project_id is None:
        raise ValueError("project not found")
    ensure_board_action_allowed(
        connection,
        actor_id,
        resolved_project_id,
        "configure_review_policy",
        "project",
        resolved_project_id,
    )
    project_row = connection.execute(
        "SELECT project_id, config_json FROM projects WHERE project_id = ?",
        (resolved_project_id,),
    ).fetchone()

    try:
        config = json.loads(project_row["config_json"] or "{}")
    except (TypeError, ValueError):
        config = {}
    if not isinstance(config, dict):
        config = {}

    current = normalize_review_policy(config.get("review_policy") or {})
    merged = normalize_review_policy({**current, **(updates or {})})
    config["review_policy"] = merged

    connection.execute(
        "UPDATE projects SET config_json = ?, updated_at = CURRENT_TIMESTAMP WHERE project_id = ?",
        (json.dumps(config), resolved_project_id),
    )
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, 'configure_review_policy', 'project', ?, ?)
        """,
        (
            generate_id("audit"),
            resolved_project_id,
            actor_id,
            resolved_project_id,
            json.dumps(merged),
        ),
    )
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, action, category, description, details_json, severity
        ) VALUES (?, ?, 'review_policy_updated', 'projects', ?, ?, 'info')
        """,
        (
            generate_id("act"),
            resolved_project_id,
            "Updated review policy for the project.",
            json.dumps(merged),
        ),
    )
    connection.commit()
    return {"project_id": resolved_project_id, "review_policy": merged}


def _load_project_config(connection, project_id):
    project_row = connection.execute(
        "SELECT config_json FROM projects WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    if project_row is None:
        return {}
    try:
        config = json.loads(project_row["config_json"] or "{}")
    except (TypeError, ValueError):
        return {}
    return config if isinstance(config, dict) else {}


def _is_brownfield_onboarding_review_task(connection, task_row):
    config = _load_project_config(connection, task_row["project_id"])
    onboarding = config.get("onboarding") or {}
    return onboarding.get("mode") == "brownfield" and task_row["title"] == BROWNFIELD_REVIEW_TASK_TITLE


def should_auto_approve_after_verification(connection, task_row, verification_runs, project_policy):
    if task_row is None:
        return False, "Task not found."
    if task_row["status"] != "review":
        return False, "Task is not waiting in review."
    if not project_policy.get("auto_approve_low_risk", False):
        return False, "Auto-approve is disabled."
    if task_row["priority"] > project_policy["max_priority_for_auto_approve"]:
        return False, "Priority is above the auto-approve threshold."
    if _is_brownfield_onboarding_review_task(connection, task_row):
        return False, "Brownfield onboarding reviews must stay manual."
    if project_policy.get("require_verification_pass", True):
        if not verification_runs:
            return False, "No verification evidence was recorded."
        if any(run.get("status") != "passed" for run in verification_runs):
            return False, "One or more verification runs did not pass."
    return True, "Low-risk verified work can auto-advance."
