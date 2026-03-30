"""Codex MVP read models."""

from datetime import datetime, timezone
import json
import os

from maas.services.artifacts import fetch_artifacts
from maas.services.delivery import fetch_task_delivery_status
from maas.services.git_workspaces import fetch_task_git_workspace
from maas.services.goal_planning import fetch_goal_explainability
from maas.services.memory import fetch_project_memory, retrieve_relevant_memory
from maas.services.provider_jobs import fetch_provider_jobs
from maas.services.reconciliation import inspect_project_truth
from maas.services.recovery_policy import fetch_suppression_summary
from maas.services.repo_plan import build_brownfield_grounding
from maas.services.review_policy import evaluate_review_decision_state, fetch_project_review_policy
from maas.services.timeline import fetch_incident_timeline
from maas.services.verification import fetch_verification_runs


RUN_CONSOLE_PREVIEW_MAX_CHARS = 6000
STALE_RUN_HEARTBEAT_SECONDS = 90
RUN_PHASE_LABELS = {
    "session_started": "Session started",
    "workspace_prepared": "Workspace prepared",
    "execution_running": "Execution running",
    "artifact_recorded": "Artifact recorded",
    "session_completed": "Completed",
    "session_failed": "Failed",
}


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


def _parse_timestamp(value):
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                parsed = datetime.strptime(value, fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_seconds(value):
    parsed = _parse_timestamp(value)
    if parsed is None:
        return None
    return max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))


