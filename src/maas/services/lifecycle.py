"""Lifecycle service methods used by adapters and API surfaces."""

import json

from maas.ids import generate_id
from maas.services.failure_memory import maybe_raise_repeated_failure_alert, record_failure
from maas.services.security import ensure_task_capability_allowed, revoke_task_capabilities


def start_session(connection, project_id, agent_id, task_id, provider_type, status_message):
    agent_row = connection.execute(
        """
        SELECT agent_id, project_id, status, current_task_id
        FROM agents
        WHERE agent_id = ?
        """,
        (agent_id,),
    ).fetchone()
    if agent_row is None or agent_row["project_id"] != project_id:
        raise ValueError("Agent not found")
    if agent_row["current_task_id"] and agent_row["current_task_id"] != task_id:
        raise ValueError("Agent already has an active task")

    task_row = connection.execute(
        """
        SELECT task_id, assigned_agent_id, status
        FROM tasks
        WHERE task_id = ? AND project_id = ?
        """,
        (task_id, project_id),
    ).fetchone()
    if task_row is None:
        raise ValueError("Task not found")
    if task_row["status"] not in ("planned", "ready", "assigned"):
        raise ValueError("Task cannot be started from status {0}".format(task_row["status"]))
    if task_row["assigned_agent_id"] and task_row["assigned_agent_id"] != agent_id:
        raise ValueError("Task is assigned to another agent")
    ensure_task_capability_allowed(connection, project_id, task_id, agent_id, "execute")

    session_id = generate_id("sess")
    connection.execute(
        """
        INSERT INTO sessions (
            session_id, project_id, agent_id, task_id, status, provider_type, progress_pct, status_message
        ) VALUES (?, ?, ?, ?, 'active', ?, 0, ?)
        """,
        (session_id, project_id, agent_id, task_id, provider_type, status_message),
    )
    connection.execute(
        """
        UPDATE agents
        SET status = 'running', current_task_id = ?, last_heartbeat_at = CURRENT_TIMESTAMP
        WHERE agent_id = ?
        """,
        (task_id, agent_id),
    )
    connection.execute(
        """
        UPDATE tasks
        SET status = 'in_progress',
            assigned_agent_id = ?,
            last_heartbeat_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ? AND status IN ('planned', 'ready', 'assigned')
        """,
        (agent_id, task_id),
    )
    connection.commit()
    return session_id


def heartbeat(connection, session_id, progress_pct, status_message):
    row = connection.execute(
        "SELECT project_id, agent_id, task_id, status FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        raise ValueError("Session not found")
    if row["status"] != "active":
        raise ValueError("Session is not active")
    ensure_task_capability_allowed(
        connection,
        row["project_id"],
        row["task_id"],
        row["agent_id"],
        "heartbeat",
        session_id=session_id,
    )
    connection.execute(
        """
        UPDATE sessions
        SET progress_pct = ?, status_message = ?, last_heartbeat_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE session_id = ?
        """,
        (progress_pct, status_message, session_id),
    )
    if row:
        connection.execute(
            "UPDATE agents SET last_heartbeat_at = CURRENT_TIMESTAMP WHERE agent_id = ?",
            (row["agent_id"],),
        )
        connection.execute(
            """
            UPDATE tasks
            SET progress_pct = ?, last_heartbeat_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ?
            """,
            (progress_pct, row["task_id"]),
        )
    connection.commit()


def log_activity(connection, project_id, agent_id, task_id, action, category, description, severity="info", details=None):
    if task_id:
        ensure_task_capability_allowed(connection, project_id, task_id, agent_id, "activity_write")
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            generate_id("act"),
            project_id,
            agent_id,
            task_id,
            action,
            category,
            description,
            json.dumps(details or {}),
            severity,
        ),
    )
    connection.commit()


def produce_artifact(connection, project_id, session_id, task_id, artifact_type, path, metadata=None):
    session_row = connection.execute(
        """
        SELECT project_id, agent_id, task_id, status
        FROM sessions
        WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()
    if session_row is None:
        raise ValueError("Session not found")
    if session_row["status"] != "active":
        raise ValueError("Session is not active")
    if session_row["project_id"] != project_id or session_row["task_id"] != task_id:
        raise ValueError("Artifact does not match session context")
    ensure_task_capability_allowed(
        connection,
        project_id,
        task_id,
        session_row["agent_id"],
        "artifact_write",
        session_id=session_id,
    )
    artifact_id = generate_id("art")
    connection.execute(
        """
        INSERT INTO artifacts (
            artifact_id, project_id, task_id, session_id, artifact_type, path, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (artifact_id, project_id, task_id, session_id, artifact_type, path, json.dumps(metadata or {})),
    )
    connection.commit()
    return artifact_id


def end_session(connection, session_id, outcome, summary):
    row = connection.execute(
        "SELECT project_id, agent_id, task_id, status FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        raise ValueError("Session not found")
    if row["status"] != "active":
        raise ValueError("Session is not active")
    ensure_task_capability_allowed(
        connection,
        row["project_id"],
        row["task_id"],
        row["agent_id"],
        "complete_session",
        session_id=session_id,
    )
    connection.execute(
        """
        UPDATE sessions
        SET status = ?, status_message = ?, ended_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE session_id = ?
        """,
        (outcome, summary, session_id),
    )
    revoke_task_capabilities(
        connection,
        row["project_id"],
        row["task_id"],
        agent_id=row["agent_id"],
        reason="session_{0}".format(outcome),
        revoked_by=row["agent_id"],
    )
    connection.execute(
        """
        UPDATE agents
        SET status = 'idle', current_task_id = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE agent_id = ?
        """,
        (row["agent_id"],),
    )
    if outcome == "completed":
        connection.execute(
            """
            UPDATE tasks
            SET status = 'review', updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ? AND status = 'in_progress'
            """,
            (row["task_id"],),
        )
    elif outcome == "failed":
        connection.execute(
            """
            UPDATE tasks
            SET status = 'blocked', review_state = 'session_failed', updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ? AND status = 'in_progress'
            """,
            (row["task_id"],),
        )
        record_failure(
            connection,
            row["project_id"],
            "session_failed",
            summary or "Session failed",
            task_id=row["task_id"],
            session_id=session_id,
            agent_id=row["agent_id"],
            details={"outcome": outcome},
        )
        connection.execute(
            """
            INSERT INTO activity_log (
                activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
            ) VALUES (?, ?, ?, ?, 'session_failed', 'runtime', ?, ?, 'error')
            """,
            (
                generate_id("act"),
                row["project_id"],
                row["agent_id"],
                row["task_id"],
                "Session failed for task {0}.".format(row["task_id"]),
                json.dumps({"session_id": session_id, "summary": summary}),
            ),
        )
        connection.execute(
            """
            INSERT INTO alerts (
                alert_id, project_id, severity, title, description, status
            ) VALUES (?, ?, 'warning', 'Task session failed', ?, 'open')
            """,
            (
                generate_id("alert"),
                row["project_id"],
                "Task {0} failed in session {1}. {2}".format(row["task_id"], session_id, summary or ""),
            ),
        )
        maybe_raise_repeated_failure_alert(connection, row["project_id"], row["task_id"], summary or "Session failed")
    elif outcome == "cancelled":
        record_failure(
            connection,
            row["project_id"],
            "session_cancelled",
            summary or "Session cancelled",
            task_id=row["task_id"],
            session_id=session_id,
            agent_id=row["agent_id"],
            details={"outcome": outcome},
        )
    connection.commit()
