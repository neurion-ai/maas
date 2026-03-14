"""Operator steering actions for the board."""

import json

from maas.ids import generate_id
from maas.services.security import (
    TASK_EXECUTION_CAPABILITIES,
    ensure_board_action_allowed,
    grant_task_capabilities,
    revoke_task_capabilities,
)

RECOVERABLE_FAILURE_REVIEW_STATES = ("session_failed", "stale_session")


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


def _activity(connection, project_id, agent_id, task_id, action, description, severity="info"):
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, agent_id, task_id, action, category, description, severity
        ) VALUES (?, ?, ?, ?, ?, 'steering', ?, ?)
        """,
        (generate_id("act"), project_id, agent_id, task_id, action, description, severity),
    )


def review_task(connection, task_id, actor_id, decision):
    task = connection.execute(
        """
        SELECT task_id, project_id, assigned_agent_id, status
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if task is None:
        raise ValueError("Task not found")
    ensure_board_action_allowed(connection, actor_id, task["project_id"], "review_task", "task", task_id)
    if task["status"] != "review":
        raise ValueError("Task is not in review")
    if decision not in ("approve", "reject"):
        raise ValueError("Unsupported review decision")

    if decision == "approve":
        connection.execute(
            """
            UPDATE tasks
            SET status = 'done', review_state = 'approved', updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ?
            """,
            (task_id,),
        )
        description = "Review approved; task marked done."
    else:
        connection.execute(
            """
            UPDATE tasks
            SET status = 'planned',
                review_state = 'changes_requested',
                updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ?
            """,
            (task_id,),
        )
        description = "Review rejected; task returned to the assignable queue."

    _audit(
        connection,
        task["project_id"],
        actor_id,
        "review_task",
        "task",
        task_id,
        {"decision": decision},
    )
    _activity(connection, task["project_id"], task["assigned_agent_id"], task_id, "review_decision", description)
    connection.commit()
    return {"task_id": task_id, "decision": decision}


