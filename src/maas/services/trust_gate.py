"""Unattended local trust eligibility and mode control."""

from __future__ import annotations

from datetime import datetime, timezone
import json

from maas.ids import generate_id
from maas.services.github_project_sync import inspect_github_project_truth
from maas.services.operator_actions import project_autopilot_action, project_launch_posture_action
from maas.services.projects import resolve_project, resolve_project_id
from maas.services.queue_capacity import queue_capacity_snapshot
from maas.services.reconciliation import inspect_project_truth, reconcile_project_truth
from maas.services.security import ensure_board_action_allowed
from maas.services.trust_runs import DEFAULT_TRUST_RUN_CYCLE_LIMIT, fetch_latest_trust_run_summary


DEFAULT_TRUST_MAX_AGE_HOURS = 24


def _utc_now():
    return datetime.now(timezone.utc)


def _utc_now_iso():
    return _utc_now().isoformat().replace("+00:00", "Z")


def _parse_timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_seconds(value):
    parsed = _parse_timestamp(value)
    if parsed is None:
        return None
    return max(0, int((_utc_now() - parsed).total_seconds()))


def _load_json(value):
    try:
        payload = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _trust_config(project_row):
    config = _load_json(project_row["config_json"] if project_row else "{}")
    trust = dict(config.get("trust") or {})
    trust.setdefault("unattended_mode_requested", False)
    trust.setdefault("required_passed_cycles", DEFAULT_TRUST_RUN_CYCLE_LIMIT)
    trust.setdefault("max_trust_run_age_hours", DEFAULT_TRUST_MAX_AGE_HOURS)
    return config, trust


def _blocker(code, summary, detail, *, severity="warning", operator_actions=None):
    item = {
        "code": code,
        "summary": summary,
        "detail": detail,
        "severity": severity,
    }
    if operator_actions:
        item["operator_actions"] = operator_actions
    return item


