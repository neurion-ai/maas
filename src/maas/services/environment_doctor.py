"""Environment and launch-readiness checks for Codex MVP projects."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import shutil
import subprocess

from maas.providers import list_provider_status
from maas.services.autopilot import fetch_autopilot_runtime, fetch_project_autopilot_policy
from maas.services.projects import resolve_project
from maas.services.queue_capacity import queue_capacity_snapshot


def _load_json(value):
    try:
        payload = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _check(code, label, status, summary, detail=None, severity=None, metadata=None):
    resolved_severity = severity
    if resolved_severity is None:
        if status == "failed":
            resolved_severity = "critical"
        elif status in {"warning", "simulation"}:
            resolved_severity = "warning"
        else:
            resolved_severity = "info"
    return {
        "code": code,
        "label": label,
        "status": status,
        "severity": resolved_severity,
        "summary": summary,
        "detail": detail or summary,
        "metadata": metadata or {},
    }


def _codex_auth_available():
    if os.environ.get("OPENAI_API_KEY"):
        return True
    configured = os.environ.get("CODEX_HOME")
    candidates = [configured, os.path.join(os.path.expanduser("~"), ".codex")]
    for candidate in candidates:
        if not candidate:
            continue
        resolved = os.path.abspath(os.path.expanduser(candidate))
        auth_path = os.path.join(resolved, "auth.json")
        if not os.path.exists(auth_path):
            continue
        try:
            with open(auth_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, TypeError, ValueError):
            continue
        if payload.get("OPENAI_API_KEY"):
            return True
        tokens = payload.get("tokens") or {}
        if tokens:
            return True
    return False


def _cli_available(command):
    executable = (command or "").strip()
    if not executable:
        return False
    return shutil.which(executable) is not None


def _git_status(source_root):
    if not source_root or not os.path.isdir(source_root):
        return {"is_git_repo": False, "branch": None, "default_branch": None}
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=source_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0 or (result.stdout or "").strip().lower() != "true":
            return {"is_git_repo": False, "branch": None, "default_branch": None}
    except (OSError, subprocess.SubprocessError):
        return {"is_git_repo": False, "branch": None, "default_branch": None}
    branch = None
    default_branch = None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=source_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            branch = (result.stdout or "").strip() or None
    except (OSError, subprocess.SubprocessError):
        branch = None
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            cwd=source_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            value = (result.stdout or "").strip()
            if value.startswith("refs/remotes/origin/"):
                default_branch = value.rsplit("/", 1)[-1]
    except (OSError, subprocess.SubprocessError):
        default_branch = None
    return {
        "is_git_repo": True,
        "branch": branch,
        "default_branch": default_branch,
    }


def _source_root_checks(source_root):
    checks = []
    if not source_root:
        checks.append(
            _check(
                "source_root_missing",
                "Source root",
                "failed",
                "No source root is configured.",
                "MAAS cannot launch live work without a real source directory.",
            )
        )
        return checks
    if not os.path.isdir(source_root):
        checks.append(
            _check(
                "source_root_missing",
                "Source root",
                "failed",
                "The configured source root does not exist.",
                "Fix the project source root before expecting live Codex execution.",
                metadata={"source_root": source_root},
            )
        )
        return checks
    checks.append(
        _check(
            "source_root_exists",
            "Source root",
            "passed",
            "Source root exists.",
            metadata={"source_root": source_root},
        )
    )
    writable = os.access(source_root, os.W_OK)
    checks.append(
        _check(
            "source_root_writable",
            "Workspace write access",
            "passed" if writable else "failed",
            "Source root is writable." if writable else "Source root is not writable.",
            "Live Codex runs need to write into the project tree or MAAS workspaces.",
            metadata={"source_root": source_root},
        )
    )
    git_status = _git_status(source_root)
    checks.append(
        _check(
            "git_repo_present",
            "Git repository",
            "passed" if git_status["is_git_repo"] else "warning",
            "Git repository detected." if git_status["is_git_repo"] else "No Git repository detected.",
            (
                "MAAS can still work without Git, but delivery and PR preparation will be limited."
                if not git_status["is_git_repo"]
                else "Git-backed delivery flows are available."
            ),
            metadata=git_status,
        )
    )
    return checks


def _provider_checks(connection, project_id):
    checks = []
    providers = list_provider_status(connection=connection, project_id=project_id)
    preferred_provider = None
    provider_rows = {}
    for provider in providers:
        provider_rows[provider["id"]] = provider
    project_row = resolve_project(connection, project_id, include_archived=True)
    config = _load_json(project_row["config_json"] if project_row else "{}")
    preferred_provider_id = ((config.get("provider_capacity") or {}).get("preferred_provider_id") or "openai_codex").strip()
    if preferred_provider_id:
        preferred_provider = provider_rows.get(preferred_provider_id)
    for provider in providers:
        preferred = provider["id"] == preferred_provider_id
        effective_mode = provider.get("effective_execution_mode") or provider.get("execution_mode")
        if effective_mode == "codex_cli":
            cli_command = ((provider.get("configurable_runtime_controls") or {}).get("cli_command") or "codex").strip()
            cli_ready = _cli_available(cli_command)
            auth_ready = _codex_auth_available()
            if cli_ready and auth_ready and provider.get("is_runnable"):
                status = "passed"
                summary = "Codex CLI is ready for live execution."
                detail = "CLI binary and auth are available, and project config accepts live Codex launches."
            elif provider.get("is_runnable"):
                status = "failed"
                problems = []
                if not cli_ready:
                    problems.append("CLI not found")
                if not auth_ready:
                    problems.append("auth missing")
                summary = "Codex CLI is not launch-ready."
                detail = ", ".join(problems) or "Project config is not ready for live Codex execution."
            else:
                status = "failed"
                summary = "Codex provider is misconfigured."
                detail = "; ".join(provider.get("config_warnings") or []) or "Provider configuration is invalid."
            if not preferred and status == "failed":
                status = "warning"
                summary = "{0} is not launch-ready.".format(provider["name"])
                detail = "{0} This does not block live execution while another preferred provider is ready.".format(
                    detail or "Provider configuration is invalid."
                ).strip()
            checks.append(
                _check(
                    "provider_{0}".format(provider["id"]),
                    provider["name"],
                    status,
                    summary,
                    detail,
                    metadata={
                        "provider_id": provider["id"],
                        "preferred": preferred,
                        "effective_execution_mode": effective_mode,
                        "cli_command": cli_command,
                        "cli_ready": cli_ready,
                        "auth_ready": auth_ready,
                        "is_runnable": provider.get("is_runnable"),
                    },
                )
            )
            continue

        if effective_mode == "local_simulation":
            status = "simulation" if preferred else "warning"
            checks.append(
                _check(
                    "provider_{0}".format(provider["id"]),
                    provider["name"],
                    status,
                    "{0} is configured for simulation.".format(provider["name"]),
                    (
                        "This provider can exercise MAAS flows, but it will not produce real external execution."
                        if preferred
                        else "This non-preferred provider is only available in simulation, so it is informational unless selected."
                    ),
                    metadata={
                        "provider_id": provider["id"],
                        "preferred": preferred,
                        "effective_execution_mode": effective_mode,
                        "is_runnable": provider.get("is_runnable"),
                    },
                )
            )
            continue

        checks.append(
            _check(
                "provider_{0}".format(provider["id"]),
                provider["name"],
                "warning" if provider.get("is_runnable") or not preferred else "failed",
                provider.get("notes") or "{0} provider state".format(provider["name"]),
                (
                    "{0} This does not block live execution while another preferred provider is ready.".format(
                        "; ".join(provider.get("config_warnings") or []) or provider.get("notes") or ""
                    ).strip()
                    if not preferred
                    else "; ".join(provider.get("config_warnings") or []) or provider.get("notes")
                ),
                metadata={
                    "provider_id": provider["id"],
                    "preferred": preferred,
                    "effective_execution_mode": effective_mode,
                    "is_runnable": provider.get("is_runnable"),
                },
            )
        )
    return checks, preferred_provider


def _goal_checks(connection, project_id):
    row = connection.execute(
        """
        SELECT
            COUNT(*) AS total_goals,
            SUM(CASE WHEN status IN ('approved', 'active') THEN 1 ELSE 0 END) AS active_goals
        FROM goals
        WHERE project_id = ?
        """,
        (project_id,),
    ).fetchone()
    total_goals = row["total_goals"] or 0
    active_goals = row["active_goals"] or 0
    return [
        _check(
            "goals_present",
            "Goals",
            "passed" if total_goals else "warning",
            "{0} goals configured.".format(total_goals),
            (
                "{0} active goals are currently driving issue generation.".format(active_goals)
                if total_goals
                else "MAAS can run without explicit goals, but planning and no-progress diagnosis are much weaker."
            ),
            metadata={"total_goals": total_goals, "active_goals": active_goals},
        )
    ]


def _github_readiness_check(source_root):
    gh_installed = _cli_available("gh")
    git_status = _git_status(source_root)
    if not git_status["is_git_repo"]:
        status = "warning"
        summary = "GitHub delivery is unavailable without Git."
        detail = "Initialize or import a Git repository before expecting PR drafts or branch-aware delivery."
    elif not gh_installed:
        status = "warning"
        summary = "GitHub CLI is not installed."
        detail = "PR draft preparation can still build content, but live GitHub delivery commands will be unavailable."
    else:
        status = "passed"
        summary = "GitHub delivery tooling is locally available."
        detail = "The repo and GitHub CLI are both present, so PR draft preparation can target the local checkout."
    return _check(
        "github_delivery",
        "GitHub delivery",
        status,
        summary,
        detail,
        metadata={
            "gh_installed": gh_installed,
            **git_status,
        },
    )


def _doctor_summary(checks):
    statuses = [item["status"] for item in checks]
    if any(status == "failed" for status in statuses):
        return {
            "status": "blocked",
            "label": "Blocked",
            "summary": "The environment is not ready for live Codex execution.",
            "detail": "Fix the failed checks before expecting safe autonomous live runs.",
        }
    if any(status == "simulation" for status in statuses):
        return {
            "status": "simulation_only",
            "label": "Simulation only",
            "summary": "The project can run in simulation, but not fully live yet.",
            "detail": "MAAS will exercise the control loop, but the preferred runtime is not fully launch-ready.",
        }
    if any(status == "warning" for status in statuses):
        return {
            "status": "attention",
            "label": "Attention needed",
            "summary": "The environment is mostly ready, but there are issues worth fixing.",
            "detail": "MAAS can run, but one or more warnings reduce delivery quality or operator trust.",
        }
    return {
        "status": "ready",
        "label": "Ready",
        "summary": "The environment is ready for live Codex work.",
        "detail": "Source root, runtime, and delivery prerequisites look healthy.",
    }


def _progress_diagnostic(connection, project_id, doctor_summary):
    task_summary = connection.execute(
        """
        SELECT
            SUM(CASE WHEN status = 'planned' THEN 1 ELSE 0 END) AS planned_tasks,
            SUM(CASE WHEN status = 'ready' THEN 1 ELSE 0 END) AS ready_tasks,
            SUM(CASE WHEN status = 'assigned' THEN 1 ELSE 0 END) AS assigned_tasks,
            SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) AS active_tasks,
            SUM(CASE WHEN status = 'review' THEN 1 ELSE 0 END) AS review_tasks,
            SUM(CASE WHEN status = 'blocked' THEN 1 ELSE 0 END) AS blocked_tasks
        FROM tasks
        WHERE project_id = ?
        """,
        (project_id,),
    ).fetchone()
    autopilot_policy = fetch_project_autopilot_policy(connection, project_id)
    runtime = fetch_autopilot_runtime(connection, project_id) or {}
    queue_snapshot = queue_capacity_snapshot(connection, project_id)
    review_tasks = task_summary["review_tasks"] or 0
    blocked_tasks = task_summary["blocked_tasks"] or 0
    ready_tasks = task_summary["ready_tasks"] or 0
    assigned_tasks = task_summary["assigned_tasks"] or 0
    active_tasks = task_summary["active_tasks"] or 0
    planned_tasks = task_summary["planned_tasks"] or 0

    reasons = []
    if doctor_summary["status"] == "blocked":
        reasons.append(
            {
                "code": "doctor_blocked",
                "severity": "critical",
                "summary": "Environment doctor is blocking live work.",
                "detail": "Fix the failed doctor checks before expecting safe live Codex execution.",
                "recommended_action": "Open the doctor panel and clear the failed readiness checks.",
            }
        )
    if queue_snapshot.get("queue_mode") == "paused":
        reasons.append(
            {
                "code": "queue_paused",
                "severity": "critical",
                "summary": "Launches are paused.",
                "detail": "Assigned issues will not launch while provider capacity posture is paused.",
                "recommended_action": "Resume launches or disable autopilot if the pause is intentional.",
            }
        )
    if queue_snapshot.get("queue_mode") == "draining":
        reasons.append(
            {
                "code": "queue_draining",
                "severity": "warning",
                "summary": "Queue is draining.",
                "detail": "Running and queued jobs can finish, but newly assigned work will not launch.",
                "recommended_action": "Return queue posture to running when you want fresh work to launch.",
            }
        )
    if int(queue_snapshot.get("max_running_jobs") or 0) <= 0:
        reasons.append(
            {
                "code": "zero_capacity",
                "severity": "critical",
                "summary": "Max running jobs is zero.",
                "detail": "The project cannot launch live provider work until capacity is increased.",
                "recommended_action": "Raise project capacity above zero.",
            }
        )
    if active_tasks:
        status = "running"
        summary = "MAAS is actively working."
        detail = "Live sessions are in progress and the queue is moving."
        recommended_action = "Let active runs continue unless the live console or stale diagnostics say otherwise."
    elif review_tasks:
        status = "waiting_for_review"
        summary = "Work is waiting on review."
        detail = "Review decisions are the main gate on forward progress right now."
        recommended_action = "Use review packets or auto-approval policy to clear the queue."
    elif assigned_tasks:
        status = "waiting_for_launch"
        summary = "Assigned work is waiting to launch."
        detail = "The scheduler already picked owners, but launches have not started yet."
        recommended_action = "Check launch posture, provider readiness, and live capacity."
    elif ready_tasks:
        status = "waiting_for_assignment"
        summary = "Ready work exists but is not assigned yet."
        detail = "The next scheduler pass should allocate ready tasks to agents."
        recommended_action = "Let autopilot run or trigger a cycle to allocate work."
    elif blocked_tasks:
        status = "blocked"
        summary = "Remaining work is blocked."
        detail = "Blocked tasks or repeated failures are now the dominant limiter."
        recommended_action = "Use the Issues view or operator inbox to recover or replan blocked work."
    elif planned_tasks:
        status = "planned_only"
        summary = "The project has a backlog but nothing is runnable yet."
        detail = "Planned tasks need dependencies cleared or a scheduler refresh before they become ready."
        recommended_action = "Refresh planning or inspect dependency chains."
    else:
        status = "idle"
        summary = "No runnable work exists."
        detail = "There are no active, assigned, ready, review, or blocked tasks in this project."
        recommended_action = "Create or synthesize a goal plan, or import work into the project."
    if not autopilot_policy.get("enabled"):
        reasons.append(
            {
                "code": "autopilot_disabled",
                "severity": "warning",
                "summary": "Autopilot is disabled.",
                "detail": "MAAS will only move when the operator runs cycles manually.",
                "recommended_action": "Enable autopilot if you want the project to keep advancing on its own.",
            }
        )
    elif runtime.get("status") == "error":
        reasons.append(
            {
                "code": "autopilot_error",
                "severity": "critical",
                "summary": "Autopilot reported an error.",
                "detail": runtime.get("last_error") or "The autonomous control loop failed during its last pass.",
                "recommended_action": "Inspect the latest run/system diagnostics and restart autopilot after clearing the failure.",
            }
        )
    return {
        "status": status,
        "summary": summary,
        "detail": detail,
        "recommended_action": recommended_action,
        "reasons": reasons,
        "facts": {
            "planned_tasks": planned_tasks,
            "ready_tasks": ready_tasks,
            "assigned_tasks": assigned_tasks,
            "active_tasks": active_tasks,
            "review_tasks": review_tasks,
            "blocked_tasks": blocked_tasks,
            "queue_mode": queue_snapshot.get("queue_mode"),
            "max_running_jobs": queue_snapshot.get("max_running_jobs"),
            "autopilot_enabled": autopilot_policy.get("enabled"),
        },
    }


def fetch_environment_doctor(connection, project_paths, project_id=None):
    project = resolve_project(connection, project_id, include_archived=False)
    if project is None:
        raise ValueError("project not found")
    source_root = os.path.abspath(project["source_root"] or project_paths.root)
    checks = []
    checks.extend(_source_root_checks(source_root))
    provider_checks, preferred_provider = _provider_checks(connection, project["project_id"])
    checks.extend(provider_checks)
    checks.extend(_goal_checks(connection, project["project_id"]))
    checks.append(_github_readiness_check(source_root))
    summary = _doctor_summary(checks)
    progress = _progress_diagnostic(connection, project["project_id"], summary)
    recommendations = [item["recommended_action"] for item in progress["reasons"] if item.get("recommended_action")]
    if not recommendations:
        recommendations.append(progress["recommended_action"])
    return {
        "generated_at": _now_iso(),
        "project_id": project["project_id"],
        "project_name": project["name"],
        "source_root": source_root,
        "preferred_provider_id": preferred_provider["id"] if preferred_provider else None,
        "summary": summary,
        "checks": checks,
        "progress": progress,
        "recommended_actions": recommendations[:5],
    }
