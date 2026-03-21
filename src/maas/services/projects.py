"""Project lifecycle and scope helpers."""

import json
import os
import re
import shutil

from maas.config import (
    DEFAULT_PROJECT_TYPE,
    build_default_project_config,
    build_project_config_from_template,
    resolve_project_template,
)
from maas.ids import generate_id
from maas.services.bootstrap import (
    BROWNFIELD_REVIEW_TASK_TITLE,
    apply_onboarding_review_overrides,
    build_discovery_summary,
    build_understanding_markdown,
    default_onboarding_review_overrides,
    detect_bootstrap_mode,
    discover_brownfield_project,
    merge_onboarding_review_overrides,
    normalize_onboarding_review_overrides,
    seed_project,
)
from maas.services.security import ensure_board_action_allowed


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


def _slugify_name(value):
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return slug or "workspace"


def _provision_greenfield_source_root(project_paths, name):
    base_dir = os.path.join(project_paths.root, "workspaces")
    os.makedirs(base_dir, exist_ok=True)
    slug = _slugify_name(name)
    candidate = os.path.join(base_dir, slug)
    suffix = 2
    while os.path.exists(candidate):
        candidate = os.path.join(base_dir, "{0}-{1}".format(slug, suffix))
        suffix += 1
    os.makedirs(candidate, exist_ok=False)
    return os.path.abspath(candidate)


def _write_project_metadata(project_paths, project_id, config, mode, discovery):
    project_paths.ensure_project_workspace(project_id)
    with open(project_paths.project_understanding_path(project_id), "w", encoding="utf-8") as handle:
        handle.write(build_understanding_markdown(config, mode=mode, discovery=discovery))
    if discovery is not None:
        with open(project_paths.project_discovery_path(project_id), "w", encoding="utf-8") as handle:
            json.dump(discovery, handle, indent=2, sort_keys=True)


