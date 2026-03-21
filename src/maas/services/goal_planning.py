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
            },
            {
                "slug": "collect-baseline-context",
                "title": "Collect baseline context for {0}".format(goal_noun),
                "description": "Inspect the current repository, prior memory, and relevant artifacts before deep work begins.",
                "priority": max(high - 4, 1),
                "acceptance": [{"type": "artifact_exists"}],
            },
            {
                "slug": "run-core-investigation",
                "title": "Run the core investigation for {0}".format(goal_noun),
                "description": "Execute the primary research loop and record evidence-backed findings.",
                "priority": max(high - 8, 1),
                "acceptance": [{"type": "artifact_exists"}],
            },
            {
                "slug": "verify-findings",
                "title": "Verify findings for {0}".format(goal_noun),
                "description": "Validate the research outputs and capture what still looks uncertain or risky.",
                "priority": max(high - 12, 1),
                "acceptance": [{"type": "artifact_exists"}, {"type": "human_review"}],
            },
            {
                "slug": "prepare-delivery-report",
                "title": "Prepare the delivery report for {0}".format(goal_noun),
                "description": "Package the research result into a deliverable summary, artifact bundle, or draft PR narrative.",
                "priority": max(high - 16, 1),
                "acceptance": [{"type": "artifact_exists"}, {"type": "human_review"}],
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
            },
            {
                "slug": "inspect-current-surface",
                "title": "Inspect the current implementation surface for {0}".format(goal_noun),
                "description": "Inspect the repo, existing memory, and current state before implementation starts.",
                "priority": max(high - 4, 1),
                "acceptance": [{"type": "artifact_exists"}],
            },
            {
                "slug": "implement-primary-slice",
                "title": "Implement the primary slice for {0}".format(goal_noun),
                "description": "Complete the highest-value change required to advance this goal and record the output.",
                "priority": max(high - 8, 1),
                "acceptance": [{"type": "artifact_exists"}],
            },
            {
                "slug": "verify-output-and-risk",
                "title": "Verify the output and risk posture for {0}".format(goal_noun),
                "description": "Run verification, collect evidence, and summarize remaining risks or follow-up items.",
                "priority": max(high - 12, 1),
                "acceptance": [{"type": "artifact_exists"}, {"type": "human_review"}],
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
            },
        ]
    return specs


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
