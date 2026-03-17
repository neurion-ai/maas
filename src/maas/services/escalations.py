"""Escalation queue helpers for high-risk steering actions."""

import json

from maas.ids import generate_id
from maas.services.security import ensure_board_action_allowed
from maas.services.steering import halt_task, pause_agent, reassign_task, resume_agent


SUPPORTED_ESCALATION_ACTIONS = {
    "halt_task": {"resource_type": "task"},
    "reassign_task": {"resource_type": "task"},
    "pause_agent": {"resource_type": "agent"},
    "resume_agent": {"resource_type": "agent"},
}


def _ensure_requester_exists(connection, project_id, actor_id):
    row = connection.execute(
        """
        SELECT agent_id
        FROM agents
        WHERE project_id = ? AND agent_id = ?
        """,
        (project_id, actor_id),
    ).fetchone()
    if row is None:
        raise ValueError("Escalation requester not found")
    return row


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


def _activity(connection, project_id, agent_id, action, description, details=None, severity="info", task_id=None):
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
        ) VALUES (?, ?, ?, ?, ?, 'steering', ?, ?, ?)
        """,
        (
            generate_id("act"),
            project_id,
            agent_id,
            task_id,
            action,
            description,
            json.dumps(details or {}),
            severity,
        ),
    )


def _validate_request(action_type, resource_type, payload):
    metadata = SUPPORTED_ESCALATION_ACTIONS.get(action_type)
    if metadata is None:
        raise ValueError("Unsupported escalation action")
    if metadata["resource_type"] != resource_type:
        raise ValueError("Escalation action does not match resource type")
    if action_type == "reassign_task" and not (payload or {}).get("agent_id"):
        raise ValueError("Reassign escalation requires agent_id")


def _ensure_resource_exists(connection, project_id, resource_type, resource_id):
    if resource_type == "task":
        row = connection.execute(
            """
            SELECT task_id
            FROM tasks
            WHERE project_id = ? AND task_id = ?
            """,
            (project_id, resource_id),
        ).fetchone()
        if row is None:
            raise ValueError("Escalation task not found")
        return

    if resource_type == "agent":
        row = connection.execute(
            """
            SELECT agent_id
            FROM agents
            WHERE project_id = ? AND agent_id = ?
            """,
            (project_id, resource_id),
        ).fetchone()
        if row is None:
            raise ValueError("Escalation agent not found")
        return

    raise ValueError("Unsupported escalation resource type")


def _ensure_reassignment_target_exists(connection, project_id, payload):
    agent_id = (payload or {}).get("agent_id")
    if not agent_id:
        return

    row = connection.execute(
        """
        SELECT agent_id
        FROM agents
        WHERE project_id = ? AND agent_id = ?
        """,
        (project_id, agent_id),
    ).fetchone()
    if row is None:
        raise ValueError("Escalation reassignment target not found")


def request_escalation(connection, project_id, actor_id, action_type, resource_type, resource_id, reason, payload=None):
    _ensure_requester_exists(connection, project_id, actor_id)
    payload = payload or {}
    _validate_request(action_type, resource_type, payload)
    _ensure_resource_exists(connection, project_id, resource_type, resource_id)
    if action_type == "reassign_task":
        _ensure_reassignment_target_exists(connection, project_id, payload)

    escalation_id = generate_id("esc")
    connection.execute(
        """
        INSERT INTO escalation_queue (
            escalation_id, project_id, requested_by, action_type, resource_type, resource_id,
            payload_json, reason, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open')
        """,
        (
            escalation_id,
            project_id,
            actor_id,
            action_type,
            resource_type,
            resource_id,
            json.dumps(payload),
            reason or "",
        ),
    )
    _audit(
        connection,
        project_id,
        actor_id,
        "request_escalation",
        resource_type,
        resource_id,
        {"escalation_id": escalation_id, "action_type": action_type, "payload": payload},
    )
    _activity(
        connection,
        project_id,
        actor_id,
        "escalation_requested",
        "Escalation requested for {0}.".format(action_type),
        details={"escalation_id": escalation_id, "resource_id": resource_id},
        severity="warning",
    )
    connection.commit()
    return {"escalation_id": escalation_id, "status": "open"}


def _load_escalation(connection, escalation_id):
    escalation = connection.execute(
        """
        SELECT *
        FROM escalation_queue
        WHERE escalation_id = ?
        """,
        (escalation_id,),
    ).fetchone()
    if escalation is None:
        raise ValueError("Escalation not found")
    return escalation


def _execute_escalation_action(connection, escalation, actor_id):
    payload = json.loads(escalation["payload_json"] or "{}")
    action_type = escalation["action_type"]
    if action_type == "halt_task":
        return halt_task(connection, escalation["resource_id"], actor_id)
    if action_type == "reassign_task":
        return reassign_task(connection, escalation["resource_id"], actor_id, payload["agent_id"])
    if action_type == "pause_agent":
        return pause_agent(connection, escalation["resource_id"], actor_id)
    if action_type == "resume_agent":
        return resume_agent(connection, escalation["resource_id"], actor_id)
    raise ValueError("Unsupported escalation action")


def approve_escalation(connection, escalation_id, actor_id, resolution_note=""):
    escalation = _load_escalation(connection, escalation_id)
    ensure_board_action_allowed(
        connection,
        actor_id,
        escalation["project_id"],
        "approve_escalation",
        "escalation",
        escalation_id,
    )
    if escalation["status"] != "open":
        raise ValueError("Escalation is not open")

    result = _execute_escalation_action(connection, escalation, actor_id)
    connection.execute(
        """
        UPDATE escalation_queue
        SET status = 'approved',
            resolved_by = ?,
            resolution_note = ?,
            resolved_at = CURRENT_TIMESTAMP
        WHERE escalation_id = ?
        """,
        (actor_id, resolution_note, escalation_id),
    )
    _audit(
        connection,
        escalation["project_id"],
        actor_id,
        "approve_escalation",
        escalation["resource_type"],
        escalation["resource_id"],
        {"escalation_id": escalation_id, "resolution_note": resolution_note},
    )
    _activity(
        connection,
        escalation["project_id"],
        actor_id,
        "escalation_approved",
        "Escalation approved for {0}.".format(escalation["action_type"]),
        details={"escalation_id": escalation_id},
        severity="info",
    )
    connection.commit()
    return {"escalation_id": escalation_id, "status": "approved", "result": result}


def reject_escalation(connection, escalation_id, actor_id, resolution_note=""):
    escalation = _load_escalation(connection, escalation_id)
    ensure_board_action_allowed(
        connection,
        actor_id,
        escalation["project_id"],
        "reject_escalation",
        "escalation",
        escalation_id,
    )
    if escalation["status"] != "open":
        raise ValueError("Escalation is not open")

    connection.execute(
        """
        UPDATE escalation_queue
        SET status = 'rejected',
            resolved_by = ?,
            resolution_note = ?,
            resolved_at = CURRENT_TIMESTAMP
        WHERE escalation_id = ?
        """,
        (actor_id, resolution_note, escalation_id),
    )
    _audit(
        connection,
        escalation["project_id"],
        actor_id,
        "reject_escalation",
        escalation["resource_type"],
        escalation["resource_id"],
        {"escalation_id": escalation_id, "resolution_note": resolution_note},
    )
    _activity(
        connection,
        escalation["project_id"],
        actor_id,
        "escalation_rejected",
        "Escalation rejected for {0}.".format(escalation["action_type"]),
        details={"escalation_id": escalation_id},
        severity="warning",
    )
    connection.commit()
    return {"escalation_id": escalation_id, "status": "rejected"}


def count_open_escalations(connection, project_id=None):
    query = "SELECT COUNT(*) AS count FROM escalation_queue WHERE status = 'open'"
    params = ()
    if project_id is not None:
        query += " AND project_id = ?"
        params = (project_id,)
    return connection.execute(query, params).fetchone()["count"]


def fetch_escalations(connection, project_id=None):
    query = """
        SELECT
            escalation_queue.escalation_id,
            escalation_queue.project_id,
            escalation_queue.requested_by,
            escalation_queue.action_type,
            escalation_queue.resource_type,
            escalation_queue.resource_id,
            escalation_queue.payload_json,
            escalation_queue.reason,
            escalation_queue.status,
            escalation_queue.resolved_by,
            escalation_queue.resolution_note,
            escalation_queue.resolved_at,
            escalation_queue.created_at,
            requester.display_name AS requester_name,
            resolver.display_name AS resolver_name
        FROM escalation_queue
        LEFT JOIN agents requester ON requester.agent_id = escalation_queue.requested_by
        LEFT JOIN agents resolver ON resolver.agent_id = escalation_queue.resolved_by
    """
    params = []
    if project_id is not None:
        query += "\nWHERE escalation_queue.project_id = ?"
        params.append(project_id)
    query += """
        ORDER BY
            CASE escalation_queue.status WHEN 'open' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END,
            escalation_queue.created_at DESC
    """
    rows = connection.execute(query, tuple(params)).fetchall()
    grouped = {"open": [], "approved": [], "rejected": []}
    for row in rows:
        escalation = dict(row)
        grouped.setdefault(escalation["status"], []).append(escalation)

    return {
        "escalations": [dict(row) for row in rows],
        "grouped": grouped,
        "summary": {
            "open": count_open_escalations(connection, project_id=project_id),
            "approved": len(grouped.get("approved", [])),
            "rejected": len(grouped.get("rejected", [])),
        },
    }
