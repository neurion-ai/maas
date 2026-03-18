"""Repo-grounded brownfield plan synthesis and refresh."""

import json

from maas.ids import generate_id
from maas.services.bootstrap import apply_onboarding_review_overrides, default_onboarding_review_overrides
from maas.services.projects import resolve_project, resolve_project_id
from maas.services.scheduler import refresh_ready_tasks
from maas.services.security import ensure_board_action_allowed


REPO_PLAN_SYNTHESIS_ORIGIN = "repo_grounded_plan"
REPO_PLAN_STALE_REVIEW_STATE = "repo_plan_stale"
REPO_PLAN_MUTABLE_STATUSES = {"planned", "ready", "blocked"}


def _load_project_config(project_row):
    try:
        config = json.loads(project_row["config_json"] or "{}")
    except ValueError:
        return {}
    return config if isinstance(config, dict) else {}


def _normalize_paths(paths):
    normalized = []
    for value in paths or []:
        if not isinstance(value, str):
            continue
        candidate = value.strip().replace("\\", "/")
        if not candidate or candidate in normalized:
            continue
        normalized.append(candidate)
    return normalized


def _source_path_criterion(paths):
    scoped_paths = _normalize_paths(paths)
    if not scoped_paths:
        return None
    return {"type": "source_path_exists", "paths": scoped_paths}


def _build_repo_plan_specs(discovery_summary):
    summary = discovery_summary or {}
    specs = []

    verification_priority = 82
    for item in summary.get("runbook_commands") or []:
        label = item.get("label")
        if not label:
            continue
        acceptance_criteria = [{"type": "artifact_exists"}]
        path_criterion = _source_path_criterion([item.get("path")] if item.get("path") else [])
        if path_criterion is not None:
            acceptance_criteria.append(path_criterion)
        if item.get("command"):
            acceptance_criteria.append(
                {
                    "type": "test_passes",
                    "command": item["command"],
                    "timeout_seconds": 180,
                }
            )
        specs.append(
            {
                "synthesis_key": "runbook:{0}".format(label),
                "task_kind": "verification_recipe",
                "title": "Verify imported validation recipe: {0}".format(label),
                "description": (
                    "Convert the imported validation signal `{label}` into a concrete MAAS verification recipe"
                    "{path}{command}{detail}."
                ).format(
                    label=label,
                    path=(" from {0}".format(item["path"]) if item.get("path") else ""),
                    command=(" using `{0}`".format(item["command"]) if item.get("command") else ""),
                    detail=(" ({0})".format(item.get("detail")) if item.get("detail") else ""),
                ),
                "priority": verification_priority,
                "acceptance_criteria": acceptance_criteria,
                "paths": _normalize_paths([item.get("path")] if item.get("path") else []),
                "command": item.get("command"),
                "source_label": label,
                "area_path": item.get("path") or "",
            }
        )
        verification_priority -= 2

    area_priority = 76
    for item in summary.get("codebase_map") or []:
        area_name = item.get("name")
        if not area_name:
            continue
        sample_files = _normalize_paths(item.get("sample_files") or [])
        scoped_paths = sample_files or _normalize_paths([item.get("path") or area_name])
        acceptance_criteria = [{"type": "artifact_exists"}]
        path_criterion = _source_path_criterion(scoped_paths)
        if path_criterion is not None:
            acceptance_criteria.append(path_criterion)
        specs.append(
            {
                "synthesis_key": "area:{0}".format(item.get("path") or area_name),
                "task_kind": "repo_area_plan",
                "title": "Plan imported area: {0}".format(area_name),
                "description": (
                    "Turn the imported {kind} `{name}` into a repo-grounded work plan using {language}, "
                    "{file_count} files, and sample paths {samples}."
                ).format(
                    kind=(item.get("kind") or "repo area").replace("_", " "),
                    name=area_name,
                    language=item.get("primary_language") or "unknown",
                    file_count=item.get("file_count") or 0,
                    samples=", ".join(scoped_paths[:3]) if scoped_paths else (item.get("path") or area_name),
                ),
                "priority": area_priority,
                "acceptance_criteria": acceptance_criteria,
                "paths": scoped_paths,
                "command": None,
                "source_label": area_name,
                "area_path": item.get("path") or area_name,
            }
        )
        area_priority -= 2

    return specs


def build_repo_plan_preview(discovery_summary):
    specs = _build_repo_plan_specs(discovery_summary)
    return {
        "generated_task_count": len(specs),
        "verification_task_count": len([item for item in specs if item["task_kind"] == "verification_recipe"]),
        "repo_area_task_count": len([item for item in specs if item["task_kind"] == "repo_area_plan"]),
        "sample_paths": _normalize_paths(
            [path for item in specs for path in item.get("paths", [])]
        )[:8],
        "items": [
            {
                "synthesis_key": item["synthesis_key"],
                "task_kind": item["task_kind"],
                "title": item["title"],
                "source_label": item["source_label"],
                "paths": item.get("paths", [])[:3],
                "command": item.get("command"),
            }
            for item in specs[:8]
        ],
    }


