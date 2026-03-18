"""Project-level risk routing policy for sensitive steering actions."""

import json

from maas.ids import generate_id
from maas.services.projects import resolve_project, resolve_project_id
from maas.services.security import ensure_board_action_allowed


DEFAULT_PRIORITY_THRESHOLD = 101


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


def _normalize_prefix(value):
    if not isinstance(value, str):
        raise ValueError("sensitive_path_prefixes entries must be strings.")
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.strip("/")
    if not normalized:
        raise ValueError("sensitive_path_prefixes entries cannot be empty.")
    return normalized


def default_risk_policy():
    return {
        "priority_threshold": DEFAULT_PRIORITY_THRESHOLD,
        "sensitive_path_prefixes": [],
    }


def normalize_risk_policy(policy=None):
    requested = policy or {}
    prefixes = []
    seen = set()
    for item in requested.get("sensitive_path_prefixes") or []:
        normalized = _normalize_prefix(item)
        if normalized in seen:
            continue
        seen.add(normalized)
        prefixes.append(normalized)
    return {
        "priority_threshold": _normalize_int(
            requested.get("priority_threshold", DEFAULT_PRIORITY_THRESHOLD),
            "priority_threshold",
        ),
        "sensitive_path_prefixes": prefixes,
    }


def risk_policy_from_row(project_row):
    if project_row is None:
        return default_risk_policy()
    config = _load_project_config(project_row["config_json"])
    return normalize_risk_policy(config.get("risk_policy") or {})


def fetch_project_risk_policy(connection, project_id=None):
    project_row = resolve_project(connection, project_id, include_archived=False)
    if project_row is None:
        raise ValueError("project not found")
    return risk_policy_from_row(project_row)


def update_project_risk_policy(connection, project_id, actor_id, policy):
    resolved_project_id = resolve_project_id(connection, project_id, include_archived=False)
    if resolved_project_id is None:
        raise ValueError("project not found")
    ensure_board_action_allowed(
        connection,
        actor_id,
        resolved_project_id,
        "configure_risk_policy",
        "project",
        resolved_project_id,
    )
    normalized_policy = normalize_risk_policy(policy)
    connection.execute(
        """
        UPDATE projects
        SET config_json = json_set(
                json_set(
                    CASE
                        WHEN json_valid(config_json) THEN config_json
                        ELSE '{}'
                    END,
                    '$.risk_policy.priority_threshold',
                    ?
                ),
                '$.risk_policy.sensitive_path_prefixes',
                json(?)
            ),
            updated_at = CURRENT_TIMESTAMP
        WHERE project_id = ?
        """,
        (
            normalized_policy["priority_threshold"],
            json.dumps(normalized_policy["sensitive_path_prefixes"]),
            resolved_project_id,
        ),
    )
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, 'configure_risk_policy', 'project', ?, ?)
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
        ) VALUES (?, ?, 'risk_policy_updated', 'projects', ?, ?, 'info')
        """,
        (
            generate_id("act"),
            resolved_project_id,
            "Risk routing policy updated.",
            json.dumps(normalized_policy),
        ),
    )
    connection.commit()
    return {"project_id": resolved_project_id, "risk_policy": normalized_policy}


def _task_scoped_paths(task_row):
    try:
        criteria = json.loads(task_row["acceptance_criteria_json"] or "[]")
    except ValueError:
        return []
    paths = []
    for criterion in criteria:
        if not isinstance(criterion, dict) or criterion.get("type") != "source_path_exists":
            continue
        for path in criterion.get("paths") or []:
            if isinstance(path, str):
                normalized = path.strip().replace("\\", "/").lstrip("./")
                if normalized and normalized not in paths:
                    paths.append(normalized)
    return paths


def _task_changed_files(connection, task_id):
    row = connection.execute(
        """
        SELECT artifacts.metadata_json
        FROM task_git_workspaces
        LEFT JOIN artifacts ON artifacts.artifact_id = task_git_workspaces.last_diff_artifact_id
        WHERE task_git_workspaces.task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if row is None:
        return []
    try:
        metadata = json.loads(row["metadata_json"] or "{}")
    except ValueError:
        return []
    changed_files = []
    for path in metadata.get("changed_files") or []:
        if isinstance(path, str):
            normalized = path.strip().replace("\\", "/").lstrip("./")
            if normalized and normalized not in changed_files:
                changed_files.append(normalized)
    return changed_files


def _matches_sensitive_prefix(path, prefix):
    return path == prefix or path.startswith(prefix + "/")


