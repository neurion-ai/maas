"""Deliverable reads, delivery gates, and GitHub draft PR sync helpers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess

from maas.ids import generate_id
from maas.services.artifacts import artifact_export_bundle_available, build_artifact_export_bundle
from maas.services.projects import resolve_project, resolve_project_id
from maas.services.security import ensure_board_action_allowed
from maas.services.verification import fetch_verification_runs, task_verification_commands


def _load_json(value):
    try:
        payload = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _task_issue_keys(connection, project_id):
    rows = connection.execute(
        """
        SELECT task_id
        FROM tasks
        WHERE project_id = ?
        ORDER BY created_at ASC, task_id ASC
        """,
        (project_id,),
    ).fetchall()
    return {
        row["task_id"]: "ISS-{0}".format(str(index + 1).zfill(4))
        for index, row in enumerate(rows)
    }


def _artifact_preview(path, limit=800):
    if not path or not os.path.exists(path) or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            content = handle.read(limit + 1)
    except OSError:
        return None
    truncated = len(content) > limit
    if truncated:
        content = content[:limit]
    return {"content": content.strip(), "truncated": truncated}


def _delivery_kind(artifact_rows):
    artifact_types = {row["artifact_type"] for row in artifact_rows}
    if "git_diff" in artifact_types:
        return "diff"
    if "bundle" in artifact_types:
        return "bundle"
    if "provider_report" in artifact_types:
        return "report"
    return "artifact"


def _run_command(command, cwd, timeout=20):
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return result


def _git_repo_snapshot(source_root):
    snapshot = {
        "is_git_repo": False,
        "branch": None,
        "default_branch": None,
        "dirty": False,
        "gh_installed": shutil.which("gh") is not None,
    }
    if not source_root or not os.path.isdir(source_root):
        return snapshot
    try:
        result = _run_command(["git", "rev-parse", "--is-inside-work-tree"], cwd=source_root, timeout=5)
        if result.returncode != 0 or (result.stdout or "").strip().lower() != "true":
            return snapshot
    except (OSError, subprocess.SubprocessError):
        return snapshot
    snapshot["is_git_repo"] = True
    try:
        result = _run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=source_root, timeout=5)
        if result.returncode == 0:
            snapshot["branch"] = (result.stdout or "").strip() or None
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        result = _run_command(["git", "symbolic-ref", "refs/remotes/origin/HEAD"], cwd=source_root, timeout=5)
        if result.returncode == 0:
            value = (result.stdout or "").strip()
            if value.startswith("refs/remotes/origin/"):
                snapshot["default_branch"] = value.rsplit("/", 1)[-1]
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        result = _run_command(["git", "status", "--porcelain"], cwd=source_root, timeout=5)
        if result.returncode == 0:
            snapshot["dirty"] = bool((result.stdout or "").strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return snapshot


def _latest_task_artifacts(connection, project_id, task_id, limit=6):
    return connection.execute(
        """
        SELECT artifact_id, artifact_type, path, metadata_json, created_at
        FROM artifacts
        WHERE project_id = ?
          AND task_id = ?
        ORDER BY created_at DESC, artifact_id DESC
        LIMIT ?
        """,
        (project_id, task_id, limit),
    ).fetchall()


def _latest_task_artifact_by_type(connection, project_id, task_id, artifact_type):
    return connection.execute(
        """
        SELECT artifact_id, artifact_type, path, metadata_json, created_at
        FROM artifacts
        WHERE project_id = ?
          AND task_id = ?
          AND artifact_type = ?
        ORDER BY created_at DESC, artifact_id DESC
        LIMIT 1
        """,
        (project_id, task_id, artifact_type),
    ).fetchone()


def _delivery_check(code, label, status, summary, detail=None, metadata=None):
    return {
        "code": code,
        "label": label,
        "status": status,
        "summary": summary,
        "detail": detail or summary,
        "metadata": metadata or {},
    }


def _latest_verification_by_command(verification_runs):
    latest = {}
    for run in verification_runs:
        command = (run.get("command") or "").strip()
        if not command or command in latest:
            continue
        latest[command] = run
    return latest


def _delivery_verification_runs(connection, project_id, task_id, task_row, default_limit=20):
    verification_commands = task_verification_commands(task_row)
    required_commands = []
    seen_commands = set()
    for command_spec in verification_commands:
        command = (command_spec.get("command") or "").strip()
        if not command or command in seen_commands:
            continue
        seen_commands.add(command)
        required_commands.append(command)
    if not required_commands:
        return fetch_verification_runs(connection, project_id=project_id, task_id=task_id, limit=default_limit)
    placeholders = ", ".join("?" for _ in required_commands)
    rows = connection.execute(
        """
        SELECT
            verification_run_id,
            project_id,
            task_id,
            command,
            status,
            exit_code,
            output_excerpt,
            artifact_id,
            actor_id,
            started_at,
            finished_at
        FROM verification_runs
        WHERE project_id = ?
          AND task_id = ?
          AND TRIM(command) IN ({0})
        ORDER BY finished_at DESC, verification_run_id DESC
        """.format(placeholders),
        (project_id, task_id, *required_commands),
    ).fetchall()
    latest = {}
    for row in rows:
        command = (row["command"] or "").strip()
        if not command or command in latest:
            continue
        latest[command] = dict(row)
        if len(latest) == len(required_commands):
            break
    return [latest[command] for command in required_commands if command in latest]


def _task_delivery_gate(task_row, artifacts, bundle_ready, verification_runs, git_snapshot):
    checks = []
    status = task_row["status"]
    if status in {"review", "done"}:
        checks.append(
            _delivery_check(
                "task_state",
                "Task state",
                "passed",
                "Task is in a delivery-capable state.",
                metadata={"task_status": status, "review_state": task_row["review_state"]},
            )
        )
    else:
        checks.append(
            _delivery_check(
                "task_state",
                "Task state",
                "failed",
                "Task is not yet in review or done.",
                "Move the task into review or done before syncing a GitHub draft PR.",
                metadata={"task_status": status, "review_state": task_row["review_state"]},
            )
        )

    if artifacts or bundle_ready:
        checks.append(
            _delivery_check(
                "deliverables",
                "Delivery evidence",
                "passed",
                "Delivery artifacts are available.",
                metadata={"artifact_count": len(artifacts), "bundle_ready": bool(bundle_ready)},
            )
        )
    else:
        checks.append(
            _delivery_check(
                "deliverables",
                "Delivery evidence",
                "failed",
                "No delivery artifacts are available yet.",
                "Capture a diff, report, bundle, or other output before syncing delivery.",
            )
        )

    verification_commands = task_verification_commands(task_row)
    if verification_commands:
        latest_by_command = _latest_verification_by_command(verification_runs)
        missing_commands = []
        failing_commands = []
        for command_spec in verification_commands:
            command = (command_spec.get("command") or "").strip()
            run = latest_by_command.get(command)
            if run is None:
                missing_commands.append(command)
                continue
            if run.get("status") != "passed":
                failing_commands.append({"command": command, "status": run.get("status")})
        if missing_commands or failing_commands:
            detail_parts = []
            if missing_commands:
                detail_parts.append("Missing verification: {0}.".format(", ".join(missing_commands[:3])))
            if failing_commands:
                detail_parts.append(
                    "Latest verification did not pass: {0}.".format(
                        ", ".join(
                            "{0} ({1})".format(item["command"], item["status"])
                            for item in failing_commands[:3]
                        )
                    )
                )
            checks.append(
                _delivery_check(
                    "verification",
                    "Verification gate",
                    "failed",
                    "Delivery verification is incomplete.",
                    " ".join(detail_parts) or "Run the delivery verification commands again before syncing GitHub delivery.",
                    metadata={
                        "required_commands": [item.get("command") for item in verification_commands],
                        "missing_commands": missing_commands,
                        "failing_commands": failing_commands,
                    },
                )
            )
        else:
            checks.append(
                _delivery_check(
                    "verification",
                    "Verification gate",
                    "passed",
                    "Latest delivery verification commands passed.",
                    metadata={"required_commands": [item.get("command") for item in verification_commands]},
                )
            )
    else:
        checks.append(
            _delivery_check(
                "verification",
                "Verification gate",
                "warning",
                "No explicit delivery verification commands are configured.",
                "Operator review is the only gate right now; add task verification commands for stronger delivery proof.",
            )
        )

    branch = git_snapshot.get("branch")
    default_branch = git_snapshot.get("default_branch")
    if not git_snapshot.get("gh_installed"):
        checks.append(
            _delivery_check(
                "github_posture",
                "GitHub posture",
                "failed",
                "GitHub CLI is not installed.",
                "Install `gh` before expecting live GitHub PR sync from MAAS.",
            )
        )
    elif not git_snapshot.get("is_git_repo"):
        checks.append(
            _delivery_check(
                "github_posture",
                "GitHub posture",
                "failed",
                "No Git repository is available for GitHub delivery.",
                "Import or initialize a Git-backed project before syncing GitHub delivery.",
            )
        )
    elif not branch or branch == "HEAD":
        checks.append(
            _delivery_check(
                "github_posture",
                "GitHub posture",
                "failed",
                "GitHub delivery requires a named branch.",
                "Checkout a feature branch before syncing a GitHub draft PR.",
            )
        )
    elif default_branch and branch == default_branch:
        checks.append(
            _delivery_check(
                "github_posture",
                "GitHub posture",
                "failed",
                "GitHub delivery should not sync from the default branch.",
                "Create or switch to a feature branch before syncing a draft PR.",
                metadata={"branch": branch, "default_branch": default_branch},
            )
        )
    else:
        checks.append(
            _delivery_check(
                "github_posture",
                "GitHub posture",
                "passed",
                "Branch posture supports GitHub draft PR sync.",
                metadata={"branch": branch, "default_branch": default_branch},
            )
        )

    overall_status = "ready"
    for check in checks:
        if check["status"] == "failed":
            overall_status = "blocked"
            break
        if check["status"] == "warning":
            overall_status = "attention"
    lead_check = next(
        (item for item in checks if item["status"] == "failed"),
        next((item for item in checks if item["status"] == "warning"), None),
    )
    return {
        "status": overall_status,
        "summary": (
            lead_check["summary"]
            if lead_check is not None
            else "Delivery candidate is ready for GitHub draft PR sync."
        ),
        "detail": (
            lead_check["detail"]
            if lead_check is not None
            else "Task state, delivery artifacts, verification, and branch posture all support GitHub delivery."
        ),
        "checks": checks,
    }


def _delivery_sync_state(sync_artifact):
    if sync_artifact is None:
        return None
    metadata = _load_json(sync_artifact["metadata_json"])
    github_pr = metadata.get("github_pr") or {}
    if not github_pr:
        return None
    return {
        "artifact_id": sync_artifact["artifact_id"],
        "synced_at": sync_artifact["created_at"],
        "mode": github_pr.get("mode"),
        "number": github_pr.get("number"),
        "url": github_pr.get("url"),
        "state": github_pr.get("state"),
        "is_draft": bool(github_pr.get("is_draft")),
        "title": github_pr.get("title"),
        "head_branch": github_pr.get("head_branch"),
        "base_branch": github_pr.get("base_branch"),
        "operation_state": github_pr.get("operation_state") or "succeeded",
        "retryable": bool(github_pr.get("retryable", True)),
        "terminal_failure": bool(github_pr.get("terminal_failure", False)),
        "last_external_result": github_pr.get("last_external_result")
        or {
            "state": github_pr.get("state"),
            "number": github_pr.get("number"),
            "url": github_pr.get("url"),
        },
    }


def _draft_state(draft_artifact):
    if draft_artifact is None:
        return None
    metadata = _load_json(draft_artifact["metadata_json"]).get("delivery") or {}
    return {
        "artifact_id": draft_artifact["artifact_id"],
        "prepared_at": draft_artifact["created_at"],
        "title": metadata.get("title"),
        "issue_key": metadata.get("issue_key"),
        "body_path": draft_artifact["path"],
        "gh_command": "gh pr create --draft --title {0!r} --body-file {1!r}".format(
            metadata.get("title") or "",
            draft_artifact["path"],
        ),
    }


def _task_delivery_item(connection, project_paths, task_row, project_row, issue_keys, git_snapshot=None):
    project_id = task_row["project_id"]
    task_id = task_row["task_id"]
    source_root = project_row["source_root"] or project_paths.root
    git_snapshot = git_snapshot or _git_repo_snapshot(source_root)
    artifacts = _latest_task_artifacts(connection, project_id, task_id, limit=6)
    latest_artifact = artifacts[0] if artifacts else None
    bundle_ready = artifact_export_bundle_available(connection, task_id=task_id)
    verification_runs = _delivery_verification_runs(connection, project_id, task_id, task_row)
    draft_artifact = _latest_task_artifact_by_type(connection, project_id, task_id, "delivery_pr_draft")
    sync_artifact = _latest_task_artifact_by_type(connection, project_id, task_id, "delivery_github_pr_sync")
    gate = _task_delivery_gate(task_row, artifacts, bundle_ready, verification_runs, git_snapshot)
    return {
        "task_id": task_id,
        "issue_key": issue_keys.get(task_id),
        "title": task_row["title"],
        "task_status": task_row["status"],
        "review_state": task_row["review_state"],
        "goal_title": task_row["goal_title"],
        "artifact_count": len(artifacts),
        "created_at": latest_artifact["created_at"] if latest_artifact is not None else task_row["updated_at"],
        "delivery_kind": _delivery_kind(artifacts),
        "latest_artifact_type": latest_artifact["artifact_type"] if latest_artifact is not None else None,
        "latest_artifacts": [
            {
                "artifact_id": artifact["artifact_id"],
                "artifact_type": artifact["artifact_type"],
                "file_name": os.path.basename(artifact["path"]),
                "path": artifact["path"],
                "created_at": artifact["created_at"],
                "preview": (_artifact_preview(artifact["path"], limit=300) or {}).get("content"),
            }
            for artifact in artifacts
        ],
        "bundle_ready": bundle_ready,
        "github_ready": bool(git_snapshot["is_git_repo"] and git_snapshot["gh_installed"]),
        "delivery_gate": gate,
        "latest_draft": _draft_state(draft_artifact),
        "github_pr": _delivery_sync_state(sync_artifact),
    }


def _load_delivery_task(connection, task_id, project_id=None):
    task_row = connection.execute(
        """
        SELECT
            tasks.task_id,
            tasks.project_id,
            tasks.goal_id,
            tasks.title,
            tasks.description,
            tasks.status,
            tasks.review_state,
            tasks.updated_at,
            tasks.acceptance_criteria_json,
            goals.title AS goal_title
        FROM tasks
        LEFT JOIN goals ON goals.goal_id = tasks.goal_id
        WHERE tasks.task_id = ?
          AND (? IS NULL OR tasks.project_id = ?)
        """,
        (task_id, project_id, project_id),
    ).fetchone()
    if task_row is None:
        raise ValueError("task not found")
    return task_row


def _load_delivery_context(connection, project_paths, task_id, project_id=None):
    task_row = _load_delivery_task(connection, task_id, project_id=project_id)
    resolved_project_id = task_row["project_id"]
    project_row = resolve_project(connection, resolved_project_id, include_archived=False)
    source_root = project_row["source_root"] or project_paths.root
    git_snapshot = _git_repo_snapshot(source_root)
    artifacts = _latest_task_artifacts(connection, resolved_project_id, task_id, limit=6)
    bundle_ready = artifact_export_bundle_available(connection, task_id=task_id)
    verification_runs = _delivery_verification_runs(connection, resolved_project_id, task_id, task_row)
    gate = _task_delivery_gate(task_row, artifacts, bundle_ready, verification_runs, git_snapshot)
    issue_keys = _task_issue_keys(connection, resolved_project_id)
    return {
        "task_row": task_row,
        "project_id": resolved_project_id,
        "project_row": project_row,
        "source_root": source_root,
        "git_snapshot": git_snapshot,
        "artifacts": artifacts,
        "bundle_ready": bundle_ready,
        "verification_runs": verification_runs,
        "delivery_gate": gate,
        "issue_key": issue_keys.get(task_id),
    }


def _build_pr_body(task_row, bundle, artifacts):
    preview_blocks = []
    artifact_ids = []
    for artifact in artifacts[:3]:
        artifact_ids.append(artifact["artifact_id"])
        preview = _artifact_preview(artifact["path"], limit=500)
        if preview and preview["content"]:
            preview_blocks.append(
                "### {0}\n\n```\n{1}\n```".format(
                    artifact["artifact_type"],
                    preview["content"],
                )
            )
    title = "[MAAS] {0}".format(task_row["title"])
    body_sections = [
        "## Summary",
        task_row["description"] or "No description provided.",
        "",
        "## Goal",
        task_row["goal_title"] or "No linked goal",
        "",
        "## Review posture",
        "Task status: {0}{1}".format(
            task_row["status"],
            " ({0})".format(task_row["review_state"]) if task_row["review_state"] else "",
        ),
    ]
    if bundle is not None:
        body_sections.extend(
            [
                "",
                "## Bundle",
                "Prepared MAAS export bundle: `{0}`".format(bundle["file_name"]),
            ]
        )
    if preview_blocks:
        body_sections.extend(["", "## Latest outputs", "", "\n\n".join(preview_blocks)])
    body = "\n".join(body_sections).strip() + "\n"
    return {"title": title, "body": body, "artifact_ids": artifact_ids}


def fetch_delivery_overview(connection, project_paths, project_id=None, limit=12):
    resolved_project_id = resolve_project_id(connection, project_id, include_archived=False)
    if resolved_project_id is None:
        raise ValueError("project not found")
    project_row = resolve_project(connection, resolved_project_id, include_archived=False)
    issue_keys = _task_issue_keys(connection, resolved_project_id)
    task_rows = connection.execute(
        """
        SELECT
            tasks.task_id,
            tasks.project_id,
            tasks.title,
            tasks.description,
            tasks.status,
            tasks.review_state,
            tasks.updated_at,
            tasks.acceptance_criteria_json,
            goals.title AS goal_title
        FROM tasks
        LEFT JOIN goals ON goals.goal_id = tasks.goal_id
        WHERE tasks.project_id = ?
          AND tasks.status IN ('review', 'done')
        ORDER BY tasks.updated_at DESC, tasks.created_at DESC
        LIMIT ?
        """,
        (resolved_project_id, max(int(limit or 12), 1)),
    ).fetchall()
    git_snapshot = _git_repo_snapshot(project_row["source_root"] or project_paths.root)
    items = [
        _task_delivery_item(
            connection,
            project_paths,
            row,
            project_row,
            issue_keys,
            git_snapshot=git_snapshot,
        )
        for row in task_rows
    ]
    return {
        "project_id": resolved_project_id,
        "project_name": project_row["name"] if project_row else "",
        "summary": {
            "candidate_count": len(items),
            "bundle_ready_count": len([item for item in items if item["bundle_ready"]]),
            "github_ready_count": len([item for item in items if item["github_ready"]]),
            "diff_count": len([item for item in items if item["delivery_kind"] == "diff"]),
            "report_count": len([item for item in items if item["delivery_kind"] == "report"]),
            "bundle_count": len([item for item in items if item["delivery_kind"] == "bundle"]),
            "ready_count": len([item for item in items if item["delivery_gate"]["status"] == "ready"]),
            "attention_count": len([item for item in items if item["delivery_gate"]["status"] == "attention"]),
            "blocked_count": len([item for item in items if item["delivery_gate"]["status"] == "blocked"]),
            "synced_count": len([item for item in items if item["github_pr"]]),
        },
        "git": git_snapshot,
        "items": items,
    }


def fetch_task_delivery_status(connection, project_paths, task_id, project_id=None):
    context = _load_delivery_context(connection, project_paths, task_id, project_id=project_id)
    issue_keys = _task_issue_keys(connection, context["project_id"])
    item = _task_delivery_item(
        connection,
        project_paths,
        context["task_row"],
        context["project_row"],
        issue_keys,
        git_snapshot=context["git_snapshot"],
    )
    item["git"] = context["git_snapshot"]
    return item


def prepare_github_pr_draft(connection, project_paths, task_id, actor_id, project_id=None):
    context = _load_delivery_context(connection, project_paths, task_id, project_id=project_id)
    ensure_board_action_allowed(connection, actor_id, context["project_id"], "prepare_delivery", "task", task_id)
    if context["task_row"]["status"] not in {"review", "done"}:
        raise ValueError("task is not ready for delivery")
    bundle = build_artifact_export_bundle(connection, project_paths, task_id=task_id)
    if not context["artifacts"] and bundle is None:
        raise ValueError("task has no delivery artifacts to prepare")

    body_payload = _build_pr_body(context["task_row"], bundle, context["artifacts"])
    title = body_payload["title"]
    body = body_payload["body"]

    draft_dir = os.path.join(project_paths.artifacts_dir, "delivery-drafts")
    os.makedirs(draft_dir, exist_ok=True)
    file_name = "{0}-{1}.md".format((context["issue_key"] or task_id).lower(), generate_id("draft"))
    draft_path = os.path.join(draft_dir, file_name)
    with open(draft_path, "w", encoding="utf-8") as handle:
        handle.write(body)
    metadata = {
        "delivery": {
            "title": title,
            "issue_key": context["issue_key"],
            "goal_title": context["task_row"]["goal_title"],
            "source_root": context["source_root"],
            "artifact_ids": body_payload["artifact_ids"],
            "bundle_file_name": bundle["file_name"] if bundle else None,
            "gh_installed": context["git_snapshot"]["gh_installed"],
            "is_git_repo": context["git_snapshot"]["is_git_repo"],
            "branch": context["git_snapshot"]["branch"],
            "default_branch": context["git_snapshot"]["default_branch"],
            "delivery_gate": context["delivery_gate"],
        }
    }
    artifact_id = generate_id("art")
    connection.execute(
        """
        INSERT INTO artifacts (
            artifact_id, project_id, task_id, session_id, artifact_type, path, metadata_json
        ) VALUES (?, ?, ?, NULL, 'delivery_pr_draft', ?, ?)
        """,
        (
            artifact_id,
            context["project_id"],
            task_id,
            draft_path,
            json.dumps(metadata),
        ),
    )
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, 'prepare_delivery', 'task', ?, ?)
        """,
        (
            generate_id("audit"),
            context["project_id"],
            actor_id,
            task_id,
            json.dumps({"artifact_id": artifact_id, "title": title}),
        ),
    )
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, task_id, action, category, description, details_json, severity
        ) VALUES (?, ?, ?, 'delivery_pr_draft_prepared', 'delivery', ?, ?, 'info')
        """,
        (
            generate_id("act"),
            context["project_id"],
            task_id,
            "Prepared a GitHub PR draft for delivery.",
            json.dumps({"artifact_id": artifact_id}),
        ),
    )
    connection.commit()
    return {
        "task_id": task_id,
        "issue_key": context["issue_key"],
        "artifact_id": artifact_id,
        "title": title,
        "body_path": draft_path,
        "bundle_file_name": bundle["file_name"] if bundle else None,
        "gh_command": "gh pr create --draft --title {0!r} --body-file {1!r}".format(title, draft_path),
        "metadata": metadata["delivery"],
        "delivery_gate": context["delivery_gate"],
    }


def _gh_list_pulls(source_root, branch):
    result = _run_command(
        [
            "gh",
            "pr",
            "list",
            "--head",
            branch,
            "--state",
            "all",
            "--limit",
            "10",
            "--json",
            "number,url,state,isDraft,title,headRefName,baseRefName",
        ],
        cwd=source_root,
        timeout=20,
    )
    if result.returncode != 0:
        error_message = (result.stderr or result.stdout or "GitHub PR lookup failed.").strip()
        raise RuntimeError(error_message)
    try:
        payload = json.loads(result.stdout or "[]")
    except ValueError as exc:  # pragma: no cover - guarded by gh output
        raise RuntimeError("GitHub PR lookup returned invalid JSON.") from exc
    return payload if isinstance(payload, list) else []


def _gh_view_pull(source_root, number):
    result = _run_command(
        [
            "gh",
            "pr",
            "view",
            str(number),
            "--json",
            "number,url,state,isDraft,title,headRefName,baseRefName",
        ],
        cwd=source_root,
        timeout=20,
    )
    if result.returncode != 0:
        error_message = (result.stderr or result.stdout or "GitHub PR read failed.").strip()
        raise RuntimeError(error_message)
    try:
        payload = json.loads(result.stdout or "{}")
    except ValueError as exc:  # pragma: no cover - guarded by gh output
        raise RuntimeError("GitHub PR read returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub PR read returned an unexpected response.")
    return payload


def refresh_delivery_github_pr_sync_state(connection, project_paths, project_id):
    project = resolve_project(connection, project_id, include_archived=False)
    if project is None:
        return {"updated": [], "warnings": []}
    source_root = project["source_root"] or project_paths.root
    git_snapshot = _git_repo_snapshot(source_root)
    if not git_snapshot["is_git_repo"] or not git_snapshot["gh_installed"]:
        return {"updated": [], "warnings": []}

    rows = connection.execute(
        """
        SELECT latest.artifact_id, latest.task_id, latest.path, latest.metadata_json
        FROM artifacts AS latest
        JOIN (
            SELECT task_id, MAX(rowid) AS rowid
            FROM artifacts
            WHERE project_id = ?
              AND artifact_type = 'delivery_github_pr_sync'
            GROUP BY task_id
        ) AS ranked
          ON ranked.rowid = latest.rowid
        WHERE latest.project_id = ?
        ORDER BY latest.task_id ASC
        """,
        (project_id, project_id),
    ).fetchall()

    issue_keys = _task_issue_keys(connection, project_id)
    updated = []
    warnings = []
    for row in rows:
        metadata = _load_json(row["metadata_json"])
        github_pr = metadata.get("github_pr") or {}
        number = github_pr.get("number")
        if not number:
            continue
        try:
            pr_record = _gh_view_pull(source_root, number)
        except RuntimeError as exc:
            warnings.append(
                {
                    "task_id": row["task_id"],
                    "issue_key": issue_keys.get(row["task_id"]),
                    "detail": str(exc),
                }
            )
            continue

        refreshed = {
            **github_pr,
            "number": pr_record.get("number"),
            "url": pr_record.get("url"),
            "state": pr_record.get("state"),
            "is_draft": bool(pr_record.get("isDraft")),
            "title": pr_record.get("title"),
            "head_branch": pr_record.get("headRefName") or github_pr.get("head_branch"),
            "base_branch": pr_record.get("baseRefName") or github_pr.get("base_branch"),
            "operation_state": "succeeded",
            "retryable": True,
            "terminal_failure": False,
            "last_external_result": {
                "state": pr_record.get("state"),
                "number": pr_record.get("number"),
                "url": pr_record.get("url"),
                "head_branch": pr_record.get("headRefName") or github_pr.get("head_branch"),
                "base_branch": pr_record.get("baseRefName") or github_pr.get("base_branch"),
            },
        }
        if refreshed == github_pr:
            continue

        connection.execute(
            """
            INSERT INTO artifacts (
                artifact_id, project_id, task_id, session_id, artifact_type, path, metadata_json
            ) VALUES (?, ?, ?, NULL, 'delivery_github_pr_sync', ?, ?)
            """,
            (
                generate_id("art"),
                project_id,
                row["task_id"],
                row["path"],
                json.dumps({**metadata, "github_pr": refreshed}),
            ),
        )
        updated.append(
            {
                "task_id": row["task_id"],
                "issue_key": issue_keys.get(row["task_id"]),
                "number": refreshed.get("number"),
                "state": refreshed.get("state"),
            }
        )
    return {"updated": updated, "warnings": warnings}


def sync_github_pr(connection, project_paths, task_id, actor_id, project_id=None):
    context = _load_delivery_context(connection, project_paths, task_id, project_id=project_id)
    ensure_board_action_allowed(connection, actor_id, context["project_id"], "sync_delivery_github_pr", "task", task_id)
    if context["delivery_gate"]["status"] == "blocked":
        raise ValueError(context["delivery_gate"]["detail"])

    branch = context["git_snapshot"]["branch"]
    default_branch = context["git_snapshot"]["default_branch"] or "main"
    if not branch or branch == "HEAD":
        raise ValueError("GitHub delivery requires a named branch.")
    if branch == default_branch:
        raise ValueError("GitHub delivery should not sync from the default branch.")

    draft = prepare_github_pr_draft(
        connection,
        project_paths,
        task_id=task_id,
        actor_id=actor_id,
        project_id=context["project_id"],
    )
    existing = _gh_list_pulls(context["source_root"], branch)
    open_pull = next((item for item in existing if (item.get("state") or "").upper() == "OPEN"), None)
    if open_pull is not None:
        result = _run_command(
            [
                "gh",
                "pr",
                "edit",
                str(open_pull["number"]),
                "--title",
                draft["title"],
                "--body-file",
                draft["body_path"],
            ],
            cwd=context["source_root"],
            timeout=20,
        )
        if result.returncode != 0:
            error_message = (result.stderr or result.stdout or "GitHub PR update failed.").strip()
            raise RuntimeError(error_message)
        mode = "updated"
        pr_record = _gh_view_pull(context["source_root"], open_pull["number"])
    elif existing:
        closed_pull = existing[0]
        raise ValueError(
            "Branch already has a non-open PR #{0}. Reopen or change branches before syncing delivery.".format(
                closed_pull.get("number")
            )
        )
    else:
        result = _run_command(
            [
                "gh",
                "pr",
                "create",
                "--draft",
                "--head",
                branch,
                "--base",
                default_branch,
                "--title",
                draft["title"],
                "--body-file",
                draft["body_path"],
            ],
            cwd=context["source_root"],
            timeout=30,
        )
        if result.returncode != 0:
            error_message = (result.stderr or result.stdout or "GitHub PR creation failed.").strip()
            raise RuntimeError(error_message)
        mode = "created"
        created = _gh_list_pulls(context["source_root"], branch)
        open_pull = next((item for item in created if (item.get("state") or "").upper() == "OPEN"), None)
        if open_pull is None:
            raise RuntimeError("GitHub PR creation succeeded but no open pull request could be found for the branch.")
        pr_record = _gh_view_pull(context["source_root"], open_pull["number"])

    sync_metadata = {
        "github_pr": {
            "mode": mode,
            "number": pr_record.get("number"),
            "url": pr_record.get("url"),
            "state": pr_record.get("state"),
            "is_draft": bool(pr_record.get("isDraft")),
            "title": pr_record.get("title"),
            "head_branch": pr_record.get("headRefName") or branch,
            "base_branch": pr_record.get("baseRefName") or default_branch,
            "draft_artifact_id": draft["artifact_id"],
            "body_path": draft["body_path"],
            "delivery_gate": context["delivery_gate"],
            "operation_state": "succeeded",
            "retryable": True,
            "terminal_failure": False,
            "last_external_result": {
                "state": pr_record.get("state"),
                "number": pr_record.get("number"),
                "url": pr_record.get("url"),
                "head_branch": pr_record.get("headRefName") or branch,
                "base_branch": pr_record.get("baseRefName") or default_branch,
            },
        }
    }
    sync_artifact_id = generate_id("art")
    connection.execute(
        """
        INSERT INTO artifacts (
            artifact_id, project_id, task_id, session_id, artifact_type, path, metadata_json
        ) VALUES (?, ?, ?, NULL, 'delivery_github_pr_sync', ?, ?)
        """,
        (
            sync_artifact_id,
            context["project_id"],
            task_id,
            draft["body_path"],
            json.dumps(sync_metadata),
        ),
    )
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, 'sync_delivery_github_pr', 'task', ?, ?)
        """,
        (
            generate_id("audit"),
            context["project_id"],
            actor_id,
            task_id,
            json.dumps({"artifact_id": sync_artifact_id, "mode": mode, "number": pr_record.get("number")}),
        ),
    )
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, task_id, action, category, description, details_json, severity
        ) VALUES (?, ?, ?, 'delivery_github_pr_synced', 'delivery', ?, ?, 'info')
        """,
        (
            generate_id("act"),
            context["project_id"],
            task_id,
            "Synced the GitHub draft PR for delivery.",
            json.dumps({"artifact_id": sync_artifact_id, "mode": mode, "url": pr_record.get("url")}),
        ),
    )
    connection.commit()
    return {
        "task_id": task_id,
        "issue_key": context["issue_key"],
        "mode": mode,
        "artifact_id": sync_artifact_id,
        "draft_artifact_id": draft["artifact_id"],
        "title": draft["title"],
        "body_path": draft["body_path"],
        "delivery_gate": context["delivery_gate"],
        "github_pr": {
            "number": pr_record.get("number"),
            "url": pr_record.get("url"),
            "state": pr_record.get("state"),
            "is_draft": bool(pr_record.get("isDraft")),
            "title": pr_record.get("title"),
            "head_branch": pr_record.get("headRefName") or branch,
            "base_branch": pr_record.get("baseRefName") or default_branch,
            "operation_state": "succeeded",
            "retryable": True,
            "terminal_failure": False,
            "last_external_result": {
                "state": pr_record.get("state"),
                "number": pr_record.get("number"),
                "url": pr_record.get("url"),
                "head_branch": pr_record.get("headRefName") or branch,
                "base_branch": pr_record.get("baseRefName") or default_branch,
            },
        },
    }
