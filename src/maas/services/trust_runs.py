"""Overnight soak runs, deterministic fault injection, and trust reporting."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import time

from maas.ids import generate_id
from maas.services.fault_injection import (
    activate_fault_injections,
    consume_fault_injection,
    list_fault_injections,
    schedule_fault_injection,
    skip_unapplied_faults,
)
from maas.services.projects import resolve_project, resolve_project_id
from maas.services.security import ensure_board_action_allowed


DEFAULT_TRUST_RUN_PROFILE = "default"
DEFAULT_TRUST_RUN_CYCLE_LIMIT = 6


def _load_json(value):
    try:
        payload = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _default_fault_plan(cycle_limit):
    plan = [
        {"cycle_index": 1, "domain": "provider", "action": "runtime", "summary": "Inject a provider runtime failure."},
        {"cycle_index": 2, "domain": "notification", "action": "deliver", "summary": "Inject a notification delivery failure."},
        {"cycle_index": 3, "domain": "git_workspace", "action": "prepare", "summary": "Inject a git workspace prepare failure."},
        {"cycle_index": 4, "domain": "delivery", "action": "sync", "summary": "Inject a GitHub delivery sync failure."},
        {"cycle_index": 5, "domain": "review", "action": "changes_requested_hold", "summary": "Force a review hold into the queue."},
        {"cycle_index": 6, "domain": "restart", "action": "stale_session_restart", "summary": "Simulate restart-time stale session recovery."},
    ]
    return [item for item in plan if item["cycle_index"] <= cycle_limit]


def _trust_run_row_to_dict(connection, row):
    if row is None:
        return None
    item = dict(row)
    item["config"] = _load_json(item.pop("config_json", "{}"))
    item["summary"] = _load_json(item.pop("summary_json", "{}"))
    item["report"] = _load_json(item.pop("report_json", "{}"))
    incident_row = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM trust_run_incidents
        WHERE trust_run_id = ?
        """,
        (item["trust_run_id"],),
    ).fetchone()
    item["incident_count"] = int(incident_row["count"]) if incident_row is not None else 0
    item["faults"] = list_fault_injections(connection, trust_run_id=item["trust_run_id"])
    item["incidents"] = fetch_trust_run_incidents(connection, item["trust_run_id"], limit=12)
    return item


def fetch_trust_run(connection, trust_run_id):
    row = connection.execute(
        """
        SELECT *
        FROM trust_runs
        WHERE trust_run_id = ?
        """,
        (trust_run_id,),
    ).fetchone()
    return _trust_run_row_to_dict(connection, row)


def fetch_latest_trust_run_summary(connection, project_id):
    row = connection.execute(
        """
        SELECT *
        FROM trust_runs
        WHERE project_id = ?
        ORDER BY started_at DESC, rowid DESC
        LIMIT 1
        """,
        (project_id,),
    ).fetchone()
    return _trust_run_row_to_dict(connection, row)


