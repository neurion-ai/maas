"""Goal intake and issue synthesis helpers."""

from __future__ import annotations

import json
import re

from maas.ids import generate_id
from maas.services.projects import resolve_project, resolve_project_id
from maas.services.scheduler import refresh_ready_tasks
from maas.services.security import ensure_board_action_allowed


def _slug(value):
    parts = re.findall(r"[a-z0-9]+", (value or "").lower())
    return "-".join(parts[:8]) or "goal"


def _load_project_config(project_row):
    try:
        payload = json.loads(project_row["config_json"] or "{}")
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


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


def _acceptance_summary(acceptance_items):
    labels = []
    for item in acceptance_items or []:
        item_type = item.get("type")
        if item_type == "artifact_exists":
            labels.append("produce operator-visible output")
        elif item_type == "human_review":
            labels.append("clear human review")
        elif item_type:
            labels.append(item_type.replace("_", " "))
    if not labels:
        return "No explicit acceptance criteria are recorded."
    if len(labels) == 1:
        return labels[0].capitalize() + "."
    return "{0}, and {1}.".format(", ".join(label for label in labels[:-1]), labels[-1]).capitalize()


def _goal_issue_specs(goal_row, project_row):
    title = (goal_row["title"] or "").strip()
    description = (goal_row["description"] or "").strip()
    project_type = (project_row["project_type"] or "").strip().lower()
    text = "{0}\n{1}".format(title, description).lower()
    is_research = project_type == "research" or any(keyword in text for keyword in ("research", "investigate", "thesis", "study", "experiment"))
    is_delivery = any(keyword in text for keyword in ("ship", "deliver", "release", "launch", "deploy", "publish", "pr"))
    goal_noun = title or "the goal"
    high = max(1, int(goal_row["priority"] or 50))
    if is_research:
        specs = [
            {
                "slug": "frame-research-brief",
                "title": "Frame the research brief for {0}".format(goal_noun),
                "description": "Clarify the scope, success criteria, and evidence expected for this research goal.\n\nGoal context:\n{0}".format(description or title),
                "priority": high,
                "acceptance": [{"type": "artifact_exists"}],
                "stage_label": "Research framing",
                "why_it_exists": "Create a clear research brief so later evidence can be judged against the same scope and success criteria.",
            },
            {
                "slug": "collect-baseline-context",
                "title": "Collect baseline context for {0}".format(goal_noun),
                "description": "Inspect the current repository, prior memory, and relevant artifacts before deep work begins.",
                "priority": max(high - 4, 1),
                "acceptance": [{"type": "artifact_exists"}],
                "stage_label": "Context grounding",
                "why_it_exists": "Ground the investigation in the current repo, prior memory, and existing artifacts before deeper work starts.",
            },
            {
                "slug": "run-core-investigation",
                "title": "Run the core investigation for {0}".format(goal_noun),
                "description": "Execute the primary research loop and record evidence-backed findings.",
                "priority": max(high - 8, 1),
                "acceptance": [{"type": "artifact_exists"}],
                "stage_label": "Investigation",
                "why_it_exists": "Produce the main research output that moves the goal forward with evidence rather than assumptions.",
            },
            {
                "slug": "verify-findings",
                "title": "Verify findings for {0}".format(goal_noun),
                "description": "Validate the research outputs and capture what still looks uncertain or risky.",
                "priority": max(high - 12, 1),
                "acceptance": [{"type": "artifact_exists"}, {"type": "human_review"}],
                "stage_label": "Verification",
                "why_it_exists": "Turn raw findings into trustworthy evidence by testing them and surfacing remaining risk explicitly.",
            },
            {
                "slug": "prepare-delivery-report",
                "title": "Prepare the delivery report for {0}".format(goal_noun),
                "description": "Package the research result into a deliverable summary, artifact bundle, or draft PR narrative.",
                "priority": max(high - 16, 1),
                "acceptance": [{"type": "artifact_exists"}, {"type": "human_review"}],
                "stage_label": "Delivery",
                "why_it_exists": "Package the result so an operator or downstream reviewer can consume it without replaying the whole investigation.",
            },
        ]
    else:
        specs = [
            {
                "slug": "define-success-criteria",
                "title": "Define success criteria for {0}".format(goal_noun),
                "description": "Turn the goal into operator-visible scope, acceptance criteria, and expected outputs.\n\nGoal context:\n{0}".format(description or title),
                "priority": high,
                "acceptance": [{"type": "artifact_exists"}],
                "stage_label": "Planning",
                "why_it_exists": "Make the goal explicit enough that implementation, review, and delivery all share the same definition of done.",
            },
            {
                "slug": "inspect-current-surface",
                "title": "Inspect the current implementation surface for {0}".format(goal_noun),
                "description": "Inspect the repo, existing memory, and current state before implementation starts.",
                "priority": max(high - 4, 1),
                "acceptance": [{"type": "artifact_exists"}],
                "stage_label": "Grounding",
                "why_it_exists": "Anchor the goal in the current implementation surface and reusable memory before changing code or behavior.",
            },
            {
                "slug": "implement-primary-slice",
                "title": "Implement the primary slice for {0}".format(goal_noun),
                "description": "Complete the highest-value change required to advance this goal and record the output.",
                "priority": max(high - 8, 1),
                "acceptance": [{"type": "artifact_exists"}],
                "stage_label": "Implementation",
                "why_it_exists": "Deliver the main code or artifact change that materially advances the goal instead of just preparing for it.",
            },
            {
                "slug": "verify-output-and-risk",
                "title": "Verify the output and risk posture for {0}".format(goal_noun),
                "description": "Run verification, collect evidence, and summarize remaining risks or follow-up items.",
                "priority": max(high - 12, 1),
                "acceptance": [{"type": "artifact_exists"}, {"type": "human_review"}],
                "stage_label": "Verification",
                "why_it_exists": "Convert the implementation result into reviewable evidence and expose the remaining risk posture before delivery.",
            },
            {
                "slug": "prepare-delivery-package",
                "title": "Prepare the delivery package for {0}".format(goal_noun),
                "description": (
                    "Prepare the final delivery artifact bundle and GitHub-ready summary for this goal."
                    if is_delivery
                    else "Prepare the final delivery artifact bundle and operator-ready summary for this goal."
                ),
                "priority": max(high - 16, 1),
                "acceptance": [{"type": "artifact_exists"}, {"type": "human_review"}],
                "stage_label": "Delivery",
                "why_it_exists": "Package the finished slice into a handoff that can be reviewed, approved, or synchronized to GitHub cleanly.",
            },
        ]
    return specs


