"""Project config loading and defaults."""

from copy import deepcopy
import os

import yaml


DEFAULT_PROJECT_TYPE = "custom"


DEFAULT_PROVIDER_SETTINGS = {
    "claude_code": {
        "mode": "simulated",
        "cli_command": "claude",
        "timeout_seconds": 300,
        "permission_mode": "acceptEdits",
        "model": "",
    },
    "openai_codex": {
        "mode": "simulated",
        "cli_command": "codex",
        "timeout_seconds": 300,
        "sandbox": "workspace-write",
        "model": "",
    },
}


def build_default_project_config(name, description, project_type, onboarding_mode="greenfield", discovery_summary=None):
    return {
        "project": {
            "name": name,
            "description": description,
            "type": project_type or DEFAULT_PROJECT_TYPE,
        },
        "onboarding": {
            "mode": onboarding_mode or "greenfield",
            "discovery_summary": discovery_summary or {},
            "review_status": "review_pending" if onboarding_mode == "brownfield" else "not_applicable",
        },
        "agent_roles": [
            {
                "role": "allocator",
                "description": "Owns planning, prioritization, and assignment.",
                "permissions": {"board_actions": True, "db_read": ["*"], "db_write": ["*"]},
            },
            {
                "role": "researcher",
                "description": "Explores problem space and creates supporting artifacts.",
                "permissions": {"board_actions": False, "db_read": ["*"], "db_write": ["activity_log", "artifacts"]},
            },
            {
                "role": "builder",
                "description": "Implements tasks and produces runnable outputs.",
                "permissions": {"board_actions": False, "db_read": ["*"], "db_write": ["activity_log", "artifacts"]},
            },
            {
                "role": "reviewer",
                "description": "Validates work and resolves review items.",
                "permissions": {"board_actions": True, "db_read": ["*"], "db_write": ["activity_log", "tasks"]},
            },
        ],
        "plan_templates": [
            {"name": "Research Investigation", "kind": "universal"},
            {"name": "Feature Development", "kind": "universal"},
            {"name": "Bug Fix", "kind": "universal"},
        ],
        "acceptance_defaults": {
            "task": ["artifact_exists"],
            "goal": ["artifact_exists", "human_review"],
        },
        "state_machines": {
            "task": [
                "planned",
                "ready",
                "assigned",
                "in_progress",
                "review",
                "blocked",
                "done",
                "cancelled",
            ]
        },
        "guardrails": {
            "max_session_cost_usd": 50,
            "heartbeat_stale_seconds": 90,
            "board_filters": ["agent", "goal", "priority", "blocked_only", "review_only"],
        },
        "recovery": {
            "auto_retry_timeout_sessions": False,
            "auto_retry_failed_sessions": False,
            "auto_recover_blocked_tasks": False,
            "auto_dlq_retry_exhausted_tasks": False,
            "max_timed_out_retries": 1,
            "max_failed_session_retries": 1,
            "timed_out_retry_cooldown_seconds": 60,
            "failed_session_retry_cooldown_seconds": 120,
            "recover_and_requeue_cooldown_seconds": 30,
            "retry_backoff_multiplier": 2,
            "retry_backoff_max_seconds": 900,
        },
        "providers": deepcopy(DEFAULT_PROVIDER_SETTINGS),
    }


def load_project_config(path):
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def save_project_config(path, config):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)