def fetch_trust_run_incidents(connection, trust_run_id, limit=20):
    rows = connection.execute(
        """
        SELECT *
        FROM trust_run_incidents
        WHERE trust_run_id = ?
        ORDER BY created_at DESC, rowid DESC
        LIMIT ?
        """,
        (trust_run_id, max(1, int(limit))),
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["snapshot"] = _load_json(item.pop("snapshot_json", "{}"))
        item["replay"] = _load_json(item.pop("replay_payload_json", "{}"))
        items.append(item)
    return items


def _insert_trust_run(connection, project_id, actor_id, cycle_limit, sleep_seconds, profile):
    trust_run_id = generate_id("trust")
    config = {
        "cycle_limit": max(1, int(cycle_limit or DEFAULT_TRUST_RUN_CYCLE_LIMIT)),
        "sleep_seconds": max(0, int(sleep_seconds or 0)),
        "profile": profile or DEFAULT_TRUST_RUN_PROFILE,
    }
    connection.execute(
        """
        INSERT INTO trust_runs (
            trust_run_id, project_id, actor_id, profile, status, cycle_limit, sleep_seconds, config_json, summary_json, report_json
        ) VALUES (?, ?, ?, ?, 'running', ?, ?, ?, '{}', '{}')
        """,
        (
            trust_run_id,
            project_id,
            actor_id,
            config["profile"],
            config["cycle_limit"],
            config["sleep_seconds"],
            json.dumps(config),
        ),
    )
    for item in _default_fault_plan(config["cycle_limit"]):
        schedule_fault_injection(
            connection,
            project_id,
            item["domain"],
            item["action"],
            trust_run_id=trust_run_id,
            cycle_index=item["cycle_index"],
            payload={"summary": item["summary"]},
            status="scheduled",
        )
    return trust_run_id


def _update_trust_run(connection, trust_run_id, *, status=None, completed_cycles=None, summary=None, report=None, cycle_started=False, cycle_finished=False):
    assignments = ["updated_at = CURRENT_TIMESTAMP"]
    params = []
    if status is not None:
        assignments.append("status = ?")
        params.append(status)
        if status in {"completed", "failed", "cancelled"}:
            assignments.append("ended_at = CURRENT_TIMESTAMP")
    if completed_cycles is not None:
        assignments.append("completed_cycles = ?")
        params.append(int(completed_cycles))
    if summary is not None:
        assignments.append("summary_json = ?")
        params.append(json.dumps(summary))
    if report is not None:
        assignments.append("report_json = ?")
        params.append(json.dumps(report))
    if cycle_started:
        assignments.append("last_cycle_started_at = CURRENT_TIMESTAMP")
    if cycle_finished:
        assignments.append("last_cycle_finished_at = CURRENT_TIMESTAMP")
    params.append(trust_run_id)
    connection.execute(
        """
        UPDATE trust_runs
        SET {assignments}
        WHERE trust_run_id = ?
        """.format(assignments=", ".join(assignments)),
        tuple(params),
    )


def _pick_task(connection, project_id, statuses):
    placeholders = ", ".join("?" for _ in statuses)
    row = connection.execute(
        """
        SELECT task_id, assigned_agent_id, title, status, review_state
        FROM tasks
        WHERE project_id = ?
          AND status IN ({placeholders})
        ORDER BY priority DESC, created_at ASC, rowid ASC
        LIMIT 1
        """.format(placeholders=placeholders),
        tuple([project_id] + list(statuses)),
    ).fetchone()
    return dict(row) if row is not None else None


def _ensure_provider_candidate(connection, project_id):
    row = connection.execute(
        """
        SELECT tasks.task_id, tasks.assigned_agent_id, tasks.title, tasks.status, tasks.review_state
        FROM tasks
        WHERE tasks.project_id = ?
          AND tasks.assigned_agent_id IS NOT NULL
          AND tasks.status IN ('assigned', 'ready', 'planned', 'blocked')
          AND EXISTS (
              SELECT 1
              FROM task_capability_grants grants
              WHERE grants.project_id = tasks.project_id
                AND grants.task_id = tasks.task_id
                AND grants.agent_id = tasks.assigned_agent_id
                AND grants.capability = 'execute'
                AND grants.revoked_at IS NULL
          )
        ORDER BY tasks.priority DESC, tasks.created_at ASC, tasks.rowid ASC
        LIMIT 1
        """,
        (project_id,),
    ).fetchone()
    task = dict(row) if row is not None else None
    if task is None:
        return None
    if task["status"] in {"blocked", "planned", "ready"}:
        connection.execute(
            """
            UPDATE tasks
            SET status = 'assigned',
                review_state = CASE
                    WHEN review_state IN ('changes_requested', 'paused_by_operator') THEN review_state
                    ELSE NULL
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ?
            """,
            (task["task_id"],),
        )
    task["status"] = "assigned"
    return task


def _ensure_delivery_candidate(connection, project_paths, project_id):
    from maas.services.verification import fetch_verification_runs

    task = _pick_task(connection, project_id, ("review", "assigned", "ready", "planned"))
    if task is None:
        return None
    connection.execute(
        """
        UPDATE tasks
        SET status = 'review',
            review_state = 'review_requested',
            acceptance_criteria_json = ?
        WHERE task_id = ?
        """,
        (json.dumps([{"type": "test_passes", "command": "pytest tests/test_trust.py"}]), task["task_id"]),
    )
    artifact_row = connection.execute(
        """
        SELECT artifact_id
        FROM artifacts
        WHERE project_id = ?
          AND task_id = ?
          AND artifact_type = 'git_diff'
        ORDER BY created_at DESC, rowid DESC
        LIMIT 1
        """,
        (project_id, task["task_id"]),
    ).fetchone()
    if artifact_row is None:
        artifact_id = generate_id("art")
        artifact_dir = os.path.join(project_paths.artifacts_dir, project_id, "trust-runs")
        os.makedirs(artifact_dir, exist_ok=True)
        artifact_path = os.path.join(artifact_dir, "{0}.diff".format(task["task_id"]))
        with open(artifact_path, "w", encoding="utf-8") as handle:
            handle.write("diff --git a/app.py b/app.py\n+print('trust delivery')\n")
        connection.execute(
            """
            INSERT INTO artifacts (
                artifact_id, project_id, task_id, session_id, artifact_type, path, metadata_json
            ) VALUES (?, ?, ?, NULL, 'git_diff', ?, '{}')
            """,
            (artifact_id, project_id, task["task_id"], artifact_path),
        )
    existing_runs = fetch_verification_runs(connection, project_id=project_id, task_id=task["task_id"], limit=5)
    if not any(run["command"] == "pytest tests/test_trust.py" and run["status"] == "passed" for run in existing_runs):
        connection.execute(
            """
            INSERT INTO verification_runs (
                verification_run_id, project_id, task_id, command, status, exit_code, output_excerpt,
                artifact_id, actor_id, started_at, finished_at
            ) VALUES (
                ?, ?, ?, 'pytest tests/test_trust.py', 'passed', 0, 'trust ok',
                NULL, 'agent_reviewer', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            (generate_id("vrf"), project_id, task["task_id"]),
        )
    return task


def _ensure_notification_candidate(connection, project_id, cycle_index, trust_run_id):
    existing = connection.execute(
        """
        SELECT notification_id
        FROM notification_outbox
        WHERE project_id = ?
          AND status IN ('queued', 'failed')
        ORDER BY created_at DESC, rowid DESC
        LIMIT 1
        """,
        (project_id,),
    ).fetchone()
    if existing is not None:
        return existing["notification_id"]
    notification_id = generate_id("notif")
    payload = {"trust_run_id": trust_run_id, "cycle_index": cycle_index}
    connection.execute(
        """
        INSERT INTO notification_outbox (
            notification_id, project_id, target_url, event_type, severity, title, body, payload_json, resource_type,
            resource_id, status, dedupe_key
        ) VALUES (?, ?, ?, 'trust_run_cycle', 'warning', ?, ?, ?, 'project', ?, 'queued', ?)
        """,
        (
            notification_id,
            project_id,
            "http://trust.local/maas",
            "Trust run delivery probe",
            "Deterministic notification used by the unattended trust soak harness.",
            json.dumps(payload),
            project_id,
            "trust:{0}:{1}".format(trust_run_id, cycle_index),
        ),
    )
    return notification_id


def _apply_review_hold(connection, project_id, cycle_index, trust_run_id):
    task = _pick_task(connection, project_id, ("review", "in_progress", "assigned", "ready"))
    if task is None:
        return {"applied": False, "reason": "no_review_candidate"}
    connection.execute(
        """
        UPDATE tasks
        SET status = 'blocked',
            review_state = 'changes_requested',
            updated_at = CURRENT_TIMESTAMP
        WHERE task_id = ?
        """,
        (task["task_id"],),
    )
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
        ) VALUES (?, ?, 'agent_reviewer', ?, 'trust_run_review_hold_injected', 'trust', ?, ?, 'warning')
        """,
        (
            generate_id("act"),
            project_id,
            task["task_id"],
            "Trust run injected a changes-requested review hold.",
            json.dumps({"cycle_index": cycle_index, "trust_run_id": trust_run_id}),
        ),
    )
    return {"applied": True, "task_id": task["task_id"]}


def _simulate_restart_reconcile(connection, project_paths, project_id, trust_run_id, cycle_index):
    from maas.services.reconciliation import reconcile_project_truth

    session = connection.execute(
        """
        SELECT session_id, task_id, agent_id
        FROM sessions
        WHERE project_id = ?
          AND status = 'active'
        ORDER BY started_at ASC, rowid ASC
        LIMIT 1
        """,
        (project_id,),
    ).fetchone()
    if session is not None:
        connection.execute(
            """
            UPDATE sessions
            SET last_heartbeat_at = DATETIME('now', '-7200 seconds')
            WHERE session_id = ?
            """,
            (session["session_id"],),
        )
        connection.execute(
            """
            UPDATE agents
            SET last_heartbeat_at = DATETIME('now', '-7200 seconds')
            WHERE agent_id = ?
            """,
            (session["agent_id"],),
        )
    result = reconcile_project_truth(connection, project_paths, project_id=project_id, actor_id="agent_allocator")
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
        ) VALUES (?, ?, 'agent_allocator', ?, 'trust_run_restart_boundary', 'trust', ?, ?, 'info')
        """,
        (
            generate_id("act"),
            project_id,
            session["task_id"] if session is not None else None,
            "Trust run simulated a restart-time reconciliation pass.",
            json.dumps({"cycle_index": cycle_index, "trust_run_id": trust_run_id, "repairs": result["summary"]["repaired_count"]}),
        ),
    )
    return result


def _store_trust_run_incident(connection, project_id, trust_run_id, incident_kind, incident_key, summary, *, source_type=None, source_id=None, snapshot=None, replay=None):
    connection.execute(
        """
        INSERT OR IGNORE INTO trust_run_incidents (
            replay_id, project_id, trust_run_id, incident_kind, incident_key, source_type, source_id,
            summary, snapshot_json, replay_payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            generate_id("replay"),
            project_id,
            trust_run_id,
            incident_kind,
            incident_key,
            source_type,
            source_id,
            summary,
            json.dumps(snapshot or {}),
            json.dumps(replay or {}),
        ),
    )


