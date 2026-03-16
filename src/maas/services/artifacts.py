"""Artifact browser read model for control-room surfaces."""

import json
import os


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


def fetch_artifacts(connection, project_paths, limit=100, offset=0, filters=None):
    where, params = _artifact_where_clause(project_paths, filters)
    base_from = """
        FROM artifacts
        LEFT JOIN tasks ON tasks.task_id = artifacts.task_id
        LEFT JOIN sessions ON sessions.session_id = artifacts.session_id
        LEFT JOIN agents ON agents.agent_id = sessions.agent_id
    """
    where_sql = ""
    if where:
        where_sql = "WHERE " + " AND ".join(where)

    row_query = """
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
        ORDER BY artifacts.created_at DESC, artifacts.artifact_id DESC
    """.format(base_from=base_from, where_sql=where_sql)

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
            "missing_only": bool((filters or {}).get("missing_only")),
        },
    }
