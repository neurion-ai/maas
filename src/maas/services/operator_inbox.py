"""Operator inbox and control-loop read models built from backend signals."""

from datetime import datetime, timezone
import json

from maas.services.autopilot import fetch_autopilot_runtime, fetch_autopilot_status, fetch_project_autopilot_policy
from maas.services.board import fetch_issue_index
from maas.services.codex_mvp import fetch_system_diagnostics
from maas.services.notifications import (
    build_notification_digests,
    build_notification_outbox_summary,
    fetch_notification_outbox,
)
from maas.services.operator_actions import (
    dedupe_operator_actions,
    notification_operator_action,
    project_autopilot_action,
    project_launch_posture_action,
    project_notification_action,
)
from maas.services.projects import resolve_project
from maas.services.queue_capacity import queue_capacity_snapshot
from maas.services.recovery_policy import fetch_project_recovery_overview
from maas.services.repo_plan import _resolve_brownfield_review_status


def _load_project_config(raw_config):
    try:
        payload = json.loads(raw_config or "{}")
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _inbox_item(
    bucket,
    subtype,
    severity,
    title,
    summary,
    resource_type,
    resource_id,
    recommended_action,
    metadata=None,
    operator_actions=None,
):
    item = {
        "bucket": bucket,
        "subtype": subtype,
        "severity": severity,
        "title": title,
        "summary": summary,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "recommended_action": recommended_action,
        "metadata": metadata or {},
    }
    if operator_actions:
        item["operator_actions"] = dedupe_operator_actions(operator_actions)
    return item


def _review_items(issue_index):
    items = []
    review_queue = issue_index["queue"]["review"]
    batch_review = review_queue.get("batch_review") or {}
    packet_task_ids = set()
    for packet in batch_review.get("packets", []):
        eligible_task_ids = list(packet.get("eligible_task_ids") or [])
        packet_task_ids.update(eligible_task_ids)
        items.append(
            _inbox_item(
                "review",
                "review_packet",
                "warning",
                packet.get("title") or "Low-risk review packet",
                "{0} issue(s) can be reviewed together. {1}".format(
                    packet.get("eligible_count") or len(eligible_task_ids),
                    packet.get("summary") or "Batch review can clear repetitive low-risk work faster.",
                ),
                "review_packet",
                packet.get("packet_key"),
                "Open Issues and batch-approve the eligible packet if the evidence looks consistent.",
                metadata=dict(packet),
            )
        )
    for task in review_queue["items"]:
        review_age_value = task.get("review_age_hours")
        if review_age_value is None:
            review_age_value = task.get("age_hours")
        review_age_hours = float(review_age_value or 0)
        overdue = review_age_hours >= 1
        if task.get("batch_review_eligible") and task["task_id"] in packet_task_ids and not overdue and task.get("priority", 0) < 90:
            continue
        items.append(
            _inbox_item(
                "review",
                "overdue_review" if overdue else "review_requested",
                "critical" if overdue or task.get("priority", 0) >= 90 else "warning",
                task.get("title") or "Issue waiting for review",
                (
                    "This issue has been waiting in review for {0:.1f}h.".format(review_age_hours)
                    if overdue
                    else task.get("review_eligibility", {}).get("summary")
                    or "Codex completed work and this issue is waiting for an operator decision."
                ),
                "task",
                task["task_id"],
                (
                    "Batch approve from the low-risk packet."
                    if task.get("batch_review_eligible") and task["task_id"] in packet_task_ids
                    else "Inspect the issue and decide approve or request changes."
                ),
                metadata={
                    "project_id": task.get("project_id"),
                    "task_id": task["task_id"],
                    "issue_key": task.get("issue_key"),
                    "priority": task.get("priority"),
                    "review_state": task.get("review_state"),
                    "batch_review_eligible": task.get("batch_review_eligible"),
                    "decision_mode": task.get("review_eligibility", {}).get("decision_mode"),
                    "age_hours": review_age_hours,
                    "overdue": overdue,
                },
            )
        )
    return items


