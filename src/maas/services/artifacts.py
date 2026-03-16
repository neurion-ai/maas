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


def fetch_artifacts(connection, project_paths, limit=100):
    rows = connection.execute(
        """
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
        FROM artifacts
        LEFT JOIN tasks ON tasks.task_id = artifacts.task_id
        LEFT JOIN sessions ON sessions.session_id = artifacts.session_id
        LEFT JOIN agents ON agents.agent_id = sessions.agent_id
        ORDER BY artifacts.created_at DESC, artifacts.artifact_id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    items = []
    for row in rows:
        metadata = _load_metadata(row["metadata_json"])
        absolute_path = _absolute_path(project_paths, row["path"])
        artifact_state = _artifact_state(project_paths, absolute_path, metadata)
        items.append(
            {
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
        )

    return {
        "summary": _state_summary(connection, project_paths),
        "artifact_types": _type_counts(connection),
        "provider_types": _provider_counts(connection),
        "items": items,
    }
