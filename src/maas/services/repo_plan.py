"""Repo-grounded brownfield plan synthesis and refresh."""

import json
import os
import subprocess

from maas.ids import generate_id
from maas.services.bootstrap import apply_onboarding_review_overrides, default_onboarding_review_overrides
from maas.services.git_workspaces import fetch_latest_git_workspace_by_task
from maas.services.projects import resolve_project, resolve_project_id
from maas.services.scheduler import refresh_ready_tasks
from maas.services.security import ensure_board_action_allowed


REPO_PLAN_SYNTHESIS_ORIGIN = "repo_grounded_plan"
REPO_PLAN_STALE_REVIEW_STATE = "repo_plan_stale"
REPO_PLAN_MUTABLE_STATUSES = {"planned", "ready", "blocked"}
BROWNFIELD_REVIEW_TASK_TITLE = "Review imported project understanding"


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


def _paths_overlap(left_paths, right_paths):
    left = _normalize_paths(left_paths)
    right = _normalize_paths(right_paths)
    if not left or not right:
        return False
    return any(
        candidate == other
        or candidate.startswith(other + "/")
        or other.startswith(candidate + "/")
        for candidate in left
        for other in right
    )


def _parse_acceptance_criteria(raw_value):
    try:
        payload = json.loads(raw_value or "[]")
    except (TypeError, ValueError):
        return []
    return payload if isinstance(payload, list) else []


def _validation_commands_from_acceptance(raw_value):
    commands = []
    seen = set()
    for criterion in _parse_acceptance_criteria(raw_value):
        if not isinstance(criterion, dict):
            continue
        command = (criterion.get("command") or "").strip()
        if not command or command in seen:
            continue
        seen.add(command)
        commands.append(command)
    return commands


def _task_paths_from_row(task_row):
    return _normalize_paths(
        [
            path
            for criterion in _parse_acceptance_criteria(task_row.get("acceptance_criteria_json"))
            if isinstance(criterion, dict) and criterion.get("type") == "source_path_exists"
            for path in criterion.get("paths") or []
        ]
    )


def _task_kind_from_synthesis_key(synthesis_key):
    if (synthesis_key or "").startswith("runbook:"):
        return "verification_recipe"
    if (synthesis_key or "").startswith("area:"):
        return "repo_area_plan"
    return "repo_plan_step"


def _project_supports_git_workspaces(connection, project_id):
    project_row = connection.execute(
        """
        SELECT source_root
        FROM projects
        WHERE project_id = ?
        """,
        (project_id,),
    ).fetchone()
    source_root = os.path.abspath((project_row["source_root"] if project_row else "") or "")
    if not source_root or not os.path.isdir(source_root):
        return False
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=source_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    return result.returncode == 0


def _issue_key_lookup(connection, project_id):
    rows = connection.execute(
        """
        SELECT task_id
        FROM tasks
        WHERE project_id = ?
        ORDER BY created_at ASC, task_id ASC
        """,
        (project_id,),
    ).fetchall()
    return {
        row["task_id"]: "ISS-{0}".format(str(index + 1).zfill(4))
        for index, row in enumerate(rows)
    }


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


def _repo_plan_task_rows(connection, project_id):
    return [
        dict(row)
        for row in connection.execute(
            """
            SELECT
                task_id,
                title,
                status,
                priority,
                review_state,
                synthesis_key,
                acceptance_criteria_json,
                created_at,
                updated_at
            FROM tasks
            WHERE project_id = ?
              AND synthesis_origin = ?
            ORDER BY priority DESC, created_at ASC, task_id ASC
            """,
            (project_id, REPO_PLAN_SYNTHESIS_ORIGIN),
        ).fetchall()
    ]


def _lineage_reference_for_item(item):
    if item is None:
        return None
    return {
        "synthesis_key": item.get("synthesis_key"),
        "task_id": item.get("task_id"),
        "issue_key": item.get("issue_key"),
        "title": item.get("title"),
        "status": item.get("status"),
        "review_state": item.get("review_state"),
        "task_kind": item.get("task_kind"),
    }


