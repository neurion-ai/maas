"""Unified incident timeline and replay feed."""

import json


def _parse_json(value):
    try:
        parsed = json.loads(value or "{}")
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _sort_events(events, order):
    reverse = order != "asc"
    return sorted(
        events,
        key=lambda item: (item["created_at"] or "", item["source"], item["event_id"]),
        reverse=reverse,
    )


def _activity_events(connection, project_id, task_id=None, session_id=None, agent_id=None, limit=100):
    filters = ["project_id = ?"]
    params = [project_id]
    if task_id:
        filters.append("task_id = ?")
        params.append(task_id)
    if agent_id:
        filters.append("agent_id = ?")
        params.append(agent_id)
    if session_id:
        filters.append("json_extract(details_json, '$.session_id') = ?")
        params.append(session_id)
    rows = connection.execute(
        """
        SELECT activity_id, agent_id, task_id, action, category, description, details_json, severity, created_at
        FROM activity_log
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT ?
        """.format(where_clause=" AND ".join(filters)),
        tuple(params + [limit]),
    ).fetchall()
    events = []
    for row in rows:
        details = _parse_json(row["details_json"])
        events.append(
            {
                "event_id": row["activity_id"],
                "source": "activity",
                "event_type": row["action"],
                "title": row["description"],
                "description": row["description"],
                "severity": row["severity"],
                "created_at": row["created_at"],
                "task_id": row["task_id"],
                "session_id": details.get("session_id"),
                "agent_id": row["agent_id"],
                "resource_type": "task" if row["task_id"] else None,
                "resource_id": row["task_id"],
                "details": {"category": row["category"], **details},
            }
        )
    return events


def _audit_events(connection, project_id, task_id=None, session_id=None, agent_id=None, resource_type=None, resource_id=None, limit=100):
    filters = ["project_id = ?"]
    params = [project_id]
    if resource_type:
        filters.append("resource_type = ?")
        params.append(resource_type)
    if resource_id:
        filters.append("resource_id = ?")
        params.append(resource_id)
    elif task_id:
        filters.append("resource_type = 'task' AND resource_id = ?")
        params.append(task_id)
    elif agent_id:
        filters.append("resource_type = 'agent' AND resource_id = ?")
        params.append(agent_id)
    elif session_id:
        filters.append("resource_type = 'session' AND resource_id = ?")
        params.append(session_id)
    rows = connection.execute(
        """
        SELECT audit_id, actor_id, action_type, resource_type, resource_id, detail_json, created_at
        FROM audit_trail
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT ?
        """.format(where_clause=" AND ".join(filters)),
        tuple(params + [limit]),
    ).fetchall()
    return [
        {
            "event_id": row["audit_id"],
            "source": "audit",
            "event_type": row["action_type"],
            "title": row["action_type"].replace("_", " "),
            "description": row["action_type"].replace("_", " "),
            "severity": "info",
            "created_at": row["created_at"],
            "task_id": row["resource_id"] if row["resource_type"] == "task" else None,
            "session_id": row["resource_id"] if row["resource_type"] == "session" else None,
            "agent_id": row["resource_id"] if row["resource_type"] == "agent" else None,
            "resource_type": row["resource_type"],
            "resource_id": row["resource_id"],
            "details": {"actor_id": row["actor_id"], **_parse_json(row["detail_json"])},
        }
        for row in rows
    ]


def _session_events(connection, project_id, task_id=None, session_id=None, agent_id=None, limit=100):
    filters = ["project_id = ?"]
    params = [project_id]
    if task_id:
        filters.append("task_id = ?")
        params.append(task_id)
    if session_id:
        filters.append("session_id = ?")
        params.append(session_id)
    if agent_id:
        filters.append("agent_id = ?")
        params.append(agent_id)
    rows = connection.execute(
        """
        SELECT session_id, task_id, agent_id, provider_type, status, progress_pct, status_message, started_at, ended_at
        FROM sessions
        WHERE {where_clause}
        ORDER BY started_at DESC
        LIMIT ?
        """.format(where_clause=" AND ".join(filters)),
        tuple(params + [limit]),
    ).fetchall()
    events = []
    for row in rows:
        events.append(
            {
                "event_id": "{0}:started".format(row["session_id"]),
                "source": "session",
                "event_type": "session_started",
                "title": "Session started",
                "description": row["status_message"] or "Session started.",
                "severity": "info",
                "created_at": row["started_at"],
                "task_id": row["task_id"],
                "session_id": row["session_id"],
                "agent_id": row["agent_id"],
                "resource_type": "session",
                "resource_id": row["session_id"],
                "details": {"provider_type": row["provider_type"], "status": row["status"]},
            }
        )
        if row["ended_at"]:
            severity = "error" if row["status"] in {"failed", "timed_out"} else "info"
            events.append(
                {
                    "event_id": "{0}:ended".format(row["session_id"]),
                    "source": "session",
                    "event_type": "session_{0}".format(row["status"]),
                    "title": "Session {0}".format(row["status"]),
                    "description": row["status_message"] or "Session finished.",
                    "severity": severity,
                    "created_at": row["ended_at"],
                    "task_id": row["task_id"],
                    "session_id": row["session_id"],
                    "agent_id": row["agent_id"],
                    "resource_type": "session",
                    "resource_id": row["session_id"],
                    "details": {
                        "provider_type": row["provider_type"],
                        "status": row["status"],
                        "progress_pct": row["progress_pct"],
                    },
                }
            )
    return events


