"""Git-aware task workspaces and diff evidence."""

import json
import os
import subprocess

from maas.ids import generate_id
from maas.services.security import ensure_board_action_allowed


def _task_row(connection, task_id):
    row = connection.execute(
        """
        SELECT task_id, project_id, title, status
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if row is None:
        raise ValueError("task not found")
    return row


def _project_source_root(connection, project_id, project_paths):
    project_row = connection.execute(
        """
        SELECT source_root
        FROM projects
        WHERE project_id = ?
        """,
        (project_id,),
    ).fetchone()
    source_root = os.path.abspath((project_row["source_root"] if project_row else "") or project_paths.root)
    if not os.path.isdir(source_root):
        raise ValueError("project source root does not exist")
    return source_root


def _run_git(args, cwd, check=True):
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    if check and result.returncode != 0:
        raise ValueError((result.stderr or result.stdout or "git command failed").strip())
    return result


def _project_git_root(connection, project_id, project_paths):
    source_root = _project_source_root(connection, project_id, project_paths)
    result = _run_git(["rev-parse", "--show-toplevel"], source_root, check=False)
    if result.returncode != 0:
        raise ValueError("project source root is not a git repository")
    git_root = os.path.abspath((result.stdout or "").strip())
    if not git_root or not os.path.isdir(git_root):
        raise ValueError("project source root is not a git repository")
    return git_root


def _workspace_branch_name(task_id):
    return "maas/{0}".format(task_id)


def _existing_workspace(connection, task_id):
    row = connection.execute(
        """
        SELECT workspace_id, project_id, task_id, repo_root, branch_name, worktree_path, base_ref,
               head_commit, dirty_file_count, change_summary, last_diff_artifact_id, prepared_at, updated_at
        FROM task_git_workspaces
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _current_head(worktree_path):
    result = _run_git(["rev-parse", "HEAD"], worktree_path, check=False)
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip() or None


def _status_summary(worktree_path):
    status_result = _run_git(["status", "--porcelain=v1"], worktree_path)
    status_lines = [line for line in (status_result.stdout or "").splitlines() if line.strip()]
    changed_files = []
    for line in status_lines:
        path = line[3:] if len(line) > 3 else ""
        if path:
            changed_files.append(path)
    diff_stat = (_run_git(["diff", "--stat", "HEAD"], worktree_path, check=False).stdout or "").strip()
    diff_body = (_run_git(["--no-pager", "diff", "--no-ext-diff", "--unified=3", "HEAD"], worktree_path, check=False).stdout or "")
    return {
        "changed_files": changed_files,
        "dirty_file_count": len(changed_files),
        "change_summary": diff_stat or ("No local changes." if not changed_files else "{0} changed files".format(len(changed_files))),
        "status_lines": status_lines,
        "diff_body": diff_body,
    }


def _diff_artifact_path(project_paths, project_id, artifact_id):
    directory = os.path.join(project_paths.artifacts_dir, project_id, "git-diff")
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, "{0}.diff".format(artifact_id))


def capture_task_git_diff(connection, project_paths, task_id, actor_id, commit=True):
    task_row = _task_row(connection, task_id)
    ensure_board_action_allowed(connection, actor_id, task_row["project_id"], "refresh_task_git_diff", "task", task_id)
    workspace = _existing_workspace(connection, task_id)
    if workspace is None:
        raise ValueError("git workspace not prepared")
    if not os.path.isdir(workspace["worktree_path"]):
        raise ValueError("git workspace path is missing")

    status = _status_summary(workspace["worktree_path"])
    head_commit = _current_head(workspace["worktree_path"])
    artifact_id = generate_id("art")
    artifact_path = _diff_artifact_path(project_paths, task_row["project_id"], artifact_id)
    with open(artifact_path, "w", encoding="utf-8") as handle:
        handle.write(
            "\n".join(
                [
                    "Branch: {0}".format(workspace["branch_name"]),
                    "Head: {0}".format(head_commit or "unknown"),
                    "Worktree: {0}".format(workspace["worktree_path"]),
                    "",
                    "Status:",
                    "\n".join(status["status_lines"]) if status["status_lines"] else "clean",
                    "",
                    "Diff summary:",
                    status["change_summary"],
                    "",
                    "Diff:",
                    status["diff_body"] or "(no diff body)",
                    "",
                ]
            )
        )

    connection.execute(
        """
        INSERT INTO artifacts (
            artifact_id, project_id, task_id, artifact_type, path, metadata_json
        ) VALUES (?, ?, ?, 'git_diff', ?, ?)
        """,
        (
            artifact_id,
            task_row["project_id"],
            task_id,
            artifact_path,
            json.dumps(
                {
                    "workspace_id": workspace["workspace_id"],
                    "branch_name": workspace["branch_name"],
                    "head_commit": head_commit,
                    "changed_files": status["changed_files"],
                    "dirty_file_count": status["dirty_file_count"],
                }
            ),
        ),
    )
    connection.execute(
        """
        UPDATE task_git_workspaces
        SET head_commit = ?,
            dirty_file_count = ?,
            change_summary = ?,
            last_diff_artifact_id = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ?
        """,
        (
            head_commit,
            status["dirty_file_count"],
            status["change_summary"],
            artifact_id,
            task_id,
        ),
    )
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, 'refresh_task_git_diff', 'task', ?, ?)
        """,
        (
            generate_id("audit"),
            task_row["project_id"],
            actor_id,
            task_id,
            json.dumps({"artifact_id": artifact_id, "dirty_file_count": status["dirty_file_count"]}),
        ),
    )
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, task_id, action, category, description, details_json, severity
        ) VALUES (?, ?, ?, 'task_git_diff_refreshed', 'git', ?, ?, 'info')
        """,
        (
            generate_id("act"),
            task_row["project_id"],
            task_id,
            "Git diff evidence captured for task workspace.",
            json.dumps({"artifact_id": artifact_id, "changed_files": status["changed_files"]}),
        ),
    )
    refreshed = _existing_workspace(connection, task_id)
    refreshed["changed_files"] = status["changed_files"]
    if commit:
        connection.commit()
    return refreshed


