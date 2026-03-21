"""Notification policy, outbox storage, and delivery helpers."""

from datetime import datetime, timezone
import hashlib
import json
from urllib import error, request

from maas.ids import generate_id
from maas.services.projects import resolve_project, resolve_project_id
from maas.services.security import ensure_board_action_allowed


DEFAULT_NOTIFICATION_POLICY = {
    "webhook_urls": [],
    "minimum_severity": "warning",
    "enabled_events": [
        "escalation_requested",
        "dead_letter_opened",
        "circuit_breaker_opened",
    ],
}

NOTIFICATION_SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}
SUPPORTED_NOTIFICATION_EVENTS = set(DEFAULT_NOTIFICATION_POLICY["enabled_events"])
NOTIFICATION_RETRY_BASE_SECONDS = 60
NOTIFICATION_RETRY_MAX_SECONDS = 3600
NOTIFICATION_MAX_ATTEMPTS = 5


def _load_project_config(raw_config):
    try:
        config = json.loads(raw_config or "{}")
    except ValueError:
        return {}
    return config if isinstance(config, dict) else {}


def _normalize_severity(value, field_name="minimum_severity"):
    normalized = (value or DEFAULT_NOTIFICATION_POLICY["minimum_severity"]).strip().lower()
    if normalized not in NOTIFICATION_SEVERITY_ORDER:
        raise ValueError("{0} must be one of: info, warning, critical.".format(field_name))
    return normalized


def _normalize_urls(values):
    urls = []
    seen = set()
    for value in values or []:
        if not isinstance(value, str):
            raise ValueError("webhook_urls entries must be strings.")
        normalized = value.strip()
        if not normalized:
            continue
        if not (normalized.startswith("http://") or normalized.startswith("https://")):
            raise ValueError("webhook_urls entries must start with http:// or https://.")
        if normalized in seen:
            continue
        seen.add(normalized)
        urls.append(normalized)
    return urls


def _normalize_enabled_events(values):
    events = []
    seen = set()
    for value in values or []:
        if not isinstance(value, str):
            raise ValueError("enabled_events entries must be strings.")
        normalized = value.strip()
        if normalized not in SUPPORTED_NOTIFICATION_EVENTS:
            raise ValueError(
                "enabled_events entries must be one of: {0}.".format(", ".join(sorted(SUPPORTED_NOTIFICATION_EVENTS)))
            )
        if normalized in seen:
            continue
        seen.add(normalized)
        events.append(normalized)
    return events


def default_notification_policy():
    return {
        "webhook_urls": list(DEFAULT_NOTIFICATION_POLICY["webhook_urls"]),
        "minimum_severity": DEFAULT_NOTIFICATION_POLICY["minimum_severity"],
        "enabled_events": list(DEFAULT_NOTIFICATION_POLICY["enabled_events"]),
    }


def _notification_dedupe_key(
    project_id,
    target_url,
    event_type,
    severity,
    title,
    body,
    resource_type,
    resource_id,
    payload_json,
):
    digest = hashlib.sha256()
    digest.update(
        "||".join(
            [
                project_id or "",
                target_url or "",
                event_type or "",
                severity or "",
                title or "",
                body or "",
                resource_type or "",
                resource_id or "",
                payload_json or "{}",
            ]
        ).encode("utf-8")
    )
    return digest.hexdigest()


def _notification_retry_delay_seconds(attempt_count):
    attempt = max(1, int(attempt_count or 1))
    delay = NOTIFICATION_RETRY_BASE_SECONDS * (2 ** max(0, attempt - 1))
    return min(delay, NOTIFICATION_RETRY_MAX_SECONDS)