def _stale_run_items(system_diagnostics):
    items = []
    for run in system_diagnostics.get("suspect_runs", []):
        if not run.get("is_stale"):
            continue
        items.append(
            _inbox_item(
                "stale_runs",
                "stale_run",
                "critical",
                run.get("task_title") or "Stale run detected",
                run.get("diagnostic_summary")
                or "A run heartbeat is stale enough to assume the execution thread is stuck.",
                "session",
                run["session_id"],
                run.get("recommended_action") or "Inspect the run and recover the agent or task if progress has stopped.",
                metadata={
                    "project_id": run.get("project_id"),
                    "session_id": run["session_id"],
                    "task_id": run.get("task_id"),
                    "issue_key": run.get("issue_key"),
                    "agent_id": run.get("agent_id"),
                    "agent_name": run.get("agent_name"),
                    "status": run.get("status"),
                    "heartbeat_age_seconds": run.get("heartbeat_age_seconds"),
                    "provider_type": run.get("provider_type"),
                },
            )
        )
    return items


def _recovery_items(recovery_overview):
    items = []
    project_id = recovery_overview.get("project_id")
    task_lists = [
        ("recoverable_blocked_task", recovery_overview.get("recoverable_blocked_tasks", []), "Recover and requeue the task."),
        ("needs_replan_task", recovery_overview.get("needs_replan_tasks", []), "Replan the task before resuming autonomy."),
        ("circuit_breaker_task", recovery_overview.get("circuit_breaker_tasks", []), "Review the repeated failure trigger before reopening execution."),
        ("quarantine_entry", recovery_overview.get("open_quarantine_entries", []), "Inspect the quarantined artifacts before restoring or dismissing them."),
        (
            "repeated_failure_incident",
            recovery_overview.get("repeated_failure_incidents", []),
            "Resolve the repeated-failure incident before retrying the task again.",
        ),
    ]
    for subtype, entries, recommended_action in task_lists:
        for entry in entries:
            resource_type = "task" if entry.get("task_id") else "failure_incident"
            resource_id = entry.get("task_id") or entry.get("incident_id") or entry.get("failure_id")
            items.append(
                _inbox_item(
                    "blocked_recovery",
                    subtype,
                    "critical",
                    entry.get("title") or entry.get("task_title") or "Recovery attention required",
                    entry.get("recovery_summary")
                    or entry.get("summary")
                    or "This issue is blocked behind a recovery policy or failure-control decision.",
                    resource_type,
                    resource_id,
                    recommended_action,
                    metadata={"project_id": project_id, **dict(entry)},
                )
            )
    for entry in recovery_overview.get("dead_letter_entries", []):
        items.append(
            _inbox_item(
                "blocked_recovery",
                "dead_letter_entry",
                "critical",
                entry.get("task_title") or "Dead-letter entry waiting",
                "Automatic recovery exhausted its retry budget and the task was routed to the dead-letter queue.",
                "dead_letter_entry",
                entry.get("dlq_id"),
                "Choose recover, restore, or replan before the work can resume.",
                metadata={"project_id": project_id, **dict(entry)},
            )
        )
    return items


