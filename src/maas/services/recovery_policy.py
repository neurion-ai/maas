"""Helpers for project-level recovery and retry policy."""

from datetime import datetime, timedelta
import json

from maas.ids import generate_id
from maas.services.alerts import (
    RECOVERABLE_FAILURE_REVIEW_STATES,
    REPEATED_TASK_FAILURE_PATTERN,
    infer_operator_action,
)
from maas.services.dead_letter import fetch_dead_letter_queue
from maas.services.failure_memory import fetch_repeated_failure_tasks
from maas.services.projects import resolve_project_id
from maas.services.scheduler import adaptive_replan_feedback
from maas.services.security import ensure_board_action_allowed


DEFAULT_RECOVERY_POLICY = {
    "auto_retry_timeout_sessions": False,
    "auto_retry_failed_sessions": False,
    "auto_recover_blocked_tasks": False,
    "auto_dlq_retry_exhausted_tasks": False,
    "max_timed_out_retries": 1,
    "max_failed_session_retries": 1,
    "timed_out_retry_cooldown_seconds": 60,
    "failed_session_retry_cooldown_seconds": 120,
    "recover_and_requeue_cooldown_seconds": 30,
    "retry_backoff_multiplier": 2,
    "retry_backoff_max_seconds": 900,
}


RECOVERY_POLICY_FIELD_RULES = {
    "auto_retry_timeout_sessions": {"type": "bool"},
    "auto_retry_failed_sessions": {"type": "bool"},
    "auto_recover_blocked_tasks": {"type": "bool"},
    "auto_dlq_retry_exhausted_tasks": {"type": "bool"},
    "max_timed_out_retries": {"type": "int", "minimum": 0},
    "max_failed_session_retries": {"type": "int", "minimum": 0},
    "timed_out_retry_cooldown_seconds": {"type": "int", "minimum": 0},
    "failed_session_retry_cooldown_seconds": {"type": "int", "minimum": 0},
    "recover_and_requeue_cooldown_seconds": {"type": "int", "minimum": 0},
    "retry_backoff_multiplier": {"type": "int", "minimum": 1},
    "retry_backoff_max_seconds": {"type": "int", "minimum": 0},
}


