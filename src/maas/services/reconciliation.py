"""Project truth inspection and safe reconciliation."""

from __future__ import annotations

from datetime import datetime, timezone
import json

from maas.ids import generate_id
from maas.services.delivery import refresh_delivery_github_pr_sync_state
from maas.services.projects import resolve_project_id
from maas.services.security import ensure_board_action_allowed


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(value):
    try:
        payload = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _warning(code, summary, detail, *, issue_key=None, task_id=None, agent_id=None, session_id=None, repairable=False, repaired=False):
    return {
        "code": code,
        "summary": summary,
        "detail": detail,
        "issue_key": issue_key,
        "task_id": task_id,
        "agent_id": agent_id,
        "session_id": session_id,
        "repairable": bool(repairable),
        "repaired": bool(repaired),
    }


TASK_SESSION_REPAIRABLE_STATUSES = {"assigned", "in_progress"}
TASK_MANUAL_HOLD_REVIEW_STATES = {"paused_by_operator", "changes_requested", "circuit_breaker_open"}


def _latest_reconciled_at(connection, project_id):
    row = connection.execute(
        """
        SELECT created_at
        FROM activity_log
        WHERE project_id = ?
          AND action = 'truth_reconciled'
        ORDER BY created_at DESC, rowid DESC
        LIMIT 1
        """,
        (project_id,),
    ).fetchone()
    return row["created_at"] if row else None


