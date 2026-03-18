"""Provider job queue storage and read helpers."""

import json

from maas.ids import generate_id
from maas.services.projects import resolve_project_id


_EMPTY_JOB_SUMMARY = {
    "queued_jobs": 0,
    "running_jobs": 0,
    "completed_jobs": 0,
    "failed_jobs": 0,
    "cancelled_jobs": 0,
    "last_job_at": None,
}


def _parse_json(value):
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _job_row_to_dict(row):
    result = _parse_json(row["result_json"])
    error = _parse_json(row["error_json"])
    return {
        "job_id": row["job_id"],
        "project_id": row["project_id"],
        "provider_id": row["provider_id"],
        "task_id": row["task_id"],
        "title": row["task_title"],
        "goal_title": row["goal_title"],
        "agent_id": row["agent_id"],
        "agent_name": row["agent_name"],
        "status": row["status"],
        "queued_by": row["queued_by"],
        "worker_id": row["worker_id"],
        "artifact_path": row["artifact_path"],
        "session_id": row["session_id"],
        "artifact_id": row["artifact_id"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "updated_at": row["updated_at"],
        "execution_mode": result.get("execution_mode"),
        "failure_kind": error.get("failure_kind"),
        "failure_detail": error.get("failure_detail"),
    }


def _provider_job_rows_query(status=None, provider_id=None):
    clauses = ["provider_job_queue.project_id = ?"]
    params = []
    if status:
        clauses.append("provider_job_queue.status = ?")
        params.append(status)
    if provider_id:
        clauses.append("provider_job_queue.provider_id = ?")
        params.append(provider_id)
    return " AND ".join(clauses), params


def insert_provider_job(connection, project_id, provider_id, task_id, agent_id, queued_by, artifact_path=None):
    job_id = generate_id("job")
    connection.execute(
        """
        INSERT INTO provider_job_queue (
            job_id, project_id, provider_id, task_id, agent_id, status, queued_by, artifact_path
        ) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)
        """,
        (job_id, project_id, provider_id, task_id, agent_id, queued_by, artifact_path),
    )
    return fetch_provider_job(connection, job_id, include_archived=True)


def fetch_provider_job(connection, job_id, include_archived=False):
    state_clause = "" if include_archived else "AND projects.state = 'active'"
    row = connection.execute(
        """
        SELECT
            provider_job_queue.job_id,
            provider_job_queue.project_id,
            provider_job_queue.provider_id,
            provider_job_queue.task_id,
            tasks.title AS task_title,
            goals.title AS goal_title,
            provider_job_queue.agent_id,
            agents.display_name AS agent_name,
            provider_job_queue.status,
            provider_job_queue.queued_by,
            provider_job_queue.worker_id,
            provider_job_queue.artifact_path,
            provider_job_queue.session_id,
            provider_job_queue.artifact_id,
            provider_job_queue.result_json,
            provider_job_queue.error_json,
            provider_job_queue.created_at,
            provider_job_queue.started_at,
            provider_job_queue.finished_at,
            provider_job_queue.updated_at
        FROM provider_job_queue
        JOIN projects ON projects.project_id = provider_job_queue.project_id
        LEFT JOIN tasks ON tasks.task_id = provider_job_queue.task_id
        LEFT JOIN goals ON goals.goal_id = tasks.goal_id
        LEFT JOIN agents ON agents.agent_id = provider_job_queue.agent_id
        WHERE provider_job_queue.job_id = ?
          {state_clause}
        """.format(state_clause=state_clause),
        (job_id,),
    ).fetchone()
    return _job_row_to_dict(row) if row is not None else None


def find_open_provider_job(connection, project_id, provider_id, task_id):
    return connection.execute(
        """
        SELECT job_id
        FROM provider_job_queue
        WHERE project_id = ?
          AND provider_id = ?
          AND task_id = ?
          AND status IN ('queued', 'running')
        ORDER BY created_at DESC, rowid DESC
        LIMIT 1
        """,
        (project_id, provider_id, task_id),
    ).fetchone()


def fetch_provider_jobs(connection, project_id=None, provider_id=None, status=None, limit=20, include_archived=False):
    resolved_project_id = resolve_project_id(connection, project_id, include_archived=include_archived)
    if resolved_project_id is None:
        return []
    where_clause, params = _provider_job_rows_query(status=status, provider_id=provider_id)
    state_clause = "" if include_archived else "AND projects.state = 'active'"
    rows = connection.execute(
        """
        SELECT
            provider_job_queue.job_id,
            provider_job_queue.project_id,
            provider_job_queue.provider_id,
            provider_job_queue.task_id,
            tasks.title AS task_title,
            goals.title AS goal_title,
            provider_job_queue.agent_id,
            agents.display_name AS agent_name,
            provider_job_queue.status,
            provider_job_queue.queued_by,
            provider_job_queue.worker_id,
            provider_job_queue.artifact_path,
            provider_job_queue.session_id,
            provider_job_queue.artifact_id,
            provider_job_queue.result_json,
            provider_job_queue.error_json,
            provider_job_queue.created_at,
            provider_job_queue.started_at,
            provider_job_queue.finished_at,
            provider_job_queue.updated_at
        FROM provider_job_queue
        JOIN projects ON projects.project_id = provider_job_queue.project_id
        LEFT JOIN tasks ON tasks.task_id = provider_job_queue.task_id
        LEFT JOIN goals ON goals.goal_id = tasks.goal_id
        LEFT JOIN agents ON agents.agent_id = provider_job_queue.agent_id
        WHERE {where_clause}
          {state_clause}
        ORDER BY
            CASE provider_job_queue.status
                WHEN 'running' THEN 0
                WHEN 'queued' THEN 1
                ELSE 2
            END,
            COALESCE(provider_job_queue.started_at, provider_job_queue.created_at) DESC,
            provider_job_queue.rowid DESC
        LIMIT ?
        """.format(where_clause=where_clause, state_clause=state_clause),
        tuple([resolved_project_id] + params + [limit]),
    ).fetchall()
    return [_job_row_to_dict(row) for row in rows]


def fetch_provider_job_summaries(connection, project_id=None):
    resolved_project_id = resolve_project_id(connection, project_id)
    if resolved_project_id is None:
        return {}
    rows = connection.execute(
        """
        SELECT
            provider_id,
            SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) AS queued_jobs,
            SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running_jobs,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_jobs,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_jobs,
            SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_jobs,
            MAX(COALESCE(finished_at, started_at, created_at)) AS last_job_at
        FROM provider_job_queue
        WHERE project_id = ?
        GROUP BY provider_id
        """,
        (resolved_project_id,),
    ).fetchall()
    return {
        row["provider_id"]: {
            "queued_jobs": row["queued_jobs"],
            "running_jobs": row["running_jobs"],
            "completed_jobs": row["completed_jobs"],
            "failed_jobs": row["failed_jobs"],
            "cancelled_jobs": row["cancelled_jobs"],
            "last_job_at": row["last_job_at"],
        }
        for row in rows
    }


def default_provider_job_summary():
    return dict(_EMPTY_JOB_SUMMARY)


def start_provider_job(connection, job_id, worker_id):
    cursor = connection.execute(
        """
        UPDATE provider_job_queue
        SET status = 'running',
            worker_id = ?,
            started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
            updated_at = CURRENT_TIMESTAMP
        WHERE job_id = ?
          AND status = 'queued'
        """,
        (worker_id, job_id),
    )
    if cursor.rowcount == 0:
        return None
    return fetch_provider_job(connection, job_id, include_archived=True)


def complete_provider_job(connection, job_id, result):
    connection.execute(
        """
        UPDATE provider_job_queue
        SET status = 'completed',
            session_id = ?,
            artifact_id = ?,
            result_json = ?,
            finished_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE job_id = ?
        """,
        (
            result.get("session_id"),
            result.get("artifact_id"),
            json.dumps(
                {
                    "execution_mode": (result.get("execution") or {}).get("execution_mode"),
                    "artifact_path": result.get("artifact_path"),
                }
            ),
            job_id,
        ),
    )
    return fetch_provider_job(connection, job_id, include_archived=True)


def fail_provider_job(connection, job_id, error):
    connection.execute(
        """
        UPDATE provider_job_queue
        SET status = 'failed',
            error_json = ?,
            finished_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE job_id = ?
        """,
        (json.dumps(error), job_id),
    )
    return fetch_provider_job(connection, job_id, include_archived=True)


def next_queued_provider_job_id(connection, project_id=None, provider_id=None):
    if project_id is not None:
        resolved_project_id = resolve_project_id(connection, project_id)
        if resolved_project_id is None:
            return None
        where_clause, params = _provider_job_rows_query(status="queued", provider_id=provider_id)
        parameters = tuple([resolved_project_id] + params)
    else:
        where_clause = "provider_job_queue.status = 'queued'"
        parameters = ()
        if provider_id:
            where_clause += " AND provider_job_queue.provider_id = ?"
            parameters = (provider_id,)
    row = connection.execute(
        """
        SELECT provider_job_queue.job_id
        FROM provider_job_queue
        JOIN projects ON projects.project_id = provider_job_queue.project_id
        WHERE {where_clause}
          AND projects.state = 'active'
        ORDER BY provider_job_queue.created_at ASC, provider_job_queue.rowid ASC
        LIMIT 1
        """.format(where_clause=where_clause),
        parameters,
    ).fetchone()
    return row["job_id"] if row is not None else None
