"""Cross-project portfolio read model."""

import json

from maas.providers import list_provider_status
from maas.services.board import BLOCKED_FAILURE_REVIEW_STATES
from maas.services.codex_mvp import STALE_RUN_HEARTBEAT_SECONDS
from maas.services.failure_memory import repeated_failure_task_count
from maas.services.notifications import (
    count_notification_outbox,
    fetch_notification_outbox,
    notification_policy_from_row,
)
from maas.services.projects import list_projects
from maas.services.queue_capacity import queue_capacity_snapshot
from maas.services.review_policy import review_policy_from_row
from maas.services.risk_policy import risk_policy_from_row
from maas.services.runtime_quotas import runtime_quota_snapshot, runtime_quotas_from_row
from maas.services.scheduler_policy import scheduler_policy_from_row


def _count_by_project(connection, query):
    rows = connection.execute(query).fetchall()
    return {row["project_id"]: row["count"] for row in rows}


def _provider_readiness_summary(connection, project_id):
    providers = list_provider_status(connection, project_id=project_id)
    ready = 0
    issues = 0
    unknown = 0
    for provider in providers:
        preflight = provider.get("latest_preflight") or {}
        preflight_status = preflight.get("status")
        if preflight_status in {"passed", "simulation_ready"}:
            ready += 1
        elif preflight_status == "failed" or not provider.get("is_runnable", True):
            issues += 1
        elif provider.get("effective_execution_mode") == "local_simulation":
            ready += 1
        else:
            unknown += 1
    return {
        "total": len(providers),
        "ready": ready,
        "issues": issues,
        "unknown": unknown,
    }


def _health_status(project, metrics):
    if project["state"] == "archived":
        return "archived"
    if metrics["critical_alerts"] > 0 or metrics["dead_letter_entries"] > 0:
        return "critical"
    if (
        metrics["open_alerts"] > 0
        or metrics["blocked_tasks"] > 0
        or metrics["open_quarantine_entries"] > 0
        or metrics["repeated_failure_tasks"] > 0
        or metrics["provider_readiness"]["issues"] > 0
    ):
        return "warn"
    return "healthy"