def fetch_project_unattended_trust(connection, project_paths, project_id=None, *, include_remote_board=False):
    resolved_project_id = resolve_project_id(connection, project_id, include_archived=False)
    if resolved_project_id is None:
        raise ValueError("project not found")
    project_row = resolve_project(connection, resolved_project_id, include_archived=False)
    config, trust_config = _trust_config(project_row)
    trust_run = fetch_latest_trust_run_summary(connection, resolved_project_id)
    truth = inspect_project_truth(connection, project_paths, resolved_project_id)
    from maas.services.autopilot import fetch_project_autopilot_policy

    autopilot_policy = fetch_project_autopilot_policy(connection, resolved_project_id)
    queue_snapshot = queue_capacity_snapshot(connection, resolved_project_id)
    blockers = []

    required_cycles = max(1, int(trust_config.get("required_passed_cycles") or DEFAULT_TRUST_RUN_CYCLE_LIMIT))
    max_age_hours = max(1, int(trust_config.get("max_trust_run_age_hours") or DEFAULT_TRUST_MAX_AGE_HOURS))
    unattended_requested = bool(trust_config.get("unattended_mode_requested"))

    if trust_run is None:
        blockers.append(
            _blocker(
                "trust_evidence_missing",
                "No unattended trust soak has been recorded.",
                "Run the trust soak before arming unattended mode so MAAS has current failure-injection evidence for this project.",
                severity="critical",
            )
        )
    else:
        report = trust_run.get("report") or {}
        completed_cycles = int(report.get("completed_cycles") or trust_run.get("completed_cycles") or 0)
        if trust_run.get("status") != "completed":
            blockers.append(
                _blocker(
                    "trust_run_incomplete",
                    "The latest trust soak did not complete.",
                    "Wait for the current soak to finish or rerun it before arming unattended mode.",
                    severity="critical",
                )
            )
        if (report.get("status") or "").lower() != "passed":
            blockers.append(
                _blocker(
                    "trust_run_not_passing",
                    "The latest trust soak still reports unresolved trust issues.",
                    "Clear the remaining trust blockers and rerun the soak until the report passes cleanly.",
                    severity="critical",
                )
            )
        if completed_cycles < required_cycles:
            blockers.append(
                _blocker(
                    "trust_run_insufficient_coverage",
                    "The latest trust soak did not cover enough cycles.",
                    "Increase the trust run to at least {0} completed cycles before relying on unattended mode.".format(required_cycles),
                    severity="warning",
                )
            )
        age_seconds = _age_seconds(trust_run.get("ended_at") or trust_run.get("started_at"))
        if age_seconds is None or age_seconds > max_age_hours * 3600:
            blockers.append(
                _blocker(
                    "trust_run_stale",
                    "The latest trust soak evidence is stale.",
                    "Rerun the trust soak. Overnight trust evidence older than {0} hours is treated as stale.".format(max_age_hours),
                    severity="warning",
                )
            )
        if int(report.get("duplicate_side_effects") or 0) > 0:
            blockers.append(
                _blocker(
                    "duplicate_side_effects_detected",
                    "The latest trust soak detected duplicate external side effects.",
                    "Resolve duplicate PR, notification, workspace, or provider side effects before relying on unattended mode.",
                    severity="critical",
                )
            )
        if int(report.get("unreconciled_truth_mismatches") or 0) > 0:
            blockers.append(
                _blocker(
                    "trust_truth_mismatch",
                    "The latest trust soak ended with unreconciled truth mismatches.",
                    "Run reconciliation and fix the remaining stale truth before arming unattended mode.",
                    severity="critical",
                )
            )

    if int(truth["summary"].get("warning_count") or 0) > 0:
        blockers.append(
            _blocker(
                "live_truth_drift",
                "Project truth still has active warnings.",
                "Reconcile the project truth and clear stale run, task, or agent linkage before leaving MAAS unattended.",
                severity="critical",
            )
        )

    if not autopilot_policy.get("enabled"):
        blockers.append(
            _blocker(
                "autopilot_disabled",
                "Autopilot is disabled.",
                "Enable autopilot before arming unattended mode; otherwise the project will not keep advancing on its own.",
                severity="warning",
                operator_actions=[
                    project_autopilot_action(
                        resolved_project_id,
                        "Enable autopilot",
                        {**autopilot_policy, "enabled": True},
                    )
                ],
            )
        )

    if queue_snapshot.get("queue_mode") != "running":
        blockers.append(
            _blocker(
                "launch_posture_not_running",
                "Launch posture is not set to running.",
                "Resume launches before arming unattended mode so new work can actually start without operator intervention.",
                severity="warning",
                operator_actions=[
                    project_launch_posture_action(
                        resolved_project_id,
                        "Resume launches",
                        "running",
                        queue_snapshot.get("max_running_jobs") or 1,
                        queue_snapshot.get("preferred_provider_id"),
                    )
                ],
            )
        )

    if int(queue_snapshot.get("max_running_jobs") or 0) <= 0:
        blockers.append(
            _blocker(
                "zero_launch_capacity",
                "Provider capacity is zero.",
                "Increase max running jobs above zero before arming unattended mode.",
                severity="critical",
                operator_actions=[
                    project_launch_posture_action(
                        resolved_project_id,
                        "Restore provider capacity",
                        "running",
                        1,
                        queue_snapshot.get("preferred_provider_id"),
                    )
                ],
            )
        )

    project_board = None
    if include_remote_board:
        project_board = inspect_github_project_truth(connection, resolved_project_id)
        if project_board.get("enabled") and not project_board.get("skipped"):
            if project_board.get("warnings"):
                blockers.append(
                    _blocker(
                        "project_board_sync_failed",
                        "GitHub project truth could not be verified cleanly.",
                        project_board["warnings"][0].get("detail") or "The execution board could not be checked cleanly.",
                        severity="warning",
                    )
                )
            elif int(project_board.get("drift_count") or 0) > 0:
                blockers.append(
                    _blocker(
                        "project_board_drift",
                        "GitHub project truth is still stale.",
                        "Reconcile the project board so merged execution state matches the GitHub issue cards before arming unattended mode.",
                        severity="warning",
                    )
                )

    eligible = not blockers
    if unattended_requested and eligible:
        status = "armed"
        summary = "Unattended mode is armed."
        detail = "MAAS has current trust evidence and no live blockers that would make overnight autonomy unsafe right now."
    elif unattended_requested:
        status = "armed_blocked"
        summary = "Unattended mode was requested, but current blockers make it unsafe."
        detail = "MAAS will not treat this project as safe for unattended use until the blockers below are cleared."
    elif eligible:
        status = "eligible"
        summary = "This project is eligible for unattended mode."
        detail = "The latest trust soak passed, launch posture is healthy, and MAAS has no active truth drift for this project."
    elif trust_run is None or any(item["code"].startswith("trust_run") or item["code"] == "trust_evidence_missing" for item in blockers):
        status = "unverified"
        summary = "This project is not yet verified for unattended mode."
        detail = "Trust evidence is missing, stale, incomplete, or still failing. Rerun the trust soak after clearing the listed blockers."
    else:
        status = "blocked"
        summary = "This project has current blockers for unattended mode."
        detail = "The trust evidence may be present, but the live control loop still has blockers that should be cleared before you leave MAAS unattended."

    return {
        "project_id": resolved_project_id,
        "status": status,
        "eligible": eligible,
        "unattended_mode_requested": unattended_requested,
        "summary": summary,
        "detail": detail,
        "checked_at": _utc_now_iso(),
        "required_passed_cycles": required_cycles,
        "max_trust_run_age_hours": max_age_hours,
        "latest_trust_run_id": (trust_run or {}).get("trust_run_id"),
        "latest_trust_run_status": (trust_run or {}).get("status"),
        "latest_trust_run_finished_at": (trust_run or {}).get("ended_at"),
        "truth_warning_count": int(truth["summary"].get("warning_count") or 0),
        "project_board": {
            "enabled": bool((project_board or {}).get("enabled")),
            "drift_count": int((project_board or {}).get("drift_count") or 0),
            "updated_count": int((project_board or {}).get("updated_count") or 0),
            "warnings": (project_board or {}).get("warnings") or [],
        },
        "blockers": blockers,
    }


