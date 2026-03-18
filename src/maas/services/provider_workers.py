"""Detached provider worker pool helpers."""

from datetime import datetime
import json

from maas.services.provider_jobs import fetch_provider_job, next_queued_provider_job_id
from maas.services.projects import list_projects, resolve_project_id
from maas.services.queue_capacity import can_start_provider_jobs


WORKER_OFFLINE_AFTER_SECONDS = 60


def _parse_json(value):
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_timestamp(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _heartbeat_age_seconds(value):
    parsed = _parse_timestamp(value)
    if parsed is None:
        return None
    return int((datetime.utcnow() - parsed).total_seconds())


def _effective_worker_status(row):
    heartbeat_age = _heartbeat_age_seconds(row["heartbeat_at"])
    status = row["status"]
    if heartbeat_age is not None and heartbeat_age > WORKER_OFFLINE_AFTER_SECONDS:
        status = "offline"
    return status, heartbeat_age


def _worker_row_to_dict(row):
    status, heartbeat_age_seconds = _effective_worker_status(row)
    metadata = _parse_json(row["metadata_json"])
    return {
        "worker_id": row["worker_id"],
        "project_id": row["project_id"],
        "project_name": row["project_name"],
        "provider_id": row["provider_id"],
        "status": status,
        "current_job_id": row["current_job_id"],
        "current_job_title": row["current_job_title"],
        "last_job_id": row["last_job_id"],
        "last_job_status": row["last_job_status"],
        "heartbeat_at": row["heartbeat_at"],
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "metadata": metadata,
    }


def upsert_provider_worker(connection, worker_id, project_id=None, provider_id=None, status="idle", current_job_id=None, last_job_id=None, last_job_status=None, metadata=None):
    resolved_project_id = resolve_project_id(connection, project_id, include_archived=False) if project_id else None
    connection.execute(
        """
        INSERT INTO provider_workers (
            worker_id, project_id, provider_id, status, current_job_id, last_job_id, last_job_status, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(worker_id) DO UPDATE SET
            project_id = excluded.project_id,
            provider_id = excluded.provider_id,
            status = excluded.status,
            current_job_id = excluded.current_job_id,
            last_job_id = COALESCE(excluded.last_job_id, provider_workers.last_job_id),
            last_job_status = COALESCE(excluded.last_job_status, provider_workers.last_job_status),
            metadata_json = excluded.metadata_json,
            heartbeat_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            worker_id,
            resolved_project_id,
            provider_id,
            status,
            current_job_id,
            last_job_id,
            last_job_status,
            json.dumps(metadata or {}),
        ),
    )


def fetch_provider_workers(connection, project_id=None, provider_id=None, limit=20):
    clauses = []
    parameters = []
    if project_id:
        resolved_project_id = resolve_project_id(connection, project_id, include_archived=False)
        if resolved_project_id is None:
            return []
        clauses.append("provider_workers.project_id = ?")
        parameters.append(resolved_project_id)
    if provider_id:
        clauses.append("provider_workers.provider_id = ?")
        parameters.append(provider_id)
    where_clause = "WHERE {0}".format(" AND ".join(clauses)) if clauses else ""
    rows = connection.execute(
        """
        SELECT
            provider_workers.worker_id,
            provider_workers.project_id,
            projects.name AS project_name,
            provider_workers.provider_id,
            provider_workers.status,
            provider_workers.current_job_id,
            provider_workers.last_job_id,
            provider_workers.last_job_status,
            provider_workers.metadata_json,
            provider_workers.created_at,
            provider_workers.heartbeat_at,
            provider_workers.updated_at,
            tasks.title AS current_job_title
        FROM provider_workers
        LEFT JOIN projects ON projects.project_id = provider_workers.project_id
        LEFT JOIN provider_job_queue ON provider_job_queue.job_id = provider_workers.current_job_id
        LEFT JOIN tasks ON tasks.task_id = provider_job_queue.task_id
        {where_clause}
        ORDER BY provider_workers.heartbeat_at DESC, provider_workers.created_at DESC
        LIMIT ?
        """.format(where_clause=where_clause),
        tuple(parameters + [limit]),
    ).fetchall()
    return [_worker_row_to_dict(row) for row in rows]


def default_provider_worker_summary():
    return {
        "total_workers": 0,
        "idle_workers": 0,
        "busy_workers": 0,
        "offline_workers": 0,
    }


def fetch_provider_worker_summary(connection, project_id=None):
    summary = default_provider_worker_summary()
    for worker in fetch_provider_workers(connection, project_id=project_id, limit=200):
        summary["total_workers"] += 1
        if worker["status"] == "busy":
            summary["busy_workers"] += 1
        elif worker["status"] == "offline":
            summary["offline_workers"] += 1
        else:
            summary["idle_workers"] += 1
    return summary


def _select_next_job_id(connection, project_id=None, provider_id=None):
    if project_id:
        can_start, _snapshot = can_start_provider_jobs(connection, project_id)
        if not can_start:
            return project_id, None
        return project_id, next_queued_provider_job_id(connection, project_id=project_id, provider_id=provider_id)
    active_projects = [project["project_id"] for project in list_projects(connection, include_archived=False)]
    for scoped_project_id in active_projects:
        can_start, _snapshot = can_start_provider_jobs(connection, scoped_project_id)
        if not can_start:
            continue
        job_id = next_queued_provider_job_id(connection, project_id=scoped_project_id, provider_id=provider_id)
        if job_id is not None:
            return scoped_project_id, job_id
    return None, None


def run_provider_worker_once(connection, project_paths, worker_id, project_id=None, provider_id=None):
    from maas.services.provider_runtime import process_provider_job

    scoped_project_id = resolve_project_id(connection, project_id, include_archived=False) if project_id else None
    upsert_provider_worker(
        connection,
        worker_id,
        project_id=scoped_project_id,
        provider_id=provider_id,
        status="idle",
        metadata={"mode": "provider_worker"},
    )
    connection.commit()

    if scoped_project_id:
        job_project_id, job_id = _select_next_job_id(connection, project_id=scoped_project_id, provider_id=provider_id)
    else:
        job_project_id, job_id = _select_next_job_id(connection, provider_id=provider_id)

    if job_id is None:
        upsert_provider_worker(
            connection,
            worker_id,
            project_id=scoped_project_id,
            provider_id=provider_id,
            status="idle",
            metadata={"mode": "provider_worker"},
        )
        connection.commit()
        return {"processed": False, "job": None, "worker_id": worker_id}

    upsert_provider_worker(
        connection,
        worker_id,
        project_id=job_project_id,
        provider_id=provider_id,
        status="busy",
        current_job_id=job_id,
        metadata={"mode": "provider_worker"},
    )
    connection.commit()
    try:
        job = process_provider_job(
            connection,
            project_paths,
            job_id,
            actor_id="agent_allocator",
            worker_id=worker_id,
        )
    except ValueError as exc:
        latest_job = None
        if str(exc) == "Provider job is no longer queued":
            latest_job = fetch_provider_job(connection, job_id, include_archived=True)
            upsert_provider_worker(
                connection,
                worker_id,
                project_id=job_project_id,
                provider_id=provider_id,
                status="idle",
                current_job_id=None,
                last_job_id=job_id,
                last_job_status=latest_job["status"] if latest_job else None,
                metadata={"mode": "provider_worker"},
            )
            connection.commit()
            return {"processed": False, "job": latest_job, "worker_id": worker_id}
        upsert_provider_worker(
            connection,
            worker_id,
            project_id=job_project_id,
            provider_id=provider_id,
            status="idle",
            current_job_id=None,
            metadata={"mode": "provider_worker"},
        )
        connection.commit()
        raise
    upsert_provider_worker(
        connection,
        worker_id,
        project_id=job["project_id"],
        provider_id=job["provider_id"],
        status="idle",
        current_job_id=None,
        last_job_id=job["job_id"],
        last_job_status=job["status"],
        metadata={"mode": "provider_worker"},
    )
    connection.commit()
    return {"processed": True, "job": job, "worker_id": worker_id}
