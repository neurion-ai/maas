"""Cross-project portfolio read model."""

from maas.providers import list_provider_status
from maas.services.failure_memory import repeated_failure_task_count
from maas.services.projects import list_projects
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

    portfolio_projects = []
    for project in projects:
        project_id = project["project_id"]
        provider_readiness = _provider_readiness_summary(connection, project_id)
        project_row = connection.execute(
            "SELECT project_id, config_json FROM projects WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        scheduler_policy = scheduler_policy_from_row(project_row)
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
            "repeated_failure_tasks": repeated_failure_task_count(connection, project_id=project_id),
            "provider_readiness": provider_readiness,
            "scheduler_policy": scheduler_policy,
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
        },
        "projects": portfolio_projects,
    }