def _goal_plan_task_rows(connection, project_id, goal_id, origin):
    return connection.execute(
        """
        SELECT
            task_id,
            title,
            status,
            priority,
            review_state,
            synthesis_key,
            created_at,
            updated_at
        FROM tasks
        WHERE project_id = ?
          AND goal_id = ?
          AND synthesis_origin = ?
        ORDER BY created_at ASC, task_id ASC
        """,
        (project_id, goal_id, origin),
    ).fetchall()


def _goal_plan_dependency_rows(connection, project_id, task_ids):
    if not task_ids:
        return []
    placeholders = ", ".join("?" for _ in task_ids)
    params = [project_id, *task_ids, *task_ids]
    return connection.execute(
        """
        SELECT source_task_id, target_task_id
        FROM task_dependencies
        WHERE project_id = ?
          AND dependency_type = 'blocks'
          AND source_task_id IN ({placeholders})
          AND target_task_id IN ({placeholders})
        ORDER BY rowid ASC
        """.format(placeholders=placeholders),
        tuple(params),
    ).fetchall()


def _goal_step_slug(origin, synthesis_key):
    prefix = "{0}:".format(origin)
    if synthesis_key and synthesis_key.startswith(prefix):
        return synthesis_key[len(prefix) :]
    return None


def _build_goal_plan_explainability(connection, project_id, goal_row, project_row, issue_keys=None):
    origin = "goal_plan:{0}".format(goal_row["goal_id"])
    task_rows = _goal_plan_task_rows(connection, project_id, goal_row["goal_id"], origin)
    issue_keys = issue_keys or _issue_key_lookup(connection, project_id)
    if not task_rows:
        return {
            "goal_id": goal_row["goal_id"],
            "goal_title": goal_row["title"],
            "origin": origin,
            "summary": {
                "task_count": 0,
                "done_count": 0,
                "open_count": 0,
                "blocked_count": 0,
                "review_count": 0,
                "current_focus_task_id": None,
                "current_focus_issue_key": None,
                "current_focus_title": None,
                "current_focus_status": None,
                "critical_path_remaining": 0,
            },
            "critical_path": {
                "remaining_task_count": 0,
                "items": [],
            },
            "tasks": [],
        }

    specs = _goal_issue_specs(goal_row, project_row)
    specs_by_slug = {
        spec["slug"]: spec
        for spec in specs
    }
    spec_order = {
        spec["slug"]: index
        for index, spec in enumerate(specs)
    }
    task_rows = sorted(
        task_rows,
        key=lambda row: (
            spec_order.get(_goal_step_slug(origin, row["synthesis_key"]), len(spec_order)),
            row["created_at"] or "",
            row["task_id"],
        ),
    )
    ordered_ids = [row["task_id"] for row in task_rows]
    row_by_id = {row["task_id"]: dict(row) for row in task_rows}
    dependency_rows = _goal_plan_dependency_rows(connection, project_id, ordered_ids)
    depends_on = {task_id: [] for task_id in ordered_ids}
    unlocks = {task_id: [] for task_id in ordered_ids}
    for row in dependency_rows:
        source_task_id = row["source_task_id"]
        target_task_id = row["target_task_id"]
        unlocks.setdefault(source_task_id, []).append(target_task_id)
        depends_on.setdefault(target_task_id, []).append(source_task_id)

    remaining_ids = [
        task_id
        for task_id in ordered_ids
        if row_by_id[task_id]["status"] not in {"done", "cancelled"}
    ]
    remaining_set = set(remaining_ids)
    longest_to_end = {}
    next_on_path = {}
    position_by_id = {task_id: index for index, task_id in enumerate(ordered_ids)}
    for task_id in reversed(ordered_ids):
        if task_id not in remaining_set:
            continue
        child_ids = [child_id for child_id in unlocks.get(task_id, []) if child_id in remaining_set]
        if not child_ids:
            longest_to_end[task_id] = 1
            next_on_path[task_id] = None
            continue
        best_child_id = max(
            child_ids,
            key=lambda child_id: (
                longest_to_end.get(child_id, 1),
                -position_by_id.get(child_id, 0),
            ),
        )
        longest_to_end[task_id] = 1 + longest_to_end.get(best_child_id, 1)
        next_on_path[task_id] = best_child_id

    root_ids = [
        task_id
        for task_id in remaining_ids
        if not [dependency_id for dependency_id in depends_on.get(task_id, []) if dependency_id in remaining_set]
    ]
    critical_path_ids = []
    if root_ids:
        start_id = max(
            root_ids,
            key=lambda task_id: (
                longest_to_end.get(task_id, 1),
                -position_by_id.get(task_id, 0),
            ),
        )
        focus_id = start_id
        while focus_id:
            critical_path_ids.append(focus_id)
            focus_id = next_on_path.get(focus_id)
    critical_rank = {
        task_id: index + 1
        for index, task_id in enumerate(critical_path_ids)
    }

    current_focus_id = next(
        (task_id for task_id in ordered_ids if row_by_id[task_id]["status"] not in {"done", "cancelled"}),
        None,
    )

    tasks = []
    for index, row in enumerate(task_rows, start=1):
        task_row = row_by_id[row["task_id"]]
        slug = _goal_step_slug(origin, task_row.get("synthesis_key"))
        spec = specs_by_slug.get(slug) or {}
        open_dependency_count = len(
            [
                task_id
                for task_id in depends_on.get(row["task_id"], [])
                if row_by_id.get(task_id, {}).get("status") not in {"done", "cancelled"}
            ]
        )
        open_unlock_count = len(
            [
                task_id
                for task_id in unlocks.get(row["task_id"], [])
                if row_by_id.get(task_id, {}).get("status") not in {"done", "cancelled"}
            ]
        )
        depends_on_items = [
            {
                "task_id": dependency_id,
                "issue_key": issue_keys.get(dependency_id),
                "title": row_by_id.get(dependency_id, {}).get("title"),
                "status": row_by_id.get(dependency_id, {}).get("status"),
            }
            for dependency_id in depends_on.get(row["task_id"], [])
        ]
        unlock_items = [
            {
                "task_id": dependency_id,
                "issue_key": issue_keys.get(dependency_id),
                "title": row_by_id.get(dependency_id, {}).get("title"),
                "status": row_by_id.get(dependency_id, {}).get("status"),
            }
            for dependency_id in unlocks.get(row["task_id"], [])
        ]
        tasks.append(
            {
                "task_id": row["task_id"],
                "issue_key": issue_keys.get(row["task_id"]),
                "title": row["title"],
                "status": row["status"],
                "review_state": row["review_state"],
                "priority": row["priority"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "step_index": index,
                "step_count": len(task_rows),
                "step_slug": slug,
                "stage_label": spec.get("stage_label"),
                "why_it_exists": spec.get("why_it_exists") or "This synthesized issue exists to move the goal forward in sequence.",
                "acceptance_summary": _acceptance_summary(spec.get("acceptance") or []),
                "depends_on": depends_on_items,
                "unlocks": unlock_items,
                "depends_on_count": len(depends_on_items),
                "unlocks_count": len(unlock_items),
                "open_dependency_count": open_dependency_count,
                "open_unlock_count": open_unlock_count,
                "is_current_focus": row["task_id"] == current_focus_id,
                "is_on_critical_path": row["task_id"] in critical_rank,
                "critical_path_rank": critical_rank.get(row["task_id"]),
            }
        )

    done_count = len([item for item in tasks if item["status"] == "done"])
    blocked_count = len([item for item in tasks if item["status"] == "blocked"])
    review_count = len([item for item in tasks if item["status"] == "review"])
    open_count = len([item for item in tasks if item["status"] not in {"done", "cancelled"}])
    current_focus = next((item for item in tasks if item["task_id"] == current_focus_id), None)
    critical_path_items = [
        next(item for item in tasks if item["task_id"] == task_id)
        for task_id in critical_path_ids
    ]

    return {
        "goal_id": goal_row["goal_id"],
        "goal_title": goal_row["title"],
        "origin": origin,
        "summary": {
            "task_count": len(tasks),
            "done_count": done_count,
            "open_count": open_count,
            "blocked_count": blocked_count,
            "review_count": review_count,
            "current_focus_task_id": current_focus["task_id"] if current_focus else None,
            "current_focus_issue_key": current_focus["issue_key"] if current_focus else None,
            "current_focus_title": current_focus["title"] if current_focus else None,
            "current_focus_status": current_focus["status"] if current_focus else None,
            "critical_path_remaining": len(critical_path_items),
        },
        "critical_path": {
            "remaining_task_count": len(critical_path_items),
            "items": critical_path_items,
        },
        "tasks": tasks,
    }


def fetch_goal_explainability(connection, project_id, goal_id):
    resolved_project_id = resolve_project_id(connection, project_id, include_archived=False)
    if resolved_project_id is None:
        raise ValueError("project not found")
    goal_row = connection.execute(
        """
        SELECT goal_id, project_id, title, description, status, goal_type, priority
        FROM goals
        WHERE project_id = ?
          AND goal_id = ?
        """,
        (resolved_project_id, goal_id),
    ).fetchone()
    if goal_row is None:
        raise ValueError("goal not found")
    project_row = resolve_project(connection, resolved_project_id, include_archived=False)
    issue_keys = _issue_key_lookup(connection, resolved_project_id)
    return _build_goal_plan_explainability(
        connection,
        resolved_project_id,
        goal_row,
        project_row,
        issue_keys=issue_keys,
    )


def create_goal(connection, actor_id, project_id, title, description="", goal_type="initiative", priority=75, parent_goal_id=None):
    resolved_project_id = resolve_project_id(connection, project_id, include_archived=False)
    if resolved_project_id is None:
        raise ValueError("project not found")
    cleaned_title = (title or "").strip()
    if not cleaned_title:
        raise ValueError("goal title is required")
    if parent_goal_id:
        parent_row = connection.execute(
            """
            SELECT goal_id
            FROM goals
            WHERE goal_id = ?
              AND project_id = ?
            """,
            (parent_goal_id, resolved_project_id),
        ).fetchone()
        if parent_row is None:
            raise ValueError("parent goal not found in this project")
    ensure_board_action_allowed(connection, actor_id, resolved_project_id, "create_goal", "project", resolved_project_id)
    goal_id = generate_id("goal")
    connection.execute(
        """
        INSERT INTO goals (
            goal_id, project_id, parent_goal_id, title, description, status,
            goal_type, priority, acceptance_criteria_json
        ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
        """,
        (
            goal_id,
            resolved_project_id,
            parent_goal_id,
            cleaned_title,
            (description or "").strip(),
            (goal_type or "initiative").strip() or "initiative",
            int(priority or 75),
            json.dumps([{"type": "artifact_exists"}, {"type": "human_review"}]),
        ),
    )
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, 'create_goal', 'goal', ?, ?)
        """,
        (
            generate_id("audit"),
            resolved_project_id,
            actor_id,
            goal_id,
            json.dumps({"title": cleaned_title, "goal_type": goal_type, "priority": priority, "parent_goal_id": parent_goal_id}),
        ),
    )
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, task_id, action, category, description, details_json, severity
        ) VALUES (?, ?, NULL, 'goal_created', 'planning', ?, ?, 'info')
        """,
        (
            generate_id("act"),
            resolved_project_id,
            "Created goal '{0}'.".format(cleaned_title),
            json.dumps({"goal_id": goal_id}),
        ),
    )
    connection.commit()
    return fetch_goal_planning(connection, resolved_project_id, goal_id=goal_id)["items"][0]