def _project_rows(connection, project_id):
    tasks = {
        row["task_id"]: dict(row)
        for row in connection.execute(
            """
            SELECT task_id, status, review_state, assigned_agent_id
            FROM tasks
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchall()
    }
    agents = {
        row["agent_id"]: dict(row)
        for row in connection.execute(
            """
            SELECT agent_id, status, current_task_id
            FROM agents
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchall()
    }
    active_sessions = [dict(row) for row in connection.execute(
        """
        SELECT session_id, task_id, agent_id, status, last_heartbeat_at
        FROM sessions
        WHERE project_id = ? AND status = 'active'
        ORDER BY started_at DESC, rowid DESC
        """,
        (project_id,),
    ).fetchall()]
    return tasks, agents, active_sessions


def _analyze_truth(connection, project_id):
    from maas.services.codex_mvp import issue_key_lookup

    issue_keys = issue_key_lookup(connection, project_id)
    tasks, agents, active_sessions = _project_rows(connection, project_id)

    active_by_task = {}
    active_by_agent = {}
    warnings = []
    fix_plan = []

    for session in active_sessions:
        active_by_task.setdefault(session["task_id"], []).append(session)
        active_by_agent.setdefault(session["agent_id"], []).append(session)

    for task_id, sessions in active_by_task.items():
        if len(sessions) > 1:
            warnings.append(
                _warning(
                    "duplicate_active_task_sessions",
                    "Multiple active runs exist for one issue.",
                    "Reconciliation cannot safely choose which run should own the task automatically.",
                    issue_key=issue_keys.get(task_id),
                    task_id=task_id,
                    session_id=sessions[0]["session_id"],
                )
            )
    for agent_id, sessions in active_by_agent.items():
        if len(sessions) > 1:
            task_id = sessions[0].get("task_id")
            warnings.append(
                _warning(
                    "duplicate_active_agent_sessions",
                    "One agent has multiple active runs.",
                    "Reconciliation cannot safely collapse multiple active sessions for the same agent automatically.",
                    issue_key=issue_keys.get(task_id),
                    task_id=task_id,
                    agent_id=agent_id,
                    session_id=sessions[0]["session_id"],
                )
            )

    unique_task_sessions = {task_id: sessions[0] for task_id, sessions in active_by_task.items() if len(sessions) == 1}
    unique_agent_sessions = {agent_id: sessions[0] for agent_id, sessions in active_by_agent.items() if len(sessions) == 1}

    for task_id, session in unique_task_sessions.items():
        task = tasks.get(task_id)
        agent = agents.get(session["agent_id"])
        issue_key = issue_keys.get(task_id)
        if task is None:
            warnings.append(
                _warning(
                    "active_session_missing_task",
                    "An active run points at a missing issue.",
                    "Manual repair is required because the session references a task that no longer exists.",
                    task_id=task_id,
                    agent_id=session["agent_id"],
                    session_id=session["session_id"],
                )
            )
            continue
        if agent is None:
            warnings.append(
                _warning(
                    "active_session_missing_agent",
                    "An active run points at a missing agent.",
                    "Manual repair is required because the session references an agent that no longer exists.",
                    issue_key=issue_key,
                    task_id=task_id,
                    agent_id=session["agent_id"],
                    session_id=session["session_id"],
                )
            )
            continue
        if task.get("status") not in TASK_SESSION_REPAIRABLE_STATUSES or task.get("review_state") in TASK_MANUAL_HOLD_REVIEW_STATES:
            warnings.append(
                _warning(
                    "active_session_conflicts_with_task_state",
                    "An active run conflicts with an intentionally held issue state.",
                    "MAAS will not auto-resume a task whose current state indicates review, blocking, or an explicit operator hold.",
                    issue_key=issue_key,
                    task_id=task_id,
                    agent_id=session["agent_id"],
                    session_id=session["session_id"],
                )
            )
            continue
        if agent.get("status") == "paused":
            warnings.append(
                _warning(
                    "active_session_conflicts_with_agent_state",
                    "An active run conflicts with a paused agent.",
                    "MAAS will not auto-resume an operator-paused agent just because a live session record still exists.",
                    issue_key=issue_key,
                    task_id=task_id,
                    agent_id=session["agent_id"],
                    session_id=session["session_id"],
                )
            )
            continue
        if task.get("assigned_agent_id") != session["agent_id"] or task.get("status") != "in_progress":
            fix_plan.append(
                {
                    "kind": "task_from_active_session",
                    "task_id": task_id,
                    "agent_id": session["agent_id"],
                    "session_id": session["session_id"],
                    "issue_key": issue_key,
                }
            )
        if agent.get("current_task_id") != task_id or agent.get("status") != "running":
            fix_plan.append(
                {
                    "kind": "agent_from_active_session",
                    "task_id": task_id,
                    "agent_id": session["agent_id"],
                    "session_id": session["session_id"],
                    "issue_key": issue_key,
                }
            )

    for task_id, task in tasks.items():
        issue_key = issue_keys.get(task_id)
        active_session = unique_task_sessions.get(task_id)
        assigned_agent_id = task.get("assigned_agent_id")
        assigned_agent_missing = bool(assigned_agent_id) and assigned_agent_id not in agents
        if assigned_agent_missing and task.get("status") != "done":
            next_status = "ready" if task.get("status") in TASK_SESSION_REPAIRABLE_STATUSES else task.get("status")
            fix_plan.append(
                {
                    "kind": "task_assigned_to_missing_agent",
                    "task_id": task_id,
                    "issue_key": issue_key,
                    "next_status": next_status,
                }
            )
            continue
        if task.get("status") == "in_progress" and active_session is None and task_id not in active_by_task:
            next_status = "assigned" if assigned_agent_id else "ready"
            fix_plan.append(
                {
                    "kind": "task_without_active_session",
                    "task_id": task_id,
                    "next_status": next_status,
                    "issue_key": issue_key,
                    "agent_id": assigned_agent_id,
                }
            )

    for agent_id, agent in agents.items():
        current_task_id = agent.get("current_task_id")
        active_session = unique_agent_sessions.get(agent_id)
        if agent.get("status") == "paused":
            continue
        if current_task_id and active_session is None and agent_id not in active_by_agent:
            fix_plan.append(
                {
                    "kind": "idle_agent_cleanup",
                    "task_id": current_task_id,
                    "agent_id": agent_id,
                    "issue_key": issue_keys.get(current_task_id),
                }
            )
        elif not current_task_id and agent.get("status") == "running" and active_session is None and agent_id not in active_by_agent:
            fix_plan.append({"kind": "running_agent_without_task", "agent_id": agent_id})

    return {
        "issue_keys": issue_keys,
        "warnings": warnings,
        "fix_plan": fix_plan,
    }


def inspect_project_truth(connection, project_paths, project_id=None):
    resolved_project_id = resolve_project_id(connection, project_id, include_archived=False)
    if resolved_project_id is None:
        return {
            "project_id": None,
            "generated_at": _utc_now_iso(),
            "latest_reconciled_at": None,
            "summary": {"warning_count": 0, "repairable_count": 0, "repaired_count": 0, "delivery_refresh_count": 0},
            "warnings": [],
        }
    analysis = _analyze_truth(connection, resolved_project_id)
    return {
        "project_id": resolved_project_id,
        "generated_at": _utc_now_iso(),
        "latest_reconciled_at": _latest_reconciled_at(connection, resolved_project_id),
        "summary": {
            "warning_count": len(analysis["warnings"]) + len(analysis["fix_plan"]),
            "repairable_count": len(analysis["fix_plan"]),
            "repaired_count": 0,
            "delivery_refresh_count": 0,
        },
        "warnings": analysis["warnings"]
        + [
            _warning(
                "repairable_truth_drift",
                "Project truth drift is repairable.",
                "MAAS can safely reconcile stale run, task, or agent linkage for this item.",
                issue_key=item.get("issue_key"),
                task_id=item.get("task_id"),
                agent_id=item.get("agent_id"),
                session_id=item.get("session_id"),
                repairable=True,
            )
            for item in analysis["fix_plan"]
        ],
    }


def reconcile_project_truth(connection, project_paths, project_id=None, actor_id=None, source="manual"):
    resolved_project_id = resolve_project_id(connection, project_id, include_archived=False)
    if resolved_project_id is None:
        raise ValueError("project not found")
    if actor_id:
        ensure_board_action_allowed(
            connection,
            actor_id,
            resolved_project_id,
            "reconcile_project_truth",
            "project",
            resolved_project_id,
        )
    analysis = _analyze_truth(connection, resolved_project_id)
    repaired = []

    for item in analysis["fix_plan"]:
        kind = item["kind"]
        if kind == "task_from_active_session":
            connection.execute(
                """
                UPDATE tasks
                SET status = 'in_progress',
                    assigned_agent_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE task_id = ?
                """,
                (item["agent_id"], item["task_id"]),
            )
        elif kind == "agent_from_active_session":
            connection.execute(
                """
                UPDATE agents
                SET status = 'running',
                    current_task_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE agent_id = ?
                """,
                (item["task_id"], item["agent_id"]),
            )
        elif kind == "task_without_active_session":
            connection.execute(
                """
                UPDATE tasks
                SET status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE task_id = ?
                """,
                (item["next_status"], item["task_id"]),
            )
        elif kind == "task_assigned_to_missing_agent":
            connection.execute(
                """
                UPDATE tasks
                SET assigned_agent_id = NULL,
                    status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE task_id = ?
                """,
                (item["next_status"], item["task_id"]),
            )
        elif kind == "idle_agent_cleanup":
            connection.execute(
                """
                UPDATE agents
                SET status = 'idle',
                    current_task_id = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE agent_id = ?
                """,
                (item["agent_id"],),
            )
        elif kind == "running_agent_without_task":
            connection.execute(
                """
                UPDATE agents
                SET status = 'idle',
                    updated_at = CURRENT_TIMESTAMP
                WHERE agent_id = ?
                """,
                (item["agent_id"],),
            )
        repaired.append(item)

    delivery_refresh = refresh_delivery_github_pr_sync_state(connection, project_paths, resolved_project_id)
    refreshed_warnings = list(analysis["warnings"])
    for refresh_warning in delivery_refresh.get("warnings", []):
        refreshed_warnings.append(
            _warning(
                "delivery_pr_refresh_failed",
                "Linked GitHub PR state could not be refreshed.",
                refresh_warning.get("detail") or "MAAS could not refresh the latest linked PR state.",
                issue_key=refresh_warning.get("issue_key"),
                task_id=refresh_warning.get("task_id"),
            )
        )

    if repaired or refreshed_warnings or delivery_refresh.get("updated"):
        payload = {
            "source": source,
            "repaired": repaired,
            "warning_codes": [warning["code"] for warning in refreshed_warnings],
            "delivery_refresh": delivery_refresh,
        }
        connection.execute(
            """
            INSERT INTO audit_trail (
                audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
            ) VALUES (?, ?, ?, 'reconcile_project_truth', 'project', ?, ?)
            """,
            (
                generate_id("audit"),
                resolved_project_id,
                actor_id or "system_reconciler",
                resolved_project_id,
                json.dumps(payload),
            ),
        )
        connection.execute(
            """
            INSERT INTO activity_log (
                activity_id, project_id, action, category, description, details_json, severity
            ) VALUES (?, ?, 'truth_reconciled', 'system', ?, ?, ?)
            """,
            (
                generate_id("act"),
                resolved_project_id,
                "Reconciled project truth and refreshed execution linkage.",
                json.dumps(payload),
                "warning" if refreshed_warnings else "info",
            ),
        )
    connection.commit()

    return {
        "project_id": resolved_project_id,
        "generated_at": _utc_now_iso(),
        "latest_reconciled_at": _latest_reconciled_at(connection, resolved_project_id),
        "summary": {
            "warning_count": len(refreshed_warnings) + len(repaired),
            "repairable_count": len(analysis["fix_plan"]),
            "repaired_count": len(repaired),
            "delivery_refresh_count": len(delivery_refresh.get("updated", [])),
        },
        "warnings": refreshed_warnings
        + [
            _warning(
                "repair_applied",
                "MAAS repaired stale project truth.",
                "A safe reconciliation was applied to restore truthful run, task, or agent linkage.",
                issue_key=item.get("issue_key"),
                task_id=item.get("task_id"),
                agent_id=item.get("agent_id"),
                session_id=item.get("session_id"),
                repairable=True,
                repaired=True,
            )
            for item in repaired
        ],
        "delivery_refresh": delivery_refresh,
    }


def reconcile_active_projects(project_paths):
    from maas.db import connect

    connection = connect(project_paths)
    try:
        project_ids = [
            row["project_id"]
            for row in connection.execute(
                "SELECT project_id FROM projects WHERE state = 'active' ORDER BY created_at ASC"
            ).fetchall()
        ]
        return [reconcile_project_truth(connection, project_paths, project_id=project_id, source="startup") for project_id in project_ids]
    finally:
        connection.close()