def prepare_task_git_workspace(connection, project_paths, task_id, actor_id, commit=True):
    task_row = _task_row(connection, task_id)
    ensure_board_action_allowed(connection, actor_id, task_row["project_id"], "prepare_task_git_workspace", "task", task_id)
    if task_row["status"] in ("done", "cancelled"):
        raise ValueError("git workspace is not available for terminal tasks")

    repo_root = _project_git_root(connection, task_row["project_id"], project_paths)
    existing = _existing_workspace(connection, task_id)
    branch_name = (existing or {}).get("branch_name") or _workspace_branch_name(task_id)
    worktree_path = (existing or {}).get("worktree_path") or project_paths.task_git_worktree(task_row["project_id"], task_id)
    os.makedirs(os.path.dirname(worktree_path), exist_ok=True)

    if os.path.isdir(worktree_path) and os.path.exists(os.path.join(worktree_path, ".git")):
        head_commit = _current_head(worktree_path)
        if existing is None:
            connection.execute(
                """
                INSERT INTO task_git_workspaces (
                    workspace_id, project_id, task_id, repo_root, branch_name, worktree_path, base_ref, head_commit
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    generate_id("gws"),
                    task_row["project_id"],
                    task_id,
                    repo_root,
                    branch_name,
                    worktree_path,
                    head_commit,
                    head_commit,
                ),
            )
    else:
        branch_exists = _run_git(["show-ref", "--verify", "--quiet", "refs/heads/{0}".format(branch_name)], repo_root, check=False)
        if branch_exists.returncode == 0:
            _run_git(["worktree", "add", "--force", worktree_path, branch_name], repo_root)
        else:
            _run_git(["worktree", "add", "--force", "-b", branch_name, worktree_path, "HEAD"], repo_root)
        head_commit = _current_head(worktree_path)
        if existing is None:
            connection.execute(
                """
                INSERT INTO task_git_workspaces (
                    workspace_id, project_id, task_id, repo_root, branch_name, worktree_path, base_ref, head_commit
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    generate_id("gws"),
                    task_row["project_id"],
                    task_id,
                    repo_root,
                    branch_name,
                    worktree_path,
                    head_commit,
                    head_commit,
                ),
            )
        else:
            connection.execute(
                """
                UPDATE task_git_workspaces
                SET repo_root = ?,
                    branch_name = ?,
                    worktree_path = ?,
                    head_commit = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE task_id = ?
                """,
                (repo_root, branch_name, worktree_path, head_commit, task_id),
            )

    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, 'prepare_task_git_workspace', 'task', ?, ?)
        """,
        (
            generate_id("audit"),
            task_row["project_id"],
            actor_id,
            task_id,
            json.dumps({"branch_name": branch_name, "worktree_path": worktree_path}),
        ),
    )
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, task_id, action, category, description, details_json, severity
        ) VALUES (?, ?, ?, 'task_git_workspace_prepared', 'git', ?, ?, 'info')
        """,
        (
            generate_id("act"),
            task_row["project_id"],
            task_id,
            "Git workspace prepared for task review.",
            json.dumps({"branch_name": branch_name, "worktree_path": worktree_path}),
        ),
    )

    workspace = capture_task_git_diff(connection, project_paths, task_id, actor_id, commit=False)
    if commit:
        connection.commit()
    return workspace


def fetch_task_git_workspace(connection, task_id):
    workspace = _existing_workspace(connection, task_id)
    if workspace is None:
        return None
    metadata = connection.execute(
        """
        SELECT metadata_json
        FROM artifacts
        WHERE artifact_id = ?
        """,
        (workspace["last_diff_artifact_id"],),
    ).fetchone()
    workspace["changed_files"] = []
    if metadata is not None:
        try:
            workspace["changed_files"] = json.loads(metadata["metadata_json"] or "{}").get("changed_files") or []
        except ValueError:
            workspace["changed_files"] = []
    return workspace


def fetch_latest_git_workspace_by_task(connection, project_id=None):
    query = """
        SELECT workspace_id, project_id, task_id, repo_root, branch_name, worktree_path, base_ref,
               head_commit, dirty_file_count, change_summary, last_diff_artifact_id, prepared_at, updated_at
        FROM task_git_workspaces
    """
    params = []
    if project_id is not None:
        query += "\nWHERE project_id = ?"
        params.append(project_id)
    rows = connection.execute(query, tuple(params)).fetchall()
    return {row["task_id"]: dict(row) for row in rows}