def _capture_trust_run_incidents(connection, project_id, trust_run_id, diagnostics):
    new_count = 0
    for warning in (diagnostics.get("truth") or {}).get("warnings", []):
        incident_key = "truth:{0}:{1}".format(
            warning.get("code"),
            warning.get("task_id") or warning.get("agent_id") or warning.get("session_id") or warning.get("summary"),
        )
        before = connection.total_changes
        _store_trust_run_incident(
            connection,
            project_id,
            trust_run_id,
            "truth_warning",
            incident_key,
            warning.get("summary") or warning.get("detail") or "Truth warning",
            source_type="truth",
            source_id=warning.get("task_id") or warning.get("agent_id") or warning.get("session_id"),
            snapshot=warning,
            replay={"action": "reconcile_truth", "project_id": project_id},
        )
        if connection.total_changes > before:
            new_count += 1
    for item in diagnostics.get("attention_items", []) or []:
        stop_state = item.get("stop_state") or {}
        if not stop_state:
            continue
        incident_key = "stop:{0}:{1}".format(
            stop_state.get("reason_key"),
            stop_state.get("resource_id") or item.get("task_id") or item.get("session_id") or item.get("title"),
        )
        before = connection.total_changes
        _store_trust_run_incident(
            connection,
            project_id,
            trust_run_id,
            "stop_state",
            incident_key,
            stop_state.get("summary") or item.get("summary") or "Canonical stop state",
            source_type=stop_state.get("resource_type"),
            source_id=stop_state.get("resource_id"),
            snapshot={"attention_item": item, "stop_state": stop_state},
            replay={
                "action": "open_stop_state",
                "project_id": project_id,
                "resource_type": stop_state.get("resource_type"),
                "resource_id": stop_state.get("resource_id"),
            },
        )
        if connection.total_changes > before:
            new_count += 1
    return new_count


