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
        "job_limit_per_pass": 2,
        "queue_paused": False,
        "model": "",
    },
    "openai_codex": {
        "mode": "simulated",
        "cli_command": "codex",
        "timeout_seconds": 300,
        "sandbox": "workspace-write",
        "job_limit_per_pass": 2,
        "queue_paused": False,
        "model": "",
    },
    "python_script": {
        "job_limit_per_pass": 2,
        "queue_paused": False,
    },
}


DEFAULT_AUTOPILOT_SETTINGS = {
    "enabled": False,
    "interval_seconds": 20,
    "allocate_limit": 6,
    "provider_job_limit": 4,
    "auto_launch_assigned_work": True,
    "process_notifications": True,
    "notification_batch_limit": 5,
    "schedule_window_start_hour_utc": None,
    "schedule_window_end_hour_utc": None,
    "stop_when_doctor_blocked": True,
    "max_review_queue": 0,
    "max_blocked_queue": 0,
    "max_idle_cycles_before_alert": 6,
    "max_stale_runs": 0,
    "max_repeated_failure_incidents": 0,
    "max_notification_failures": 0,
}


PROJECT_TEMPLATES = [
    {
        "id": "scratch-codex",
        "name": "Scratch Codex workspace",
        "description": "Fresh greenfield workspace with live-ready Codex defaults and low operator friction.",
        "mode": "greenfield",
        "project_type": "custom",
        "create_source_root": True,
        "overrides": {
            "provider_capacity": {
                "queue_mode": "running",
                "max_running_jobs": 2,
                "preferred_provider_id": "openai_codex",
            },
            "review_policy": {
                "auto_approve_low_risk": True,
                "max_priority_for_auto_approve": 69,
                "require_verification_pass": True,
            },
            "autopilot": {
                "enabled": False,
                "interval_seconds": 20,
                "allocate_limit": 6,
                "provider_job_limit": 4,
                "auto_launch_assigned_work": True,
                "process_notifications": True,
                "notification_batch_limit": 5,
            },
        },
    },
    {
        "id": "import-codex",
        "name": "Import existing repo",
        "description": "Brownfield import tuned for repo discovery, manual onboarding review, and live Codex follow-up.",
        "mode": "brownfield",
        "project_type": "custom",
        "create_source_root": False,
        "overrides": {
            "provider_capacity": {
                "queue_mode": "running",
                "max_running_jobs": 2,
                "preferred_provider_id": "openai_codex",
            },
            "review_policy": {
                "auto_approve_low_risk": False,
                "max_priority_for_auto_approve": 0,
                "require_verification_pass": True,
            },
            "autopilot": {
                "enabled": False,
                "interval_seconds": 20,
                "allocate_limit": 6,
                "provider_job_limit": 4,
                "auto_launch_assigned_work": True,
                "process_notifications": True,
                "notification_batch_limit": 5,
            },
        },
    },
    {
        "id": "research-loop",
        "name": "Research loop",
        "description": "Longer-running Codex project with conservative review and more queued parallelism.",
        "mode": "greenfield",
        "project_type": "research",
        "create_source_root": True,
        "overrides": {
            "provider_capacity": {
                "queue_mode": "running",
                "max_running_jobs": 3,
                "preferred_provider_id": "openai_codex",
            },
            "review_policy": {
                "auto_approve_low_risk": True,
                "max_priority_for_auto_approve": 55,
                "require_verification_pass": True,
            },
            "autopilot": {
                "enabled": False,
                "interval_seconds": 30,
                "allocate_limit": 8,
                "provider_job_limit": 4,
                "auto_launch_assigned_work": True,
                "process_notifications": True,
                "notification_batch_limit": 8,
            },
        },
    },
]


def _deep_merge(base, overrides):
    merged = deepcopy(base)
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def list_project_templates():
    return [
        {
            "id": template["id"],
            "name": template["name"],
            "description": template["description"],
            "mode": template["mode"],
            "project_type": template["project_type"],
            "create_source_root": template["create_source_root"],
        }
        for template in PROJECT_TEMPLATES
    ]


def resolve_project_template(template_id):
    for template in PROJECT_TEMPLATES:
        if template["id"] == template_id:
            return deepcopy(template)
    raise ValueError("project template not found")


def build_default_project_config(
    name,
    description,
    project_type,
    onboarding_mode="greenfield",
    discovery_summary=None,
    source_root=None,
):
    return {
        "project": {
            "name": name,
            "description": description,
            "type": project_type or DEFAULT_PROJECT_TYPE,
            "source_root": source_root or "",
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
        "provider_capacity": {
            "queue_mode": "running",
            "max_running_jobs": 2,
            "preferred_provider_id": "openai_codex",
        },
        "autopilot": deepcopy(DEFAULT_AUTOPILOT_SETTINGS),
        "review_policy": {
            "auto_approve_low_risk": True,
            "max_priority_for_auto_approve": 69,
            "require_verification_pass": True,
        },
        "risk_policy": {
            "priority_threshold": 101,
            "sensitive_path_prefixes": [],
        },
        "runtime_quotas": {
            "daily_run_limit": 0,
            "daily_live_run_limit": 0,
            "daily_runtime_seconds_limit": 0,
            "max_task_session_attempts": 0,
        },
    }


def build_project_config_from_template(
    template_id,
    name,
    description,
    project_type,
    onboarding_mode="greenfield",
    discovery_summary=None,
    source_root=None,
):
    template = resolve_project_template(template_id)
    config = build_default_project_config(
        name=name,
        description=description,
        project_type=project_type or template.get("project_type") or DEFAULT_PROJECT_TYPE,
        onboarding_mode=onboarding_mode or template.get("mode") or "greenfield",
        discovery_summary=discovery_summary,
        source_root=source_root,
    )
    config = _deep_merge(config, template.get("overrides") or {})
    project_block = dict(config.get("project") or {})
    project_block["name"] = name
    project_block["description"] = description
    project_block["type"] = project_type or template.get("project_type") or DEFAULT_PROJECT_TYPE
    project_block["source_root"] = source_root or ""
    project_block["template_id"] = template["id"]
    config["project"] = project_block
    return config


def load_project_config(path):
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def save_project_config(path, config):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)
