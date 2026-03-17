"""Provider adapter execution helpers."""

import os
import shutil
import subprocess
import tempfile

from maas.providers import (
    fetch_provider_runtime_overview,
    get_provider_runtime_settings,
    list_provider_status,
    update_provider_mode,
    update_provider_settings,
)
from maas.services.lifecycle import end_session, heartbeat, log_activity, produce_artifact, start_session
from maas.services.security import ensure_board_action_allowed


class ProviderRuntimeFailure(RuntimeError):
    def __init__(self, kind, message, **details):
        super().__init__(message)
        self.kind = kind
        self.details = details


SAFE_RUNTIME_ENV_KEYS = (
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LOGNAME",
    "PATH",
    "SHELL",
    "SYSTEMROOT",
    "TERM",
    "TMP",
    "TEMP",
    "TMPDIR",
    "USER",
    "WINDIR",
    "PATHEXT",
    "COMSPEC",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "XDG_DATA_HOME",
)

PROVIDER_RUNTIME_ENV_KEYS = {
    "claude_code": ("ANTHROPIC_API_KEY",),
    "openai_codex": ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORGANIZATION", "OPENAI_PROJECT_ID"),
}

PROVIDER_REQUIRED_ENV_KEYS = {
    "claude_code": ("ANTHROPIC_API_KEY",),
    "openai_codex": ("OPENAI_API_KEY",),
}


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


def _runtime_env(project_paths, provider):
    runtime_tmp_dir = os.path.join(project_paths.runtime_dir, "tmp")
    os.makedirs(runtime_tmp_dir, exist_ok=True)
    env = {}
    for key in SAFE_RUNTIME_ENV_KEYS:
        value = os.environ.get(key)
        if value:
            env[key] = value
    for key in PROVIDER_RUNTIME_ENV_KEYS.get(provider["id"], ()):
        value = os.environ.get(key)
        if value:
            env[key] = value
    env["MAAS_PROJECT_ROOT"] = project_paths.root
    env["MAAS_RUNTIME_ROOT"] = project_paths.runtime_dir
    env["MAAS_ARTIFACT_ROOT"] = project_paths.artifacts_dir
    env["TMPDIR"] = runtime_tmp_dir
    env["TMP"] = runtime_tmp_dir
    env["TEMP"] = runtime_tmp_dir
    return env


def _provider_preflight_command(provider_id, provider_settings):
    cli_command = (provider_settings.get("cli_command") or provider_id).strip()
    if provider_id == "claude_code":
        return [cli_command, "--version"]
    if provider_id == "openai_codex":
        return [cli_command, "--version"]
    return []


def _record_provider_preflight(
    connection,
    project_id,
    actor_id,
    provider,
    description,
    preflight_status,
    issues=None,
    execution_mode=None,
    external_runtime=None,
):
    log_activity(
        connection,
        project_id=project_id,
        agent_id=actor_id,
        task_id=None,
        action="provider_preflight_checked",
        category="runtime",
        description=description,
        severity="info" if preflight_status in ("passed", "simulation_ready") else "warning",
        details=_provider_activity_details(
            provider,
            "preflight_checked",
            preflight_status=preflight_status,
            issues=issues or [],
            execution_mode=execution_mode,
            external_runtime=external_runtime,
        ),
    )


