"""Task scheduling and acceptance evaluation helpers."""

from datetime import datetime
import json
import os
import sqlite3
import subprocess

from maas.ids import generate_id
from maas.services.security import TASK_EXECUTION_CAPABILITIES, grant_task_capabilities


ROLE_KEYWORDS = {
    "allocator": ("plan", "schedule", "priorit", "board", "queue", "workflow", "orchestr", "wire"),
    "researcher": ("define", "research", "investigate", "explore", "discover", "understand", "analyze"),
    "builder": ("implement", "build", "create", "integrate", "bootstrap", "fix", "ship"),
    "reviewer": ("review", "validate", "verify", "audit", "acceptance", "qa"),
}


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


def _parse_timestamp(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _cooldown_active(value):
    next_retry_at = _parse_timestamp(value)
    if next_retry_at is None:
        return False
    return next_retry_at > datetime.utcnow()


def resolve_ready_tasks(connection):
    rows = connection.execute(
        """
        SELECT task_id, title, priority, status, next_retry_at, next_retry_reason
        FROM tasks
        WHERE status IN ('planned', 'assigned', 'ready')
        ORDER BY priority DESC, created_at ASC
        """
    ).fetchall()
    ready = []
    for row in rows:
        if _cooldown_active(row["next_retry_at"]):
            continue
        if _task_is_blocked(connection, row["task_id"]) or _task_has_conflict(connection, row["task_id"]):
            continue
        ready.append(
            {
                "task_id": row["task_id"],
                "title": row["title"],
                "priority": row["priority"],
                "status": row["status"],
                "next_retry_at": row["next_retry_at"],
                "next_retry_reason": row["next_retry_reason"],
            }
        )
    return ready


def refresh_ready_tasks(connection, commit=True):
    task_rows = connection.execute(
        """
        SELECT task_id, status, assigned_agent_id, review_state, next_retry_at, next_retry_reason
        FROM tasks
        WHERE status IN ('planned', 'assigned', 'ready', 'blocked')
        """
    ).fetchall()
    changed = []
    for row in task_rows:
        blocked_by_dependency = _task_is_blocked(connection, row["task_id"])
        blocked_by_conflict = _task_has_conflict(connection, row["task_id"])
        blocked = blocked_by_dependency or blocked_by_conflict
        cooldown_active = _cooldown_active(row["next_retry_at"])
        next_status = row["status"]
        next_review_state = row["review_state"]
        next_retry_at = row["next_retry_at"]
        next_retry_reason = row["next_retry_reason"]

        if blocked and row["status"] in ("planned", "assigned", "ready"):
            next_status = "blocked"
            next_review_state = "blocked_by_conflict" if blocked_by_conflict else "blocked_by_dependency"
        elif cooldown_active and row["status"] in ("planned", "assigned", "ready"):
            next_status = "planned"
            next_review_state = "retry_backoff"
        elif not blocked and row["status"] == "planned":
            next_status = "ready"
            if row["review_state"] == "retry_backoff":
                next_review_state = None
        elif not blocked and row["status"] == "blocked" and row["review_state"] in (
            "blocked_by_dependency",
            "blocked_by_conflict",
        ):
            if cooldown_active:
                next_status = "planned"
                next_review_state = "retry_backoff"
            else:
                next_status = "assigned" if row["assigned_agent_id"] else "ready"
                next_review_state = None

        if not cooldown_active and row["next_retry_at"] is not None:
            next_retry_at = None
            next_retry_reason = None

        if (
            next_status != row["status"]
            or next_review_state != row["review_state"]
            or next_retry_at != row["next_retry_at"]
            or next_retry_reason != row["next_retry_reason"]
        ):
            connection.execute(
                """
                UPDATE tasks
                SET status = ?,
                    review_state = ?,
                    next_retry_at = ?,
                    next_retry_reason = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE task_id = ?
                """,
                (next_status, next_review_state, next_retry_at, next_retry_reason, row["task_id"]),
            )
            changed.append(
                {
                    "task_id": row["task_id"],
                    "status": next_status,
                    "review_state": next_review_state,
                    "next_retry_at": next_retry_at,
                    "next_retry_reason": next_retry_reason,
                }
            )
    if commit:
        connection.commit()
    return changed


def _task_text(task_row):
    return "{0} {1}".format(task_row["title"] or "", task_row["description"] or "").lower()


def _role_bonus(agent_row, task_row):
    if task_row["assigned_agent_id"] == agent_row["agent_id"]:
        return 300

    bonus = 0
    text = _task_text(task_row)
    for keyword in ROLE_KEYWORDS.get(agent_row["role"], ()):
        if keyword in text:
            bonus += 40
            break

    if agent_row["role"] == "builder" and bonus == 0:
        bonus += 10
    return bonus


def _candidate_tasks_for_agent(connection, agent_row):
    refresh_ready_tasks(connection)
    rows = connection.execute(
        """
        SELECT task_id, project_id, title, description, status, priority, assigned_agent_id, created_at
        FROM tasks
        WHERE status IN ('ready', 'assigned')
        ORDER BY priority DESC, created_at ASC
        """
    ).fetchall()

    candidates = []
    for row in rows:
        if row["assigned_agent_id"] and row["assigned_agent_id"] != agent_row["agent_id"]:
            continue
        score = row["priority"] + _role_bonus(agent_row, row)
        candidates.append((score, row))
    candidates.sort(key=lambda item: (-item[0], item[1]["created_at"], item[1]["title"]))
    return [row for _, row in candidates]


def _audit_assignment(connection, project_id, actor_id, task_id, agent_id, assignment_type):
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, ?, 'task', ?, ?)
        """,
        (
            generate_id("audit"),
            project_id,
            actor_id,
            "assign_task",
            task_id,
            json.dumps({"agent_id": agent_id, "assignment_type": assignment_type}),
        ),
    )


def _log_assignment_activity(connection, project_id, agent_id, task_id, description):
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
        ) VALUES (?, ?, ?, ?, 'task_assigned', 'allocation', ?, ?, 'info')
        """,
        (
            generate_id("act"),
            project_id,
            agent_id,
            task_id,
            description,
            json.dumps({}),
        ),
    )