def _candidate_lineage_score(task_row, candidate):
    if candidate.get("task_kind") != _task_kind_from_synthesis_key(task_row.get("synthesis_key")):
        return -1
    score = 0
    task_paths = _task_paths_from_row(task_row)
    candidate_paths = candidate.get("paths") or []
    if _paths_overlap(task_paths, candidate_paths):
        score += 4
    task_commands = _validation_commands_from_acceptance(task_row.get("acceptance_criteria_json"))
    candidate_commands = candidate.get("validation_commands") or ([] if not candidate.get("command") else [candidate["command"]])
    if task_commands and candidate_commands and any(command in candidate_commands for command in task_commands):
        score += 5
    source_label = (task_row.get("synthesis_key") or "").split(":", 1)[-1]
    if source_label and source_label == candidate.get("source_label"):
        score += 2
    if task_row.get("synthesis_key") == candidate.get("synthesis_key"):
        score += 3
    return score


def _match_superseding_repo_plan_item(task_row, current_items):
    best_match = None
    best_score = -1
    for item in current_items:
        score = _candidate_lineage_score(task_row, item)
        if score > best_score:
            best_match = item
            best_score = score
    return best_match if best_score > 0 else None


def build_repo_plan_lineage(connection, project_id, current_items_by_key, task_rows=None, issue_keys=None):
    issue_keys = issue_keys or _issue_key_lookup(connection, project_id)
    task_rows = task_rows or _repo_plan_task_rows(connection, project_id)
    current_items_by_key = current_items_by_key or {}
    current_items = list(current_items_by_key.values())
    superseded_items = []
    historical_items = []
    for row in task_rows:
        current_item = current_items_by_key.get(row.get("synthesis_key"))
        if current_item is not None and current_item.get("task_id") == row.get("task_id"):
            continue
        successor = _match_superseding_repo_plan_item(row, current_items)
        lineage_status = (
            "superseded"
            if row.get("review_state") == REPO_PLAN_STALE_REVIEW_STATE or row.get("status") == "cancelled"
            else "historical"
        )
        payload = {
            "task_id": row.get("task_id"),
            "issue_key": issue_keys.get(row.get("task_id")),
            "title": row.get("title"),
            "status": row.get("status"),
            "review_state": row.get("review_state"),
            "task_kind": _task_kind_from_synthesis_key(row.get("synthesis_key")),
            "synthesis_key": row.get("synthesis_key"),
            "paths": _task_paths_from_row(row)[:3],
            "validation_commands": _validation_commands_from_acceptance(row.get("acceptance_criteria_json")),
            "updated_at": row.get("updated_at"),
            "lineage_status": lineage_status,
            "superseded_by": _lineage_reference_for_item(successor),
        }
        if lineage_status == "superseded":
            superseded_items.append(payload)
        else:
            historical_items.append(payload)

    refresh_history = []
    for row in connection.execute(
        """
        SELECT actor_id, detail_json, created_at
        FROM audit_trail
        WHERE project_id = ?
          AND action_type = 'refresh_repo_grounded_plan'
        ORDER BY created_at DESC, rowid DESC
        LIMIT 5
        """,
        (project_id,),
    ).fetchall():
        try:
            detail = json.loads(row["detail_json"] or "{}")
        except ValueError:
            detail = {}
        refresh_history.append(
            {
                "refreshed_at": row["created_at"],
                "refreshed_by": row["actor_id"],
                "created_count": len(detail.get("created_task_ids") or []),
                "updated_count": len(detail.get("updated_task_ids") or []),
                "cancelled_count": len(detail.get("cancelled_task_ids") or []),
                "skipped_count": len(detail.get("skipped_task_ids") or []),
                "generated_task_count": detail.get("generated_task_count") or 0,
            }
        )

    return {
        "superseded_task_count": len(superseded_items),
        "historical_task_count": len(historical_items),
        "superseded_items": superseded_items[:6],
        "historical_items": historical_items[:6],
        "recent_refreshes": refresh_history,
    }