def _parse_timestamp(value):
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                parsed = datetime.strptime(value, fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _notification_retry_budget_remaining(attempts):
    return max(0, NOTIFICATION_MAX_ATTEMPTS - max(0, int(attempts or 0)))


def _notification_retry_exhausted(attempts):
    return _notification_retry_budget_remaining(attempts) <= 0


def _notification_delivery_state(status, attempts, next_attempt_at, now=None):
    if status == "sent":
        return "sent"
    if status == "queued":
        return "queued"
    if status != "failed":
        return status or "unknown"
    if _notification_retry_exhausted(attempts):
        return "retry_exhausted"
    parsed_next_attempt_at = _parse_timestamp(next_attempt_at)
    current_time = now or datetime.now(timezone.utc)
    if parsed_next_attempt_at is None or parsed_next_attempt_at <= current_time:
        return "retry_ready"
    return "retry_scheduled"


def _notification_digest_item(item):
    return {
        "dedupe_key": item.get("dedupe_key"),
        "project_id": item.get("project_id"),
        "project_name": item.get("project_name"),
        "event_type": item.get("event_type"),
        "severity": item.get("severity"),
        "title": item.get("title"),
        "resource_type": item.get("resource_type"),
        "resource_id": item.get("resource_id"),
        "delivery_state": item.get("delivery_state"),
        "attempts": item.get("attempts"),
        "retry_budget_remaining": item.get("retry_budget_remaining"),
        "retry_budget_exhausted": item.get("retry_budget_exhausted"),
        "next_attempt_at": item.get("next_attempt_at"),
        "next_attempt_in_seconds": item.get("next_attempt_in_seconds"),
        "last_attempt_at": item.get("last_attempt_at"),
        "last_error": item.get("last_error"),
        "last_response_code": item.get("last_response_code"),
        "created_at": item.get("created_at"),
        "notification_ids": [item.get("notification_id")] if item.get("notification_id") else [],
        "count": 1,
    }


def build_notification_outbox_summary(items):
    return {
        "total": len(items),
        "queued": len([item for item in items if item.get("status") == "queued"]),
        "failed": len([item for item in items if item.get("status") == "failed"]),
        "sent": len([item for item in items if item.get("status") == "sent"]),
        "retry_ready": len([item for item in items if item.get("delivery_state") == "retry_ready"]),
        "retry_scheduled": len([item for item in items if item.get("delivery_state") == "retry_scheduled"]),
        "retry_exhausted": len([item for item in items if item.get("delivery_state") == "retry_exhausted"]),
        "max_attempts": NOTIFICATION_MAX_ATTEMPTS,
    }


def build_notification_digests(items, limit=8):
    grouped = {}
    for item in items:
        dedupe_key = item.get("dedupe_key") or item["notification_id"]
        current = grouped.get(dedupe_key)
        if current is None:
            grouped[dedupe_key] = _notification_digest_item(item)
            continue
        notification_ids = list(current["notification_ids"])
        if item.get("notification_id") and item["notification_id"] not in notification_ids:
            notification_ids.append(item["notification_id"])
        if item.get("created_at") and (current.get("created_at") or "") < item["created_at"]:
            updated = _notification_digest_item(item)
            updated["notification_ids"] = notification_ids
            updated["count"] = len(notification_ids) or 1
            grouped[dedupe_key] = updated
            continue
        current["notification_ids"] = notification_ids
        current["count"] = len(notification_ids) or 1
    ordered = sorted(
        grouped.values(),
        key=lambda item: (
            0 if item["delivery_state"] == "retry_exhausted" else 1 if item["delivery_state"] == "retry_ready" else 2,
            -NOTIFICATION_SEVERITY_ORDER.get(item.get("severity") or "info", 0),
            item.get("next_attempt_in_seconds") if item.get("next_attempt_in_seconds") is not None else -1,
            item.get("created_at") or "",
        ),
    )
    return {
        "attention": [
            item
            for item in ordered
            if item["delivery_state"] in {"retry_exhausted", "retry_ready", "retry_scheduled"}
        ][:limit],
        "queued": [item for item in ordered if item["delivery_state"] == "queued"][:limit],
    }


def _decorate_notification_item(item, now=None):
    current_time = now or datetime.now(timezone.utc)
    parsed_next_attempt_at = _parse_timestamp(item.get("next_attempt_at"))
    item["retry_budget_remaining"] = _notification_retry_budget_remaining(item.get("attempts"))
    item["retry_budget_exhausted"] = _notification_retry_exhausted(item.get("attempts"))
    item["delivery_state"] = _notification_delivery_state(
        item.get("status"),
        item.get("attempts"),
        item.get("next_attempt_at"),
        now=current_time,
    )
    item["next_attempt_due"] = bool(parsed_next_attempt_at and parsed_next_attempt_at <= current_time)
    item["next_attempt_in_seconds"] = (
        max(0, int((parsed_next_attempt_at - current_time).total_seconds()))
        if parsed_next_attempt_at is not None
        else None
    )
    item["retry_strategy"] = {
        "base_delay_seconds": NOTIFICATION_RETRY_BASE_SECONDS,
        "max_delay_seconds": NOTIFICATION_RETRY_MAX_SECONDS,
        "max_attempts": NOTIFICATION_MAX_ATTEMPTS,
    }
    return item


def normalize_notification_policy(policy=None):
    requested = policy or {}
    return {
        "webhook_urls": _normalize_urls(requested.get("webhook_urls", DEFAULT_NOTIFICATION_POLICY["webhook_urls"])),
        "minimum_severity": _normalize_severity(requested.get("minimum_severity")),
        "enabled_events": _normalize_enabled_events(
            requested.get("enabled_events", DEFAULT_NOTIFICATION_POLICY["enabled_events"])
        ),
    }


def notification_policy_from_row(project_row):
    if project_row is None:
        return default_notification_policy()
    config = _load_project_config(project_row["config_json"])
    return normalize_notification_policy(config.get("notifications") or {})


def fetch_project_notification_policy(connection, project_id=None):
    project_row = resolve_project(connection, project_id, include_archived=False)
    if project_row is None:
        raise ValueError("project not found")
    return notification_policy_from_row(project_row)


def update_project_notification_policy(connection, project_id, actor_id, policy):
    resolved_project_id = resolve_project_id(connection, project_id, include_archived=False)
    if resolved_project_id is None:
        raise ValueError("project not found")
    ensure_board_action_allowed(
        connection,
        actor_id,
        resolved_project_id,
        "configure_notifications",
        "project",
        resolved_project_id,
    )
    normalized = normalize_notification_policy(policy)
    connection.execute(
        """
        UPDATE projects
        SET config_json = json_set(
                json_set(
                    json_set(
                        CASE
                            WHEN json_valid(config_json) THEN config_json
                            ELSE '{}'
                        END,
                        '$.notifications.webhook_urls',
                        json(?)
                    ),
                    '$.notifications.minimum_severity',
                    ?
                ),
                '$.notifications.enabled_events',
                json(?)
            ),
            updated_at = CURRENT_TIMESTAMP
        WHERE project_id = ?
        """,
        (
            json.dumps(normalized["webhook_urls"]),
            normalized["minimum_severity"],
            json.dumps(normalized["enabled_events"]),
            resolved_project_id,
        ),
    )
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, 'configure_notifications', 'project', ?, ?)
        """,
        (
            generate_id("audit"),
            resolved_project_id,
            actor_id,
            resolved_project_id,
            json.dumps(normalized),
        ),
    )
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, action, category, description, details_json, severity
        ) VALUES (?, ?, 'notification_policy_updated', 'projects', ?, ?, 'info')
        """,
        (
            generate_id("act"),
            resolved_project_id,
            "Notification policy updated.",
            json.dumps(normalized),
        ),
    )
    connection.commit()
    return {"project_id": resolved_project_id, "notification_policy": normalized}


