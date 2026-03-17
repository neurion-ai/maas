"""Artifact browser read model for control-room surfaces."""

import json
import mimetypes
import os
import tempfile
import zipfile
from difflib import unified_diff

RECOVERABLE_FAILURE_REVIEW_STATES = ("session_failed", "stale_session")
ARTIFACT_PREVIEW_MAX_BYTES = 8192
ARTIFACT_COMPARE_MAX_CHARS = 20000


def _load_metadata(value):
    try:
        return json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}


def _absolute_path(project_paths, stored_path):
    if not stored_path:
        return None
    if os.path.isabs(stored_path):
        return os.path.abspath(stored_path)
    return os.path.abspath(os.path.join(project_paths.root, stored_path))


def _path_within(root_path, candidate_path):
    if not root_path or not candidate_path:
        return False
    try:
        return os.path.commonpath([os.path.abspath(root_path), os.path.abspath(candidate_path)]) == os.path.abspath(root_path)
    except ValueError:
        return False


def _artifact_state(project_paths, absolute_path, metadata):
    if metadata.get("quarantined"):
        return "quarantined"
    if metadata.get("restored_from_quarantine"):
        return "restored"
    if _path_within(project_paths.quarantine_dir, absolute_path):
        return "quarantined"
    if _path_within(project_paths.artifacts_dir, absolute_path):
        return "active"
    return "external"


def _display_path(project_paths, absolute_path, stored_path):
    if absolute_path and _path_within(project_paths.root, absolute_path):
        return os.path.relpath(absolute_path, project_paths.root)
    return stored_path


def _size_bytes(absolute_path):
    if not absolute_path or not os.path.exists(absolute_path):
        return None
    try:
        return os.path.getsize(absolute_path)
    except OSError:
        return None


def _download_content_type(absolute_path):
    content_type, _ = mimetypes.guess_type(absolute_path or "")
    return content_type or "application/octet-stream"


def _can_download_artifact(project_paths, absolute_path):
    return bool(absolute_path and os.path.isfile(absolute_path) and _path_within(project_paths.root, absolute_path))


def _metadata_snapshot(metadata):
    return metadata if isinstance(metadata, dict) else {}


def _preview_kind(absolute_path):
    extension = os.path.splitext(absolute_path or "")[1].lower()
    if extension == ".json":
        return "json"
    return "text"


def _artifact_preview(absolute_path):
    if not absolute_path or not os.path.exists(absolute_path):
        return {"kind": "unavailable", "reason": "missing_file"}
    if not os.path.isfile(absolute_path):
        return {"kind": "unavailable", "reason": "not_a_file"}

    try:
        with open(absolute_path, "rb") as handle:
            preview_bytes = handle.read(ARTIFACT_PREVIEW_MAX_BYTES + 1)
    except OSError:
        return {"kind": "unavailable", "reason": "read_failed"}

    truncated = len(preview_bytes) > ARTIFACT_PREVIEW_MAX_BYTES
    payload = preview_bytes[:ARTIFACT_PREVIEW_MAX_BYTES]
    if b"\x00" in payload:
        return {"kind": "unavailable", "reason": "binary_file"}

    try:
        content = payload.decode("utf-8")
    except UnicodeDecodeError:
        return {"kind": "unavailable", "reason": "binary_file"}

    return {
        "kind": _preview_kind(absolute_path),
        "encoding": "utf-8",
        "truncated": truncated,
        "content": content,
    }


def _preview_is_comparable(preview):
    return preview.get("kind") in ("text", "json") and preview.get("content") is not None


def _truncate_text(value, limit):
    if len(value) <= limit:
        return value, False
    return value[:limit], True


def _state_summary(connection, project_paths):
    rows = connection.execute(
        """
        SELECT path, metadata_json
        FROM artifacts
        """
    ).fetchall()
    summary = {
        "total_artifacts": 0,
        "active_artifacts": 0,
        "quarantined_artifacts": 0,
        "restored_artifacts": 0,
        "external_artifacts": 0,
        "missing_files": 0,
    }
    for row in rows:
        metadata = _load_metadata(row["metadata_json"])
        absolute_path = _absolute_path(project_paths, row["path"])
        state = _artifact_state(project_paths, absolute_path, metadata)
        summary["total_artifacts"] += 1
        summary["{0}_artifacts".format(state)] += 1
        if not absolute_path or not os.path.exists(absolute_path):
            summary["missing_files"] += 1
    return summary