def _fetch_command_center_escalations(connection, limit=8):
    rows = connection.execute(
        """
        SELECT
            escalation_queue.escalation_id,
            escalation_queue.project_id,
            projects.name AS project_name,
            escalation_queue.requested_by,
            escalation_queue.action_type,
            escalation_queue.resource_type,
            escalation_queue.resource_id,
            escalation_queue.payload_json,
            escalation_queue.reason,
            escalation_queue.status,
            escalation_queue.created_at,
            requester.display_name AS requester_name
        FROM escalation_queue
        JOIN projects ON projects.project_id = escalation_queue.project_id
        LEFT JOIN agents requester ON requester.agent_id = escalation_queue.requested_by
        WHERE escalation_queue.status = 'open'
          AND projects.state = 'active'
        ORDER BY escalation_queue.created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def _fetch_command_center_alerts(connection, limit=8):
    rows = connection.execute(
        """
        SELECT
            alerts.alert_id,
            alerts.project_id,
            projects.name AS project_name,
            alerts.severity,
            alerts.title,
            alerts.description,
            alerts.status,
            alerts.created_at
        FROM alerts
        JOIN projects ON projects.project_id = alerts.project_id
        WHERE alerts.status = 'open'
          AND projects.state = 'active'
        ORDER BY
            CASE alerts.severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
            alerts.created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def _fetch_command_center_dead_letters(connection, limit=8):
    rows = connection.execute(
        """
        SELECT
            dead_letter_queue.dlq_id,
            dead_letter_queue.project_id,
            projects.name AS project_name,
            dead_letter_queue.task_id,
            dead_letter_queue.failure_id,
            dead_letter_queue.reason,
            dead_letter_queue.status,
            dead_letter_queue.detail_json,
            dead_letter_queue.resolution_note,
            dead_letter_queue.created_at,
            dead_letter_queue.updated_at,
            dead_letter_queue.resolved_at,
            tasks.title,
            tasks.status AS task_status,
            tasks.review_state,
            tasks.priority,
            tasks.retry_count,
            tasks.auto_retry_limit,
            tasks.last_retry_reason,
            tasks.next_retry_at,
            tasks.next_retry_reason,
            goals.title AS goal_title,
            agents.display_name AS agent_name
        FROM dead_letter_queue
        JOIN projects ON projects.project_id = dead_letter_queue.project_id
        JOIN tasks ON tasks.task_id = dead_letter_queue.task_id
        LEFT JOIN goals ON goals.goal_id = tasks.goal_id
        LEFT JOIN agents ON agents.agent_id = tasks.assigned_agent_id
        WHERE dead_letter_queue.status = 'open'
          AND projects.state = 'active'
        ORDER BY dead_letter_queue.created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["detail"] = {}
        detail_json = item.pop("detail_json", None)
        if detail_json:
            try:
                item["detail"] = json.loads(detail_json or "{}")
            except ValueError:
                item["detail"] = {}
        items.append(item)
    return items


def _fetch_command_center_provider_jobs(connection, limit=8):
    rows = connection.execute(
        """
        SELECT
            provider_job_queue.job_id,
            provider_job_queue.project_id,
            projects.name AS project_name,
            provider_job_queue.provider_id,
            provider_job_queue.task_id,
            tasks.title AS title,
            goals.title AS goal_title,
            provider_job_queue.agent_id,
            agents.display_name AS agent_name,
            provider_job_queue.status,
            provider_job_queue.queued_by,
            provider_job_queue.worker_id,
            provider_job_queue.artifact_path,
            provider_job_queue.session_id,
            provider_job_queue.artifact_id,
            provider_job_queue.created_at,
            provider_job_queue.started_at,
            provider_job_queue.finished_at,
            provider_job_queue.updated_at
        FROM provider_job_queue
        JOIN projects ON projects.project_id = provider_job_queue.project_id
        LEFT JOIN tasks ON tasks.task_id = provider_job_queue.task_id
        LEFT JOIN goals ON goals.goal_id = tasks.goal_id
        LEFT JOIN agents ON agents.agent_id = provider_job_queue.agent_id
        WHERE provider_job_queue.status IN ('queued', 'running')
          AND projects.state = 'active'
        ORDER BY
            CASE provider_job_queue.status WHEN 'running' THEN 0 ELSE 1 END,
            provider_job_queue.created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def _fetch_command_center_notifications(connection, limit=8):
    return fetch_notification_outbox(connection, project_id=None, limit=limit, include_archived=False)


def _fetch_command_center_review_queue(connection, limit=8):
    rows = connection.execute(
        """
        SELECT
            tasks.project_id,
            projects.name AS project_name,
            tasks.task_id,
            tasks.title,
            tasks.priority,
            tasks.review_state,
            goals.title AS goal_title,
            agents.display_name AS agent_name,
            tasks.updated_at
        FROM tasks
        JOIN projects ON projects.project_id = tasks.project_id
        LEFT JOIN goals ON goals.goal_id = tasks.goal_id
        LEFT JOIN agents ON agents.agent_id = tasks.assigned_agent_id
        WHERE projects.state = 'active'
          AND tasks.status = 'review'
        ORDER BY tasks.priority DESC, tasks.updated_at DESC, tasks.created_at ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def _fetch_command_center_blocked_failures(connection, limit=8):
    placeholders = ", ".join("?" for _ in BLOCKED_FAILURE_REVIEW_STATES)
    rows = connection.execute(
        """
        SELECT
            tasks.project_id,
            projects.name AS project_name,
            tasks.task_id,
            tasks.title,
            tasks.priority,
            tasks.review_state,
            goals.title AS goal_title,
            agents.display_name AS agent_name,
            COUNT(failure_log.failure_id) AS failure_count,
            MAX(failure_log.created_at) AS latest_failure_at
        FROM tasks
        JOIN projects ON projects.project_id = tasks.project_id
        LEFT JOIN goals ON goals.goal_id = tasks.goal_id
        LEFT JOIN agents ON agents.agent_id = tasks.assigned_agent_id
        LEFT JOIN failure_log
            ON failure_log.project_id = tasks.project_id
           AND failure_log.task_id = tasks.task_id
        WHERE projects.state = 'active'
          AND tasks.status = 'blocked'
          AND (
            tasks.review_state IN ({placeholders})
            OR failure_log.failure_id IS NOT NULL
          )
        GROUP BY tasks.task_id
        ORDER BY tasks.priority DESC, COALESCE(MAX(failure_log.created_at), tasks.updated_at) DESC
        LIMIT ?
        """.format(placeholders=placeholders),
        tuple(BLOCKED_FAILURE_REVIEW_STATES) + (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def _fetch_command_center_suspect_runs(connection, limit=8):
    rows = connection.execute(
        """
        SELECT
            sessions.project_id,
            projects.name AS project_name,
            sessions.session_id,
            sessions.task_id,
            tasks.title AS task_title,
            sessions.agent_id,
            agents.display_name AS agent_name,
            sessions.status,
            sessions.provider_type,
            sessions.status_message,
            sessions.started_at,
            sessions.last_heartbeat_at
        FROM sessions
        JOIN projects ON projects.project_id = sessions.project_id
        LEFT JOIN tasks ON tasks.task_id = sessions.task_id
        LEFT JOIN agents ON agents.agent_id = sessions.agent_id
        WHERE projects.state = 'active'
          AND (
            sessions.status IN ('failed', 'timed_out', 'cancelled')
            OR (
              sessions.status = 'active'
              AND sessions.last_heartbeat_at IS NOT NULL
              AND STRFTIME('%s', 'now') - STRFTIME('%s', sessions.last_heartbeat_at) >= ?
            )
          )
        ORDER BY
          CASE sessions.status WHEN 'active' THEN 0 ELSE 1 END,
          COALESCE(sessions.ended_at, sessions.started_at) DESC
        LIMIT ?
        """,
        (STALE_RUN_HEARTBEAT_SECONDS, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def fetch_portfolio(connection):
    projects = list_projects(connection, include_archived=True)
    blocked_counts = _count_by_project(
        connection,
        """
        SELECT project_id, COUNT(*) AS count
        FROM tasks
        WHERE status = 'blocked'
        GROUP BY project_id
        """,
    )
    in_progress_counts = _count_by_project(
        connection,
        """
        SELECT project_id, COUNT(*) AS count
        FROM tasks
        WHERE status = 'in_progress'
        GROUP BY project_id
        """,
    )
    open_alert_counts = _count_by_project(
        connection,
        """
        SELECT project_id, COUNT(*) AS count
        FROM alerts
        WHERE status = 'open'
        GROUP BY project_id
        """,
    )
    critical_alert_counts = _count_by_project(
        connection,
        """
        SELECT project_id, COUNT(*) AS count
        FROM alerts
        WHERE status = 'open' AND severity = 'critical'
        GROUP BY project_id
        """,
    )
    active_session_counts = _count_by_project(
        connection,
        """
        SELECT project_id, COUNT(*) AS count
        FROM sessions
        WHERE status = 'active'
        GROUP BY project_id
        """,
    )
    running_agent_counts = _count_by_project(
        connection,
        """
        SELECT project_id, COUNT(*) AS count
        FROM agents
        WHERE status = 'running'
        GROUP BY project_id
        """,
    )
    quarantine_counts = _count_by_project(
        connection,
        """
        SELECT project_id, COUNT(*) AS count
        FROM quarantine_queue
        WHERE status = 'open'
        GROUP BY project_id
        """,
    )
    dead_letter_counts = _count_by_project(
        connection,
        """
        SELECT project_id, COUNT(*) AS count
        FROM dead_letter_queue
        WHERE status = 'open'
        GROUP BY project_id
        """,
    )
    review_queue_counts = _count_by_project(
        connection,
        """
        SELECT project_id, COUNT(*) AS count
        FROM tasks
        WHERE status = 'review'
        GROUP BY project_id
        """,
    )
    blocked_failure_counts = _count_by_project(
        connection,
        """
        SELECT tasks.project_id, COUNT(DISTINCT tasks.task_id) AS count
        FROM tasks
        LEFT JOIN failure_log
          ON failure_log.project_id = tasks.project_id
         AND failure_log.task_id = tasks.task_id
        WHERE tasks.status = 'blocked'
          AND (
            tasks.review_state IN ('session_failed', 'timed_out', 'circuit_breaker_open', 'retry_budget_exhausted')
            OR failure_log.failure_id IS NOT NULL
          )
        GROUP BY tasks.project_id
        """,
    )
    suspect_run_counts = _count_by_project(
        connection,
        """
        SELECT project_id, COUNT(*) AS count
        FROM sessions
        WHERE status IN ('failed', 'timed_out', 'cancelled')
           OR (
                status = 'active'
                AND last_heartbeat_at IS NOT NULL
                AND STRFTIME('%s', 'now') - STRFTIME('%s', last_heartbeat_at) >= {stale_seconds}
           )
        GROUP BY project_id
        """.format(stale_seconds=STALE_RUN_HEARTBEAT_SECONDS),
    )
    stale_agent_counts = _count_by_project(
        connection,
        """
        SELECT project_id, COUNT(*) AS count
        FROM agents
        WHERE last_heartbeat_at IS NOT NULL
          AND STRFTIME('%s', 'now') - STRFTIME('%s', last_heartbeat_at) >= {stale_seconds}
        GROUP BY project_id
        """.format(stale_seconds=STALE_RUN_HEARTBEAT_SECONDS),
    )

    portfolio_projects = []
    for project in projects:
        project_id = project["project_id"]
        provider_readiness = _provider_readiness_summary(connection, project_id)
        project_row = connection.execute(
            "SELECT project_id, config_json FROM projects WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        scheduler_policy = scheduler_policy_from_row(project_row)
        provider_capacity = queue_capacity_snapshot(connection, project_id)
        review_policy = review_policy_from_row(project_row)
        risk_policy = risk_policy_from_row(project_row)
        runtime_quota_view = runtime_quota_snapshot(connection, project_id)
        notification_policy = notification_policy_from_row(project_row)
        item = {
            **project,
            "blocked_tasks": blocked_counts.get(project_id, 0),
            "in_progress_tasks": in_progress_counts.get(project_id, 0),
            "open_alerts": open_alert_counts.get(project_id, 0),
            "critical_alerts": critical_alert_counts.get(project_id, 0),
            "active_sessions": active_session_counts.get(project_id, 0),
            "running_agents": running_agent_counts.get(project_id, 0),
            "open_quarantine_entries": quarantine_counts.get(project_id, 0),
            "dead_letter_entries": dead_letter_counts.get(project_id, 0),
            "review_queue_count": review_queue_counts.get(project_id, 0),
            "blocked_failure_count": blocked_failure_counts.get(project_id, 0),
            "suspect_run_count": suspect_run_counts.get(project_id, 0),
            "stale_agent_count": stale_agent_counts.get(project_id, 0),
            "repeated_failure_tasks": repeated_failure_task_count(connection, project_id=project_id),
            "provider_readiness": provider_readiness,
            "scheduler_policy": scheduler_policy,
            "provider_capacity": provider_capacity,
            "review_policy": review_policy,
            "risk_policy": risk_policy,
            "runtime_quotas": {
                **runtime_quotas_from_row(project_row),
                "runs_today": runtime_quota_view["usage"]["runs_today"],
                "live_runs_today": runtime_quota_view["usage"]["live_runs_today"],
                "runtime_seconds_today": runtime_quota_view["usage"]["runtime_seconds_today"],
            },
            "notification_policy": notification_policy,
            "at_scheduler_capacity": active_session_counts.get(project_id, 0) >= scheduler_policy["max_active_sessions"],
        }
        item["health"] = _health_status(project, item)
        portfolio_projects.append(item)

    portfolio_projects.sort(
        key=lambda item: (
            {"critical": 0, "warn": 1, "healthy": 2, "archived": 3}.get(item["health"], 9),
            0 if item["state"] == "active" else 1,
            item["name"].lower(),
        )
    )

    active_projects = [item for item in portfolio_projects if item["state"] == "active"]
    open_escalations = _fetch_command_center_escalations(connection)
    urgent_alerts = _fetch_command_center_alerts(connection)
    open_dead_letters = _fetch_command_center_dead_letters(connection)
    provider_job_backlog = _fetch_command_center_provider_jobs(connection)
    review_queue = _fetch_command_center_review_queue(connection)
    blocked_failures = _fetch_command_center_blocked_failures(connection)
    suspect_runs = _fetch_command_center_suspect_runs(connection)
    notification_counts = count_notification_outbox(connection)
    notification_outbox = _fetch_command_center_notifications(connection)
    return {
        "summary": {
            "active_projects": len(active_projects),
            "archived_projects": len([item for item in portfolio_projects if item["state"] == "archived"]),
            "open_alerts": sum(item["open_alerts"] for item in active_projects),
            "blocked_tasks": sum(item["blocked_tasks"] for item in active_projects),
            "active_sessions": sum(item["active_sessions"] for item in active_projects),
            "recovery_pressure": sum(
                item["open_quarantine_entries"] + item["dead_letter_entries"] + item["repeated_failure_tasks"]
                for item in active_projects
            ),
            "projects_with_issues": len([item for item in active_projects if item["health"] in {"critical", "warn"}]),
            "open_escalations": len(open_escalations),
            "queued_provider_jobs": len(provider_job_backlog),
            "queued_notifications": notification_counts["queued"],
            "failed_notifications": notification_counts["failed"],
            "review_queue": len(review_queue),
            "blocked_failures": len(blocked_failures),
            "suspect_runs": len(suspect_runs),
            "stale_agents": sum(item["stale_agent_count"] for item in active_projects),
        },
        "projects": portfolio_projects,
        "command_center": {
            "open_escalations": open_escalations,
            "urgent_alerts": urgent_alerts,
            "open_dead_letter_entries": open_dead_letters,
            "queued_provider_jobs": provider_job_backlog,
            "review_queue": review_queue,
            "blocked_failures": blocked_failures,
            "suspect_runs": suspect_runs,
            "notification_deliveries": notification_outbox,
        },
    }