def _filtered_discovery_summary(config):
    onboarding = dict(config.get("onboarding") or {})
    raw_summary = onboarding.get("discovery_summary") or {}
    review_overrides = onboarding.get("review_overrides") or default_onboarding_review_overrides(raw_summary)
    return apply_onboarding_review_overrides(raw_summary, review_overrides)


def _upsert_repo_plan_dependencies(connection, project_id, synthesized_tasks, desired_specs):
    synthesized_task_ids = [task_id for task_id in synthesized_tasks.values()]
    if synthesized_task_ids:
        placeholders = ", ".join(["?"] * len(synthesized_task_ids))
        connection.execute(
            """
            DELETE FROM task_dependencies
            WHERE project_id = ?
              AND source_task_id IN ({0})
              AND target_task_id IN ({0})
            """.format(placeholders),
            (project_id, *synthesized_task_ids, *synthesized_task_ids),
        )

    area_specs = {
        item["synthesis_key"]: item
        for item in desired_specs
        if item["task_kind"] == "repo_area_plan"
    }
    runbook_specs = [
        item
        for item in desired_specs
        if item["task_kind"] == "verification_recipe"
    ]
    area_keys = list(area_specs.keys())

    for runbook in runbook_specs:
        source_task_id = synthesized_tasks.get(runbook["synthesis_key"])
        if not source_task_id:
            continue
        matching_area_keys = [
            area_key
            for area_key, area_spec in area_specs.items()
            if any(
                path == area_spec["area_path"] or path.startswith(area_spec["area_path"] + "/")
                for path in (runbook.get("paths") or [])
                if area_spec.get("area_path")
            )
        ]
        if not matching_area_keys and area_keys:
            matching_area_keys = [area_keys[0]]
        for area_key in matching_area_keys:
            target_task_id = synthesized_tasks.get(area_key)
            if not target_task_id or target_task_id == source_task_id:
                continue
            connection.execute(
                """
                INSERT INTO task_dependencies (
                    dependency_id, project_id, source_task_id, target_task_id, dependency_type
                ) VALUES (?, ?, ?, ?, 'informs')
                """,
                (generate_id("dep"), project_id, source_task_id, target_task_id),
            )