def run_provider_preflight(connection, project_paths, provider_id, actor_id, project_id=None):
    scoped_project_id = project_id
    if scoped_project_id is None:
        row = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()
        if row is None:
            raise ValueError("Project not found")
        scoped_project_id = row["project_id"]
    ensure_board_action_allowed(connection, actor_id, scoped_project_id, "check_provider_runtime", "provider", provider_id)
    providers = list_provider_status(connection=connection, project_id=scoped_project_id)
    provider = next((item for item in providers if item["id"] == provider_id), None)
    if provider is None:
        raise ValueError("Unsupported provider type: {0}".format(provider_id))

    provider, provider_settings = get_provider_runtime_settings(
        provider_id,
        connection=connection,
        project_id=scoped_project_id,
    )
    if provider["configured_execution_mode"] == "local_simulation":
        description = "{0} preflight passed in local simulation mode.".format(provider["name"])
        _record_provider_preflight(
            connection,
            scoped_project_id,
            actor_id,
            provider,
            description,
            preflight_status="simulation_ready",
            execution_mode="local_simulation",
        )
        connection.commit()
        return {
            "provider_id": provider_id,
            "status": "simulation_ready",
            "summary": description,
            "issues": [],
        }

    if not provider["is_runnable"]:
        issues = list(provider.get("config_warnings") or [])
        description = "{0} preflight failed: {1}".format(
            provider["name"],
            issues[0] if issues else "provider configuration is invalid",
        )
        _record_provider_preflight(
            connection,
            scoped_project_id,
            actor_id,
            provider,
            description,
            preflight_status="failed",
            issues=issues,
            execution_mode=provider.get("effective_execution_mode"),
            external_runtime=provider.get("effective_execution_mode"),
        )
        connection.commit()
        return {
            "provider_id": provider_id,
            "status": "failed",
            "summary": description,
            "issues": issues,
        }

    runtime_env = _runtime_env(project_paths, {"id": provider_id})
    missing_env = [key for key in PROVIDER_REQUIRED_ENV_KEYS.get(provider_id, ()) if not runtime_env.get(key)]
    command = _provider_preflight_command(provider_id, provider_settings)
    issues = []

    if command:
        executable = shutil.which(command[0], path=runtime_env.get("PATH"))
        if executable is None:
            issues.append("Executable '{0}' is not available on PATH.".format(command[0]))
    if missing_env:
        issues.extend("Missing required environment variable: {0}.".format(key) for key in missing_env)

    if issues:
        description = "{0} preflight failed: {1}".format(provider["name"], issues[0])
        _record_provider_preflight(
            connection,
            scoped_project_id,
            actor_id,
            provider,
            description,
            preflight_status="failed",
            issues=issues,
            execution_mode=provider.get("effective_execution_mode"),
            external_runtime=provider.get("effective_execution_mode"),
        )
        connection.commit()
        return {
            "provider_id": provider_id,
            "status": "failed",
            "summary": description,
            "issues": issues,
        }

    timeout_seconds = min(int(provider_settings.get("timeout_seconds") or 30), 10)
    try:
        result = subprocess.run(
            command,
            cwd=project_paths.root,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=runtime_env,
        )
    except subprocess.TimeoutExpired as exc:
        issues = ["Preflight timed out after {0}s.".format(timeout_seconds)]
        description = "{0} preflight failed: {1}".format(provider["name"], issues[0])
        _record_provider_preflight(
            connection,
            scoped_project_id,
            actor_id,
            provider,
            description,
            preflight_status="failed",
            issues=issues,
            execution_mode=provider.get("effective_execution_mode"),
            external_runtime=provider.get("effective_execution_mode"),
        )
        connection.commit()
        return {
            "provider_id": provider_id,
            "status": "failed",
            "summary": description,
            "issues": issues,
            "timeout_seconds": timeout_seconds,
        }

    if result.returncode != 0:
        stderr = (result.stderr or "").strip() or (result.stdout or "").strip() or "unknown error"
        issues = ["Preflight command exited with status {0}: {1}".format(result.returncode, stderr)]
        description = "{0} preflight failed: {1}".format(provider["name"], issues[0])
        _record_provider_preflight(
            connection,
            scoped_project_id,
            actor_id,
            provider,
            description,
            preflight_status="failed",
            issues=issues,
            execution_mode=provider.get("effective_execution_mode"),
            external_runtime=provider.get("effective_execution_mode"),
        )
        connection.commit()
        return {
            "provider_id": provider_id,
            "status": "failed",
            "summary": description,
            "issues": issues,
        }

    summary_line = ((result.stdout or "").strip() or (result.stderr or "").strip() or "preflight passed").splitlines()[0]
    description = "{0} preflight passed: {1}".format(provider["name"], summary_line)
    _record_provider_preflight(
        connection,
        scoped_project_id,
        actor_id,
        provider,
        description,
        preflight_status="passed",
        issues=[],
        execution_mode=provider.get("effective_execution_mode"),
        external_runtime=provider.get("effective_execution_mode"),
    )
    connection.commit()
    return {
        "provider_id": provider_id,
        "status": "passed",
        "summary": description,
        "issues": [],
    }


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