def _should_emit_notification(policy, event_type, severity):
    if not policy["webhook_urls"]:
        return False
    if event_type not in policy["enabled_events"]:
        return False
    return NOTIFICATION_SEVERITY_ORDER[severity] >= NOTIFICATION_SEVERITY_ORDER[policy["minimum_severity"]]


def queue_notification_event(
    connection,
    project_id,
    event_type,
    severity,
    title,
    body,
    resource_type=None,
    resource_id=None,
    payload=None,
):
    policy = fetch_project_notification_policy(connection, project_id)
    normalized_severity = _normalize_severity(severity, field_name="severity")
    if not _should_emit_notification(policy, event_type, normalized_severity):
        return []
    queued_ids = []
    payload_json = json.dumps(payload or {}, sort_keys=True)
    for target_url in policy["webhook_urls"]:
        dedupe_key = _notification_dedupe_key(
            project_id,
            target_url,
            event_type,
            normalized_severity,
            title,
            body,
            resource_type,
            resource_id,
            payload_json,
        )
        existing = connection.execute(
            """
            SELECT notification_id, status
            FROM notification_outbox
            WHERE dedupe_key = ?
              AND status IN ('queued', 'failed')
            LIMIT 1
            """,
            (dedupe_key,),
        ).fetchone()
        if existing is not None:
            connection.execute(
                """
                UPDATE notification_outbox
                SET status = CASE
                        WHEN status = 'failed' AND attempts < ? THEN 'queued'
                        ELSE status
                    END,
                    next_attempt_at = CASE
                        WHEN status = 'failed' AND attempts < ? THEN CURRENT_TIMESTAMP
                        ELSE next_attempt_at
                    END,
                    last_error = CASE
                        WHEN status = 'failed' AND attempts < ? THEN NULL
                        ELSE last_error
                    END,
                    last_response_code = CASE
                        WHEN status = 'failed' AND attempts < ? THEN NULL
                        ELSE last_response_code
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE notification_id = ?
                """,
                (
                    NOTIFICATION_MAX_ATTEMPTS,
                    NOTIFICATION_MAX_ATTEMPTS,
                    NOTIFICATION_MAX_ATTEMPTS,
                    NOTIFICATION_MAX_ATTEMPTS,
                    existing["notification_id"],
                ),
            )
            queued_ids.append(existing["notification_id"])
            continue
        notification_id = generate_id("notif")
        connection.execute(
            """
            INSERT INTO notification_outbox (
                notification_id, project_id, target_url, event_type, severity, title, body,
                payload_json, resource_type, resource_id, dedupe_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                notification_id,
                project_id,
                target_url,
                event_type,
                normalized_severity,
                title,
                body,
                payload_json,
                resource_type,
                resource_id,
                dedupe_key,
            ),
        )
        queued_ids.append(notification_id)
    return queued_ids


def fetch_notification_outbox(connection, project_id=None, status=None, limit=20, include_archived=False):
    if project_id:
        resolved_project_id = resolve_project_id(connection, project_id, include_archived=include_archived)
        if resolved_project_id is None:
            return []
        filters = ["notification_outbox.project_id = ?"]
        params = [resolved_project_id]
    else:
        filters = []
        params = []
    if not include_archived:
        filters.append("projects.state = 'active'")
    if status:
        filters.append("notification_outbox.status = ?")
        params.append(status)
    where_clause = "WHERE " + " AND ".join(filters) if filters else ""
    rows = connection.execute(
        """
        SELECT
            notification_outbox.notification_id,
            notification_outbox.project_id,
            projects.name AS project_name,
            notification_outbox.target_url,
            notification_outbox.event_type,
            notification_outbox.severity,
            notification_outbox.title,
            notification_outbox.body,
            notification_outbox.payload_json,
            notification_outbox.resource_type,
            notification_outbox.resource_id,
            notification_outbox.status,
            notification_outbox.attempts,
            notification_outbox.last_error,
            notification_outbox.last_response_code,
            notification_outbox.dedupe_key,
            notification_outbox.next_attempt_at,
            notification_outbox.last_attempt_at,
            notification_outbox.created_at,
            notification_outbox.updated_at,
            notification_outbox.sent_at
        FROM notification_outbox
        JOIN projects ON projects.project_id = notification_outbox.project_id
        {where_clause}
        ORDER BY
            CASE notification_outbox.status WHEN 'queued' THEN 0 WHEN 'failed' THEN 1 ELSE 2 END,
            notification_outbox.created_at DESC
        LIMIT ?
        """.format(where_clause=where_clause),
        tuple(params + [limit]),
    ).fetchall()
    items = []
    now = datetime.now(timezone.utc)
    for row in rows:
        item = dict(row)
        try:
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
        except ValueError:
            item["payload"] = {}
        items.append(_decorate_notification_item(item, now=now))
    return items


def count_notification_outbox(connection, project_id=None):
    filters = []
    params = []
    if project_id:
        filters.append("project_id = ?")
        params.append(project_id)
    where_clause = "WHERE " + " AND ".join(filters) if filters else ""
    row = connection.execute(
        """
        SELECT
            SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) AS queued_count,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count
        FROM notification_outbox
        {where_clause}
        """.format(where_clause=where_clause),
        tuple(params),
    ).fetchone()
    return {
        "queued": row["queued_count"] or 0,
        "failed": row["failed_count"] or 0,
    }


def process_notification(connection, notification_id, actor_id):
    row = connection.execute(
        """
        SELECT *
        FROM notification_outbox
        WHERE notification_id = ?
        """,
        (notification_id,),
    ).fetchone()
    if row is None:
        raise ValueError("Notification not found")
    ensure_board_action_allowed(connection, actor_id, row["project_id"], "process_notification", "notification", notification_id)
    payload = {
        "notification_id": row["notification_id"],
        "project_id": row["project_id"],
        "event_type": row["event_type"],
        "severity": row["severity"],
        "title": row["title"],
        "body": row["body"],
        "resource_type": row["resource_type"],
        "resource_id": row["resource_id"],
    }
    try:
        payload["payload"] = json.loads(row["payload_json"] or "{}")
    except ValueError:
        payload["payload"] = {}

    request_body = json.dumps(payload).encode("utf-8")
    http_request = request.Request(
        row["target_url"],
        data=request_body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(http_request, timeout=10) as response:
            status_code = getattr(response, "status", response.getcode())
            response.read()
        connection.execute(
            """
            UPDATE notification_outbox
            SET status = 'sent',
                attempts = attempts + 1,
                last_error = NULL,
                last_response_code = ?,
                next_attempt_at = NULL,
                last_attempt_at = CURRENT_TIMESTAMP,
                sent_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE notification_id = ?
            """,
            (status_code, notification_id),
        )
        connection.commit()
    except error.URLError as exc:
        next_attempts = (row["attempts"] or 0) + 1
        next_attempt_at = None
        if not _notification_retry_exhausted(next_attempts):
            retry_delay_seconds = _notification_retry_delay_seconds(next_attempts)
            next_attempt_at = "+{0} seconds".format(retry_delay_seconds)
        connection.execute(
            """
            UPDATE notification_outbox
            SET status = 'failed',
                attempts = attempts + 1,
                last_error = ?,
                next_attempt_at = CASE
                    WHEN ? IS NULL THEN NULL
                    ELSE DATETIME('now', ?)
                END,
                last_attempt_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE notification_id = ?
            """,
            (str(exc.reason or exc), next_attempt_at, next_attempt_at, notification_id),
        )
        connection.commit()
    except Exception as exc:
        next_attempts = (row["attempts"] or 0) + 1
        next_attempt_at = None
        if not _notification_retry_exhausted(next_attempts):
            retry_delay_seconds = _notification_retry_delay_seconds(next_attempts)
            next_attempt_at = "+{0} seconds".format(retry_delay_seconds)
        connection.execute(
            """
            UPDATE notification_outbox
            SET status = 'failed',
                attempts = attempts + 1,
                last_error = ?,
                next_attempt_at = CASE
                    WHEN ? IS NULL THEN NULL
                    ELSE DATETIME('now', ?)
                END,
                last_attempt_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE notification_id = ?
            """,
            (str(exc), next_attempt_at, next_attempt_at, notification_id),
        )
        connection.commit()
    refreshed = fetch_notification_outbox(connection, project_id=row["project_id"], limit=100, include_archived=True)
    return next((item for item in refreshed if item["notification_id"] == notification_id), None)


def process_next_notification(connection, actor_id, project_id=None):
    resolved_project_id = resolve_project_id(connection, project_id, include_archived=False) if project_id else None
    filters = [
        "(status = 'queued' OR (status = 'failed' AND attempts < ? AND (next_attempt_at IS NULL OR STRFTIME('%s', next_attempt_at) <= STRFTIME('%s', 'now'))))"
    ]
    params = [NOTIFICATION_MAX_ATTEMPTS]
    if resolved_project_id:
        filters.append("project_id = ?")
        params.append(resolved_project_id)
    row = connection.execute(
        """
        SELECT notification_id
        FROM notification_outbox
        WHERE {where_clause}
        ORDER BY
            CASE status WHEN 'queued' THEN 0 ELSE 1 END,
            COALESCE(next_attempt_at, created_at) ASC,
            created_at ASC
        LIMIT 1
        """.format(where_clause=" AND ".join(filters)),
        tuple(params),
    ).fetchone()
    if row is None:
        return {"processed": False, "notification": None}
    processed = process_notification(connection, row["notification_id"], actor_id)
    return {"processed": True, "notification": processed}
