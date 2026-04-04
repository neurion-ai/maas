"""Canonical stop-state payloads shared across operator surfaces."""

from __future__ import annotations

from maas.services.operator_actions import dedupe_operator_actions


def build_stop_state(
    reason_key,
    summary,
    detail,
    *,
    severity="warning",
    autopilot_blocking=True,
    safe_auto_retry=False,
    recommended_action=None,
    operator_actions=None,
    operator_confirmation_required=False,
    repair_attempted=False,
    repair_result=None,
    resource_type=None,
    resource_id=None,
    bucket=None,
    subtype=None,
):
    return {
        "reason_key": reason_key,
        "summary": summary,
        "detail": detail,
        "severity": severity,
        "autopilot_blocking": bool(autopilot_blocking),
        "safe_auto_retry": bool(safe_auto_retry),
        "recommended_action": recommended_action,
        "operator_actions": dedupe_operator_actions(operator_actions or []),
        "operator_confirmation_required": bool(operator_confirmation_required),
        "repair_attempted": bool(repair_attempted),
        "repair_result": repair_result,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "bucket": bucket,
        "subtype": subtype,
    }


_INBOX_STOP_STATE_DEFAULTS = {
    ("review", "review_packet"): {
        "reason_key": "review_pending",
        "autopilot_blocking": True,
        "safe_auto_retry": False,
    },
    ("review", "review_requested"): {
        "reason_key": "review_pending",
        "autopilot_blocking": True,
        "safe_auto_retry": False,
    },
    ("review", "overdue_review"): {
        "reason_key": "review_pending",
        "autopilot_blocking": True,
        "safe_auto_retry": False,
    },
    ("stale_runs", "stale_run"): {
        "reason_key": "stale_run",
        "autopilot_blocking": True,
        "safe_auto_retry": False,
    },
    ("blocked_recovery", "recoverable_blocked_task"): {
        "reason_key": "recovery_required",
        "autopilot_blocking": True,
        "safe_auto_retry": False,
    },
    ("blocked_recovery", "needs_replan_task"): {
        "reason_key": "replan_required",
        "autopilot_blocking": True,
        "safe_auto_retry": False,
    },
    ("blocked_recovery", "circuit_breaker_task"): {
        "reason_key": "repeated_failure_suppressed",
        "autopilot_blocking": True,
        "safe_auto_retry": False,
    },
    ("blocked_recovery", "quarantine_entry"): {
        "reason_key": "quarantine_hold",
        "autopilot_blocking": True,
        "safe_auto_retry": False,
    },
    ("blocked_recovery", "repeated_failure_incident"): {
        "reason_key": "repeated_failure_suppressed",
        "autopilot_blocking": True,
        "safe_auto_retry": False,
    },
    ("blocked_recovery", "dead_letter_entry"): {
        "reason_key": "dead_letter_hold",
        "autopilot_blocking": True,
        "safe_auto_retry": False,
    },
    ("policy_conflicts", "autopilot_paused_queue"): {
        "reason_key": "launches_paused",
        "autopilot_blocking": True,
        "safe_auto_retry": True,
    },
    ("policy_conflicts", "autopilot_draining_queue"): {
        "reason_key": "launches_draining",
        "autopilot_blocking": True,
        "safe_auto_retry": True,
    },
    ("policy_conflicts", "autopilot_zero_capacity"): {
        "reason_key": "zero_launch_capacity",
        "autopilot_blocking": True,
        "safe_auto_retry": True,
    },
    ("policy_conflicts", "brownfield_review_pending"): {
        "reason_key": "brownfield_review_pending",
        "autopilot_blocking": True,
        "safe_auto_retry": False,
    },
    ("policy_conflicts", "brownfield_review_changes_requested"): {
        "reason_key": "brownfield_changes_requested",
        "autopilot_blocking": True,
        "safe_auto_retry": False,
    },
    ("notification_failures", "retry_ready"): {
        "reason_key": "notification_delivery_retry_ready",
        "autopilot_blocking": False,
        "safe_auto_retry": True,
    },
    ("notification_failures", "retry_scheduled"): {
        "reason_key": "notification_delivery_retry_scheduled",
        "autopilot_blocking": False,
        "safe_auto_retry": True,
    },
    ("notification_failures", "retry_exhausted"): {
        "reason_key": "notification_delivery_exhausted",
        "autopilot_blocking": False,
        "safe_auto_retry": False,
    },
}