def _policy_conflict_items(connection, project_id):
    items = []
    autopilot_policy = fetch_project_autopilot_policy(connection, project_id)
    queue_snapshot = queue_capacity_snapshot(connection, project_id)
    project_row = resolve_project(connection, project_id, include_archived=False)
    config = _load_project_config(project_row["config_json"] if project_row else "{}")
    onboarding = config.get("onboarding") or {}
    review_task = None
    review_task_id = onboarding.get("review_task_id")
    if review_task_id:
        review_task = connection.execute(
            """
            SELECT task_id, status, review_state
            FROM tasks
            WHERE task_id = ?
            """,
            (review_task_id,),
        ).fetchone()
    onboarding_review_status = _resolve_brownfield_review_status(connection, project_id, onboarding, review_task=review_task)
    if autopilot_policy.get("enabled") and queue_snapshot.get("queue_mode") == "paused":
        items.append(
            _inbox_item(
                "policy_conflicts",
                "autopilot_paused_queue",
                "critical",
                "Autopilot is enabled while launches are paused",
                "The control loop can keep running, but newly assigned work will not launch until queue posture is resumed.",
                "project",
                project_id,
                "Either disable autopilot or resume launches so the project can make forward progress.",
                metadata={"project_id": project_id, "queue_mode": queue_snapshot.get("queue_mode"), "autopilot_enabled": True},
                operator_actions=[
                    project_launch_posture_action(
                        project_id,
                        "Resume launches",
                        "running",
                        max(1, int(queue_snapshot.get("max_running_jobs") or 1)),
                        preferred_provider_id=queue_snapshot.get("preferred_provider_id"),
                    ),
                    project_autopilot_action(project_id, "Disable autopilot", {**autopilot_policy, "enabled": False}),
                ],
            )
        )
    if autopilot_policy.get("enabled") and queue_snapshot.get("queue_mode") == "draining":
        items.append(
            _inbox_item(
                "policy_conflicts",
                "autopilot_draining_queue",
                "warning",
                "Autopilot is enabled while the queue is draining",
                "MAAS will finish queued work but will not auto-launch newly assigned tasks until posture returns to running.",
                "project",
                project_id,
                "Switch queue posture back to running when you want autopilot to launch fresh work again.",
                metadata={"project_id": project_id, "queue_mode": queue_snapshot.get("queue_mode"), "autopilot_enabled": True},
                operator_actions=[
                    project_launch_posture_action(
                        project_id,
                        "Resume launches",
                        "running",
                        max(1, int(queue_snapshot.get("max_running_jobs") or 1)),
                        preferred_provider_id=queue_snapshot.get("preferred_provider_id"),
                    )
                ],
            )
        )
    if autopilot_policy.get("enabled") and int(queue_snapshot.get("max_running_jobs") or 0) <= 0:
        items.append(
            _inbox_item(
                "policy_conflicts",
                "autopilot_zero_capacity",
                "critical",
                "Autopilot is enabled with zero launch capacity",
                "The control loop is allowed to run, but provider capacity is set to zero concurrent jobs.",
                "project",
                project_id,
                "Increase max running jobs or disable autopilot for this project.",
                metadata={"project_id": project_id, "max_running_jobs": queue_snapshot.get("max_running_jobs"), "autopilot_enabled": True},
                operator_actions=[
                    project_launch_posture_action(
                        project_id,
                        "Set capacity to 1 and resume launches",
                        "running",
                        1,
                        preferred_provider_id=queue_snapshot.get("preferred_provider_id"),
                    ),
                    project_autopilot_action(project_id, "Disable autopilot", {**autopilot_policy, "enabled": False}),
                ],
            )
        )
    if autopilot_policy.get("enabled") and onboarding.get("mode") == "brownfield" and onboarding_review_status in {"review_pending", "changes_requested"}:
        items.append(
            _inbox_item(
                "policy_conflicts",
                "brownfield_review_changes_requested"
                if onboarding_review_status == "changes_requested"
                else "brownfield_review_pending",
                "critical",
                "Brownfield onboarding review needs changes"
                if onboarding_review_status == "changes_requested"
                else "Brownfield onboarding review is still pending",
                (
                    "Autonomy is enabled, but imported understanding was sent back with changes requested."
                    if onboarding_review_status == "changes_requested"
                    else "Autonomy is enabled, but imported understanding still requires explicit operator approval."
                ),
                "project",
                project_id,
                (
                    "Reconfirm the brownfield import inputs, then approve the review before expecting wider autonomous execution."
                    if onboarding_review_status == "changes_requested"
                    else "Approve or adjust the brownfield onboarding review before expecting wider autonomous execution."
                ),
                metadata={
                    "project_id": project_id,
                    "review_status": onboarding_review_status,
                    "review_task_id": review_task_id,
                    "onboarding_mode": onboarding.get("mode"),
                },
            )
        )
    return items