def build_repo_plan_trust(onboarding, lineage):
    onboarding = onboarding or {}
    repo_plan_state = onboarding.get("repo_plan") or {}
    drift = onboarding.get("drift_summary") or {}
    drift_detected = bool(drift.get("detected"))
    drift_severity = drift.get("severity") or ("none" if not drift_detected else "medium")
    stale = bool(repo_plan_state.get("stale"))
    review_status = onboarding.get("review_status") or "review_pending"
    stale_reason = repo_plan_state.get("stale_reason")
    last_refreshed_at = repo_plan_state.get("last_refreshed_at")
    superseded_count = (lineage or {}).get("superseded_task_count", 0)
    historical_count = (lineage or {}).get("historical_task_count", 0)

    if not last_refreshed_at:
        return {
            "state": "preview_only",
            "safe_to_execute": False,
            "stale": stale,
            "drift_detected": drift_detected,
            "drift_severity": drift_severity,
            "summary": "Repo-grounded brownfield work is still a preview until the plan has been refreshed at least once.",
            "detail": "Approve the onboarding review and refresh the repo-grounded plan before relying on synthesized brownfield tasks.",
            "recommended_action": "Refresh the repo-grounded plan after the brownfield review is approved.",
            "superseded_task_count": superseded_count,
            "historical_task_count": historical_count,
        }

    if stale:
        if stale_reason == "review_overrides_changed":
            detail = "Review overrides changed after the last refresh, so the current brownfield plan no longer matches the accepted imported scope."
            action = "Reconfirm the brownfield review inputs, then refresh the repo-grounded plan."
        elif drift_detected:
            detail = drift.get("diagnosis") or "Imported repository drift changed the inputs that grounded the current brownfield plan."
            action = "Review the imported drift and refresh the repo-grounded plan before acting on stale recommendations."
        else:
            detail = "The imported understanding changed after the last repo-plan refresh."
            action = "Refresh the repo-grounded plan before acting on imported recommendations."
        return {
            "state": "stale",
            "safe_to_execute": False,
            "stale": True,
            "drift_detected": drift_detected,
            "drift_severity": drift_severity,
            "summary": "Brownfield grounding is stale relative to the latest imported understanding.",
            "detail": detail,
            "recommended_action": action,
            "superseded_task_count": superseded_count,
            "historical_task_count": historical_count,
        }

    if drift_detected and drift.get("safe_to_execute"):
        return {
            "state": "watch",
            "safe_to_execute": True,
            "stale": False,
            "drift_detected": True,
            "drift_severity": drift_severity,
            "summary": drift.get("summary") or "Low-severity brownfield drift was detected after the last scan.",
            "detail": drift.get("diagnosis") or "The imported repo changed, but the current brownfield recommendations are still considered safe to execute.",
            "recommended_action": "Monitor the imported drift and rescan again if the affected area broadens.",
            "superseded_task_count": superseded_count,
            "historical_task_count": historical_count,
        }

    return {
        "state": "fresh",
        "safe_to_execute": review_status == "approved",
        "stale": False,
        "drift_detected": drift_detected,
        "drift_severity": drift_severity,
        "summary": "Brownfield grounding matches the latest approved imported understanding.",
        "detail": (
            "Historical synthesized tasks remain visible for context."
            if superseded_count or historical_count
            else "No superseded brownfield plan steps are waiting for operator interpretation."
        ),
        "recommended_action": "Use the repo-grounded plan and linked issue detail as the current imported execution baseline.",
        "superseded_task_count": superseded_count,
        "historical_task_count": historical_count,
    }


def _repo_plan_relationship_map(connection, project_id, task_rows, issue_keys):
    task_rows_by_id = {row["task_id"]: row for row in task_rows}
    task_ids = list(task_rows_by_id.keys())
    if not task_ids:
        return {}
    placeholders = ", ".join("?" for _ in task_ids)
    rows = connection.execute(
        """
        SELECT source_task_id, target_task_id, dependency_type
        FROM task_dependencies
        WHERE project_id = ?
          AND source_task_id IN ({placeholders})
          AND target_task_id IN ({placeholders})
        ORDER BY rowid ASC
        """.format(placeholders=placeholders),
        (project_id, *task_ids, *task_ids),
    ).fetchall()
    relationships = {task_id: [] for task_id in task_ids}
    for row in rows:
        source_task_id = row["source_task_id"]
        target_task_id = row["target_task_id"]
        dependency_type = row["dependency_type"]
        source_row = task_rows_by_id.get(source_task_id)
        target_row = task_rows_by_id.get(target_task_id)
        if source_row is not None:
            relationships[source_task_id].append(
                {
                    "task_id": target_task_id,
                    "issue_key": issue_keys.get(target_task_id),
                    "title": target_row.get("title") if target_row else None,
                    "status": target_row.get("status") if target_row else None,
                    "review_state": target_row.get("review_state") if target_row else None,
                    "task_kind": _task_kind_from_synthesis_key(target_row.get("synthesis_key")) if target_row else None,
                    "dependency_type": dependency_type,
                    "direction": "outgoing",
                }
            )
        if target_row is not None:
            relationships[target_task_id].append(
                {
                    "task_id": source_task_id,
                    "issue_key": issue_keys.get(source_task_id),
                    "title": source_row.get("title") if source_row else None,
                    "status": source_row.get("status") if source_row else None,
                    "review_state": source_row.get("review_state") if source_row else None,
                    "task_kind": _task_kind_from_synthesis_key(source_row.get("synthesis_key")) if source_row else None,
                    "dependency_type": dependency_type,
                    "direction": "incoming",
                }
            )
    return relationships