def _load_project_discovery(project_paths, project_id):
    discovery_path = project_paths.project_discovery_path(project_id)
    if not os.path.exists(discovery_path):
        return None
    try:
        with open(discovery_path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


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


def _save_project_config(connection, project_id, config):
    connection.execute(
        "UPDATE projects SET config_json = ?, updated_at = CURRENT_TIMESTAMP WHERE project_id = ?",
        (json.dumps(config), project_id),
    )


def _discovery_drift(previous_summary, current_summary, scanned_at):
    previous_summary = previous_summary or {}
    current_summary = current_summary or {}

    previous_workflows = set(previous_summary.get("workflow_labels") or [])
    current_workflows = set(current_summary.get("workflow_labels") or [])
    previous_repo_areas = set(previous_summary.get("repo_areas") or [])
    current_repo_areas = set(current_summary.get("repo_areas") or [])
    previous_packages = set(previous_summary.get("package_managers") or [])
    current_packages = set(current_summary.get("package_managers") or [])
    previous_map = set(item.get("name") for item in (previous_summary.get("codebase_map") or []) if item.get("name"))
    current_map = set(item.get("name") for item in (current_summary.get("codebase_map") or []) if item.get("name"))

    file_count_before = previous_summary.get("total_files") or 0
    file_count_after = current_summary.get("total_files") or 0
    file_count_delta = file_count_after - file_count_before
    primary_language_before = previous_summary.get("primary_language")
    primary_language_after = current_summary.get("primary_language")

    workflow_labels_added = sorted(current_workflows - previous_workflows)
    workflow_labels_removed = sorted(previous_workflows - current_workflows)
    repo_areas_added = sorted(current_repo_areas - previous_repo_areas)
    repo_areas_removed = sorted(previous_repo_areas - current_repo_areas)
    package_managers_added = sorted(current_packages - previous_packages)
    package_managers_removed = sorted(previous_packages - current_packages)
    codebase_map_added = sorted(current_map - previous_map)
    codebase_map_removed = sorted(previous_map - current_map)

    changes = []
    if primary_language_before != primary_language_after:
        changes.append(
            "Primary language changed from {0} to {1}".format(
                primary_language_before or "unknown",
                primary_language_after or "unknown",
            )
        )
    if file_count_delta:
        direction = "increased" if file_count_delta > 0 else "decreased"
        changes.append("Scanned file count {0} by {1}".format(direction, abs(file_count_delta)))
    if workflow_labels_added:
        changes.append("New workflow signals: {0}".format(", ".join(workflow_labels_added[:4])))
    if workflow_labels_removed:
        changes.append("Removed workflow signals: {0}".format(", ".join(workflow_labels_removed[:4])))
    if repo_areas_added:
        changes.append("New repo areas: {0}".format(", ".join(repo_areas_added[:4])))
    if repo_areas_removed:
        changes.append("Removed repo areas: {0}".format(", ".join(repo_areas_removed[:4])))
    if package_managers_added:
        changes.append("New package managers: {0}".format(", ".join(package_managers_added[:4])))
    if package_managers_removed:
        changes.append("Removed package managers: {0}".format(", ".join(package_managers_removed[:4])))
    if codebase_map_added:
        changes.append("New codebase map entries: {0}".format(", ".join(codebase_map_added[:4])))
    if codebase_map_removed:
        changes.append("Removed codebase map entries: {0}".format(", ".join(codebase_map_removed[:4])))

    detected = bool(changes)
    return {
        "detected": detected,
        "scanned_at": scanned_at,
        "summary": changes[0] if changes else "No brownfield drift detected.",
        "changes": changes,
        "file_count_delta": file_count_delta,
        "primary_language_before": primary_language_before,
        "primary_language_after": primary_language_after,
        "workflow_labels_added": workflow_labels_added,
        "workflow_labels_removed": workflow_labels_removed,
        "repo_areas_added": repo_areas_added,
        "repo_areas_removed": repo_areas_removed,
        "package_managers_added": package_managers_added,
        "package_managers_removed": package_managers_removed,
        "codebase_map_added": codebase_map_added,
        "codebase_map_removed": codebase_map_removed,
    }


def _ensure_brownfield_review_alert(connection, project_id, description):
    existing = connection.execute(
        """
        SELECT alert_id, status
        FROM alerts
        WHERE project_id = ?
          AND title = 'Brownfield onboarding review pending'
        ORDER BY
            CASE status
                WHEN 'open' THEN 0
                WHEN 'acknowledged' THEN 1
                ELSE 2
            END,
            rowid DESC
        LIMIT 1
        """,
        (project_id,),
    ).fetchone()
    if existing is not None:
        if existing["status"] == "resolved":
            connection.execute(
                """
                UPDATE alerts
                SET status = 'open',
                    description = ?
                WHERE alert_id = ?
                """,
                (description, existing["alert_id"]),
            )
        return existing["alert_id"]

    alert_id = generate_id("alert")
    connection.execute(
        """
        INSERT INTO alerts (
            alert_id, project_id, severity, title, description, status
        ) VALUES (?, ?, 'info', 'Brownfield onboarding review pending', ?, 'open')
        """,
        (alert_id, project_id, description),
    )
    return alert_id


def _reopen_brownfield_review_task(connection, project_id):
    review_task = connection.execute(
        """
        SELECT task_id, status, review_state
        FROM tasks
        WHERE project_id = ? AND title = ?
        ORDER BY created_at ASC
        LIMIT 1
        """,
        (project_id, BROWNFIELD_REVIEW_TASK_TITLE),
    ).fetchone()
    if review_task is None:
        return None
    if review_task["status"] == "review" and review_task["review_state"] == "awaiting_review":
        return dict(review_task)
    connection.execute(
        """
        UPDATE tasks
        SET status = 'review',
            review_state = 'awaiting_review',
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ?
        """,
        (review_task["task_id"],),
    )
    return {
        "task_id": review_task["task_id"],
        "status": "review",
        "review_state": "awaiting_review",
    }


def create_project(
    connection,
    project_paths,
    actor_id,
    name,
    description="",
    project_type=None,
    mode="auto",
    source_root=None,
    create_source_root=False,
    template_id=None,
):
    cleaned_name = (name or "").strip()
    if not cleaned_name:
        raise ValueError("project name is required")
    template = resolve_project_template(template_id) if template_id else None
    auto_created_source_root = False
    if template and create_source_root is False:
        create_source_root = bool(template.get("create_source_root"))
    if template and (not project_type):
        project_type = template.get("project_type") or project_type
    if template and mode == "auto":
        mode = template.get("mode") or mode
    resolved_mode = mode or "auto"
    if resolved_mode not in ("auto", "greenfield", "brownfield"):
        raise ValueError("unsupported project mode")
    if resolved_mode == "greenfield" and create_source_root and not source_root:
        resolved_source_root = _provision_greenfield_source_root(project_paths, cleaned_name)
        auto_created_source_root = True
    else:
        resolved_source_root = _normalize_source_root(project_paths, source_root)
    detected_mode = detect_bootstrap_mode(resolved_source_root) if resolved_mode == "auto" else resolved_mode
    discovery = discover_brownfield_project(resolved_source_root) if detected_mode == "brownfield" else None
    if template:
        config = build_project_config_from_template(
            template["id"],
            name=cleaned_name,
            description=(description or "").strip(),
            project_type=project_type or DEFAULT_PROJECT_TYPE,
            onboarding_mode=detected_mode,
            discovery_summary=build_discovery_summary(discovery),
            source_root=resolved_source_root,
        )
    else:
        config = build_default_project_config(
            name=cleaned_name,
            description=(description or "").strip(),
            project_type=project_type or DEFAULT_PROJECT_TYPE,
            onboarding_mode=detected_mode,
            discovery_summary=build_discovery_summary(discovery),
            source_root=resolved_source_root,
        )
    if detected_mode == "brownfield":
        onboarding = dict(config.get("onboarding") or {})
        onboarding["review_overrides"] = default_onboarding_review_overrides(onboarding.get("discovery_summary") or {})
        config["onboarding"] = onboarding
    config.setdefault("project", {})["generated_source_root"] = auto_created_source_root

    project_id = seed_project(
        connection,
        config,
        mode=detected_mode,
        discovery=discovery,
        source_root=resolved_source_root,
        seed_runtime_demo=False,
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
            "generated_source_root": auto_created_source_root,
            "name": cleaned_name,
            "template_id": template["id"] if template else None,
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
            "generated_source_root": auto_created_source_root,
            "template_id": template["id"] if template else None,
        },
    }