def _execution_explanation(connection, project_id):
    task_summary = connection.execute(
        """
        SELECT
            SUM(CASE WHEN status = 'ready' THEN 1 ELSE 0 END) AS ready_tasks,
            SUM(CASE WHEN status = 'assigned' THEN 1 ELSE 0 END) AS assigned_tasks,
            SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) AS active_tasks,
            SUM(CASE WHEN status = 'review' THEN 1 ELSE 0 END) AS review_tasks,
            SUM(CASE WHEN status = 'blocked' THEN 1 ELSE 0 END) AS blocked_tasks
        FROM tasks
        WHERE project_id = ?
        """,
        (project_id,),
    ).fetchone()
    project_row = connection.execute(
        "SELECT config_json FROM projects WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    config = _load_json(project_row["config_json"] if project_row else "{}")
    provider_capacity = config.get("provider_capacity") or {}
    queue_mode = provider_capacity.get("queue_mode") or "running"
    ready_tasks = task_summary["ready_tasks"] or 0
    assigned_tasks = task_summary["assigned_tasks"] or 0
    active_tasks = task_summary["active_tasks"] or 0
    review_tasks = task_summary["review_tasks"] or 0
    blocked_tasks = task_summary["blocked_tasks"] or 0
    if active_tasks:
        return {
            "state": "running",
            "summary": "MAAS is actively executing work.",
            "detail": "Live Codex runs are in progress and the queue is moving.",
        }
    if queue_mode == "paused":
        return {
            "state": "paused",
            "summary": "Launches are paused.",
            "detail": "Assigned work will not start until launch posture is resumed.",
        }
    if queue_mode == "draining":
        return {
            "state": "draining",
            "summary": "Queue is draining.",
            "detail": "Queued and running jobs can finish, but newly assigned work will not launch.",
        }
    if review_tasks and not ready_tasks and not assigned_tasks:
        return {
            "state": "waiting_for_review",
            "summary": "Work is waiting on review decisions.",
            "detail": "Operator review or auto-approval policy is the current gate on forward progress.",
        }
    if assigned_tasks:
        return {
            "state": "waiting_for_launch",
            "summary": "Assigned work is waiting to launch.",
            "detail": "The next cycle or provider readiness is the only thing stopping new Codex runs.",
        }
    if ready_tasks:
        return {
            "state": "waiting_for_assignment",
            "summary": "Ready work exists but has not been assigned yet.",
            "detail": "The next cycle should allocate ready issues to an agent.",
        }
    if blocked_tasks:
        return {
            "state": "blocked",
            "summary": "The remaining work is blocked.",
            "detail": "Recovery, dependency clearing, or replanning is required before the project can continue.",
        }
    return {
        "state": "idle",
        "summary": "No runnable work exists right now.",
        "detail": "There are no ready, assigned, or active issues in this project.",
    }


def _derive_run_phases(activity, status):
    discovered = {}
    for event in activity:
        details = event.get("details") or {}
        phase = details.get("phase")
        if phase and phase not in discovered:
            discovered[phase] = {
                "key": phase,
                "label": RUN_PHASE_LABELS.get(phase, phase.replace("_", " ")),
                "timestamp": event.get("created_at"),
                "description": event.get("description"),
                "status": "completed",
            }
    ordered_keys = ["session_started", "workspace_prepared", "execution_running", "artifact_recorded", "session_completed"]
    phases = []
    seen_terminal = False
    for key in ordered_keys:
        phase = discovered.get(key)
        if phase:
            phases.append(phase)
            if key == "session_completed":
                seen_terminal = True
            continue
        inferred_status = "pending"
        if status == "active" and key == "execution_running":
            inferred_status = "active"
        phases.append({"key": key, "label": RUN_PHASE_LABELS.get(key, key.replace("_", " ")), "timestamp": None, "description": None, "status": inferred_status})
    failure_phase = discovered.get("session_failed")
    if failure_phase:
        failure_phase["status"] = "failed"
        phases.append(failure_phase)
        seen_terminal = True
    if status == "cancelled" and not seen_terminal:
        phases.append(
            {
                "key": "session_cancelled",
                "label": "Cancelled",
                "timestamp": None,
                "description": "Operator cancelled the run before completion.",
                "status": "failed",
            }
        )
    return phases


def _run_memory_context(activity):
    for event in activity:
        if event.get("action") != "memory_context_loaded":
            continue
        details = event.get("details") or {}
        return details.get("memory_items") or []
    return []


def _issue_recovery_playbook(task_row, review_decision, failure_count, latest_run, verification_runs):
    if task_row["status"] == "review":
        decision_mode = review_decision.get("decision_mode")
        review_packet = review_decision.get("grouped_review_packet") or {}
        if decision_mode == "auto_approve":
            return {
                "kind": "review",
                "title": "Low-risk review should auto-advance",
                "summary": review_decision["summary"],
                "detail": review_decision["detail"],
                "recommended_action": "Leave it alone if you trust the policy, or approve manually now if you need the unblock immediately.",
                "actions": ["approve", "reject"],
                "confidence": "high",
            }
        if decision_mode == "batch_review":
            return {
                "kind": "review",
                "title": review_packet.get("title") or "Review the latest output",
                "summary": review_decision["summary"],
                "detail": review_decision["detail"],
                "recommended_action": "Batch-approve it with the rest of the low-risk verified packet if the evidence looks consistent.",
                "actions": ["approve", "reject"],
                "confidence": "high",
            }
        return {
            "kind": "review",
            "title": "Review the latest output",
            "summary": review_decision["summary"],
            "detail": review_decision.get("why_not_batch_reviewed") or review_decision["detail"],
            "recommended_action": "Approve it if the output and checks look correct; request changes otherwise.",
            "actions": ["approve", "reject"],
            "confidence": "medium",
        }
    if task_row["status"] == "blocked":
        reason = task_row["review_state"] or "blocked"
        if failure_count or reason in {"session_failed", "timed_out", "retry_budget_exhausted", "circuit_breaker_open"}:
            return {
                "kind": "recovery",
                "title": "Recover the issue before running it again",
                "summary": "The issue is blocked by a failed or exhausted execution path.",
                "detail": "Inspect the latest run trace, then recover, requeue, or replan depending on whether the failure was transient.",
                "recommended_action": "Recover + requeue if the run failed transiently, or mark for replan if the output path was wrong.",
                "actions": ["recover", "requeue", "replan"],
                "confidence": "high",
            }
        return {
            "kind": "dependency",
            "title": "Unblock the dependency chain",
            "summary": "The issue is blocked by upstream work or a pending operator decision.",
            "detail": "Open the linked issues and clear the dependency or review gate before expecting this issue to move again.",
            "recommended_action": "Inspect dependencies first; only recover this issue if the upstream cause is already resolved.",
            "actions": ["open_dependencies", "replan"],
            "confidence": "medium",
        }
    if task_row["status"] == "in_progress":
        return {
            "kind": "running",
            "title": "Let Codex continue unless the run looks stale",
            "summary": "A live run is actively working on this issue.",
            "detail": (latest_run.get("diagnostic_summary") or latest_run.get("status_message")) if latest_run else "The issue currently has an active execution session.",
            "recommended_action": "Watch the run trace and only stop it if the output tail or heartbeat suggests it is stuck.",
            "actions": ["open_run", "stop"],
            "confidence": "medium",
        }
    if task_row["status"] == "assigned":
        return {
            "kind": "launch",
            "title": "Assigned work is waiting to launch",
            "summary": "The issue already has an owner but no active run yet.",
            "detail": "Launch posture, provider readiness, or the next cycle is the current gate.",
            "recommended_action": "Run the next cycle or resume launches if the queue is paused.",
            "actions": ["run_cycle"],
            "confidence": "medium",
        }
    if task_row["status"] == "ready":
        return {
            "kind": "ready",
            "title": "Ready for assignment",
            "summary": "This issue is ready but has not been allocated yet.",
            "detail": "A scheduler cycle will pick an owner and move it forward.",
            "recommended_action": "Run the next cycle and let MAAS allocate it.",
            "actions": ["run_cycle"],
            "confidence": "high",
        }
    if task_row["status"] in {"done", "cancelled"}:
        return {
            "kind": "resolved",
            "title": "Resolved history",
            "summary": "This issue no longer needs operator intervention.",
            "detail": "Use the run and artifact history for audit, reuse, or memory promotion.",
            "recommended_action": "Promote a useful output to memory if this result should influence future runs.",
            "actions": ["promote_memory"],
            "confidence": "high",
        }
    return {
        "kind": "idle",
        "title": "No immediate intervention required",
        "summary": "This issue is not currently in a state that needs operator action.",
        "detail": "Inspect the latest output and relationships if you need more context.",
        "recommended_action": "Let the system continue unless a related alert or run suggests otherwise.",
        "actions": [],
        "confidence": "low",
    }


def _run_row_to_dict(row, issue_keys):
    started_at = row["started_at"]
    last_heartbeat_at = row["last_heartbeat_at"]
    heartbeat_age_seconds = _age_seconds(last_heartbeat_at)
    run_age_seconds = _age_seconds(started_at)
    is_live = row["status"] == "active"
    is_stale = bool(is_live and heartbeat_age_seconds is not None and heartbeat_age_seconds >= STALE_RUN_HEARTBEAT_SECONDS)
    diagnostic_summary, recommended_action = _run_diagnostics(
        row["status"],
        row["task_status"],
        row["task_review_state"],
        heartbeat_age_seconds,
        is_stale,
    )
    observability = _run_observability(row, heartbeat_age_seconds, is_stale)
    return {
        "session_id": row["session_id"],
        "task_id": row["task_id"],
        "task_title": row["task_title"],
        "task_status": row["task_status"],
        "task_review_state": row["task_review_state"],
        "issue_key": issue_keys.get(row["task_id"]) if row["task_id"] else None,
        "goal_id": row["goal_id"],
        "goal_title": row["goal_title"],
        "agent_id": row["agent_id"],
        "agent_name": row["agent_name"],
        "provider_type": row["provider_type"],
        "execution_mode": row["execution_mode"],
        "external_runtime": row["external_runtime"],
        "status": row["status"],
        "progress_pct": row["progress_pct"],
        "status_message": row["status_message"],
        "last_heartbeat_at": last_heartbeat_at,
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "started_at": started_at,
        "ended_at": row["ended_at"],
        "run_age_seconds": run_age_seconds,
        "is_live": is_live,
        "is_stale": is_stale,
        "diagnostic_summary": diagnostic_summary,
        "recommended_action": recommended_action,
        "observability": observability,
        "artifact_count": row["artifact_count"] or 0,
        "failure_count": row["failure_count"] or 0,
    }


def _run_diagnostics(status, task_status, task_review_state, heartbeat_age_seconds, is_stale):
    if status == "active" and is_stale:
        return (
            "The session is still marked active, but the heartbeat has gone quiet long enough to treat it as suspect.",
            "Inspect the run trace and stop the issue if Codex is no longer making progress.",
        )
    if status == "active":
        return (
            "Codex is actively working on this issue and is still heartbeating normally.",
            "Let the run continue unless the output tail or logs show it is stuck.",
        )
    if status in {"failed", "timed_out"}:
        return (
            "The last execution ended unsuccessfully and the linked issue likely needs recovery or replanning.",
            "Open the issue and recover or requeue it after inspecting the trace and output.",
        )
    if status == "cancelled":
        return (
            "This run was cancelled before completion. The linked issue may be halted or waiting for operator intervention.",
            "Open the issue to decide whether to recover, requeue, or leave it cancelled.",
        )
    if task_status == "review" or task_review_state == "review_requested":
        return (
            "Execution completed and the linked issue is waiting on a review decision.",
            "Open the issue and review the output before approving or requesting changes.",
        )
    if task_status == "done":
        return (
            "Execution completed and the linked issue has already been resolved.",
            "Use the run trace for audit or debugging; no operator action is required now.",
        )
    return (
        "Execution finished and the linked issue moved on to its next state.",
        "Open the issue if you need to inspect what changed or what this run unlocked.",
    )


def _run_observability(row, heartbeat_age_seconds, is_stale):
    last_activity_at = row["last_activity_at"] if "last_activity_at" in row.keys() else None
    last_activity_action = row["last_activity_action"] if "last_activity_action" in row.keys() else None
    activity_count = int(row["activity_count"] or 0) if "activity_count" in row.keys() else 0
    status = row["status"]
    if status == "active" and is_stale:
        state = "stalled"
        attention_level = "critical"
        summary = "Heartbeat is stale while the run still appears active."
        detail = "This usually means the session stopped advancing or the worker process lost contact."
    elif status == "active":
        state = "active"
        attention_level = "info"
        summary = "Run is active and still heartbeating."
        detail = "Activity and heartbeat signals indicate the session is still making normal progress."
    elif status in {"failed", "timed_out"}:
        state = "failed"
        attention_level = "critical"
        summary = "Run ended unsuccessfully."
        detail = "This session needs recovery, replanning, or operator confirmation before work continues."
    elif status == "cancelled":
        state = "cancelled"
        attention_level = "warning"
        summary = "Run was cancelled before completion."
        detail = "The linked issue may still need recovery or a deliberate stop decision."
    elif row["task_status"] == "review" or row["task_review_state"] == "review_requested":
        state = "review"
        attention_level = "warning"
        summary = "Execution is complete and waiting on review."
        detail = "Operator judgment is now the main gate on forward progress for this issue."
    else:
        state = "resolved"
        attention_level = "info"
        summary = "Run is no longer active."
        detail = "Use the trace and artifacts for audit, reuse, or debugging."
    if last_activity_at:
        detail = "{0} Last run-scoped activity: {1}{2}.".format(
            detail,
            last_activity_action.replace("_", " ") if last_activity_action else "activity recorded",
            " at {0}".format(last_activity_at),
        )
    return {
        "state": state,
        "attention_level": attention_level,
        "summary": summary,
        "detail": detail,
        "last_activity_at": last_activity_at,
        "last_activity_action": last_activity_action,
        "activity_count": activity_count,
        "heartbeat_age_seconds": heartbeat_age_seconds,
    }


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
    items = []
    for row in rows:
        start_details = _session_start_details(connection, project_id, task_id, row["session_id"])
        items.append(
            {
                "session_id": row["session_id"],
                "agent_id": row["agent_id"],
                "agent_name": row["agent_name"],
                "provider_type": row["provider_type"],
                "execution_mode": start_details.get("execution_mode"),
                "external_runtime": start_details.get("external_runtime"),
                "status": row["status"],
                "progress_pct": row["progress_pct"],
                "status_message": row["status_message"],
                "last_heartbeat_at": row["last_heartbeat_at"],
                "started_at": row["started_at"],
                "ended_at": row["ended_at"],
            }
        )
    return items


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


def fetch_runs(connection, project_id, limit=200, status=None, search=None):
    issue_keys = issue_key_lookup(connection, project_id)
    params = [project_id]
    filters = ["sessions.project_id = ?"]
    if status:
        filters.append("sessions.status = ?")
        params.append(status)
    search_value = (search or "").strip()
    if search_value:
        filters.append(
            """
            (
                sessions.session_id LIKE ?
                OR COALESCE(tasks.title, '') LIKE ?
                OR COALESCE(tasks.task_id, '') LIKE ?
                OR COALESCE(agents.display_name, '') LIKE ?
                OR COALESCE(sessions.status_message, '') LIKE ?
            )
            """
        )
        pattern = f"%{search_value}%"
        params.extend([pattern, pattern, pattern, pattern, pattern])

    rows = connection.execute(
        """
        SELECT
            sessions.session_id,
            sessions.task_id,
            tasks.title AS task_title,
            tasks.status AS task_status,
            tasks.review_state AS task_review_state,
            tasks.goal_id AS goal_id,
            goals.title AS goal_title,
            sessions.agent_id,
            agents.display_name AS agent_name,
            sessions.provider_type,
            sessions.status,
            sessions.progress_pct,
            sessions.status_message,
            sessions.last_heartbeat_at,
            sessions.started_at,
            sessions.ended_at,
            (
                SELECT activity_log.created_at
                FROM activity_log
                WHERE activity_log.project_id = sessions.project_id
                  AND activity_log.task_id = sessions.task_id
                  AND json_extract(activity_log.details_json, '$.session_id') = sessions.session_id
                ORDER BY activity_log.created_at DESC, activity_log.rowid DESC
                LIMIT 1
            ) AS last_activity_at,
            (
                SELECT activity_log.action
                FROM activity_log
                WHERE activity_log.project_id = sessions.project_id
                  AND activity_log.task_id = sessions.task_id
                  AND json_extract(activity_log.details_json, '$.session_id') = sessions.session_id
                ORDER BY activity_log.created_at DESC, activity_log.rowid DESC
                LIMIT 1
            ) AS last_activity_action,
            (
                SELECT COUNT(*)
                FROM activity_log
                WHERE activity_log.project_id = sessions.project_id
                  AND activity_log.task_id = sessions.task_id
                  AND json_extract(activity_log.details_json, '$.session_id') = sessions.session_id
            ) AS activity_count,
            json_extract(start_log.details_json, '$.execution_mode') AS execution_mode,
            json_extract(start_log.details_json, '$.external_runtime') AS external_runtime,
            COUNT(DISTINCT artifacts.artifact_id) AS artifact_count,
            COUNT(DISTINCT failure_log.failure_id) AS failure_count
        FROM sessions
        LEFT JOIN tasks ON tasks.task_id = sessions.task_id
        LEFT JOIN goals ON goals.goal_id = tasks.goal_id
        LEFT JOIN agents ON agents.agent_id = sessions.agent_id
        LEFT JOIN activity_log AS start_log
            ON start_log.project_id = sessions.project_id
           AND start_log.task_id = sessions.task_id
           AND start_log.action = 'provider_adapter_started'
           AND json_extract(start_log.details_json, '$.session_id') = sessions.session_id
        LEFT JOIN artifacts
            ON artifacts.project_id = sessions.project_id
           AND artifacts.session_id = sessions.session_id
        LEFT JOIN failure_log
            ON failure_log.project_id = sessions.project_id
           AND failure_log.session_id = sessions.session_id
        WHERE {where_clause}
        GROUP BY sessions.session_id
        ORDER BY
            CASE sessions.status
                WHEN 'active' THEN 0
                WHEN 'failed' THEN 1
                WHEN 'timed_out' THEN 2
                WHEN 'cancelled' THEN 3
                ELSE 4
            END,
            COALESCE(sessions.ended_at, sessions.started_at) DESC,
            sessions.rowid DESC
        LIMIT ?
        """.format(where_clause=" AND ".join(filters)),
        tuple(params + [max(int(limit), 1)]),
    ).fetchall()

    items = [_run_row_to_dict(row, issue_keys) for row in rows]
    summary = {
        "total_runs": len(items),
        "active_runs": len([item for item in items if item["status"] == "active"]),
        "failed_runs": len([item for item in items if item["status"] == "failed"]),
        "timed_out_runs": len([item for item in items if item["status"] == "timed_out"]),
        "cancelled_runs": len([item for item in items if item["status"] == "cancelled"]),
        "completed_runs": len([item for item in items if item["status"] == "completed"]),
        "stale_runs": len([item for item in items if item["is_stale"]]),
    }
    return {"summary": summary, "items": items}


def fetch_system_diagnostics(connection, project_id, project_paths=None):
    run_payload = fetch_runs(connection, project_id, limit=100)
    truth = inspect_project_truth(connection, project_paths, project_id=project_id) if project_paths else {
        "project_id": project_id,
        "generated_at": None,
        "latest_reconciled_at": None,
        "summary": {"warning_count": 0, "repairable_count": 0, "repaired_count": 0, "delivery_refresh_count": 0},
        "warnings": [],
    }
    suspect_run_count = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM sessions
        WHERE project_id = ?
          AND (
            status IN ('failed', 'timed_out', 'cancelled')
            OR (
                status = 'active'
                AND last_heartbeat_at IS NOT NULL
                AND datetime(last_heartbeat_at) <= datetime('now', ?)
            )
          )
        """,
        (project_id, "-{0} seconds".format(STALE_RUN_HEARTBEAT_SECONDS)),
    ).fetchone()["count"]
    all_suspect_runs = [
        item
        for item in run_payload["items"]
        if item["is_stale"] or item["status"] in {"failed", "timed_out", "cancelled"}
    ]
    suspect_runs = all_suspect_runs[:10]
    suppression = fetch_suppression_summary(connection, project_id=project_id, limit=12)

    issue_keys = issue_key_lookup(connection, project_id)
    stale_agent_rows = connection.execute(
        """
        SELECT
            agents.agent_id,
            agents.display_name,
            agents.status,
            agents.current_task_id,
            tasks.title AS current_task_title,
            agents.last_heartbeat_at,
            active_sessions.session_id AS focus_run_session_id
        FROM agents
        LEFT JOIN tasks ON tasks.task_id = agents.current_task_id
        LEFT JOIN sessions AS active_sessions
            ON active_sessions.project_id = agents.project_id
           AND active_sessions.agent_id = agents.agent_id
           AND active_sessions.status = 'active'
        WHERE agents.project_id = ?
        ORDER BY agents.display_name ASC
        """,
        (project_id,),
    ).fetchall()
    stale_agents = []
    for row in stale_agent_rows:
        heartbeat_age_seconds = _age_seconds(row["last_heartbeat_at"])
        if heartbeat_age_seconds is None or heartbeat_age_seconds < STALE_RUN_HEARTBEAT_SECONDS:
            continue
        stale_agents.append(
            {
                "agent_id": row["agent_id"],
                "display_name": row["display_name"],
                "status": row["status"],
                "heartbeat_age_seconds": heartbeat_age_seconds,
                "current_task_id": row["current_task_id"],
                "current_issue_key": issue_keys.get(row["current_task_id"]) if row["current_task_id"] else None,
                "current_task_title": row["current_task_title"],
                "focus_run_session_id": row["focus_run_session_id"],
                "diagnostic_summary": "The agent heartbeat is stale enough to inspect for a stuck Codex thread or crashed worker.",
                "recommended_action": (
                    "Open the live run if one exists, otherwise inspect the agent history and recover the agent if it is no longer progressing."
                ),
            }
        )

    provider_jobs = fetch_provider_jobs(connection, project_id=project_id, limit=200)
    queued_jobs = [job for job in provider_jobs if job["status"] == "queued"]
    running_jobs = [job for job in provider_jobs if job["status"] == "running"]
    oldest_queued_at = min((job["created_at"] for job in queued_jobs), default=None)
    oldest_running_at = min(
        ((job["started_at"] or job["created_at"]) for job in running_jobs),
        default=None,
    )
    attention_items = []
    for run in suspect_runs[:6]:
        attention_items.append(
            {
                "kind": "suspect_run",
                "title": run["issue_key"] or run["task_title"] or run["session_id"],
                "summary": run.get("diagnostic_summary") or run.get("status_message") or "Run needs inspection.",
                "detail": run.get("observability", {}).get("detail") or run.get("recommended_action"),
                "session_id": run["session_id"],
                "task_id": run.get("task_id"),
                "issue_key": run.get("issue_key"),
                "operator_action": None,
            }
        )
    for agent in stale_agents[:4]:
        attention_items.append(
            {
                "kind": "stale_agent",
                "title": agent["display_name"],
                "summary": agent.get("diagnostic_summary") or "Agent heartbeat is stale.",
                "detail": agent.get("recommended_action"),
                "session_id": agent.get("focus_run_session_id"),
                "task_id": agent.get("current_task_id"),
                "issue_key": agent.get("current_issue_key"),
                "operator_action": None,
            }
        )
    for item in suppression["items"][:6]:
        attention_items.append(
            {
                "kind": item["kind"],
                "title": item.get("task_title") or item.get("task_id") or item.get("kind"),
                "summary": item.get("summary"),
                "detail": item.get("detail"),
                "session_id": None,
                "task_id": item.get("task_id"),
                "issue_key": issue_keys.get(item["task_id"]) if item.get("task_id") else None,
                "operator_action": item.get("operator_action"),
            }
        )

    return {
        "summary": {
            "active_runs": run_payload["summary"]["active_runs"],
            "suspect_runs": suspect_run_count,
            "stale_agents": len(stale_agents),
            "queued_jobs": len(queued_jobs),
            "running_jobs": len(running_jobs),
            "suppressed_items": suppression["summary"]["total"],
            "oldest_queued_at": oldest_queued_at,
            "oldest_running_at": oldest_running_at,
            "truth_warnings": truth["summary"]["warning_count"],
        },
        "execution_state": _execution_explanation(connection, project_id),
        "live_runs": {
            "active_runs": run_payload["summary"]["active_runs"],
            "stale_runs": run_payload["summary"]["stale_runs"],
            "failed_runs": run_payload["summary"]["failed_runs"] + run_payload["summary"]["timed_out_runs"],
            "completed_runs": run_payload["summary"]["completed_runs"],
        },
        "suspect_runs": suspect_runs,
        "stale_agents": stale_agents,
        "attention_items": attention_items[:12],
        "suppression": suppression,
        "queue_pressure": {
            "queued_jobs": len(queued_jobs),
            "running_jobs": len(running_jobs),
            "oldest_queued_at": oldest_queued_at,
            "oldest_running_at": oldest_running_at,
        },
        "truth": truth,
    }


def fetch_retrieval_search(connection, project_id=None, search="", goal_id=None, agent_id=None, priority_min=None, limit=8):
    search_value = (search or "").strip()
    safe_limit = max(1, min(int(limit or 8), 25))
    if not search_value:
        return {
            "query": {
                "search": "",
                "goal_id": goal_id,
                "agent_id": agent_id,
                "priority_min": priority_min,
            },
            "summary": {
                "total_hits": 0,
                "issue_hits": 0,
                "run_hits": 0,
                "artifact_hits": 0,
                "event_hits": 0,
                "memory_hits": 0,
            },
            "issues": [],
            "runs": [],
            "artifacts": [],
            "events": [],
            "memory": [],
        }

    issue_keys = issue_key_lookup(connection, project_id)
    pattern = "%{0}%".format(search_value)

    task_filters = [
        """
        (
            tasks.task_id LIKE ?
            OR COALESCE(tasks.title, '') LIKE ?
            OR COALESCE(tasks.description, '') LIKE ?
            OR COALESCE(goals.title, '') LIKE ?
            OR COALESCE(agents.display_name, '') LIKE ?
        )
        """
    ]
    task_params = [pattern, pattern, pattern, pattern, pattern]
    if project_id is not None:
        task_filters.append("tasks.project_id = ?")
        task_params.append(project_id)
    if goal_id:
        task_filters.append("tasks.goal_id = ?")
        task_params.append(goal_id)
    if agent_id:
        task_filters.append("tasks.assigned_agent_id = ?")
        task_params.append(agent_id)
    if priority_min is not None:
        task_filters.append("tasks.priority >= ?")
        task_params.append(priority_min)

    issue_rows = connection.execute(
        """
        SELECT
            tasks.task_id,
            tasks.project_id,
            projects.name AS project_name,
            tasks.title,
            tasks.status,
            tasks.priority,
            tasks.updated_at,
            tasks.goal_id,
            goals.title AS goal_title,
            tasks.assigned_agent_id AS agent_id,
            agents.display_name AS agent_name,
            CASE
                WHEN COALESCE(tasks.description, '') LIKE ? THEN COALESCE(tasks.description, '')
                WHEN COALESCE(goals.title, '') LIKE ? THEN 'Goal: ' || goals.title
                WHEN COALESCE(agents.display_name, '') LIKE ? THEN 'Owner: ' || agents.display_name
                ELSE COALESCE(tasks.description, goals.title, tasks.title)
            END AS match_context
        FROM tasks
        JOIN projects ON projects.project_id = tasks.project_id
        LEFT JOIN goals ON goals.goal_id = tasks.goal_id
        LEFT JOIN agents ON agents.agent_id = tasks.assigned_agent_id
        WHERE projects.state = 'active'
          AND {where_clause}
        ORDER BY tasks.priority DESC, tasks.updated_at DESC, tasks.created_at DESC
        LIMIT ?
        """.format(where_clause=" AND ".join(task_filters)),
        tuple([pattern, pattern, pattern] + task_params + [safe_limit]),
    ).fetchall()
    issues = [
        {
            "task_id": row["task_id"],
            "issue_key": issue_keys.get(row["task_id"]),
            "project_id": row["project_id"],
            "project_name": row["project_name"],
            "title": row["title"],
            "status": row["status"],
            "priority": row["priority"],
            "goal_id": row["goal_id"],
            "goal_title": row["goal_title"],
            "agent_id": row["agent_id"],
            "agent_name": row["agent_name"],
            "match_context": row["match_context"] or row["title"],
            "updated_at": row["updated_at"],
        }
        for row in issue_rows
    ]

    run_filters = [
        """
        (
            sessions.session_id LIKE ?
            OR COALESCE(tasks.title, '') LIKE ?
            OR COALESCE(tasks.task_id, '') LIKE ?
            OR COALESCE(agents.display_name, '') LIKE ?
            OR COALESCE(sessions.status_message, '') LIKE ?
        )
        """
    ]
    run_params = [pattern, pattern, pattern, pattern, pattern]
    if project_id is not None:
        run_filters.append("sessions.project_id = ?")
        run_params.append(project_id)
    if goal_id:
        run_filters.append("tasks.goal_id = ?")
        run_params.append(goal_id)
    if agent_id:
        run_filters.append("sessions.agent_id = ?")
        run_params.append(agent_id)
    if priority_min is not None:
        run_filters.append("tasks.priority >= ?")
        run_params.append(priority_min)

    run_rows = connection.execute(
        """
        SELECT
            sessions.session_id,
            sessions.project_id,
            projects.name AS project_name,
            sessions.task_id,
            tasks.title AS task_title,
            sessions.status,
            sessions.provider_type,
            sessions.started_at,
            sessions.status_message AS match_context,
            json_extract(start_log.details_json, '$.execution_mode') AS execution_mode,
            json_extract(start_log.details_json, '$.external_runtime') AS external_runtime
        FROM sessions
        JOIN projects ON projects.project_id = sessions.project_id
        LEFT JOIN tasks ON tasks.task_id = sessions.task_id
        LEFT JOIN agents ON agents.agent_id = sessions.agent_id
        LEFT JOIN activity_log AS start_log
            ON start_log.project_id = sessions.project_id
           AND start_log.task_id = sessions.task_id
           AND start_log.action = 'provider_adapter_started'
           AND json_extract(start_log.details_json, '$.session_id') = sessions.session_id
        WHERE projects.state = 'active'
          AND {where_clause}
        ORDER BY
            CASE sessions.status WHEN 'active' THEN 0 ELSE 1 END,
            COALESCE(sessions.ended_at, sessions.started_at) DESC,
            sessions.rowid DESC
        LIMIT ?
        """.format(where_clause=" AND ".join(run_filters)),
        tuple(run_params + [safe_limit]),
    ).fetchall()
    runs = [
        {
            "session_id": row["session_id"],
            "task_id": row["task_id"],
            "issue_key": issue_keys.get(row["task_id"]) if row["task_id"] else None,
            "project_id": row["project_id"],
            "project_name": row["project_name"],
            "task_title": row["task_title"],
            "status": row["status"],
            "provider_type": row["provider_type"],
            "execution_mode": row["execution_mode"],
            "external_runtime": row["external_runtime"],
            "match_context": row["match_context"] or row["task_title"] or row["session_id"],
            "started_at": row["started_at"],
        }
        for row in run_rows
    ]

    artifact_filters = [
        """
        (
            artifacts.artifact_id LIKE ?
            OR COALESCE(artifacts.path, '') LIKE ?
            OR COALESCE(tasks.title, '') LIKE ?
            OR COALESCE(tasks.task_id, '') LIKE ?
            OR COALESCE(artifacts.artifact_type, '') LIKE ?
        )
        """
    ]
    artifact_params = [pattern, pattern, pattern, pattern, pattern]
    if project_id is not None:
        artifact_filters.append("artifacts.project_id = ?")
        artifact_params.append(project_id)
    if goal_id:
        artifact_filters.append("tasks.goal_id = ?")
        artifact_params.append(goal_id)
    if agent_id:
        artifact_filters.append("tasks.assigned_agent_id = ?")
        artifact_params.append(agent_id)
    if priority_min is not None:
        artifact_filters.append("tasks.priority >= ?")
        artifact_params.append(priority_min)

    artifact_rows = connection.execute(
        """
        SELECT
            artifacts.artifact_id,
            artifacts.project_id,
            projects.name AS project_name,
            artifacts.task_id,
            artifacts.session_id,
            artifacts.path AS artifact_path,
            artifacts.artifact_type,
            COALESCE(json_extract(artifacts.metadata_json, '$.artifact_state'), 'active') AS artifact_state,
            COALESCE(tasks.title, artifacts.path, artifacts.artifact_id) AS title,
            artifacts.created_at
        FROM artifacts
        JOIN projects ON projects.project_id = artifacts.project_id
        LEFT JOIN tasks ON tasks.task_id = artifacts.task_id
        WHERE projects.state = 'active'
          AND {where_clause}
        ORDER BY artifacts.created_at DESC, artifacts.rowid DESC
        LIMIT ?
        """.format(where_clause=" AND ".join(artifact_filters)),
        tuple(artifact_params + [safe_limit]),
    ).fetchall()
    artifacts = [
        {
            "artifact_id": row["artifact_id"],
            "task_id": row["task_id"],
            "issue_key": issue_keys.get(row["task_id"]) if row["task_id"] else None,
            "session_id": row["session_id"],
            "project_id": row["project_id"],
            "project_name": row["project_name"],
            "artifact_path": row["artifact_path"],
            "artifact_type": row["artifact_type"],
            "artifact_state": row["artifact_state"],
            "title": row["title"],
            "created_at": row["created_at"],
        }
        for row in artifact_rows
    ]

    event_filters = [
        """
        (
            activity_log.activity_id LIKE ?
            OR COALESCE(activity_log.action, '') LIKE ?
            OR COALESCE(activity_log.description, '') LIKE ?
            OR COALESCE(tasks.title, '') LIKE ?
            OR COALESCE(agents.display_name, '') LIKE ?
        )
        """
    ]
    event_params = [pattern, pattern, pattern, pattern, pattern]
    if project_id is not None:
        event_filters.append("activity_log.project_id = ?")
        event_params.append(project_id)
    if goal_id:
        event_filters.append("tasks.goal_id = ?")
        event_params.append(goal_id)
    if agent_id:
        event_filters.append("activity_log.agent_id = ?")
        event_params.append(agent_id)
    if priority_min is not None:
        event_filters.append("tasks.priority >= ?")
        event_params.append(priority_min)

    event_rows = connection.execute(
        """
        SELECT
            activity_log.activity_id AS event_id,
            activity_log.project_id,
            projects.name AS project_name,
            activity_log.task_id,
            json_extract(activity_log.details_json, '$.session_id') AS session_id,
            activity_log.agent_id,
            activity_log.action AS title,
            activity_log.description,
            activity_log.created_at
        FROM activity_log
        JOIN projects ON projects.project_id = activity_log.project_id
        LEFT JOIN tasks ON tasks.task_id = activity_log.task_id
        LEFT JOIN agents ON agents.agent_id = activity_log.agent_id
        WHERE projects.state = 'active'
          AND {where_clause}
        ORDER BY activity_log.created_at DESC, activity_log.rowid DESC
        LIMIT ?
        """.format(where_clause=" AND ".join(event_filters)),
        tuple(event_params + [safe_limit]),
    ).fetchall()
    events = [
        {
            "source": "activity",
            "event_id": row["event_id"],
            "project_id": row["project_id"],
            "project_name": row["project_name"],
            "task_id": row["task_id"],
            "issue_key": issue_keys.get(row["task_id"]) if row["task_id"] else None,
            "session_id": row["session_id"],
            "agent_id": row["agent_id"],
            "title": row["title"],
            "description": row["description"] or row["title"],
            "created_at": row["created_at"],
        }
        for row in event_rows
    ]

    memory = fetch_project_memory(connection, project_id, limit=safe_limit, search=search_value) if project_id is not None else []
    if goal_id or agent_id or priority_min is not None:
        memory = [item for item in memory if not goal_id and not agent_id and priority_min is None]

    return {
        "query": {
            "search": search_value,
            "goal_id": goal_id,
            "agent_id": agent_id,
            "priority_min": priority_min,
        },
        "summary": {
            "total_hits": len(issues) + len(runs) + len(artifacts) + len(events) + len(memory),
            "issue_hits": len(issues),
            "run_hits": len(runs),
            "artifact_hits": len(artifacts),
            "event_hits": len(events),
            "memory_hits": len(memory),
        },
        "issues": issues,
        "runs": runs,
        "artifacts": artifacts,
        "events": events,
        "memory": memory,
    }


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
        "execution_mode": start_details.get("execution_mode"),
        "external_runtime": start_details.get("external_runtime"),
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


def _session_artifacts(connection, project_paths, project_id, session_id):
    return fetch_artifacts(
        connection,
        project_paths,
        limit=12,
        offset=0,
        filters={"session_id": session_id},
        project_id=project_id,
    )


def fetch_run_detail(connection, project_paths, project_id, session_id):
    row = connection.execute(
        """
        SELECT
            sessions.session_id,
            sessions.project_id,
            sessions.agent_id,
            sessions.task_id,
            sessions.status,
            sessions.provider_type,
            sessions.progress_pct,
            sessions.status_message,
            sessions.last_heartbeat_at,
            sessions.started_at,
            sessions.ended_at,
            (
                SELECT activity_log.created_at
                FROM activity_log
                WHERE activity_log.project_id = sessions.project_id
                  AND activity_log.task_id = sessions.task_id
                  AND json_extract(activity_log.details_json, '$.session_id') = sessions.session_id
                ORDER BY activity_log.created_at DESC, activity_log.rowid DESC
                LIMIT 1
            ) AS last_activity_at,
            (
                SELECT activity_log.action
                FROM activity_log
                WHERE activity_log.project_id = sessions.project_id
                  AND activity_log.task_id = sessions.task_id
                  AND json_extract(activity_log.details_json, '$.session_id') = sessions.session_id
                ORDER BY activity_log.created_at DESC, activity_log.rowid DESC
                LIMIT 1
            ) AS last_activity_action,
            (
                SELECT COUNT(*)
                FROM activity_log
                WHERE activity_log.project_id = sessions.project_id
                  AND activity_log.task_id = sessions.task_id
                  AND json_extract(activity_log.details_json, '$.session_id') = sessions.session_id
            ) AS activity_count,
            tasks.title AS task_title,
            tasks.status AS task_status,
            tasks.review_state AS task_review_state,
            agents.display_name AS agent_name
        FROM sessions
        LEFT JOIN tasks ON tasks.task_id = sessions.task_id
        LEFT JOIN agents ON agents.agent_id = sessions.agent_id
        WHERE sessions.project_id = ?
          AND sessions.session_id = ?
        """,
        (project_id, session_id),
    ).fetchone()
    if row is None:
        return None

    issue_keys = issue_key_lookup(connection, project_id)
    envelope_root = project_paths.runtime_envelope_root(project_id, session_id)
    output_preview = _tail_console_preview(os.path.join(envelope_root, "runtime-output.txt"))
    stdout_preview = _tail_console_preview(os.path.join(envelope_root, "stdout.log"))
    stderr_preview = _tail_console_preview(os.path.join(envelope_root, "stderr.log"))
    activity = _session_activity(connection, project_id, row["task_id"], session_id, limit=24)
    start_details = _session_start_details(connection, project_id, row["task_id"], session_id)
    artifacts = _session_artifacts(connection, project_paths, project_id, session_id)
    phases = _derive_run_phases(activity, row["status"])
    current_step = next(
        (
            event["description"]
            for event in activity
            if event.get("description")
        ),
        row["status_message"],
    )
    return {
        **_run_row_to_dict(
            {
                **dict(row),
                "task_status": row["task_status"],
                "task_review_state": row["task_review_state"],
                "goal_id": None,
                "goal_title": None,
                "execution_mode": start_details.get("execution_mode"),
                "external_runtime": start_details.get("external_runtime"),
                "last_activity_at": row["last_activity_at"],
                "last_activity_action": row["last_activity_action"],
                "activity_count": row["activity_count"],
                "artifact_count": len(artifacts["items"]),
                "failure_count": 0,
            },
            issue_keys,
        ),
        "session_id": row["session_id"],
        "task_id": row["task_id"],
        "task_title": row["task_title"],
        "task_status": row["task_status"],
        "task_review_state": row["task_review_state"],
        "issue_key": issue_keys.get(row["task_id"]) if row["task_id"] else None,
        "agent_id": row["agent_id"],
        "agent_name": row["agent_name"],
        "provider_type": row["provider_type"],
        "execution_mode": start_details.get("execution_mode"),
        "external_runtime": start_details.get("external_runtime"),
        "timeout_seconds": start_details.get("timeout_seconds"),
        "command": start_details.get("command"),
        "runtime_root": start_details.get("runtime_root") or envelope_root,
        "current_step": current_step,
        "phases": phases,
        "memory_context": _run_memory_context(activity),
        "output_preview": output_preview,
        "stdout_preview": stdout_preview,
        "stderr_preview": stderr_preview,
        "activity": activity,
        "artifacts": artifacts["items"],
        "artifact_summary": artifacts["summary"],
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
            tasks.status AS task_status,
            tasks.review_state AS task_review_state,
            sessions.provider_type,
            sessions.status,
            sessions.progress_pct,
            sessions.status_message,
            sessions.last_heartbeat_at,
            sessions.started_at,
            sessions.ended_at,
            tasks.title AS task_title,
            json_extract(start_log.details_json, '$.execution_mode') AS execution_mode,
            json_extract(start_log.details_json, '$.external_runtime') AS external_runtime
        FROM sessions
        LEFT JOIN tasks ON tasks.task_id = sessions.task_id
        LEFT JOIN activity_log AS start_log
            ON start_log.project_id = sessions.project_id
           AND start_log.task_id = sessions.task_id
           AND start_log.action = 'provider_adapter_started'
           AND json_extract(start_log.details_json, '$.session_id') = sessions.session_id
        WHERE sessions.project_id = ?
          AND sessions.agent_id = ?
        ORDER BY sessions.started_at DESC, sessions.rowid DESC
        LIMIT 12
        """,
        (project_id, agent_id),
    ).fetchall()
    issue_keys = issue_key_lookup(connection, project_id)
    return [
        _run_row_to_dict(
            {
                **dict(row),
                "goal_id": None,
                "goal_title": None,
                "agent_id": agent_id,
                "agent_name": None,
                "artifact_count": 0,
                "failure_count": 0,
            },
            issue_keys,
        )
        for row in rows
    ]


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
            tasks.synthesis_origin,
            tasks.synthesis_key,
            tasks.acceptance_criteria_json,
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

    brownfield_grounding = build_brownfield_grounding(connection, project_id, dict(task_row), issue_keys=issue_keys)
    relationships = _task_relationships(connection, project_id, task_id, task_row["goal_id"], issue_keys)
    runs = _task_runs(connection, project_id, task_id)
    run_console = _issue_run_console(connection, project_paths, project_id, task_id, runs)
    history = fetch_incident_timeline(connection, project_id=project_id, task_id=task_id, limit=30, order="desc")["events"]
    verification_runs = fetch_verification_runs(connection, project_id=project_id, task_id=task_id, limit=10)
    failure_count_row = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM failure_log
        WHERE project_id = ?
          AND task_id = ?
        """,
        (project_id, task_id),
    ).fetchone()
    project_policy = fetch_project_review_policy(connection, project_id)
    review_decision = evaluate_review_decision_state(
        connection,
        dict(task_row),
        project_policy,
        verification_runs=verification_runs,
        failure_count=(failure_count_row["count"] if failure_count_row else 0),
    )
    git_workspace = fetch_task_git_workspace(connection, task_id)
    artifact_payload = fetch_artifacts(
        connection,
        project_paths,
        limit=10,
        offset=0,
        filters={"task_id": task_id},
        project_id=project_id,
    )
    related_memory = retrieve_relevant_memory(
        connection,
        project_id,
        task_row["title"],
        task_description=task_row["description"],
        goal_title=task_row["goal_title"],
        limit=4,
    )
    goal_explainability = None
    if task_row["goal_id"]:
        goal_plan = fetch_goal_explainability(connection, project_id, task_row["goal_id"])
        selected_plan_task = next(
            (item for item in goal_plan.get("tasks") or [] if item["task_id"] == task_id),
            None,
        )
        if selected_plan_task is not None:
            goal_explainability = {
                **goal_plan,
                "task": selected_plan_task,
            }
    delivery = fetch_task_delivery_status(connection, project_paths, task_id, project_id=project_id)
    latest_run = runs[0] if runs else None
    recovery_playbook = _issue_recovery_playbook(
        dict(task_row),
        review_decision,
        (failure_count_row["count"] if failure_count_row else 0),
        latest_run,
        verification_runs,
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
            "synthesis_origin": task_row["synthesis_origin"],
            "synthesis_key": task_row["synthesis_key"],
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
        "review_decision": review_decision,
        "recovery_playbook": recovery_playbook,
        "goal_explainability": goal_explainability,
        "brownfield_grounding": brownfield_grounding,
        "memory_context": related_memory,
        "delivery": delivery,
        "git_workspace": git_workspace,
    }