def _build_report(cycle_limit):
    return {
        "status": "running",
        "cycle_limit": cycle_limit,
        "completed_cycles": 0,
        "faults_scheduled": 0,
        "faults_applied": 0,
        "faults_skipped": 0,
        "incident_count": 0,
        "invariant_violations_found": 0,
        "automatic_repairs_attempted": 0,
        "manual_stop_states_raised": 0,
        "unreconciled_truth_mismatches": 0,
        "duplicate_side_effects": 0,
        "recent_cycles": [],
    }


def execute_trust_run(connection, project_paths, project_id, actor_id="agent_allocator", *, cycle_limit=DEFAULT_TRUST_RUN_CYCLE_LIMIT, sleep_seconds=0, profile=DEFAULT_TRUST_RUN_PROFILE):
    from maas.services.codex_mvp import fetch_system_diagnostics
    from maas.services.delivery import sync_github_pr
    from maas.services.git_workspaces import prepare_task_git_workspace
    from maas.services.notifications import process_next_notification
    from maas.services.orchestrator import run_orchestrator_once
    from maas.services.provider_runtime import process_next_provider_job, queue_provider_task

    resolved_project_id = resolve_project_id(connection, project_id, include_archived=False)
    if resolved_project_id is None:
        raise ValueError("project not found")
    actor = ensure_board_action_allowed(connection, actor_id, resolved_project_id, "run_trust_soak", "project", resolved_project_id)
    project_row = resolve_project(connection, resolved_project_id, include_archived=False)
    if project_row is None:
        raise ValueError("project not found")

    trust_run_id = _insert_trust_run(
        connection,
        resolved_project_id,
        actor["actor_id"],
        cycle_limit=cycle_limit,
        sleep_seconds=sleep_seconds,
        profile=profile,
    )
    report = _build_report(cycle_limit)
    report["faults_scheduled"] = len(list_fault_injections(connection, trust_run_id=trust_run_id))
    summary = {
        "project_name": project_row["name"],
        "latest_cycle": None,
        "latest_reconciled_at": None,
    }
    connection.commit()

    try:
        for cycle_index in range(1, max(1, int(cycle_limit)) + 1):
            _update_trust_run(connection, trust_run_id, completed_cycles=cycle_index - 1, summary=summary, report=report, cycle_started=True)
            activated_faults = activate_fault_injections(connection, trust_run_id, cycle_index)
            cycle_summary = {
                "cycle_index": cycle_index,
                "activated_faults": [{"domain": item["domain"], "action": item["action"]} for item in activated_faults],
                "duplicate_side_effects": 0,
            }
            for fault in activated_faults:
                if fault["domain"] == "review":
                    consume_fault_injection(
                        connection,
                        resolved_project_id,
                        "review",
                        "changes_requested_hold",
                    )
                    cycle_summary["review_fault"] = _apply_review_hold(connection, resolved_project_id, cycle_index, trust_run_id)
                elif fault["domain"] == "restart":
                    consume_fault_injection(
                        connection,
                        resolved_project_id,
                        "restart",
                        "stale_session_restart",
                    )
                    cycle_summary["restart_fault"] = _simulate_restart_reconcile(
                        connection,
                        project_paths,
                        resolved_project_id,
                        trust_run_id,
                        cycle_index,
                    )
            provider_target = _ensure_provider_candidate(connection, resolved_project_id)
            if provider_target is not None and provider_target.get("assigned_agent_id"):
                try:
                    queued_job = queue_provider_task(
                        connection,
                        project_paths,
                        provider_id="python_script",
                        actor_id=actor["actor_id"],
                        project_id=resolved_project_id,
                        agent_id=provider_target["assigned_agent_id"],
                        task_id=provider_target["task_id"],
                    )
                    if queued_job.get("duplicate_suppressed"):
                        cycle_summary["duplicate_side_effects"] += 1
                    cycle_summary["queued_provider_job"] = queued_job["job_id"]
                except ValueError as exc:
                    cycle_summary["provider_queue_error"] = str(exc)
            provider_process = process_next_provider_job(
                connection,
                project_paths,
                actor["actor_id"],
                project_id=resolved_project_id,
                provider_id="python_script",
                worker_id="trust_worker",
            )
            cycle_summary["provider_processed"] = bool(provider_process.get("processed"))

            notification_id = _ensure_notification_candidate(connection, resolved_project_id, cycle_index, trust_run_id)
            cycle_summary["notification_id"] = notification_id
            notification_process = process_next_notification(connection, actor["actor_id"], project_id=resolved_project_id)
            cycle_summary["notification_processed"] = bool(notification_process.get("processed"))

            workspace_task = _pick_task(connection, resolved_project_id, ("review", "assigned", "ready"))
            if workspace_task is not None:
                try:
                    workspace = prepare_task_git_workspace(
                        connection,
                        project_paths,
                        workspace_task["task_id"],
                        actor["actor_id"],
                    )
                    cycle_summary["workspace_state"] = workspace.get("prepare_state") or workspace.get("operation_state")
                except Exception as exc:
                    cycle_summary["workspace_error"] = str(exc)

            delivery_task = _ensure_delivery_candidate(connection, project_paths, resolved_project_id)
            if delivery_task is not None:
                try:
                    delivery_payload = sync_github_pr(
                        connection,
                        project_paths,
                        task_id=delivery_task["task_id"],
                        actor_id=actor["actor_id"],
                        project_id=resolved_project_id,
                    )
                    cycle_summary["delivery_state"] = delivery_payload.get("github_pr", {}).get("operation_state")
                except Exception as exc:
                    cycle_summary["delivery_error"] = str(exc)

            orchestrator_summary = run_orchestrator_once(
                connection,
                project_paths,
                allocate_limit=2,
                provider_job_limit=1,
                project_id=resolved_project_id,
                auto_launch_assigned_work=True,
            )
            cycle_summary["orchestrator_project_runs"] = len(orchestrator_summary.get("project_runs") or [])

            diagnostics = fetch_system_diagnostics(connection, resolved_project_id, project_paths=project_paths)
            cycle_summary["truth_warning_count"] = diagnostics["truth"]["summary"]["warning_count"]
            cycle_summary["repair_count"] = diagnostics["truth"]["summary"]["repaired_count"]
            cycle_summary["blocking_stop_states"] = len(
                [
                    item
                    for item in diagnostics.get("attention_items", [])
                    if (item.get("stop_state") or {}).get("autopilot_blocking")
                ]
            )
            new_incidents = _capture_trust_run_incidents(connection, resolved_project_id, trust_run_id, diagnostics)
            cycle_summary["new_incidents"] = new_incidents

            report["completed_cycles"] = cycle_index
            report["incident_count"] += new_incidents
            report["invariant_violations_found"] += diagnostics["truth"]["summary"]["warning_count"]
            report["automatic_repairs_attempted"] += diagnostics["truth"]["summary"]["repaired_count"]
            report["manual_stop_states_raised"] += cycle_summary["blocking_stop_states"]
            report["unreconciled_truth_mismatches"] = max(
                report["unreconciled_truth_mismatches"],
                diagnostics["truth"]["summary"]["warning_count"],
            )
            report["duplicate_side_effects"] += cycle_summary["duplicate_side_effects"]
            applied_faults = list_fault_injections(connection, trust_run_id=trust_run_id)
            report["faults_applied"] = len([item for item in applied_faults if item["status"] == "applied"])
            report["faults_skipped"] = len([item for item in applied_faults if item["status"] == "skipped"])
            report["recent_cycles"] = (report["recent_cycles"] + [cycle_summary])[-8:]
            summary["latest_cycle"] = cycle_summary
            summary["latest_reconciled_at"] = diagnostics["truth"].get("latest_reconciled_at")
            _update_trust_run(
                connection,
                trust_run_id,
                completed_cycles=cycle_index,
                summary=summary,
                report=report,
                cycle_finished=True,
            )
            connection.commit()
            if cycle_index < cycle_limit and sleep_seconds:
                time.sleep(max(0, int(sleep_seconds)))
        skip_unapplied_faults(connection, trust_run_id)
        report["faults_skipped"] = len(
            [item for item in list_fault_injections(connection, trust_run_id=trust_run_id) if item["status"] == "skipped"]
        )
        report["status"] = "attention" if report["unreconciled_truth_mismatches"] else "passed"
        _update_trust_run(
            connection,
            trust_run_id,
            status="completed",
            completed_cycles=cycle_limit,
            summary=summary,
            report=report,
        )
        connection.commit()
    except Exception as exc:
        skip_unapplied_faults(connection, trust_run_id)
        report["status"] = "failed"
        summary["latest_error"] = str(exc)
        _update_trust_run(
            connection,
            trust_run_id,
            status="failed",
            summary=summary,
            report=report,
        )
        connection.commit()
        raise
    return fetch_trust_run(connection, trust_run_id)