def _type_counts(connection):
    rows = connection.execute(
        """
        SELECT artifact_type, COUNT(*) AS count
        FROM artifacts
        GROUP BY artifact_type
        ORDER BY count DESC, artifact_type ASC
        """
    ).fetchall()
    return [{"artifact_type": row["artifact_type"], "count": row["count"]} for row in rows]


def _provider_counts(connection):
    rows = connection.execute(
        """
        SELECT COALESCE(sessions.provider_type, 'unknown') AS provider_type, COUNT(*) AS count
        FROM artifacts
        LEFT JOIN sessions ON sessions.session_id = artifacts.session_id
        GROUP BY COALESCE(sessions.provider_type, 'unknown')
        ORDER BY count DESC, provider_type ASC
        """
    ).fetchall()
    return [{"provider_type": row["provider_type"], "count": row["count"]} for row in rows]


def _relative_workspace_path(project_paths, absolute_path):
    return os.path.relpath(absolute_path, project_paths.root).replace("\\", "/")


def _artifact_state_sql(project_paths):
    artifacts_prefix = os.path.abspath(project_paths.artifacts_dir).replace("\\", "/") + "/%"
    quarantine_prefix = os.path.abspath(project_paths.quarantine_dir).replace("\\", "/") + "/%"
    relative_artifacts_prefix = _relative_workspace_path(project_paths, project_paths.artifacts_dir) + "/%"
    relative_quarantine_prefix = _relative_workspace_path(project_paths, project_paths.quarantine_dir) + "/%"
    return (
        """
        CASE
            WHEN json_extract(artifacts.metadata_json, '$.quarantined') = 1 THEN 'quarantined'
            WHEN json_extract(artifacts.metadata_json, '$.restored_from_quarantine') = 1 THEN 'restored'
            WHEN REPLACE(artifacts.path, '\\', '/') LIKE :quarantine_prefix THEN 'quarantined'
            WHEN REPLACE(artifacts.path, '\\', '/') LIKE :relative_quarantine_prefix THEN 'quarantined'
            WHEN REPLACE(artifacts.path, '\\', '/') LIKE :artifacts_prefix THEN 'active'
            WHEN REPLACE(artifacts.path, '\\', '/') LIKE :relative_artifacts_prefix THEN 'active'
            ELSE 'external'
        END
        """,
        {
            "artifacts_prefix": artifacts_prefix,
            "quarantine_prefix": quarantine_prefix,
            "relative_artifacts_prefix": relative_artifacts_prefix,
            "relative_quarantine_prefix": relative_quarantine_prefix,
        },
    )


def _artifact_where_clause(project_paths, filters):
    filters = filters or {}
    state_sql, params = _artifact_state_sql(project_paths)
    where = []

    if filters.get("provider_type") and filters["provider_type"] != "all":
        where.append("COALESCE(sessions.provider_type, 'unknown') = :provider_type")
        params["provider_type"] = filters["provider_type"]

    if filters.get("artifact_type") and filters["artifact_type"] != "all":
        where.append("artifacts.artifact_type = :artifact_type")
        params["artifact_type"] = filters["artifact_type"]

    if filters.get("task_id"):
        where.append("artifacts.task_id = :task_id")
        params["task_id"] = filters["task_id"]

    if filters.get("session_id"):
        where.append("artifacts.session_id = :session_id")
        params["session_id"] = filters["session_id"]

    if filters.get("state") and filters["state"] != "all":
        where.append("{0} = :state".format(state_sql))
        params["state"] = filters["state"]

    if filters.get("search"):
        params["search"] = "%{0}%".format(filters["search"].strip().lower())
        where.append(
            """
            (
                LOWER(artifacts.artifact_id) LIKE :search
                OR LOWER(COALESCE(artifacts.task_id, '')) LIKE :search
                OR LOWER(COALESCE(tasks.title, '')) LIKE :search
                OR LOWER(COALESCE(agents.display_name, '')) LIKE :search
                OR LOWER(COALESCE(sessions.provider_type, '')) LIKE :search
                OR LOWER(artifacts.artifact_type) LIKE :search
                OR LOWER(REPLACE(artifacts.path, '\\', '/')) LIKE :search
                OR LOWER(COALESCE(json_extract(artifacts.metadata_json, '$.quarantined_from_path'), '')) LIKE :search
                OR LOWER(COALESCE(json_extract(artifacts.metadata_json, '$.quarantine_reason'), '')) LIKE :search
            )
            """
        )

    return where, params


