"""Provider registry and metadata for the initial runtime slice."""

from copy import deepcopy
import json


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


def list_provider_status(connection=None, project_id=None):
    providers = list_providers()
    provider_config = _project_provider_config(connection, project_id)
    for provider in providers:
        config = provider_config.get(provider["id"]) or {}
        configured_mode = config.get("mode")
        if configured_mode:
            if configured_mode in ("simulated", "local_simulation"):
                provider["configured_execution_mode"] = "local_simulation"
            else:
                provider["configured_execution_mode"] = configured_mode
            if provider["id"] == "openai_codex" and configured_mode == "codex_cli":
                provider["execution_mode"] = "codex_cli"
                provider["status"] = "configured"
                provider["supports_live_api"] = True
                provider["notes"] = "Local Codex CLI integration enabled by project config."
        else:
            provider["configured_execution_mode"] = provider["execution_mode"]
    return providers