def _notification_failure_items(connection, project_id):
    notifications = fetch_notification_outbox(connection, project_id=project_id, limit=100, include_archived=False)
    digests = build_notification_digests(notifications, limit=12)
    items = []
    for digest in digests["attention"]:
        if digest.get("delivery_state") == "retry_scheduled":
            continue
        event_severity = digest.get("severity") or "warning"
        severity = "critical" if digest.get("retry_budget_exhausted") or event_severity == "critical" else "warning"
        operator_actions = []
        notification_ids = [item for item in (digest.get("notification_ids") or []) if item]
        if digest.get("delivery_state") in {"retry_ready", "retry_exhausted"} and len(notification_ids) == 1:
            operator_actions.append(
                notification_operator_action(
                    "process_notification",
                    "Retry this delivery now",
                    notification_ids[0],
                )
            )
        items.append(
            _inbox_item(
                "notification_failures",
                digest.get("delivery_state"),
                severity,
                digest.get("title") or "Notification delivery needs attention",
                digest.get("last_error")
                or "Notification delivery is delayed or exhausted and needs operator review.",
                "notification_digest",
                digest.get("dedupe_key") or notification_ids[0] if notification_ids else digest.get("title"),
                (
                    "Inspect delivery policy and clear the failed endpoint before requeueing."
                    if digest.get("retry_budget_exhausted")
                    else "Inspect the failing webhook or wait for the scheduled retry window."
                ),
                metadata={"project_id": project_id, **digest},
                operator_actions=operator_actions,
            )
        )
    return items


def _tone_for_severity(severity):
    if severity == "critical":
        return "danger"
    if severity == "warning":
        return "warn"
    return "default"


def _workflow_item(item):
    resource_type = item.get("resource_type")
    resource_id = item.get("resource_id")
    target_view = "system"
    route = {
        "view": "system",
        "projectId": item.get("metadata", {}).get("project_id"),
    }
    if resource_type == "task":
        target_view = "issues"
        route = {
            "view": "issues",
            "taskId": resource_id,
            "projectId": item.get("metadata", {}).get("project_id"),
        }
    elif resource_type == "session":
        target_view = "runs"
        route = {
            "view": "runs",
            "sessionId": resource_id,
            "projectId": item.get("metadata", {}).get("project_id"),
        }
    elif resource_type in {"notification", "notification_digest", "project", "dead_letter_entry", "failure_incident", "review_packet"}:
        target_view = (
            "issues"
            if item.get("bucket") in {"review", "blocked_recovery"}
            else "command"
            if item.get("bucket") in {"policy_conflicts", "notification_failures"}
            else "system"
        )
        route = {
            "view": target_view,
            "resourceType": resource_type,
            "resourceId": resource_id,
            "projectId": item.get("metadata", {}).get("project_id"),
        }
        review_task_id = item.get("metadata", {}).get("review_task_id")
        if review_task_id:
            route["taskId"] = review_task_id
    label_map = {
        "review": "Review",
        "blocked_recovery": "Recover",
        "stale_runs": "Inspect run",
        "policy_conflicts": "Fix posture",
        "notification_failures": "Inspect delivery",
    }
    return {
        "id": "{0}:{1}:{2}".format(item.get("bucket"), item.get("subtype"), resource_id or item.get("title")),
        "bucket": item.get("bucket"),
        "tone": _tone_for_severity(item.get("severity")),
        "label": label_map.get(item.get("bucket"), "Inspect"),
        "title": item.get("title") or "Operator attention required",
        "detail": item.get("summary") or item.get("recommended_action") or "Inspect the current system state.",
        "recommendedAction": item.get("recommended_action"),
        "operatorActions": item.get("operator_actions") or [],
        "route": route,
    }