def _enrich_artifact_row(project_paths, row):
    metadata = _load_metadata(row["metadata_json"])
    absolute_path = _absolute_path(project_paths, row["path"])
    artifact_state = _artifact_state(project_paths, absolute_path, metadata)
    return {
        "artifact_id": row["artifact_id"],
        "project_id": row["project_id"],
        "task_id": row["task_id"],
        "task_title": row["task_title"],
        "task_status": row["task_status"],
        "task_review_state": row["task_review_state"],
        "session_id": row["session_id"],
        "session_status": row["session_status"],
        "provider_type": row["provider_type"],
        "agent_id": row["agent_id"],
        "agent_name": row["agent_name"],
        "artifact_type": row["artifact_type"],
        "path": row["path"],
        "display_path": _display_path(project_paths, absolute_path, row["path"]),
        "file_name": os.path.basename(absolute_path or row["path"]),
        "artifact_state": artifact_state,
        "exists": bool(absolute_path and os.path.exists(absolute_path)),
        "size_bytes": _size_bytes(absolute_path),
        "quarantine_reason": metadata.get("quarantine_reason"),
        "quarantined_from_path": metadata.get("quarantined_from_path"),
        "restored_from_quarantine": bool(metadata.get("restored_from_quarantine")),
        "created_at": row["created_at"],
    }


def _matches_search(item, query):
    if not query:
        return True
    normalized_query = query.strip().lower()
    if not normalized_query:
        return True
    haystack = " ".join(
        str(value)
        for value in (
            item["artifact_id"],
            item["task_id"],
            item["task_title"],
            item["agent_name"],
            item["provider_type"],
            item["artifact_type"],
            item["file_name"],
            item["display_path"],
            item["quarantined_from_path"],
            item["quarantine_reason"],
        )
        if value
    ).lower()
    return normalized_query in haystack


def _matches_filters(item, filters):
    filters = filters or {}
    if filters.get("state") and filters["state"] != "all" and item["artifact_state"] != filters["state"]:
        return False
    if filters.get("provider_type") and filters["provider_type"] != "all":
        if (item.get("provider_type") or "unknown") != filters["provider_type"]:
            return False
    if filters.get("artifact_type") and filters["artifact_type"] != "all":
        if item["artifact_type"] != filters["artifact_type"]:
            return False
    if filters.get("task_id") and item.get("task_id") != filters["task_id"]:
        return False
    if filters.get("missing_only") and item["exists"]:
        return False
    return _matches_search(item, filters.get("search"))


def _quarantine_queue_entries_by_session(connection, session_ids):
    if not session_ids:
        return {}

    placeholders = ", ".join(["?"] * len(session_ids))
    rows = connection.execute(
        """
        SELECT session_id, queue_id, status, reason, resolution_note, created_at, updated_at, resolved_at
        FROM quarantine_queue
        WHERE session_id IN ({0})
        ORDER BY
            CASE status
                WHEN 'open' THEN 0
                WHEN 'dismissed' THEN 1
                ELSE 2
            END,
            created_at DESC
        """.format(placeholders),
        tuple(session_ids),
    ).fetchall()

    queue_entries = {}
    for row in rows:
        queue_entries.setdefault(row["session_id"], dict(row))
    return queue_entries


def _artifact_base_from():
    return """
        FROM artifacts
        LEFT JOIN tasks ON tasks.task_id = artifacts.task_id
        LEFT JOIN sessions ON sessions.session_id = artifacts.session_id
        LEFT JOIN agents ON agents.agent_id = sessions.agent_id
    """


