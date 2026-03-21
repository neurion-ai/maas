"""Project review policy and low-risk auto-advance helpers."""

import json

from maas.services.bootstrap import BROWNFIELD_REVIEW_TASK_TITLE
from maas.ids import generate_id
from maas.services.projects import resolve_project, resolve_project_id
from maas.services.security import ensure_board_action_allowed


LOW_RISK_REVIEW_PACKET_FAMILY = "low_risk_verified"


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


def _review_reason(code, summary, detail, blocks_batch=True, blocks_auto=True):
    return {
        "code": code,
        "summary": summary,
        "detail": detail,
        "blocks_batch_review": blocks_batch,
        "blocks_auto_approve": blocks_auto,
    }


def _task_value(task_row, key, default=None):
    if task_row is None:
        return default
    try:
        return task_row[key]
    except (KeyError, IndexError, TypeError):
        if hasattr(task_row, "get"):
            return task_row.get(key, default)
        return default


def _review_packet_scope(task_row):
    goal_id = _task_value(task_row, "goal_id")
    if goal_id:
        return {
            "packet_scope": "goal",
            "packet_scope_id": goal_id,
            "packet_scope_label": _task_value(task_row, "goal_title") or "Shared goal",
        }
    review_state = _task_value(task_row, "review_state")
    if review_state:
        return {
            "packet_scope": "review_state",
            "packet_scope_id": review_state,
            "packet_scope_label": review_state.replace("_", " "),
        }
    return {
        "packet_scope": "project",
        "packet_scope_id": _task_value(task_row, "project_id", "project"),
        "packet_scope_label": "Project",
    }


def _grouped_review_packet(task_row, project_policy):
    auto_enabled = project_policy.get("auto_approve_low_risk", False)
    scope = _review_packet_scope(task_row or {})
    return {
        "packet_key": (
            "low_risk_verified_{mode}:{scope}:{scope_id}".format(
                mode="auto" if auto_enabled else "manual",
                scope=scope["packet_scope"],
                scope_id=scope["packet_scope_id"],
            )
        ),
        "family": LOW_RISK_REVIEW_PACKET_FAMILY,
        "title": "Low-risk verified review packet",
        "summary": (
            "Verified low-risk issues that qualify for automatic approval."
            if auto_enabled
            else "Verified low-risk issues that can be approved together from one review packet."
        ),
        "recommended_decision": "approve",
        **scope,
    }


def _decision_mode(batch_review_eligible, auto_approve_eligible):
    if auto_approve_eligible:
        return "auto_approve"
    if batch_review_eligible:
        return "batch_review"
    return "manual_review"


