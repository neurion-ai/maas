"""Provider registry and metadata for the initial runtime slice."""

from copy import deepcopy
import json

from maas.config import DEFAULT_PROVIDER_SETTINGS
from maas.ids import generate_id
from maas.services.security import ensure_board_action_allowed


STANDARD_PROVIDER_LIFECYCLE_VERSION = "provider_runtime_v1"
STANDARD_PROVIDER_LIFECYCLE_PHASES = [
    "session_started",
    "workspace_prepared",
    "execution_running",
    "artifact_recorded",
    "session_completed",
]


PROVIDER_REGISTRY = {
    "claude_code": {
        "id": "claude_code",
        "name": "Claude Code",
        "kind": "interactive_cli",
        "status": "simulated",
        "execution_mode": "local_simulation",
        "supports_worker_execution": True,
        "supports_live_api": False,
        "default_artifact_type": "provider_report",
        "lifecycle_version": STANDARD_PROVIDER_LIFECYCLE_VERSION,
        "lifecycle_phases": list(STANDARD_PROVIDER_LIFECYCLE_PHASES),
        "notes": "Simulated local adapter with normalized runtime phase reporting.",
    },
    "openai_codex": {
        "id": "openai_codex",
        "name": "OpenAI Codex",
        "kind": "api_runtime",
        "status": "simulated",
        "execution_mode": "local_simulation",
        "supports_worker_execution": True,
        "supports_live_api": False,
        "default_artifact_type": "provider_report",
        "lifecycle_version": STANDARD_PROVIDER_LIFECYCLE_VERSION,
        "lifecycle_phases": list(STANDARD_PROVIDER_LIFECYCLE_PHASES),
        "notes": "Simulated API-style adapter with normalized runtime phase reporting.",
    },
    "python_script": {
        "id": "python_script",
        "name": "Python Script",
        "kind": "local_worker",
        "status": "available",
        "execution_mode": "local_simulation",
        "supports_worker_execution": True,
        "supports_live_api": False,
        "default_artifact_type": "provider_report",
        "lifecycle_version": STANDARD_PROVIDER_LIFECYCLE_VERSION,
        "lifecycle_phases": list(STANDARD_PROVIDER_LIFECYCLE_PHASES),
        "notes": "Reference local runtime with normalized runtime phase reporting.",
    },
}


PROVIDER_RUNTIME_RULES = {
    "claude_code": {
        "available_execution_modes": ["local_simulation", "claude_cli"],
        "live_mode": "claude_cli",
        "runtime_controls": ["cli_command", "timeout_seconds", "permission_mode", "model"],
        "notes": {
            "configured": "Local Claude Code CLI integration enabled by project config.",
            "misconfigured": "Claude Code runtime configuration is invalid; task execution is blocked until fixed.",
        },
    },
    "openai_codex": {
        "available_execution_modes": ["local_simulation", "codex_cli"],
        "live_mode": "codex_cli",
        "runtime_controls": ["cli_command", "timeout_seconds", "sandbox", "model"],
        "notes": {
            "configured": "Local Codex CLI integration enabled by project config.",
            "misconfigured": "OpenAI Codex runtime configuration is invalid; task execution is blocked until fixed.",
        },
    },
    "python_script": {
        "available_execution_modes": ["local_simulation"],
        "live_mode": None,
        "runtime_controls": [],
        "notes": {
            "configured": "Reference local runtime with normalized runtime phase reporting.",
            "misconfigured": "Python Script runtime configuration is invalid; task execution is blocked until fixed.",
        },
    },
}


def list_providers():
    return [deepcopy(provider) for provider in PROVIDER_REGISTRY.values()]


def get_provider(provider_id):
    provider = PROVIDER_REGISTRY.get(provider_id)
    if provider is None:
        raise ValueError("Unsupported provider type: {0}".format(provider_id))
    return deepcopy(provider)


