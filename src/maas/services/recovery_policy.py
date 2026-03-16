"""Helpers for project-level recovery and retry policy."""

from datetime import datetime, timedelta
import json

from maas.ids import generate_id
from maas.services.security import ensure_board_action_allowed


DEFAULT_RECOVERY_POLICY = {
    "auto_retry_timeout_sessions": False,
    "auto_retry_failed_sessions": False,
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
    if project_id is None:
        row = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()
    else:
        row = connection.execute("SELECT project_id FROM projects WHERE project_id = ?", (project_id,)).fetchone()
    if row is None:
        raise ValueError("Project not found")
    return row["project_id"]


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
    tasks_row = connection.execute(
        """
        SELECT
            SUM(CASE WHEN review_state = 'retry_backoff' THEN 1 ELSE 0 END) AS retry_backoff_tasks,
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
          AND title = 'Repeated task failures detected'
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
        "tasks_with_retry_history": tasks_row["tasks_with_retry_history"] or 0,
        "recoverable_blocked_tasks": tasks_row["recoverable_blocked_tasks"] or 0,
        "tasks_with_retry_overrides": tasks_with_retry_overrides or 0,
        "open_quarantine_entries": open_quarantine_entries or 0,
        "open_failure_alerts": open_failure_alerts or 0,
        "open_repeated_failure_alerts": open_repeated_failure_alerts or 0,
    }


def _recovery_task_items(connection, project_id, where_clause, params, limit=8):
    rows = connection.execute(
        """
        SELECT
            tasks.task_id,
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
        LIMIT ?
        """.format(where_clause),
        tuple([project_id] + list(params) + [limit]),
    ).fetchall()
    return [dict(row) for row in rows]


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
        "task_retry_history": _recovery_task_items(
            connection,
            project_id,
            "tasks.status NOT IN ('done', 'cancelled') AND COALESCE(tasks.retry_count, 0) > 0",
            [],
        ),
        "active_retry_backoff": _recovery_task_items(
            connection,
            project_id,
            (
                "tasks.status IN ('planned', 'ready', 'assigned', 'blocked') "
                "AND (tasks.review_state = 'retry_backoff' OR tasks.next_retry_at IS NOT NULL)"
            ),
            [],
        ),
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