def _summarize_inbox(summary):
    review_count = summary["review"]
    recovery_count = summary["blocked_recovery"]
    suspect_run_count = summary["stale_runs"]
    failed_notification_count = summary["notification_failures"]
    policy_conflict_count = summary["policy_conflicts"]
    if recovery_count > 0:
        return {
            "headline": "{0} issue{1} need recovery or replanning".format(
                recovery_count,
                "" if recovery_count == 1 else "s",
            ),
            "detail": "Use Issues to recover blocked work first. The queue will not move until recovery pressure is cleared.",
            "recommendedView": "issues",
            "recommendedLabel": "Open Issues",
        }
    if review_count > 0:
        return {
            "headline": "{0} issue{1} waiting for review".format(
                review_count,
                "" if review_count == 1 else "s",
            ),
            "detail": "Use Issues for approval or change requests. Low-risk items can often be handled in grouped review.",
            "recommendedView": "issues",
            "recommendedLabel": "Review in Issues",
        }
    if suspect_run_count > 0:
        return {
            "headline": "{0} run{1} need live inspection".format(
                suspect_run_count,
                "" if suspect_run_count == 1 else "s",
            ),
            "detail": "Use Runs for stale or suspect sessions. Only intervene if the trace confirms the run is stuck.",
            "recommendedView": "runs",
            "recommendedLabel": "Open Runs",
        }
    if policy_conflict_count > 0:
        return {
            "headline": "{0} control-loop conflict{1} need attention".format(
                policy_conflict_count,
                "" if policy_conflict_count == 1 else "s",
            ),
            "detail": "Execution posture and project policy are disagreeing. Fix the posture before expecting autonomy to progress.",
            "recommendedView": "command",
            "recommendedLabel": "Open Command",
        }
    if failed_notification_count > 0:
        return {
            "headline": "{0} notification delivery{1} failed".format(
                failed_notification_count,
                "" if failed_notification_count == 1 else "ies",
            ),
            "detail": "Work can continue, but operator visibility is degraded until delivery failures are cleared or retried.",
            "recommendedView": "command",
            "recommendedLabel": "Open Command",
        }
    return {
        "headline": "Operator inbox is clear",
        "detail": "No review, recovery, stale-run, or notification pressure currently requires manual intervention.",
        "recommendedView": "command",
        "recommendedLabel": "Open Command",
    }


def _workflow_operator_actions(items, limit=3):
    collected = []
    for item in items or []:
        collected.extend(item.get("operatorActions") or [])
    return dedupe_operator_actions(collected)[:limit]


