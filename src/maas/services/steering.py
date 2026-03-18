"""Operator steering actions for the board."""

import json

from maas.ids import generate_id
from maas.services.bootstrap import (
    BROWNFIELD_PENDING_REVIEW_STATE,
    BROWNFIELD_REVIEW_TASK_TITLE,
    default_onboarding_review_overrides,
    normalize_onboarding_review_overrides,
)
from maas.services.artifacts import artifact_scope_rows, purge_artifact_scope
from maas.services.dead_letter import resolve_dead_letter_entries_for_task
from maas.services.recovery_policy import (
    fetch_project_recovery_policy,
    recover_and_requeue_cooldown_seconds,
    retry_deadline,
)
from maas.services.repo_plan import refresh_repo_grounded_plan
from maas.services.scheduler import refresh_ready_tasks
from maas.services.alerts import (
    resolve_brownfield_onboarding_alerts,
    resolve_stale_heartbeat_alerts,
    resolve_task_session_failed_alerts,
)
from maas.services.failure_memory import (
    failure_attempt_count,
    dismiss_quarantine_queue_entry,
    reopen_quarantine_queue_entry,
    resolve_repeated_failure_alerts,
    restore_quarantined_session_artifacts,
)
from maas.services.security import (
    TASK_EXECUTION_CAPABILITIES,
    ensure_board_action_allowed,
    grant_task_capabilities,
    revoke_task_capabilities,
)

RECOVERABLE_FAILURE_REVIEW_STATES = ("session_failed", "stale_session")


def _load_project_config(connection, project_id):
    row = connection.execute(
        "SELECT config_json FROM projects WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    if row is None:
        return {}
    try:
        config = json.loads(row["config_json"] or "{}")
    except ValueError:
        return {}
    return config if isinstance(config, dict) else {}


def _save_project_config(connection, project_id, config):
    connection.execute(
        "UPDATE projects SET config_json = ? WHERE project_id = ?",
        (json.dumps(config), project_id),
    )


def _is_brownfield_onboarding_review_task(connection, task):
    config = _load_project_config(connection, task["project_id"])
    onboarding = config.get("onboarding") or {}
    return onboarding.get("mode") == "brownfield" and task["title"] == BROWNFIELD_REVIEW_TASK_TITLE


def _set_project_onboarding_review_state(connection, project_id, actor_id, status, task_id=None):
    config = _load_project_config(connection, project_id)
    onboarding = dict(config.get("onboarding") or {})
    reviewed_at = connection.execute("SELECT CURRENT_TIMESTAMP AS ts").fetchone()["ts"]
    onboarding["review_status"] = status
    onboarding["reviewed_by"] = actor_id
    onboarding["reviewed_at"] = reviewed_at
    if task_id:
        onboarding["review_task_id"] = task_id
    config["onboarding"] = onboarding
    _save_project_config(connection, project_id, config)


def _task_source_paths(task):
    try:
        criteria = json.loads(task["acceptance_criteria_json"] or "[]")
    except ValueError:
        return []
    paths = []
    for criterion in criteria:
        if not isinstance(criterion, dict) or criterion.get("type") != "source_path_exists":
            continue
        for path in criterion.get("paths") or []:
            if isinstance(path, str) and path not in paths:
                paths.append(path)
    return paths


def _task_paths_all_ignored(task, ignored_paths):
    if not ignored_paths:
        return False
    scoped_paths = _task_source_paths(task)
    if not scoped_paths:
        return False
    return all(
        any(path == ignored or path.startswith(ignored + "/") for ignored in ignored_paths)
        for path in scoped_paths
    )


def _workflow_review_task_label(task, discovery_summary):
    prefix = "Validate imported workflow: "
    if not task["title"].startswith(prefix):
        return None
    task_name = task["title"][len(prefix) :].strip()
    task_paths = set(_task_source_paths(task))
    exact_match = None
    fallback_match = None
    for item in discovery_summary.get("workflow_details") or []:
        label = item.get("label")
        if not isinstance(label, str):
            continue
        _, _, workflow_name = label.partition(":")
        if workflow_name != task_name:
            continue
        item_path = item.get("path")
        if item_path and task_paths and item_path in task_paths:
            exact_match = label
            break
        if fallback_match is None:
            fallback_match = label
    return exact_match or fallback_match


def _load_onboarding_review_decisions(connection, project_id):
    config = _load_project_config(connection, project_id)
    onboarding = dict(config.get("onboarding") or {})
    discovery_summary = onboarding.get("discovery_summary") or {}
    review_overrides = onboarding.get("review_overrides") or default_onboarding_review_overrides(discovery_summary)
    return discovery_summary, normalize_onboarding_review_overrides(discovery_summary, review_overrides)


def _release_brownfield_onboarding_tasks(connection, project_id):
    discovery_summary, review_overrides = _load_onboarding_review_decisions(connection, project_id)
    gated_rows = [
        dict(row)
        for row in connection.execute(
            """
            SELECT task_id, title, acceptance_criteria_json
            FROM tasks
            WHERE project_id = ?
              AND status = 'blocked'
              AND review_state = ?
            """,
            (project_id, BROWNFIELD_PENDING_REVIEW_STATE),
        ).fetchall()
    ]
    if not gated_rows:
        return {"released_task_ids": [], "ignored_task_ids": []}

    accepted_workflow_labels = set(review_overrides.get("accepted_workflow_labels") or [])
    ignored_paths = list(review_overrides.get("ignored_paths") or [])
    released_task_ids = []
    ignored_task_ids = []
    for task in gated_rows:
        workflow_label = _workflow_review_task_label(task, discovery_summary)
        should_ignore = False
        if workflow_label is not None and workflow_label not in accepted_workflow_labels:
            should_ignore = True
        elif _task_paths_all_ignored(task, ignored_paths):
            should_ignore = True

        if should_ignore:
            ignored_task_ids.append(task["task_id"])
        else:
            released_task_ids.append(task["task_id"])

    if released_task_ids:
        placeholders = ", ".join(["?"] * len(released_task_ids))
        connection.execute(
            """
            UPDATE tasks
            SET status = 'planned',
                review_state = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE task_id IN ({0})
            """.format(placeholders),
            tuple(released_task_ids),
        )
    if ignored_task_ids:
        placeholders = ", ".join(["?"] * len(ignored_task_ids))
        connection.execute(
            """
            UPDATE tasks
            SET status = 'cancelled',
                review_state = 'ignored_onboarding_scope',
                updated_at = CURRENT_TIMESTAMP
            WHERE task_id IN ({0})
            """.format(placeholders),
            tuple(ignored_task_ids),
        )
    if released_task_ids:
        refresh_ready_tasks(connection, commit=False)
    return {"released_task_ids": released_task_ids, "ignored_task_ids": ignored_task_ids}


def _audit(connection, project_id, actor_id, action_type, resource_type, resource_id, detail):
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            generate_id("audit"),
            project_id,
            actor_id,
            action_type,
            resource_type,
            resource_id,
            json.dumps(detail),
        ),
    )