def _artifact_row_query(where_sql=""):
    return """
        SELECT
            artifacts.artifact_id,
            artifacts.project_id,
            artifacts.task_id,
            artifacts.session_id,
            artifacts.artifact_type,
            artifacts.path,
            artifacts.metadata_json,
            artifacts.created_at,
            tasks.title AS task_title,
            tasks.status AS task_status,
            tasks.review_state AS task_review_state,
            sessions.provider_type,
            sessions.status AS session_status,
            sessions.agent_id,
            agents.display_name AS agent_name
        {base_from}
        {where_sql}
    """.format(base_from=_artifact_base_from(), where_sql=where_sql)


def _artifact_has_recoverable_task(item):
    return item.get("task_status") == "blocked" and item.get("task_review_state") in RECOVERABLE_FAILURE_REVIEW_STATES


def _infer_artifact_operator_action(item):
    queue_id = item.get("quarantine_queue_id")
    queue_status = item.get("quarantine_queue_status")

    if queue_id and queue_status == "open" and item.get("artifact_state") == "quarantined" and _artifact_has_recoverable_task(item):
        return {
            "action": "restore_and_requeue_quarantine_entry",
            "label": "Restore + requeue",
            "resource_type": "quarantine",
            "resource_id": queue_id,
            "related_task_id": item.get("task_id"),
        }

    if queue_id and queue_status == "dismissed" and item.get("artifact_state") == "quarantined":
        return {
            "action": "reopen_quarantine_entry",
            "label": "Reopen",
            "resource_type": "quarantine",
            "resource_id": queue_id,
            "related_task_id": item.get("task_id"),
        }

    if queue_id and queue_status == "open" and item.get("artifact_state") == "quarantined":
        return {
            "action": "restore_quarantine_entry",
            "label": "Restore artifacts",
            "resource_type": "quarantine",
            "resource_id": queue_id,
            "related_task_id": item.get("task_id"),
        }

    return None


def _infer_artifact_secondary_operator_action(item):
    queue_id = item.get("quarantine_queue_id")
    queue_status = item.get("quarantine_queue_status")

    if queue_id and queue_status == "open" and item.get("artifact_state") == "quarantined":
        return {
            "action": "dismiss_quarantine_entry",
            "label": "Dismiss",
            "resource_type": "quarantine",
            "resource_id": queue_id,
            "related_task_id": item.get("task_id"),
        }

    return None


def _attach_quarantine_actions(connection, items):
    session_ids = [item["session_id"] for item in items if item.get("session_id")]
    queue_entries_by_session = _quarantine_queue_entries_by_session(connection, session_ids)

    enriched_items = []
    for item in items:
        enriched_item = dict(item)
        queue_entry = queue_entries_by_session.get(item.get("session_id"))
        if queue_entry is not None:
            enriched_item["quarantine_queue_id"] = queue_entry["queue_id"]
            enriched_item["quarantine_queue_status"] = queue_entry["status"]
        operator_action = _infer_artifact_operator_action(enriched_item)
        if operator_action is not None:
            enriched_item["operator_action"] = operator_action
        secondary_operator_action = _infer_artifact_secondary_operator_action(enriched_item)
        if secondary_operator_action is not None:
            enriched_item["secondary_operator_action"] = secondary_operator_action
        enriched_items.append(enriched_item)
    return enriched_items


def _artifact_related_summary(item):
    return {
        "artifact_id": item["artifact_id"],
        "artifact_type": item["artifact_type"],
        "file_name": item["file_name"],
        "display_path": item["display_path"],
        "artifact_state": item["artifact_state"],
        "provider_type": item.get("provider_type"),
        "session_id": item.get("session_id"),
        "created_at": item["created_at"],
    }


def _related_artifact_items(connection, project_paths, focus_item, limit=6):
    task_id = focus_item.get("task_id")
    if not task_id:
        return []

    rows = connection.execute(
        _artifact_row_query("WHERE artifacts.task_id = ? AND artifacts.artifact_id != ?")
        + "\nORDER BY artifacts.created_at DESC, artifacts.artifact_id DESC LIMIT ?",
        (task_id, focus_item["artifact_id"], limit),
    ).fetchall()
    items = _attach_quarantine_actions(connection, [_enrich_artifact_row(project_paths, row) for row in rows])
    return [_artifact_related_summary(item) for item in items]