def _summarize_autopilot(project_id, policy, runtime, queue_snapshot, issue_index, notification_summary, why_idle=None, governance_gate=None):
    queue_mode = queue_snapshot.get("queue_mode") or "running"
    review_count = issue_index["summary"]["review"]
    recovery_count = issue_index["summary"]["blocked_failures"] + issue_index["summary"]["blocked_dependencies"]
    runtime_status = runtime.get("runtime_status") or runtime.get("status") or "idle"
    lease_active = bool(runtime.get("lease_active") or runtime.get("owns_lease") or runtime.get("running"))
    governance_gate = governance_gate or {}
    operator_actions = dedupe_operator_actions(
        [
            action
            for signal in (governance_gate.get("signals") or [])
            for action in (signal.get("operator_actions") or [])
        ]
    )
    facts = [
        "Loop {0}".format(runtime.get("loop_count") or 0),
        "Heartbeat {0}".format(runtime.get("last_heartbeat_at") or "never"),
        "{0} review".format(review_count),
        "{0} recovery".format(recovery_count),
    ]
    if notification_summary.get("retry_exhausted"):
        facts.append("{0} delivery exhausted".format(notification_summary["retry_exhausted"]))
    if queue_mode == "paused":
        return {
            "tone": "danger",
            "label": "Autopilot constrained",
            "summary": "Launches are paused, so assigned work will not start even if autopilot is enabled.",
            "detail": "Resume launches before expecting newly assigned work to move forward.",
            "facts": facts,
            "operatorActions": dedupe_operator_actions(
                operator_actions
                + [
                    project_launch_posture_action(
                        project_id,
                        "Resume launches",
                        "running",
                        max(1, int(queue_snapshot.get("max_running_jobs") or 1)),
                        preferred_provider_id=queue_snapshot.get("preferred_provider_id"),
                    )
                ]
            )[:3],
        }
    if queue_mode == "draining":
        return {
            "tone": "warn",
            "label": "Autopilot draining",
            "summary": "The loop is still active, but newly assigned work will not launch while the queue is draining.",
            "detail": "Current runs can finish, but fresh assigned work will wait until posture returns to running.",
            "facts": facts,
            "operatorActions": dedupe_operator_actions(
                operator_actions
                + [
                    project_launch_posture_action(
                        project_id,
                        "Resume launches",
                        "running",
                        max(1, int(queue_snapshot.get("max_running_jobs") or 1)),
                        preferred_provider_id=queue_snapshot.get("preferred_provider_id"),
                    )
                ]
            )[:3],
        }
    if not policy.get("enabled"):
        return {
            "tone": "warn" if review_count or recovery_count else "default",
            "label": "Manual loop",
            "summary": "Autopilot is disabled for this project.",
            "detail": "MAAS will only advance when the operator runs cycles manually.",
            "facts": facts,
            "operatorActions": [
                project_autopilot_action(project_id, "Enable autopilot", {**policy, "enabled": True})
            ],
        }
    if governance_gate.get("blocked"):
        return {
            "tone": "danger",
            "label": "Autopilot gated",
            "summary": governance_gate.get("summary") or "Autopilot is blocked by control-loop policy.",
            "detail": governance_gate.get("detail") or why_idle or "Clear the blocking governance signal before resuming autonomy.",
            "facts": facts,
            "operatorActions": operator_actions[:3],
        }
    if lease_active:
        if runtime_status == "error":
            return {
                "tone": "danger",
                "label": "Autopilot error",
                "summary": "The autopilot runner hit an error on the last cycle.",
                "detail": runtime.get("last_error") or "Inspect the operator inbox and system diagnostics before resuming.",
                "facts": facts,
                "operatorActions": operator_actions[:3],
            }
        return {
            "tone": "default",
            "label": "Autopilot active",
            "summary": "The autonomous loop is running for this project.",
            "detail": (
                "Last cycle: {0} assigned, {1} started, {2} queued, {3} notifications processed.".format(
                    (runtime.get("last_summary") or {}).get("assigned_count", 0),
                    ((runtime.get("last_summary") or {}).get("provider_jobs_processed", 0))
                    + ((runtime.get("last_summary") or {}).get("provider_jobs_dispatched", 0)),
                    (runtime.get("last_summary") or {}).get("provider_jobs_queued", 0),
                    (runtime.get("last_summary") or {}).get("notifications_processed", 0),
                )
                if runtime.get("last_summary")
                else "MAAS is actively advancing work in the background."
            ),
            "facts": facts,
            "operatorActions": operator_actions[:3],
        }
    if runtime_status == "waiting":
        return {
            "tone": "warn",
            "label": "Autopilot waiting",
            "summary": "Autopilot is enabled but this process does not currently own the active lease.",
            "detail": why_idle
            or "Another MAAS process may own the project loop, or the lease is waiting to be reacquired after a restart.",
            "facts": facts,
            "operatorActions": operator_actions[:3],
        }
    if operator_actions:
        return {
            "tone": "warn",
            "label": "Autopilot needs attention",
            "summary": governance_gate.get("summary") or "Autopilot is within policy, but the control loop needs intervention.",
            "detail": why_idle or governance_gate.get("detail") or "Clear the current control-loop pressure before relying on autonomous progress.",
            "facts": facts,
            "operatorActions": operator_actions[:3],
        }
    return {
        "tone": "default",
        "label": "Autopilot armed",
        "summary": "Autopilot is enabled and waiting for the next cycle.",
        "detail": why_idle or "No blocker is recorded at the loop level; the next cycle should continue normal autonomous progress.",
        "facts": facts,
        "operatorActions": [],
    }