def assign_next_task(connection, agent_id, actor_id="system_allocator"):
    agent_row = connection.execute(
        """
        SELECT agent_id, project_id, role, display_name, status, current_task_id
        FROM agents
        WHERE agent_id = ?
        """,
        (agent_id,),
    ).fetchone()
    if agent_row is None:
        raise ValueError("Agent not found")
    if agent_row["status"] != "idle" or agent_row["current_task_id"] is not None:
        raise ValueError("Agent is not idle")

    candidates = _candidate_tasks_for_agent(connection, agent_row)
    if not candidates:
        return {"agent_id": agent_id, "task_id": None, "assigned": False}

    task_row = candidates[0]
    if task_row["status"] == "assigned" and task_row["assigned_agent_id"] == agent_id:
        return {
            "agent_id": agent_id,
            "task_id": task_row["task_id"],
            "task_title": task_row["title"],
            "status": "assigned",
            "assigned": False,
            "already_assigned": True,
        }

    connection.execute(
        """
        UPDATE tasks
        SET assigned_agent_id = ?,
            status = 'assigned',
            review_state = NULL,
            next_retry_at = NULL,
            next_retry_reason = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ?
        """,
        (agent_id, task_row["task_id"]),
    )
    grant_task_capabilities(
        connection,
        task_row["project_id"],
        task_row["task_id"],
        agent_id,
        TASK_EXECUTION_CAPABILITIES,
        granted_by=actor_id,
    )
    _audit_assignment(connection, task_row["project_id"], actor_id, task_row["task_id"], agent_id, "allocator")
    _log_assignment_activity(
        connection,
        task_row["project_id"],
        agent_id,
        task_row["task_id"],
        "Allocator assigned task to {0}.".format(agent_row["display_name"]),
    )
    connection.commit()
    return {
        "agent_id": agent_id,
        "task_id": task_row["task_id"],
        "task_title": task_row["title"],
        "status": "assigned",
        "assigned": True,
        "already_assigned": False,
    }


def allocate_ready_tasks(connection, actor_id="system_allocator", limit=None):
    idle_agents = connection.execute(
        """
        SELECT agent_id
        FROM agents
        WHERE status = 'idle' AND current_task_id IS NULL
        ORDER BY display_name ASC
        """
    ).fetchall()

    allocations = []
    new_assignment_count = 0
    for row in idle_agents:
        if limit is not None and new_assignment_count >= limit:
            break
        result = assign_next_task(connection, row["agent_id"], actor_id=actor_id)
        if result["task_id"] is None:
            continue
        if result["assigned"]:
            allocations.append(result)
            new_assignment_count += 1

    return {
        "allocations": allocations,
        "assigned_count": new_assignment_count,
    }


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
    try:
        row = connection.execute(query).fetchone()
    except sqlite3.Error as exc:
        return {
            "type": "db_query",
            "passed": False,
            "reason": "Query failed: {0}".format(str(exc)),
        }
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
    try:
        result = subprocess.run(
            command,
            cwd=project_paths.root,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            universal_newlines=True,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.output or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return {
            "type": "test_passes",
            "passed": False,
            "reason": "Command timed out after {0}s".format(timeout),
            "output": output[-500:],
        }
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
