"""Dead-letter queue helpers for retry-exhausted work."""

import json

from maas.ids import generate_id


def upsert_dead_letter_entry(connection, project_id, task_id, reason, detail=None, failure_id=None):
    existing = connection.execute(
        """
        SELECT dlq_id
        FROM dead_letter_queue
        WHERE project_id = ?
          AND task_id = ?
          AND reason = ?
          AND status = 'open'
        LIMIT 1
        """,
        (project_id, task_id, reason),
    ).fetchone()
    detail_json = json.dumps(detail or {})
    if existing is not None:
        connection.execute(
            """
            UPDATE dead_letter_queue
            SET failure_id = COALESCE(?, failure_id),
                detail_json = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE dlq_id = ?
            """,
            (failure_id, detail_json, existing["dlq_id"]),
        )
        return existing["dlq_id"]

    dlq_id = generate_id("dlq")
    connection.execute(
        """
        INSERT INTO dead_letter_queue (
            dlq_id, project_id, task_id, failure_id, reason, detail_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (dlq_id, project_id, task_id, failure_id, reason, detail_json),
    )
    return dlq_id


def resolve_dead_letter_entries_for_task(connection, project_id, task_id, resolution_note):
    rows = connection.execute(
        """
        SELECT dlq_id
        FROM dead_letter_queue
        WHERE project_id = ?
          AND task_id = ?
          AND status = 'open'
        """,
        (project_id, task_id),
    ).fetchall()
    if not rows:
        return []
    connection.execute(
        """
        UPDATE dead_letter_queue
        SET status = 'resolved',
            resolution_note = ?,
            resolved_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE project_id = ?
          AND task_id = ?
          AND status = 'open'
        """,
        (resolution_note, project_id, task_id),
    )
    return [row["dlq_id"] for row in rows]


def fetch_dead_letter_queue(connection, project_id, limit=8):
    rows = connection.execute(
        """
        SELECT
            dead_letter_queue.dlq_id,
            dead_letter_queue.project_id,
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
        JOIN tasks ON tasks.task_id = dead_letter_queue.task_id
        LEFT JOIN goals ON goals.goal_id = tasks.goal_id
        LEFT JOIN agents ON agents.agent_id = tasks.assigned_agent_id
        WHERE dead_letter_queue.project_id = ?
          AND dead_letter_queue.status = 'open'
        ORDER BY dead_letter_queue.created_at DESC
        LIMIT ?
        """,
        (project_id, limit),
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        try:
            item["detail"] = json.loads(item.pop("detail_json") or "{}")
        except json.JSONDecodeError:
            item["detail"] = {}
        items.append(item)
    return items