def update_project_unattended_mode(connection, project_paths, project_id, actor_id, enabled):
    resolved_project_id = resolve_project_id(connection, project_id, include_archived=False)
    if resolved_project_id is None:
        raise ValueError("project not found")
    actor = ensure_board_action_allowed(
        connection,
        actor_id,
        resolved_project_id,
        "update_unattended_mode",
        "project",
        resolved_project_id,
    )
    project_row = resolve_project(connection, resolved_project_id, include_archived=False)
    if project_row is None:
        raise ValueError("project not found")
    config, trust_config = _trust_config(project_row)

    if enabled:
        reconcile_project_truth(
            connection,
            project_paths,
            project_id=resolved_project_id,
            actor_id=actor["actor_id"],
            source="unattended_mode_arm",
        )
        gate = fetch_project_unattended_trust(
            connection,
            project_paths,
            resolved_project_id,
            include_remote_board=True,
        )
        if not gate["eligible"]:
            raise ValueError(gate["summary"])
    else:
        gate = fetch_project_unattended_trust(connection, project_paths, resolved_project_id)

    trust_config["unattended_mode_requested"] = bool(enabled)
    trust_config["last_mode_changed_at"] = _utc_now_iso()
    if enabled:
        trust_config["last_armed_at"] = trust_config["last_mode_changed_at"]
    else:
        trust_config["last_disarmed_at"] = trust_config["last_mode_changed_at"]
    config["trust"] = trust_config

    connection.execute(
        "UPDATE projects SET config_json = ?, updated_at = CURRENT_TIMESTAMP WHERE project_id = ?",
        (json.dumps(config), resolved_project_id),
    )
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, ?, 'project', ?, ?)
        """,
        (
            generate_id("audit"),
            resolved_project_id,
            actor["actor_id"],
            "update_unattended_mode",
            resolved_project_id,
            json.dumps(
                {
                    "enabled": bool(enabled),
                    "trust_gate_status": gate["status"],
                    "eligible": gate["eligible"],
                    "blocker_codes": [item["code"] for item in gate["blockers"]],
                }
            ),
        ),
    )
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, action, category, description, details_json, severity
        ) VALUES (?, ?, 'unattended_mode_updated', 'projects', ?, ?, 'info')
        """,
        (
            generate_id("act"),
            resolved_project_id,
            "Armed unattended mode." if enabled else "Disarmed unattended mode.",
            json.dumps({"enabled": bool(enabled), "actor_id": actor["actor_id"]}),
        ),
    )
    connection.commit()
    return fetch_project_unattended_trust(connection, project_paths, resolved_project_id, include_remote_board=bool(enabled))