def _activity(connection, project_id, agent_id, task_id, action, description, severity="info"):
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, agent_id, task_id, action, category, description, severity
        ) VALUES (?, ?, ?, ?, ?, 'steering', ?, ?)
        """,
        (generate_id("act"), project_id, agent_id, task_id, action, description, severity),
    )


def _mark_task_for_replan_internal(
    connection,
    task,
    actor_id,
    audit_action,
    activity_action,
    activity_description,
    resolution_reason,
):
    if task["assigned_agent_id"]:
        revoke_task_capabilities(
            connection,
            task["project_id"],
            task["task_id"],
            agent_id=task["assigned_agent_id"],
            reason=resolution_reason,
            revoked_by=actor_id,
        )

    connection.execute(
        """
        UPDATE tasks
        SET status = 'blocked',
            assigned_agent_id = NULL,
            review_state = 'needs_replan',
            next_retry_at = NULL,
            next_retry_reason = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ?
        """,
        (task["task_id"],),
    )
    resolved_dead_letter_entries = resolve_dead_letter_entries_for_task(
        connection,
        task["project_id"],
        task["task_id"],
        resolution_reason,
    )
    _audit(
        connection,
        task["project_id"],
        actor_id,
        audit_action,
        "task",
        task["task_id"],
        {
            "previous_status": task["status"],
            "previous_review_state": task["review_state"],
            "previous_agent_id": task["assigned_agent_id"],
            "previous_next_retry_at": task["next_retry_at"],
            "previous_next_retry_reason": task["next_retry_reason"],
            "resolved_dead_letter_entries": resolved_dead_letter_entries,
        },
    )
    _activity(
        connection,
        task["project_id"],
        task["assigned_agent_id"],
        task["task_id"],
        activity_action,
        activity_description,
        severity="warning",
    )
    resolve_repeated_failure_alerts(
        connection,
        task["project_id"],
        task["task_id"],
        actor_id,
        resolution_reason=resolution_reason,
    )
    resolve_task_session_failed_alerts(
        connection,
        task["project_id"],
        task["task_id"],
        actor_id,
        reason=resolution_reason,
    )
    return {"task_id": task["task_id"], "status": "blocked", "review_state": "needs_replan"}


def _load_purgeable_artifact_scope(connection, project_paths, actor_id, task_id=None, session_id=None):
    rows, _ = artifact_scope_rows(connection, project_paths, task_id=task_id, session_id=session_id)
    if not rows:
        raise ValueError("Artifact scope not found")

    scope_type = "task" if task_id else "session"
    scope_id = task_id or session_id
    project_id = rows[0]["project_id"]
    ensure_board_action_allowed(connection, actor_id, project_id, "purge_artifacts", scope_type, scope_id)

    session_ids = sorted({row["session_id"] for row in rows if row["session_id"]})
    if session_ids:
        placeholders = ", ".join(["?"] * len(session_ids))
        open_queue = connection.execute(
            """
            SELECT queue_id
            FROM quarantine_queue
            WHERE session_id IN ({0}) AND status = 'open'
            LIMIT 1
            """.format(placeholders),
            tuple(session_ids),
        ).fetchone()
        if open_queue is not None:
            raise ValueError("Cannot purge artifacts from an open quarantine incident")

    return {
        "project_id": project_id,
        "task_id": rows[0]["task_id"],
        "scope_type": scope_type,
        "scope_id": scope_id,
    }


def review_task(connection, task_id, actor_id, decision):
    task = connection.execute(
        """
        SELECT task_id, project_id, assigned_agent_id, status, title, review_state
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if task is None:
        raise ValueError("Task not found")
    ensure_board_action_allowed(connection, actor_id, task["project_id"], "review_task", "task", task_id)
    if task["status"] != "review":
        raise ValueError("Task is not in review")
    if decision not in ("approve", "reject"):
        raise ValueError("Unsupported review decision")
    is_brownfield_onboarding_review = _is_brownfield_onboarding_review_task(connection, task)
    audit_detail = {"decision": decision}

    if decision == "approve" and is_brownfield_onboarding_review:
        connection.execute(
            """
            UPDATE tasks
            SET status = 'done', review_state = 'approved', updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ?
            """,
            (task_id,),
        )
        release_result = _release_brownfield_onboarding_tasks(connection, task["project_id"])
        _set_project_onboarding_review_state(connection, task["project_id"], actor_id, "approved", task_id=task_id)
        repo_plan_result = refresh_repo_grounded_plan(
            connection,
            task["project_id"],
            actor_id,
            commit=False,
            enforce_permissions=False,
        )
        resolved_alert_ids = resolve_brownfield_onboarding_alerts(
            connection,
            task["project_id"],
            actor_id,
            reason="brownfield_onboarding_approved",
        )
        description = "Brownfield onboarding approved; imported work released and repo-grounded planning refreshed."
        audit_detail.update(
            {
                "brownfield_onboarding": True,
                "released_task_ids": release_result["released_task_ids"],
                "ignored_task_ids": release_result["ignored_task_ids"],
                "repo_plan_created_task_ids": repo_plan_result["created_task_ids"],
                "repo_plan_updated_task_ids": repo_plan_result["updated_task_ids"],
                "resolved_alert_ids": resolved_alert_ids,
            }
        )
    elif decision == "approve":
        connection.execute(
            """
            UPDATE tasks
            SET status = 'done', review_state = 'approved', updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ?
            """,
            (task_id,),
        )
        description = "Review approved; task marked done."
    elif is_brownfield_onboarding_review:
        connection.execute(
            """
            UPDATE tasks
            SET status = 'planned',
                review_state = 'changes_requested',
                updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ?
            """,
            (task_id,),
        )
        _set_project_onboarding_review_state(
            connection,
            task["project_id"],
            actor_id,
            "changes_requested",
            task_id=task_id,
        )
        description = "Brownfield onboarding rejected; imported work remains gated while requested changes are reworked."
        audit_detail["brownfield_onboarding"] = True
    else:
        connection.execute(
            """
            UPDATE tasks
            SET status = 'planned',
                review_state = 'changes_requested',
                updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ?
            """,
            (task_id,),
        )
        description = "Review rejected; task returned to the assignable queue."

    _audit(
        connection,
        task["project_id"],
        actor_id,
        "review_task",
        "task",
        task_id,
        audit_detail,
    )
    _activity(connection, task["project_id"], task["assigned_agent_id"], task_id, "review_decision", description)
    connection.commit()
    return {"task_id": task_id, "decision": decision}


