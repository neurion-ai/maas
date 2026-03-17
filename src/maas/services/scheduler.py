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

MAX_RETRY_PRESSURE_PENALTY = 45


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


def _agent_rows(connection):
    return connection.execute(
        """
        SELECT agent_id, project_id, role, display_name, status, current_task_id
        FROM agents
        ORDER BY display_name ASC
        """
    ).fetchall()


def _eligible_idle_agents(agent_rows):
    return [row for row in agent_rows if row["status"] == "idle" and row["current_task_id"] is None]


def resolve_ready_tasks(connection):
    rows = connection.execute(
        """
        SELECT task_id, title, description, priority, status, retry_count, assigned_agent_id, created_at, next_retry_at, next_retry_reason
        FROM tasks
        WHERE status IN ('planned', 'assigned', 'ready')
        ORDER BY priority DESC, created_at ASC
        """
    ).fetchall()
    agent_rows = _agent_rows(connection)
    ready = []
    for row in rows:
        if _cooldown_active(row["next_retry_at"]):
            continue
        if _task_is_blocked(connection, row["task_id"]) or _task_has_conflict(connection, row["task_id"]):
            continue
        ready.append(dict(row))
    decisions = scheduler_decisions_for_tasks(ready, agent_rows)
    ranked_ready = []
    for item in ready:
        decision = decisions.get(item["task_id"], {})
        ranked_ready.append(
            {
                "task_id": item["task_id"],
                "title": item["title"],
                "priority": item["priority"],
                "status": item["status"],
                "next_retry_at": item["next_retry_at"],
                "next_retry_reason": item["next_retry_reason"],
                "scheduler_status": decision.get("scheduler_status"),
                "scheduler_summary": decision.get("scheduler_summary"),
                "scheduler_score": decision.get("scheduler_score"),
                "scheduler_rank": decision.get("scheduler_rank"),
                "scheduler_agent_id": decision.get("scheduler_agent_id"),
                "scheduler_agent_name": decision.get("scheduler_agent_name"),
            }
        )
    ranked_ready.sort(
        key=lambda item: (
            item["scheduler_rank"] is None,
            item["scheduler_rank"] if item["scheduler_rank"] is not None else 999999,
            -item["priority"],
            item["title"],
        )
    )
    return ranked_ready


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


def _age_bonus(task_row):
    created_at = _parse_timestamp(task_row["created_at"])
    if created_at is None:
        return 0
    age_hours = (datetime.utcnow() - created_at).total_seconds() / 3600.0
    if age_hours >= 24:
        return 15
    if age_hours >= 8:
        return 10
    if age_hours >= 2:
        return 5
    return 0


def _retry_pressure_penalty(task_row):
    retry_count = task_row["retry_count"] or 0
    return min(retry_count * 15, MAX_RETRY_PRESSURE_PENALTY)


def _factor(key, label, value):
    return {"key": key, "label": label, "value": value}


def score_task_for_agent(agent_row, task_row):
    factors = [_factor("priority", "Priority", task_row["priority"])]
    age_bonus = _age_bonus(task_row)
    if age_bonus:
        factors.append(_factor("age_bonus", "Task age", age_bonus))

    if task_row["assigned_agent_id"] == agent_row["agent_id"]:
        factors.append(_factor("assignment_bonus", "Existing assignment", 300))
    else:
        role_bonus = _role_bonus(agent_row, task_row)
        if role_bonus:
            label = "Role match" if role_bonus >= 40 else "Default builder fit"
            factors.append(_factor("role_bonus", label, role_bonus))

    retry_penalty = _retry_pressure_penalty(task_row)
    if retry_penalty:
        factors.append(_factor("retry_penalty", "Retry pressure", -retry_penalty))

    total_score = sum(factor["value"] for factor in factors)
    return {"total_score": total_score, "factors": factors}


def _scheduler_summary(decision, include_rank=False):
    parts = []
    if include_rank and decision.get("scheduler_rank") is not None:
        parts.append("Rank #{0}".format(decision["scheduler_rank"]))
    if decision.get("scheduler_agent_name"):
        parts.append("Best fit: {0}".format(decision["scheduler_agent_name"]))
    factor_parts = []
    for factor in decision.get("scheduler_factors", []):
        value = factor["value"]
        if value > 0:
            factor_parts.append("+{0} {1}".format(value, factor["label"].lower()))
        elif value < 0:
            factor_parts.append("{0} {1}".format(value, factor["label"].lower()))
    if factor_parts:
        parts.append(", ".join(factor_parts))
    if not parts:
        return None
    return " | ".join(parts)


