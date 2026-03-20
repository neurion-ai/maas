"""Background orchestration pass for supervisor plus queued provider jobs."""

import json

from maas.ids import generate_id
from maas.providers import list_provider_status, provider_run_targets
from maas.services.queue_capacity import queue_capacity_snapshot
from maas.services.provider_runtime import process_next_provider_job, queue_provider_task
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


def _provider_queue_controls(provider_statuses):
    controls = {}
    for provider in provider_statuses:
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


def _preferred_codex_provider_id(provider_statuses):
    for provider in provider_statuses:
        if provider["id"] == "openai_codex" and provider.get("is_runnable"):
            return provider["id"]
    return None


def _queue_launch_ready_codex_work(connection, project_paths, project_id, queue_controls, provider_job_limit):
    provider_id = _preferred_codex_provider_id(list_provider_status(connection, project_id=project_id))
    if provider_id is None:
        return []

    control = queue_controls.get(provider_id) or {}
    if control.get("queue_paused"):
        return []

    effective_limit = min(max(provider_job_limit or 0, 0), control.get("job_limit_per_pass", 0))
    if effective_limit <= 0:
        return []

    queued_jobs = []
    for target in provider_run_targets(connection, project_id, limit=effective_limit):
        try:
            queued_jobs.append(
                queue_provider_task(
                    connection,
                    project_paths,
                    provider_id=provider_id,
                    actor_id="agent_allocator",
                    project_id=project_id,
                    agent_id=target["agent_id"],
                    task_id=target["task_id"],
                )
            )
        except ValueError as exc:
            if "already exists" in str(exc) or "not eligible" in str(exc):
                continue
            raise
    return queued_jobs


def run_orchestrator_once(
    connection,
    project_paths,
    allocate_limit=None,
    provider_job_limit=2,
    project_id=None,
    auto_launch_assigned_work=False,
):
    supervisor_result = run_supervisor_once(
        connection,
        allocate_limit=allocate_limit,
        project_paths=project_paths,
        project_id=project_id,
    )

    project_runs = []
    total_jobs_queued = 0
    total_jobs_processed = 0
    for project_run in supervisor_result["project_runs"]:
        scoped_project_id = project_run["project_id"]
        queued_jobs = []
        processed_jobs = []
        provider_statuses = list_provider_status(connection, project_id=scoped_project_id)
        queue_controls = _provider_queue_controls(provider_statuses)
        project_capacity = queue_capacity_snapshot(connection, scoped_project_id)
        if project_capacity["queue_mode"] != "running":
            queue_controls["__project_capacity__"] = project_capacity
            summary = {
                "assigned_count": project_run["assigned_count"],
                "ready_changes": len(project_run["ready_changes"]),
                "stale_sessions": len(project_run["stale_sessions"]),
                "auto_recovered_tasks": len(project_run["auto_recovered_tasks"]),
                "auto_replanned_tasks": len(project_run.get("auto_replanned_tasks") or []),
                "provider_jobs_queued": 0,
                "provider_jobs_processed": 0,
                "queue_controls": queue_controls,
                "project_capacity": project_capacity,
            }
            _record_orchestrator_activity(connection, scoped_project_id, summary)
            project_runs.append(
                {
                    **project_run,
                    "provider_jobs_queued": 0,
                    "queued_jobs": [],
                    "provider_jobs_processed": 0,
                    "processed_jobs": [],
                    "queue_controls": queue_controls,
                    "project_capacity": project_capacity,
                }
            )
            continue
        if auto_launch_assigned_work:
            queued_jobs = _queue_launch_ready_codex_work(
                connection,
                project_paths,
                scoped_project_id,
                queue_controls,
                provider_job_limit,
            )
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
        total_jobs_queued += len(queued_jobs)
        total_jobs_processed += len(processed_jobs)
        summary = {
            "assigned_count": project_run["assigned_count"],
            "ready_changes": len(project_run["ready_changes"]),
            "stale_sessions": len(project_run["stale_sessions"]),
            "auto_recovered_tasks": len(project_run["auto_recovered_tasks"]),
            "auto_replanned_tasks": len(project_run.get("auto_replanned_tasks") or []),
            "provider_jobs_queued": len(queued_jobs),
            "provider_jobs_processed": len(processed_jobs),
            "queue_controls": queue_controls,
            "project_capacity": project_capacity,
        }
        _record_orchestrator_activity(connection, scoped_project_id, summary)
        project_runs.append(
            {
                **project_run,
                "provider_jobs_queued": len(queued_jobs),
                "queued_jobs": queued_jobs,
                "provider_jobs_processed": len(processed_jobs),
                "processed_jobs": processed_jobs,
                "queue_controls": queue_controls,
                "project_capacity": project_capacity,
            }
        )

    connection.commit()
    return {
        "ready_changes": supervisor_result["ready_changes"],
        "allocations": supervisor_result["allocations"],
        "assigned_count": supervisor_result["assigned_count"],
        "stale_sessions": supervisor_result["stale_sessions"],
        "auto_recovered_tasks": supervisor_result["auto_recovered_tasks"],
        "auto_replanned_tasks": supervisor_result.get("auto_replanned_tasks") or [],
        "provider_jobs_queued": total_jobs_queued,
        "provider_jobs_processed": total_jobs_processed,
        "project_runs": project_runs,
    }
