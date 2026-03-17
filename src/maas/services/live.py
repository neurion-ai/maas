"""Lightweight live snapshot helpers for dashboard refresh."""

import asyncio
import json
from datetime import datetime

from maas.services.escalations import count_open_escalations
from maas.services.failure_memory import repeated_failure_task_count


def build_live_snapshot(connection, project_id=None):
    task_where = " WHERE project_id = ?" if project_id is not None else ""
    params = (project_id,) if project_id is not None else ()
    latest_task = connection.execute("SELECT MAX(updated_at) AS value FROM tasks" + task_where, params).fetchone()["value"]
    latest_activity = connection.execute(
        "SELECT MAX(created_at) AS value FROM activity_log" + task_where,
        params,
    ).fetchone()["value"]
    latest_alert = connection.execute("SELECT MAX(created_at) AS value FROM alerts" + task_where, params).fetchone()["value"]
    latest_failure = connection.execute(
        "SELECT MAX(created_at) AS value FROM failure_log" + task_where,
        params,
    ).fetchone()["value"]
    latest_escalation = connection.execute(
        "SELECT MAX(created_at) AS value FROM escalation_queue" + task_where,
        params,
    ).fetchone()["value"]
    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "counts": {
            "tasks_in_progress": connection.execute(
                "SELECT COUNT(*) AS count FROM tasks WHERE status = 'in_progress'"
                + (" AND project_id = ?" if project_id is not None else ""),
                params,
            ).fetchone()["count"],
            "tasks_review": connection.execute(
                "SELECT COUNT(*) AS count FROM tasks WHERE status = 'review'"
                + (" AND project_id = ?" if project_id is not None else ""),
                params,
            ).fetchone()["count"],
            "alerts_open": connection.execute(
                "SELECT COUNT(*) AS count FROM alerts WHERE status = 'open'"
                + (" AND project_id = ?" if project_id is not None else ""),
                params,
            ).fetchone()["count"],
            "escalations_open": count_open_escalations(connection, project_id=project_id),
            "agents_running": connection.execute(
                "SELECT COUNT(*) AS count FROM agents WHERE status = 'running'"
                + (" AND project_id = ?" if project_id is not None else ""),
                params,
            ).fetchone()["count"],
            "failures_total": connection.execute(
                "SELECT COUNT(*) AS count FROM failure_log"
                + (" WHERE project_id = ?" if project_id is not None else ""),
                params,
            ).fetchone()["count"],
            "repeated_failure_tasks": repeated_failure_task_count(connection, project_id=project_id),
        },
        "revision": {
            "latest_task": latest_task,
            "latest_activity": latest_activity,
            "latest_alert": latest_alert,
            "latest_failure": latest_failure,
            "latest_escalation": latest_escalation,
        },
    }


async def sse_stream(connection_factory, interval_seconds=2, project_id=None):
    while True:
        connection = connection_factory()
        try:
            snapshot = build_live_snapshot(connection, project_id=project_id)
        finally:
            connection.close()
        yield "event: dashboard\n"
        yield "data: {0}\n\n".format(json.dumps(snapshot))
        await asyncio.sleep(interval_seconds)


async def websocket_stream(send_snapshot, connection_factory, interval_seconds=2, project_id=None):
    while True:
        connection = connection_factory()
        try:
            snapshot = build_live_snapshot(connection, project_id=project_id)
        finally:
            connection.close()
        await send_snapshot(snapshot)
        await asyncio.sleep(interval_seconds)
