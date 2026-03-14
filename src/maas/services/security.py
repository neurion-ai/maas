"""Permission helpers for steering and other sensitive MAAS actions."""

import json

from maas.ids import generate_id


TASK_EXECUTION_CAPABILITIES = (
    "execute",
    "heartbeat",
    "activity_write",
    "artifact_write",
    "complete_session",
)


def _audit_denial(connection, project_id, actor_id, action_type, resource_type, resource_id, reason):
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
            "permission_denied",
            resource_type,
            resource_id,
            json.dumps({"action_type": action_type, "reason": reason}),
        ),
    )


def ensure_board_action_allowed(connection, actor_id, project_id, action_type, resource_type, resource_id):
    actor = connection.execute(
        """
        SELECT agent_id, role, permissions_json
        FROM agents
        WHERE agent_id = ? AND project_id = ?
        """,
        (actor_id, project_id),
    ).fetchone()
    if actor is None:
        _audit_denial(connection, project_id, actor_id, action_type, resource_type, resource_id, "actor_not_found")
        connection.commit()
        raise PermissionError("Actor is not allowed to perform board actions")

    permissions = json.loads(actor["permissions_json"] or "{}")
    if not permissions.get("board_actions"):
        _audit_denial(connection, project_id, actor_id, action_type, resource_type, resource_id, "board_actions_denied")
        connection.commit()
        raise PermissionError("Actor is not allowed to perform board actions")

    return {"actor_id": actor_id, "role": actor["role"]}


def _validate_capability(capability):
    if capability not in TASK_EXECUTION_CAPABILITIES:
        raise ValueError("Unsupported task capability: {0}".format(capability))


def grant_task_capabilities(connection, project_id, task_id, agent_id, capabilities, granted_by):
    granted = []
    for capability in capabilities:
        _validate_capability(capability)
        existing = connection.execute(
            """
            SELECT grant_id
            FROM task_capability_grants
            WHERE project_id = ?
              AND task_id = ?
              AND agent_id = ?
              AND capability = ?
              AND revoked_at IS NULL
            """,
            (project_id, task_id, agent_id, capability),
        ).fetchone()
        if existing is not None:
            continue
        connection.execute(
            """
            INSERT INTO task_capability_grants (
                grant_id, project_id, task_id, agent_id, capability, granted_by
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                generate_id("grant"),
                project_id,
                task_id,
                agent_id,
                capability,
                granted_by,
            ),
        )
        connection.execute(
            """
            INSERT INTO audit_trail (
                audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
            ) VALUES (?, ?, ?, 'grant_task_capability', 'task', ?, ?)
            """,
            (
                generate_id("audit"),
                project_id,
                granted_by,
                task_id,
                json.dumps({"agent_id": agent_id, "capability": capability}),
            ),
        )
        granted.append(capability)
    return granted


def revoke_task_capabilities(connection, project_id, task_id, agent_id=None, reason="revoked", revoked_by="system"):
    params = [project_id, task_id]
    query = """
        SELECT grant_id, agent_id, capability
        FROM task_capability_grants
        WHERE project_id = ?
          AND task_id = ?
          AND revoked_at IS NULL
    """
    if agent_id is not None:
        query += " AND agent_id = ?"
        params.append(agent_id)

    active_rows = connection.execute(query, tuple(params)).fetchall()
    revoked = []
    for row in active_rows:
        connection.execute(
            """
            UPDATE task_capability_grants
            SET revoked_at = CURRENT_TIMESTAMP, revoked_reason = ?
            WHERE grant_id = ?
            """,
            (reason, row["grant_id"]),
        )
        connection.execute(
            """
            INSERT INTO audit_trail (
                audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
            ) VALUES (?, ?, ?, 'revoke_task_capability', 'task', ?, ?)
            """,
            (
                generate_id("audit"),
                project_id,
                revoked_by,
                task_id,
                json.dumps(
                    {
                        "agent_id": row["agent_id"],
                        "capability": row["capability"],
                        "reason": reason,
                    }
                ),
            ),
        )
        revoked.append({"agent_id": row["agent_id"], "capability": row["capability"]})
    return revoked


def ensure_task_capability_allowed(connection, project_id, task_id, agent_id, capability, session_id=None):
    _validate_capability(capability)
    if session_id is not None:
        session_row = connection.execute(
            """
            SELECT session_id
            FROM sessions
            WHERE session_id = ?
              AND project_id = ?
              AND task_id = ?
              AND agent_id = ?
              AND status = 'active'
            """,
            (session_id, project_id, task_id, agent_id),
        ).fetchone()
        if session_row is None:
            _audit_denial(
                connection,
                project_id,
                agent_id,
                "task_capability:{0}".format(capability),
                "task",
                task_id,
                "active_session_not_found",
            )
            connection.commit()
            raise PermissionError("Agent does not have an active session for this task")

    grant_row = connection.execute(
        """
        SELECT grant_id
        FROM task_capability_grants
        WHERE project_id = ?
          AND task_id = ?
          AND agent_id = ?
          AND capability = ?
          AND revoked_at IS NULL
        """,
        (project_id, task_id, agent_id, capability),
    ).fetchone()
    if grant_row is None:
        _audit_denial(
            connection,
            project_id,
            agent_id,
            "task_capability:{0}".format(capability),
            "task",
            task_id,
            "grant_not_found",
        )
        connection.commit()
        raise PermissionError("Agent is not allowed to perform this task action")

    return {"task_id": task_id, "agent_id": agent_id, "capability": capability}


def fetch_task_capabilities(connection, task_id):
    rows = connection.execute(
        """
        SELECT agent_id, capability, granted_by, created_at
        FROM task_capability_grants
        WHERE task_id = ? AND revoked_at IS NULL
        ORDER BY agent_id ASC, capability ASC
        """,
        (task_id,),
    ).fetchall()
    return [dict(row) for row in rows]
