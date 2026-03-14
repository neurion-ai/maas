"""Permission helpers for steering and other sensitive MAAS actions."""

import json

from maas.ids import generate_id


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
