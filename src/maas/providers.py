"""Provider registry and metadata for the initial runtime slice."""

from copy import deepcopy
import json

from maas.config import DEFAULT_PROVIDER_SETTINGS


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


def _resolve_provider_status(provider, config):
    rules = PROVIDER_RUNTIME_RULES[provider["id"]]
    merged_settings = _merged_provider_settings(provider["id"], config)
    raw_mode = (merged_settings.get("mode") or "local_simulation").strip() or "local_simulation"
    configured_mode = "local_simulation" if raw_mode in ("simulated", "local_simulation") else raw_mode
    warnings = []

    provider["available_execution_modes"] = list(rules["available_execution_modes"])
    provider["configured_execution_mode"] = configured_mode
    provider["effective_execution_mode"] = provider["execution_mode"]
    provider["runtime_controls"] = {}
    provider["config_warnings"] = warnings
    provider["is_runnable"] = True

    if configured_mode not in rules["available_execution_modes"]:
        warnings.append(
            "Unsupported execution mode '{0}' for {1}; expected one of: {2}.".format(
                configured_mode,
                provider["name"],
                ", ".join(rules["available_execution_modes"]),
            )
        )
        provider["status"] = "misconfigured"
        provider["execution_mode"] = "unavailable"
        provider["effective_execution_mode"] = None
        provider["supports_live_api"] = False
        provider["notes"] = rules["notes"]["misconfigured"]
        provider["is_runnable"] = False
        return provider, merged_settings

    live_mode = rules["live_mode"]
    if live_mode and configured_mode == live_mode:
        timeout_value = _validate_timeout(provider["name"], merged_settings.get("timeout_seconds"), warnings)
        cli_command = (merged_settings.get("cli_command") or "").strip()
        if not cli_command:
            warnings.append("{0} cli_command must not be empty when {1} mode is enabled.".format(provider["name"], live_mode))
        merged_settings["cli_command"] = cli_command
        merged_settings["timeout_seconds"] = timeout_value

        provider["runtime_controls"] = {
            key: merged_settings.get(key)
            for key in rules["runtime_controls"]
            if merged_settings.get(key) not in (None, "")
        }
        if warnings:
            provider["status"] = "misconfigured"
            provider["execution_mode"] = "unavailable"
            provider["effective_execution_mode"] = None
            provider["supports_live_api"] = False
            provider["notes"] = rules["notes"]["misconfigured"]
            provider["is_runnable"] = False
            return provider, merged_settings

        provider["execution_mode"] = live_mode
        provider["effective_execution_mode"] = live_mode
        provider["status"] = "configured"
        provider["supports_live_api"] = True
        provider["notes"] = rules["notes"]["configured"]
        return provider, merged_settings

    provider["configured_execution_mode"] = "local_simulation"
    provider["effective_execution_mode"] = "local_simulation"
    return provider, merged_settings


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
    providers = []
    for provider in list_providers():
        resolved_provider, _ = _resolve_provider_status(provider, provider_config.get(provider["id"]) or {})
        providers.append(resolved_provider)
    return providers