def refresh_repo_grounded_plan(connection, project_id, actor_id, commit=True, enforce_permissions=True):
    resolved_project_id = resolve_project_id(connection, project_id, include_archived=False)
    if resolved_project_id is None:
        raise ValueError("project not found")
    project_row = resolve_project(connection, resolved_project_id, include_archived=False)
    if project_row is None:
        raise ValueError("project not found")
    if enforce_permissions:
        ensure_board_action_allowed(
            connection,
            actor_id,
            resolved_project_id,
            "refresh_repo_grounded_plan",
            "project",
            resolved_project_id,
        )

    config = _load_project_config(project_row)
    onboarding = dict(config.get("onboarding") or {})
    if (onboarding.get("mode") or "greenfield") != "brownfield":
        raise ValueError("project is not in brownfield mode")
    if (onboarding.get("review_status") or "review_pending") != "approved":
        raise ValueError("brownfield onboarding must be approved before refreshing the repo-grounded plan")

    filtered_summary = _filtered_discovery_summary(config)
    desired_specs = _build_repo_plan_specs(filtered_summary)
    preview = build_repo_plan_preview(filtered_summary)
    tactical_goal = connection.execute(
        """
        SELECT goal_id
        FROM goals
        WHERE project_id = ? AND goal_type = 'tactical'
        ORDER BY priority DESC, created_at ASC
        LIMIT 1
        """,
        (resolved_project_id,),
    ).fetchone()
    goal_id = tactical_goal["goal_id"] if tactical_goal is not None else None
    existing_rows = connection.execute(
        """
        SELECT
            task_id,
            title,
            description,
            status,
            review_state,
            acceptance_criteria_json,
            priority,
            synthesis_key
        FROM tasks
        WHERE project_id = ?
          AND synthesis_origin = ?
        """,
        (resolved_project_id, REPO_PLAN_SYNTHESIS_ORIGIN),
    ).fetchall()
    existing_by_key = {row["synthesis_key"]: dict(row) for row in existing_rows if row["synthesis_key"]}

    created_task_ids = []
    updated_task_ids = []
    skipped_task_ids = []
    cancelled_task_ids = []
    synthesized_task_ids = {}

    for spec in desired_specs:
        existing = existing_by_key.get(spec["synthesis_key"])
        if existing is None:
            task_id = generate_id("task")
            connection.execute(
                """
                INSERT INTO tasks (
                    task_id, project_id, goal_id, title, description, status,
                    priority, assigned_agent_id, acceptance_criteria_json,
                    progress_pct, review_state, synthesis_origin, synthesis_key
                ) VALUES (?, ?, ?, ?, ?, 'planned', ?, NULL, ?, 0, NULL, ?, ?)
                """,
                (
                    task_id,
                    resolved_project_id,
                    goal_id,
                    spec["title"],
                    spec["description"],
                    spec["priority"],
                    json.dumps(spec["acceptance_criteria"]),
                    REPO_PLAN_SYNTHESIS_ORIGIN,
                    spec["synthesis_key"],
                ),
            )
            created_task_ids.append(task_id)
            synthesized_task_ids[spec["synthesis_key"]] = task_id
            continue

        synthesized_task_ids[spec["synthesis_key"]] = existing["task_id"]
        mutable = (
            existing["status"] in REPO_PLAN_MUTABLE_STATUSES
            or (
                existing["status"] == "cancelled"
                and existing["review_state"] == REPO_PLAN_STALE_REVIEW_STATE
            )
        )
        if not mutable:
            skipped_task_ids.append(existing["task_id"])
            continue

        current_criteria = existing["acceptance_criteria_json"] or "[]"
        next_criteria = json.dumps(spec["acceptance_criteria"])
        if (
            existing["title"] == spec["title"]
            and existing["description"] == spec["description"]
            and existing["priority"] == spec["priority"]
            and current_criteria == next_criteria
            and existing["status"] in REPO_PLAN_MUTABLE_STATUSES
            and existing["review_state"] in (None, REPO_PLAN_STALE_REVIEW_STATE)
        ):
            continue

        connection.execute(
            """
            UPDATE tasks
            SET title = ?,
                description = ?,
                priority = ?,
                acceptance_criteria_json = ?,
                status = 'planned',
                review_state = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ?
            """,
            (
                spec["title"],
                spec["description"],
                spec["priority"],
                next_criteria,
                existing["task_id"],
            ),
        )
        updated_task_ids.append(existing["task_id"])

    desired_keys = {item["synthesis_key"] for item in desired_specs}
    for existing in existing_rows:
        if existing["synthesis_key"] in desired_keys:
            continue
        if existing["status"] not in REPO_PLAN_MUTABLE_STATUSES:
            skipped_task_ids.append(existing["task_id"])
            continue
        connection.execute(
            """
            UPDATE tasks
            SET status = 'cancelled',
                review_state = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ?
            """,
            (REPO_PLAN_STALE_REVIEW_STATE, existing["task_id"]),
        )
        cancelled_task_ids.append(existing["task_id"])

    _upsert_repo_plan_dependencies(connection, resolved_project_id, synthesized_task_ids, desired_specs)
    refresh_ready_tasks(connection, commit=False, project_id=resolved_project_id)

    refreshed_at = connection.execute("SELECT CURRENT_TIMESTAMP AS ts").fetchone()["ts"]
    onboarding["repo_plan"] = {
        **preview,
        "active_task_count": len(created_task_ids) + len(updated_task_ids) + len(skipped_task_ids),
        "created_count": len(created_task_ids),
        "updated_count": len(updated_task_ids),
        "cancelled_count": len(cancelled_task_ids),
        "stale": False,
        "last_refreshed_at": refreshed_at,
        "last_refreshed_by": actor_id,
    }
    config["onboarding"] = onboarding
    connection.execute(
        "UPDATE projects SET config_json = ?, updated_at = CURRENT_TIMESTAMP WHERE project_id = ?",
        (json.dumps(config), resolved_project_id),
    )
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, 'refresh_repo_grounded_plan', 'project', ?, ?)
        """,
        (
            generate_id("audit"),
            resolved_project_id,
            actor_id,
            resolved_project_id,
            json.dumps(
                {
                    "created_task_ids": created_task_ids,
                    "updated_task_ids": updated_task_ids,
                    "skipped_task_ids": skipped_task_ids,
                    "cancelled_task_ids": cancelled_task_ids,
                    "generated_task_count": preview["generated_task_count"],
                }
            ),
        ),
    )
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, action, category, description, details_json, severity
        ) VALUES (?, ?, 'repo_plan_refreshed', 'projects', ?, ?, 'info')
        """,
        (
            generate_id("act"),
            resolved_project_id,
            "Repo-grounded brownfield plan refreshed from the filtered discovery summary.",
            json.dumps(
                {
                    "created_count": len(created_task_ids),
                    "updated_count": len(updated_task_ids),
                    "cancelled_count": len(cancelled_task_ids),
                    "generated_task_count": preview["generated_task_count"],
                }
            ),
        ),
    )
    if commit:
        connection.commit()
    return {
        "project_id": resolved_project_id,
        "preview": preview,
        "created_task_ids": created_task_ids,
        "updated_task_ids": updated_task_ids,
        "skipped_task_ids": skipped_task_ids,
        "cancelled_task_ids": cancelled_task_ids,
        "repo_plan": onboarding["repo_plan"],
    }
