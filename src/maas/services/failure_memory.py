"""Failure memory helpers for resilience and repeated-failure visibility."""

import json

from maas.ids import generate_id


REPEATED_FAILURE_THRESHOLD = 2


def record_failure(connection, project_id, failure_type, summary, task_id=None, session_id=None, agent_id=None, details=None):
    failure_id = generate_id("fail")
    connection.execute(
        """
        INSERT INTO failure_log (
            failure_id, project_id, task_id, session_id, agent_id, failure_type, summary, detail_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            failure_id,
            project_id,
            task_id,
            session_id,
            agent_id,
            failure_type,
            summary,
            json.dumps(details or {}),
        ),
    )
    return failure_id


def _failure_count_for_task(connection, task_id):
    if task_id is None:
        return 0
    return connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM failure_log
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()["count"]


def maybe_raise_repeated_failure_alert(connection, project_id, task_id, summary):
    if task_id is None:
        return None
    failure_count = _failure_count_for_task(connection, task_id)
    if failure_count < REPEATED_FAILURE_THRESHOLD:
        return None

    task = connection.execute(
        """
        SELECT task_id, title
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if task is None:
        return None

    existing = connection.execute(
        """
        SELECT alert_id
        FROM alerts
        WHERE project_id = ?
          AND status IN ('open', 'acknowledged')
          AND title = 'Repeated task failures'
          AND description LIKE ?
        LIMIT 1
        """,
        (project_id, "%{0}%".format(task_id)),
    ).fetchone()
    if existing is not None:
        return None

    alert_id = generate_id("alert")
    description = "Task {0} ({1}) has failed {2} times. Latest failure: {3}".format(
        task_id,
        task["title"],
        failure_count,
        summary,
    )
    connection.execute(
        """
        INSERT INTO alerts (
            alert_id, project_id, severity, title, description, status
        ) VALUES (?, ?, 'critical', 'Repeated task failures', ?, 'open')
        """,
        (alert_id, project_id, description),
    )
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, task_id, action, category, description, details_json, severity
        ) VALUES (?, ?, ?, 'repeated_failure_alert', 'resilience', ?, ?, 'warning')
        """,
        (
            generate_id("act"),
            project_id,
            task_id,
            "Repeated failure alert raised for task {0}.".format(task["title"]),
            json.dumps({"task_id": task_id, "failure_count": failure_count}),
        ),
    )
    return {"alert_id": alert_id, "task_id": task_id, "failure_count": failure_count}


def fetch_failure_log(connection, limit=20):
    rows = connection.execute(
        """
        SELECT
            failure_log.failure_id,
            failure_log.project_id,
            failure_log.task_id,
            failure_log.session_id,
            failure_log.agent_id,
            failure_log.failure_type,
            failure_log.summary,
            failure_log.detail_json,
            failure_log.created_at,
            tasks.title AS task_title,
            agents.display_name AS agent_name
        FROM failure_log
        LEFT JOIN tasks ON tasks.task_id = failure_log.task_id
        LEFT JOIN agents ON agents.agent_id = failure_log.agent_id
        ORDER BY failure_log.created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    recent = [dict(row) for row in rows]
    repeated_tasks = [
        dict(row)
        for row in connection.execute(
            """
            SELECT
                failure_log.task_id,
                tasks.title AS task_title,
                COUNT(*) AS failure_count,
                MAX(failure_log.created_at) AS latest_failure_at
            FROM failure_log
            LEFT JOIN tasks ON tasks.task_id = failure_log.task_id
            WHERE failure_log.task_id IS NOT NULL
            GROUP BY failure_log.task_id, tasks.title
            HAVING COUNT(*) >= ?
            ORDER BY failure_count DESC, latest_failure_at DESC
            """,
            (REPEATED_FAILURE_THRESHOLD,),
        ).fetchall()
    ]

    return {
        "recent": recent,
        "repeated_tasks": repeated_tasks,
        "summary": {
            "total_failures": connection.execute(
                "SELECT COUNT(*) AS count FROM failure_log"
            ).fetchone()["count"],
            "tasks_with_failures": connection.execute(
                "SELECT COUNT(DISTINCT task_id) AS count FROM failure_log WHERE task_id IS NOT NULL"
            ).fetchone()["count"],
            "repeated_tasks": len(repeated_tasks),
        },
    }
