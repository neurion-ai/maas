"""Provider adapter execution helpers."""

from datetime import datetime, timezone
import json
import os
import sqlite3
import shutil
import subprocess
import tempfile

from maas.ids import generate_id
from maas.providers import (
    fetch_provider_runtime_overview,
    get_provider_runtime_settings,
    list_provider_status,
    update_provider_mode,
    update_provider_settings,
)
from maas.services.provider_jobs import (
    complete_provider_job,
    fail_provider_job,
    fetch_provider_job,
    fetch_provider_jobs,
    find_open_provider_job,
    insert_provider_job,
    next_queued_provider_job_id,
    start_provider_job,
)
from maas.services.lifecycle import end_session, heartbeat, log_activity, produce_artifact, start_session
from maas.services.memory import build_task_prompt, record_memory_injection, record_memory_outcome
from maas.services.projects import resolve_project, resolve_project_id
from maas.services.queue_capacity import can_start_provider_jobs
from maas.services.runtime_quotas import ensure_runtime_quotas_allow_provider_run
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


def _codex_home_dir():
    configured = os.environ.get("CODEX_HOME")
    candidates = [configured, os.path.join(os.path.expanduser("~"), ".codex")]
    for candidate in candidates:
        if not candidate:
            continue
        resolved = os.path.abspath(os.path.expanduser(candidate))
        if os.path.isdir(resolved):
            return resolved
    return None


def _codex_cli_auth_available():
    if os.environ.get("OPENAI_API_KEY"):
        return True
    codex_home = _codex_home_dir()
    if codex_home is None:
        return False
    auth_path = os.path.join(codex_home, "auth.json")
    if not os.path.exists(auth_path):
        return False
    try:
        with open(auth_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError):
        return False
    if payload.get("OPENAI_API_KEY"):
        return True
    tokens = payload.get("tokens") or {}
    return bool(tokens)


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


def _project_runtime_context(connection, project_paths, project_id):
    project = resolve_project(connection, project_id)
    if project is None:
        raise ValueError("Project not found")
    source_root = os.path.abspath(project["source_root"] or project_paths.root)
    if not os.path.isdir(source_root):
        raise ValueError("Project source root is not available for provider runtime.")
    project_paths.ensure_project_workspace(project["project_id"])
    runtime_dir = project_paths.project_runtime_dir(project["project_id"])
    runtime_tmp_dir = project_paths.project_runtime_tmp_dir(project["project_id"])
    os.makedirs(runtime_tmp_dir, exist_ok=True)
    return {
        "project_id": project["project_id"],
        "source_root": source_root,
        "project_runtime_dir": runtime_dir,
        "runtime_dir": runtime_dir,
        "runtime_tmp_dir": runtime_tmp_dir,
    }