def _failure_events(connection, project_id, task_id=None, session_id=None, agent_id=None, limit=100):
    filters = ["project_id = ?"]
    params = [project_id]
    if task_id:
        filters.append("task_id = ?")
        params.append(task_id)
    if session_id:
        filters.append("session_id = ?")
        params.append(session_id)
    if agent_id:
        filters.append("agent_id = ?")
        params.append(agent_id)
    rows = connection.execute(
        """
        SELECT failure_id, task_id, session_id, agent_id, failure_type, summary, detail_json, created_at
        FROM failure_log
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT ?
        """.format(where_clause=" AND ".join(filters)),
        tuple(params + [limit]),
    ).fetchall()
    return [
        {
            "event_id": row["failure_id"],
            "source": "failure",
            "event_type": row["failure_type"],
            "title": row["failure_type"].replace("_", " "),
            "description": row["summary"],
            "severity": "error",
            "created_at": row["created_at"],
            "task_id": row["task_id"],
            "session_id": row["session_id"],
            "agent_id": row["agent_id"],
            "resource_type": "failure",
            "resource_id": row["failure_id"],
            "details": _parse_json(row["detail_json"]),
        }
        for row in rows
    ]


def _dead_letter_events(connection, project_id, task_id=None, limit=100):
    filters = ["project_id = ?"]
    params = [project_id]
    if task_id:
        filters.append("task_id = ?")
        params.append(task_id)
    rows = connection.execute(
        """
        SELECT dlq_id, task_id, failure_id, reason, status, detail_json, resolution_note, created_at, resolved_at
        FROM dead_letter_queue
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT ?
        """.format(where_clause=" AND ".join(filters)),
        tuple(params + [limit]),
    ).fetchall()
    events = []
    for row in rows:
        events.append(
            {
                "event_id": "{0}:opened".format(row["dlq_id"]),
                "source": "dead_letter",
                "event_type": row["reason"],
                "title": "Dead-letter entry opened",
                "description": row["reason"].replace("_", " "),
                "severity": "warning",
                "created_at": row["created_at"],
                "task_id": row["task_id"],
                "session_id": None,
                "agent_id": None,
                "resource_type": "dead_letter",
                "resource_id": row["dlq_id"],
                "details": {"status": row["status"], "failure_id": row["failure_id"], **_parse_json(row["detail_json"])},
            }
        )
        if row["resolved_at"]:
            events.append(
                {
                    "event_id": "{0}:resolved".format(row["dlq_id"]),
                    "source": "dead_letter",
                    "event_type": "dead_letter_resolved",
                    "title": "Dead-letter entry resolved",
                    "description": row["resolution_note"] or "Dead-letter entry resolved.",
                    "severity": "info",
                    "created_at": row["resolved_at"],
                    "task_id": row["task_id"],
                    "session_id": None,
                    "agent_id": None,
                    "resource_type": "dead_letter",
                    "resource_id": row["dlq_id"],
                    "details": {"status": row["status"], "failure_id": row["failure_id"]},
                }
            )
    return events