def _session_artifact_items(connection, project_paths, focus_item, limit=8):
    session_id = focus_item.get("session_id")
    if not session_id:
        return []

    rows = connection.execute(
        _artifact_row_query("WHERE artifacts.session_id = ? AND artifacts.artifact_id != ?")
        + "\nORDER BY artifacts.created_at DESC, artifacts.artifact_id DESC LIMIT ?",
        (session_id, focus_item["artifact_id"], limit),
    ).fetchall()
    items = _attach_quarantine_actions(connection, [_enrich_artifact_row(project_paths, row) for row in rows])
    return [_artifact_related_summary(item) for item in items]


def _artifact_lineage_summary(connection, focus_item):
    task_id = focus_item.get("task_id")
    session_id = focus_item.get("session_id")
    task_artifact_count = 0
    session_artifact_count = 0

    if task_id:
        task_artifact_count = connection.execute(
            "SELECT COUNT(*) AS count FROM artifacts WHERE task_id = ?",
            (task_id,),
        ).fetchone()["count"]

    if session_id:
        session_artifact_count = connection.execute(
            "SELECT COUNT(*) AS count FROM artifacts WHERE session_id = ?",
            (session_id,),
        ).fetchone()["count"]

    return {
        "task_artifact_count": task_artifact_count,
        "session_artifact_count": session_artifact_count,
    }