def build_repo_plan_item_lookup(
    discovery_summary,
    task_rows=None,
    issue_keys=None,
    relationship_map=None,
    latest_verification_by_task=None,
    git_workspaces_by_task=None,
    git_workspace_supported=False,
):
    specs = _build_repo_plan_specs(discovery_summary)
    existing_by_key = {
        row["synthesis_key"]: dict(row)
        for row in (task_rows or [])
        if row.get("synthesis_key")
    }
    relationship_map = relationship_map or {}
    issue_keys = issue_keys or {}
    latest_verification_by_task = latest_verification_by_task or {}
    git_workspaces_by_task = git_workspaces_by_task or {}
    items = {}
    for spec in specs:
        existing = existing_by_key.get(spec["synthesis_key"])
        task_id = existing.get("task_id") if existing else None
        all_linked_items = relationship_map.get(task_id, []) if task_id else []
        linked_items = all_linked_items[:4]
        validation_commands = (
            _validation_commands_from_acceptance(existing.get("acceptance_criteria_json"))
            if existing
            else ([spec["command"]] if spec.get("command") else [])
        )
        latest_verification = latest_verification_by_task.get(task_id) or {}
        git_workspace = git_workspaces_by_task.get(task_id) or {}
        supporting_verification_recipe_count = len(
            [
                item
                for item in all_linked_items
                if item.get("direction") == "incoming"
                and item.get("dependency_type") == "informs"
                and item.get("task_kind") == "verification_recipe"
            ]
        )
        covered_repo_area_count = len(
            [
                item
                for item in all_linked_items
                if item.get("direction") == "outgoing"
                and item.get("dependency_type") == "informs"
                and item.get("task_kind") == "repo_area_plan"
            ]
        )
        items[spec["synthesis_key"]] = {
            "synthesis_key": spec["synthesis_key"],
            "task_kind": spec["task_kind"],
            "title": spec["title"],
            "source_label": spec["source_label"],
            "paths": spec.get("paths", [])[:3],
            "command": spec.get("command"),
            "validation_commands": validation_commands,
            "task_id": task_id,
            "issue_key": issue_keys.get(task_id) if task_id else None,
            "status": existing.get("status") if existing else None,
            "review_state": existing.get("review_state") if existing else None,
            "linked_items": linked_items,
            "latest_verification_status": latest_verification.get("status"),
            "latest_verification_at": latest_verification.get("finished_at"),
            "latest_verification_command": latest_verification.get("command"),
            "git_workspace_supported": bool(git_workspace_supported and task_id and spec["task_kind"] == "repo_area_plan"),
            "git_workspace_prepared": bool(git_workspace),
            "git_workspace_branch": git_workspace.get("branch_name"),
            "git_workspace_dirty_files": git_workspace.get("dirty_file_count", 0),
            "git_workspace_last_diff_at": git_workspace.get("updated_at"),
            "supporting_verification_recipe_count": supporting_verification_recipe_count,
            "covered_repo_area_count": covered_repo_area_count,
            "lineage_status": "current",
            "superseded_by": None,
        }
    return items