def clone_project(connection, project_paths, project_id, actor_id, name=None):
    project = resolve_project(connection, project_id, include_archived=True)
    if project is None:
        raise ValueError("project not found")

    source_config = _load_project_config(project["config_json"])
    source_project = dict(source_config.get("project") or {})
    cloned_name = (name or "{0} copy".format(project["name"])).strip()
    if not cloned_name:
        raise ValueError("project name is required")

    onboarding = dict(source_config.get("onboarding") or {})
    source_mode = onboarding.get("mode") or "greenfield"
    generated_source_root = bool(source_project.get("generated_source_root"))
    source_root = os.path.abspath(project["source_root"] or source_project.get("source_root") or project_paths.root)

    if source_mode == "greenfield" and generated_source_root:
        resolved_source_root = _provision_greenfield_source_root(project_paths, cloned_name)
        auto_created_source_root = True
    else:
        resolved_source_root = _normalize_source_root(project_paths, source_root)
        auto_created_source_root = False

    cloned_config = json.loads(json.dumps(source_config))
    cloned_project = dict(cloned_config.get("project") or {})
    cloned_project["name"] = cloned_name
    cloned_project["description"] = project["description"] or ""
    cloned_project["type"] = project["project_type"] or DEFAULT_PROJECT_TYPE
    cloned_project["source_root"] = resolved_source_root
    cloned_project["generated_source_root"] = auto_created_source_root
    cloned_project["cloned_from_project_id"] = project_id
    cloned_config["project"] = cloned_project

    discovery = _load_project_discovery(project_paths, project_id) if source_mode == "brownfield" else None
    if source_mode == "brownfield" and discovery is None:
        discovery = discover_brownfield_project(resolved_source_root)
    if source_mode == "brownfield":
        onboarding["mode"] = "brownfield"
        onboarding["discovery_summary"] = build_discovery_summary(discovery)
        onboarding["review_overrides"] = default_onboarding_review_overrides(onboarding.get("discovery_summary") or {})
        onboarding["review_status"] = "review_pending"
        onboarding["review_required"] = True
        onboarding["review_task_id"] = None
        onboarding["review_task_status"] = None
        onboarding["review_task_review_state"] = None
        onboarding["pending_gated_tasks"] = 0
        onboarding["last_scanned_at"] = None
        onboarding["last_scanned_by"] = None
        onboarding["drift_summary"] = None
        onboarding["reviewed_by"] = None
        onboarding["reviewed_at"] = None
        cloned_config["onboarding"] = onboarding
    else:
        cloned_config["onboarding"] = {
            "mode": "greenfield",
            "review_status": "not_applicable",
            "review_required": False,
            "review_overrides": {"ignored_paths": [], "accepted_workflow_labels": [], "accepted_runbook_labels": []},
            "discovery_summary": {},
            "review_task_id": None,
            "review_task_status": None,
            "review_task_review_state": None,
            "pending_gated_tasks": 0,
            "last_scanned_at": None,
            "last_scanned_by": None,
            "drift_summary": None,
            "reviewed_by": None,
            "reviewed_at": None,
        }

    cloned_project_id = seed_project(
        connection,
        cloned_config,
        mode=source_mode,
        discovery=discovery,
        source_root=resolved_source_root,
        seed_runtime_demo=False,
    )
    _write_project_metadata(project_paths, cloned_project_id, cloned_config, source_mode, discovery)
    _activity(
        connection,
        cloned_project_id,
        "project_cloned",
        "Project cloned from {0} into {1}.".format(project["name"], resolved_source_root),
    )
    _audit(
        connection,
        cloned_project_id,
        actor_id,
        "clone_project",
        "project",
        cloned_project_id,
        {
            "cloned_from_project_id": project_id,
            "mode": source_mode,
            "source_root": resolved_source_root,
            "generated_source_root": auto_created_source_root,
        },
    )
    connection.commit()

    created_row = connection.execute(
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
        (cloned_project_id,),
    ).fetchone()
    return {
        "project": _project_summary(created_row),
        "mode": source_mode,
        "metadata": {
            "understanding_path": project_paths.project_understanding_path(cloned_project_id),
            "discovery_path": project_paths.project_discovery_path(cloned_project_id) if discovery is not None else None,
            "source_root": resolved_source_root,
            "generated_source_root": auto_created_source_root,
            "cloned_from_project_id": project_id,
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


def delete_project(connection, project_paths, project_id, actor_id):
    project = resolve_project(connection, project_id, include_archived=True)
    if project is None:
        raise ValueError("project not found")
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
        raise ValueError("cannot delete a project with an active session")
    active_provider_job = connection.execute(
        """
        SELECT job_id
        FROM provider_job_queue
        WHERE project_id = ? AND status IN ('queued', 'running')
        LIMIT 1
        """,
        (project_id,),
    ).fetchone()
    if active_provider_job is not None:
        raise ValueError("cannot delete a project with queued or running provider jobs")

    config = _load_project_config(project["config_json"])
    generated_source_root = bool((config.get("project") or {}).get("generated_source_root"))
    source_root = os.path.abspath(project["source_root"] or (config.get("project") or {}).get("source_root") or "")

    connection.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))
    connection.commit()

    workspace_root = project_paths.project_workspace(project_id)
    if os.path.isdir(workspace_root):
        shutil.rmtree(workspace_root, ignore_errors=True)

    if generated_source_root and source_root and os.path.isdir(source_root):
        generated_root = os.path.abspath(os.path.join(project_paths.root, "workspaces"))
        if source_root == generated_root or not source_root.startswith(generated_root + os.sep):
            source_root = ""
        if source_root:
            shutil.rmtree(source_root, ignore_errors=True)

    return {"project_id": project_id, "state": "deleted"}