def _dependency_artifact_links(connection, project_paths, focus_item, direction, limit=3):
    task_id = focus_item.get("task_id")
    if not task_id:
        return []

    if direction == "upstream":
        rows = connection.execute(
            """
            SELECT td.source_task_id AS linked_task_id, tasks.title AS linked_task_title, td.dependency_type
            FROM task_dependencies td
            JOIN tasks ON tasks.task_id = td.source_task_id
            WHERE td.target_task_id = ?
            ORDER BY
                CASE td.dependency_type
                    WHEN 'blocks' THEN 0
                    WHEN 'informs' THEN 1
                    ELSE 2
                END,
                tasks.created_at ASC
            """,
            (task_id,),
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT td.target_task_id AS linked_task_id, tasks.title AS linked_task_title, td.dependency_type
            FROM task_dependencies td
            JOIN tasks ON tasks.task_id = td.target_task_id
            WHERE td.source_task_id = ?
            ORDER BY
                CASE td.dependency_type
                    WHEN 'blocks' THEN 0
                    WHEN 'informs' THEN 1
                    ELSE 2
                END,
                tasks.created_at ASC
            """,
            (task_id,),
        ).fetchall()

    links = []
    for row in rows:
        artifact_count = connection.execute(
            "SELECT COUNT(*) AS count FROM artifacts WHERE task_id = ?",
            (row["linked_task_id"],),
        ).fetchone()["count"]
        artifact_rows = connection.execute(
            _artifact_row_query("WHERE artifacts.task_id = ?")
            + "\nORDER BY artifacts.created_at DESC, artifacts.artifact_id DESC LIMIT ?",
            (row["linked_task_id"], limit),
        ).fetchall()
        items = _attach_quarantine_actions(connection, [_enrich_artifact_row(project_paths, artifact_row) for artifact_row in artifact_rows])
        links.append(
            {
                "task_id": row["linked_task_id"],
                "task_title": row["linked_task_title"],
                "dependency_type": row["dependency_type"],
                "artifact_count": artifact_count,
                "recent_artifacts": [_artifact_related_summary(item) for item in items],
            }
        )
    return links


def _artifact_export_rows(connection, project_paths, task_id=None, session_id=None):
    clauses = []
    params = []
    if task_id:
        clauses.append("artifacts.task_id = ?")
        params.append(task_id)
    if session_id:
        clauses.append("artifacts.session_id = ?")
        params.append(session_id)
    if len(clauses) != 1:
        raise ValueError("exactly one export scope is required")

    rows = connection.execute(
        _artifact_row_query("WHERE " + clauses[0]) + "\nORDER BY artifacts.created_at ASC, artifacts.artifact_id ASC",
        tuple(params),
    ).fetchall()
    items = _attach_quarantine_actions(connection, [_enrich_artifact_row(project_paths, row) for row in rows])
    return rows, items


def build_artifact_export_bundle(connection, project_paths, task_id=None, session_id=None):
    rows, items = _artifact_export_rows(connection, project_paths, task_id=task_id, session_id=session_id)
    if not rows:
        return None

    scope_type = "task" if task_id else "session"
    scope_id = task_id or session_id
    manifest = {
        "scope_type": scope_type,
        "scope_id": scope_id,
        "artifact_count": len(items),
        "artifacts": [],
    }

    temp_file = tempfile.NamedTemporaryFile(prefix="maas-artifact-export-", suffix=".zip", delete=False)
    temp_file_path = temp_file.name
    temp_file.close()

    with zipfile.ZipFile(temp_file_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for row, item in zip(rows, items):
            absolute_path = _absolute_path(project_paths, row["path"])
            export_entry = {
                "artifact_id": item["artifact_id"],
                "file_name": item["file_name"],
                "display_path": item["display_path"],
                "artifact_type": item["artifact_type"],
                "artifact_state": item["artifact_state"],
                "task_id": item.get("task_id"),
                "session_id": item.get("session_id"),
                "included": False,
                "reason": None,
            }
            if _can_download_artifact(project_paths, absolute_path):
                archive.write(absolute_path, arcname="artifacts/{0}-{1}".format(item["artifact_id"], item["file_name"]))
                export_entry["included"] = True
            elif not absolute_path or not os.path.exists(absolute_path):
                export_entry["reason"] = "missing_file"
            elif not os.path.isfile(absolute_path):
                export_entry["reason"] = "not_a_file"
            elif not _path_within(project_paths.root, absolute_path):
                export_entry["reason"] = "external_file"
            else:
                export_entry["reason"] = "export_unavailable"
            manifest["artifacts"].append(export_entry)

        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))

    return {
        "absolute_path": temp_file_path,
        "file_name": "{0}-{1}-artifacts.zip".format(scope_type, scope_id),
        "content_type": "application/zip",
    }


def fetch_artifacts(connection, project_paths, limit=100, offset=0, filters=None):
    where, params = _artifact_where_clause(project_paths, filters)
    base_from = _artifact_base_from()
    where_sql = ""
    if where:
        where_sql = "WHERE " + " AND ".join(where)

    row_query = _artifact_row_query(where_sql) + "\nORDER BY artifacts.created_at DESC, artifacts.artifact_id DESC"

    missing_only = bool((filters or {}).get("missing_only"))
    if missing_only:
        rows = connection.execute(row_query, params).fetchall()
        enriched_items = [_enrich_artifact_row(project_paths, row) for row in rows]
        filtered_items = [item for item in enriched_items if _matches_filters(item, {"missing_only": True})]
        paged_items = filtered_items[offset : offset + limit]
        filtered_count = len(filtered_items)
    else:
        count_query = "SELECT COUNT(*) AS count {0} {1}".format(base_from, where_sql)
        filtered_count = connection.execute(count_query, params).fetchone()["count"]
        paged_params = dict(params)
        paged_params["limit"] = limit
        paged_params["offset"] = offset
        rows = connection.execute(
            row_query + "\nLIMIT :limit OFFSET :offset",
            paged_params,
        ).fetchall()
        paged_items = [_enrich_artifact_row(project_paths, row) for row in rows]

    paged_items = _attach_quarantine_actions(connection, paged_items)

    return {
        "summary": _state_summary(connection, project_paths),
        "artifact_types": _type_counts(connection),
        "provider_types": _provider_counts(connection),
        "items": paged_items,
        "filtered_count": filtered_count,
        "offset": offset,
        "limit": limit,
        "selected_filters": {
            "search": (filters or {}).get("search") or "",
            "state": (filters or {}).get("state") or "all",
            "provider_type": (filters or {}).get("provider_type") or "all",
            "artifact_type": (filters or {}).get("artifact_type") or "all",
            "task_id": (filters or {}).get("task_id") or "",
            "session_id": (filters or {}).get("session_id") or "",
            "missing_only": bool((filters or {}).get("missing_only")),
        },
    }


def fetch_artifact_detail(connection, project_paths, artifact_id):
    row = connection.execute(
        _artifact_row_query("WHERE artifacts.artifact_id = ?"),
        (artifact_id,),
    ).fetchone()
    if row is None:
        return None

    enriched_item = _attach_quarantine_actions(connection, [_enrich_artifact_row(project_paths, row)])[0]
    metadata = _load_metadata(row["metadata_json"])
    absolute_path = _absolute_path(project_paths, row["path"])
    can_download = _can_download_artifact(project_paths, absolute_path)

    quarantine_entry = None
    if enriched_item.get("session_id"):
        queue_entry = _quarantine_queue_entries_by_session(connection, [enriched_item["session_id"]]).get(enriched_item["session_id"])
        if queue_entry is not None:
            quarantine_entry = {
                "queue_id": queue_entry["queue_id"],
                "status": queue_entry["status"],
                "reason": queue_entry.get("reason") or metadata.get("quarantine_reason"),
                "resolution_note": queue_entry.get("resolution_note"),
                "created_at": queue_entry.get("created_at"),
                "updated_at": queue_entry.get("updated_at"),
                "resolved_at": queue_entry.get("resolved_at"),
            }

    return {
        **enriched_item,
        "metadata": _metadata_snapshot(metadata),
        "absolute_path": absolute_path,
        "download_url": "/api/artifacts/{0}/download".format(artifact_id) if can_download else None,
        "task_export_url": "/api/artifacts/export?task_id={0}".format(enriched_item["task_id"]) if enriched_item.get("task_id") else None,
        "session_export_url": "/api/artifacts/export?session_id={0}".format(enriched_item["session_id"]) if enriched_item.get("session_id") else None,
        "download_content_type": _download_content_type(absolute_path) if can_download else None,
        "preview": _artifact_preview(absolute_path),
        "quarantine_entry": quarantine_entry,
        "lineage_summary": _artifact_lineage_summary(connection, enriched_item),
        "session_artifacts": _session_artifact_items(connection, project_paths, enriched_item),
        "upstream_task_artifacts": _dependency_artifact_links(connection, project_paths, enriched_item, "upstream"),
        "downstream_task_artifacts": _dependency_artifact_links(connection, project_paths, enriched_item, "downstream"),
        "related_artifacts": _related_artifact_items(connection, project_paths, enriched_item),
    }


def resolve_artifact_download(connection, project_paths, artifact_id):
    row = connection.execute(
        "SELECT path FROM artifacts WHERE artifact_id = ?",
        (artifact_id,),
    ).fetchone()
    if row is None:
        return None

    absolute_path = _absolute_path(project_paths, row["path"])
    if not _can_download_artifact(project_paths, absolute_path):
        return None

    return {
        "absolute_path": absolute_path,
        "file_name": os.path.basename(absolute_path),
        "content_type": _download_content_type(absolute_path),
    }


def fetch_artifact_comparison(connection, project_paths, left_artifact_id, right_artifact_id):
    left_detail = fetch_artifact_detail(connection, project_paths, left_artifact_id)
    right_detail = fetch_artifact_detail(connection, project_paths, right_artifact_id)
    if left_detail is None or right_detail is None:
        return None

    left_preview = left_detail["preview"]
    right_preview = right_detail["preview"]
    if not _preview_is_comparable(left_preview) or not _preview_is_comparable(right_preview):
        return {
            "left": left_detail,
            "right": right_detail,
            "comparable": False,
            "reason": "preview_unavailable",
            "unified_diff": None,
            "truncated": False,
        }

    diff_lines = unified_diff(
        left_preview["content"].splitlines(),
        right_preview["content"].splitlines(),
        fromfile=left_detail["file_name"],
        tofile=right_detail["file_name"],
        lineterm="",
    )
    diff_text, diff_truncated = _truncate_text("\n".join(diff_lines), ARTIFACT_COMPARE_MAX_CHARS)
    return {
        "left": left_detail,
        "right": right_detail,
        "comparable": True,
        "reason": None,
        "unified_diff": diff_text,
        "truncated": bool(left_preview.get("truncated") or right_preview.get("truncated") or diff_truncated),
    }