def _escalation_events(connection, project_id, task_id=None, agent_id=None, resource_type=None, resource_id=None, limit=100):
    filters = ["project_id = ?"]
    params = [project_id]
    if resource_type:
        filters.append("resource_type = ?")
        params.append(resource_type)
    if resource_id:
        filters.append("resource_id = ?")
        params.append(resource_id)
    elif task_id:
        filters.append("resource_type = 'task' AND resource_id = ?")
        params.append(task_id)
    elif agent_id:
        filters.append("resource_type = 'agent' AND resource_id = ?")
        params.append(agent_id)
    rows = connection.execute(
        """
        SELECT escalation_id, requested_by, action_type, resource_type, resource_id, reason, status, resolved_by, resolution_note, created_at, resolved_at
        FROM escalation_queue
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT ?
        """.format(where_clause=" AND ".join(filters)),
        tuple(params + [limit]),
    ).fetchall()
    events = []
    for row in rows:
        events.append(
            {
                "event_id": "{0}:opened".format(row["escalation_id"]),
                "source": "escalation",
                "event_type": row["action_type"],
                "title": "Escalation requested",
                "description": row["reason"] or row["action_type"],
                "severity": "warning",
                "created_at": row["created_at"],
                "task_id": row["resource_id"] if row["resource_type"] == "task" else None,
                "session_id": None,
                "agent_id": row["resource_id"] if row["resource_type"] == "agent" else None,
                "resource_type": row["resource_type"],
                "resource_id": row["resource_id"],
                "details": {"escalation_id": row["escalation_id"], "status": row["status"], "requested_by": row["requested_by"]},
            }
        )
        if row["resolved_at"]:
            events.append(
                {
                    "event_id": "{0}:resolved".format(row["escalation_id"]),
                    "source": "escalation",
                    "event_type": "escalation_{0}".format(row["status"]),
                    "title": "Escalation {0}".format(row["status"]),
                    "description": row["resolution_note"] or "Escalation {0}.".format(row["status"]),
                    "severity": "info" if row["status"] == "approved" else "warning",
                    "created_at": row["resolved_at"],
                    "task_id": row["resource_id"] if row["resource_type"] == "task" else None,
                    "session_id": None,
                    "agent_id": row["resource_id"] if row["resource_type"] == "agent" else None,
                    "resource_type": row["resource_type"],
                    "resource_id": row["resource_id"],
                    "details": {"escalation_id": row["escalation_id"], "resolved_by": row["resolved_by"], "status": row["status"]},
                }
            )
    return events


def _provider_job_events(connection, project_id, task_id=None, agent_id=None, limit=100):
    filters = ["project_id = ?"]
    params = [project_id]
    if task_id:
        filters.append("task_id = ?")
        params.append(task_id)
    if agent_id:
        filters.append("agent_id = ?")
        params.append(agent_id)
    rows = connection.execute(
        """
        SELECT job_id, provider_id, task_id, agent_id, status, worker_id, created_at, started_at, finished_at
        FROM provider_job_queue
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT ?
        """.format(where_clause=" AND ".join(filters)),
        tuple(params + [limit]),
    ).fetchall()
    events = []
    for row in rows:
        events.append(
            {
                "event_id": "{0}:queued".format(row["job_id"]),
                "source": "provider_job",
                "event_type": "provider_job_queued",
                "title": "Provider job queued",
                "description": "Queued {0} run.".format(row["provider_id"]),
                "severity": "info",
                "created_at": row["created_at"],
                "task_id": row["task_id"],
                "session_id": None,
                "agent_id": row["agent_id"],
                "resource_type": "provider_job",
                "resource_id": row["job_id"],
                "details": {"provider_id": row["provider_id"], "status": row["status"]},
            }
        )
        if row["started_at"]:
            events.append(
                {
                    "event_id": "{0}:started".format(row["job_id"]),
                    "source": "provider_job",
                    "event_type": "provider_job_started",
                    "title": "Provider job started",
                    "description": "Provider job started.",
                    "severity": "info",
                    "created_at": row["started_at"],
                    "task_id": row["task_id"],
                    "session_id": None,
                    "agent_id": row["agent_id"],
                    "resource_type": "provider_job",
                    "resource_id": row["job_id"],
                    "details": {"provider_id": row["provider_id"], "worker_id": row["worker_id"], "status": row["status"]},
                }
            )
        if row["finished_at"]:
            events.append(
                {
                    "event_id": "{0}:finished".format(row["job_id"]),
                    "source": "provider_job",
                    "event_type": "provider_job_{0}".format(row["status"]),
                    "title": "Provider job {0}".format(row["status"]),
                    "description": "Provider job {0}.".format(row["status"]),
                    "severity": "error" if row["status"] == "failed" else "info",
                    "created_at": row["finished_at"],
                    "task_id": row["task_id"],
                    "session_id": None,
                    "agent_id": row["agent_id"],
                    "resource_type": "provider_job",
                    "resource_id": row["job_id"],
                    "details": {"provider_id": row["provider_id"], "worker_id": row["worker_id"], "status": row["status"]},
                }
            )
    return events


