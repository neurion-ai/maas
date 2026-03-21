"""Verification runs and evidence capture for task validation commands."""

import json
import os
import subprocess

from maas.ids import generate_id
from maas.services.projects import resolve_project_id
from maas.services.review_policy import fetch_project_review_policy, should_auto_approve_after_verification
from maas.services.security import ensure_board_action_allowed
from maas.services.steering import apply_review_decision


def _parse_acceptance_criteria(raw_value):
    try:
        parsed = json.loads(raw_value or "[]")
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def task_verification_commands(task_row):
    commands = []
    for criterion in _parse_acceptance_criteria(task_row["acceptance_criteria_json"]):
        if criterion.get("type") != "test_passes":
            continue
        command = (criterion.get("command") or "").strip()
        if not command:
            continue
        commands.append(
            {
                "command": command,
                "timeout_seconds": int(criterion.get("timeout_seconds", 30)),
            }
        )
    return commands


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
        return project_paths.root
    return source_root


def _verification_log_path(project_paths, project_id, verification_run_id):
    directory = os.path.join(project_paths.artifacts_dir, project_id, "verification")
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, "{0}.log".format(verification_run_id))


def fetch_verification_runs(connection, project_id=None, task_id=None, limit=20):
    query = """
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
        WHERE 1 = 1
    """
    params = []
    if project_id is not None:
        resolved_project_id = resolve_project_id(connection, project_id)
        if resolved_project_id is None:
            raise ValueError("project not found")
        query += "\n  AND project_id = ?"
        params.append(resolved_project_id)
    if task_id is not None:
        query += "\n  AND task_id = ?"
        params.append(task_id)
    query += "\nORDER BY finished_at DESC, verification_run_id DESC LIMIT ?"
    params.append(limit)
    rows = connection.execute(query, tuple(params)).fetchall()
    return [dict(row) for row in rows]


def fetch_latest_verification_by_task(connection, project_id=None):
    query = """
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
    """
    params = []
    if project_id is not None:
        resolved_project_id = resolve_project_id(connection, project_id)
        if resolved_project_id is None:
            return {}
        query += "\nWHERE project_id = ?"
        params.append(resolved_project_id)
    query += "\nORDER BY finished_at DESC, verification_run_id DESC"
    rows = connection.execute(query, tuple(params)).fetchall()
    latest = {}
    for row in rows:
        if row["task_id"] in latest:
            continue
        latest[row["task_id"]] = dict(row)
    return latest


def fetch_verification_history_by_task(connection, project_id=None, limit_per_task=None):
    query = """
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
    """
    params = []
    if project_id is not None:
        resolved_project_id = resolve_project_id(connection, project_id)
        if resolved_project_id is None:
            return {}
        query += "\nWHERE project_id = ?"
        params.append(resolved_project_id)
    query += "\nORDER BY finished_at DESC, verification_run_id DESC"
    rows = connection.execute(query, tuple(params)).fetchall()
    history = {}
    for row in rows:
        bucket = history.setdefault(row["task_id"], [])
        if limit_per_task is not None and len(bucket) >= limit_per_task:
            continue
        bucket.append(
            {
                "status": row["status"],
                "finished_at": row["finished_at"],
                "started_at": row["started_at"],
                "command": row["command"],
                "verification_run_id": row["verification_run_id"],
            }
        )
    return history


