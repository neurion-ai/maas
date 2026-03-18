"""Background orchestration pass for supervisor plus queued provider jobs."""

import json

from maas.ids import generate_id
from maas.providers import list_provider_status
from maas.services.provider_runtime import process_next_provider_job
from maas.supervisor import run_supervisor_once


def _record_orchestrator_activity(connection, project_id, summary):
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, action, category, description, details_json, severity
        ) VALUES (?, ?, 'orchestrator_pass', 'orchestration', ?, ?, 'info')
        """,
        (
            generate_id("act"),
            project_id,
            "Background orchestration pass completed.",
            json.dumps(summary),
        ),
    )


def _provider_queue_controls(connection, project_id):
    controls = {}
    for provider in list_provider_status(connection, project_id=project_id):
        settings = provider.get("configurable_runtime_controls") or {}
        raw_limit = settings.get("job_limit_per_pass", 0)
        raw_paused = settings.get("queue_paused", False)
        try:
            job_limit = int(raw_limit)
        except (TypeError, ValueError):
            job_limit = 0
        if isinstance(raw_paused, str):
            queue_paused = raw_paused.strip().lower() in {"true", "1", "yes", "on"}
        else:
            queue_paused = bool(raw_paused)
        controls[provider["id"]] = {
            "job_limit_per_pass": max(job_limit, 0),
            "queue_paused": queue_paused,
        }
    return controls


def run_orchestrator_once(
    connection,
    project_paths,
    allocate_limit=None,
    provider_job_limit=2,
    project_id=None,
):
    supervisor_result = run_supervisor_once(
        connection,
        allocate_limit=allocate_limit,
        project_paths=project_paths,
        project_id=project_id,
    )

    project_runs = []
    total_jobs_processed = 0
    for project_run in supervisor_result["project_runs"]:
        scoped_project_id = project_run["project_id"]
        processed_jobs = []
        queue_controls = _provider_queue_controls(connection, scoped_project_id)
        for provider_id, control in queue_controls.items():
            if control["queue_paused"]:
                continue
            effective_limit = min(max(provider_job_limit or 0, 0), control["job_limit_per_pass"])
            for _ in range(effective_limit):
                next_job = process_next_provider_job(
                    connection,
                    project_paths,
                    actor_id="agent_allocator",
                    project_id=scoped_project_id,
                    provider_id=provider_id,
                )
                if not next_job["processed"]:
                    break
                processed_jobs.append(next_job["job"])
        total_jobs_processed += len(processed_jobs)
        summary = {
            "assigned_count": project_run["assigned_count"],
            "ready_changes": len(project_run["ready_changes"]),
            "stale_sessions": len(project_run["stale_sessions"]),
            "auto_recovered_tasks": len(project_run["auto_recovered_tasks"]),
            "provider_jobs_processed": len(processed_jobs),
            "queue_controls": queue_controls,
        }
        _record_orchestrator_activity(connection, scoped_project_id, summary)
        project_runs.append(
            {
                **project_run,
                "provider_jobs_processed": len(processed_jobs),
                "processed_jobs": processed_jobs,
                "queue_controls": queue_controls,
            }
        )

    connection.commit()
    return {
        "ready_changes": supervisor_result["ready_changes"],
        "allocations": supervisor_result["allocations"],
        "assigned_count": supervisor_result["assigned_count"],
        "stale_sessions": supervisor_result["stale_sessions"],
        "auto_recovered_tasks": supervisor_result["auto_recovered_tasks"],
        "provider_jobs_processed": total_jobs_processed,
        "project_runs": project_runs,
    }
