"""Background orchestration pass for supervisor plus queued provider jobs."""

import json

from maas.ids import generate_id
from maas.providers import get_provider_runtime_settings, list_provider_status, provider_run_targets
from maas.services.failure_memory import failure_attempt_count
from maas.services.queue_capacity import queue_capacity_snapshot
from maas.services.provider_runtime import process_next_provider_job, queue_provider_task
from maas.services.provider_workers import launch_detached_provider_workers
from maas.services.review_policy import evaluate_review_decision_state, fetch_project_review_policy
from maas.services.steering import apply_review_decision
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


def _provider_queue_paused(provider):
    settings = provider.get("configurable_runtime_controls") or {}
    raw_value = settings.get("queue_paused", False)
    if isinstance(raw_value, str):
        return raw_value.strip().lower() in {"true", "1", "yes", "on"}
    return bool(raw_value)


def _provider_is_launch_ready(provider):
    if not provider.get("is_runnable"):
        return False
    if _provider_queue_paused(provider):
        return False
    execution_mode = provider.get("effective_execution_mode") or provider.get("execution_mode")
    if execution_mode == "local_simulation":
        return True
    preflight_status = (provider.get("latest_preflight") or {}).get("status")
    if preflight_status in {"passed", "simulation_ready"}:
        return True
    return provider.get("status") in {"configured", "available"}


def _preferred_launch_provider_id(provider_statuses, preferred_provider_id=None):
    statuses_by_id = {provider["id"]: provider for provider in provider_statuses}
    if preferred_provider_id:
        preferred = statuses_by_id.get(preferred_provider_id)
        if preferred is not None and _provider_is_launch_ready(preferred):
            return preferred_provider_id

    fallback_order = ["openai_codex", "python_script", "claude_code"]
    for provider_id in fallback_order:
        provider = statuses_by_id.get(provider_id)
        if provider is not None and _provider_is_launch_ready(provider):
            return provider_id
    for provider in provider_statuses:
        if _provider_is_launch_ready(provider):
            return provider["id"]
    return None


def _queue_launch_ready_codex_work(connection, project_paths, project_id, queue_controls, provider_job_limit, project_capacity):
    provider_statuses = list_provider_status(connection, project_id=project_id)
    provider_id = _preferred_launch_provider_id(
        provider_statuses,
        preferred_provider_id=project_capacity.get("preferred_provider_id"),
    )
    if provider_id is None:
        return [], None

    control = queue_controls.get(provider_id) or {}
    if control.get("queue_paused"):
        return [], provider_id

    effective_limit = min(max(provider_job_limit or 0, 0), control.get("job_limit_per_pass", 0))
    if effective_limit <= 0:
        return [], provider_id

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
    return queued_jobs, provider_id


def _provider_uses_detached_workers(connection, project_id, provider_id):
    provider, _settings = get_provider_runtime_settings(
        provider_id,
        connection=connection,
        project_id=project_id,
    )
    return provider.get("effective_execution_mode") in {"codex_cli", "claude_cli"}


def _queued_provider_job_count(connection, project_id, provider_id):
    row = connection.execute(
        """
        SELECT COUNT(*) AS queued_jobs
        FROM provider_job_queue
        WHERE project_id = ?
          AND provider_id = ?
          AND status = 'queued'
        """,
        (project_id, provider_id),
    ).fetchone()
    return int(row["queued_jobs"]) if row is not None else 0


def _latest_verification_by_task(connection, project_id):
    rows = connection.execute(
        """
        SELECT task_id, status, finished_at
        FROM verification_runs
        WHERE project_id = ?
        ORDER BY finished_at DESC, verification_run_id DESC
        """,
        (project_id,),
    ).fetchall()
    latest = {}
    for row in rows:
        latest.setdefault(row["task_id"], []).append({"status": row["status"], "finished_at": row["finished_at"]})
    return latest