def inbox_stop_state(item):
    bucket = item.get("bucket")
    subtype = item.get("subtype")
    defaults = _INBOX_STOP_STATE_DEFAULTS.get((bucket, subtype), {})
    return build_stop_state(
        defaults.get("reason_key", "{0}:{1}".format(bucket or "unknown", subtype or "unknown")),
        item.get("title") or "Operator attention required",
        item.get("summary") or item.get("recommended_action") or "Inspect the current stop condition.",
        severity=item.get("severity") or "warning",
        autopilot_blocking=defaults.get("autopilot_blocking", True),
        safe_auto_retry=defaults.get("safe_auto_retry", False),
        recommended_action=item.get("recommended_action"),
        operator_actions=item.get("operator_actions") or [],
        resource_type=item.get("resource_type"),
        resource_id=item.get("resource_id"),
        bucket=bucket,
        subtype=subtype,
    )


def run_stop_state(run):
    status = run.get("status")
    if run.get("is_stale"):
        return build_stop_state(
            "stale_run",
            run.get("task_title") or run.get("issue_key") or "Stale run detected",
            run.get("diagnostic_summary")
            or "The active session heartbeat is stale enough to assume execution needs manual inspection.",
            severity="critical",
            autopilot_blocking=True,
            safe_auto_retry=False,
            recommended_action=run.get("recommended_action"),
            resource_type="session",
            resource_id=run.get("session_id"),
        )
    if status in {"failed", "timed_out", "cancelled"}:
        return build_stop_state(
            "run_failed",
            run.get("task_title") or run.get("issue_key") or "Run failed",
            run.get("diagnostic_summary") or run.get("status_message") or "The linked run failed and needs inspection before retrying.",
            severity="critical",
            autopilot_blocking=True,
            safe_auto_retry=False,
            recommended_action=run.get("recommended_action"),
            resource_type="session",
            resource_id=run.get("session_id"),
        )
    return None


def stale_agent_stop_state(agent):
    return build_stop_state(
        "stale_agent",
        agent.get("display_name") or "Stale agent detected",
        agent.get("diagnostic_summary") or "The agent heartbeat is stale and needs inspection before trusting autonomous progress.",
        severity="critical",
        autopilot_blocking=True,
        safe_auto_retry=False,
        recommended_action=agent.get("recommended_action"),
        resource_type="agent",
        resource_id=agent.get("agent_id"),
    )


def issue_stop_state(task, recovery_playbook=None):
    recovery_playbook = recovery_playbook or {}
    status = task.get("status")
    review_state = task.get("review_state")
    if status == "review":
        return build_stop_state(
            "review_pending",
            recovery_playbook.get("title") or "Review decision required",
            recovery_playbook.get("detail") or recovery_playbook.get("summary") or "This issue is waiting on an operator review decision.",
            severity="warning",
            autopilot_blocking=True,
            safe_auto_retry=False,
            recommended_action=recovery_playbook.get("recommended_action"),
            resource_type="task",
            resource_id=task.get("task_id"),
        )
    if status == "blocked":
        if review_state in {"changes_requested", "paused_by_operator"}:
            return build_stop_state(
                "operator_hold",
                recovery_playbook.get("title") or "Issue is intentionally held",
                recovery_playbook.get("detail") or "This issue is paused behind an explicit operator decision.",
                severity="critical" if review_state == "changes_requested" else "warning",
                autopilot_blocking=True,
                safe_auto_retry=False,
                recommended_action=recovery_playbook.get("recommended_action"),
                resource_type="task",
                resource_id=task.get("task_id"),
            )
        if review_state in {"session_failed", "timed_out", "retry_budget_exhausted", "circuit_breaker_open"}:
            return build_stop_state(
                "recovery_required",
                recovery_playbook.get("title") or "Recovery required",
                recovery_playbook.get("detail") or "The latest execution path failed and needs recovery before the issue can continue.",
                severity="critical",
                autopilot_blocking=True,
                safe_auto_retry=False,
                recommended_action=recovery_playbook.get("recommended_action"),
                resource_type="task",
                resource_id=task.get("task_id"),
            )
        return build_stop_state(
            "dependency_blocked",
            recovery_playbook.get("title") or "Dependency block",
            recovery_playbook.get("detail") or "Upstream work or a policy gate is blocking this issue.",
            severity="warning",
            autopilot_blocking=True,
            safe_auto_retry=False,
            recommended_action=recovery_playbook.get("recommended_action"),
            resource_type="task",
            resource_id=task.get("task_id"),
        )
    return None
