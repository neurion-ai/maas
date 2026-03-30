"""Project-level autonomous execution loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
import socket
import threading
from typing import Dict, Optional

from maas.config import DEFAULT_AUTOPILOT_SETTINGS
from maas.db import connect
from maas.ids import generate_id
from maas.paths import ProjectPaths
from maas.services.codex_mvp import STALE_RUN_HEARTBEAT_SECONDS
from maas.services.notifications import process_next_notification, queue_notification_event
from maas.services.operator_actions import dedupe_operator_actions, task_operator_action
from maas.services.orchestrator import run_orchestrator_once
from maas.services.projects import resolve_project_id
from maas.services.reconciliation import reconcile_project_truth
from maas.services.security import ensure_board_action_allowed


AUTOPILOT_ACTOR_ID = "agent_allocator"
_AUTOPILOT_THREADS: Dict[tuple[str, str], "AutopilotLoop"] = {}
_AUTOPILOT_LOCK = threading.Lock()
AUTOPILOT_STOP_JOIN_SECONDS = 5
AUTOPILOT_LEASE_MIN_SECONDS = 15
AUTOPILOT_LEASE_MULTIPLIER = 3


def _load_json(value):
    try:
        payload = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _runtime_summary_json(summary):
    return json.dumps(summary or {})


def _lease_duration_seconds(policy):
    interval_seconds = max(5, int((policy or {}).get("interval_seconds") or DEFAULT_AUTOPILOT_SETTINGS["interval_seconds"]))
    return max(AUTOPILOT_LEASE_MIN_SECONDS, interval_seconds * AUTOPILOT_LEASE_MULTIPLIER)


def _ensure_runtime_row(connection, project_id):
    connection.execute(
        """
        INSERT INTO autopilot_runtime (project_id, last_summary_json)
        VALUES (?, '{}')
        ON CONFLICT(project_id) DO NOTHING
        """,
        (project_id,),
    )


def fetch_autopilot_runtime(connection, project_id):
    row = connection.execute(
        """
        SELECT
            project_id,
            lease_token,
            lease_owner,
            lease_acquired_at,
            lease_expires_at,
            last_heartbeat_at,
            last_summary_json,
            last_error,
            loop_count,
            status,
            updated_at,
            CASE
                WHEN lease_token IS NOT NULL
                 AND lease_expires_at IS NOT NULL
                 AND STRFTIME('%s', lease_expires_at) > STRFTIME('%s', 'now')
                THEN 1
                ELSE 0
            END AS lease_active
        FROM autopilot_runtime
        WHERE project_id = ?
        """,
        (project_id,),
    ).fetchone()
    if row is None:
        return None
    item = dict(row)
    try:
        item["last_summary"] = json.loads(item.pop("last_summary_json") or "{}")
    except (TypeError, ValueError):
        item["last_summary"] = {}
    item["lease_active"] = bool(item.pop("lease_active"))
    return item


def claim_autopilot_runtime_lease(connection, project_id, lease_token, lease_owner, policy):
    _ensure_runtime_row(connection, project_id)
    lease_seconds = _lease_duration_seconds(policy)
    cursor = connection.execute(
        """
        UPDATE autopilot_runtime
        SET lease_token = ?,
            lease_owner = ?,
            lease_acquired_at = CASE
                WHEN lease_token = ? THEN lease_acquired_at
                ELSE CURRENT_TIMESTAMP
            END,
            lease_expires_at = DATETIME('now', ?),
            status = 'running',
            updated_at = CURRENT_TIMESTAMP
        WHERE project_id = ?
          AND (
            lease_token IS NULL
            OR lease_token = ?
            OR lease_expires_at IS NULL
            OR STRFTIME('%s', lease_expires_at) <= STRFTIME('%s', 'now')
          )
        """,
        (
            lease_token,
            lease_owner,
            lease_token,
            "+{0} seconds".format(lease_seconds),
            project_id,
            lease_token,
        ),
    )
    connection.commit()
    if cursor.rowcount <= 0:
        return None
    return fetch_autopilot_runtime(connection, project_id)


def record_autopilot_runtime_result(connection, project_id, lease_token, policy, summary=None, error=None, status_override=None):
    _ensure_runtime_row(connection, project_id)
    lease_seconds = _lease_duration_seconds(policy)
    cursor = connection.execute(
        """
        UPDATE autopilot_runtime
        SET last_heartbeat_at = CURRENT_TIMESTAMP,
            last_summary_json = COALESCE(?, last_summary_json),
            last_error = ?,
            loop_count = loop_count + 1,
            status = ?,
            lease_expires_at = DATETIME('now', ?),
            updated_at = CURRENT_TIMESTAMP
        WHERE project_id = ?
          AND lease_token = ?
        """,
        (
            _runtime_summary_json(summary) if summary is not None else None,
            error,
            status_override or ("error" if error else "running"),
            "+{0} seconds".format(lease_seconds),
            project_id,
            lease_token,
        ),
    )
    connection.commit()
    if cursor.rowcount <= 0:
        return None
    return fetch_autopilot_runtime(connection, project_id)


def refresh_autopilot_runtime_lease(connection, project_id, lease_token, policy, status="running"):
    _ensure_runtime_row(connection, project_id)
    lease_seconds = _lease_duration_seconds(policy)
    cursor = connection.execute(
        """
        UPDATE autopilot_runtime
        SET last_heartbeat_at = CURRENT_TIMESTAMP,
            lease_expires_at = DATETIME('now', ?),
            status = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE project_id = ?
          AND lease_token = ?
        """,
        (
            "+{0} seconds".format(lease_seconds),
            status,
            project_id,
            lease_token,
        ),
    )
    connection.commit()
    if cursor.rowcount <= 0:
        return None
    return fetch_autopilot_runtime(connection, project_id)


def release_autopilot_runtime_lease(connection, project_id, lease_token=None, status="stopped", error=None):
    _ensure_runtime_row(connection, project_id)
    params = [status, error, project_id]
    where_clause = "project_id = ?"
    if lease_token is not None:
        where_clause += " AND lease_token = ?"
        params.append(lease_token)
    connection.execute(
        """
        UPDATE autopilot_runtime
        SET lease_token = NULL,
            lease_owner = NULL,
            lease_acquired_at = NULL,
            lease_expires_at = NULL,
            status = ?,
            last_error = COALESCE(?, last_error),
            updated_at = CURRENT_TIMESTAMP
        WHERE {where_clause}
        """.format(where_clause=where_clause),
        tuple(params),
    )
    connection.commit()
    return fetch_autopilot_runtime(connection, project_id)


def _process_autopilot_notifications(connection, project_id, policy, lease_token=None):
    if not policy.get("process_notifications"):
        return 0
    processed_count = 0
    for _ in range(policy["notification_batch_limit"]):
        processed = process_next_notification(
            connection,
            AUTOPILOT_ACTOR_ID,
            project_id=project_id,
        )
        if not processed["processed"]:
            break
        processed_count += 1
        if lease_token is not None:
            refresh_autopilot_runtime_lease(
                connection,
                project_id,
                lease_token,
                policy,
                status="waiting",
            )
    return processed_count


def _idle_cycle_signature(summary):
    governance_gate = (summary or {}).get("governance_gate") or {}
    reason = governance_gate.get("reason")
    if reason:
        return "gate:{0}".format(reason)
    why_idle = (summary or {}).get("why_idle")
    return why_idle or "active"


def _summary_has_forward_progress(summary):
    if not summary:
        return False
    return any(
        int(summary.get(key) or 0) > 0
        for key in (
            "assigned_count",
            "provider_jobs_queued",
            "provider_jobs_processed",
            "provider_jobs_dispatched",
            "notifications_processed",
        )
    )


def _apply_idle_cycle_governance(connection, project_id, policy, summary, previous_summary=None):
    if summary is None:
        return None
    previous = previous_summary or {}
    signature = _idle_cycle_signature(summary)
    threshold = max(1, int(policy.get("max_idle_cycles_before_alert") or 1))
    if _summary_has_forward_progress(summary):
        summary["consecutive_idle_cycles"] = 0
        summary["idle_signature"] = None
        summary["idle_alert_triggered"] = False
        return summary
    previous_signature = previous.get("idle_signature")
    previous_cycles = int(previous.get("consecutive_idle_cycles") or 0) if previous_signature == signature else 0
    cycles = previous_cycles + 1
    summary["consecutive_idle_cycles"] = cycles
    summary["idle_signature"] = signature
    triggered = previous_cycles < threshold <= cycles and signature != "gate:outside_schedule_window"
    summary["idle_alert_triggered"] = triggered
    if triggered:
        queue_notification_event(
            connection,
            project_id,
            "escalation_requested",
            "warning",
            "Autopilot is idle without forward progress",
            summary.get("why_idle") or "Autopilot has not advanced work for several consecutive cycles.",
            resource_type="project",
            resource_id=project_id,
            payload={
                "idle_signature": signature,
                "consecutive_idle_cycles": cycles,
                "threshold": threshold,
            },
        )
    return summary


def normalize_autopilot_policy(policy=None):
    requested = policy or {}
    defaults = DEFAULT_AUTOPILOT_SETTINGS

    enabled = bool(requested.get("enabled", defaults["enabled"]))
    interval_seconds = max(5, int(requested.get("interval_seconds", defaults["interval_seconds"]) or defaults["interval_seconds"]))
    allocate_limit = max(1, int(requested.get("allocate_limit", defaults["allocate_limit"]) or defaults["allocate_limit"]))
    provider_job_limit = max(
        1,
        int(requested.get("provider_job_limit", defaults["provider_job_limit"]) or defaults["provider_job_limit"]),
    )
    auto_launch_assigned_work = bool(
        requested.get("auto_launch_assigned_work", defaults["auto_launch_assigned_work"])
    )
    process_notifications = bool(requested.get("process_notifications", defaults["process_notifications"]))
    notification_batch_limit = max(
        1,
        int(
            requested.get("notification_batch_limit", defaults["notification_batch_limit"])
            or defaults["notification_batch_limit"]
        ),
    )
    start_hour = requested.get("schedule_window_start_hour_utc", defaults["schedule_window_start_hour_utc"])
    end_hour = requested.get("schedule_window_end_hour_utc", defaults["schedule_window_end_hour_utc"])

    def _normalize_hour(value, field_name):
        if value in (None, ""):
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("{0} must be an integer hour or null".format(field_name))
        if value < 0 or value > 23:
            raise ValueError("{0} must be between 0 and 23".format(field_name))
        return value

    stop_when_doctor_blocked = bool(
        requested.get("stop_when_doctor_blocked", defaults["stop_when_doctor_blocked"])
    )
    max_review_queue = max(
        0,
        int(requested.get("max_review_queue", defaults["max_review_queue"]) or 0),
    )
    max_blocked_queue = max(
        0,
        int(requested.get("max_blocked_queue", defaults["max_blocked_queue"]) or 0),
    )
    max_idle_cycles_before_alert = max(
        1,
        int(
            requested.get("max_idle_cycles_before_alert", defaults["max_idle_cycles_before_alert"])
            or defaults["max_idle_cycles_before_alert"]
        ),
    )
    max_stale_runs = max(
        0,
        int(requested.get("max_stale_runs", defaults["max_stale_runs"]) or 0),
    )
    max_repeated_failure_incidents = max(
        0,
        int(
            requested.get(
                "max_repeated_failure_incidents",
                defaults["max_repeated_failure_incidents"],
            )
            or 0
        ),
    )
    max_notification_failures = max(
        0,
        int(requested.get("max_notification_failures", defaults["max_notification_failures"]) or 0),
    )
    return {
        "enabled": enabled,
        "interval_seconds": interval_seconds,
        "allocate_limit": allocate_limit,
        "provider_job_limit": provider_job_limit,
        "auto_launch_assigned_work": auto_launch_assigned_work,
        "process_notifications": process_notifications,
        "notification_batch_limit": notification_batch_limit,
        "schedule_window_start_hour_utc": _normalize_hour(
            start_hour,
            "schedule_window_start_hour_utc",
        ),
        "schedule_window_end_hour_utc": _normalize_hour(
            end_hour,
            "schedule_window_end_hour_utc",
        ),
        "stop_when_doctor_blocked": stop_when_doctor_blocked,
        "max_review_queue": max_review_queue,
        "max_blocked_queue": max_blocked_queue,
        "max_idle_cycles_before_alert": max_idle_cycles_before_alert,
        "max_stale_runs": max_stale_runs,
        "max_repeated_failure_incidents": max_repeated_failure_incidents,
        "max_notification_failures": max_notification_failures,
    }


def fetch_project_autopilot_policy(connection, project_id=None):
    resolved_project_id = resolve_project_id(connection, project_id, include_archived=False)
    if resolved_project_id is None:
        raise ValueError("project not found")
    row = connection.execute(
        "SELECT config_json FROM projects WHERE project_id = ?",
        (resolved_project_id,),
    ).fetchone()
    config = _load_json(row["config_json"] if row else "{}")
    return normalize_autopilot_policy(config.get("autopilot") or {})


def _save_project_autopilot_policy(connection, project_id, policy):
    row = connection.execute(
        "SELECT config_json FROM projects WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    config = _load_json(row["config_json"] if row else "{}")
    config["autopilot"] = normalize_autopilot_policy(policy)
    connection.execute(
        "UPDATE projects SET config_json = ?, updated_at = CURRENT_TIMESTAMP WHERE project_id = ?",
        (json.dumps(config), project_id),
    )


def _execution_explanation(connection, project_id):
    summary = connection.execute(
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
    capacity = connection.execute(
        "SELECT config_json FROM projects WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    config = _load_json(capacity["config_json"] if capacity else "{}")
    provider_capacity = config.get("provider_capacity") or {}
    queue_mode = provider_capacity.get("queue_mode") or "running"
    if (summary["active_tasks"] or 0) > 0:
        return "Work is already in progress; MAAS is waiting on active Codex runs to finish."
    if queue_mode == "paused":
        return "Launches are paused, so assigned work will not start until the queue posture is resumed."
    if queue_mode == "draining":
        return "Queue is draining; MAAS will finish queued/running jobs but will not launch newly assigned work."
    if (summary["review_tasks"] or 0) > 0 and not (summary["ready_tasks"] or 0) and not (summary["assigned_tasks"] or 0):
        return "Work is waiting in review. Operator approval or auto-approval policy is the current gate."
    if (summary["assigned_tasks"] or 0) > 0:
        return "Assigned work is waiting on the next launch cycle or provider readiness."
    if (summary["ready_tasks"] or 0) > 0:
        return "Ready work exists, but it has not been assigned yet. The next cycle should allocate it."
    if (summary["blocked_tasks"] or 0) > 0:
        return "No runnable work is left; the remaining issues are blocked and need recovery or dependencies cleared."
    return "No ready, assigned, or active work exists for this project right now."


def _load_cycle_policy(connection, project_id, fallback_policy):
    try:
        return fetch_project_autopilot_policy(connection, project_id)
    except Exception:
        return normalize_autopilot_policy(fallback_policy)


def _schedule_window_open(policy, now=None):
    start_hour = policy.get("schedule_window_start_hour_utc")
    end_hour = policy.get("schedule_window_end_hour_utc")
    if start_hour is None or end_hour is None:
        return True
    current = now or datetime.now(timezone.utc)
    hour = current.hour
    if start_hour == end_hour:
        return True
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def _governance_gate(connection, project_paths, project_id, policy):
    from maas.services.failure_memory import fetch_repeated_failure_tasks

    def _signal(
        code,
        label,
        severity,
        summary,
        detail,
        *,
        count=0,
        threshold=0,
        blocking=False,
        operator_actions=None,
    ):
        item = {
            "code": code,
            "label": label,
            "severity": severity,
            "summary": summary,
            "detail": detail,
            "count": int(count or 0),
            "threshold": int(threshold or 0),
            "blocking": bool(blocking),
        }
        if operator_actions:
            item["operator_actions"] = dedupe_operator_actions(operator_actions)
        return item

    repeated_failure_items = fetch_repeated_failure_tasks(connection, project_id=project_id, actionable_only=True)
    review_count = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM tasks
        WHERE project_id = ?
          AND status = 'review'
        """,
        (project_id,),
    ).fetchone()["count"]
    blocked_count = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM tasks
        WHERE project_id = ?
          AND status = 'blocked'
        """,
        (project_id,),
    ).fetchone()["count"]
    stale_runs = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM sessions
        WHERE project_id = ?
          AND status = 'active'
          AND last_heartbeat_at IS NOT NULL
          AND datetime(last_heartbeat_at) <= datetime('now', ?)
        """,
        (project_id, "-{0} seconds".format(STALE_RUN_HEARTBEAT_SECONDS)),
    ).fetchone()["count"]
    repeated_failure_incidents = len(repeated_failure_items)
    notification_failures = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM notification_outbox
        WHERE project_id = ?
          AND status = 'failed'
        """,
        (project_id,),
    ).fetchone()["count"]
    gate = {
        "blocked": False,
        "reason": None,
        "detail": None,
        "review_queue": review_count or 0,
        "blocked_queue": blocked_count or 0,
        "stale_runs": stale_runs or 0,
        "repeated_failure_incidents": repeated_failure_incidents,
        "notification_failures": notification_failures or 0,
        "schedule_window_open": _schedule_window_open(policy),
        "doctor_summary": None,
        "doctor_state": None,
        "summary": "Autopilot governance thresholds are clear.",
        "signals": [],
        "thresholds": {
            "max_review_queue": int(policy.get("max_review_queue") or 0),
            "max_blocked_queue": int(policy.get("max_blocked_queue") or 0),
            "max_stale_runs": int(policy.get("max_stale_runs") or 0),
            "max_repeated_failure_incidents": int(policy.get("max_repeated_failure_incidents") or 0),
            "max_notification_failures": int(policy.get("max_notification_failures") or 0),
        },
    }
    signals = []
    if not gate["schedule_window_open"]:
        signals.append(
            _signal(
                "outside_schedule_window",
                "Outside schedule window",
                "warning",
                "Autopilot is outside the configured UTC schedule window for this project.",
                "No autonomous cycles should launch until the schedule window opens again.",
                blocking=True,
            )
        )
    max_review_queue = int(policy.get("max_review_queue") or 0)
    if gate["review_queue"] > 0:
        signals.append(
            _signal(
                "review_queue_limit",
                "Review queue pressure",
                "warning",
                (
                    "Review queue reached the configured threshold."
                    if max_review_queue > 0 and gate["review_queue"] >= max_review_queue
                    else "Review queue is accumulating operator work."
                ),
                "Too much review backlog reduces autonomous forward progress and increases merge latency.",
                count=gate["review_queue"],
                threshold=max_review_queue,
                blocking=bool(max_review_queue > 0 and gate["review_queue"] >= max_review_queue),
            )
        )
    max_blocked_queue = int(policy.get("max_blocked_queue") or 0)
    if gate["blocked_queue"] > 0:
        signals.append(
            _signal(
                "blocked_queue_limit",
                "Blocked queue pressure",
                "warning",
                (
                    "Blocked queue reached the configured threshold."
                    if max_blocked_queue > 0 and gate["blocked_queue"] >= max_blocked_queue
                    else "Blocked work is accumulating and should be recovered or replanned."
                ),
                "Too much blocked work means the allocator can keep spinning without real delivery progress.",
                count=gate["blocked_queue"],
                threshold=max_blocked_queue,
                blocking=bool(max_blocked_queue > 0 and gate["blocked_queue"] >= max_blocked_queue),
            )
        )
    max_stale_runs = int(policy.get("max_stale_runs") or 0)
    if gate["stale_runs"] > 0:
        signals.append(
            _signal(
                "stale_run_limit",
                "Stale run pressure",
                "critical",
                (
                    "Stale or suspect live runs reached the configured threshold."
                    if max_stale_runs > 0 and gate["stale_runs"] >= max_stale_runs
                    else "Stale or suspect runs exist and need inspection."
                ),
                "Stale sessions usually mean the loop is spending capacity on work that is no longer advancing.",
                count=gate["stale_runs"],
                threshold=max_stale_runs,
                blocking=bool(max_stale_runs > 0 and gate["stale_runs"] >= max_stale_runs),
            )
        )
    max_repeated_failures = int(policy.get("max_repeated_failure_incidents") or 0)
    repeated_failure_actions = []
    if repeated_failure_items and repeated_failure_items[0].get("operator_action"):
        repeated_failure_actions.append(
            task_operator_action(
                "resolve_repeated_failures",
                repeated_failure_items[0]["operator_action"].get("label") or "Resolve repeated failures",
                repeated_failure_items[0]["task_id"],
            )
        )
    if gate["repeated_failure_incidents"] > 0:
        signals.append(
            _signal(
                "repeated_failure_limit",
                "Repeated failure pressure",
                "critical",
                (
                    "Repeated-failure incidents reached the configured threshold."
                    if max_repeated_failures > 0 and gate["repeated_failure_incidents"] >= max_repeated_failures
                    else "Repeated-failure incidents are open and suppressing autonomous retries."
                ),
                "Thrashing tasks should be resolved or replanned before the loop keeps spending effort on them.",
                count=gate["repeated_failure_incidents"],
                threshold=max_repeated_failures,
                blocking=bool(max_repeated_failures > 0 and gate["repeated_failure_incidents"] >= max_repeated_failures),
                operator_actions=repeated_failure_actions,
            )
        )
    max_notification_failures = int(policy.get("max_notification_failures") or 0)
    if gate["notification_failures"] > 0:
        signals.append(
            _signal(
                "notification_failure_limit",
                "Notification delivery failures",
                "warning",
                (
                    "Failed outbound notifications reached the configured threshold."
                    if max_notification_failures > 0 and gate["notification_failures"] >= max_notification_failures
                    else "Failed outbound notifications exist and reduce operator visibility."
                ),
                "Notification failures do not stop code from running, but they reduce trust in autonomous supervision.",
                count=gate["notification_failures"],
                threshold=max_notification_failures,
                blocking=bool(max_notification_failures > 0 and gate["notification_failures"] >= max_notification_failures),
            )
        )
    from maas.services.environment_doctor import fetch_environment_doctor

    doctor = fetch_environment_doctor(connection, project_paths, project_id)
    gate["doctor_summary"] = doctor.get("summary")
    gate["doctor_state"] = (doctor.get("progress") or {}).get("status")
    doctor_status = (doctor.get("summary") or {}).get("status")
    if doctor_status in {"blocked", "attention", "simulation_only"}:
        doctor_signal_code = "doctor_blocked" if doctor_status == "blocked" else "doctor_attention"
        signals.append(
            _signal(
                doctor_signal_code,
                "Environment doctor",
                "critical" if doctor_status == "blocked" else "warning",
                (
                    "Environment doctor is blocking live execution."
                    if doctor_status == "blocked"
                    else "Environment doctor has live-readiness issues worth clearing."
                ),
                (doctor.get("summary") or {}).get("detail")
                or "Doctor posture should be cleared before trusting fully autonomous live execution.",
                blocking=bool(policy.get("stop_when_doctor_blocked", True) and doctor_status == "blocked"),
            )
        )
    blocking_signals = [item for item in signals if item["blocking"]]
    gate["signals"] = signals
    if blocking_signals:
        first = blocking_signals[0]
        gate.update(
            {
                "blocked": True,
                "reason": first["code"],
                "detail": first["detail"],
                "summary": first["summary"],
            }
        )
    elif signals:
        gate["summary"] = "Autopilot is within policy, but control-loop pressure is building."
        gate["detail"] = signals[0]["detail"]
    return gate


def _run_orchestrator_with_lease_refresh(project_root, project_id, lease_token, policy):
    paths = ProjectPaths(project_root)
    result_holder = {}
    error_holder = {}
    finished = threading.Event()
    lease_lost = threading.Event()
    heartbeat_interval = max(1.0, min(5.0, _lease_duration_seconds(policy) / 3.0))

    def _worker():
        worker_connection = None
        try:
            worker_connection = connect(paths)
            result_holder["result"] = run_orchestrator_once(
                worker_connection,
                paths,
                allocate_limit=policy["allocate_limit"],
                provider_job_limit=policy["provider_job_limit"],
                project_id=project_id,
                auto_launch_assigned_work=policy["auto_launch_assigned_work"],
            )
        except Exception as exc:  # pragma: no cover - surfaced to caller
            error_holder["error"] = exc
        finally:
            if worker_connection is not None:
                worker_connection.close()
            finished.set()

    worker = threading.Thread(
        target=_worker,
        name="maas-autopilot-cycle-{0}".format(project_id),
        daemon=True,
    )
    worker.start()

    try:
        while not finished.wait(heartbeat_interval):
            lease_connection = connect(paths)
            try:
                runtime_row = refresh_autopilot_runtime_lease(
                    lease_connection,
                    project_id,
                    lease_token,
                    policy,
                    status="running",
                )
            finally:
                lease_connection.close()
            if runtime_row is None:
                lease_lost.set()
                break
    finally:
        worker.join()

    if "error" in error_holder:
        raise error_holder["error"]
    if lease_lost.is_set():
        raise RuntimeError(
            "Autopilot lost its lease during an active orchestrator cycle for project {0}.".format(project_id)
        )
    return result_holder.get("result", {})


@dataclass
class AutopilotLoop:
    project_root: str
    project_id: str
    policy: dict
    stop_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    thread: Optional[threading.Thread] = None
    last_heartbeat_at: Optional[str] = None
    last_summary: Optional[dict] = None
    last_error: Optional[str] = None
    loop_count: int = 0
    loop_token: str = field(default_factory=lambda: generate_id("autopilot"))
    lease_owner: Optional[str] = None
    lease_expires_at: Optional[str] = None
    runtime_status: str = "idle"
    owns_lease: bool = False

    def __post_init__(self):
        if self.lease_owner is None:
            self.lease_owner = "{0}:{1}:{2}".format(socket.gethostname(), os.getpid(), self.loop_token)

    def update_policy(self, policy):
        with self.lock:
            self.policy = normalize_autopilot_policy(policy)

    def snapshot(self):
        with self.lock:
            policy = dict(self.policy)
            return {
                "project_id": self.project_id,
                "enabled": policy["enabled"],
                "running": bool(
                    self.thread and self.thread.is_alive() and not self.stop_event.is_set() and self.owns_lease
                ),
                "policy": policy,
                "last_heartbeat_at": self.last_heartbeat_at,
                "last_summary": self.last_summary,
                "last_error": self.last_error,
                "loop_count": self.loop_count,
                "runtime_status": self.runtime_status,
                "lease_owner": self.lease_owner,
                "lease_expires_at": self.lease_expires_at,
                "owns_lease": self.owns_lease,
            }

    def mark_result(self, runtime_row, summary=None, error=None):
        with self.lock:
            self.last_heartbeat_at = runtime_row.get("last_heartbeat_at") if runtime_row else datetime.now(timezone.utc).isoformat()
            if summary is not None:
                self.last_summary = summary
            elif runtime_row and runtime_row.get("last_summary") is not None:
                self.last_summary = runtime_row.get("last_summary")
            self.last_error = error
            self.loop_count = int(runtime_row.get("loop_count") or 0) if runtime_row else self.loop_count + 1
            self.runtime_status = runtime_row.get("status") if runtime_row else ("error" if error else "waiting")
            self.lease_expires_at = runtime_row.get("lease_expires_at") if runtime_row else None
            self.owns_lease = bool(runtime_row and runtime_row.get("lease_active"))

    def mark_waiting(self, error=None):
        with self.lock:
            self.last_error = error
            self.runtime_status = "waiting"
            self.lease_expires_at = None
            self.owns_lease = False

    def mark_stopped(self):
        with self.lock:
            self.runtime_status = "stopped"
            self.lease_expires_at = None
            self.owns_lease = False

    def run_forever(self):
        paths = ProjectPaths(self.project_root)
        while not self.stop_event.is_set():
            try:
                connection = connect(paths)
                try:
                    with self.lock:
                        fallback_policy = dict(self.policy)
                    policy = _load_cycle_policy(connection, self.project_id, fallback_policy)
                    self.update_policy(policy)
                    if not policy.get("enabled"):
                        release_autopilot_runtime_lease(connection, self.project_id, lease_token=self.loop_token, status="idle")
                        self.mark_waiting()
                        continue
                    runtime_row = claim_autopilot_runtime_lease(
                        connection,
                        self.project_id,
                        self.loop_token,
                        self.lease_owner,
                        policy,
                    )
                    if runtime_row is None:
                        self.mark_waiting()
                    else:
                        try:
                            previous_summary = runtime_row.get("last_summary") or {}
                            reconciliation = reconcile_project_truth(
                                connection,
                                paths,
                                self.project_id,
                                source="autopilot",
                            )
                            governance_gate = _governance_gate(connection, paths, self.project_id, policy)
                            if governance_gate["blocked"]:
                                notifications_processed = _process_autopilot_notifications(
                                    connection,
                                    self.project_id,
                                    policy,
                                    lease_token=self.loop_token,
                                )
                                summary = {
                                    "assigned_count": 0,
                                    "provider_jobs_queued": 0,
                                    "provider_jobs_processed": 0,
                                    "provider_jobs_dispatched": 0,
                                    "notifications_processed": notifications_processed,
                                    "why_idle": governance_gate["detail"],
                                    "governance_gate": governance_gate,
                                    "reconciliation": reconciliation["summary"],
                                }
                                summary = _apply_idle_cycle_governance(
                                    connection,
                                    self.project_id,
                                    policy,
                                    summary,
                                    previous_summary,
                                )
                                runtime_row = record_autopilot_runtime_result(
                                    connection,
                                    self.project_id,
                                    self.loop_token,
                                    policy,
                                    summary=summary,
                                    error=governance_gate["detail"],
                                    status_override="waiting",
                                )
                                self.mark_result(runtime_row, summary=summary, error=governance_gate["detail"])
                                continue
                            runtime_row = refresh_autopilot_runtime_lease(
                                connection,
                                self.project_id,
                                self.loop_token,
                                policy,
                                status="running",
                            )
                            result = _run_orchestrator_with_lease_refresh(
                                self.project_root,
                                self.project_id,
                                self.loop_token,
                                policy,
                            )
                            notifications_processed = _process_autopilot_notifications(
                                connection,
                                self.project_id,
                                policy,
                                lease_token=self.loop_token,
                            )
                            summary = {
                                "assigned_count": result.get("assigned_count", 0),
                                "provider_jobs_queued": result.get("provider_jobs_queued", 0),
                                "provider_jobs_processed": result.get("provider_jobs_processed", 0),
                                "provider_jobs_dispatched": result.get("provider_jobs_dispatched", 0),
                                "notifications_processed": notifications_processed,
                                "why_idle": _execution_explanation(connection, self.project_id),
                                "governance_gate": governance_gate,
                                "reconciliation": reconciliation["summary"],
                            }
                            summary = _apply_idle_cycle_governance(
                                connection,
                                self.project_id,
                                policy,
                                summary,
                                previous_summary,
                            )
                            runtime_row = record_autopilot_runtime_result(
                                connection,
                                self.project_id,
                                self.loop_token,
                                policy,
                                summary=summary,
                            )
                            self.mark_result(runtime_row, summary=summary, error=None)
                        except Exception as exc:  # pragma: no cover - guardrail path
                            runtime_row = record_autopilot_runtime_result(
                                connection,
                                self.project_id,
                                self.loop_token,
                                policy,
                                error=str(exc),
                            )
                            self.mark_result(runtime_row, summary=None, error=str(exc))
                finally:
                    connection.close()
            except Exception as exc:  # pragma: no cover - guardrail path
                self.mark_waiting(error=str(exc))
            if self.stop_event.wait(policy["interval_seconds"]):
                break

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self.run_forever,
            name="maas-autopilot-{0}".format(self.project_id),
            daemon=True,
        )
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(AUTOPILOT_STOP_JOIN_SECONDS)
        if not self.thread or not self.thread.is_alive():
            connection = connect(ProjectPaths(self.project_root))
            try:
                release_autopilot_runtime_lease(
                    connection,
                    self.project_id,
                    lease_token=self.loop_token,
                    status="stopped",
                    error=self.last_error if self.runtime_status == "error" else None,
                )
            finally:
                connection.close()
            self.mark_stopped()
            return True
        return False


def stop_project_autopilot(project_paths, project_id):
    key = _manager_key(project_paths, project_id)
    with _AUTOPILOT_LOCK:
        current = _AUTOPILOT_THREADS.get(key)
        if current is None:
            return False
        stopped = current.stop()
        if stopped:
            del _AUTOPILOT_THREADS[key]
            return True
        return False


def _manager_key(project_paths, project_id):
    return (project_paths.root, project_id)


def sync_project_autopilot(connection, project_paths, project_id):
    policy = fetch_project_autopilot_policy(connection, project_id)
    key = _manager_key(project_paths, project_id)
    with _AUTOPILOT_LOCK:
        current = _AUTOPILOT_THREADS.get(key)
        if not policy["enabled"]:
            if current is not None:
                stopped = current.stop()
                if stopped:
                    del _AUTOPILOT_THREADS[key]
            else:
                release_autopilot_runtime_lease(connection, project_id, status="idle")
            return None
        if current is None:
            current = AutopilotLoop(project_root=project_paths.root, project_id=project_id, policy=policy)
            _AUTOPILOT_THREADS[key] = current
            current.start()
        else:
            current.update_policy(policy)
            if current.stop_event.is_set() and current.thread and current.thread.is_alive():
                current.thread.join(AUTOPILOT_STOP_JOIN_SECONDS)
            if not current.thread or not current.thread.is_alive():
                current.start()
        return current.snapshot()


def sync_enabled_autopilots(project_paths):
    connection = connect(project_paths)
    try:
        active_project_ids = {
            row["project_id"]
            for row in connection.execute(
                "SELECT project_id FROM projects WHERE state = 'active'"
            ).fetchall()
        }
        with _AUTOPILOT_LOCK:
            stale_keys = [
                key
                for key in _AUTOPILOT_THREADS
                if key[0] == project_paths.root and key[1] not in active_project_ids
            ]
        for key in stale_keys:
            stop_project_autopilot(project_paths, key[1])
        snapshots = []
        for project_id in active_project_ids:
            snapshot = sync_project_autopilot(connection, project_paths, project_id)
            if snapshot is not None:
                snapshots.append(snapshot)
        return snapshots
    finally:
        connection.close()


def stop_all_autopilots(project_paths):
    with _AUTOPILOT_LOCK:
        keys = [key for key in _AUTOPILOT_THREADS if key[0] == project_paths.root]
    for key in keys:
        stop_project_autopilot(project_paths, key[1])


def fetch_autopilot_status(connection, project_paths, project_id=None):
    resolved_project_id = resolve_project_id(connection, project_id, include_archived=False)
    if resolved_project_id is None:
        raise ValueError("project not found")
    policy = fetch_project_autopilot_policy(connection, resolved_project_id)
    governance_gate = _governance_gate(connection, project_paths, resolved_project_id, policy)
    key = _manager_key(project_paths, resolved_project_id)
    with _AUTOPILOT_LOCK:
        loop = _AUTOPILOT_THREADS.get(key)
        runtime = loop.snapshot() if loop is not None else None
    durable_runtime = fetch_autopilot_runtime(connection, resolved_project_id)
    if durable_runtime is not None:
        holder_is_local = bool(runtime and runtime.get("lease_owner") == durable_runtime.get("lease_owner") and runtime.get("owns_lease"))
        runtime = {
            "project_id": resolved_project_id,
            "enabled": policy["enabled"],
            "running": bool(durable_runtime.get("lease_active") and durable_runtime.get("status") in {"running", "error"}),
            "policy": policy,
            "last_heartbeat_at": durable_runtime.get("last_heartbeat_at"),
            "last_summary": durable_runtime.get("last_summary") or {},
            "last_error": durable_runtime.get("last_error"),
            "loop_count": durable_runtime.get("loop_count") or 0,
            "runtime_status": durable_runtime.get("status"),
            "lease_owner": durable_runtime.get("lease_owner"),
            "lease_expires_at": durable_runtime.get("lease_expires_at"),
            "owns_lease": holder_is_local,
            "holder_is_local": holder_is_local,
        }
    return {
        "project_id": resolved_project_id,
        "policy": policy,
        "runtime": runtime
        or {
            "project_id": resolved_project_id,
            "enabled": policy["enabled"],
            "running": False,
            "policy": policy,
            "last_heartbeat_at": None,
            "last_summary": None,
            "last_error": None,
            "loop_count": 0,
            "runtime_status": "idle",
            "lease_owner": None,
            "lease_expires_at": None,
            "owns_lease": False,
            "holder_is_local": False,
        },
        "why_idle": _execution_explanation(connection, resolved_project_id),
        "governance_gate": governance_gate,
    }


def update_project_autopilot_policy(connection, project_paths, project_id, actor_id, policy):
    resolved_project_id = resolve_project_id(connection, project_id, include_archived=False)
    if resolved_project_id is None:
        raise ValueError("project not found")
    ensure_board_action_allowed(
        connection,
        actor_id,
        resolved_project_id,
        "configure_autopilot",
        "project",
        resolved_project_id,
    )
    normalized = normalize_autopilot_policy(policy)
    _save_project_autopilot_policy(connection, resolved_project_id, normalized)
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, 'configure_autopilot', 'project', ?, ?)
        """,
        (
            generate_id("audit"),
            resolved_project_id,
            actor_id,
            resolved_project_id,
            json.dumps(normalized),
        ),
    )
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, action, category, description, details_json, severity
        ) VALUES (?, ?, 'autopilot_policy_updated', 'projects', ?, ?, 'info')
        """,
        (
            generate_id("act"),
            resolved_project_id,
            "Updated project autopilot policy.",
            json.dumps(normalized),
        ),
    )
    connection.commit()
    sync_project_autopilot(connection, project_paths, resolved_project_id)
    return fetch_autopilot_status(connection, project_paths, resolved_project_id)
