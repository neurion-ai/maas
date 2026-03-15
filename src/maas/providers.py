"""Provider registry and metadata for the initial runtime slice."""

from copy import deepcopy


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