def halt_task(connection, task_id, actor_id):
    task = connection.execute(
        """
        SELECT task_id, project_id, assigned_agent_id, status
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if task is None:
        raise ValueError("Task not found")
    ensure_board_action_allowed(connection, actor_id, task["project_id"], "halt_task", "task", task_id)
    if task["status"] in ("done", "cancelled"):
        raise ValueError("Task cannot be halted from status {0}".format(task["status"]))

    connection.execute(
        """
        UPDATE tasks
        SET status = 'cancelled', review_state = 'halted_by_operator', updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ?
        """,
        (task_id,),
    )
    connection.execute(
        """
        UPDATE sessions
        SET status = 'cancelled', status_message = 'Halted by operator', ended_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ? AND status = 'active'
        """,
        (task_id,),
    )
    if task["assigned_agent_id"]:
        revoke_task_capabilities(
            connection,
            task["project_id"],
            task_id,
            agent_id=task["assigned_agent_id"],
            reason="task_halted",
            revoked_by=actor_id,
        )
        connection.execute(
            """
            UPDATE agents
            SET status = CASE WHEN status = 'paused' THEN 'paused' ELSE 'idle' END,
                current_task_id = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE agent_id = ? AND current_task_id = ?
            """,
            (task["assigned_agent_id"], task_id),
        )

    _audit(
        connection,
        task["project_id"],
        actor_id,
        "halt_task",
        "task",
        task_id,
        {"previous_status": task["status"]},
    )
    _activity(
        connection,
        task["project_id"],
        task["assigned_agent_id"],
        task_id,
        "halted",
        "Task halted by operator.",
        severity="warning",
    )
    connection.commit()
    return {"task_id": task_id, "status": "cancelled"}


def recover_task(connection, task_id, actor_id):
    task = _load_recoverable_task(connection, task_id, actor_id)
    _reset_recoverable_task(
        connection,
        task,
        actor_id,
        audit_action_type="recover_task",
        activity_action="recovered",
        activity_description="Task returned to the planning queue after failure recovery.",
    )
    connection.commit()
    return {"task_id": task_id, "status": "planned"}


def set_task_retry_limit(connection, task_id, actor_id, auto_retry_limit=None):
    task = connection.execute(
        """
        SELECT task_id, project_id, assigned_agent_id, status, auto_retry_limit
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if task is None:
        raise ValueError("Task not found")
    ensure_board_action_allowed(connection, actor_id, task["project_id"], "set_task_retry_limit", "task", task_id)
    if task["status"] in ("done", "cancelled"):
        raise ValueError("Retry limit cannot be changed for tasks in status {0}".format(task["status"]))
    if auto_retry_limit is not None:
        try:
            normalized_limit = int(auto_retry_limit)
        except (TypeError, ValueError):
            raise ValueError("Retry limit must be an integer")
        if normalized_limit < 0:
            raise ValueError("Retry limit must be greater than or equal to zero")
    else:
        normalized_limit = None

    if task["auto_retry_limit"] == normalized_limit:
        return {"task_id": task_id, "auto_retry_limit": normalized_limit}

    connection.execute(
        """
        UPDATE tasks
        SET auto_retry_limit = ?, updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ?
        """,
        (normalized_limit, task_id),
    )
    _audit(
        connection,
        task["project_id"],
        actor_id,
        "set_task_retry_limit",
        "task",
        task_id,
        {
            "previous_auto_retry_limit": task["auto_retry_limit"],
            "auto_retry_limit": normalized_limit,
        },
    )
    _activity(
        connection,
        task["project_id"],
        task["assigned_agent_id"],
        task_id,
        "retry_limit_updated",
        (
            "Task retry override cleared; task now follows the project recovery policy."
            if normalized_limit is None
            else "Task retry override set to {0}.".format(normalized_limit)
        ),
    )
    connection.commit()
    return {"task_id": task_id, "auto_retry_limit": normalized_limit}


def release_task_retry_backoff(connection, task_id, actor_id):
    task = connection.execute(
        """
        SELECT task_id, project_id, assigned_agent_id, status, review_state, next_retry_at, next_retry_reason
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if task is None:
        raise ValueError("Task not found")
    ensure_board_action_allowed(connection, actor_id, task["project_id"], "release_task_retry_backoff", "task", task_id)
    if task["status"] in ("done", "cancelled"):
        raise ValueError("Retry backoff cannot be released for tasks in status {0}".format(task["status"]))
    if task["review_state"] != "retry_backoff" and task["next_retry_at"] is None:
        raise ValueError("Task is not currently waiting on retry backoff")

    connection.execute(
        """
        UPDATE tasks
        SET next_retry_at = NULL,
            next_retry_reason = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ?
        """,
        (task_id,),
    )
    refreshed = refresh_ready_tasks(connection, commit=False)
    task_after = connection.execute(
        """
        SELECT status, review_state, next_retry_at, next_retry_reason
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    _audit(
        connection,
        task["project_id"],
        actor_id,
        "release_task_retry_backoff",
        "task",
        task_id,
        {
            "previous_review_state": task["review_state"],
            "previous_next_retry_at": task["next_retry_at"],
            "previous_next_retry_reason": task["next_retry_reason"],
            "ready_changes": refreshed,
        },
    )
    _activity(
        connection,
        task["project_id"],
        task["assigned_agent_id"],
        task_id,
        "retry_backoff_released",
        "Task retry cooldown released by operator and readiness re-evaluated.",
    )
    connection.commit()
    return {
        "task_id": task_id,
        "status": task_after["status"],
        "review_state": task_after["review_state"],
        "next_retry_at": task_after["next_retry_at"],
        "next_retry_reason": task_after["next_retry_reason"],
    }


def reset_task_retry_state(connection, task_id, actor_id):
    task = connection.execute(
        """
        SELECT
            task_id,
            project_id,
            assigned_agent_id,
            status,
            review_state,
            retry_count,
            last_retry_at,
            last_retry_reason,
            next_retry_at,
            next_retry_reason
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if task is None:
        raise ValueError("Task not found")
    ensure_board_action_allowed(connection, actor_id, task["project_id"], "reset_task_retry_state", "task", task_id)
    if task["status"] in ("done", "cancelled"):
        raise ValueError("Retry state cannot be reset for tasks in status {0}".format(task["status"]))
    has_retry_state = any(
        (
            task["retry_count"],
            task["last_retry_at"],
            task["last_retry_reason"],
            task["next_retry_at"],
            task["next_retry_reason"],
            task["review_state"] == "retry_backoff",
        )
    )
    if not has_retry_state:
        raise ValueError("Task has no retry state to reset")

    connection.execute(
        """
        UPDATE tasks
        SET retry_count = 0,
            last_retry_at = NULL,
            last_retry_reason = NULL,
            next_retry_at = NULL,
            next_retry_reason = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ?
        """,
        (task_id,),
    )
    refreshed = refresh_ready_tasks(connection, commit=False)
    task_after = connection.execute(
        """
        SELECT status, review_state, retry_count, last_retry_at, last_retry_reason, next_retry_at, next_retry_reason
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    _audit(
        connection,
        task["project_id"],
        actor_id,
        "reset_task_retry_state",
        "task",
        task_id,
        {
            "previous_retry_count": task["retry_count"],
            "previous_last_retry_at": task["last_retry_at"],
            "previous_last_retry_reason": task["last_retry_reason"],
            "previous_next_retry_at": task["next_retry_at"],
            "previous_next_retry_reason": task["next_retry_reason"],
            "previous_review_state": task["review_state"],
            "ready_changes": refreshed,
        },
    )
    _activity(
        connection,
        task["project_id"],
        task["assigned_agent_id"],
        task_id,
        "retry_state_reset",
        "Task retry history and cooldown metadata reset by operator.",
    )
    connection.commit()
    return {
        "task_id": task_id,
        "status": task_after["status"],
        "review_state": task_after["review_state"],
        "retry_count": task_after["retry_count"],
        "last_retry_at": task_after["last_retry_at"],
        "last_retry_reason": task_after["last_retry_reason"],
        "next_retry_at": task_after["next_retry_at"],
        "next_retry_reason": task_after["next_retry_reason"],
    }


def reset_task_circuit_breaker(connection, task_id, actor_id):
    task = connection.execute(
        """
        SELECT task_id, project_id, assigned_agent_id, status, review_state, retry_count
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if task is None:
        raise ValueError("Task not found")
    ensure_board_action_allowed(connection, actor_id, task["project_id"], "reset_task_circuit_breaker", "task", task_id)
    if task["status"] != "blocked" or task["review_state"] != "circuit_breaker_open":
        raise ValueError("Task does not currently have an open circuit breaker")

    connection.execute(
        """
        UPDATE tasks
        SET status = 'planned',
            review_state = NULL,
            assigned_agent_id = NULL,
            retry_count = 0,
            last_retry_at = NULL,
            last_retry_reason = NULL,
            next_retry_at = NULL,
            next_retry_reason = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ?
        """,
        (task_id,),
    )
    refreshed = refresh_ready_tasks(connection, commit=False)
    task_after = connection.execute(
        """
        SELECT status, review_state, retry_count, next_retry_at, next_retry_reason
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    resolved_dlq_entries = resolve_dead_letter_entries_for_task(
        connection,
        task["project_id"],
        task_id,
        "circuit_breaker_reset",
    )
    resolve_repeated_failure_alerts(
        connection,
        task["project_id"],
        task_id,
        actor_id,
        resolution_reason="circuit_breaker_reset",
    )
    resolve_task_session_failed_alerts(
        connection,
        task["project_id"],
        task_id,
        actor_id,
        reason="circuit_breaker_reset",
        activity_description="Task failure alerts resolved after circuit breaker reset.",
    )
    _audit(
        connection,
        task["project_id"],
        actor_id,
        "reset_task_circuit_breaker",
        "task",
        task_id,
        {
            "previous_status": task["status"],
            "previous_review_state": task["review_state"],
            "previous_retry_count": task["retry_count"],
            "resolved_dead_letter_entries": resolved_dlq_entries,
            "ready_changes": refreshed,
        },
    )
    _activity(
        connection,
        task["project_id"],
        task["assigned_agent_id"],
        task_id,
        "circuit_breaker_reset",
        "Task circuit breaker reset by operator and returned to readiness evaluation.",
    )
    connection.commit()
    return {
        "task_id": task_id,
        "status": task_after["status"],
        "review_state": task_after["review_state"],
        "retry_count": task_after["retry_count"],
        "next_retry_at": task_after["next_retry_at"],
        "next_retry_reason": task_after["next_retry_reason"],
    }


def mark_task_for_replan(connection, task_id, actor_id):
    task = connection.execute(
        """
        SELECT
            task_id,
            project_id,
            assigned_agent_id,
            status,
            review_state,
            retry_count,
            next_retry_at,
            next_retry_reason
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if task is None:
        raise ValueError("Task not found")
    ensure_board_action_allowed(connection, actor_id, task["project_id"], "mark_task_for_replan", "task", task_id)
    if task["status"] in ("done", "cancelled", "in_progress", "review"):
        raise ValueError("Task cannot be marked for replanning from status {0}".format(task["status"]))
    if task["review_state"] == "needs_replan":
        raise ValueError("Task is already marked for replanning")
    if not (
        task["review_state"] in ("session_failed", "stale_session", "retry_backoff")
        or (task["retry_count"] or 0) > 0
        or task["next_retry_at"] is not None
    ):
        raise ValueError("Task does not currently require replanning")
    active_session = connection.execute(
        """
        SELECT session_id
        FROM sessions
        WHERE task_id = ? AND status = 'active'
        LIMIT 1
        """,
        (task_id,),
    ).fetchone()
    if active_session is not None:
        raise ValueError("Task cannot be marked for replanning while a session is active")

    result = _mark_task_for_replan_internal(
        connection,
        task,
        actor_id,
        audit_action="mark_task_for_replan",
        activity_action="marked_for_replan",
        activity_description="Task removed from retry/recovery flow and marked for manual replanning.",
        resolution_reason="task_marked_for_replan",
    )
    connection.commit()
    return result


def finish_task_replan(connection, task_id, actor_id):
    task = connection.execute(
        """
        SELECT task_id, project_id, assigned_agent_id, status, review_state
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if task is None:
        raise ValueError("Task not found")
    ensure_board_action_allowed(connection, actor_id, task["project_id"], "finish_task_replan", "task", task_id)
    if task["status"] != "blocked" or task["review_state"] != "needs_replan":
        raise ValueError("Task is not currently waiting on replanning")

    connection.execute(
        """
        UPDATE tasks
        SET status = 'planned',
            review_state = NULL,
            next_retry_at = NULL,
            next_retry_reason = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ?
        """,
        (task_id,),
    )
    refreshed = refresh_ready_tasks(connection, commit=False)
    task_after = connection.execute(
        """
        SELECT status, review_state, next_retry_at, next_retry_reason
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    _audit(
        connection,
        task["project_id"],
        actor_id,
        "finish_task_replan",
        "task",
        task_id,
        {
            "previous_status": task["status"],
            "previous_review_state": task["review_state"],
            "resolved_dead_letter_entries": resolve_dead_letter_entries_for_task(
                connection,
                task["project_id"],
                task_id,
                "replan_finished",
            ),
            "ready_changes": refreshed,
        },
    )
    _activity(
        connection,
        task["project_id"],
        task["assigned_agent_id"],
        task_id,
        "replan_finished",
        "Task replanning marked complete and returned to readiness evaluation.",
    )
    connection.commit()
    return {
        "task_id": task_id,
        "status": task_after["status"],
        "review_state": task_after["review_state"],
        "next_retry_at": task_after["next_retry_at"],
        "next_retry_reason": task_after["next_retry_reason"],
    }


def recover_and_requeue_task(connection, task_id, actor_id):
    task = _load_recoverable_task(connection, task_id, actor_id)
    refreshed_task = _recover_and_requeue_task(connection, task, actor_id)
    connection.commit()
    return {
        "task_id": task_id,
        "status": refreshed_task["status"],
        "review_state": refreshed_task["review_state"],
        "next_retry_at": refreshed_task["next_retry_at"],
        "next_retry_reason": refreshed_task["next_retry_reason"],
    }


def _recover_and_requeue_task(connection, task, actor_id, consume_retry_reason=None):
    recovery_policy = fetch_project_recovery_policy(connection, task["project_id"])
    failure_count = failure_attempt_count(connection, task["task_id"])
    cooldown_seconds = recover_and_requeue_cooldown_seconds(recovery_policy, failure_count)
    next_retry_at = retry_deadline(cooldown_seconds)
    next_retry_reason = "recover_and_requeue" if next_retry_at is not None else None
    _reset_recoverable_task(
        connection,
        task,
        actor_id,
        audit_action_type="recover_and_requeue_task",
        activity_action="recovered_and_requeued",
        activity_description="Task recovered from failure and returned to readiness evaluation.",
        next_retry_at=next_retry_at,
        next_retry_reason=next_retry_reason,
        consume_retry_reason=consume_retry_reason,
        extra_audit_detail={
            "failure_count": failure_count,
            "cooldown_seconds": cooldown_seconds,
        },
    )
    refresh_ready_tasks(connection, commit=False)
    return connection.execute(
        """
        SELECT status, review_state, next_retry_at, next_retry_reason
        FROM tasks
        WHERE task_id = ?
        """,
        (task["task_id"],),
    ).fetchone()


def _load_recoverable_task(connection, task_id, actor_id):
    task = connection.execute(
        """
        SELECT task_id, project_id, assigned_agent_id, status, review_state
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if task is None:
        raise ValueError("Task not found")
    ensure_board_action_allowed(connection, actor_id, task["project_id"], "recover_task", "task", task_id)
    if task["status"] != "blocked":
        raise ValueError("Only blocked tasks can be recovered")
    if task["review_state"] not in RECOVERABLE_FAILURE_REVIEW_STATES:
        raise ValueError("Task is not blocked by a recoverable failure")
    return task


def _reset_recoverable_task(
    connection,
    task,
    actor_id,
    audit_action_type,
    activity_action,
    activity_description,
    next_retry_at=None,
    next_retry_reason=None,
    consume_retry_reason=None,
    extra_audit_detail=None,
):
    if task["assigned_agent_id"]:
        revoke_task_capabilities(
            connection,
            task["project_id"],
            task["task_id"],
            agent_id=task["assigned_agent_id"],
            reason="task_recovered",
            revoked_by=actor_id,
        )

    connection.execute(
        """
        UPDATE tasks
        SET status = 'planned',
            assigned_agent_id = NULL,
            progress_pct = 0,
            review_state = NULL,
            last_heartbeat_at = NULL,
            retry_count = CASE
                WHEN ? IS NULL THEN retry_count
                ELSE COALESCE(retry_count, 0) + 1
            END,
            last_retry_at = CASE
                WHEN ? IS NULL THEN last_retry_at
                ELSE CURRENT_TIMESTAMP
            END,
            last_retry_reason = CASE
                WHEN ? IS NULL THEN last_retry_reason
                ELSE ?
            END,
            next_retry_at = ?,
            next_retry_reason = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ?
        """,
        (
            consume_retry_reason,
            consume_retry_reason,
            consume_retry_reason,
            consume_retry_reason,
            next_retry_at,
            next_retry_reason,
            task["task_id"],
        ),
    )
    audit_detail = {
        "previous_status": task["status"],
        "previous_review_state": task["review_state"],
        "previous_agent_id": task["assigned_agent_id"],
    }
    if consume_retry_reason is not None:
        audit_detail["consumed_retry_reason"] = consume_retry_reason
    if next_retry_at is not None:
        audit_detail["next_retry_at"] = next_retry_at
        audit_detail["next_retry_reason"] = next_retry_reason
    if extra_audit_detail:
        audit_detail.update(extra_audit_detail)
    _audit(
        connection,
        task["project_id"],
        actor_id,
        audit_action_type,
        "task",
        task["task_id"],
        audit_detail,
    )
    _activity(
        connection,
        task["project_id"],
        task["assigned_agent_id"],
        task["task_id"],
        activity_action,
        activity_description,
    )
    resolve_repeated_failure_alerts(
        connection,
        task["project_id"],
        task["task_id"],
        actor_id,
        resolution_reason="task_recovered",
    )
    resolve_task_session_failed_alerts(
        connection,
        task["project_id"],
        task["task_id"],
        actor_id,
        reason="task_recovered",
    )


def resolve_task_repeated_failures(connection, task_id, actor_id):
    task = connection.execute(
        """
        SELECT task_id, project_id, status
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if task is None:
        raise ValueError("Task not found")
    ensure_board_action_allowed(
        connection,
        actor_id,
        task["project_id"],
        "resolve_task_repeated_failures",
        "task",
        task_id,
    )

    resolved_alert_ids = resolve_repeated_failure_alerts(
        connection,
        task["project_id"],
        task_id,
        actor_id,
        resolution_reason="operator_triaged",
    )
    if not resolved_alert_ids:
        raise ValueError("Task has no open repeated-failure alert")

    connection.commit()
    return {
        "task_id": task_id,
        "resolved_alert_ids": resolved_alert_ids,
        "resolved_count": len(resolved_alert_ids),
        "status": task["status"],
    }


def _restore_quarantine_session(connection, project_paths, queue_row, actor_id, resource_type, resource_id):
    ensure_board_action_allowed(
        connection,
        actor_id,
        queue_row["project_id"],
        "restore_quarantine_artifacts",
        resource_type,
        resource_id,
    )
    if queue_row["session_id"] is None:
        raise ValueError("Quarantine entry is not linked to a session")

    restored_artifacts = restore_quarantined_session_artifacts(connection, project_paths, queue_row["session_id"])
    if not restored_artifacts:
        raise ValueError("Quarantine entry has no quarantined artifacts to restore")

    _audit(
        connection,
        queue_row["project_id"],
        actor_id,
        "restore_quarantine_artifacts",
        resource_type,
        resource_id,
        {"session_id": queue_row["session_id"], "restored_count": len(restored_artifacts)},
    )
    _activity(
        connection,
        queue_row["project_id"],
        actor_id,
        queue_row["task_id"],
        "artifacts_restored",
        "Quarantined artifacts restored to the active artifact workspace.",
    )
    return restored_artifacts


def restore_quarantine_entry(connection, project_paths, queue_id, actor_id):
    queue_entry = connection.execute(
        """
        SELECT queue_id, project_id, task_id, session_id, status
        FROM quarantine_queue
        WHERE queue_id = ?
        """,
        (queue_id,),
    ).fetchone()
    if queue_entry is None:
        raise ValueError("Quarantine entry not found")
    if queue_entry["status"] != "open":
        raise ValueError("Only open quarantine entries can be restored")

    restored_artifacts = _restore_quarantine_session(
        connection,
        project_paths,
        queue_entry,
        actor_id,
        resource_type="quarantine",
        resource_id=queue_id,
    )
    connection.commit()
    return {
        "queue_id": queue_id,
        "session_id": queue_entry["session_id"],
        "restored_artifacts": restored_artifacts,
        "restored_count": len(restored_artifacts),
        "status": "restored",
    }


def restore_and_requeue_quarantine_entry(connection, project_paths, queue_id, actor_id):
    queue_entry = connection.execute(
        """
        SELECT queue_id, project_id, task_id, session_id, status
        FROM quarantine_queue
        WHERE queue_id = ?
        """,
        (queue_id,),
    ).fetchone()
    if queue_entry is None:
        raise ValueError("Quarantine entry not found")
    if queue_entry["status"] != "open":
        raise ValueError("Only open quarantine entries can be restored and requeued")
    if queue_entry["task_id"] is None:
        raise ValueError("Quarantine entry is not linked to a recoverable task")

    task = _load_recoverable_task(connection, queue_entry["task_id"], actor_id)
    restored_artifacts = _restore_quarantine_session(
        connection,
        project_paths,
        queue_entry,
        actor_id,
        resource_type="quarantine",
        resource_id=queue_id,
    )
    refreshed_task = _recover_and_requeue_task(connection, task, actor_id)
    connection.commit()
    return {
        "queue_id": queue_id,
        "task_id": task["task_id"],
        "session_id": queue_entry["session_id"],
        "restored_artifacts": restored_artifacts,
        "restored_count": len(restored_artifacts),
        "status": "restored",
        "task_status": refreshed_task["status"],
        "task_review_state": refreshed_task["review_state"],
        "next_retry_at": refreshed_task["next_retry_at"],
        "next_retry_reason": refreshed_task["next_retry_reason"],
    }


def restore_failure_artifacts(connection, project_paths, failure_id, actor_id):
    failure = connection.execute(
        """
        SELECT failure_id, project_id, task_id, session_id
        FROM failure_log
        WHERE failure_id = ?
        """,
        (failure_id,),
    ).fetchone()
    if failure is None:
        raise ValueError("Failure not found")
    ensure_board_action_allowed(
        connection,
        actor_id,
        failure["project_id"],
        "restore_failure_artifacts",
        "failure",
        failure_id,
    )
    if failure["session_id"] is None:
        raise ValueError("Failure is not linked to a session")

    restored_artifacts = _restore_quarantine_session(
        connection,
        project_paths,
        failure,
        actor_id,
        resource_type="failure",
        resource_id=failure_id,
    )
    connection.commit()
    return {
        "failure_id": failure_id,
        "session_id": failure["session_id"],
        "restored_artifacts": restored_artifacts,
        "restored_count": len(restored_artifacts),
    }


def dismiss_quarantine_entry(connection, queue_id, actor_id):
    queue_entry = connection.execute(
        """
        SELECT queue_id, project_id, task_id, session_id, status, artifact_count
        FROM quarantine_queue
        WHERE queue_id = ?
        """,
        (queue_id,),
    ).fetchone()
    if queue_entry is None:
        raise ValueError("Quarantine entry not found")
    ensure_board_action_allowed(
        connection,
        actor_id,
        queue_entry["project_id"],
        "dismiss_quarantine_entry",
        "quarantine",
        queue_id,
    )
    dismissed_entry = dismiss_quarantine_queue_entry(connection, queue_id)

    _audit(
        connection,
        queue_entry["project_id"],
        actor_id,
        "dismiss_quarantine_entry",
        "quarantine",
        queue_id,
        {"session_id": queue_entry["session_id"], "artifact_count": queue_entry["artifact_count"]},
    )
    _activity(
        connection,
        queue_entry["project_id"],
        actor_id,
        queue_entry["task_id"],
        "quarantine_dismissed",
        "Quarantined artifacts left isolated after operator review.",
        severity="warning",
    )
    connection.commit()
    return {
        "queue_id": queue_id,
        "session_id": dismissed_entry["session_id"],
        "status": "dismissed",
        "artifact_count": dismissed_entry["artifact_count"],
    }


def reopen_quarantine_entry(connection, queue_id, actor_id):
    queue_entry = connection.execute(
        """
        SELECT queue_id, project_id, task_id, session_id, status, artifact_count
        FROM quarantine_queue
        WHERE queue_id = ?
        """,
        (queue_id,),
    ).fetchone()
    if queue_entry is None:
        raise ValueError("Quarantine entry not found")
    ensure_board_action_allowed(
        connection,
        actor_id,
        queue_entry["project_id"],
        "reopen_quarantine_entry",
        "quarantine",
        queue_id,
    )
    reopened_entry = reopen_quarantine_queue_entry(connection, queue_id)

    _audit(
        connection,
        queue_entry["project_id"],
        actor_id,
        "reopen_quarantine_entry",
        "quarantine",
        queue_id,
        {"session_id": queue_entry["session_id"], "artifact_count": queue_entry["artifact_count"]},
    )
    _activity(
        connection,
        queue_entry["project_id"],
        actor_id,
        queue_entry["task_id"],
        "quarantine_reopened",
        "Dismissed quarantined artifacts returned to the open review queue.",
        severity="warning",
    )
    connection.commit()
    return {
        "queue_id": queue_id,
        "session_id": reopened_entry["session_id"],
        "status": "open",
        "artifact_count": reopened_entry["artifact_count"],
    }


def purge_task_artifacts(connection, project_paths, task_id, actor_id):
    scope = _load_purgeable_artifact_scope(connection, project_paths, actor_id, task_id=task_id)
    result = purge_artifact_scope(connection, project_paths, task_id=task_id)
    if result is None:
        raise ValueError("Artifact scope not found")

    _audit(
        connection,
        scope["project_id"],
        actor_id,
        "purge_artifacts",
        "task",
        task_id,
        result,
    )
    _activity(
        connection,
        scope["project_id"],
        actor_id,
        scope["task_id"],
        "artifact_scope_purged",
        "Purged {0} artifact records from task scope.".format(result["deleted_artifact_count"]),
        severity="warning",
    )
    connection.commit()
    return result


def purge_session_artifacts(connection, project_paths, session_id, actor_id):
    scope = _load_purgeable_artifact_scope(connection, project_paths, actor_id, session_id=session_id)
    result = purge_artifact_scope(connection, project_paths, session_id=session_id)
    if result is None:
        raise ValueError("Artifact scope not found")

    _audit(
        connection,
        scope["project_id"],
        actor_id,
        "purge_artifacts",
        "session",
        session_id,
        result,
    )
    _activity(
        connection,
        scope["project_id"],
        actor_id,
        scope["task_id"],
        "artifact_scope_purged",
        "Purged {0} artifact records from session scope.".format(result["deleted_artifact_count"]),
        severity="warning",
    )
    connection.commit()
    return result


def reprioritize_task(connection, task_id, actor_id, priority):
    task = connection.execute(
        "SELECT task_id, project_id, assigned_agent_id FROM tasks WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    if task is None:
        raise ValueError("Task not found")
    ensure_board_action_allowed(connection, actor_id, task["project_id"], "reprioritize_task", "task", task_id)
    connection.execute(
        "UPDATE tasks SET priority = ?, updated_at = CURRENT_TIMESTAMP WHERE task_id = ?",
        (priority, task_id),
    )
    _audit(
        connection,
        task["project_id"],
        actor_id,
        "reprioritize_task",
        "task",
        task_id,
        {"priority": priority},
    )
    _activity(
        connection,
        task["project_id"],
        task["assigned_agent_id"],
        task_id,
        "reprioritized",
        "Task priority updated to {0}.".format(priority),
    )
    connection.commit()
    return {"task_id": task_id, "priority": priority}


def reassign_task(connection, task_id, actor_id, agent_id):
    task = connection.execute(
        "SELECT task_id, project_id, status, assigned_agent_id FROM tasks WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    if task is None:
        raise ValueError("Task not found")
    ensure_board_action_allowed(connection, actor_id, task["project_id"], "reassign_task", "task", task_id)
    if task["status"] == "in_progress":
        raise ValueError("In-progress tasks cannot be reassigned")
    agent = connection.execute(
        "SELECT agent_id FROM agents WHERE agent_id = ? AND project_id = ?",
        (agent_id, task["project_id"]),
    ).fetchone()
    if agent is None:
        raise ValueError("Agent not found")
    connection.execute(
        """
        UPDATE tasks
        SET assigned_agent_id = ?, status = CASE WHEN status = 'planned' THEN 'assigned' ELSE status END,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ?
        """,
        (agent_id, task_id),
    )
    if task["assigned_agent_id"] and task["assigned_agent_id"] != agent_id:
        revoke_task_capabilities(
            connection,
            task["project_id"],
            task_id,
            agent_id=task["assigned_agent_id"],
            reason="task_reassigned",
            revoked_by=actor_id,
        )
    grant_task_capabilities(
        connection,
        task["project_id"],
        task_id,
        agent_id,
        TASK_EXECUTION_CAPABILITIES,
        granted_by=actor_id,
    )
    _audit(
        connection,
        task["project_id"],
        actor_id,
        "reassign_task",
        "task",
        task_id,
        {"agent_id": agent_id},
    )
    _activity(
        connection,
        task["project_id"],
        agent_id,
        task_id,
        "reassigned",
        "Task reassigned to {0}.".format(agent_id),
    )
    connection.commit()
    return {"task_id": task_id, "agent_id": agent_id}


def pause_agent(connection, agent_id, actor_id):
    agent = connection.execute(
        "SELECT agent_id, project_id, current_task_id FROM agents WHERE agent_id = ?",
        (agent_id,),
    ).fetchone()
    if agent is None:
        raise ValueError("Agent not found")
    ensure_board_action_allowed(connection, actor_id, agent["project_id"], "pause_agent", "agent", agent_id)
    connection.execute(
        """
        UPDATE agents
        SET status = 'paused', updated_at = CURRENT_TIMESTAMP
        WHERE agent_id = ?
        """,
        (agent_id,),
    )
    if agent["current_task_id"]:
        connection.execute(
            """
            UPDATE tasks
            SET status = 'blocked', review_state = 'paused_by_operator', updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ? AND status = 'in_progress'
            """,
            (agent["current_task_id"],),
        )
    _audit(
        connection,
        agent["project_id"],
        actor_id,
        "pause_agent",
        "agent",
        agent_id,
        {"current_task_id": agent["current_task_id"]},
    )
    _activity(
        connection,
        agent["project_id"],
        agent_id,
        agent["current_task_id"],
        "paused",
        "Agent paused by operator.",
        severity="warning",
    )
    connection.commit()
    return {"agent_id": agent_id, "status": "paused"}


def resume_agent(connection, agent_id, actor_id):
    agent = connection.execute(
        "SELECT agent_id, project_id, current_task_id FROM agents WHERE agent_id = ?",
        (agent_id,),
    ).fetchone()
    if agent is None:
        raise ValueError("Agent not found")
    ensure_board_action_allowed(connection, actor_id, agent["project_id"], "resume_agent", "agent", agent_id)
    connection.execute(
        """
        UPDATE agents
        SET status = CASE WHEN current_task_id IS NULL THEN 'idle' ELSE 'running' END,
            updated_at = CURRENT_TIMESTAMP
        WHERE agent_id = ?
        """,
        (agent_id,),
    )
    if agent["current_task_id"]:
        connection.execute(
            """
            UPDATE tasks
            SET status = 'in_progress', review_state = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ? AND status = 'blocked'
            """,
            (agent["current_task_id"],),
        )
    _audit(
        connection,
        agent["project_id"],
        actor_id,
        "resume_agent",
        "agent",
        agent_id,
        {"current_task_id": agent["current_task_id"]},
    )
    _activity(
        connection,
        agent["project_id"],
        agent_id,
        agent["current_task_id"],
        "resumed",
        "Agent resumed by operator.",
    )
    connection.commit()
    return {"agent_id": agent_id, "status": "running" if agent["current_task_id"] else "idle"}


def recover_agent(connection, agent_id, actor_id):
    agent = connection.execute(
        """
        SELECT agent_id, project_id, status, current_task_id
        FROM agents
        WHERE agent_id = ?
        """,
        (agent_id,),
    ).fetchone()
    if agent is None:
        raise ValueError("Agent not found")
    ensure_board_action_allowed(connection, actor_id, agent["project_id"], "recover_agent", "agent", agent_id)
    if agent["status"] != "error":
        raise ValueError("Only error agents can be recovered")
    if agent["current_task_id"] is not None:
        raise ValueError("Agent cannot be recovered while still attached to a task")

    active_session = connection.execute(
        """
        SELECT session_id
        FROM sessions
        WHERE agent_id = ? AND status = 'active'
        LIMIT 1
        """,
        (agent_id,),
    ).fetchone()
    if active_session is not None:
        raise ValueError("Agent cannot be recovered while an active session exists")

    connection.execute(
        """
        UPDATE agents
        SET status = 'idle', updated_at = CURRENT_TIMESTAMP
        WHERE agent_id = ?
        """,
        (agent_id,),
    )
    _audit(
        connection,
        agent["project_id"],
        actor_id,
        "recover_agent",
        "agent",
        agent_id,
        {"previous_status": agent["status"]},
    )
    _activity(
        connection,
        agent["project_id"],
        agent_id,
        None,
        "agent_recovered",
        "Agent recovered from error state.",
    )
    resolve_stale_heartbeat_alerts(
        connection,
        agent["project_id"],
        agent_id,
        actor_id,
        reason="agent_recovered",
    )
    connection.commit()
    return {"agent_id": agent_id, "status": "idle"}
