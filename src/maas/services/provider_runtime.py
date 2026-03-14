"""Provider adapter execution helpers."""

import os

from maas.providers import get_provider, list_providers
from maas.services.lifecycle import end_session, heartbeat, log_activity, produce_artifact, start_session


def _task_title(connection, task_id):
    row = connection.execute("SELECT title FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    return row["title"] if row else task_id


def _provider_artifact_payload(provider_type, task_title, task_id):
    if provider_type == "claude_code":
        return {
            "artifact_type": "provider_report",
            "content": (
                "# Claude Code Runtime Report\n\n"
                "- Task: {0}\n"
                "- Task ID: {1}\n"
                "- Provider: Claude Code (simulated)\n"
                "- Outcome: Generated local execution summary and artifact.\n"
            ).format(task_title, task_id),
            "status_message": "Claude Code adapter completed simulated execution",
        }
    if provider_type == "openai_codex":
        return {
            "artifact_type": "provider_report",
            "content": (
                "# OpenAI Codex Runtime Report\n\n"
                "- Task: {0}\n"
                "- Task ID: {1}\n"
                "- Provider: OpenAI Codex (simulated)\n"
                "- Outcome: Generated local execution summary and artifact.\n"
            ).format(task_title, task_id),
            "status_message": "OpenAI Codex adapter completed simulated execution",
        }
    return {
        "artifact_type": "text",
        "content": "MAAS worker artifact for task {0}\n".format(task_id),
        "status_message": "Python Script adapter completed simulated execution",
    }


def _resolve_artifact_path(project_paths, provider_type, task_id, artifact_path):
    default_relative = "{0}-{1}.txt".format(provider_type, task_id)
    requested_path = artifact_path or default_relative
    if os.path.isabs(requested_path):
        raise ValueError("Artifact path must stay within .maas/artifacts")
    normalized_relative = os.path.normpath(requested_path)
    if normalized_relative in (".", ""):
        normalized_relative = default_relative
    if normalized_relative.startswith(".."):
        raise ValueError("Artifact path must stay within .maas/artifacts")

    artifact_root = os.path.abspath(project_paths.artifacts_dir)
    artifact_full_path = os.path.abspath(os.path.join(artifact_root, normalized_relative))
    if os.path.commonpath([artifact_root, artifact_full_path]) != artifact_root:
        raise ValueError("Artifact path must stay within .maas/artifacts")
    return artifact_full_path


def run_provider_task(connection, project_paths, project_id, agent_id, task_id, provider_type, artifact_path=None):
    provider = get_provider(provider_type)
    task_title = _task_title(connection, task_id)
    artifact_payload = _provider_artifact_payload(provider_type, task_title, task_id)
    session_id = start_session(
        connection,
        project_id=project_id,
        agent_id=agent_id,
        task_id=task_id,
        provider_type=provider_type,
        status_message="{0} adapter started".format(provider["name"]),
    )
    artifact_full_path = _resolve_artifact_path(project_paths, provider_type, task_id, artifact_path)
    os.makedirs(os.path.dirname(artifact_full_path), exist_ok=True)
    with open(artifact_full_path, "w", encoding="utf-8") as handle:
        handle.write(artifact_payload["content"])

    log_activity(
        connection,
        project_id=project_id,
        agent_id=agent_id,
        task_id=task_id,
        action="provider_adapter_started",
        category="runtime",
        description="{0} adapter started local execution.".format(provider["name"]),
        details={"provider_type": provider_type},
    )
    heartbeat(connection, session_id, 50, "{0} adapter is halfway through simulated work".format(provider["name"]))
    artifact_id = produce_artifact(
        connection,
        project_id=project_id,
        session_id=session_id,
        task_id=task_id,
        artifact_type=artifact_payload["artifact_type"],
        path=artifact_full_path,
        metadata={"provider_type": provider_type, "provider_name": provider["name"]},
    )
    log_activity(
        connection,
        project_id=project_id,
        agent_id=agent_id,
        task_id=task_id,
        action="provider_adapter_completed",
        category="runtime",
        description=artifact_payload["status_message"],
        details={"provider_type": provider_type, "artifact_id": artifact_id},
    )
    end_session(connection, session_id, "completed", artifact_payload["status_message"], project_paths=project_paths)
    return {
        "session_id": session_id,
        "artifact_id": artifact_id,
        "artifact_path": artifact_full_path,
        "provider": provider,
    }


def list_provider_runtime_status():
    providers = list_providers()
    for provider in providers:
        provider["execution_mode"] = "local_simulation"
    return providers
