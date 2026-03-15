"""Failure memory helpers for resilience and repeated-failure visibility."""

from datetime import datetime
import json
import os
import shutil

from maas.ids import generate_id


REPEATED_FAILURE_THRESHOLD = 2
REPEATED_FAILURE_TYPES = ("session_failed", "session_timed_out", "capability_denied")


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


def _utc_now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _insert_quarantine_queue_entry(
    connection,
    project_id,
    session_id,
    task_id,
    failure_id,
    reason,
    artifact_count,
    status="open",
    resolution_note="",
    resolved_at=None,
):
    queue_id = generate_id("quar")
    connection.execute(
        """
        INSERT INTO quarantine_queue (
            queue_id, project_id, session_id, task_id, failure_id, status, reason,
            artifact_count, resolution_note, resolved_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            queue_id,
            project_id,
            session_id,
            task_id,
            failure_id,
            status,
            reason,
            artifact_count,
            resolution_note,
            resolved_at,
        ),
    )
    return queue_id


def _upsert_quarantine_queue_entry(connection, project_id, session_id, task_id, failure_id, reason, artifact_count):
    existing = connection.execute(
        """
        SELECT queue_id, status
        FROM quarantine_queue
        WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()
    if existing is None:
        queue_id = _insert_quarantine_queue_entry(
            connection,
            project_id,
            session_id,
            task_id,
            failure_id,
            reason,
            artifact_count,
        )
        return {"queue_id": queue_id, "status": "open"}

    connection.execute(
        """
        UPDATE quarantine_queue
        SET task_id = COALESCE(?, task_id),
            failure_id = COALESCE(?, failure_id),
            reason = ?,
            artifact_count = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE session_id = ?
        """,
        (task_id, failure_id, reason, artifact_count, session_id),
    )
    return {"queue_id": existing["queue_id"], "status": existing["status"]}


def _set_quarantine_queue_status_for_session(connection, session_id, status, resolution_note):
    connection.execute(
        """
        UPDATE quarantine_queue
        SET status = ?,
            resolution_note = ?,
            updated_at = CURRENT_TIMESTAMP,
            resolved_at = CASE WHEN ? = 'open' THEN NULL ELSE CURRENT_TIMESTAMP END
        WHERE session_id = ?
        """,
        (status, resolution_note, status, session_id),
    )


def _artifact_quarantine_snapshot(connection, session_ids=None):
    params = []
    query = """
        SELECT project_id, task_id, session_id, metadata_json
        FROM artifacts
        WHERE session_id IS NOT NULL
    """
    if session_ids:
        placeholders = ", ".join(["?"] * len(session_ids))
        query += " AND session_id IN ({0})".format(placeholders)
        params.extend(session_ids)

    snapshots = {}
    for row in connection.execute(query, tuple(params)).fetchall():
        metadata = json.loads(row["metadata_json"] or "{}")
        if not metadata.get("quarantined") and not metadata.get("restored_from_quarantine"):
            continue
        snapshot = snapshots.setdefault(
            row["session_id"],
            {
                "project_id": row["project_id"],
                "task_id": row["task_id"],
                "reason": "",
                "quarantined_count": 0,
                "restored_count": 0,
            },
        )
        if metadata.get("quarantined"):
            snapshot["quarantined_count"] += 1
            if not snapshot["reason"]:
                snapshot["reason"] = metadata.get("quarantine_reason") or ""
        if metadata.get("restored_from_quarantine"):
            snapshot["restored_count"] += 1
    return snapshots


def _latest_failures_by_session(connection, session_ids):
    if not session_ids:
        return {}

    placeholders = ", ".join(["?"] * len(session_ids))
    rows = connection.execute(
        """
        SELECT failure_id, session_id, task_id, failure_type
        FROM failure_log
        WHERE session_id IN ({0})
        ORDER BY created_at DESC
        """.format(placeholders),
        tuple(session_ids),
    ).fetchall()

    latest = {}
    for row in rows:
        latest.setdefault(row["session_id"], dict(row))
    return latest


def backfill_quarantine_queue(connection, session_ids=None):
    snapshots = _artifact_quarantine_snapshot(connection, session_ids=session_ids)
    if not snapshots:
        return []

    if session_ids:
        placeholders = ", ".join(["?"] * len(session_ids))
        existing_rows = connection.execute(
            "SELECT session_id FROM quarantine_queue WHERE session_id IN ({0})".format(placeholders),
            tuple(session_ids),
        ).fetchall()
    else:
        existing_rows = connection.execute("SELECT session_id FROM quarantine_queue").fetchall()
    existing_session_ids = {row["session_id"] for row in existing_rows}
    latest_failures = _latest_failures_by_session(connection, list(snapshots.keys()))

    inserted_queue_ids = []
    for session_id, snapshot in snapshots.items():
        if session_id in existing_session_ids:
            continue
        status = "open" if snapshot["quarantined_count"] else "restored"
        artifact_count = snapshot["quarantined_count"] or snapshot["restored_count"]
        if artifact_count <= 0:
            continue
        failure = latest_failures.get(session_id)
        queue_id = _insert_quarantine_queue_entry(
            connection,
            snapshot["project_id"],
            session_id,
            (failure or {}).get("task_id") or snapshot["task_id"],
            (failure or {}).get("failure_id"),
            snapshot["reason"] or (failure or {}).get("failure_type") or "",
            artifact_count,
            status=status,
            resolution_note="" if status == "open" else "backfilled_restored_entry",
            resolved_at=None if status == "open" else _utc_now(),
        )
        inserted_queue_ids.append(queue_id)

    return inserted_queue_ids


def quarantine_session_artifacts(connection, project_paths, session_id, reason, project_id=None, task_id=None, failure_id=None):
    if project_paths is None:
        return []

    artifacts = connection.execute(
        """
        SELECT artifact_id, path, metadata_json
        FROM artifacts
        WHERE session_id = ?
        """,
        (session_id,),
    ).fetchall()
    if not artifacts:
        return []

    artifact_root = os.path.abspath(project_paths.artifacts_dir)
    quarantine_root = os.path.abspath(project_paths.quarantine_dir)
    quarantined = []
    quarantined_paths = {}
    for artifact in artifacts:
        stored_path = artifact["path"]
        source_path = stored_path if os.path.isabs(stored_path) else os.path.abspath(os.path.join(project_paths.root, stored_path))
        if os.path.commonpath([artifact_root, source_path]) != artifact_root:
            continue

        relative_path = os.path.relpath(source_path, artifact_root)
        destination_path = os.path.join(quarantine_root, session_id, relative_path)
        if source_path not in quarantined_paths:
            if not os.path.exists(source_path):
                continue
            os.makedirs(os.path.dirname(destination_path), exist_ok=True)
            shutil.move(source_path, destination_path)
            quarantined_paths[source_path] = destination_path
        else:
            destination_path = quarantined_paths[source_path]

        metadata = json.loads(artifact["metadata_json"] or "{}")
        metadata.update(
            {
                "quarantined": True,
                "quarantine_reason": reason,
                "quarantined_from_path": stored_path,
            }
        )
        connection.execute(
            """
            UPDATE artifacts
            SET path = ?, metadata_json = ?
            WHERE artifact_id = ?
            """,
            (destination_path, json.dumps(metadata), artifact["artifact_id"]),
        )
        quarantined.append(
            {
                "artifact_id": artifact["artifact_id"],
                "path": destination_path,
            }
        )

    if quarantined:
        if project_id is None or task_id is None:
            session_row = connection.execute(
                """
                SELECT project_id, task_id
                FROM sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if session_row is not None:
                project_id = project_id or session_row["project_id"]
                task_id = task_id or session_row["task_id"]
        if project_id is not None:
            _upsert_quarantine_queue_entry(
                connection,
                project_id,
                session_id,
                task_id,
                failure_id,
                reason,
                len(quarantined),
            )

    return quarantined


def restore_quarantined_session_artifacts(connection, project_paths, session_id):
    if project_paths is None:
        raise ValueError("Project paths are required to restore quarantined artifacts")
    backfill_quarantine_queue(connection, session_ids=[session_id])

    artifacts = connection.execute(
        """
        SELECT artifact_id, path, metadata_json
        FROM artifacts
        WHERE session_id = ?
        """,
        (session_id,),
    ).fetchall()
    if not artifacts:
        return []

    artifact_root = os.path.abspath(project_paths.artifacts_dir)
    quarantine_root = os.path.abspath(project_paths.quarantine_dir)
    planned_moves = {}
    planned_destinations = {}
    rows_to_restore = []
    for artifact in artifacts:
        metadata = json.loads(artifact["metadata_json"] or "{}")
        if not metadata.get("quarantined"):
            continue

        original_path = metadata.get("quarantined_from_path")
        if not original_path:
            continue

        source_path = artifact["path"]
        if not os.path.isabs(source_path):
            source_path = os.path.abspath(os.path.join(project_paths.root, source_path))
        if os.path.commonpath([quarantine_root, source_path]) != quarantine_root:
            continue

        destination_path = original_path
        if not os.path.isabs(destination_path):
            destination_path = os.path.abspath(os.path.join(project_paths.root, destination_path))
        if os.path.commonpath([artifact_root, destination_path]) != artifact_root:
            raise ValueError("Quarantined artifact cannot be restored outside the artifacts directory")

        existing_destination = planned_moves.get(source_path)
        if existing_destination is None:
            planned_moves[source_path] = destination_path
        elif existing_destination != destination_path:
            raise ValueError("Quarantined artifact rows disagree on the restore path")
        existing_source = planned_destinations.get(destination_path)
        if existing_source is None:
            planned_destinations[destination_path] = source_path
        elif existing_source != source_path:
            raise ValueError("Multiple quarantined artifacts cannot be restored to the same destination")

        rows_to_restore.append((artifact["artifact_id"], metadata, original_path))

    if not rows_to_restore:
        return []

    for source_path, destination_path in planned_moves.items():
        if not os.path.exists(source_path):
            raise ValueError("Quarantined artifact file is missing")
        if os.path.exists(destination_path):
            raise ValueError("Restore destination already exists")

    moved_paths = []
    try:
        for source_path, destination_path in planned_moves.items():
            os.makedirs(os.path.dirname(destination_path), exist_ok=True)
            shutil.move(source_path, destination_path)
            moved_paths.append((source_path, destination_path))
    except OSError:
        for rollback_source, rollback_destination in reversed(moved_paths):
            if os.path.exists(rollback_destination) and not os.path.exists(rollback_source):
                os.makedirs(os.path.dirname(rollback_source), exist_ok=True)
                shutil.move(rollback_destination, rollback_source)
        raise

    restored = []
    for artifact_id, metadata, original_path in rows_to_restore:
        metadata.pop("quarantined", None)
        metadata.pop("quarantine_reason", None)
        metadata.pop("quarantined_from_path", None)
        metadata["restored_from_quarantine"] = True
        connection.execute(
            """
            UPDATE artifacts
            SET path = ?, metadata_json = ?
            WHERE artifact_id = ?
            """,
            (original_path, json.dumps(metadata), artifact_id),
        )
        restored.append(
            {
                "artifact_id": artifact_id,
                "path": original_path,
            }
        )

    _set_quarantine_queue_status_for_session(connection, session_id, "restored", "artifacts_restored")
    return restored


def dismiss_quarantine_queue_entry(connection, queue_id):
    backfill_quarantine_queue(connection)
    entry = connection.execute(
        """
        SELECT queue_id, project_id, session_id, task_id, failure_id, status, artifact_count
        FROM quarantine_queue
        WHERE queue_id = ?
        """,
        (queue_id,),
    ).fetchone()
    if entry is None:
        raise ValueError("Quarantine entry not found")
    if entry["status"] != "open":
        raise ValueError("Only open quarantine entries can be dismissed")

    _set_quarantine_queue_status_for_session(connection, entry["session_id"], "dismissed", "quarantine_dismissed")
    return dict(entry)


def _repeated_failure_clause():
    placeholders = ", ".join(["?"] * len(REPEATED_FAILURE_TYPES))
    return "failure_type IN ({0})".format(placeholders), REPEATED_FAILURE_TYPES


def _escape_like(value):
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _repeated_failure_alert_like_pattern(task_id):
    return "Task {0} (%".format(_escape_like(task_id))


def _repeated_failure_alert_description(task_id, task_title, failure_count, summary):
    return "Task {0} ({1}) has failed {2} times. Latest failure: {3}".format(
        task_id,
        task_title,
        failure_count,
        summary,
    )


def _failure_count_for_task(connection, task_id):
    if task_id is None:
        return 0
    clause, params = _repeated_failure_clause()
    return connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM failure_log
        WHERE task_id = ?
          AND {0}
        """.format(clause),
        (task_id,) + params,
    ).fetchone()["count"]


def failure_attempt_count(connection, task_id):
    return _failure_count_for_task(connection, task_id)


def fetch_repeated_failure_tasks(connection, limit=None):
    clause, params = _repeated_failure_clause()
    query = """
        SELECT
            failure_log.task_id,
            tasks.title AS task_title,
            COUNT(*) AS failure_count,
            MAX(failure_log.created_at) AS latest_failure_at
        FROM failure_log
        LEFT JOIN tasks ON tasks.task_id = failure_log.task_id
        WHERE failure_log.task_id IS NOT NULL
          AND {0}
        GROUP BY failure_log.task_id, tasks.title
        HAVING COUNT(*) >= ?
        ORDER BY failure_count DESC, latest_failure_at DESC
    """.format(clause)
    query_params = params + (REPEATED_FAILURE_THRESHOLD,)
    if limit is not None:
        query += "\nLIMIT ?"
        query_params += (limit,)

    return [dict(row) for row in connection.execute(query, query_params).fetchall()]


def repeated_failure_task_count(connection):
    return len(fetch_repeated_failure_tasks(connection))


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
          ESCAPE '\\'
        LIMIT 1
        """,
        (project_id, _repeated_failure_alert_like_pattern(task_id)),
    ).fetchone()
    if existing is not None:
        return None

    alert_id = generate_id("alert")
    description = _repeated_failure_alert_description(task_id, task["title"], failure_count, summary)
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


def resolve_repeated_failure_alerts(connection, project_id, task_id, actor_id, resolution_reason):
    if task_id is None:
        return []

    rows = connection.execute(
        """
        SELECT alert_id
        FROM alerts
        WHERE project_id = ?
          AND status IN ('open', 'acknowledged')
          AND title = 'Repeated task failures'
          AND description LIKE ?
          ESCAPE '\\'
        """,
        (project_id, _repeated_failure_alert_like_pattern(task_id)),
    ).fetchall()

    resolved_alert_ids = []
    for row in rows:
        connection.execute(
            "UPDATE alerts SET status = 'resolved' WHERE alert_id = ?",
            (row["alert_id"],),
        )
        connection.execute(
            """
            INSERT INTO audit_trail (
                audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
            ) VALUES (?, ?, ?, 'resolve_repeated_failure_alert', 'alert', ?, ?)
            """,
            (
                generate_id("audit"),
                project_id,
                actor_id,
                row["alert_id"],
                json.dumps({"task_id": task_id, "reason": resolution_reason}),
            ),
        )
        resolved_alert_ids.append(row["alert_id"])

    if resolved_alert_ids:
        connection.execute(
            """
            INSERT INTO activity_log (
                activity_id, project_id, task_id, action, category, description, details_json, severity
            ) VALUES (?, ?, ?, 'repeated_failure_alert_resolved', 'resilience', ?, ?, 'info')
            """,
            (
                generate_id("act"),
                project_id,
                task_id,
                "Repeated failure alerts resolved for task {0}.".format(task_id),
                json.dumps({"alert_ids": resolved_alert_ids, "reason": resolution_reason}),
            ),
        )

    return resolved_alert_ids


def _quarantined_artifacts_by_session(connection, session_ids):
    if not session_ids:
        return {}

    placeholders = ", ".join(["?"] * len(session_ids))
    rows = connection.execute(
        """
        SELECT session_id, artifact_id, path, metadata_json
        FROM artifacts
        WHERE session_id IN ({0})
        """.format(placeholders),
        tuple(session_ids),
    ).fetchall()

    artifacts_by_session = {}
    for row in rows:
        metadata = json.loads(row["metadata_json"] or "{}")
        if not metadata.get("quarantined"):
            continue
        artifacts_by_session.setdefault(row["session_id"], []).append(
            {
                "artifact_id": row["artifact_id"],
                "path": row["path"],
                "quarantine_reason": metadata.get("quarantine_reason"),
                "quarantined_from_path": metadata.get("quarantined_from_path"),
            }
        )

    return artifacts_by_session


def enrich_failures_with_quarantine(connection, failures):
    session_ids = [failure["session_id"] for failure in failures if failure.get("session_id")]
    artifacts_by_session = _quarantined_artifacts_by_session(connection, session_ids)
    enriched = []
    for failure in failures:
        quarantined_artifacts = artifacts_by_session.get(failure.get("session_id"), [])
        enriched_failure = dict(failure)
        enriched_failure["quarantined_artifacts"] = quarantined_artifacts
        enriched_failure["quarantined_artifact_count"] = len(quarantined_artifacts)
        enriched.append(enriched_failure)
    return enriched


def fetch_quarantine_queue(connection, limit=20):
    inserted_queue_ids = backfill_quarantine_queue(connection)
    if inserted_queue_ids:
        connection.commit()
    rows = connection.execute(
        """
        SELECT
            quarantine_queue.queue_id,
            quarantine_queue.project_id,
            quarantine_queue.session_id,
            quarantine_queue.task_id,
            quarantine_queue.failure_id,
            quarantine_queue.status,
            quarantine_queue.reason,
            quarantine_queue.artifact_count,
            quarantine_queue.resolution_note,
            quarantine_queue.created_at,
            quarantine_queue.updated_at,
            quarantine_queue.resolved_at,
            failure_log.failure_type,
            failure_log.summary,
            tasks.title AS task_title,
            agents.display_name AS agent_name
        FROM quarantine_queue
        LEFT JOIN failure_log ON failure_log.failure_id = quarantine_queue.failure_id
        LEFT JOIN tasks ON tasks.task_id = quarantine_queue.task_id
        LEFT JOIN agents ON agents.agent_id = failure_log.agent_id
        ORDER BY
            CASE quarantine_queue.status
                WHEN 'open' THEN 0
                WHEN 'dismissed' THEN 1
                ELSE 2
            END,
            quarantine_queue.created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    entries = [dict(row) for row in rows]
    artifacts_by_session = _quarantined_artifacts_by_session(
        connection,
        [entry["session_id"] for entry in entries if entry.get("session_id")],
    )
    for entry in entries:
        entry["quarantined_artifacts"] = artifacts_by_session.get(entry["session_id"], [])

    return {
        "entries": entries,
        "summary": {
            "open": connection.execute(
                "SELECT COUNT(*) AS count FROM quarantine_queue WHERE status = 'open'"
            ).fetchone()["count"],
            "restored": connection.execute(
                "SELECT COUNT(*) AS count FROM quarantine_queue WHERE status = 'restored'"
            ).fetchone()["count"],
            "dismissed": connection.execute(
                "SELECT COUNT(*) AS count FROM quarantine_queue WHERE status = 'dismissed'"
            ).fetchone()["count"],
        },
    }


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
            tasks.retry_count,
            tasks.last_retry_at,
            tasks.last_retry_reason,
            tasks.next_retry_at,
            tasks.next_retry_reason,
            agents.display_name AS agent_name
        FROM failure_log
        LEFT JOIN tasks ON tasks.task_id = failure_log.task_id
        LEFT JOIN agents ON agents.agent_id = failure_log.agent_id
        ORDER BY failure_log.created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    recent = enrich_failures_with_quarantine(connection, [dict(row) for row in rows])
    repeated_tasks = fetch_repeated_failure_tasks(connection)

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
            "repeated_tasks": repeated_failure_task_count(connection),
        },
    }
