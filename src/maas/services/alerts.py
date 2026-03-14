"""Alert read models and steering actions."""

import json

from maas.ids import generate_id
from maas.services.security import ensure_board_action_allowed


def fetch_alerts(connection):
    rows = connection.execute(
        """
        SELECT alert_id, project_id, severity, title, description, status, created_at
        FROM alerts
        ORDER BY
            CASE status WHEN 'open' THEN 0 WHEN 'acknowledged' THEN 1 ELSE 2 END,
            CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
            created_at DESC
        """
    ).fetchall()

    grouped = {"open": [], "acknowledged": [], "resolved": []}
    for row in rows:
        alert = dict(row)
        grouped.setdefault(alert["status"], []).append(alert)

    return {
        "alerts": [dict(row) for row in rows],
        "grouped": grouped,
        "summary": {
            "open": len(grouped.get("open", [])),
            "acknowledged": len(grouped.get("acknowledged", [])),
            "resolved": len(grouped.get("resolved", [])),
            "critical_open": len(
                [alert for alert in grouped.get("open", []) if alert["severity"] == "critical"]
            ),
            "repeated_failure_open": len(
                [
                    alert
                    for alert in grouped.get("open", [])
                    if alert["title"] == "Repeated task failures"
                ]
            ),
        },
    }


def update_alert_status(connection, alert_id, actor_id, status):
    alert = connection.execute(
        "SELECT alert_id, project_id, status FROM alerts WHERE alert_id = ?",
        (alert_id,),
    ).fetchone()
    if alert is None:
        raise ValueError("Alert not found")
    ensure_board_action_allowed(connection, actor_id, alert["project_id"], "update_alert_status", "alert", alert_id)
    if status not in ("acknowledged", "resolved"):
        raise ValueError("Unsupported alert status")
    if alert["status"] == status:
        return {"alert_id": alert_id, "status": status}

    connection.execute(
        "UPDATE alerts SET status = ? WHERE alert_id = ?",
        (status, alert_id),
    )
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, ?, 'alert', ?, ?)
        """,
        (
            generate_id("audit"),
            alert["project_id"],
            actor_id,
            "alert_status_updated",
            alert_id,
            json.dumps({"status": status}),
        ),
    )
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, action, category, description, details_json, severity
        ) VALUES (?, ?, 'alert_status_updated', 'steering', ?, ?, 'info')
        """,
        (
            generate_id("act"),
            alert["project_id"],
            "Alert {0} moved to {1}.".format(alert_id, status),
            json.dumps({"alert_id": alert_id, "status": status}),
        ),
    )
    connection.commit()
    return {"alert_id": alert_id, "status": status}
