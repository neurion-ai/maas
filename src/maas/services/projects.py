"""Project lifecycle and scope helpers."""

import json
import os

from maas.config import DEFAULT_PROJECT_TYPE, build_default_project_config
from maas.ids import generate_id
from maas.services.bootstrap import (
    build_discovery_summary,
    build_understanding_markdown,
    detect_bootstrap_mode,
    discover_brownfield_project,
    seed_project,
)


def _load_project_config(raw_config):
    try:
        config = json.loads(raw_config or "{}")
    except ValueError:
        return {}
    return config if isinstance(config, dict) else {}


def _project_summary(row):
    config = _load_project_config(row["config_json"])
    onboarding = config.get("onboarding") or {}
    project_config = config.get("project") or {}
    return {
        "project_id": row["project_id"],
        "name": row["name"],
        "description": row["description"],
        "project_type": row["project_type"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "state": row["state"] or "active",
        "archived_at": row["archived_at"],
        "source_root": row["source_root"] or project_config.get("source_root") or "",
        "onboarding_mode": onboarding.get("mode") or "greenfield",
        "task_count": row["task_count"],
        "agent_count": row["agent_count"],
        "open_alert_count": row["open_alert_count"],
    }


def list_projects(connection, include_archived=True):
    if include_archived:
        state_clause = ""
        parameters = ()
    else:
        state_clause = "WHERE projects.state = 'active'"
        parameters = ()
    rows = connection.execute(
        """
        SELECT
            projects.project_id,
            projects.name,
            projects.description,
            projects.project_type,
            projects.config_json,
            projects.created_at,
            projects.updated_at,
            projects.state,
            projects.archived_at,
            projects.source_root,
            (
                SELECT COUNT(*)
                FROM tasks
                WHERE tasks.project_id = projects.project_id
            ) AS task_count,
            (
                SELECT COUNT(*)
                FROM agents
                WHERE agents.project_id = projects.project_id
            ) AS agent_count,
            (
                SELECT COUNT(*)
                FROM alerts
                WHERE alerts.project_id = projects.project_id
                  AND alerts.status = 'open'
            ) AS open_alert_count
        FROM projects
        {state_clause}
        ORDER BY
            CASE projects.state WHEN 'active' THEN 0 ELSE 1 END,
            projects.created_at ASC
        """.format(state_clause=state_clause),
        parameters,
    ).fetchall()
    return [_project_summary(row) for row in rows]


def resolve_project(connection, project_id=None, include_archived=False):
    if project_id:
        clause = "WHERE project_id = ?"
        parameters = [project_id]
        if not include_archived:
            clause += " AND state = 'active'"
    else:
        clause = "WHERE state = 'active'" if not include_archived else ""
        parameters = []
    row = connection.execute(
        """
        SELECT project_id, name, description, project_type, config_json, created_at, updated_at, state, archived_at, source_root
        FROM projects
        {clause}
        ORDER BY
            CASE state WHEN 'active' THEN 0 ELSE 1 END,
            created_at ASC
        LIMIT 1
        """.format(clause=clause),
        tuple(parameters),
    ).fetchone()
    return row


def resolve_project_id(connection, project_id=None, include_archived=False):
    row = resolve_project(connection, project_id, include_archived=include_archived)
    return row["project_id"] if row is not None else None


def _normalize_source_root(project_paths, source_root):
    candidate = source_root or project_paths.root
    normalized = os.path.abspath(candidate)
    if not os.path.isdir(normalized):
        raise ValueError("source root must be an existing directory")
    return normalized


def _write_project_metadata(project_paths, project_id, config, mode, discovery):
    project_paths.ensure_project_workspace(project_id)
    with open(project_paths.project_understanding_path(project_id), "w", encoding="utf-8") as handle:
        handle.write(build_understanding_markdown(config, mode=mode, discovery=discovery))
    if discovery is not None:
        with open(project_paths.project_discovery_path(project_id), "w", encoding="utf-8") as handle:
            json.dump(discovery, handle, indent=2, sort_keys=True)


def _audit(connection, project_id, actor_id, action_type, resource_type, resource_id, detail):
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            generate_id("audit"),
            project_id,
            actor_id,
            action_type,
            resource_type,
            resource_id,
            json.dumps(detail),
        ),
    )