def _auto_approve_low_risk_reviews(connection, project_id):
    project_policy = fetch_project_review_policy(connection, project_id)
    if not project_policy.get("auto_approve_low_risk", False):
        return []
    verification_by_task = _latest_verification_by_task(connection, project_id)
    rows = connection.execute(
        """
        SELECT task_id, project_id, title, status, priority, review_state
        FROM tasks
        WHERE project_id = ?
          AND status = 'review'
        ORDER BY priority DESC, created_at ASC
        LIMIT 25
        """,
        (project_id,),
    ).fetchall()
    approved = []
    for row in rows:
        state = evaluate_review_decision_state(
            connection,
            dict(row),
            project_policy,
            verification_runs=verification_by_task.get(row["task_id"], []),
            failure_count=failure_attempt_count(connection, row["task_id"]),
        )
        if not state.get("auto_approve_eligible"):
            continue
        apply_review_decision(connection, row["task_id"], "agent_allocator", "approve", commit=False, automated=True)
        approved.append(row["task_id"])
    return approved


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
    total_jobs_dispatched = 0
    total_auto_approved_reviews = 0
    for project_run in supervisor_result["project_runs"]:
        scoped_project_id = project_run["project_id"]
        auto_approved_reviews = _auto_approve_low_risk_reviews(connection, scoped_project_id)
        total_auto_approved_reviews += len(auto_approved_reviews)
        queued_jobs = []
        processed_jobs = []
        dispatched_worker_ids = []
        detached_workers_started = False
        provider_statuses = list_provider_status(connection, project_id=scoped_project_id)
        queue_controls = _provider_queue_controls(provider_statuses)
        project_capacity = queue_capacity_snapshot(connection, scoped_project_id)
        launch_provider_id = None
        if project_capacity["queue_mode"] == "paused":
            queue_controls["__project_capacity__"] = project_capacity
            summary = {
                "assigned_count": project_run["assigned_count"],
                "ready_changes": len(project_run["ready_changes"]),
                "stale_sessions": len(project_run["stale_sessions"]),
                "auto_recovered_tasks": len(project_run["auto_recovered_tasks"]),
                "auto_replanned_tasks": len(project_run.get("auto_replanned_tasks") or []),
                "provider_jobs_queued": 0,
                "provider_jobs_processed": 0,
                "provider_jobs_dispatched": 0,
                "auto_approved_reviews": len(auto_approved_reviews),
                "launch_provider_id": None,
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
                    "provider_jobs_dispatched": 0,
                    "dispatched_worker_ids": [],
                    "auto_approved_reviews": len(auto_approved_reviews),
                    "launch_provider_id": None,
                    "queue_controls": queue_controls,
                    "project_capacity": project_capacity,
                }
            )
            continue
        if auto_launch_assigned_work and project_capacity["queue_mode"] == "running":
            queued_jobs, launch_provider_id = _queue_launch_ready_codex_work(
                connection,
                project_paths,
                scoped_project_id,
                queue_controls,
                provider_job_limit,
                project_capacity,
            )
        queued_job_counts = {}
        for job in queued_jobs:
            queued_job_counts[job["provider_id"]] = queued_job_counts.get(job["provider_id"], 0) + 1
        for provider_id, control in queue_controls.items():
            if control["queue_paused"]:
                continue
            effective_limit = min(max(provider_job_limit or 0, 0), control["job_limit_per_pass"])
            if effective_limit <= 0:
                continue
            if _provider_uses_detached_workers(connection, scoped_project_id, provider_id):
                launch_count = min(
                    _queued_provider_job_count(connection, scoped_project_id, provider_id),
                    effective_limit,
                )
                if launch_count > 0:
                    if not detached_workers_started:
                        connection.commit()
                        detached_workers_started = True
                    dispatched_worker_ids.extend(
                        launch_detached_provider_workers(
                            project_paths,
                            project_id=scoped_project_id,
                            provider_id=provider_id,
                            worker_count=launch_count,
                        )
                    )
                continue
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
        total_jobs_dispatched += len(dispatched_worker_ids)
        summary = {
            "assigned_count": project_run["assigned_count"],
            "ready_changes": len(project_run["ready_changes"]),
            "stale_sessions": len(project_run["stale_sessions"]),
            "auto_recovered_tasks": len(project_run["auto_recovered_tasks"]),
            "auto_replanned_tasks": len(project_run.get("auto_replanned_tasks") or []),
            "provider_jobs_queued": len(queued_jobs),
            "provider_jobs_processed": len(processed_jobs),
            "provider_jobs_dispatched": len(dispatched_worker_ids),
            "auto_approved_reviews": len(auto_approved_reviews),
            "launch_provider_id": launch_provider_id,
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
                "provider_jobs_dispatched": len(dispatched_worker_ids),
                "dispatched_worker_ids": dispatched_worker_ids,
                "auto_approved_reviews": len(auto_approved_reviews),
                "launch_provider_id": launch_provider_id,
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
        "provider_jobs_dispatched": total_jobs_dispatched,
        "auto_approved_reviews": total_auto_approved_reviews,
        "project_runs": project_runs,
    }
