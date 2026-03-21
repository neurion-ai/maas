"""Deliverable and GitHub draft preparation helpers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess

from maas.ids import generate_id
from maas.services.artifacts import artifact_export_bundle_available, build_artifact_export_bundle
from maas.services.projects import resolve_project, resolve_project_id
from maas.services.security import ensure_board_action_allowed


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
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=source_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0 or (result.stdout or "").strip().lower() != "true":
            return snapshot
    except (OSError, subprocess.SubprocessError):
        return snapshot
    snapshot["is_git_repo"] = True
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
            snapshot["branch"] = (result.stdout or "").strip() or None
    except (OSError, subprocess.SubprocessError):
        pass
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
                snapshot["default_branch"] = value.rsplit("/", 1)[-1]
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=source_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
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
            tasks.title,
            tasks.status,
            tasks.review_state,
            tasks.updated_at,
            goals.title AS goal_title,
            COUNT(artifacts.artifact_id) AS artifact_count,
            MAX(artifacts.created_at) AS latest_artifact_at
        FROM tasks
        LEFT JOIN goals ON goals.goal_id = tasks.goal_id
        LEFT JOIN artifacts
            ON artifacts.project_id = tasks.project_id
           AND artifacts.task_id = tasks.task_id
        WHERE tasks.project_id = ?
          AND tasks.status IN ('review', 'done')
        GROUP BY tasks.task_id
        ORDER BY COALESCE(MAX(artifacts.created_at), tasks.updated_at) DESC, tasks.updated_at DESC
        LIMIT ?
        """,
        (resolved_project_id, max(int(limit or 12), 1)),
    ).fetchall()
    git_snapshot = _git_repo_snapshot(project_row["source_root"] or project_paths.root)
    items = []
    for row in task_rows:
        artifacts = _latest_task_artifacts(connection, resolved_project_id, row["task_id"], limit=6)
        latest_artifact = artifacts[0] if artifacts else None
        preview = _artifact_preview(latest_artifact["path"]) if latest_artifact is not None else None
        items.append(
            {
                "task_id": row["task_id"],
                "issue_key": issue_keys.get(row["task_id"]),
                "title": row["title"],
                "task_status": row["status"],
                "review_state": row["review_state"],
                "goal_title": row["goal_title"],
                "artifact_count": row["artifact_count"] or 0,
                "created_at": row["latest_artifact_at"],
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
                "bundle_ready": artifact_export_bundle_available(connection, task_id=row["task_id"]),
                "github_ready": bool(git_snapshot["is_git_repo"] and git_snapshot["gh_installed"]),
            }
        )
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
        },
        "git": git_snapshot,
        "items": items,
    }


def prepare_github_pr_draft(connection, project_paths, task_id, actor_id, project_id=None):
    task_row = connection.execute(
        """
        SELECT
            tasks.task_id,
            tasks.project_id,
            tasks.title,
            tasks.description,
            tasks.status,
            tasks.review_state,
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
    resolved_project_id = task_row["project_id"]
    ensure_board_action_allowed(connection, actor_id, resolved_project_id, "prepare_delivery", "task", task_id)
    project_row = resolve_project(connection, resolved_project_id, include_archived=False)
    source_root = project_row["source_root"] or project_paths.root
    git_snapshot = _git_repo_snapshot(source_root)
    artifacts = _latest_task_artifacts(connection, resolved_project_id, task_id, limit=6)
    bundle = build_artifact_export_bundle(connection, project_paths, task_id=task_id)
    if task_row["status"] not in {"review", "done"}:
        raise ValueError("task is not ready for delivery")
    if not artifacts and bundle is None:
        raise ValueError("task has no delivery artifacts to prepare")
    issue_keys = _task_issue_keys(connection, resolved_project_id)
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

    draft_dir = os.path.join(project_paths.artifacts_dir, "delivery-drafts")
    os.makedirs(draft_dir, exist_ok=True)
    file_name = "{0}-{1}.md".format(issue_keys.get(task_id, task_id).lower(), generate_id("draft"))
    draft_path = os.path.join(draft_dir, file_name)
    with open(draft_path, "w", encoding="utf-8") as handle:
        handle.write(body)
    metadata = {
        "delivery": {
            "title": title,
            "issue_key": issue_keys.get(task_id),
            "goal_title": task_row["goal_title"],
            "source_root": source_root,
            "artifact_ids": artifact_ids,
            "bundle_file_name": bundle["file_name"] if bundle else None,
            "gh_installed": git_snapshot["gh_installed"],
            "is_git_repo": git_snapshot["is_git_repo"],
            "branch": git_snapshot["branch"],
            "default_branch": git_snapshot["default_branch"],
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
            resolved_project_id,
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
            resolved_project_id,
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
            resolved_project_id,
            task_id,
            "Prepared a GitHub PR draft for delivery.",
            json.dumps({"artifact_id": artifact_id}),
        ),
    )
    connection.commit()
    return {
        "task_id": task_id,
        "issue_key": issue_keys.get(task_id),
        "artifact_id": artifact_id,
        "title": title,
        "body_path": draft_path,
        "bundle_file_name": bundle["file_name"] if bundle else None,
        "gh_command": "gh pr create --title {0!r} --body-file {1!r}".format(title, draft_path),
        "metadata": metadata["delivery"],
    }