def evaluate_task_action_risk(connection, task_row, policy=None):
    policy = normalize_risk_policy(policy)
    reasons = []
    matched_paths = []
    scoped_paths = _task_scoped_paths(task_row)
    changed_files = _task_changed_files(connection, task_row["task_id"])
    observed_paths = scoped_paths + [path for path in changed_files if path not in scoped_paths]
    if task_row["priority"] >= policy["priority_threshold"]:
        reasons.append(
            {
                "code": "priority_threshold",
                "message": "Task priority {0} meets the approval threshold {1}.".format(
                    task_row["priority"],
                    policy["priority_threshold"],
                ),
            }
        )
    for path in observed_paths:
        if any(_matches_sensitive_prefix(path, prefix) for prefix in policy["sensitive_path_prefixes"]):
            matched_paths.append(path)
    if matched_paths:
        reasons.append(
            {
                "code": "sensitive_paths",
                "message": "Task scope touches sensitive paths: {0}.".format(", ".join(matched_paths[:5])),
            }
        )
    return {
        "requires_approval": bool(reasons),
        "priority_threshold": policy["priority_threshold"],
        "priority": task_row["priority"],
        "sensitive_path_prefixes": policy["sensitive_path_prefixes"],
        "scoped_paths": scoped_paths,
        "changed_files": changed_files,
        "matched_paths": matched_paths,
        "reasons": reasons,
    }


def evaluate_agent_action_risk(connection, agent_row, policy=None):
    policy = normalize_risk_policy(policy)
    if not agent_row["current_task_id"]:
        return {
            "requires_approval": False,
            "priority_threshold": policy["priority_threshold"],
            "priority": None,
            "sensitive_path_prefixes": policy["sensitive_path_prefixes"],
            "scoped_paths": [],
            "changed_files": [],
            "matched_paths": [],
            "reasons": [],
        }
    task_row = connection.execute(
        """
        SELECT task_id, project_id, title, priority, acceptance_criteria_json
        FROM tasks
        WHERE task_id = ?
        """,
        (agent_row["current_task_id"],),
    ).fetchone()
    if task_row is None:
        return {
            "requires_approval": False,
            "priority_threshold": policy["priority_threshold"],
            "priority": None,
            "sensitive_path_prefixes": policy["sensitive_path_prefixes"],
            "scoped_paths": [],
            "changed_files": [],
            "matched_paths": [],
            "reasons": [],
        }
    risk = evaluate_task_action_risk(connection, task_row, policy=policy)
    risk["task_id"] = task_row["task_id"]
    risk["task_title"] = task_row["title"]
    return risk


def _find_open_risk_escalation(connection, project_id, action_type, resource_type, resource_id, payload):
    if action_type == "reassign_task":
        target_agent_id = (payload or {}).get("agent_id")
        return connection.execute(
            """
            SELECT escalation_id
            FROM escalation_queue
            WHERE project_id = ?
              AND action_type = ?
              AND resource_type = ?
              AND resource_id = ?
              AND status = 'open'
              AND json_extract(payload_json, '$.agent_id') = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (project_id, action_type, resource_type, resource_id, target_agent_id),
        ).fetchone()
    return connection.execute(
        """
        SELECT escalation_id
        FROM escalation_queue
        WHERE project_id = ?
          AND action_type = ?
          AND resource_type = ?
          AND resource_id = ?
          AND status = 'open'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (project_id, action_type, resource_type, resource_id),
    ).fetchone()


def request_risk_escalation(connection, project_id, actor_id, action_type, resource_type, resource_id, risk, payload=None):
    existing = _find_open_risk_escalation(connection, project_id, action_type, resource_type, resource_id, payload or {})
    if existing is not None:
        return {
            "status": "escalated",
            "escalation_id": existing["escalation_id"],
            "existing": True,
            "risk": risk,
        }

    reason_parts = [item["message"] for item in risk.get("reasons") or []]
    reason = "Risk policy routed {0} for approval: {1}".format(
        action_type,
        " ".join(reason_parts) if reason_parts else "manual review required.",
    )
    from maas.services.escalations import request_escalation

    result = request_escalation(
        connection,
        project_id=project_id,
        actor_id=actor_id,
        action_type=action_type,
        resource_type=resource_type,
        resource_id=resource_id,
        reason=reason,
        payload=payload or {},
    )
    return {
        "status": "escalated",
        "escalation_id": result["escalation_id"],
        "existing": False,
        "risk": risk,
    }