def _existing_goal_tasks(connection, project_id, goal_id, origin):
    rows = connection.execute(
        """
        SELECT task_id, title, description, status, priority, synthesis_origin, synthesis_key
        FROM tasks
        WHERE project_id = ?
          AND goal_id = ?
          AND synthesis_origin = ?
        ORDER BY created_at ASC, task_id ASC
        """,
        (project_id, goal_id, origin),
    ).fetchall()
    return {row["synthesis_key"]: dict(row) for row in rows}


def _ensure_dependency(connection, project_id, source_task_id, target_task_id):
    existing = connection.execute(
        """
        SELECT dependency_id
        FROM task_dependencies
        WHERE project_id = ?
          AND source_task_id = ?
          AND target_task_id = ?
          AND dependency_type = 'blocks'
        LIMIT 1
        """,
        (project_id, source_task_id, target_task_id),
    ).fetchone()
    if existing is not None:
        return
    connection.execute(
        """
        INSERT INTO task_dependencies (dependency_id, project_id, source_task_id, target_task_id, dependency_type)
        VALUES (?, ?, ?, ?, 'blocks')
        """,
        (generate_id("dep"), project_id, source_task_id, target_task_id),
    )


def _reset_goal_dependencies(connection, project_id, goal_id, origin):
    connection.execute(
        """
        DELETE FROM task_dependencies
        WHERE project_id = ?
          AND dependency_type = 'blocks'
          AND source_task_id IN (
              SELECT task_id
              FROM tasks
              WHERE project_id = ?
                AND goal_id = ?
                AND synthesis_origin = ?
          )
          AND target_task_id IN (
              SELECT task_id
              FROM tasks
              WHERE project_id = ?
                AND goal_id = ?
                AND synthesis_origin = ?
          )
        """,
        (
            project_id,
            project_id,
            goal_id,
            origin,
            project_id,
            goal_id,
            origin,
        ),
    )