def evaluate_review_decision_state(connection, task_row, project_policy, verification_runs=None, failure_count=0, onboarding_mode=None):
    verification_runs = verification_runs or []
    verification_required = project_policy.get("require_verification_pass", True)
    verification_recorded = len(verification_runs)
    verification_passed = bool(verification_runs) and all(run.get("status") == "passed" for run in verification_runs)

    if task_row is None:
        return {
            "status": "unavailable",
            "batch_review_eligible": False,
            "auto_approve_eligible": False,
            "manual_review_required": True,
            "decision_mode": "manual_review",
            "summary": "Task not found.",
            "detail": "The review policy could not be evaluated because the task record is missing.",
            "why_not_batch_reviewed": "Task not found.",
            "why_not_auto_approved": "Task not found.",
            "reasons": [
                _review_reason(
                    "task_missing",
                    "Task not found.",
                    "The review policy could not be evaluated because the task record is missing.",
                )
            ],
            "grouped_review_packet": None,
            "verification": {
                "required": verification_required,
                "recorded_runs": verification_recorded,
                "passed": verification_passed,
            },
        }
    if task_row["status"] != "review":
        return {
            "status": "not_in_review",
            "batch_review_eligible": False,
            "auto_approve_eligible": False,
            "manual_review_required": False,
            "decision_mode": "manual_review",
            "summary": "This issue is not currently waiting in review.",
            "detail": "Review decisions only apply after Codex finishes a run and the issue moves into review.",
            "why_not_batch_reviewed": "This issue is not currently in review.",
            "why_not_auto_approved": "This issue is not currently in review.",
            "reasons": [
                _review_reason(
                    "not_in_review",
                    "This issue is not currently in review.",
                    "Review decisions only apply after Codex finishes a run and the issue moves into review.",
                )
            ],
            "grouped_review_packet": None,
            "verification": {
                "required": verification_required,
                "recorded_runs": verification_recorded,
                "passed": verification_passed,
            },
        }
    is_brownfield_onboarding_review = False
    if onboarding_mode == "brownfield" and task_row["title"] == BROWNFIELD_REVIEW_TASK_TITLE:
        is_brownfield_onboarding_review = True
    elif connection is not None and "project_id" in task_row.keys() and task_row["project_id"]:
        is_brownfield_onboarding_review = _is_brownfield_onboarding_review_task(connection, task_row)
    reasons = []
    if is_brownfield_onboarding_review:
        reasons.append(
            _review_reason(
                "brownfield_onboarding_manual",
                "Manual review is required.",
                "Brownfield onboarding reviews must stay manual so imported understanding is explicitly approved by an operator.",
            )
        )
    if task_row["priority"] > project_policy["max_priority_for_auto_approve"]:
        reasons.append(
            _review_reason(
                "priority_above_low_risk_threshold",
                "Manual review is required.",
                "Priority is above the low-risk review threshold for batch or automatic approval.",
            )
        )
    if failure_count:
        reasons.append(
            _review_reason(
                "failure_history_present",
                "Manual review is required.",
                "Issues with recorded failures stay manual even if Codex produced output.",
            )
        )
    if verification_required:
        if not verification_runs:
            reasons.append(
                _review_reason(
                    "verification_missing",
                    "Manual review is required.",
                    "No verification evidence was recorded, so the issue cannot be batch-decided or auto-approved.",
                )
            )
        elif not verification_passed:
            reasons.append(
                _review_reason(
                    "verification_failed",
                    "Manual review is required.",
                    "One or more verification runs did not pass.",
                )
            )

    batch_review_eligible = not any(reason["blocks_batch_review"] for reason in reasons)
    auto_approve_enabled = project_policy.get("auto_approve_low_risk", False)
    if batch_review_eligible and not auto_approve_enabled:
        reasons.append(
            _review_reason(
                "auto_approve_disabled_by_policy",
                "Auto-approval is disabled by project policy.",
                "This issue qualifies for the low-risk review packet, but project policy still requires a human or batch approval step.",
                blocks_batch=False,
                blocks_auto=True,
            )
        )

    auto_approve_eligible = batch_review_eligible and auto_approve_enabled
    grouped_review_packet = _grouped_review_packet(task_row, project_policy) if batch_review_eligible else None
    blocking_batch_reasons = [reason for reason in reasons if reason["blocks_batch_review"]]
    blocking_auto_reasons = [reason for reason in reasons if reason["blocks_auto_approve"]]
    decision_mode = _decision_mode(batch_review_eligible, auto_approve_eligible)

    if auto_approve_eligible:
        status = "low_risk_review"
        summary = "Low-risk verified work can auto-advance."
        detail = "Project policy would auto-approve this issue after verification."
    elif batch_review_eligible:
        status = "low_risk_review"
        summary = "Low-risk verified work can be batch-reviewed."
        detail = "Project policy keeps this issue manual, but it still meets the low-risk batch-review rules."
    else:
        status = "manual_required"
        primary_reason = blocking_batch_reasons[0] if blocking_batch_reasons else None
        summary = primary_reason["summary"] if primary_reason else "Manual review is required."
        detail = (
            primary_reason["detail"]
            if primary_reason
            else "This issue does not meet the current low-risk review rules."
        )

    return {
        "status": status,
        "decision_mode": decision_mode,
        "batch_review_eligible": batch_review_eligible,
        "auto_approve_eligible": auto_approve_eligible,
        "manual_review_required": not batch_review_eligible,
        "summary": summary,
        "detail": detail,
        "why_not_batch_reviewed": (
            None if batch_review_eligible else blocking_batch_reasons[0]["detail"]
        ),
        "why_not_auto_approved": (
            None if auto_approve_eligible else blocking_auto_reasons[0]["detail"]
        ),
        "reasons": reasons,
        "grouped_review_packet": grouped_review_packet,
        "verification": {
            "required": verification_required,
            "recorded_runs": verification_recorded,
            "passed": verification_passed,
        },
    }


def should_auto_approve_after_verification(connection, task_row, verification_runs, project_policy):
    state = evaluate_review_decision_state(
        connection,
        task_row,
        project_policy,
        verification_runs=verification_runs,
        failure_count=0,
    )
    if not project_policy.get("auto_approve_low_risk", False):
        return False, "Auto-approve is disabled."
    if not state["auto_approve_eligible"]:
        return False, state.get("why_not_auto_approved") or state["detail"]
    return True, state["summary"]