def _create_runtime_envelope(project_paths, runtime_context, provider_id, purpose, envelope_id=None, session_id=None):
    resolved_envelope_id = envelope_id or session_id or generate_id("run")
    envelope = project_paths.ensure_runtime_envelope(runtime_context["project_id"], resolved_envelope_id)
    manifest = {
        "envelope_id": resolved_envelope_id,
        "purpose": purpose,
        "provider_id": provider_id,
        "project_id": runtime_context["project_id"],
        "session_id": session_id,
        "source_root": runtime_context["source_root"],
        "project_runtime_root": runtime_context["project_runtime_dir"],
        "runtime_root": envelope["root"],
        "home_dir": envelope["home_dir"],
        "tmp_dir": envelope["tmp_dir"],
        "cache_dir": envelope["cache_dir"],
        "config_dir": envelope["config_dir"],
        "data_dir": envelope["data_dir"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(envelope["manifest_path"], "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
    envelope["manifest"] = manifest
    return envelope


def _runtime_env(project_paths, provider, runtime_context, runtime_envelope=None):
    env = {}
    for key in SAFE_RUNTIME_ENV_KEYS:
        value = os.environ.get(key)
        if value:
            env[key] = value
    for key in PROVIDER_RUNTIME_ENV_KEYS.get(provider["id"], ()):
        value = os.environ.get(key)
        if value:
            env[key] = value
    if provider["id"] == "openai_codex":
        codex_home = _codex_home_dir()
        if codex_home is not None:
            env["CODEX_HOME"] = codex_home
    env["MAAS_PROJECT_ID"] = runtime_context["project_id"]
    env["MAAS_PROJECT_ROOT"] = runtime_context["source_root"]
    env["MAAS_PROJECT_RUNTIME_ROOT"] = runtime_context["project_runtime_dir"]
    env["MAAS_ARTIFACT_ROOT"] = project_paths.artifacts_dir
    if runtime_envelope is None:
        runtime_envelope = {
            "root": runtime_context["runtime_dir"],
            "home_dir": runtime_context["runtime_dir"],
            "tmp_dir": runtime_context["runtime_tmp_dir"],
            "cache_dir": runtime_context["runtime_dir"],
            "config_dir": runtime_context["runtime_dir"],
            "data_dir": runtime_context["runtime_dir"],
            "manifest_path": "",
        }
    env["MAAS_RUNTIME_ROOT"] = runtime_envelope["root"]
    env["MAAS_RUNTIME_MANIFEST"] = runtime_envelope.get("manifest_path") or ""
    env["HOME"] = runtime_envelope["home_dir"]
    env["XDG_CACHE_HOME"] = runtime_envelope["cache_dir"]
    env["XDG_CONFIG_HOME"] = runtime_envelope["config_dir"]
    env["XDG_DATA_HOME"] = runtime_envelope["data_dir"]
    env["TMPDIR"] = runtime_envelope["tmp_dir"]
    env["TMP"] = runtime_envelope["tmp_dir"]
    env["TEMP"] = runtime_envelope["tmp_dir"]
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
    scoped_project_id = resolve_project_id(connection, project_id)
    if scoped_project_id is None:
        raise ValueError("Project not found")
    runtime_context = _project_runtime_context(connection, project_paths, scoped_project_id)
    actor = ensure_board_action_allowed(
        connection,
        actor_id,
        scoped_project_id,
        "check_provider_runtime",
        "provider",
        provider_id,
    )
    resolved_actor_id = actor["actor_id"]
    providers = list_provider_status(connection=connection, project_id=scoped_project_id)
    provider = next((item for item in providers if item["id"] == provider_id), None)
    if provider is None:
        raise ValueError("Unsupported provider type: {0}".format(provider_id))

    provider, provider_settings = get_provider_runtime_settings(
        provider_id,
        connection=connection,
        project_id=scoped_project_id,
    )
    if not provider["is_runnable"]:
        issues = list(provider.get("config_warnings") or [])
        description = "{0} preflight failed: {1}".format(
            provider["name"],
            issues[0] if issues else "provider configuration is invalid",
        )
        _record_provider_preflight(
            connection,
            scoped_project_id,
            resolved_actor_id,
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

    if provider["configured_execution_mode"] == "local_simulation":
        description = "{0} preflight passed in local simulation mode.".format(provider["name"])
        _record_provider_preflight(
            connection,
            scoped_project_id,
            resolved_actor_id,
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

    runtime_envelope = _create_runtime_envelope(
        project_paths,
        runtime_context,
        provider_id,
        purpose="preflight",
        envelope_id=generate_id("run"),
    )
    runtime_env = _runtime_env(project_paths, {"id": provider_id}, runtime_context, runtime_envelope=runtime_envelope)
    command = _provider_preflight_command(provider_id, provider_settings)
    issues = []
    missing_env = []

    if command:
        executable = shutil.which(command[0], path=runtime_env.get("PATH"))
        if executable is None:
            issues.append("Executable '{0}' is not available on PATH.".format(command[0]))
    if provider_id == "openai_codex" and provider.get("effective_execution_mode") == "codex_cli":
        if not _codex_cli_auth_available():
            issues.append("Codex CLI auth is not available. Sign in to Codex CLI or export OPENAI_API_KEY.")
    else:
        missing_env = [key for key in PROVIDER_REQUIRED_ENV_KEYS.get(provider_id, ()) if not runtime_env.get(key)]
    if missing_env:
        issues.extend("Missing required environment variable: {0}.".format(key) for key in missing_env)

    if issues:
        description = "{0} preflight failed: {1}".format(provider["name"], issues[0])
        _record_provider_preflight(
            connection,
            scoped_project_id,
            resolved_actor_id,
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
            cwd=runtime_context["source_root"],
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
            resolved_actor_id,
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
            resolved_actor_id,
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
        resolved_actor_id,
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


def _runtime_console_paths(runtime_envelope):
    return {
        "output_path": os.path.join(runtime_envelope["root"], "runtime-output.txt"),
        "stdout_path": os.path.join(runtime_envelope["root"], "stdout.log"),
        "stderr_path": os.path.join(runtime_envelope["root"], "stderr.log"),
    }


def _tail_runtime_text(path, limit=1200):
    if not path or not os.path.exists(path) or not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            read_start = max(size - (limit * 4), 0)
            handle.seek(read_start)
            payload = handle.read()
    except OSError:
        return None
    content = payload.decode("utf-8", errors="ignore")
    if len(content) > limit:
        content = content[-limit:]
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        return None
    return lines[-1]


def _provider_run_target(connection, project_id, task_id, agent_id):
    return connection.execute(
        """
        SELECT
            tasks.project_id,
            tasks.task_id,
            tasks.title,
            tasks.status,
            tasks.priority,
            tasks.review_state,
            tasks.assigned_agent_id AS agent_id
        FROM tasks
        WHERE tasks.project_id = ?
          AND tasks.task_id = ?
          AND tasks.assigned_agent_id = ?
          AND tasks.status IN ('planned', 'ready', 'assigned')
          AND (
              tasks.next_retry_at IS NULL
              OR datetime(tasks.next_retry_at) <= CURRENT_TIMESTAMP
          )
          AND EXISTS (
              SELECT 1
              FROM task_capability_grants grants
              WHERE grants.project_id = tasks.project_id
                AND grants.task_id = tasks.task_id
                AND grants.agent_id = tasks.assigned_agent_id
                AND grants.capability = 'execute'
                AND grants.revoked_at IS NULL
          )
        """,
        (project_id, task_id, agent_id),
    ).fetchone()


def _audit_provider_job(connection, project_id, actor_id, action_type, job_id, detail):
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, ?, 'provider_job', ?, ?)
        """,
        (
            generate_id("audit"),
            project_id,
            actor_id,
            action_type,
            job_id,
            json.dumps(detail),
        ),
    )


def _activity_provider_job(connection, project_id, agent_id, task_id, action, description, details, severity="info"):
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
        ) VALUES (?, ?, ?, ?, ?, 'runtime', ?, ?, ?)
        """,
        (
            generate_id("act"),
            project_id,
            agent_id,
            task_id,
            action,
            description,
            json.dumps(details),
            severity,
        ),
    )


def _codex_cli_command(runtime_context, provider_settings, prompt, output_path):
    command = [
        provider_settings.get("cli_command") or "codex",
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        provider_settings.get("sandbox") or "workspace-write",
        "--color",
        "never",
        "-C",
        runtime_context["source_root"],
        "-o",
        output_path,
    ]
    model = (provider_settings.get("model") or "").strip()
    if model:
        command.extend(["--model", model])
    command.append(prompt)
    return command


def _codex_cli_activity_details(runtime_context, provider_settings, task_prompt, runtime_envelope):
    command = _codex_cli_command(runtime_context, provider_settings, task_prompt, "<runtime-output>")
    return {
        "command": command,
        "timeout_seconds": int(provider_settings.get("timeout_seconds") or 300),
        "external_runtime": "codex_cli",
        "environment_scope": "session_envelope",
        "runtime_root": runtime_envelope["root"],
        "project_runtime_root": runtime_context["project_runtime_dir"],
        "runtime_manifest_path": runtime_envelope["manifest_path"],
        "project_root": runtime_context["source_root"],
    }


def _claude_cli_command(runtime_context, provider_settings, prompt):
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
    command.extend(["--add-dir", runtime_context["source_root"]])
    command.append(prompt)
    return command


def _claude_cli_activity_details(runtime_context, provider_settings, task_prompt, runtime_envelope):
    command = _claude_cli_command(runtime_context, provider_settings, task_prompt)
    return {
        "command": command,
        "timeout_seconds": int(provider_settings.get("timeout_seconds") or 300),
        "external_runtime": "claude_cli",
        "environment_scope": "session_envelope",
        "runtime_root": runtime_envelope["root"],
        "project_runtime_root": runtime_context["project_runtime_dir"],
        "runtime_manifest_path": runtime_envelope["manifest_path"],
        "project_root": runtime_context["source_root"],
    }


def _run_openai_codex_cli(project_paths, runtime_context, runtime_envelope, provider_settings, task_prompt):
    timeout_seconds = int(provider_settings.get("timeout_seconds") or 300)
    runtime_env = _runtime_env(
        project_paths,
        {"id": "openai_codex"},
        runtime_context,
        runtime_envelope=runtime_envelope,
    )
    os.makedirs(runtime_envelope["root"], exist_ok=True)
    console_paths = _runtime_console_paths(runtime_envelope)
    output_path = console_paths["output_path"]
    stdout_path = console_paths["stdout_path"]
    stderr_path = console_paths["stderr_path"]
    command = _codex_cli_command(runtime_context, provider_settings, task_prompt, output_path)
    try:
        with open(stdout_path, "w", encoding="utf-8") as stdout_handle, open(stderr_path, "w", encoding="utf-8") as stderr_handle:
            try:
                result = subprocess.run(
                    command,
                    cwd=runtime_context["source_root"],
                    stdout=stdout_handle,
                    stderr=stderr_handle,
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
                    console_paths=console_paths,
                ) from exc
        try:
            with open(stdout_path, "r", encoding="utf-8") as stdout_handle:
                stdout_text = stdout_handle.read()
        except OSError:
            stdout_text = ""
        try:
            with open(stderr_path, "r", encoding="utf-8") as stderr_handle:
                stderr_text = stderr_handle.read()
        except OSError:
            stderr_text = ""
        if result.returncode != 0:
            raise ProviderRuntimeFailure(
                "nonzero_exit",
                "Codex CLI exited with status {0}: {1}".format(
                    result.returncode,
                    (stderr_text or "").strip() or "unknown error",
                ),
                exit_code=result.returncode,
                stderr=(stderr_text or "").strip(),
                stdout=(stdout_text or "").strip(),
                command=command,
                console_paths=console_paths,
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
                console_paths=console_paths,
            ) from exc
        return {
            "summary_text": final_message or "Codex CLI completed without a final message.",
            "stdout": stdout_text or "",
            "stderr": stderr_text or "",
            "console_paths": console_paths,
        }
    except ProviderRuntimeFailure:
        raise


def _run_claude_code_cli(project_paths, runtime_context, runtime_envelope, provider_settings, task_prompt):
    timeout_seconds = int(provider_settings.get("timeout_seconds") or 300)
    runtime_env = _runtime_env(
        project_paths,
        {"id": "claude_code"},
        runtime_context,
        runtime_envelope=runtime_envelope,
    )
    command = _claude_cli_command(runtime_context, provider_settings, task_prompt)
    try:
        result = subprocess.run(
            command,
            cwd=runtime_context["source_root"],
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
    runtime_context = _project_runtime_context(connection, project_paths, project_id)
    provider, provider_settings = get_provider_runtime_settings(
        provider_type,
        connection=connection,
        project_id=project_id,
    )
    if not provider["is_runnable"]:
        raise ValueError("; ".join(provider["config_warnings"]) or "Provider configuration is invalid.")
    task_title = _task_title(connection, task_id)
    effective_mode = provider.get("effective_execution_mode") or provider["execution_mode"]
    ensure_runtime_quotas_allow_provider_run(connection, project_id, task_id, effective_mode)
    claude_cli_enabled = effective_mode == "claude_cli"
    codex_cli_enabled = effective_mode == "codex_cli"
    prompt_payload = build_task_prompt(connection, task_id) if (claude_cli_enabled or codex_cli_enabled) else None
    task_prompt = prompt_payload["prompt"] if prompt_payload else None
    memory_context = prompt_payload["memory_context"] if prompt_payload else []
    memory_artifact_ids = [item.get("artifact_id") for item in memory_context if item.get("artifact_id")]
    memory_injection_recorded = False

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
    runtime_envelope = _create_runtime_envelope(
        project_paths,
        runtime_context,
        provider_type,
        purpose="task_run",
        session_id=session_id,
    )
    extra_activity_details = {
        "environment_scope": "session_envelope",
        "runtime_root": runtime_envelope["root"],
        "project_runtime_root": runtime_context["project_runtime_dir"],
        "runtime_manifest_path": runtime_envelope["manifest_path"],
    }
    if claude_cli_enabled:
        extra_activity_details.update(
            _claude_cli_activity_details(runtime_context, provider_settings, task_prompt, runtime_envelope)
        )
    elif codex_cli_enabled:
        extra_activity_details.update(
            _codex_cli_activity_details(runtime_context, provider_settings, task_prompt, runtime_envelope)
        )
        extra_activity_details.update(_runtime_console_paths(runtime_envelope))
    execution_summary_label = (
        "{0} adapter is executing live CLI work".format(provider["name"])
        if (claude_cli_enabled or codex_cli_enabled)
        else "{0} adapter is executing the provider run".format(provider["name"])
    )
    execution_detail_description = (
        "{0} adapter is executing the live CLI provider run.".format(provider["name"])
        if (claude_cli_enabled or codex_cli_enabled)
        else "{0} adapter is executing the provider run.".format(provider["name"])
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
        if memory_context:
            record_memory_injection(connection, memory_artifact_ids)
            memory_injection_recorded = True
            log_activity(
                connection,
                project_id=project_id,
                agent_id=agent_id,
                task_id=task_id,
                action="memory_context_loaded",
                category="memory",
                description="Loaded promoted project memory into the live provider prompt.",
                details={
                    "session_id": session_id,
                    "memory_items": memory_context,
                    "memory_count": len(memory_context),
                },
            )
        heartbeat(connection, session_id, 60, execution_summary_label)
        _log_provider_phase(
            connection,
            project_id,
            agent_id,
            task_id,
            provider,
            action="provider_execution_progress",
            phase="execution_running",
            description=execution_detail_description,
            session_id=session_id,
            progress_pct=60,
            artifact_path=artifact_full_path,
            artifact_type=provider["default_artifact_type"],
            **extra_activity_details
        )
        if claude_cli_enabled:
            external_result = _run_claude_code_cli(
                project_paths,
                runtime_context,
                runtime_envelope,
                provider_settings,
                task_prompt,
            )
            artifact_payload = _claude_cli_artifact_payload(provider, task_id, external_result)
        elif codex_cli_enabled:
            external_result = _run_openai_codex_cli(
                project_paths,
                runtime_context,
                runtime_envelope,
                provider_settings,
                task_prompt,
            )
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
                "runtime_manifest_path": runtime_envelope["manifest_path"],
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
        if memory_artifact_ids:
            record_memory_outcome(connection, memory_artifact_ids, "completed")
    except Exception as exc:
        if memory_injection_recorded and memory_artifact_ids:
            try:
                record_memory_outcome(connection, memory_artifact_ids, "failed")
            except Exception:
                pass
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


def queue_provider_task(connection, project_paths, provider_id, actor_id, project_id, agent_id, task_id, artifact_path=None):
    resolved_project_id = resolve_project_id(connection, project_id)
    if resolved_project_id is None:
        raise ValueError("Project not found")
    ensure_board_action_allowed(connection, actor_id, resolved_project_id, "queue_provider_task", "provider", provider_id)
    existing = find_open_provider_job(connection, resolved_project_id, provider_id, task_id)
    if existing is not None:
        job = fetch_provider_job(connection, existing["job_id"], include_archived=True)
        if job is not None:
            job["duplicate_suppressed"] = True
            return job
    provider, _provider_settings = get_provider_runtime_settings(
        provider_id,
        connection=connection,
        project_id=resolved_project_id,
    )
    if not provider["is_runnable"]:
        raise ValueError("; ".join(provider["config_warnings"]) or "Provider configuration is invalid.")
    target = _provider_run_target(connection, resolved_project_id, task_id, agent_id)
    if target is None:
        raise ValueError("Task is not eligible for provider queueing.")
    effective_mode = provider.get("effective_execution_mode") or provider["execution_mode"]
    ensure_runtime_quotas_allow_provider_run(connection, resolved_project_id, task_id, effective_mode)
    try:
        job = insert_provider_job(
            connection,
            resolved_project_id,
            provider_id,
            task_id,
            agent_id,
            queued_by=actor_id,
            artifact_path=artifact_path,
        )
    except sqlite3.IntegrityError:
        existing = find_open_provider_job(connection, resolved_project_id, provider_id, task_id)
        if existing is not None:
            job = fetch_provider_job(connection, existing["job_id"], include_archived=True)
            if job is not None:
                job["duplicate_suppressed"] = True
                return job
        raise
    job["duplicate_suppressed"] = False
    _activity_provider_job(
        connection,
        resolved_project_id,
        agent_id,
        task_id,
        "provider_job_queued",
        "{0} queued a provider job for {1}.".format(actor_id, provider["name"]),
        {
            "job_id": job["job_id"],
            "provider_id": provider_id,
            "provider_name": provider["name"],
            "artifact_path": artifact_path,
        },
    )
    _audit_provider_job(
        connection,
        resolved_project_id,
        actor_id,
        "queue_provider_task",
        job["job_id"],
        {"provider_id": provider_id, "task_id": task_id, "agent_id": agent_id, "artifact_path": artifact_path},
    )
    connection.commit()
    return job


def process_provider_job(connection, project_paths, job_id, actor_id, worker_id=None):
    job = fetch_provider_job(connection, job_id, include_archived=False)
    if job is None:
        raise ValueError("Provider job not found")
    ensure_board_action_allowed(connection, actor_id, job["project_id"], "process_provider_job", "provider", job["provider_id"])
    if job["status"] != "queued":
        job["duplicate_suppressed"] = True
        return job
    running_job = start_provider_job(connection, job_id, worker_id=worker_id or actor_id)
    if running_job is None:
        current = fetch_provider_job(connection, job_id, include_archived=True)
        if current is None:
            raise ValueError("Provider job is no longer queued")
        current["duplicate_suppressed"] = True
        return current
    _activity_provider_job(
        connection,
        running_job["project_id"],
        running_job["agent_id"],
        running_job["task_id"],
        "provider_job_started",
        "{0} started queued provider job {1}.".format(actor_id, job_id),
        {
            "job_id": job_id,
            "provider_id": running_job["provider_id"],
            "worker_id": worker_id or actor_id,
        },
    )
    _audit_provider_job(
        connection,
        running_job["project_id"],
        actor_id,
        "process_provider_job",
        job_id,
        {"provider_id": running_job["provider_id"], "task_id": running_job["task_id"]},
    )
    connection.commit()
    try:
        result = run_provider_task(
            connection,
            project_paths=project_paths,
            project_id=running_job["project_id"],
            agent_id=running_job["agent_id"],
            task_id=running_job["task_id"],
            provider_type=running_job["provider_id"],
            artifact_path=running_job["artifact_path"],
        )
    except Exception as exc:
        error = {
            "failure_kind": getattr(exc, "kind", "runtime_error"),
            "failure_detail": str(exc),
        }
        failed_job = fail_provider_job(connection, job_id, error)
        _activity_provider_job(
            connection,
            failed_job["project_id"],
            failed_job["agent_id"],
            failed_job["task_id"],
            "provider_job_failed",
            "Queued provider job failed during execution.",
            {"job_id": job_id, **error},
            severity="error",
        )
        connection.commit()
        return failed_job

    completed_job = complete_provider_job(connection, job_id, result)
    _activity_provider_job(
        connection,
        completed_job["project_id"],
        completed_job["agent_id"],
        completed_job["task_id"],
        "provider_job_completed",
        "Queued provider job completed successfully.",
        {
            "job_id": job_id,
            "session_id": completed_job["session_id"],
            "artifact_id": completed_job["artifact_id"],
            "execution_mode": completed_job["execution_mode"],
        },
    )
    connection.commit()
    return completed_job


def _next_startable_provider_job_id(connection, provider_id=None):
    parameters = []
    provider_clause = ""
    if provider_id:
        provider_clause = "AND provider_job_queue.provider_id = ?"
        parameters.append(provider_id)
    rows = connection.execute(
        """
        SELECT provider_job_queue.job_id, provider_job_queue.project_id
        FROM provider_job_queue
        JOIN projects ON projects.project_id = provider_job_queue.project_id
        WHERE provider_job_queue.status = 'queued'
          AND projects.state = 'active'
          {provider_clause}
        ORDER BY provider_job_queue.created_at ASC, provider_job_queue.rowid ASC
        """.format(provider_clause=provider_clause),
        tuple(parameters),
    ).fetchall()
    for row in rows:
        can_start, _snapshot = can_start_provider_jobs(connection, row["project_id"])
        if can_start:
            return row["job_id"], row["project_id"]
    return None, None


def process_next_provider_job(connection, project_paths, actor_id, project_id=None, provider_id=None, worker_id=None):
    resource_id = provider_id or "provider_queue"
    if project_id:
        resolved_project_id = resolve_project_id(connection, project_id)
        if resolved_project_id is None:
            raise ValueError("Project not found")
        ensure_board_action_allowed(connection, actor_id, resolved_project_id, "process_provider_job", "provider", resource_id)
        can_start, _snapshot = can_start_provider_jobs(connection, resolved_project_id)
        if not can_start:
            return {"processed": False, "job": None}
        job_id = next_queued_provider_job_id(connection, project_id=resolved_project_id, provider_id=provider_id)
    else:
        job_id, job_project_id = _next_startable_provider_job_id(connection, provider_id=provider_id)
        if job_id is not None:
            if job_project_id is None:
                return {"processed": False, "job": None}
            ensure_board_action_allowed(connection, actor_id, job_project_id, "process_provider_job", "provider", resource_id)
    if job_id is None:
        return {"processed": False, "job": None}
    job = process_provider_job(connection, project_paths, job_id, actor_id, worker_id=worker_id)
    return {"processed": True, "job": job}


def provider_job_queue(connection, project_id=None, provider_id=None, status=None, limit=20):
    return fetch_provider_jobs(connection, project_id=project_id, provider_id=provider_id, status=status, limit=limit)


def list_provider_runtime_status(connection=None, project_id=None):
    return list_provider_status(connection=connection, project_id=project_id)


def provider_runtime_overview(connection=None, project_id=None):
    return fetch_provider_runtime_overview(connection=connection, project_id=project_id)


def set_provider_mode(connection, provider_id, actor_id, mode, project_id=None):
    return update_provider_mode(connection, provider_id, actor_id, mode, project_id=project_id)


def set_provider_settings(connection, provider_id, actor_id, settings, project_id=None):
    return update_provider_settings(connection, provider_id, actor_id, settings, project_id=project_id)