def fetch_operator_inbox(connection, project_id, project_paths=None):
    issue_index = fetch_issue_index(connection, project_id=project_id)
    system_diagnostics = fetch_system_diagnostics(connection, project_id=project_id)
    recovery_overview = fetch_project_recovery_overview(connection, project_id=project_id)
    project_row = resolve_project(connection, project_id, include_archived=False)
    autopilot_policy = fetch_project_autopilot_policy(connection, project_id)
    autopilot_runtime = fetch_autopilot_runtime(connection, project_id) or {
        "project_id": project_id,
        "last_summary": {},
        "last_error": None,
        "last_heartbeat_at": None,
        "loop_count": 0,
        "status": "idle",
        "lease_active": False,
    }
    autopilot_status = None
    if project_paths is not None:
        autopilot_status = fetch_autopilot_status(connection, project_paths, project_id)
        autopilot_policy = autopilot_status["policy"]
        autopilot_runtime = autopilot_status["runtime"]
    queue_snapshot = queue_capacity_snapshot(connection, project_id)
    notification_items = fetch_notification_outbox(connection, project_id=project_id, limit=100, include_archived=False)
    notification_summary = build_notification_outbox_summary(notification_items)

    buckets = {
        "review": _review_items(issue_index),
        "stale_runs": _stale_run_items(system_diagnostics),
        "blocked_recovery": _recovery_items(recovery_overview),
        "policy_conflicts": _policy_conflict_items(connection, project_id),
        "notification_failures": _notification_failure_items(connection, project_id),
    }
    items = [
        item
        for bucket_items in buckets.values()
        for item in bucket_items
    ]
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    items.sort(key=lambda item: (severity_order.get(item["severity"], 3), item["bucket"], item["title"]))
    workflow_items = [_workflow_item(item) for item in items[:12]]
    workflow_operator_actions = _workflow_operator_actions(workflow_items)
    if any(item.get("metadata", {}).get("delivery_state") in {"retry_ready", "retry_exhausted"} for item in buckets["notification_failures"]):
        workflow_operator_actions = dedupe_operator_actions(
            workflow_operator_actions
            + [
                project_notification_action(
                    "process_next_notification",
                    "Process next due delivery",
                    project_id,
                )
            ]
        )[:4]
    inbox_summary = {
        "total_items": len(items),
        "review": issue_index["summary"]["review"],
        "stale_runs": len(buckets["stale_runs"]),
        "blocked_recovery": len(buckets["blocked_recovery"]),
        "policy_conflicts": len(buckets["policy_conflicts"]),
        "notification_failures": len(buckets["notification_failures"]),
        "critical_items": len([item for item in items if item["severity"] == "critical"]),
    }
    inbox_copy = _summarize_inbox(inbox_summary)
    return {
        "project_id": project_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": inbox_summary,
        "buckets": buckets,
        "items": items,
        "workflow": {
            "inbox": {
                "headline": inbox_copy["headline"],
                "detail": inbox_copy["detail"],
                "totalCount": inbox_summary["total_items"],
                "reviewCount": inbox_summary["review"],
                "recoveryCount": inbox_summary["blocked_recovery"],
                "suspectRunCount": inbox_summary["stale_runs"],
                "failedNotificationCount": inbox_summary["notification_failures"],
                "policyConflictCount": inbox_summary["policy_conflicts"],
                "recommendedView": inbox_copy["recommendedView"],
                "recommendedLabel": inbox_copy["recommendedLabel"],
                "operatorActions": workflow_operator_actions,
                "items": workflow_items,
            },
            "autopilot": _summarize_autopilot(
                project_id,
                autopilot_policy,
                autopilot_runtime,
                queue_snapshot,
                issue_index,
                notification_summary,
                why_idle=(autopilot_status or {}).get("why_idle"),
                governance_gate=(autopilot_status or {}).get("governance_gate"),
            ),
        },
        "project": {
            "project_id": project_id,
            "name": project_row["name"] if project_row else project_id,
            "queue_mode": queue_snapshot.get("queue_mode"),
            "max_running_jobs": queue_snapshot.get("max_running_jobs"),
            "autopilot_enabled": autopilot_policy.get("enabled", False),
        },
    }