def _notification_events(connection, project_id, task_id=None, agent_id=None, resource_type=None, resource_id=None, limit=100):
    filters = ["project_id = ?"]
    params = [project_id]
    if resource_type:
        filters.append("resource_type = ?")
        params.append(resource_type)
    if resource_id:
        filters.append("resource_id = ?")
        params.append(resource_id)
    elif task_id:
        filters.append("resource_type = 'task' AND resource_id = ?")
        params.append(task_id)
    elif agent_id:
        filters.append("resource_type = 'agent' AND resource_id = ?")
        params.append(agent_id)
    rows = connection.execute(
        """
        SELECT notification_id, target_url, event_type, severity, title, body, payload_json, resource_type, resource_id, status, created_at, sent_at
        FROM notification_outbox
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT ?
        """.format(where_clause=" AND ".join(filters)),
        tuple(params + [limit]),
    ).fetchall()
    events = []
    for row in rows:
        events.append(
            {
                "event_id": "{0}:queued".format(row["notification_id"]),
                "source": "notification",
                "event_type": row["event_type"],
                "title": "Notification queued",
                "description": row["title"],
                "severity": row["severity"],
                "created_at": row["created_at"],
                "task_id": row["resource_id"] if row["resource_type"] == "task" else None,
                "session_id": None,
                "agent_id": row["resource_id"] if row["resource_type"] == "agent" else None,
                "resource_type": row["resource_type"],
                "resource_id": row["resource_id"],
                "details": {"status": row["status"], "target_url": row["target_url"], **_parse_json(row["payload_json"])},
            }
        )
        if row["sent_at"]:
            events.append(
                {
                    "event_id": "{0}:sent".format(row["notification_id"]),
                    "source": "notification",
                    "event_type": "notification_sent",
                    "title": "Notification sent",
                    "description": row["body"],
                    "severity": "info",
                    "created_at": row["sent_at"],
                    "task_id": row["resource_id"] if row["resource_type"] == "task" else None,
                    "session_id": None,
                    "agent_id": row["resource_id"] if row["resource_type"] == "agent" else None,
                    "resource_type": row["resource_type"],
                    "resource_id": row["resource_id"],
                    "details": {"status": row["status"], "target_url": row["target_url"]},
                }
            )
    return events


def fetch_incident_timeline(
    connection,
    project_id,
    task_id=None,
    session_id=None,
    agent_id=None,
    resource_type=None,
    resource_id=None,
    limit=100,
    order="desc",
):
    events = []
    events.extend(_activity_events(connection, project_id, task_id=task_id, session_id=session_id, agent_id=agent_id, limit=limit))
    events.extend(
        _audit_events(
            connection,
            project_id,
            task_id=task_id,
            session_id=session_id,
            agent_id=agent_id,
            resource_type=resource_type,
            resource_id=resource_id,
            limit=limit,
        )
    )
    events.extend(_session_events(connection, project_id, task_id=task_id, session_id=session_id, agent_id=agent_id, limit=limit))
    events.extend(_failure_events(connection, project_id, task_id=task_id, session_id=session_id, agent_id=agent_id, limit=limit))
    events.extend(_dead_letter_events(connection, project_id, task_id=task_id, limit=limit))
    events.extend(
        _escalation_events(
            connection,
            project_id,
            task_id=task_id,
            agent_id=agent_id,
            resource_type=resource_type,
            resource_id=resource_id,
            limit=limit,
        )
    )
    events.extend(_provider_job_events(connection, project_id, task_id=task_id, agent_id=agent_id, limit=limit))
    events.extend(
        _notification_events(
            connection,
            project_id,
            task_id=task_id,
            agent_id=agent_id,
            resource_type=resource_type,
            resource_id=resource_id,
            limit=limit,
        )
    )
    ordered = _sort_events(events, order)[:limit]
    by_source = {}
    for item in ordered:
        by_source[item["source"]] = by_source.get(item["source"], 0) + 1
    return {
        "filters": {
            "task_id": task_id,
            "session_id": session_id,
            "agent_id": agent_id,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "limit": limit,
            "order": "asc" if order == "asc" else "desc",
        },
        "summary": {
            "total_events": len(ordered),
            "sources": by_source,
        },
        "events": ordered,
    }