def scheduler_decisions_for_tasks(task_rows, agent_rows):
    idle_agents = _eligible_idle_agents(agent_rows)
    agents_by_id = {row["agent_id"]: row for row in agent_rows}
    decisions = {}
    ranked_ready = []

    for task_row in task_rows:
        status = task_row["status"]
        task_id = task_row["task_id"]

        if status == "ready":
            if idle_agents:
                best_agent = None
                best_score = None
                best_factors = None
                for agent_row in idle_agents:
                    scoring = score_task_for_agent(agent_row, task_row)
                    candidate_key = (
                        scoring["total_score"],
                        agent_row["display_name"],
                    )
                    if best_score is None or candidate_key > (best_score, best_agent["display_name"]):
                        best_agent = agent_row
                        best_score = scoring["total_score"]
                        best_factors = scoring["factors"]
                decision = {
                    "scheduler_status": "ready_for_allocation",
                    "scheduler_score": best_score,
                    "scheduler_rank": None,
                    "scheduler_agent_id": best_agent["agent_id"],
                    "scheduler_agent_name": best_agent["display_name"],
                    "scheduler_factors": best_factors or [],
                }
                decisions[task_id] = decision
                ranked_ready.append((best_score, task_row["created_at"], task_row["title"], task_id))
            else:
                decisions[task_id] = {
                    "scheduler_status": "waiting_for_idle_agent",
                    "scheduler_score": None,
                    "scheduler_rank": None,
                    "scheduler_agent_id": None,
                    "scheduler_agent_name": None,
                    "scheduler_factors": [],
                    "scheduler_summary": "Ready, waiting for an idle agent.",
                }
        elif status == "assigned":
            assigned_agent = agents_by_id.get(task_row["assigned_agent_id"])
            if assigned_agent is None:
                decisions[task_id] = {
                    "scheduler_status": "assigned_to_missing_agent",
                    "scheduler_score": None,
                    "scheduler_rank": None,
                    "scheduler_agent_id": None,
                    "scheduler_agent_name": None,
                    "scheduler_factors": [],
                    "scheduler_summary": "Assigned to an agent record that is no longer present.",
                }
            else:
                scoring = score_task_for_agent(assigned_agent, task_row)
                decisions[task_id] = {
                    "scheduler_status": "reserved_for_assigned_agent",
                    "scheduler_score": scoring["total_score"],
                    "scheduler_rank": None,
                    "scheduler_agent_id": assigned_agent["agent_id"],
                    "scheduler_agent_name": assigned_agent["display_name"],
                    "scheduler_factors": scoring["factors"],
                }

    ranked_ready.sort(key=lambda item: (-item[0], item[1], item[2]))
    for rank, (_, _, _, task_id) in enumerate(ranked_ready, start=1):
        decisions[task_id]["scheduler_rank"] = rank
        decisions[task_id]["scheduler_summary"] = _scheduler_summary(decisions[task_id], include_rank=True)

    for task_id, decision in decisions.items():
        if decision.get("scheduler_summary") is None:
            decision["scheduler_summary"] = _scheduler_summary(decision, include_rank=False)
    return decisions


def describe_task_scheduler(task_row, decision=None):
    status = task_row["status"]
    review_state = task_row["review_state"]
    if decision:
        return decision

    if status == "blocked":
        if review_state == "blocked_by_dependency":
            return {"scheduler_status": "blocked_by_dependency", "scheduler_summary": "Blocked until a dependency task is done."}
        if review_state == "blocked_by_conflict":
            return {"scheduler_status": "blocked_by_conflict", "scheduler_summary": "Blocked by a conflicting task that is already in progress."}
        if review_state == "retry_backoff":
            return {
                "scheduler_status": "retry_backoff",
                "scheduler_summary": "Cooling down until the next retry window opens.",
            }
        if review_state in ("session_failed", "stale_session"):
            return {
                "scheduler_status": "blocked_for_recovery",
                "scheduler_summary": "Failure-blocked and waiting for recovery or requeue.",
            }
        return {"scheduler_status": "blocked", "scheduler_summary": "Blocked by an operator or another non-scheduler condition."}
    if status == "planned":
        if review_state == "retry_backoff" or _cooldown_active(task_row["next_retry_at"]):
            return {
                "scheduler_status": "retry_backoff",
                "scheduler_summary": "Cooling down until the next retry window opens.",
            }
        return {"scheduler_status": "planned_not_ready", "scheduler_summary": "Planned, but not yet promoted into the ready queue."}
    if status == "in_progress":
        return {"scheduler_status": "in_progress", "scheduler_summary": "Currently running with an assigned agent."}
    if status == "review":
        return {"scheduler_status": "awaiting_review", "scheduler_summary": "Waiting for operator review before it can continue."}
    if status == "done":
        return {"scheduler_status": "done", "scheduler_summary": "Completed and no longer in the scheduling queue."}
    if status == "cancelled":
        return {"scheduler_status": "cancelled", "scheduler_summary": "Cancelled and removed from future scheduling."}
    return {"scheduler_status": status, "scheduler_summary": None}


def _candidate_tasks_for_agent(connection, agent_row):
    refresh_ready_tasks(connection)
    rows = connection.execute(
        """
        SELECT task_id, project_id, title, description, status, priority, retry_count, assigned_agent_id, created_at
        FROM tasks
        WHERE status IN ('ready', 'assigned')
        ORDER BY priority DESC, created_at ASC
        """
    ).fetchall()

    candidates = []
    for row in rows:
        if row["assigned_agent_id"] and row["assigned_agent_id"] != agent_row["agent_id"]:
            continue
        scoring = score_task_for_agent(agent_row, row)
        candidates.append((scoring["total_score"], row, scoring["factors"]))
    candidates.sort(key=lambda item: (-item[0], item[1]["created_at"], item[1]["title"]))
    return [
        {
            **dict(row),
            "scheduler_score": score,
            "scheduler_factors": factors,
        }
        for score, row, factors in candidates
    ]


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
            "scheduler_score": task_row.get("scheduler_score"),
            "scheduler_factors": task_row.get("scheduler_factors", []),
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
        "scheduler_score": task_row.get("scheduler_score"),
        "scheduler_factors": task_row.get("scheduler_factors", []),
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