def halt_task(connection, task_id, actor_id):
    task = connection.execute(
        """
        SELECT task_id, project_id, assigned_agent_id, status
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if task is None:
        raise ValueError("Task not found")
    ensure_board_action_allowed(connection, actor_id, task["project_id"], "halt_task", "task", task_id)
    if task["status"] in ("done", "cancelled"):
        raise ValueError("Task cannot be halted from status {0}".format(task["status"]))

    connection.execute(
        """
        UPDATE tasks
        SET status = 'cancelled', review_state = 'halted_by_operator', updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ?
        """,
        (task_id,),
    )
    connection.execute(
        """
        UPDATE sessions
        SET status = 'cancelled', status_message = 'Halted by operator', ended_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ? AND status = 'active'
        """,
        (task_id,),
    )
    if task["assigned_agent_id"]:
        revoke_task_capabilities(
            connection,
            task["project_id"],
            task_id,
            agent_id=task["assigned_agent_id"],
            reason="task_halted",
            revoked_by=actor_id,
        )
        connection.execute(
            """
            UPDATE agents
            SET status = CASE WHEN status = 'paused' THEN 'paused' ELSE 'idle' END,
                current_task_id = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE agent_id = ? AND current_task_id = ?
            """,
            (task["assigned_agent_id"], task_id),
        )

    _audit(
        connection,
        task["project_id"],
        actor_id,
        "halt_task",
        "task",
        task_id,
        {"previous_status": task["status"]},
    )
    _activity(
        connection,
        task["project_id"],
        task["assigned_agent_id"],
        task_id,
        "halted",
        "Task halted by operator.",
        severity="warning",
    )
    connection.commit()
    return {"task_id": task_id, "status": "cancelled"}


def recover_task(connection, task_id, actor_id):
    task = connection.execute(
        """
        SELECT task_id, project_id, assigned_agent_id, status, review_state
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if task is None:
        raise ValueError("Task not found")
    ensure_board_action_allowed(connection, actor_id, task["project_id"], "recover_task", "task", task_id)
    if task["status"] != "blocked":
        raise ValueError("Only blocked tasks can be recovered")
    if task["review_state"] not in RECOVERABLE_FAILURE_REVIEW_STATES:
        raise ValueError("Task is not blocked by a recoverable failure")

    if task["assigned_agent_id"]:
        revoke_task_capabilities(
            connection,
            task["project_id"],
            task_id,
            agent_id=task["assigned_agent_id"],
            reason="task_recovered",
            revoked_by=actor_id,
        )

    connection.execute(
        """
        UPDATE tasks
        SET status = 'planned',
            assigned_agent_id = NULL,
            progress_pct = 0,
            review_state = NULL,
            last_heartbeat_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ?
        """,
        (task_id,),
    )
    _audit(
        connection,
        task["project_id"],
        actor_id,
        "recover_task",
        "task",
        task_id,
        {
            "previous_status": task["status"],
            "previous_review_state": task["review_state"],
            "previous_agent_id": task["assigned_agent_id"],
        },
    )
    _activity(
        connection,
        task["project_id"],
        task["assigned_agent_id"],
        task_id,
        "recovered",
        "Task returned to the planning queue after failure recovery.",
    )
    connection.commit()
    return {"task_id": task_id, "status": "planned"}


def reprioritize_task(connection, task_id, actor_id, priority):
    task = connection.execute(
        "SELECT task_id, project_id, assigned_agent_id FROM tasks WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    if task is None:
        raise ValueError("Task not found")
    ensure_board_action_allowed(connection, actor_id, task["project_id"], "reprioritize_task", "task", task_id)
    connection.execute(
        "UPDATE tasks SET priority = ?, updated_at = CURRENT_TIMESTAMP WHERE task_id = ?",
        (priority, task_id),
    )
    _audit(
        connection,
        task["project_id"],
        actor_id,
        "reprioritize_task",
        "task",
        task_id,
        {"priority": priority},
    )
    _activity(
        connection,
        task["project_id"],
        task["assigned_agent_id"],
        task_id,
        "reprioritized",
        "Task priority updated to {0}.".format(priority),
    )
    connection.commit()
    return {"task_id": task_id, "priority": priority}


def reassign_task(connection, task_id, actor_id, agent_id):
    task = connection.execute(
        "SELECT task_id, project_id, status, assigned_agent_id FROM tasks WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    if task is None:
        raise ValueError("Task not found")
    ensure_board_action_allowed(connection, actor_id, task["project_id"], "reassign_task", "task", task_id)
    if task["status"] == "in_progress":
        raise ValueError("In-progress tasks cannot be reassigned")
    agent = connection.execute(
        "SELECT agent_id FROM agents WHERE agent_id = ? AND project_id = ?",
        (agent_id, task["project_id"]),
    ).fetchone()
    if agent is None:
        raise ValueError("Agent not found")
    connection.execute(
        """
        UPDATE tasks
        SET assigned_agent_id = ?, status = CASE WHEN status = 'planned' THEN 'assigned' ELSE status END,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ?
        """,
        (agent_id, task_id),
    )
    if task["assigned_agent_id"] and task["assigned_agent_id"] != agent_id:
        revoke_task_capabilities(
            connection,
            task["project_id"],
            task_id,
            agent_id=task["assigned_agent_id"],
            reason="task_reassigned",
            revoked_by=actor_id,
        )
    grant_task_capabilities(
        connection,
        task["project_id"],
        task_id,
        agent_id,
        TASK_EXECUTION_CAPABILITIES,
        granted_by=actor_id,
    )
    _audit(
        connection,
        task["project_id"],
        actor_id,
        "reassign_task",
        "task",
        task_id,
        {"agent_id": agent_id},
    )
    _activity(
        connection,
        task["project_id"],
        agent_id,
        task_id,
        "reassigned",
        "Task reassigned to {0}.".format(agent_id),
    )
    connection.commit()
    return {"task_id": task_id, "agent_id": agent_id}


def pause_agent(connection, agent_id, actor_id):
    agent = connection.execute(
        "SELECT agent_id, project_id, current_task_id FROM agents WHERE agent_id = ?",
        (agent_id,),
    ).fetchone()
    if agent is None:
        raise ValueError("Agent not found")
    ensure_board_action_allowed(connection, actor_id, agent["project_id"], "pause_agent", "agent", agent_id)
    connection.execute(
        """
        UPDATE agents
        SET status = 'paused', updated_at = CURRENT_TIMESTAMP
        WHERE agent_id = ?
        """,
        (agent_id,),
    )
    if agent["current_task_id"]:
        connection.execute(
            """
            UPDATE tasks
            SET status = 'blocked', review_state = 'paused_by_operator', updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ? AND status = 'in_progress'
            """,
            (agent["current_task_id"],),
        )
    _audit(
        connection,
        agent["project_id"],
        actor_id,
        "pause_agent",
        "agent",
        agent_id,
        {"current_task_id": agent["current_task_id"]},
    )
    _activity(
        connection,
        agent["project_id"],
        agent_id,
        agent["current_task_id"],
        "paused",
        "Agent paused by operator.",
        severity="warning",
    )
    connection.commit()
    return {"agent_id": agent_id, "status": "paused"}


def resume_agent(connection, agent_id, actor_id):
    agent = connection.execute(
        "SELECT agent_id, project_id, current_task_id FROM agents WHERE agent_id = ?",
        (agent_id,),
    ).fetchone()
    if agent is None:
        raise ValueError("Agent not found")
    ensure_board_action_allowed(connection, actor_id, agent["project_id"], "resume_agent", "agent", agent_id)
    connection.execute(
        """
        UPDATE agents
        SET status = CASE WHEN current_task_id IS NULL THEN 'idle' ELSE 'running' END,
            updated_at = CURRENT_TIMESTAMP
        WHERE agent_id = ?
        """,
        (agent_id,),
    )
    if agent["current_task_id"]:
        connection.execute(
            """
            UPDATE tasks
            SET status = 'in_progress', review_state = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ? AND status = 'blocked'
            """,
            (agent["current_task_id"],),
        )
    _audit(
        connection,
        agent["project_id"],
        actor_id,
        "resume_agent",
        "agent",
        agent_id,
        {"current_task_id": agent["current_task_id"]},
    )
    _activity(
        connection,
        agent["project_id"],
        agent_id,
        agent["current_task_id"],
        "resumed",
        "Agent resumed by operator.",
    )
    connection.commit()
    return {"agent_id": agent_id, "status": "running" if agent["current_task_id"] else "idle"}


def recover_agent(connection, agent_id, actor_id):
    agent = connection.execute(
        """
        SELECT agent_id, project_id, status, current_task_id
        FROM agents
        WHERE agent_id = ?
        """,
        (agent_id,),
    ).fetchone()
    if agent is None:
        raise ValueError("Agent not found")
    ensure_board_action_allowed(connection, actor_id, agent["project_id"], "recover_agent", "agent", agent_id)
    if agent["status"] != "error":
        raise ValueError("Only error agents can be recovered")
    if agent["current_task_id"] is not None:
        raise ValueError("Agent cannot be recovered while still attached to a task")

    active_session = connection.execute(
        """
        SELECT session_id
        FROM sessions
        WHERE agent_id = ? AND status = 'active'
        LIMIT 1
        """,
        (agent_id,),
    ).fetchone()
    if active_session is not None:
        raise ValueError("Agent cannot be recovered while an active session exists")

    connection.execute(
        """
        UPDATE agents
        SET status = 'idle', updated_at = CURRENT_TIMESTAMP
        WHERE agent_id = ?
        """,
        (agent_id,),
    )
    _audit(
        connection,
        agent["project_id"],
        actor_id,
        "recover_agent",
        "agent",
        agent_id,
        {"previous_status": agent["status"]},
    )
    _activity(
        connection,
        agent["project_id"],
        agent_id,
        None,
        "agent_recovered",
        "Agent recovered from error state.",
    )
    connection.commit()
    return {"agent_id": agent_id, "status": "idle"}
