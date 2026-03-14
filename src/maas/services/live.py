"""Lightweight live snapshot and SSE helpers for dashboard refresh."""

import asyncio
import json
from datetime import datetime

from maas.services.failure_memory import repeated_failure_task_count


def build_live_snapshot(connection):
    latest_task = connection.execute("SELECT MAX(updated_at) AS value FROM tasks").fetchone()["value"]
    latest_activity = connection.execute("SELECT MAX(created_at) AS value FROM activity_log").fetchone()["value"]
    latest_alert = connection.execute("SELECT MAX(created_at) AS value FROM alerts").fetchone()["value"]
    latest_failure = connection.execute("SELECT MAX(created_at) AS value FROM failure_log").fetchone()["value"]
    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "counts": {
            "tasks_in_progress": connection.execute(
                "SELECT COUNT(*) AS count FROM tasks WHERE status = 'in_progress'"
            ).fetchone()["count"],
            "tasks_review": connection.execute(
                "SELECT COUNT(*) AS count FROM tasks WHERE status = 'review'"
            ).fetchone()["count"],
            "alerts_open": connection.execute(
                "SELECT COUNT(*) AS count FROM alerts WHERE status = 'open'"
            ).fetchone()["count"],
            "agents_running": connection.execute(
                "SELECT COUNT(*) AS count FROM agents WHERE status = 'running'"
            ).fetchone()["count"],
            "failures_total": connection.execute(
                "SELECT COUNT(*) AS count FROM failure_log"
            ).fetchone()["count"],
            "repeated_failure_tasks": repeated_failure_task_count(connection),
        },
        "revision": {
            "latest_task": latest_task,
            "latest_activity": latest_activity,
            "latest_alert": latest_alert,
            "latest_failure": latest_failure,
        },
    }


async def sse_stream(connection_factory, interval_seconds=2):
    while True:
        connection = connection_factory()
        try:
            snapshot = build_live_snapshot(connection)
        finally:
            connection.close()
        yield "event: dashboard\n"
        yield "data: {0}\n\n".format(json.dumps(snapshot))
        await asyncio.sleep(interval_seconds)