def synthesize_goal_issues(connection, project_id, goal_id, actor_id, refresh=True):
    resolved_project_id = resolve_project_id(connection, project_id, include_archived=False)
    if resolved_project_id is None:
        raise ValueError("project not found")
    ensure_board_action_allowed(connection, actor_id, resolved_project_id, "synthesize_goal_plan", "goal", goal_id)
    goal_row = connection.execute(
        """
        SELECT goal_id, project_id, title, description, status, goal_type, priority
        FROM goals
        WHERE project_id = ?
          AND goal_id = ?
        """,
        (resolved_project_id, goal_id),
    ).fetchone()
    if goal_row is None:
        raise ValueError("goal not found")
    project_row = resolve_project(connection, resolved_project_id, include_archived=False)
    origin = "goal_plan:{0}".format(goal_id)
    specs = _goal_issue_specs(goal_row, project_row)
    existing = _existing_goal_tasks(connection, resolved_project_id, goal_id, origin)
    created_task_ids = []
    updated_task_ids = []
    ordered_task_ids = []

    for index, spec in enumerate(specs):
        synthesis_key = "{0}:{1}".format(origin, spec["slug"])
        row = existing.get(synthesis_key)
        if row is None:
            task_id = generate_id("task")
            connection.execute(
                """
                INSERT INTO tasks (
                    task_id, project_id, goal_id, title, description, status,
                    priority, assigned_agent_id, acceptance_criteria_json, progress_pct,
                    review_state, synthesis_origin, synthesis_key
                ) VALUES (?, ?, ?, ?, ?, 'planned', ?, NULL, ?, 0, NULL, ?, ?)
                """,
                (
                    task_id,
                    resolved_project_id,
                    goal_id,
                    spec["title"],
                    spec["description"],
                    spec["priority"],
                    json.dumps(spec["acceptance"]),
                    origin,
                    synthesis_key,
                ),
            )
            created_task_ids.append(task_id)
            ordered_task_ids.append(task_id)
            continue
        ordered_task_ids.append(row["task_id"])
        if refresh and row["status"] in {"planned", "ready", "assigned"}:
            connection.execute(
                """
                UPDATE tasks
                SET title = ?,
                    description = ?,
                    priority = ?,
                    acceptance_criteria_json = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE task_id = ?
                """,
                (
                    spec["title"],
                    spec["description"],
                    spec["priority"],
                    json.dumps(spec["acceptance"]),
                    row["task_id"],
                ),
            )
            updated_task_ids.append(row["task_id"])

    cancelled_task_ids = []
    if refresh:
        valid_keys = {"{0}:{1}".format(origin, spec["slug"]) for spec in specs}
        for key, row in existing.items():
            if key in valid_keys:
                continue
            if row["status"] in {"planned", "ready", "assigned"}:
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'cancelled',
                        review_state = 'superseded_goal_plan',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE task_id = ?
                    """,
                    (row["task_id"],),
                )
                cancelled_task_ids.append(row["task_id"])

    _reset_goal_dependencies(connection, resolved_project_id, goal_id, origin)
    for source_task_id, target_task_id in zip(ordered_task_ids, ordered_task_ids[1:]):
        _ensure_dependency(connection, resolved_project_id, source_task_id, target_task_id)

    refresh_ready_tasks(connection, commit=False, project_id=resolved_project_id)
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, 'synthesize_goal_plan', 'goal', ?, ?)
        """,
        (
            generate_id("audit"),
            resolved_project_id,
            actor_id,
            goal_id,
            json.dumps(
                {
                    "created_task_ids": created_task_ids,
                    "updated_task_ids": updated_task_ids,
                    "origin": origin,
                    "refresh": bool(refresh),
                }
            ),
        ),
    )
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, task_id, action, category, description, details_json, severity
        ) VALUES (?, ?, NULL, 'goal_plan_synthesized', 'planning', ?, ?, 'info')
        """,
        (
            generate_id("act"),
            resolved_project_id,
            "Synthesized goal plan for '{0}'.".format(goal_row["title"]),
            json.dumps(
                {
                    "goal_id": goal_id,
                    "created_count": len(created_task_ids),
                    "updated_count": len(updated_task_ids),
                }
            ),
        ),
    )
    connection.commit()
    return {
        "project_id": resolved_project_id,
        "goal_id": goal_id,
        "refreshed": bool(refresh),
        "created_count": len(created_task_ids),
        "updated_count": len(updated_task_ids),
        "cancelled_count": len(cancelled_task_ids),
        "task_count": len(ordered_task_ids),
        "task_ids": ordered_task_ids,
        "created_task_ids": created_task_ids,
        "updated_task_ids": updated_task_ids,
        "cancelled_task_ids": cancelled_task_ids,
    }


def fetch_goal_planning(connection, project_id=None, goal_id=None):
    resolved_project_id = resolve_project_id(connection, project_id, include_archived=False)
    if resolved_project_id is None:
        raise ValueError("project not found")
    project_row = resolve_project(connection, resolved_project_id, include_archived=False)
    issue_keys = _issue_key_lookup(connection, resolved_project_id)
    params = [resolved_project_id]
    where_clause = "WHERE goals.project_id = ?"
    if goal_id:
        where_clause += " AND goals.goal_id = ?"
        params.append(goal_id)
    rows = connection.execute(
        """
        SELECT
            goals.goal_id,
            goals.parent_goal_id,
            goals.title,
            goals.description,
            goals.status,
            goals.goal_type,
            goals.priority,
            goals.created_at,
            goals.updated_at,
            SUM(CASE WHEN tasks.status = 'planned' THEN 1 ELSE 0 END) AS planned_tasks,
            SUM(CASE WHEN tasks.status = 'ready' THEN 1 ELSE 0 END) AS ready_tasks,
            SUM(CASE WHEN tasks.status = 'assigned' THEN 1 ELSE 0 END) AS assigned_tasks,
            SUM(CASE WHEN tasks.status = 'in_progress' THEN 1 ELSE 0 END) AS active_tasks,
            SUM(CASE WHEN tasks.status = 'review' THEN 1 ELSE 0 END) AS review_tasks,
            SUM(CASE WHEN tasks.status = 'blocked' THEN 1 ELSE 0 END) AS blocked_tasks,
            SUM(CASE WHEN tasks.status = 'done' THEN 1 ELSE 0 END) AS done_tasks,
            SUM(CASE WHEN tasks.synthesis_origin = 'goal_plan:' || goals.goal_id THEN 1 ELSE 0 END) AS synthesized_tasks
        FROM goals
        LEFT JOIN tasks ON tasks.goal_id = goals.goal_id
        {where_clause}
        GROUP BY goals.goal_id
        ORDER BY goals.priority DESC, goals.created_at ASC
        """.format(where_clause=where_clause),
        tuple(params),
    ).fetchall()
    goals = []
    for row in rows:
        synthesized_tasks = row["synthesized_tasks"] or 0
        total_open = sum(
            row[key] or 0
            for key in ("planned_tasks", "ready_tasks", "assigned_tasks", "active_tasks", "review_tasks", "blocked_tasks")
        )
        plan = (
            _build_goal_plan_explainability(
                connection,
                resolved_project_id,
                row,
                project_row,
                issue_keys=issue_keys,
            )
            if synthesized_tasks
            else None
        )
        goals.append(
            {
                "goal_id": row["goal_id"],
                "parent_goal_id": row["parent_goal_id"],
                "title": row["title"],
                "description": row["description"],
                "status": row["status"],
                "goal_type": row["goal_type"],
                "priority": row["priority"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "task_counts": {
                    "planned": row["planned_tasks"] or 0,
                    "ready": row["ready_tasks"] or 0,
                    "assigned": row["assigned_tasks"] or 0,
                    "in_progress": row["active_tasks"] or 0,
                    "review": row["review_tasks"] or 0,
                    "blocked": row["blocked_tasks"] or 0,
                    "done": row["done_tasks"] or 0,
                },
                "synthesized_tasks": synthesized_tasks,
                "supports_synthesis": row["status"] in {"proposed", "approved", "active", "blocked"},
                "next_step": (
                    "Synthesize issues from this goal."
                    if synthesized_tasks == 0
                    else "Refresh or inspect the synthesized issue plan."
                ),
                "open_issue_count": total_open,
                "plan": plan,
            }
        )
    return {
        "project_id": resolved_project_id,
        "goals": goals,
        "items": goals,
        "summary": {
            "total_goals": len(goals),
            "active_goals": len([goal for goal in goals if goal["status"] in {"approved", "active"}]),
            "synthesized_goals": len([goal for goal in goals if goal["synthesized_tasks"] > 0]),
            "open_issue_count": sum(goal["open_issue_count"] for goal in goals),
            "synthesized_tasks": sum(goal["synthesized_tasks"] for goal in goals),
        },
    }