def _activity(connection, project_id, action, description):
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, action, category, description, severity
        ) VALUES (?, ?, ?, 'projects', ?, 'info')
        """,
        (generate_id("act"), project_id, action, description),
    )


def create_project(
    connection,
    project_paths,
    actor_id,
    name,
    description="",
    project_type=None,
    mode="auto",
    source_root=None,
):
    cleaned_name = (name or "").strip()
    if not cleaned_name:
        raise ValueError("project name is required")
    resolved_mode = mode or "auto"
    if resolved_mode not in ("auto", "greenfield", "brownfield"):
        raise ValueError("unsupported project mode")

    resolved_source_root = _normalize_source_root(project_paths, source_root)
    detected_mode = detect_bootstrap_mode(resolved_source_root) if resolved_mode == "auto" else resolved_mode
    discovery = discover_brownfield_project(resolved_source_root) if detected_mode == "brownfield" else None
    config = build_default_project_config(
        name=cleaned_name,
        description=(description or "").strip(),
        project_type=project_type or DEFAULT_PROJECT_TYPE,
        onboarding_mode=detected_mode,
        discovery_summary=build_discovery_summary(discovery),
        source_root=resolved_source_root,
    )

    project_id = seed_project(
        connection,
        config,
        mode=detected_mode,
        discovery=discovery,
        source_root=resolved_source_root,
    )
    _write_project_metadata(project_paths, project_id, config, detected_mode, discovery)
    _activity(
        connection,
        project_id,
        "project_created",
        "Project created in {mode} mode from {source_root}.".format(
            mode=detected_mode,
            source_root=resolved_source_root,
        ),
    )
    _audit(
        connection,
        project_id,
        actor_id,
        "create_project",
        "project",
        project_id,
        {
            "mode": detected_mode,
            "source_root": resolved_source_root,
            "name": cleaned_name,
        },
    )
    connection.commit()

    project = resolve_project(connection, project_id, include_archived=True)
    return {
        "project": _project_summary(
            connection.execute(
                """
                SELECT
                    projects.project_id,
                    projects.name,
                    projects.description,
                    projects.project_type,
                    projects.config_json,
                    projects.created_at,
                    projects.updated_at,
                    projects.state,
                    projects.archived_at,
                    projects.source_root,
                    (
                        SELECT COUNT(*)
                        FROM tasks
                        WHERE tasks.project_id = projects.project_id
                    ) AS task_count,
                    (
                        SELECT COUNT(*)
                        FROM agents
                        WHERE agents.project_id = projects.project_id
                    ) AS agent_count,
                    (
                        SELECT COUNT(*)
                        FROM alerts
                        WHERE alerts.project_id = projects.project_id
                          AND alerts.status = 'open'
                    ) AS open_alert_count
                FROM projects
                WHERE projects.project_id = ?
                """,
                (project["project_id"],),
            ).fetchone()
        ),
        "mode": detected_mode,
        "metadata": {
            "understanding_path": project_paths.project_understanding_path(project_id),
            "discovery_path": project_paths.project_discovery_path(project_id) if discovery is not None else None,
            "source_root": resolved_source_root,
        },
    }


def archive_project(connection, project_id, actor_id):
    project = resolve_project(connection, project_id, include_archived=True)
    if project is None:
        raise ValueError("project not found")
    if project["state"] == "archived":
        raise ValueError("project is already archived")
    active_project_count = connection.execute(
        "SELECT COUNT(*) AS count FROM projects WHERE state = 'active'"
    ).fetchone()["count"]
    if active_project_count <= 1:
        raise ValueError("cannot archive the last active project")
    active_session = connection.execute(
        """
        SELECT session_id
        FROM sessions
        WHERE project_id = ? AND status = 'active'
        LIMIT 1
        """,
        (project_id,),
    ).fetchone()
    if active_session is not None:
        raise ValueError("cannot archive a project with an active session")

    connection.execute(
        """
        UPDATE projects
        SET state = 'archived',
            archived_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE project_id = ?
        """,
        (project_id,),
    )
    _activity(connection, project_id, "project_archived", "Project archived from the control room.")
    _audit(connection, project_id, actor_id, "archive_project", "project", project_id, {})
    connection.commit()
    return {"project_id": project_id, "state": "archived"}


def restore_project(connection, project_id, actor_id):
    project = resolve_project(connection, project_id, include_archived=True)
    if project is None:
        raise ValueError("project not found")
    if project["state"] != "archived":
        raise ValueError("project is not archived")
    connection.execute(
        """
        UPDATE projects
        SET state = 'active',
            archived_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE project_id = ?
        """,
        (project_id,),
    )
    _activity(connection, project_id, "project_restored", "Project restored to the active workspace.")
    _audit(connection, project_id, actor_id, "restore_project", "project", project_id, {})
    connection.commit()
    return {"project_id": project_id, "state": "active"}