def _parse_bool(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("1", "true", "yes", "on"):
            return True
        if normalized in ("0", "false", "no", "off", ""):
            return False
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _parse_int(value, default, minimum=None):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    if minimum is not None:
        parsed = max(int(minimum), parsed)
    return parsed


def _coerce_bool_setting(field_name, value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("1", "true", "yes", "on"):
            return True
        if normalized in ("0", "false", "no", "off"):
            return False
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    raise ValueError("{0} must be a boolean.".format(field_name))


def _coerce_int_setting(field_name, value, minimum):
    if isinstance(value, bool):
        raise ValueError("{0} must be an integer.".format(field_name))
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        if not value.is_integer():
            raise ValueError("{0} must be an integer.".format(field_name))
        parsed = int(value)
    else:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise ValueError("{0} must be an integer.".format(field_name))
    if parsed < minimum:
        raise ValueError("{0} must be greater than or equal to {1}.".format(field_name, minimum))
    return parsed


def _resolve_project_id(connection, project_id=None):
    resolved = resolve_project_id(connection, project_id)
    if resolved is None:
        raise ValueError("Project not found")
    return resolved


def _retry_delay_preview(base_seconds, attempt_limit, project_policy):
    preview = []
    for attempt in range(1, max(0, int(attempt_limit)) + 1):
        preview.append(
            {
                "attempt": attempt,
                "delay_seconds": retry_backoff_seconds(base_seconds, attempt, project_policy),
            }
        )
    return preview


def _recovery_summary(connection, project_id):
    auto_recovery_candidates = fetch_auto_recovery_candidate_tasks(connection, project_id=project_id, limit=None)
    open_dead_letter_entries = connection.execute(
        """
        SELECT COUNT(*)
        FROM dead_letter_queue
        WHERE project_id = ? AND status = 'open'
        """,
        (project_id,),
    ).fetchone()[0]
    tasks_row = connection.execute(
        """
        SELECT
            SUM(CASE WHEN review_state = 'retry_backoff' THEN 1 ELSE 0 END) AS retry_backoff_tasks,
            SUM(CASE WHEN status = 'blocked' AND review_state = 'needs_replan' THEN 1 ELSE 0 END) AS needs_replan_tasks,
            SUM(
                CASE
                    WHEN status NOT IN ('done', 'cancelled', 'in_progress', 'review')
                         AND COALESCE(review_state, '') != 'needs_replan'
                         AND (
                             review_state IN ('session_failed', 'stale_session', 'retry_backoff')
                             OR COALESCE(retry_count, 0) > 0
                             OR next_retry_at IS NOT NULL
                         ) THEN 1
                    ELSE 0
                END
            ) AS replanning_candidates,
            SUM(
                CASE
                    WHEN status NOT IN ('done', 'cancelled') AND COALESCE(retry_count, 0) > 0 THEN 1
                    ELSE 0
                END
            ) AS tasks_with_retry_history,
            SUM(
                CASE
                    WHEN status = 'blocked' AND review_state IN ('session_failed', 'stale_session') THEN 1
                    ELSE 0
                END
            ) AS recoverable_blocked_tasks
        FROM tasks
        WHERE project_id = ?
        """,
        (project_id,),
    ).fetchone()
    open_quarantine_entries = connection.execute(
        """
        SELECT COUNT(*)
        FROM quarantine_queue
        WHERE project_id = ? AND status = 'open'
        """,
        (project_id,),
    ).fetchone()[0]
    open_failure_alerts = connection.execute(
        """
        SELECT COUNT(*)
        FROM alerts
        WHERE project_id = ?
          AND status = 'open'
          AND title = 'Task session failed'
        """,
        (project_id,),
    ).fetchone()[0]
    open_repeated_failure_alerts = connection.execute(
        """
        SELECT COUNT(*)
        FROM alerts
        WHERE project_id = ?
          AND status = 'open'
          AND title = 'Repeated task failures'
        """,
        (project_id,),
    ).fetchone()[0]
    open_stale_agent_alerts = connection.execute(
        """
        SELECT COUNT(*)
        FROM alerts
        WHERE project_id = ?
          AND status = 'open'
          AND title = 'Stale agent heartbeat'
        """,
        (project_id,),
    ).fetchone()[0]
    tasks_with_retry_overrides = connection.execute(
        """
        SELECT COUNT(*)
        FROM tasks
        WHERE project_id = ?
          AND auto_retry_limit IS NOT NULL
          AND status NOT IN ('done', 'cancelled')
        """,
        (project_id,),
    ).fetchone()[0]
    return {
        "retry_backoff_tasks": tasks_row["retry_backoff_tasks"] or 0,
        "needs_replan_tasks": tasks_row["needs_replan_tasks"] or 0,
        "replanning_candidates": tasks_row["replanning_candidates"] or 0,
        "tasks_with_retry_history": tasks_row["tasks_with_retry_history"] or 0,
        "recoverable_blocked_tasks": tasks_row["recoverable_blocked_tasks"] or 0,
        "auto_recovery_candidates": len(auto_recovery_candidates),
        "open_dead_letter_entries": open_dead_letter_entries or 0,
        "tasks_with_retry_overrides": tasks_with_retry_overrides or 0,
        "open_quarantine_entries": open_quarantine_entries or 0,
        "open_failure_alerts": open_failure_alerts or 0,
        "open_repeated_failure_alerts": open_repeated_failure_alerts or 0,
        "open_stale_agent_alerts": open_stale_agent_alerts or 0,
    }


def _recovery_task_items(connection, project_id, where_clause, params, limit=8):
    query = """
        SELECT
            tasks.task_id,
            tasks.project_id,
            tasks.assigned_agent_id,
            tasks.title,
            tasks.status,
            tasks.review_state,
            tasks.priority,
            tasks.retry_count,
            tasks.auto_retry_limit,
            tasks.last_retry_at,
            tasks.last_retry_reason,
            tasks.next_retry_at,
            tasks.next_retry_reason,
            tasks.updated_at,
            goals.title AS goal_title,
            agents.display_name AS agent_name,
            failures.failure_count,
            failures.latest_failure_at
        FROM tasks
        LEFT JOIN goals ON goals.goal_id = tasks.goal_id
        LEFT JOIN agents ON agents.agent_id = tasks.assigned_agent_id
        LEFT JOIN (
            SELECT task_id, COUNT(*) AS failure_count, MAX(created_at) AS latest_failure_at
            FROM failure_log
            WHERE task_id IS NOT NULL
            GROUP BY task_id
        ) AS failures ON failures.task_id = tasks.task_id
        WHERE tasks.project_id = ?
          AND {0}
        ORDER BY tasks.priority DESC, tasks.updated_at DESC, tasks.created_at ASC
    """.format(where_clause)
    query_params = [project_id] + list(params)
    if limit is not None:
        query += "\n        LIMIT ?"
        query_params.append(limit)
    rows = connection.execute(query, tuple(query_params)).fetchall()
    return [dict(row) for row in rows]


def _recovery_quarantine_entries(connection, project_id, limit=8):
    rows = connection.execute(
        """
        SELECT
            quarantine_queue.queue_id,
            quarantine_queue.project_id,
            quarantine_queue.session_id,
            quarantine_queue.task_id,
            quarantine_queue.failure_id,
            quarantine_queue.status,
            quarantine_queue.reason,
            quarantine_queue.artifact_count,
            quarantine_queue.resolution_note,
            quarantine_queue.created_at,
            quarantine_queue.updated_at,
            quarantine_queue.resolved_at,
            failure_log.failure_type,
            failure_log.summary,
            tasks.title AS task_title,
            tasks.status AS task_status,
            tasks.review_state AS task_review_state,
            agents.display_name AS agent_name
        FROM quarantine_queue
        LEFT JOIN failure_log ON failure_log.failure_id = quarantine_queue.failure_id
        LEFT JOIN tasks ON tasks.task_id = quarantine_queue.task_id
        LEFT JOIN agents ON agents.agent_id = failure_log.agent_id
        WHERE quarantine_queue.project_id = ?
          AND quarantine_queue.status = 'open'
        ORDER BY quarantine_queue.created_at DESC
        LIMIT ?
        """,
        (project_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def _recovery_open_failure_alerts(connection, project_id, limit=8):
    rows = connection.execute(
        """
        SELECT alert_id, project_id, severity, title, description, status, created_at
        FROM alerts
        WHERE project_id = ?
          AND status = 'open'
          AND title = 'Task session failed'
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (project_id, limit),
    ).fetchall()
    alerts = []
    for row in rows:
        alert = dict(row)
        operator_action = infer_operator_action(connection, alert["title"], alert["description"])
        if operator_action is not None:
            alert["operator_action"] = operator_action
        alerts.append(alert)
    return alerts


def _recovery_stale_agent_alerts(connection, project_id, limit=8):
    rows = connection.execute(
        """
        SELECT alert_id, project_id, severity, title, description, status, created_at
        FROM alerts
        WHERE project_id = ?
          AND status = 'open'
          AND title = 'Stale agent heartbeat'
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (project_id, limit),
    ).fetchall()
    alerts = []
    for row in rows:
        alert = dict(row)
        operator_action = infer_operator_action(connection, alert["title"], alert["description"])
        if operator_action is not None:
            alert["operator_action"] = operator_action
        alerts.append(alert)
    return alerts


def _recovery_repeated_failure_incidents(connection, project_id, limit=8):
    return fetch_repeated_failure_tasks(connection, limit=limit, project_id=project_id, actionable_only=True)


def _replan_reason(task):
    if task.get("review_state") == "retry_backoff":
        return "Cooling down repeatedly; operator replanning can break the retry loop."
    if task.get("review_state") in ("session_failed", "stale_session"):
        return "Failure-blocked and likely needs plan or scope changes."
    if task.get("next_retry_at"):
        return "Queued for another retry; operator replanning can replace the current retry path."
    if (task.get("retry_count") or 0) > 0:
        return "Retry history suggests the current plan is unstable."
    return "Operator replanning recommended."


def _open_quarantine_task_ids(connection, project_id):
    rows = connection.execute(
        """
        SELECT DISTINCT task_id
        FROM quarantine_queue
        WHERE project_id = ?
          AND status = 'open'
          AND task_id IS NOT NULL
        """,
        (project_id,),
    ).fetchall()
    return {row["task_id"] for row in rows}


def _open_repeated_failure_task_ids(connection, project_id):
    rows = connection.execute(
        """
        SELECT description
        FROM alerts
        WHERE project_id = ?
          AND status IN ('open', 'acknowledged')
          AND title = 'Repeated task failures'
        """,
        (project_id,),
    ).fetchall()
    task_ids = set()
    for row in rows:
        match = REPEATED_TASK_FAILURE_PATTERN.match(row["description"] or "")
        if match is not None:
            task_ids.add(match.group("task_id"))
    return task_ids


def _auto_recovery_retry_limit(task_row, project_policy):
    if task_row.get("review_state") == "stale_session":
        return task_timed_out_retry_limit(task_row, project_policy)
    return task_failed_session_retry_limit(task_row, project_policy)


def _is_auto_recovery_candidate(task_row, project_policy, open_quarantine_task_ids, repeated_failure_task_ids):
    if task_row.get("status") != "blocked":
        return False
    if task_row.get("review_state") not in RECOVERABLE_FAILURE_REVIEW_STATES:
        return False
    if task_row["task_id"] in open_quarantine_task_ids:
        return False
    if task_row["task_id"] in repeated_failure_task_ids:
        return False
    retry_limit = _auto_recovery_retry_limit(task_row, project_policy)
    return retry_limit > 0 and (task_row.get("retry_count") or 0) < retry_limit


def fetch_auto_recovery_candidate_tasks(connection, project_id=None, limit=8):
    project_id = _resolve_project_id(connection, project_id)
    project_policy = fetch_project_recovery_policy(connection, project_id)
    open_quarantine_task_ids = _open_quarantine_task_ids(connection, project_id)
    repeated_failure_task_ids = _open_repeated_failure_task_ids(connection, project_id)
    items = _recovery_task_items(
        connection,
        project_id,
        "tasks.status = 'blocked' AND tasks.review_state IN ('session_failed', 'stale_session')",
        [],
        limit=None,
    )
    candidates = [
        item
        for item in items
        if _is_auto_recovery_candidate(item, project_policy, open_quarantine_task_ids, repeated_failure_task_ids)
    ]
    if limit is None:
        return candidates
    return candidates[:limit]


def _replanning_candidate_tasks(connection, project_id, limit=8):
    items = _recovery_task_items(
        connection,
        project_id,
        (
            "tasks.status NOT IN ('done', 'cancelled', 'in_progress', 'review') "
            "AND COALESCE(tasks.review_state, '') != 'needs_replan' "
            "AND (tasks.review_state IN ('session_failed', 'stale_session', 'retry_backoff') "
            "OR COALESCE(tasks.retry_count, 0) > 0 "
            "OR tasks.next_retry_at IS NOT NULL)"
        ),
        [],
        limit=limit,
    )
    for item in items:
        item["replan_reason"] = _replan_reason(item)
        feedback = adaptive_replan_feedback(item)
        if feedback:
            item.update(feedback)
    return items


def _needs_replan_tasks(connection, project_id, limit=8):
    items = _recovery_task_items(
        connection,
        project_id,
        "tasks.status = 'blocked' AND tasks.review_state = 'needs_replan'",
        [],
        limit=limit,
    )
    for item in items:
        item["replan_reason"] = "Marked by an operator for manual replanning before requeue."
        feedback = adaptive_replan_feedback(item)
        if feedback:
            item.update(feedback)
    return items


def fetch_project_recovery_overview(connection, project_id=None):
    project_id = _resolve_project_id(connection, project_id)
    policy = fetch_project_recovery_policy(connection, project_id)
    return {
        "project_id": project_id,
        "policy": policy,
        "defaults": dict(DEFAULT_RECOVERY_POLICY),
        "summary": _recovery_summary(connection, project_id),
        "backoff_preview": {
            "timed_out_retry_delays": _retry_delay_preview(
                policy["timed_out_retry_cooldown_seconds"],
                policy["max_timed_out_retries"],
                policy,
            ),
            "failed_session_retry_delays": _retry_delay_preview(
                policy["failed_session_retry_cooldown_seconds"],
                policy["max_failed_session_retries"],
                policy,
            ),
            "recover_and_requeue_delays": _retry_delay_preview(
                policy["recover_and_requeue_cooldown_seconds"],
                3,
                policy,
            ),
        },
        "task_retry_overrides": _recovery_task_items(
            connection,
            project_id,
            "tasks.auto_retry_limit IS NOT NULL AND tasks.status NOT IN ('done', 'cancelled')",
            [],
        ),
        "auto_recovery_candidates": fetch_auto_recovery_candidate_tasks(connection, project_id=project_id),
        "recoverable_blocked_tasks": _recovery_task_items(
            connection,
            project_id,
            "tasks.status = 'blocked' AND tasks.review_state IN ('session_failed', 'stale_session')",
            [],
        ),
        "task_retry_history": _recovery_task_items(
            connection,
            project_id,
            "tasks.status NOT IN ('done', 'cancelled') AND COALESCE(tasks.retry_count, 0) > 0",
            [],
        ),
        "replanning_candidates": _replanning_candidate_tasks(connection, project_id),
        "needs_replan_tasks": _needs_replan_tasks(connection, project_id),
        "active_retry_backoff": _recovery_task_items(
            connection,
            project_id,
            (
                "tasks.status IN ('planned', 'ready', 'assigned', 'blocked') "
                "AND (tasks.review_state = 'retry_backoff' OR tasks.next_retry_at IS NOT NULL)"
            ),
            [],
        ),
        "dead_letter_entries": fetch_dead_letter_queue(connection, project_id),
        "open_quarantine_entries": _recovery_quarantine_entries(connection, project_id),
        "open_failure_alerts": _recovery_open_failure_alerts(connection, project_id),
        "open_stale_agent_alerts": _recovery_stale_agent_alerts(connection, project_id),
        "repeated_failure_incidents": _recovery_repeated_failure_incidents(connection, project_id),
    }


def update_project_recovery_policy(connection, actor_id, updates, project_id=None):
    project_id = _resolve_project_id(connection, project_id)
    ensure_board_action_allowed(
        connection,
        actor_id,
        project_id,
        "configure_recovery_policy",
        "project",
        project_id,
    )

    requested_updates = updates or {}
    unknown_keys = sorted(set(requested_updates) - set(RECOVERY_POLICY_FIELD_RULES))
    if unknown_keys:
        raise ValueError("Unsupported recovery policy settings: {0}.".format(", ".join(unknown_keys)))
    if not requested_updates:
        return fetch_project_recovery_overview(connection, project_id)

    normalized_updates = {}
    for field_name, value in requested_updates.items():
        field_rules = RECOVERY_POLICY_FIELD_RULES[field_name]
        if field_rules["type"] == "bool":
            normalized_updates[field_name] = _coerce_bool_setting(field_name, value)
        else:
            normalized_updates[field_name] = _coerce_int_setting(field_name, value, field_rules["minimum"])

    json_set_parts = []
    params = []
    for field_name, value in normalized_updates.items():
        json_set_parts.append("?, ?")
        params.extend(["$.recovery.{0}".format(field_name), value])

    connection.execute(
        """
        UPDATE projects
        SET config_json = json_set(
                CASE
                    WHEN json_valid(config_json) THEN config_json
                    ELSE '{{}}'
                END,
                {0}
            ),
            updated_at = CURRENT_TIMESTAMP
        WHERE project_id = ?
        """.format(", ".join(json_set_parts)),
        tuple(params + [project_id]),
    )
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, 'configure_recovery_policy', 'project', ?, ?)
        """,
        (
            generate_id("audit"),
            project_id,
            actor_id,
            project_id,
            json.dumps({"recovery": normalized_updates}),
        ),
    )
    connection.commit()
    return fetch_project_recovery_overview(connection, project_id)


def fetch_project_recovery_policy(connection, project_id):
    row = connection.execute(
        """
        SELECT config_json
        FROM projects
        WHERE project_id = ?
        """,
        (project_id,),
    ).fetchone()
    if row is None:
        return dict(DEFAULT_RECOVERY_POLICY)

    try:
        config = json.loads(row["config_json"] or "{}")
    except json.JSONDecodeError:
        config = {}

    recovery = config.get("recovery") or {}
    return {
        "auto_retry_timeout_sessions": _parse_bool(
            recovery.get("auto_retry_timeout_sessions"),
            DEFAULT_RECOVERY_POLICY["auto_retry_timeout_sessions"],
        ),
        "auto_retry_failed_sessions": _parse_bool(
            recovery.get("auto_retry_failed_sessions"),
            DEFAULT_RECOVERY_POLICY["auto_retry_failed_sessions"],
        ),
        "auto_recover_blocked_tasks": _parse_bool(
            recovery.get("auto_recover_blocked_tasks"),
            DEFAULT_RECOVERY_POLICY["auto_recover_blocked_tasks"],
        ),
        "auto_dlq_retry_exhausted_tasks": _parse_bool(
            recovery.get("auto_dlq_retry_exhausted_tasks"),
            DEFAULT_RECOVERY_POLICY["auto_dlq_retry_exhausted_tasks"],
        ),
        "max_timed_out_retries": _parse_int(
            recovery.get("max_timed_out_retries"),
            DEFAULT_RECOVERY_POLICY["max_timed_out_retries"],
            minimum=0,
        ),
        "max_failed_session_retries": _parse_int(
            recovery.get("max_failed_session_retries"),
            DEFAULT_RECOVERY_POLICY["max_failed_session_retries"],
            minimum=0,
        ),
        "timed_out_retry_cooldown_seconds": _parse_int(
            recovery.get("timed_out_retry_cooldown_seconds"),
            DEFAULT_RECOVERY_POLICY["timed_out_retry_cooldown_seconds"],
            minimum=0,
        ),
        "failed_session_retry_cooldown_seconds": _parse_int(
            recovery.get("failed_session_retry_cooldown_seconds"),
            DEFAULT_RECOVERY_POLICY["failed_session_retry_cooldown_seconds"],
            minimum=0,
        ),
        "recover_and_requeue_cooldown_seconds": _parse_int(
            recovery.get("recover_and_requeue_cooldown_seconds"),
            DEFAULT_RECOVERY_POLICY["recover_and_requeue_cooldown_seconds"],
            minimum=0,
        ),
        "retry_backoff_multiplier": _parse_int(
            recovery.get("retry_backoff_multiplier"),
            DEFAULT_RECOVERY_POLICY["retry_backoff_multiplier"],
            minimum=1,
        ),
        "retry_backoff_max_seconds": _parse_int(
            recovery.get("retry_backoff_max_seconds"),
            DEFAULT_RECOVERY_POLICY["retry_backoff_max_seconds"],
            minimum=0,
        ),
    }


def task_timed_out_retry_limit(task_row, project_policy):
    if task_row["auto_retry_limit"] is not None:
        return int(task_row["auto_retry_limit"])
    return int(project_policy["max_timed_out_retries"])


def task_failed_session_retry_limit(task_row, project_policy):
    if task_row["auto_retry_limit"] is not None:
        return int(task_row["auto_retry_limit"])
    return int(project_policy["max_failed_session_retries"])


def retry_backoff_seconds(base_seconds, attempt_count, project_policy):
    if base_seconds <= 0:
        return 0

    attempt_count = max(1, int(attempt_count))
    multiplier = max(1, int(project_policy["retry_backoff_multiplier"]))
    max_seconds = max(int(base_seconds), int(project_policy["retry_backoff_max_seconds"]))
    delay = int(base_seconds) * (multiplier ** (attempt_count - 1))
    return min(delay, max_seconds)


def timed_out_retry_cooldown_seconds(project_policy, retry_count):
    return retry_backoff_seconds(project_policy["timed_out_retry_cooldown_seconds"], retry_count, project_policy)


def failed_session_retry_cooldown_seconds(project_policy, retry_count):
    return retry_backoff_seconds(project_policy["failed_session_retry_cooldown_seconds"], retry_count, project_policy)


def recover_and_requeue_cooldown_seconds(project_policy, failure_count):
    return retry_backoff_seconds(project_policy["recover_and_requeue_cooldown_seconds"], failure_count, project_policy)


def retry_deadline(seconds):
    if seconds <= 0:
        return None
    return (datetime.utcnow() + timedelta(seconds=int(seconds))).strftime("%Y-%m-%d %H:%M:%S")