def _rollback_untracked_artifact(artifact_full_path, artifact_existed_before_run, original_artifact_bytes):
    if not artifact_full_path:
        return
    try:
        if artifact_existed_before_run:
            with open(artifact_full_path, "wb") as handle:
                handle.write(original_artifact_bytes or b"")
        elif os.path.exists(artifact_full_path):
            os.remove(artifact_full_path)
    except OSError:
        return


def _task_prompt(connection, task_id):
    row = connection.execute(
        """
        SELECT title, description
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if row is None:
        return "Complete task {0} and summarize the result.".format(task_id)
    description = (row["description"] or "").strip()
    if description:
        return "Task: {0}\n\nContext:\n{1}\n\nReturn a concise completion summary.".format(row["title"], description)
    return "Task: {0}\n\nReturn a concise completion summary.".format(row["title"])


def _codex_cli_command(project_paths, provider_settings, prompt, output_path):
    command = [
        provider_settings.get("cli_command") or "codex",
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        provider_settings.get("sandbox") or "workspace-write",
        "--color",
        "never",
        "-C",
        project_paths.root,
        "-o",
        output_path,
    ]
    model = (provider_settings.get("model") or "").strip()
    if model:
        command.extend(["--model", model])
    command.append(prompt)
    return command


def _codex_cli_activity_details(project_paths, provider_settings, task_prompt):
    command = _codex_cli_command(project_paths, provider_settings, task_prompt, "<runtime-output>")
    return {
        "command": command,
        "timeout_seconds": int(provider_settings.get("timeout_seconds") or 300),
        "external_runtime": "codex_cli",
        "environment_scope": "sanitized",
    }


def _claude_cli_command(project_paths, provider_settings, prompt):
    command = [
        provider_settings.get("cli_command") or "claude",
        "-p",
    ]
    permission_mode = (provider_settings.get("permission_mode") or "").strip()
    if permission_mode:
        command.extend(["--permission-mode", permission_mode])
    model = (provider_settings.get("model") or "").strip()
    if model:
        command.extend(["--model", model])
    command.extend(["--add-dir", project_paths.root])
    command.append(prompt)
    return command


def _claude_cli_activity_details(project_paths, provider_settings, task_prompt):
    command = _claude_cli_command(project_paths, provider_settings, task_prompt)
    return {
        "command": command,
        "timeout_seconds": int(provider_settings.get("timeout_seconds") or 300),
        "external_runtime": "claude_cli",
        "environment_scope": "sanitized",
    }


def _run_openai_codex_cli(project_paths, provider_settings, task_prompt):
    timeout_seconds = int(provider_settings.get("timeout_seconds") or 300)
    runtime_env = _runtime_env(project_paths, {"id": "openai_codex"})
    os.makedirs(project_paths.runtime_dir, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix="openai-codex-",
        suffix=".txt",
        dir=project_paths.runtime_dir,
        delete=False,
    ) as handle:
        output_path = handle.name

    command = _codex_cli_command(project_paths, provider_settings, task_prompt, output_path)
    try:
        try:
            result = subprocess.run(
                command,
                cwd=project_paths.root,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                env=runtime_env,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProviderRuntimeFailure(
                "timeout",
                "Codex CLI timed out after {0}s.".format(timeout_seconds),
                timeout_seconds=timeout_seconds,
                command=command,
            ) from exc
        if result.returncode != 0:
            raise ProviderRuntimeFailure(
                "nonzero_exit",
                "Codex CLI exited with status {0}: {1}".format(
                    result.returncode,
                    (result.stderr or "").strip() or "unknown error",
                ),
                exit_code=result.returncode,
                stderr=(result.stderr or "").strip(),
                stdout=(result.stdout or "").strip(),
                command=command,
            )
        try:
            with open(output_path, "r", encoding="utf-8") as output_handle:
                final_message = output_handle.read().strip()
        except OSError as exc:
            raise ProviderRuntimeFailure(
                "output_read_failed",
                "Codex CLI completed but the runtime output file could not be read: {0}".format(exc),
                command=command,
                output_path=output_path,
            ) from exc
        return {
            "summary_text": final_message or "Codex CLI completed without a final message.",
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
        }
    finally:
        if os.path.exists(output_path):
            os.remove(output_path)


def _run_claude_code_cli(project_paths, provider_settings, task_prompt):
    timeout_seconds = int(provider_settings.get("timeout_seconds") or 300)
    runtime_env = _runtime_env(project_paths, {"id": "claude_code"})
    command = _claude_cli_command(project_paths, provider_settings, task_prompt)
    try:
        result = subprocess.run(
            command,
            cwd=project_paths.root,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=runtime_env,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProviderRuntimeFailure(
            "timeout",
            "Claude CLI timed out after {0}s.".format(timeout_seconds),
            timeout_seconds=timeout_seconds,
            command=command,
        ) from exc
    if result.returncode != 0:
        raise ProviderRuntimeFailure(
            "nonzero_exit",
            "Claude CLI exited with status {0}: {1}".format(
                result.returncode,
                (result.stderr or "").strip() or "unknown error",
            ),
            exit_code=result.returncode,
            stderr=(result.stderr or "").strip(),
            stdout=(result.stdout or "").strip(),
            command=command,
        )
    return {
        "summary_text": (result.stdout or "").strip() or "Claude CLI completed without a final message.",
        "stdout": result.stdout or "",
        "stderr": result.stderr or "",
    }


def _provider_failure_details(exc):
    if isinstance(exc, ProviderRuntimeFailure):
        return exc.kind, str(exc), dict(exc.details)
    if isinstance(exc, subprocess.TimeoutExpired):
        return (
            "timeout",
            "Provider runtime timed out after {0}s.".format(exc.timeout),
            {"timeout_seconds": exc.timeout, "command": exc.cmd},
        )
    return "runtime_error", str(exc), {}


def _claude_cli_artifact_payload(provider, task_id, external_result):
    return {
        "artifact_type": provider["default_artifact_type"],
        "content": (
            "# Claude Code Runtime Report\n\n"
            "- Task ID: {0}\n"
            "- Provider: Claude Code CLI\n"
            "- Outcome: External Claude CLI execution completed.\n\n"
            "## Final Message\n\n{1}\n\n"
            "## Stdout\n\n```\n{2}\n```\n\n"
            "## Stderr\n\n```\n{3}\n```\n"
        ).format(task_id, external_result["summary_text"], external_result["stdout"].strip(), external_result["stderr"].strip()),
        "status_message": "Claude Code CLI completed task execution",
    }


def _codex_cli_artifact_payload(provider, task_id, external_result):
    return {
        "artifact_type": provider["default_artifact_type"],
        "content": (
            "# OpenAI Codex Runtime Report\n\n"
            "- Task ID: {0}\n"
            "- Provider: OpenAI Codex CLI\n"
            "- Outcome: External Codex CLI execution completed.\n\n"
            "## Final Message\n\n{1}\n\n"
            "## Stdout\n\n```\n{2}\n```\n\n"
            "## Stderr\n\n```\n{3}\n```\n"
        ).format(task_id, external_result["summary_text"], external_result["stdout"].strip(), external_result["stderr"].strip()),
        "status_message": "OpenAI Codex CLI completed task execution",
    }


def run_provider_task(connection, project_paths, project_id, agent_id, task_id, provider_type, artifact_path=None):
    provider, provider_settings = get_provider_runtime_settings(
        provider_type,
        connection=connection,
        project_id=project_id,
    )
    if not provider["is_runnable"]:
        raise ValueError("; ".join(provider["config_warnings"]) or "Provider configuration is invalid.")
    task_title = _task_title(connection, task_id)
    effective_mode = provider.get("effective_execution_mode") or provider["execution_mode"]
    claude_cli_enabled = effective_mode == "claude_cli"
    codex_cli_enabled = effective_mode == "codex_cli"
    if claude_cli_enabled:
        task_prompt = _task_prompt(connection, task_id)
        extra_activity_details = _claude_cli_activity_details(project_paths, provider_settings, task_prompt)
    elif codex_cli_enabled:
        task_prompt = _task_prompt(connection, task_id)
        extra_activity_details = _codex_cli_activity_details(project_paths, provider_settings, task_prompt)
    else:
        task_prompt = None
        extra_activity_details = {}

    artifact_full_path = _resolve_artifact_path(project_paths, provider_type, task_id, artifact_path)
    artifact_existed_before_run = os.path.exists(artifact_full_path)
    original_artifact_bytes = None
    if artifact_existed_before_run:
        with open(artifact_full_path, "rb") as handle:
            original_artifact_bytes = handle.read()
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
            **extra_activity_details
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
            **extra_activity_details
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
            artifact_type=provider["default_artifact_type"],
            **extra_activity_details
        )
        if claude_cli_enabled:
            external_result = _run_claude_code_cli(project_paths, provider_settings, task_prompt)
            artifact_payload = _claude_cli_artifact_payload(provider, task_id, external_result)
        elif codex_cli_enabled:
            external_result = _run_openai_codex_cli(project_paths, provider_settings, task_prompt)
            artifact_payload = _codex_cli_artifact_payload(provider, task_id, external_result)
        else:
            artifact_payload = _provider_artifact_payload(provider, task_title, task_id)

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
                "configured_execution_mode": provider["configured_execution_mode"],
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
            **extra_activity_details
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
            **extra_activity_details
        )
        end_session(connection, session_id, "completed", artifact_payload["status_message"], project_paths=project_paths)
    except Exception as exc:
        _rollback_untracked_artifact(
            artifact_full_path if artifact_id is None else None,
            artifact_existed_before_run=artifact_existed_before_run,
            original_artifact_bytes=original_artifact_bytes,
        )
        failure_kind, failure_detail, failure_metadata = _provider_failure_details(exc)
        failure_summary = "{0} adapter failed ({1}): {2}".format(provider["name"], failure_kind, failure_detail)
        if session_id is not None:
            try:
                failure_activity_details = dict(extra_activity_details)
                failure_activity_details.update(failure_metadata)
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
                        failure_kind=failure_kind,
                        failure_detail=failure_detail,
                        error=str(exc),
                        progress_pct=100,
                        **failure_activity_details
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


def list_provider_runtime_status(connection=None, project_id=None):
    return list_provider_status(connection=connection, project_id=project_id)


def provider_runtime_overview(connection=None, project_id=None):
    return fetch_provider_runtime_overview(connection=connection, project_id=project_id)


def set_provider_mode(connection, provider_id, actor_id, mode, project_id=None):
    return update_provider_mode(connection, provider_id, actor_id, mode, project_id=project_id)


def set_provider_settings(connection, provider_id, actor_id, settings, project_id=None):
    return update_provider_settings(connection, provider_id, actor_id, settings, project_id=project_id)
