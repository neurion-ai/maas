"""Persisted fault-injection helpers for unattended trust runs."""

from __future__ import annotations

import json

from maas.ids import generate_id


def _load_json(value):
    try:
        payload = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def schedule_fault_injection(
    connection,
    project_id,
    domain,
    action,
    *,
    trust_run_id=None,
    cycle_index=None,
    target_resource_type=None,
    target_resource_id=None,
    payload=None,
    mode="once",
    status="scheduled",
):
    injection_id = generate_id("fault")
    connection.execute(
        """
        INSERT INTO fault_injections (
            injection_id, project_id, trust_run_id, cycle_index, domain, action,
            target_resource_type, target_resource_id, mode, status, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            injection_id,
            project_id,
            trust_run_id,
            cycle_index,
            domain,
            action,
            target_resource_type,
            target_resource_id,
            mode,
            status,
            json.dumps(payload or {}),
        ),
    )
    row = connection.execute(
        """
        SELECT *
        FROM fault_injections
        WHERE injection_id = ?
        """,
        (injection_id,),
    ).fetchone()
    return _fault_row_to_dict(row) if row is not None else None


def _fault_row_to_dict(row):
    item = dict(row)
    item["payload"] = _load_json(item.pop("payload_json", "{}"))
    return item


def activate_fault_injections(connection, trust_run_id, cycle_index):
    connection.execute(
        """
        UPDATE fault_injections
        SET status = 'pending'
        WHERE trust_run_id = ?
          AND cycle_index = ?
          AND status = 'scheduled'
        """,
        (trust_run_id, cycle_index),
    )
    rows = connection.execute(
        """
        SELECT *
        FROM fault_injections
        WHERE trust_run_id = ?
          AND cycle_index = ?
          AND status = 'pending'
        ORDER BY created_at ASC, rowid ASC
        """,
        (trust_run_id, cycle_index),
    ).fetchall()
    return [_fault_row_to_dict(row) for row in rows]


def list_fault_injections(connection, *, trust_run_id=None, project_id=None, status=None):
    filters = []
    params = []
    if trust_run_id is not None:
        filters.append("trust_run_id = ?")
        params.append(trust_run_id)
    if project_id is not None:
        filters.append("project_id = ?")
        params.append(project_id)
    if status is not None:
        filters.append("status = ?")
        params.append(status)
    where_clause = "WHERE " + " AND ".join(filters) if filters else ""
    rows = connection.execute(
        """
        SELECT *
        FROM fault_injections
        {where_clause}
        ORDER BY cycle_index ASC, created_at ASC, rowid ASC
        """.format(where_clause=where_clause),
        tuple(params),
    ).fetchall()
    return [_fault_row_to_dict(row) for row in rows]


def consume_fault_injection(
    connection,
    project_id,
    domain,
    action,
    *,
    target_resource_type=None,
    target_resource_id=None,
):
    rows = connection.execute(
        """
        SELECT *
        FROM fault_injections
        WHERE project_id = ?
          AND domain = ?
          AND action = ?
          AND status = 'pending'
        ORDER BY created_at ASC, rowid ASC
        """,
        (project_id, domain, action),
    ).fetchall()
    for row in rows:
        if row["target_resource_type"] and row["target_resource_type"] != target_resource_type:
            continue
        if row["target_resource_id"] and row["target_resource_id"] != target_resource_id:
            continue
        next_status = "pending" if row["mode"] == "persistent" else "applied"
        connection.execute(
            """
            UPDATE fault_injections
            SET status = ?,
                applied_at = CURRENT_TIMESTAMP
            WHERE injection_id = ?
            """,
            (next_status, row["injection_id"]),
        )
        refreshed = connection.execute(
            """
            SELECT *
            FROM fault_injections
            WHERE injection_id = ?
            """,
            (row["injection_id"],),
        ).fetchone()
        return _fault_row_to_dict(refreshed) if refreshed is not None else _fault_row_to_dict(row)
    return None


def skip_unapplied_faults(connection, trust_run_id):
    connection.execute(
        """
        UPDATE fault_injections
        SET status = 'skipped'
        WHERE trust_run_id = ?
          AND status IN ('scheduled', 'pending')
        """,
        (trust_run_id,),
    )
