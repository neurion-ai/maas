"""Provider registry and metadata for the initial runtime slice."""

from copy import deepcopy


PROVIDER_REGISTRY = {
    "claude_code": {
        "id": "claude_code",
        "name": "Claude Code",
        "kind": "interactive_cli",
        "status": "simulated",
        "supports_worker_execution": True,
        "supports_live_api": False,
        "notes": "Simulated local adapter with provider-specific runtime artifacts.",
    },
    "openai_codex": {
        "id": "openai_codex",
        "name": "OpenAI Codex",
        "kind": "api_runtime",
        "status": "simulated",
        "supports_worker_execution": True,
        "supports_live_api": False,
        "notes": "Simulated API-style adapter with provider-specific runtime artifacts.",
    },
    "python_script": {
        "id": "python_script",
        "name": "Python Script",
        "kind": "local_worker",
        "status": "available",
        "supports_worker_execution": True,
        "supports_live_api": False,
        "notes": "Reference local runtime used for scaffolded execution.",
    },
}


def list_providers():
    return [deepcopy(provider) for provider in PROVIDER_REGISTRY.values()]


def get_provider(provider_id):
    provider = PROVIDER_REGISTRY.get(provider_id)
    if provider is None:
        raise ValueError("Unsupported provider type: {0}".format(provider_id))
    return deepcopy(provider)
