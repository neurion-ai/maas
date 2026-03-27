"""Shared operator action payload helpers for control-loop read models."""

from __future__ import annotations

import json


def operator_action(action, label, resource_type, resource_id, payload=None, related_task_id=None):
    item = {
        "action": action,
        "label": label,
        "resource_type": resource_type,
        "resource_id": resource_id,
    }
    if payload:
        item["payload"] = payload
    if related_task_id:
        item["related_task_id"] = related_task_id
    return item


def project_launch_posture_action(
    project_id,
    label,
    queue_mode,
    max_running_jobs,
    preferred_provider_id=None,
):
    return operator_action(
        "update_launch_posture",
        label,
        "project",
        project_id,
        payload={
            "queue_mode": queue_mode,
            "max_running_jobs": max(0, int(max_running_jobs or 0)),
            "preferred_provider_id": preferred_provider_id,
        },
    )


def project_autopilot_action(project_id, label, policy):
    return operator_action(
        "update_autopilot",
        label,
        "project",
        project_id,
        payload=dict(policy or {}),
    )


def project_orchestrator_action(
    project_id,
    label="Run next cycle",
    allocate_limit=6,
    provider_job_limit=4,
    auto_launch_assigned_work=True,
):
    return operator_action(
        "run_orchestrator",
        label,
        "project",
        project_id,
        payload={
            "allocate_limit": max(1, int(allocate_limit or 1)),
            "provider_job_limit": max(1, int(provider_job_limit or 1)),
            "auto_launch_assigned_work": bool(auto_launch_assigned_work),
        },
    )


def task_operator_action(action, label, task_id):
    return operator_action(action, label, "task", task_id)


def quarantine_operator_action(action, label, queue_id, related_task_id=None):
    return operator_action(
        action,
        label,
        "quarantine",
        queue_id,
        related_task_id=related_task_id,
    )


def run_operator_action(action, label, session_id, related_task_id=None):
    return operator_action(
        action,
        label,
        "run",
        session_id,
        related_task_id=related_task_id,
    )


def dedupe_operator_actions(actions):
    items = []
    seen = set()
    for action in actions or []:
        if not isinstance(action, dict):
            continue
        payload = action.get("payload")
        key = (
            action.get("action"),
            action.get("resource_type"),
            action.get("resource_id"),
            action.get("related_task_id"),
            json.dumps(payload, sort_keys=True) if isinstance(payload, dict) else None,
        )
        if key in seen:
            continue
        seen.add(key)
        items.append(action)
    return items
