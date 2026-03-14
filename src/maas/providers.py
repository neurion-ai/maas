"""Minimal provider registry for the initial runtime slice."""

PROVIDERS = [
    {
        "id": "claude_code",
        "name": "Claude Code",
        "kind": "interactive_cli",
        "status": "planned",
        "notes": "Uses local CLI invocation with lifecycle hooks.",
    },
    {
        "id": "openai_codex",
        "name": "OpenAI Codex",
        "kind": "api_runtime",
        "status": "planned",
        "notes": "Uses API-driven execution with lifecycle sync.",
    },
    {
        "id": "python_script",
        "name": "Python Script",
        "kind": "local_worker",
        "status": "available",
        "notes": "Reference runtime for the scaffold and local simulations.",
    },
]


def list_providers():
    return list(PROVIDERS)