def build_repo_plan_preview(
    discovery_summary,
    task_rows=None,
    issue_keys=None,
    relationship_map=None,
    latest_verification_by_task=None,
    git_workspaces_by_task=None,
    git_workspace_supported=False,
):
    items = list(
        build_repo_plan_item_lookup(
            discovery_summary,
            task_rows=task_rows,
            issue_keys=issue_keys,
            relationship_map=relationship_map,
            latest_verification_by_task=latest_verification_by_task,
            git_workspaces_by_task=git_workspaces_by_task,
            git_workspace_supported=git_workspace_supported,
        ).values()
    )
    return {
        "generated_task_count": len(items),
        "verification_task_count": len([item for item in items if item["task_kind"] == "verification_recipe"]),
        "repo_area_task_count": len([item for item in items if item["task_kind"] == "repo_area_plan"]),
        "sample_paths": _normalize_paths(
            [path for item in items for path in item.get("paths", [])]
        )[:8],
        "items": items[:8],
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

    from maas.services.verification import fetch_latest_verification_by_task

    current_repo_plan_tasks = _repo_plan_task_rows(connection, resolved_project_id)
    issue_keys = _issue_key_lookup(connection, resolved_project_id)
    relationship_map = _repo_plan_relationship_map(connection, resolved_project_id, current_repo_plan_tasks, issue_keys)
    latest_verification_by_task = fetch_latest_verification_by_task(connection, resolved_project_id)
    git_workspaces_by_task = fetch_latest_git_workspace_by_task(connection, project_id=resolved_project_id)
    git_workspace_supported = _project_supports_git_workspaces(connection, resolved_project_id)
    preview = build_repo_plan_preview(
        filtered_summary,
        task_rows=current_repo_plan_tasks,
        issue_keys=issue_keys,
        relationship_map=relationship_map,
        latest_verification_by_task=latest_verification_by_task,
        git_workspaces_by_task=git_workspaces_by_task,
        git_workspace_supported=git_workspace_supported,
    )

    refreshed_at = connection.execute("SELECT CURRENT_TIMESTAMP AS ts").fetchone()["ts"]
    onboarding["repo_plan"] = {
        **preview,
        "active_task_count": len([row for row in current_repo_plan_tasks if row.get("status") != "cancelled"]),
        "created_count": len(created_task_ids),
        "updated_count": len(updated_task_ids),
        "cancelled_count": len(cancelled_task_ids),
        "stale": False,
        "stale_reason": None,
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


def build_brownfield_grounding(connection, project_id, task_row, issue_keys=None):
    project_row = resolve_project(connection, project_id, include_archived=False)
    if project_row is None:
        return None
    config = _load_project_config(project_row)
    onboarding = dict(config.get("onboarding") or {})
    if (onboarding.get("mode") or "greenfield") != "brownfield":
        return None

    filtered_summary = _filtered_discovery_summary(config)
    from maas.services.verification import fetch_latest_verification_by_task

    repo_task_rows = _repo_plan_task_rows(connection, project_id)
    issue_keys = issue_keys or _issue_key_lookup(connection, project_id)
    relationship_map = _repo_plan_relationship_map(connection, project_id, repo_task_rows, issue_keys)
    latest_verification_by_task = fetch_latest_verification_by_task(connection, project_id)
    git_workspaces_by_task = fetch_latest_git_workspace_by_task(connection, project_id=project_id)
    git_workspace_supported = _project_supports_git_workspaces(connection, project_id)
    repo_plan_items = build_repo_plan_item_lookup(
        filtered_summary,
        task_rows=repo_task_rows,
        issue_keys=issue_keys,
        relationship_map=relationship_map,
        latest_verification_by_task=latest_verification_by_task,
        git_workspaces_by_task=git_workspaces_by_task,
        git_workspace_supported=git_workspace_supported,
    )
    lineage = build_repo_plan_lineage(connection, project_id, repo_plan_items, task_rows=repo_task_rows, issue_keys=issue_keys)
    trust = build_repo_plan_trust(onboarding, lineage)
    scoped_paths = _normalize_paths(
        [
            path
            for criterion in _parse_acceptance_criteria(task_row.get("acceptance_criteria_json"))
            if isinstance(criterion, dict) and criterion.get("type") == "source_path_exists"
            for path in criterion.get("paths") or []
        ]
    )
    validation_commands = _validation_commands_from_acceptance(task_row.get("acceptance_criteria_json"))
    current_repo_plan_preview = build_repo_plan_preview(
        filtered_summary,
        task_rows=repo_task_rows,
        issue_keys=issue_keys,
        relationship_map=relationship_map,
        latest_verification_by_task=latest_verification_by_task,
        git_workspaces_by_task=git_workspaces_by_task,
        git_workspace_supported=git_workspace_supported,
    )
    current_active_count = len([row for row in repo_task_rows if row.get("status") != "cancelled"])
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
    review_status = onboarding.get("review_status")
    if not review_status:
        if review_task is None:
            review_status = "review_pending"
        elif review_task["status"] == "done" or review_task["review_state"] == "approved":
            review_status = "approved"
        elif review_task["review_state"] == "changes_requested":
            review_status = "changes_requested"
        else:
            review_status = "review_pending"

    matched_repo_items = []
    synthesis_key = task_row.get("synthesis_key")
    seen_synthesis_keys = set()
    if task_row.get("synthesis_origin") == REPO_PLAN_SYNTHESIS_ORIGIN:
        exact_item = repo_plan_items.get(synthesis_key)
        if exact_item is None:
            task_workspace = git_workspaces_by_task.get(task_row.get("task_id")) or {}
            latest_verification = latest_verification_by_task.get(task_row.get("task_id")) or {}
            inferred_kind = _task_kind_from_synthesis_key(synthesis_key)
            all_linked_items = relationship_map.get(task_row.get("task_id"), [])
            linked_items = all_linked_items[:4]
            current_match = _match_superseding_repo_plan_item(task_row, list(repo_plan_items.values()))
            exact_item = {
                "synthesis_key": synthesis_key,
                "task_kind": inferred_kind,
                "title": task_row.get("title"),
                "source_label": (synthesis_key or task_row.get("title") or "").split(":", 1)[-1],
                "paths": scoped_paths[:3],
                "command": validation_commands[0] if validation_commands else None,
                "validation_commands": validation_commands,
                "task_id": task_row.get("task_id"),
                "issue_key": issue_keys.get(task_row.get("task_id")),
                "status": task_row.get("status"),
                "review_state": task_row.get("review_state"),
                "linked_items": linked_items,
                "latest_verification_status": latest_verification.get("status"),
                "latest_verification_at": latest_verification.get("finished_at"),
                "latest_verification_command": latest_verification.get("command"),
                "git_workspace_supported": bool(
                    git_workspace_supported and task_row.get("task_id") and inferred_kind == "repo_area_plan"
                ),
                "git_workspace_prepared": bool(task_workspace),
                "git_workspace_branch": task_workspace.get("branch_name"),
                "git_workspace_dirty_files": task_workspace.get("dirty_file_count", 0),
                "git_workspace_last_diff_at": task_workspace.get("updated_at"),
                "supporting_verification_recipe_count": len(
                    [
                        item
                        for item in all_linked_items
                        if item.get("direction") == "incoming"
                        and item.get("dependency_type") == "informs"
                        and item.get("task_kind") == "verification_recipe"
                    ]
                ),
                "covered_repo_area_count": len(
                    [
                        item
                        for item in all_linked_items
                        if item.get("direction") == "outgoing"
                        and item.get("dependency_type") == "informs"
                        and item.get("task_kind") == "repo_area_plan"
                    ]
                ),
                "lineage_status": (
                    "superseded"
                    if task_row.get("review_state") == REPO_PLAN_STALE_REVIEW_STATE or task_row.get("status") == "cancelled"
                    else "historical"
                ),
                "superseded_by": _lineage_reference_for_item(current_match),
            }
        else:
            exact_item = {
                **exact_item,
                "lineage_status": "current",
                "superseded_by": None,
            }
        matched_repo_items.append(exact_item)
        seen_synthesis_keys.add(exact_item["synthesis_key"])
    for item in repo_plan_items.values():
        if item["synthesis_key"] in seen_synthesis_keys:
            continue
        command_match = bool(item.get("command") and item["command"] in validation_commands)
        path_match = _paths_overlap(item.get("paths") or [], scoped_paths)
        if command_match or path_match:
            matched_repo_items.append(item)
            seen_synthesis_keys.add(item["synthesis_key"])

    codebase_areas = [
        item
        for item in filtered_summary.get("codebase_map") or []
        if _paths_overlap(scoped_paths, (item.get("sample_files") or []) + ([item.get("path")] if item.get("path") else []))
    ][:4]
    workflow_signals = [
        item
        for item in filtered_summary.get("workflow_details") or []
        if item.get("path") and _paths_overlap(scoped_paths, [item["path"]])
    ][:4]
    runbook_signals = [
        item
        for item in filtered_summary.get("runbook_commands") or []
        if (
            item.get("command") and item["command"] in validation_commands
        ) or (
            item.get("path") and _paths_overlap(scoped_paths, [item["path"]])
        )
    ][:4]
    repo_plan_state = onboarding.get("repo_plan") or {}

    return {
        "review_status": review_status,
        "scoped_paths": scoped_paths,
        "validation_commands": validation_commands,
        "repo_plan": {
            "generated_task_count": current_repo_plan_preview["generated_task_count"],
            "active_task_count": current_active_count,
            "stale": bool(repo_plan_state.get("stale")),
            "stale_reason": repo_plan_state.get("stale_reason"),
            "last_refreshed_at": repo_plan_state.get("last_refreshed_at"),
            "last_refreshed_by": repo_plan_state.get("last_refreshed_by"),
            "trust": trust,
            "lineage": lineage,
        },
        "repo_plan_items": matched_repo_items[:6],
        "codebase_areas": codebase_areas,
        "workflow_signals": workflow_signals,
        "runbook_signals": runbook_signals,
    }