def rescan_brownfield_project(connection, project_paths, project_id, actor_id):
    project = resolve_project(connection, project_id, include_archived=False)
    if project is None:
        raise ValueError("project not found")

    config = _load_project_config(project["config_json"])
    onboarding = dict(config.get("onboarding") or {})
    if (onboarding.get("mode") or "greenfield") != "brownfield":
        raise ValueError("project is not in brownfield mode")

    source_root = os.path.abspath(project["source_root"] or config.get("project", {}).get("source_root") or "")
    if not source_root or not os.path.isdir(source_root):
        raise ValueError("project source root is not available")

    scanned_at = connection.execute("SELECT CURRENT_TIMESTAMP AS ts").fetchone()["ts"]
    previous_summary = onboarding.get("discovery_summary") or {}
    previous_review_overrides = onboarding.get("review_overrides") or default_onboarding_review_overrides(previous_summary)
    discovery = discover_brownfield_project(source_root)
    discovery_summary = build_discovery_summary(discovery)
    drift = _discovery_drift(previous_summary, discovery_summary, scanned_at)

    onboarding["discovery_summary"] = discovery_summary
    onboarding["review_overrides"] = merge_onboarding_review_overrides(
        discovery_summary,
        previous_summary=previous_summary,
        current_overrides=previous_review_overrides,
    )
    onboarding["last_scanned_at"] = scanned_at
    onboarding["last_scanned_by"] = actor_id
    onboarding["drift_summary"] = drift
    review_task = None
    if drift["detected"]:
        onboarding["review_status"] = "review_pending"
        if onboarding.get("repo_plan"):
            repo_plan = dict(onboarding.get("repo_plan") or {})
            repo_plan["stale"] = True
            onboarding["repo_plan"] = repo_plan
        review_task = _reopen_brownfield_review_task(connection, project_id)
        if review_task is not None:
            onboarding["review_task_id"] = review_task["task_id"]
        _ensure_brownfield_review_alert(
            connection,
            project_id,
            "Imported repository drift was detected during rescan. Review the updated understanding artifact before expanding automation.",
        )

    config["onboarding"] = onboarding
    _save_project_config(connection, project_id, config)
    _write_project_metadata(project_paths, project_id, config, "brownfield", discovery)
    _activity(
        connection,
        project_id,
        "brownfield_rescanned",
        (
            "Brownfield repository rescanned; drift detected and review reopened."
            if drift["detected"]
            else "Brownfield repository rescanned with no material drift detected."
        ),
    )
    _audit(
        connection,
        project_id,
        actor_id,
        "rescan_brownfield_project",
        "project",
        project_id,
        {"source_root": source_root, "drift": drift},
    )
    connection.commit()
    return {
        "project_id": project_id,
        "mode": "brownfield",
        "review_status": onboarding.get("review_status") or "review_pending",
        "review_task_id": review_task["task_id"] if review_task else onboarding.get("review_task_id"),
        "review_task_status": review_task["status"] if review_task else None,
        "drift": drift,
        "metadata": {
            "understanding_path": project_paths.project_understanding_path(project_id),
            "discovery_path": project_paths.project_discovery_path(project_id),
            "source_root": source_root,
        },
    }


