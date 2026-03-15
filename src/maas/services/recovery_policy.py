"""Helpers for project-level recovery and retry policy."""

from datetime import datetime, timedelta
import json


DEFAULT_RECOVERY_POLICY = {
    "auto_retry_timeout_sessions": False,
    "max_timed_out_retries": 1,
    "timed_out_retry_cooldown_seconds": 60,
    "recover_and_requeue_cooldown_seconds": 30,
    "retry_backoff_multiplier": 2,
    "retry_backoff_max_seconds": 900,
}


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
        "auto_retry_timeout_sessions": bool(
            recovery.get("auto_retry_timeout_sessions", DEFAULT_RECOVERY_POLICY["auto_retry_timeout_sessions"])
        ),
        "max_timed_out_retries": int(
            recovery.get("max_timed_out_retries", DEFAULT_RECOVERY_POLICY["max_timed_out_retries"])
        ),
        "timed_out_retry_cooldown_seconds": int(
            recovery.get(
                "timed_out_retry_cooldown_seconds",
                DEFAULT_RECOVERY_POLICY["timed_out_retry_cooldown_seconds"],
            )
        ),
        "recover_and_requeue_cooldown_seconds": int(
            recovery.get(
                "recover_and_requeue_cooldown_seconds",
                DEFAULT_RECOVERY_POLICY["recover_and_requeue_cooldown_seconds"],
            )
        ),
        "retry_backoff_multiplier": max(
            1,
            int(recovery.get("retry_backoff_multiplier", DEFAULT_RECOVERY_POLICY["retry_backoff_multiplier"])),
        ),
        "retry_backoff_max_seconds": int(
            recovery.get("retry_backoff_max_seconds", DEFAULT_RECOVERY_POLICY["retry_backoff_max_seconds"])
        ),
    }


def task_timed_out_retry_limit(task_row, project_policy):
    if task_row["auto_retry_limit"] is not None:
        return int(task_row["auto_retry_limit"])
    return int(project_policy["max_timed_out_retries"])


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


def recover_and_requeue_cooldown_seconds(project_policy, failure_count):
    return retry_backoff_seconds(project_policy["recover_and_requeue_cooldown_seconds"], failure_count, project_policy)


def retry_deadline(seconds):
    if seconds <= 0:
        return None
    return (datetime.utcnow() + timedelta(seconds=int(seconds))).strftime("%Y-%m-%d %H:%M:%S")