def run_task_verification(connection, project_paths, task_id, actor_id, commit=True):
    task_row = connection.execute(
        """
        SELECT task_id, project_id, title, acceptance_criteria_json
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if task_row is None:
        raise ValueError("task not found")
    ensure_board_action_allowed(connection, actor_id, task_row["project_id"], "run_task_verification", "task", task_id)

    commands = task_verification_commands(task_row)
    if not commands:
        raise ValueError("task has no verification commands")

    source_root = _project_source_root(connection, task_row["project_id"], project_paths)
    run_results = []
    overall_passed = True

    for command_spec in commands:
        verification_run_id = generate_id("verify")
        command = command_spec["command"]
        timeout_seconds = command_spec["timeout_seconds"]
        started_at = connection.execute("SELECT CURRENT_TIMESTAMP AS ts").fetchone()["ts"]

        status = "failed"
        exit_code = None
        output = ""
        try:
            result = subprocess.run(
                command,
                cwd=source_root,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout_seconds,
                universal_newlines=True,
            )
            output = result.stdout or ""
            exit_code = result.returncode
            status = "passed" if result.returncode == 0 else "failed"
        except subprocess.TimeoutExpired as exc:
            output = exc.output or ""
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            status = "timed_out"

        if status != "passed":
            overall_passed = False

        log_path = _verification_log_path(project_paths, task_row["project_id"], verification_run_id)
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write(output or "")

        artifact_id = generate_id("art")
        connection.execute(
            """
            INSERT INTO artifacts (
                artifact_id, project_id, task_id, artifact_type, path, metadata_json
            ) VALUES (?, ?, ?, 'verification_log', ?, ?)
            """,
            (
                artifact_id,
                task_row["project_id"],
                task_id,
                log_path,
                json.dumps(
                    {
                        "verification_run_id": verification_run_id,
                        "command": command,
                        "status": status,
                        "exit_code": exit_code,
                    }
                ),
            ),
        )
        finished_at = connection.execute("SELECT CURRENT_TIMESTAMP AS ts").fetchone()["ts"]
        output_excerpt = (output or "")[-500:]
        connection.execute(
            """
            INSERT INTO verification_runs (
                verification_run_id, project_id, task_id, command, status, exit_code,
                output_excerpt, artifact_id, actor_id, started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                verification_run_id,
                task_row["project_id"],
                task_id,
                command,
                status,
                exit_code,
                output_excerpt,
                artifact_id,
                actor_id,
                started_at,
                finished_at,
            ),
        )
        run_results.append(
            {
                "verification_run_id": verification_run_id,
                "command": command,
                "status": status,
                "exit_code": exit_code,
                "artifact_id": artifact_id,
                "log_path": log_path,
                "started_at": started_at,
                "finished_at": finished_at,
                "output_excerpt": output_excerpt,
            }
        )

    auto_review = None
    refreshed_task = connection.execute(
        """
        SELECT task_id, project_id, title, status, priority, review_state
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if overall_passed and refreshed_task is not None:
        project_policy = fetch_project_review_policy(connection, refreshed_task["project_id"])
        should_auto_approve, auto_reason = should_auto_approve_after_verification(
            connection,
            refreshed_task,
            run_results,
            project_policy,
        )
        if should_auto_approve:
            auto_review = apply_review_decision(
                connection,
                task_id,
                actor_id="system_supervisor",
                decision="approve",
                commit=False,
                automated=True,
            )
        else:
            auto_review = {"decision": "manual_review", "reason": auto_reason}

    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, 'run_task_verification', 'task', ?, ?)
        """,
        (
            generate_id("audit"),
            task_row["project_id"],
            actor_id,
            task_id,
            json.dumps({"overall_passed": overall_passed, "runs": run_results, "auto_review": auto_review}),
        ),
    )
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, task_id, action, category, description, details_json, severity
        ) VALUES (?, ?, ?, 'task_verification_run', 'verification', ?, ?, ?)
        """,
        (
            generate_id("act"),
            task_row["project_id"],
            task_id,
            "Verification commands executed for task acceptance evidence.",
            json.dumps({"overall_passed": overall_passed, "runs": run_results, "auto_review": auto_review}),
            "info" if overall_passed else "warning",
        ),
    )
    if commit:
        connection.commit()
    return {
        "task_id": task_id,
        "project_id": task_row["project_id"],
        "overall_passed": overall_passed,
        "runs": run_results,
        "auto_review": auto_review,
    }
