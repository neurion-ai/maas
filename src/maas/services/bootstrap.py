"""Greenfield project bootstrap and seed data."""

import json
import os

from maas.config import build_default_project_config, save_project_config
from maas.db import connect, run_migrations
from maas.ids import generate_id
from maas.paths import ProjectPaths
from maas.services.security import TASK_EXECUTION_CAPABILITIES, grant_task_capabilities


def default_project_name(project_root):
    return os.path.basename(os.path.abspath(project_root)) or "maas-project"


def build_understanding_markdown(config):
    project = config["project"]
    return """# Project Understanding

## Summary

- Name: {name}
- Type: {project_type}
- Description: {description}
- Operating Model: board-first multi-agent execution

## Initial Assumptions

- This project is being bootstrapped in greenfield mode.
- The Kanban board is the primary human operating surface.
- Goals remain available as a separate hierarchy, but daily work flows through tasks.
- Initial agent roles are allocator, researcher, builder, and reviewer.

## Initial Plan Templates

- Research Investigation
- Feature Development
- Bug Fix
""".format(
        name=project["name"],
        project_type=project["type"],
        description=project["description"],
    )


def seed_project(connection, config):
    project_id = generate_id("proj")
    project = config["project"]
    connection.execute(
        """
        INSERT INTO projects (project_id, name, description, project_type, config_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            project_id,
            project["name"],
            project["description"],
            project["type"],
            json.dumps(config),
        ),
    )

    agents = []
    for role in config["agent_roles"]:
        agent_id = "agent_{role}".format(role=role["role"])
        agents.append((agent_id, role["role"], role["description"]))
        connection.execute(
            """
            INSERT INTO agents (agent_id, project_id, role, display_name, status, permissions_json)
            VALUES (?, ?, ?, ?, 'idle', ?)
            """,
            (agent_id, project_id, role["role"], role["role"].replace("_", " ").title(), json.dumps(role["permissions"])),
        )

    goal_specs = [
        ("Strategic", "Launch the first usable MAAS workspace", "active", 95),
        ("Tactical", "Stand up board-first orchestration services", "active", 90),
    ]
    goal_ids = []
    parent_goal_id = None
    for title_prefix, title, status, priority in goal_specs:
        goal_id = generate_id("goal")
        goal_ids.append(goal_id)
        connection.execute(
            """
            INSERT INTO goals (
                goal_id, project_id, parent_goal_id, title, description, status,
                goal_type, priority, acceptance_criteria_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                goal_id,
                project_id,
                parent_goal_id,
                title,
                "{0} goal for the initial MAAS bootstrap.".format(title_prefix),
                status,
                title_prefix.lower(),
                priority,
                json.dumps([{"type": "artifact_exists"}, {"type": "human_review"}]),
            ),
        )
        parent_goal_id = goal_id

    allocator_id = "agent_allocator"
    builder_id = "agent_builder"
    reviewer_id = "agent_reviewer"
    researcher_id = "agent_researcher"

    task_specs = [
        ("planned", "Define project workspace contracts", researcher_id, 80, "Design the stable `project.yaml` and `.maas/` workspace contracts."),
        ("ready", "Wire the scheduler and board read model", allocator_id, 88, "Prepare the task graph and board grouping logic."),
        ("in_progress", "Implement FastAPI board endpoint", builder_id, 92, "Expose grouped Kanban columns through `/api/board`."),
        ("review", "Validate seeded lifecycle semantics", reviewer_id, 74, "Review status transitions and acceptance-gate handling."),
        ("blocked", "Integrate provider adapters", builder_id, 60, "Waiting on runtime adapter contracts and lifecycle wrapper decisions."),
        ("done", "Bootstrap migration runner", allocator_id, 99, "Migration runner is in place and ready for use."),
    ]

    task_ids = []
    for status, title, agent_id, priority, description in task_specs:
        task_id = generate_id("task")
        task_ids.append(task_id)
        heartbeat = "CURRENT_TIMESTAMP" if status == "in_progress" else None
        connection.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, goal_id, title, description, status,
                priority, assigned_agent_id, acceptance_criteria_json,
                progress_pct, review_state, last_heartbeat_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {heartbeat})
            """.format(heartbeat=heartbeat or "?"),
            (
                task_id,
                project_id,
                goal_ids[-1],
                title,
                description,
                status,
                priority,
                agent_id,
                json.dumps([{"type": "artifact_exists"}]),
                55 if status == "in_progress" else 0,
                "awaiting_review" if status == "review" else None,
            )
            if heartbeat
            else (
                task_id,
                project_id,
                goal_ids[-1],
                title,
                description,
                status,
                priority,
                agent_id,
                json.dumps([{"type": "artifact_exists"}]),
                55 if status == "in_progress" else 0,
                "awaiting_review" if status == "review" else None,
                None,
            ),
            )

        if agent_id and status in ("planned", "ready", "assigned", "in_progress", "blocked"):
            grant_task_capabilities(
                connection,
                project_id,
                task_id,
                agent_id,
                TASK_EXECUTION_CAPABILITIES,
                granted_by="system_bootstrap",
            )

    connection.execute(
        """
        INSERT INTO task_dependencies (dependency_id, project_id, source_task_id, target_task_id, dependency_type)
        VALUES (?, ?, ?, ?, 'blocks')
        """,
        (generate_id("dep"), project_id, task_ids[1], task_ids[2]),
    )

    connection.execute(
        """
        INSERT INTO sessions (
            session_id, project_id, agent_id, task_id, status, provider_type, progress_pct, status_message
        ) VALUES (?, ?, ?, ?, 'active', 'python_script', 55, 'Implementing board endpoint')
        """,
        (generate_id("sess"), project_id, builder_id, task_ids[2]),
    )
    connection.execute(
        """
        UPDATE agents
        SET status = 'running', current_task_id = ?, last_heartbeat_at = CURRENT_TIMESTAMP
        WHERE agent_id = ?
        """,
        (task_ids[2], builder_id),
    )

    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, agent_id, task_id, action, category, description, severity
        ) VALUES (?, ?, ?, ?, 'task_started', 'runtime', 'Builder picked up board endpoint work.', 'info')
        """,
        (generate_id("act"), project_id, builder_id, task_ids[2]),
    )
    connection.execute(
        """
        INSERT INTO alerts (
            alert_id, project_id, severity, title, description, status
        ) VALUES (?, ?, 'warning', 'Broader provider integrations pending', 'Simulated adapters and explicit local CLI modes are available, but broader provider coverage is still pending.', 'open')
        """,
        (generate_id("alert"), project_id),
    )
    connection.commit()
    return project_id


def bootstrap_project(project_root, name=None, description=None, project_type=None):
    paths = ProjectPaths(project_root)
    paths.ensure_directories()
    config = build_default_project_config(
        name=name or default_project_name(project_root),
        description=description or "Board-first MAAS workspace",
        project_type=project_type or "custom",
    )
    save_project_config(paths.project_config, config)
    with open(paths.understanding_path, "w", encoding="utf-8") as handle:
        handle.write(build_understanding_markdown(config))

    run_migrations(project_root, paths)
    connection = connect(paths)
    project_id = seed_project(connection, config)
    connection.close()
    return {"paths": paths, "config": config, "project_id": project_id}
