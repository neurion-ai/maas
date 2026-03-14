"""Task scheduling and acceptance evaluation helpers."""

import json
import os
import subprocess

from maas.ids import generate_id


def _compare(left, operator, right):
    if operator == ">=":
        return left >= right
    if operator == ">":
        return left > right
    if operator == "<=":
        return left <= right
    if operator == "<":
        return left < right
    if operator == "==":
        return left == right
    if operator == "!=":
        return left != right
    raise ValueError("Unsupported operator: {0}".format(operator))


def _task_is_blocked(connection, task_id):
    row = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM task_dependencies td
        JOIN tasks blockers ON blockers.task_id = td.source_task_id
        WHERE td.target_task_id = ?
          AND td.dependency_type = 'blocks'
          AND blockers.status != 'done'
        """,
        (task_id,),
    ).fetchone()
    return row["count"] > 0


def _task_has_conflict(connection, task_id):
    row = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM task_dependencies td
        JOIN tasks conflicts ON conflicts.task_id = td.source_task_id
        WHERE td.target_task_id = ?
          AND td.dependency_type = 'conflicts'
          AND conflicts.status = 'in_progress'
        """,
        (task_id,),
    ).fetchone()
    return row["count"] > 0


def resolve_ready_tasks(connection):
    rows = connection.execute(
        """
        SELECT task_id, title, priority, status
        FROM tasks
        WHERE status IN ('planned', 'assigned', 'ready')
        ORDER BY priority DESC, created_at ASC
        """
    ).fetchall()
    ready = []
    for row in rows:
        if _task_is_blocked(connection, row["task_id"]) or _task_has_conflict(connection, row["task_id"]):
            continue
        ready.append(
            {
                "task_id": row["task_id"],
                "title": row["title"],
                "priority": row["priority"],
                "status": row["status"],
            }
        )
    return ready


def refresh_ready_tasks(connection):
    task_rows = connection.execute(
        """
        SELECT task_id, status, assigned_agent_id, review_state
        FROM tasks
        WHERE status IN ('planned', 'assigned', 'ready', 'blocked')
        """
    ).fetchall()
    changed = []
    for row in task_rows:
        blocked_by_dependency = _task_is_blocked(connection, row["task_id"])
        blocked_by_conflict = _task_has_conflict(connection, row["task_id"])
        blocked = blocked_by_dependency or blocked_by_conflict
        next_status = row["status"]
        next_review_state = row["review_state"]

        if blocked and row["status"] in ("planned", "assigned", "ready"):
            next_status = "blocked"
            next_review_state = "blocked_by_conflict" if blocked_by_conflict else "blocked_by_dependency"
        elif not blocked and row["status"] == "planned":
            next_status = "ready"
        elif not blocked and row["status"] == "blocked" and row["review_state"] in (
            "blocked_by_dependency",
            "blocked_by_conflict",
        ):
            next_status = "assigned" if row["assigned_agent_id"] else "ready"
            next_review_state = None

        if next_status != row["status"] or next_review_state != row["review_state"]:
            connection.execute(
                """
                UPDATE tasks
                SET status = ?, review_state = ?, updated_at = CURRENT_TIMESTAMP
                WHERE task_id = ?
                """,
                (next_status, next_review_state, row["task_id"]),
            )
            changed.append(
                {
                    "task_id": row["task_id"],
                    "status": next_status,
                    "review_state": next_review_state,
                }
            )
    connection.commit()
    return changed


def _evaluate_artifact_exists(connection, task_row, project_paths, criterion):
    path = criterion.get("path")
    if path:
        full_path = path if os.path.isabs(path) else os.path.join(project_paths.root, path)
        passed = os.path.exists(full_path)
        return {"type": "artifact_exists", "passed": passed, "reason": "Path checked: {0}".format(full_path)}

    artifact_count = connection.execute(
        "SELECT COUNT(*) AS count FROM artifacts WHERE task_id = ?",
        (task_row["task_id"],),
    ).fetchone()["count"]
    return {
        "type": "artifact_exists",
        "passed": artifact_count > 0,
        "reason": "Found {0} registered artifacts.".format(artifact_count),
    }


def _evaluate_metric(task_row, criterion):
    metric_name = criterion.get("metric")
    operator = criterion.get("op", ">=")
    expected = criterion.get("value")
    actual = task_row[metric_name] if metric_name in task_row.keys() else None
    if actual is None or expected is None:
        return {"type": "metric", "passed": False, "reason": "Metric or value missing."}
    passed = _compare(actual, operator, expected)
    return {
        "type": "metric",
        "passed": passed,
        "reason": "Metric {0}={1} {2} {3}".format(metric_name, actual, operator, expected),
    }


def _evaluate_db_query(connection, criterion):
    query = criterion.get("query")
    operator = criterion.get("op", ">=")
    expected = criterion.get("value")
    if not query or expected is None:
        return {"type": "db_query", "passed": False, "reason": "Query or expected value missing."}
    row = connection.execute(query).fetchone()
    actual = None if row is None else list(row)[0]
    if actual is None:
        return {"type": "db_query", "passed": False, "reason": "Query returned no rows."}
    passed = _compare(actual, operator, expected)
    return {
        "type": "db_query",
        "passed": passed,
        "reason": "Query result {0} {1} {2}".format(actual, operator, expected),
    }


def _evaluate_test_passes(project_paths, criterion):
    command = criterion.get("command")
    timeout = int(criterion.get("timeout_seconds", 30))
    if not command:
        return {"type": "test_passes", "passed": False, "reason": "Command missing."}
    result = subprocess.run(
        command,
        cwd=project_paths.root,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        universal_newlines=True,
    )
    return {
        "type": "test_passes",
        "passed": result.returncode == 0,
        "reason": "Exit code {0}".format(result.returncode),
        "output": result.stdout[-500:],
    }


def evaluate_acceptance(connection, task_row, project_paths):
    criteria = json.loads(task_row["acceptance_criteria_json"] or "[]")
    results = []
    for criterion in criteria:
        criterion_type = criterion.get("type")
        if criterion_type == "artifact_exists":
            results.append(_evaluate_artifact_exists(connection, task_row, project_paths, criterion))
        elif criterion_type == "metric":
            results.append(_evaluate_metric(task_row, criterion))
        elif criterion_type == "db_query":
            results.append(_evaluate_db_query(connection, criterion))
        elif criterion_type == "test_passes":
            results.append(_evaluate_test_passes(project_paths, criterion))
        else:
            results.append({"type": criterion_type, "passed": False, "reason": "Unknown criterion type."})
    return results


def evaluate_task(connection, project_paths, task_id):
    task_row = connection.execute(
        """
        SELECT task_id, project_id, title, status, priority, progress_pct, acceptance_criteria_json
        FROM tasks
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if task_row is None:
        raise ValueError("Task not found")

    results = evaluate_acceptance(connection, task_row, project_paths)
    overall_passed = bool(results) and all(result["passed"] for result in results)
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, task_id, action, category, description, details_json, severity
        ) VALUES (?, ?, ?, 'task_evaluated', 'evaluation', ?, ?, ?)
        """,
        (
            generate_id("act"),
            task_row["project_id"],
            task_id,
            "Acceptance evaluation completed.",
            json.dumps({"results": results, "overall_passed": overall_passed}),
            "info" if overall_passed else "warning",
        ),
    )
    connection.commit()
    return {
        "task_id": task_id,
        "overall_passed": overall_passed,
        "results": results,
    }