def update_brownfield_onboarding_review(connection, project_paths, project_id, actor_id, review_updates):
    project = resolve_project(connection, project_id, include_archived=False)
    if project is None:
        raise ValueError("project not found")

    ensure_board_action_allowed(connection, actor_id, project_id, "configure_onboarding_review", "project", project_id)

    config = _load_project_config(project["config_json"])
    onboarding = dict(config.get("onboarding") or {})
    if (onboarding.get("mode") or "greenfield") != "brownfield":
        raise ValueError("project is not in brownfield mode")

    discovery_summary = onboarding.get("discovery_summary") or {}
    current_review_overrides = onboarding.get("review_overrides") or default_onboarding_review_overrides(discovery_summary)
    merged_request = {
        "ignored_paths": review_updates.get("ignored_paths", current_review_overrides.get("ignored_paths")),
        "accepted_workflow_labels": review_updates.get(
            "accepted_workflow_labels",
            current_review_overrides.get("accepted_workflow_labels"),
        ),
        "accepted_runbook_labels": review_updates.get(
            "accepted_runbook_labels",
            current_review_overrides.get("accepted_runbook_labels"),
        ),
    }
    normalized_review = normalize_onboarding_review_overrides(discovery_summary, merged_request)
    filtered_summary = apply_onboarding_review_overrides(discovery_summary, normalized_review)
    if normalized_review == current_review_overrides:
        return {
            "project_id": project_id,
            "review_status": onboarding.get("review_status") or "review_pending",
            "review_task_id": onboarding.get("review_task_id"),
            "review_overrides": normalized_review,
            "discovery_summary": filtered_summary,
        }

    onboarding["review_overrides"] = normalized_review
    onboarding["review_status"] = "review_pending"
    if onboarding.get("repo_plan"):
        repo_plan = dict(onboarding.get("repo_plan") or {})
        repo_plan["stale"] = True
        onboarding["repo_plan"] = repo_plan
    onboarding["reviewed_by"] = actor_id
    onboarding["reviewed_at"] = connection.execute("SELECT CURRENT_TIMESTAMP AS ts").fetchone()["ts"]
    config["onboarding"] = onboarding
    _save_project_config(connection, project_id, config)

    review_task = _reopen_brownfield_review_task(connection, project_id)
    if review_task is not None:
        onboarding["review_task_id"] = review_task["task_id"]
        config["onboarding"] = onboarding
        _save_project_config(connection, project_id, config)
    _ensure_brownfield_review_alert(
        connection,
        project_id,
        "Brownfield onboarding review inputs changed. Reconfirm the imported understanding before expanding automation.",
    )

    discovery = _load_project_discovery(project_paths, project_id)
    _write_project_metadata(project_paths, project_id, config, "brownfield", discovery)
    _activity(
        connection,
        project_id,
        "brownfield_review_updated",
        "Brownfield onboarding review inputs were updated before approval.",
    )
    _audit(
        connection,
        project_id,
        actor_id,
        "update_brownfield_onboarding_review",
        "project",
        project_id,
        {"review_overrides": normalized_review},
    )
    connection.commit()
    return {
        "project_id": project_id,
        "review_status": onboarding.get("review_status") or "review_pending",
        "review_task_id": review_task["task_id"] if review_task else onboarding.get("review_task_id"),
        "review_overrides": normalized_review,
        "discovery_summary": filtered_summary,
    }
