"""Provider adapter execution helpers."""

import os

from maas.providers import get_provider, list_providers
from maas.services.lifecycle import end_session, heartbeat, log_activity, produce_artifact, start_session


def _task_title(connection, task_id):
    row = connection.execute("SELECT title FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    return row["title"] if row else task_id


def _provider_artifact_payload(provider, task_title, task_id):
    if provider["id"] == "claude_code":
        return {
            "artifact_type": provider["default_artifact_type"],
            "content": (
                "# Claude Code Runtime Report\n\n"
                "- Task: {0}\n"
                "- Task ID: {1}\n"
                "- Provider: Claude Code (simulated)\n"
                "- Outcome: Generated local execution summary and artifact.\n"
            ).format(task_title, task_id),
            "status_message": "Claude Code adapter completed simulated execution",
        }
    if provider["id"] == "openai_codex":
        return {
            "artifact_type": provider["default_artifact_type"],
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
        "artifact_type": provider["default_artifact_type"],
        "content": (
            "# Python Script Runtime Report\n\n"
            "- Task: {0}\n"
            "- Task ID: {1}\n"
            "- Provider: Python Script (local simulation)\n"
            "- Outcome: Generated local execution summary and artifact.\n"
        ).format(task_title, task_id),
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


def _provider_activity_details(provider, phase, **extra):
    details = {
        "provider_type": provider["id"],
        "provider_name": provider["name"],
        "provider_kind": provider["kind"],
        "execution_mode": provider["execution_mode"],
        "lifecycle_version": provider["lifecycle_version"],
        "phase": phase,
    }
    details.update(extra)
    return details


def _log_provider_phase(connection, project_id, agent_id, task_id, provider, action, phase, description, **details):
    log_activity(
        connection,
        project_id=project_id,
        agent_id=agent_id,
        task_id=task_id,
        action=action,
        category="runtime",
        description=description,
        details=_provider_activity_details(provider, phase, **details),
    )


def _cleanup_untracked_artifact(artifact_full_path):
    if artifact_full_path and os.path.exists(artifact_full_path):
        try:
            os.remove(artifact_full_path)
        except OSError:
            return


def run_provider_task(connection, project_paths, project_id, agent_id, task_id, provider_type, artifact_path=None):
    provider = get_provider(provider_type)
    task_title = _task_title(connection, task_id)
    artifact_payload = _provider_artifact_payload(provider, task_title, task_id)
    artifact_full_path = _resolve_artifact_path(project_paths, provider_type, task_id, artifact_path)
    session_id = None
    artifact_id = None
    session_id = start_session(
        connection,
        project_id=project_id,
        agent_id=agent_id,
        task_id=task_id,
        provider_type=provider_type,
        status_message="{0} adapter started".format(provider["name"]),
    )
    try:
        _log_provider_phase(
            connection,
            project_id,
            agent_id,
            task_id,
            provider,
            action="provider_adapter_started",
            phase="session_started",
            description="{0} adapter started local execution.".format(provider["name"]),
            session_id=session_id,
            task_title=task_title,
            progress_pct=0,
        )
        os.makedirs(os.path.dirname(artifact_full_path), exist_ok=True)
        heartbeat(connection, session_id, 15, "{0} adapter prepared the local workspace".format(provider["name"]))
        _log_provider_phase(
            connection,
            project_id,
            agent_id,
            task_id,
            provider,
            action="provider_workspace_prepared",
            phase="workspace_prepared",
            description="{0} adapter prepared the local workspace.".format(provider["name"]),
            session_id=session_id,
            progress_pct=15,
            artifact_path=artifact_full_path,
        )
        heartbeat(connection, session_id, 60, "{0} adapter is executing simulated work".format(provider["name"]))
        _log_provider_phase(
            connection,
            project_id,
            agent_id,
            task_id,
            provider,
            action="provider_execution_progress",
            phase="execution_running",
            description="{0} adapter is executing the simulated provider run.".format(provider["name"]),
            session_id=session_id,
            progress_pct=60,
            artifact_path=artifact_full_path,
            artifact_type=artifact_payload["artifact_type"],
        )
        with open(artifact_full_path, "w", encoding="utf-8") as handle:
            handle.write(artifact_payload["content"])

        artifact_id = produce_artifact(
            connection,
            project_id=project_id,
            session_id=session_id,
            task_id=task_id,
            artifact_type=artifact_payload["artifact_type"],
            path=artifact_full_path,
            metadata={
                "provider_type": provider["id"],
                "provider_name": provider["name"],
                "provider_kind": provider["kind"],
                "execution_mode": provider["execution_mode"],
                "lifecycle_version": provider["lifecycle_version"],
                "lifecycle_phases": provider["lifecycle_phases"],
            },
        )
        heartbeat(connection, session_id, 90, "{0} adapter recorded the runtime artifact".format(provider["name"]))
        _log_provider_phase(
            connection,
            project_id,
            agent_id,
            task_id,
            provider,
            action="provider_artifact_recorded",
            phase="artifact_recorded",
            description="{0} adapter recorded the runtime artifact.".format(provider["name"]),
            session_id=session_id,
            artifact_id=artifact_id,
            artifact_path=artifact_full_path,
            artifact_type=artifact_payload["artifact_type"],
            progress_pct=90,
        )
        heartbeat(connection, session_id, 100, artifact_payload["status_message"])
        _log_provider_phase(
            connection,
            project_id,
            agent_id,
            task_id,
            provider,
            action="provider_adapter_completed",
            phase="session_completed",
            description=artifact_payload["status_message"],
            session_id=session_id,
            artifact_id=artifact_id,
            artifact_path=artifact_full_path,
            artifact_type=artifact_payload["artifact_type"],
            progress_pct=100,
        )
        end_session(connection, session_id, "completed", artifact_payload["status_message"], project_paths=project_paths)
    except Exception as exc:
        _cleanup_untracked_artifact(artifact_full_path if artifact_id is None else None)
        failure_summary = "{0} adapter failed: {1}".format(provider["name"], exc)
        if session_id is not None:
            try:
                log_activity(
                    connection,
                    project_id=project_id,
                    agent_id=agent_id,
                    task_id=task_id,
                    action="provider_adapter_failed",
                    category="runtime",
                    description=failure_summary,
                    severity="error",
                    details=_provider_activity_details(
                        provider,
                        "session_failed",
                        session_id=session_id,
                        error=str(exc),
                        progress_pct=100,
                    ),
                )
            except Exception:
                pass
            try:
                end_session(connection, session_id, "failed", failure_summary, project_paths=project_paths)
            except Exception:
                pass
        raise
    return {
        "session_id": session_id,
        "artifact_id": artifact_id,
        "artifact_path": artifact_full_path,
        "provider": provider,
        "execution": {
            "execution_mode": provider["execution_mode"],
            "lifecycle_version": provider["lifecycle_version"],
            "lifecycle_phases": provider["lifecycle_phases"],
            "artifact_type": artifact_payload["artifact_type"],
        },
    }


def list_provider_runtime_status():
    return list_providers()