def _project_provider_config(connection, project_id):
    if connection is None:
        return {}

    if project_id is None:
        row = connection.execute("SELECT project_id, config_json FROM projects LIMIT 1").fetchone()
    else:
        row = connection.execute(
            "SELECT project_id, config_json FROM projects WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    if row is None:
        return {}
    try:
        config = json.loads(row["config_json"] or "{}")
    except json.JSONDecodeError:
        return {}
    return config.get("providers") or {}


def _merged_provider_settings(provider_id, config):
    settings = deepcopy(DEFAULT_PROVIDER_SETTINGS.get(provider_id) or {})
    if isinstance(config, dict):
        settings.update(config)
    return settings


def _validate_timeout(provider_name, timeout_seconds, warnings):
    try:
        timeout_value = int(timeout_seconds)
    except (TypeError, ValueError):
        warnings.append("{0} timeout_seconds must be a positive integer.".format(provider_name))
        return None
    if timeout_value <= 0:
        warnings.append("{0} timeout_seconds must be greater than zero.".format(provider_name))
        return None
    return timeout_value


def _normalize_string_setting(provider_name, setting_name, value, warnings, required=False):
    if value in (None, ""):
        if required:
            warnings.append("{0} {1} must not be empty.".format(provider_name, setting_name))
        return ""
    if not isinstance(value, str):
        warnings.append("{0} {1} must be a string.".format(provider_name, setting_name))
        return ""
    normalized_value = value.strip()
    if required and not normalized_value:
        warnings.append("{0} {1} must not be empty.".format(provider_name, setting_name))
    return normalized_value


def _mark_provider_misconfigured(provider, rules):
    provider["status"] = "misconfigured"
    provider["execution_mode"] = "unavailable"
    provider["effective_execution_mode"] = None
    provider["supports_live_api"] = False
    provider["notes"] = rules["notes"]["misconfigured"]
    provider["is_runnable"] = False
    return provider


def _resolve_provider_status(provider, config):
    rules = PROVIDER_RUNTIME_RULES[provider["id"]]
    merged_settings = _merged_provider_settings(provider["id"], config)
    warnings = []
    raw_mode = _normalize_string_setting(provider["name"], "mode", merged_settings.get("mode"), warnings) or "local_simulation"
    configured_mode = "local_simulation" if raw_mode in ("simulated", "local_simulation") else raw_mode

    provider["available_execution_modes"] = list(rules["available_execution_modes"])
    provider["configured_execution_mode"] = configured_mode
    provider["effective_execution_mode"] = provider["execution_mode"]
    provider["runtime_controls"] = {}
    provider["configurable_runtime_controls"] = {
        key: merged_settings.get(key, "")
        for key in rules["runtime_controls"]
    }
    provider["config_warnings"] = warnings
    provider["is_runnable"] = True

    if warnings:
        return _mark_provider_misconfigured(provider, rules), merged_settings

    if configured_mode not in rules["available_execution_modes"]:
        warnings.append(
            "Unsupported execution mode '{0}' for {1}; expected one of: {2}.".format(
                configured_mode,
                provider["name"],
                ", ".join(rules["available_execution_modes"]),
            )
        )
        return _mark_provider_misconfigured(provider, rules), merged_settings

    live_mode = rules["live_mode"]
    if live_mode and configured_mode == live_mode:
        timeout_value = _validate_timeout(provider["name"], merged_settings.get("timeout_seconds"), warnings)
        cli_command = _normalize_string_setting(
            provider["name"],
            "cli_command",
            merged_settings.get("cli_command"),
            warnings,
            required=True,
        )
        merged_settings["model"] = _normalize_string_setting(
            provider["name"],
            "model",
            merged_settings.get("model"),
            warnings,
        )
        if "permission_mode" in rules["runtime_controls"]:
            merged_settings["permission_mode"] = _normalize_string_setting(
                provider["name"],
                "permission_mode",
                merged_settings.get("permission_mode"),
                warnings,
            )
        if "sandbox" in rules["runtime_controls"]:
            merged_settings["sandbox"] = _normalize_string_setting(
                provider["name"],
                "sandbox",
                merged_settings.get("sandbox"),
                warnings,
            )
        merged_settings["cli_command"] = cli_command
        merged_settings["timeout_seconds"] = timeout_value

        provider["runtime_controls"] = {
            key: merged_settings.get(key)
            for key in rules["runtime_controls"]
            if merged_settings.get(key) not in (None, "")
        }
        if warnings:
            return _mark_provider_misconfigured(provider, rules), merged_settings

        provider["execution_mode"] = live_mode
        provider["effective_execution_mode"] = live_mode
        provider["status"] = "configured"
        provider["supports_live_api"] = True
        provider["notes"] = rules["notes"]["configured"]
        return provider, merged_settings

    provider["configured_execution_mode"] = "local_simulation"
    provider["effective_execution_mode"] = "local_simulation"
    return provider, merged_settings


def _provider_run_history(connection, project_id):
    if connection is None:
        return {}

    if project_id is None:
        project = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()
        project_id = project["project_id"] if project else None
    if project_id is None:
        return {}

    summary_rows = connection.execute(
        """
        SELECT
            provider_type,
            COUNT(*) AS total_runs,
            SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active_runs,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_runs,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_runs,
            SUM(CASE WHEN status = 'timed_out' THEN 1 ELSE 0 END) AS timed_out_runs,
            SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_runs,
            MAX(started_at) AS last_run_at
        FROM sessions
        WHERE project_id = ?
        GROUP BY provider_type
        """,
        (project_id,),
    ).fetchall()
    summaries = {
        row["provider_type"]: {
            "total_runs": row["total_runs"],
            "active_runs": row["active_runs"],
            "completed_runs": row["completed_runs"],
            "failed_runs": row["failed_runs"],
            "timed_out_runs": row["timed_out_runs"],
            "cancelled_runs": row["cancelled_runs"],
            "last_run_at": row["last_run_at"],
            "timeout_failures": 0,
            "nonzero_exit_failures": 0,
            "runtime_failures": 0,
            "latest_failure_kind": None,
            "latest_failure_at": None,
        }
        for row in summary_rows
    }

    failure_rows = connection.execute(
        """
        SELECT
            sessions.provider_type,
            activity_log.created_at,
            json_extract(activity_log.details_json, '$.failure_kind') AS failure_kind
        FROM activity_log
        JOIN sessions
          ON sessions.session_id = json_extract(activity_log.details_json, '$.session_id')
        WHERE activity_log.project_id = ?
          AND activity_log.action = 'provider_adapter_failed'
        ORDER BY activity_log.created_at DESC, activity_log.rowid DESC
        """,
        (project_id,),
    ).fetchall()
    for row in failure_rows:
        summary = summaries.setdefault(
            row["provider_type"],
            {
                "total_runs": 0,
                "active_runs": 0,
                "completed_runs": 0,
                "failed_runs": 0,
                "timed_out_runs": 0,
                "cancelled_runs": 0,
                "last_run_at": None,
                "timeout_failures": 0,
                "nonzero_exit_failures": 0,
                "runtime_failures": 0,
                "latest_failure_kind": None,
                "latest_failure_at": None,
            },
        )
        failure_kind = row["failure_kind"] or "runtime_error"
        if failure_kind == "timeout":
            summary["timeout_failures"] += 1
        elif failure_kind == "nonzero_exit":
            summary["nonzero_exit_failures"] += 1
        else:
            summary["runtime_failures"] += 1
        if summary["latest_failure_at"] is None:
            summary["latest_failure_at"] = row["created_at"]
            summary["latest_failure_kind"] = failure_kind

    started_rows = connection.execute(
        """
        SELECT
            json_extract(details_json, '$.session_id') AS session_id,
            json_extract(details_json, '$.execution_mode') AS execution_mode,
            json_extract(details_json, '$.external_runtime') AS external_runtime
        FROM activity_log
        WHERE project_id = ?
          AND action = 'provider_adapter_started'
        """,
        (project_id,),
    ).fetchall()
    started_by_session = {
        row["session_id"]: {
            "execution_mode": row["execution_mode"],
            "external_runtime": row["external_runtime"],
        }
        for row in started_rows
        if row["session_id"]
    }

    failure_detail_rows = connection.execute(
        """
        SELECT
            ranked.session_id,
            ranked.failure_kind,
            ranked.failure_detail
        FROM (
            SELECT
                json_extract(details_json, '$.session_id') AS session_id,
                json_extract(details_json, '$.failure_kind') AS failure_kind,
                json_extract(details_json, '$.failure_detail') AS failure_detail,
                ROW_NUMBER() OVER (
                    PARTITION BY json_extract(details_json, '$.session_id')
                    ORDER BY rowid DESC
                ) AS session_rank
            FROM activity_log
            WHERE project_id = ?
              AND action = 'provider_adapter_failed'
        ) AS ranked
        WHERE ranked.session_rank = 1
        """,
        (project_id,),
    ).fetchall()
    failure_by_session = {
        row["session_id"]: {
            "failure_kind": row["failure_kind"] or "runtime_error",
            "failure_detail": row["failure_detail"],
        }
        for row in failure_detail_rows
        if row["session_id"]
    }

    recent_rows = connection.execute(
        """
        SELECT
            ranked.provider_type,
            ranked.session_id,
            ranked.task_id,
            ranked.task_title,
            ranked.agent_id,
            ranked.agent_name,
            ranked.status,
            ranked.progress_pct,
            ranked.status_message,
            ranked.started_at,
            ranked.ended_at
        FROM (
            SELECT
                sessions.provider_type,
                sessions.session_id,
                sessions.task_id,
                tasks.title AS task_title,
                sessions.agent_id,
                agents.display_name AS agent_name,
                sessions.status,
                sessions.progress_pct,
                sessions.status_message,
                sessions.started_at,
                sessions.ended_at,
                sessions.rowid AS session_rowid,
                ROW_NUMBER() OVER (
                    PARTITION BY sessions.provider_type
                    ORDER BY sessions.started_at DESC, sessions.rowid DESC
                ) AS provider_rank
            FROM sessions
            LEFT JOIN tasks ON tasks.task_id = sessions.task_id
            LEFT JOIN agents ON agents.agent_id = sessions.agent_id
            WHERE sessions.project_id = ?
        ) AS ranked
        WHERE ranked.provider_rank <= 3
        ORDER BY ranked.provider_type ASC, ranked.started_at DESC, ranked.session_rowid DESC
        """,
        (project_id,),
    ).fetchall()
    recent_runs = {}
    for row in recent_rows:
        entries = recent_runs.setdefault(row["provider_type"], [])
        started = started_by_session.get(row["session_id"], {})
        failure = failure_by_session.get(row["session_id"], {})
        entries.append(
            {
                "session_id": row["session_id"],
                "task_id": row["task_id"],
                "task_title": row["task_title"],
                "agent_id": row["agent_id"],
                "agent_name": row["agent_name"],
                "status": row["status"],
                "progress_pct": row["progress_pct"],
                "status_message": row["status_message"],
                "started_at": row["started_at"],
                "ended_at": row["ended_at"],
                "execution_mode": started.get("execution_mode"),
                "external_runtime": started.get("external_runtime"),
                "failure_kind": failure.get("failure_kind"),
                "failure_detail": failure.get("failure_detail"),
            }
        )
    return {"summaries": summaries, "recent_runs": recent_runs}


def _provider_run_targets(connection, project_id, limit=5):
    if connection is None:
        return []

    if project_id is None:
        project = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()
        project_id = project["project_id"] if project else None
    if project_id is None:
        return []

    rows = connection.execute(
        """
        SELECT
            tasks.project_id,
            tasks.task_id,
            tasks.title,
            tasks.status,
            tasks.priority,
            tasks.review_state,
            tasks.assigned_agent_id AS agent_id,
            agents.display_name AS agent_name,
            goals.title AS goal_title
        FROM tasks
        JOIN agents ON agents.agent_id = tasks.assigned_agent_id
        LEFT JOIN goals ON goals.goal_id = tasks.goal_id
        WHERE tasks.project_id = ?
          AND tasks.assigned_agent_id IS NOT NULL
          AND tasks.status IN ('planned', 'ready', 'assigned')
          AND (
              tasks.next_retry_at IS NULL
              OR datetime(tasks.next_retry_at) <= CURRENT_TIMESTAMP
          )
          AND EXISTS (
              SELECT 1
              FROM task_capability_grants grants
              WHERE grants.project_id = tasks.project_id
                AND grants.task_id = tasks.task_id
                AND grants.agent_id = tasks.assigned_agent_id
                AND grants.capability = 'execute'
                AND grants.revoked_at IS NULL
          )
        ORDER BY tasks.priority DESC, tasks.created_at ASC
        LIMIT ?
        """,
        (project_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def fetch_provider_runtime_overview(connection=None, project_id=None):
    return {
        "providers": list_provider_status(connection=connection, project_id=project_id),
        "run_targets": _provider_run_targets(connection, project_id),
    }


def update_provider_mode(connection, provider_id, actor_id, mode, project_id=None):
    provider = get_provider(provider_id)
    rules = PROVIDER_RUNTIME_RULES[provider_id]
    normalized_mode = "local_simulation" if mode in ("simulated", "local_simulation") else mode
    if normalized_mode not in rules["available_execution_modes"]:
        raise ValueError(
            "Unsupported execution mode '{0}' for {1}; expected one of: {2}.".format(
                normalized_mode,
                provider["name"],
                ", ".join(rules["available_execution_modes"]),
            )
        )

    if project_id is None:
        project = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()
    else:
        project = connection.execute(
            "SELECT project_id FROM projects WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    if project is None:
        raise ValueError("Project not found")
    project_id = project["project_id"]

    ensure_board_action_allowed(connection, actor_id, project_id, "configure_provider", "provider", provider_id)
    persisted_mode = "simulated" if normalized_mode == "local_simulation" else normalized_mode
    config_path = "$.providers.{0}.mode".format(provider_id)

    connection.execute(
        """
        UPDATE projects
        SET config_json = json_set(
                CASE
                    WHEN json_valid(config_json) THEN config_json
                    ELSE '{}'
                END,
                ?,
                ?
            ),
            updated_at = CURRENT_TIMESTAMP
        WHERE project_id = ?
        """,
        (config_path, persisted_mode, project_id),
    )
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, 'configure_provider', 'provider', ?, ?)
        """,
        (
            generate_id("audit"),
            project_id,
            actor_id,
            provider_id,
            json.dumps({"mode": persisted_mode}),
        ),
    )
    connection.commit()
    return get_provider_status(provider_id, connection=connection, project_id=project_id)


def _normalize_provider_setting_value(provider_name, setting_name, value):
    if setting_name == "timeout_seconds":
        try:
            timeout_value = int(value)
        except (TypeError, ValueError):
            raise ValueError("{0} timeout_seconds must be a positive integer.".format(provider_name))
        if timeout_value <= 0:
            raise ValueError("{0} timeout_seconds must be greater than zero.".format(provider_name))
        return timeout_value

    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("{0} {1} must be a string.".format(provider_name, setting_name))
    return value.strip()


def update_provider_settings(connection, provider_id, actor_id, settings, project_id=None):
    provider = get_provider(provider_id)
    rules = PROVIDER_RUNTIME_RULES[provider_id]
    allowed_keys = set(rules["runtime_controls"])
    requested_settings = settings or {}
    unknown_keys = sorted(set(requested_settings) - allowed_keys)
    if unknown_keys:
        raise ValueError(
            "Unsupported provider settings for {0}: {1}.".format(
                provider["name"],
                ", ".join(unknown_keys),
            )
        )

    if project_id is None:
        project = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()
    else:
        project = connection.execute(
            "SELECT project_id FROM projects WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    if project is None:
        raise ValueError("Project not found")
    project_id = project["project_id"]

    ensure_board_action_allowed(connection, actor_id, project_id, "configure_provider", "provider", provider_id)

    normalized_updates = {}
    for key, value in requested_settings.items():
        normalized_updates[key] = _normalize_provider_setting_value(provider["name"], key, value)

    if not normalized_updates:
        return get_provider_status(provider_id, connection=connection, project_id=project_id)

    json_set_parts = []
    params = []
    for key, value in normalized_updates.items():
        json_set_parts.append("?, ?")
        params.extend(["$.providers.{0}.{1}".format(provider_id, key), value])

    connection.execute(
        """
        UPDATE projects
        SET config_json = json_set(
                CASE
                    WHEN json_valid(config_json) THEN config_json
                    ELSE '{{}}'
                END,
                {0}
            ),
            updated_at = CURRENT_TIMESTAMP
        WHERE project_id = ?
        """.format(", ".join(json_set_parts)),
        tuple(params + [project_id]),
    )
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, 'configure_provider', 'provider', ?, ?)
        """,
        (
            generate_id("audit"),
            project_id,
            actor_id,
            provider_id,
            json.dumps({"settings": normalized_updates}),
        ),
    )
    connection.commit()
    return get_provider_status(provider_id, connection=connection, project_id=project_id)


def get_provider_status(provider_id, connection=None, project_id=None):
    provider = get_provider(provider_id)
    provider_config = _project_provider_config(connection, project_id)
    resolved_provider, _ = _resolve_provider_status(provider, provider_config.get(provider_id) or {})
    return resolved_provider


def get_provider_runtime_settings(provider_id, connection=None, project_id=None):
    provider = get_provider(provider_id)
    provider_config = _project_provider_config(connection, project_id)
    resolved_provider, resolved_settings = _resolve_provider_status(provider, provider_config.get(provider_id) or {})
    return resolved_provider, resolved_settings


def list_provider_status(connection=None, project_id=None):
    provider_config = _project_provider_config(connection, project_id)
    run_history = _provider_run_history(connection, project_id)
    providers = []
    for provider in list_providers():
        resolved_provider, _ = _resolve_provider_status(provider, provider_config.get(provider["id"]) or {})
        resolved_provider["run_summary"] = run_history.get("summaries", {}).get(
            provider["id"],
            {
                "total_runs": 0,
                "active_runs": 0,
                "completed_runs": 0,
                "failed_runs": 0,
                "timed_out_runs": 0,
                "cancelled_runs": 0,
                "last_run_at": None,
                "timeout_failures": 0,
                "nonzero_exit_failures": 0,
                "runtime_failures": 0,
                "latest_failure_kind": None,
                "latest_failure_at": None,
            },
        )
        resolved_provider["recent_runs"] = run_history.get("recent_runs", {}).get(provider["id"], [])
        providers.append(resolved_provider)
    return providers
