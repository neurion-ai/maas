"""Execution Theater read model."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import re

from maas.services.board import fetch_board
from maas.services.codex_mvp import fetch_runs
from maas.services.dashboard import fetch_agent_roster, fetch_overview
from maas.services.delivery import fetch_delivery_overview
from maas.services.git_workspaces import fetch_latest_git_workspace_by_task
from maas.services.projects import resolve_project

logger = logging.getLogger(__name__)

THEATER_ACTIVE_BRANCH_RENDER_LIMIT = 40
THEATER_HISTORY_BRANCH_RENDER_LIMIT = 24

THEATER_LANE_ORDER = [
    "planned",
    "ready",
    "assigned",
    "in_progress",
    "review",
    "blocked",
    "delivery",
    "done_recent",
]
THEATER_LANE_LABELS = {
    "planned": "Planned",
    "ready": "Ready",
    "assigned": "Assigned",
    "in_progress": "In Progress",
    "review": "Review",
    "blocked": "Blocked",
    "delivery": "Delivery",
    "done_recent": "Done",
}


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _lane_for_issue(issue, delivery_item):
    status = issue.get("status")
    if delivery_item is not None and status == "done":
        if delivery_item.get("github_pr") or delivery_item.get("latest_draft"):
            return "delivery"
        return "done_recent"
    if delivery_item is not None and status == "review":
        if delivery_item.get("github_pr") or delivery_item.get("delivery_gate", {}).get("status") == "ready":
            return "delivery"
        return "review"
    if status in {"done", "cancelled"}:
        return "done_recent"
    return status or "planned"


def _sort_weight(issue, lane_key):
    lane_rank = THEATER_LANE_ORDER.index(lane_key) if lane_key in THEATER_LANE_ORDER else len(THEATER_LANE_ORDER)
    priority = int(issue.get("priority") or 0)
    age_hours = issue.get("age_hours") or 0
    return (lane_rank * 1000000) + ((100 - priority) * 1000) - int(age_hours * 10)


def _agent_visual_state(agent, task_id_to_issue, task_id_to_runs):
    task_id = agent.get("current_task_id")
    issue = task_id_to_issue.get(task_id) if task_id else None
    runs = task_id_to_runs.get(task_id, [])
    active_run = next((run for run in runs if run.get("status") == "active"), None)

    if agent.get("status") == "error":
        return "attention"
    if active_run and active_run.get("is_stale"):
        return "attention"
    if issue and issue.get("status") == "blocked":
        return "blocked"
    if issue and issue.get("status") == "review":
        return "review_wait"
    if active_run or issue and issue.get("status") in {"assigned", "in_progress"}:
        return "working"
    return "idle"


def _branch_recency_value(branch):
    timestamp = branch.get("latest_activity_at")
    if not timestamp:
        return ""
    return timestamp


def _looks_like_git_sha(value):
    if not value:
        return False
    return bool(re.fullmatch(r"[0-9a-f]{7,40}", str(value)))


def _branch_lineage_state(branch):
    if branch.get("is_active"):
        return "active"
    if branch.get("pr_id") or branch.get("task_status") in {"done", "review"} or branch.get("worktree_path"):
        return "recent"
    return "historical"


def _agent_current_run(agent_id, task_id_to_runs, task_id):
    if not agent_id:
        return None
    if task_id:
        for run in task_id_to_runs.get(task_id, []):
            if run.get("agent_id") == agent_id:
                return run
    for task_runs in task_id_to_runs.values():
        for run in task_runs:
            if run.get("agent_id") == agent_id:
                return run
    return None


def fetch_theater(connection, project_paths, project_id=None):
    project = resolve_project(connection, project_id, include_archived=False)
    if project is None:
        return {
            "generated_at": _utc_now_iso(),
            "project": None,
            "summary": {
                "issue_count": 0,
                "active_issue_count": 0,
                "agent_count": 0,
                "active_run_count": 0,
                "branch_count": 0,
                "pull_request_count": 0,
                "git_supported": False,
                "branch_data_state": "empty",
                "truth_warnings": 0,
                "reconciled_at": None,
            },
            "issues": [],
            "agents": [],
            "runs": [],
            "branches": [],
            "pull_requests": [],
            "links": {
                "issue_to_agent": [],
                "issue_to_run": [],
                "issue_to_branch": [],
                "branch_to_pr": [],
                "branch_to_base": [],
            },
            "layout": {
                "issue_lanes": [{"key": key, "label": THEATER_LANE_LABELS[key]} for key in THEATER_LANE_ORDER],
                "branch_groups": [],
            },
        }
    project = dict(project)

    scoped_project_id = project["project_id"]
    board = fetch_board(connection, project_id=scoped_project_id)
    overview = fetch_overview(connection, project_id=scoped_project_id, project_paths=project_paths)
    roster = fetch_agent_roster(connection, project_id=scoped_project_id)
    runs_payload = fetch_runs(connection, project_id=scoped_project_id, limit=400)
    git_workspaces = fetch_latest_git_workspace_by_task(connection, project_id=scoped_project_id)
    delivery_payload = fetch_delivery_overview(
        connection,
        project_paths,
        project_id=scoped_project_id,
        limit=max(board["summary"]["total_tasks"], 12),
    )

    board_tasks = [task for column in board["columns"] for task in column["tasks"]]
    issues_by_task = {task["task_id"]: task for task in board_tasks}
    delivery_by_task = {item["task_id"]: item for item in delivery_payload["items"]}
    runs_by_task = {}
    for run in runs_payload["items"]:
        task_id = run.get("task_id")
        if not task_id:
            continue
        runs_by_task.setdefault(task_id, []).append(run)
    for task_runs in runs_by_task.values():
        task_runs.sort(key=lambda run: run.get("started_at") or "", reverse=True)
        task_runs.sort(key=lambda run: 0 if run.get("status") == "active" else 1)

    issues = []
    issue_to_agent = []
    issue_to_run = []
    issue_to_branch = []
    branch_nodes = {}
    pull_requests = {}
    branch_to_pr = []
    branch_to_base = []

    for task in sorted(board_tasks, key=lambda item: (-int(item.get("priority") or 0), item.get("title") or "")):
        task_id = task["task_id"]
        delivery_item = delivery_by_task.get(task_id)
        workspace = git_workspaces.get(task_id) or {}
        linked_runs = runs_by_task.get(task_id, [])
        current_run = linked_runs[0] if linked_runs else None
        lane_key = _lane_for_issue(task, delivery_item)
        issue_row = {
            "task_id": task_id,
            "issue_key": task.get("issue_key"),
            "title": task.get("title"),
            "status": task.get("status"),
            "priority": task.get("priority"),
            "review_state": task.get("review_state"),
            "goal_title": (task.get("goal") or {}).get("title"),
            "agent_id": (task.get("agent") or {}).get("id"),
            "agent_name": (task.get("agent") or {}).get("name"),
            "agent_status": (task.get("agent") or {}).get("status"),
            "current_run_session_id": current_run.get("session_id") if current_run else None,
            "current_run_status": current_run.get("status") if current_run else None,
            "current_run_stale": bool(current_run.get("is_stale")) if current_run else False,
            "delivery_state": delivery_item.get("delivery_gate", {}).get("status") if delivery_item else None,
            "delivery_summary": delivery_item.get("delivery_gate", {}).get("summary") if delivery_item else None,
            "github_pr_state": (delivery_item.get("github_pr") or {}).get("state") if delivery_item else None,
            "github_pr_url": (delivery_item.get("github_pr") or {}).get("url") if delivery_item else None,
            "blocked_reason": task.get("review_state") if task.get("status") == "blocked" else None,
            "age_hours": task.get("age_hours"),
            "review_age_hours": task.get("review_age_hours"),
            "scoped_paths": task.get("scoped_paths") or [],
            "validation_commands": task.get("validation_commands") or [],
            "latest_verification_status": task.get("latest_verification_status"),
            "latest_verification_at": task.get("latest_verification_at"),
            "latest_verification_command": task.get("latest_verification_command"),
            "git_workspace_supported": bool(task.get("git_workspace_supported")),
            "git_workspace_prepared": bool(task.get("git_workspace_prepared")),
            "git_workspace_branch": workspace.get("branch_name") or task.get("git_workspace_branch"),
            "git_workspace_path": workspace.get("worktree_path"),
            "git_workspace_dirty_files": workspace.get("dirty_file_count", task.get("git_workspace_dirty_files", 0)),
            "git_workspace_base_ref": workspace.get("base_ref"),
            "git_workspace_head_commit": workspace.get("head_commit"),
            "git_workspace_updated_at": workspace.get("updated_at"),
            "lane_key": lane_key,
            "sort_weight": _sort_weight(task, lane_key),
        }
        issues.append(issue_row)

        if issue_row["agent_id"]:
            issue_to_agent.append({"issue_id": task_id, "agent_id": issue_row["agent_id"]})
        if issue_row["current_run_session_id"]:
            issue_to_run.append({"issue_id": task_id, "run_id": issue_row["current_run_session_id"]})

        branch_name = issue_row["git_workspace_branch"] or ((delivery_item.get("github_pr") or {}).get("head_branch") if delivery_item else None)
        if branch_name:
            branch_id = branch_name
            raw_base_ref = workspace.get("base_ref")
            named_base_ref = None if _looks_like_git_sha(raw_base_ref) else raw_base_ref
            github_pr = (delivery_item or {}).get("github_pr") or None
            branch_node = branch_nodes.setdefault(
                branch_id,
                {
                    "branch_id": branch_id,
                    "branch_name": branch_name,
                    "task_id": task_id,
                    "issue_key": issue_row["issue_key"],
                    "issue_title": issue_row["title"],
                    "agent_id": issue_row["agent_id"],
                    "agent_name": issue_row["agent_name"],
                    "run_id": issue_row["current_run_session_id"],
                    "run_status": issue_row["current_run_status"],
                    "task_status": issue_row["status"],
                    "worktree_path": workspace.get("worktree_path"),
                    "base_branch": named_base_ref or (github_pr or {}).get("base_branch"),
                    "pr_base_branch": (github_pr or {}).get("base_branch"),
                    "base_ref": raw_base_ref,
                    "head_commit": workspace.get("head_commit"),
                    "dirty_file_count": workspace.get("dirty_file_count", 0),
                    "change_summary": workspace.get("change_summary"),
                    "latest_activity_at": workspace.get("updated_at") or (github_pr or {}).get("synced_at"),
                    "is_active": issue_row["status"] not in {"done", "cancelled"},
                    "pr_id": None,
                    "linked_task_ids": [task_id],
                    "linked_issue_keys": [issue_row["issue_key"]] if issue_row["issue_key"] else [],
                    "depth": 0,
                },
            )
            if task_id not in branch_node.get("linked_task_ids", []):
                branch_node.setdefault("linked_task_ids", []).append(task_id)
            if issue_row["issue_key"] and issue_row["issue_key"] not in branch_node.get("linked_issue_keys", []):
                branch_node.setdefault("linked_issue_keys", []).append(issue_row["issue_key"])
            branch_node["is_active"] = bool(branch_node.get("is_active")) or issue_row["status"] not in {"done", "cancelled"}
            if named_base_ref and not branch_node.get("base_branch"):
                branch_node["base_branch"] = named_base_ref
            if github_pr and github_pr.get("base_branch"):
                branch_node["pr_base_branch"] = github_pr.get("base_branch")
            if raw_base_ref and not branch_node.get("base_ref"):
                branch_node["base_ref"] = raw_base_ref
            if workspace.get("worktree_path") and not branch_node.get("worktree_path"):
                branch_node["worktree_path"] = workspace.get("worktree_path")
            if workspace.get("updated_at") and (
                not branch_node.get("latest_activity_at") or workspace["updated_at"] > branch_node["latest_activity_at"]
            ):
                branch_node["latest_activity_at"] = workspace.get("updated_at")
            issue_to_branch.append({"issue_id": task_id, "branch_id": branch_id})

            if github_pr:
                pr_id = str(github_pr.get("number") or github_pr.get("artifact_id") or branch_name)
                pr_node = pull_requests.setdefault(
                    pr_id,
                    {
                        "pr_id": pr_id,
                        "number": github_pr.get("number"),
                        "url": github_pr.get("url"),
                        "state": github_pr.get("state"),
                        "is_draft": bool(github_pr.get("is_draft")),
                        "title": github_pr.get("title"),
                        "head_branch": github_pr.get("head_branch") or branch_name,
                        "base_branch": github_pr.get("base_branch"),
                        "task_id": task_id,
                        "issue_key": issue_row["issue_key"],
                        "linked_task_ids": [task_id],
                        "linked_issue_keys": [issue_row["issue_key"]] if issue_row["issue_key"] else [],
                    },
                )
                if task_id not in pr_node.get("linked_task_ids", []):
                    pr_node.setdefault("linked_task_ids", []).append(task_id)
                if issue_row["issue_key"] and issue_row["issue_key"] not in pr_node.get("linked_issue_keys", []):
                    pr_node.setdefault("linked_issue_keys", []).append(issue_row["issue_key"])
                branch_node["pr_id"] = pr_id
                branch_to_pr.append({"branch_id": branch_id, "pr_id": pr_id})
            if branch_node.get("base_branch"):
                branch_to_base.append({"branch_id": branch_id, "base_branch": branch_node["base_branch"]})

    agents = []
    for agent in roster["agents"]:
        current_run = _agent_current_run(agent.get("agent_id"), runs_by_task, agent.get("current_task_id"))
        agents.append(
            {
                "agent_id": agent.get("agent_id"),
                "name": agent.get("display_name"),
                "role": agent.get("role"),
                "status": agent.get("status"),
                "current_task_id": agent.get("current_task_id"),
                "current_task_title": agent.get("current_task_title"),
                "current_run_id": current_run.get("session_id") if current_run else None,
                "last_heartbeat_age_seconds": agent.get("heartbeat_age_seconds"),
                "visual_state": _agent_visual_state(agent, issues_by_task, runs_by_task),
            }
        )

    runs = []
    for run in runs_payload["items"]:
        runs.append(
            {
                "run_id": run.get("session_id"),
                "task_id": run.get("task_id"),
                "issue_key": run.get("issue_key"),
                "task_title": run.get("task_title"),
                "agent_id": run.get("agent_id"),
                "agent_name": run.get("agent_name"),
                "status": run.get("status"),
                "is_live": bool(run.get("is_live")),
                "is_stale": bool(run.get("is_stale")),
                "execution_mode": run.get("execution_mode") or run.get("provider_type"),
                "status_message": run.get("status_message"),
                "recommended_action": run.get("recommended_action"),
                "started_at": run.get("started_at"),
                "ended_at": run.get("ended_at"),
                "last_heartbeat_at": run.get("last_heartbeat_at"),
                "heartbeat_age_seconds": run.get("heartbeat_age_seconds"),
            }
        )

    branch_list = list(branch_nodes.values())
    branch_name_to_id = {branch["branch_name"]: branch["branch_id"] for branch in branch_list}
    branch_by_id = {branch["branch_id"]: branch for branch in branch_list}

    for branch in branch_list:
        parent_branch_id = branch_name_to_id.get(branch.get("base_branch")) or branch_name_to_id.get(branch.get("base_ref"))
        branch["parent_branch_id"] = parent_branch_id
        branch["has_tracked_base"] = bool(parent_branch_id)
        branch["lineage_state"] = _branch_lineage_state(branch)
        branch["linked_task_count"] = len(branch.get("linked_task_ids") or [])
        if branch["linked_task_count"] != 1:
            branch["task_id"] = None
            branch["issue_key"] = None
            branch["issue_title"] = None
            branch["agent_id"] = None
            branch["agent_name"] = None
            branch["run_id"] = None
            branch["run_status"] = None
            branch["task_status"] = None

    def _resolve_depth(branch_id, visiting=None):
        branch = branch_by_id[branch_id]
        parent_id = branch.get("parent_branch_id")
        if not parent_id or parent_id == branch_id:
            return 0
        if visiting is None:
            visiting = set()
        if branch_id in visiting or parent_id in visiting:
            return 0
        return 1 + _resolve_depth(parent_id, visiting | {branch_id})

    def _resolve_root_base(branch_id, visiting=None):
        branch = branch_by_id[branch_id]
        parent_id = branch.get("parent_branch_id")
        if not parent_id or parent_id == branch_id:
            return branch.get("base_branch") or "unbased"
        if visiting is None:
            visiting = set()
        if branch_id in visiting or parent_id in visiting:
            return branch.get("base_branch") or "unbased"
        return _resolve_root_base(parent_id, visiting | {branch_id})

    for branch in branch_list:
        branch["depth"] = _resolve_depth(branch["branch_id"])
        branch["lineage_root_base"] = _resolve_root_base(branch["branch_id"])

    branch_list.sort(key=lambda branch: branch.get("branch_name") or "")
    branch_list.sort(key=_branch_recency_value, reverse=True)
    branch_list.sort(key=lambda branch: 0 if branch.get("is_active") else 1)
    for recency_rank, branch in enumerate(branch_list):
        branch["recency_rank"] = recency_rank

    branch_groups = []
    grouped = {}
    active_branch_ids_all = [branch["branch_id"] for branch in branch_list if branch.get("lineage_state") == "active"]
    history_branch_ids_all = [branch["branch_id"] for branch in branch_list if branch.get("lineage_state") != "active"]
    visible_active_branch_ids = set(active_branch_ids_all[:THEATER_ACTIVE_BRANCH_RENDER_LIMIT])
    visible_history_branch_ids = set(history_branch_ids_all[:THEATER_HISTORY_BRANCH_RENDER_LIMIT])
    for branch in branch_list:
        group_base = branch.get("lineage_root_base") or "unbased"
        group = grouped.setdefault(
            group_base,
            {
                "base_branch": group_base,
                "branch_ids": [],
                "root_branch_ids": [],
                "active_branch_ids": [],
                "history_branch_ids": [],
                "visible_active_branch_ids": [],
                "visible_history_branch_ids": [],
            },
        )
        group["branch_ids"].append(branch["branch_id"])
        if branch.get("parent_branch_id") is None:
            group["root_branch_ids"].append(branch["branch_id"])
        if branch.get("lineage_state") == "active":
            group["active_branch_ids"].append(branch["branch_id"])
            if branch["branch_id"] in visible_active_branch_ids:
                group["visible_active_branch_ids"].append(branch["branch_id"])
        else:
            group["history_branch_ids"].append(branch["branch_id"])
            if branch["branch_id"] in visible_history_branch_ids:
                group["visible_history_branch_ids"].append(branch["branch_id"])
    for base_branch, group in grouped.items():
        group["active_count"] = len(group["active_branch_ids"])
        group["history_count"] = len(group["history_branch_ids"])
        group["hidden_active_count"] = group["active_count"] - len(group["visible_active_branch_ids"])
        group["hidden_history_count"] = group["history_count"] - len(group["visible_history_branch_ids"])
        branch_groups.append(group)

    git_supported = bool(delivery_payload.get("git", {}).get("is_git_repo")) or any(
        issue.get("git_workspace_supported") for issue in issues
    )
    branch_data_state = "available" if branch_list else ("unsupported" if not git_supported else "empty")
    degraded_reasons = []
    hidden_active_count = max(0, len(active_branch_ids_all) - len(visible_active_branch_ids))
    hidden_history_count = max(0, len(history_branch_ids_all) - len(visible_history_branch_ids))
    if branch_data_state == "unsupported":
        degraded_reasons.append("branch_lineage_unsupported")

    lane_rank = {key: index for index, key in enumerate(THEATER_LANE_ORDER)}

    if degraded_reasons and set(degraded_reasons) != {"branch_lineage_unsupported"}:
        logger.warning(
            "Theater snapshot degraded for project %s: reasons=%s active_hidden=%s history_hidden=%s",
            scoped_project_id,
            ",".join(degraded_reasons),
            hidden_active_count,
            hidden_history_count,
        )

    pull_request_list = []
    for pull_request in pull_requests.values():
        pull_request["linked_task_count"] = len(pull_request.get("linked_task_ids") or [])
        if pull_request["linked_task_count"] != 1:
            pull_request["task_id"] = None
            pull_request["issue_key"] = None
        pull_request_list.append(pull_request)

    return {
        "generated_at": _utc_now_iso(),
        "project": {
            "project_id": scoped_project_id,
            "name": project["name"],
            "description": project["description"],
            "project_type": project["project_type"],
            "source_root": project.get("source_root"),
            "onboarding_mode": (overview.get("onboarding") or {}).get("mode"),
        },
        "summary": {
            "issue_count": len(issues),
            "active_issue_count": len([issue for issue in issues if issue["status"] not in {"done", "cancelled"}]),
            "agent_count": len(agents),
            "active_run_count": len([run for run in runs if run.get("is_live")]),
            "branch_count": len(branch_list),
            "pull_request_count": len(pull_requests),
            "git_supported": git_supported,
            "branch_data_state": branch_data_state,
            "brownfield_trust": ((overview.get("onboarding") or {}).get("repo_plan_trust") or {}).get("state"),
            "degraded_reasons": degraded_reasons,
            "truth_warnings": ((overview.get("truth") or {}).get("summary") or {}).get("warning_count", 0),
            "reconciled_at": (overview.get("truth") or {}).get("latest_reconciled_at"),
            "lineage_render_limits": {
                "active_cap": THEATER_ACTIVE_BRANCH_RENDER_LIMIT,
                "history_cap": THEATER_HISTORY_BRANCH_RENDER_LIMIT,
                "visible_active_count": len(visible_active_branch_ids),
                "hidden_active_count": hidden_active_count,
                "visible_history_count": len(visible_history_branch_ids),
                "hidden_history_count": hidden_history_count,
                "is_capped": bool(hidden_active_count or hidden_history_count),
            },
        },
        "issues": sorted(
            issues,
            key=lambda issue: (
                lane_rank.get(issue["lane_key"], len(THEATER_LANE_ORDER)),
                -int(issue.get("priority") or 0),
                issue.get("title") or "",
            ),
        ),
        "agents": agents,
        "runs": runs,
        "branches": branch_list,
        "pull_requests": pull_request_list,
        "links": {
            "issue_to_agent": issue_to_agent,
            "issue_to_run": issue_to_run,
            "issue_to_branch": issue_to_branch,
            "branch_to_pr": branch_to_pr,
            "branch_to_base": branch_to_base,
        },
        "layout": {
            "issue_lanes": [{"key": key, "label": THEATER_LANE_LABELS[key]} for key in THEATER_LANE_ORDER],
            "branch_groups": branch_groups,
        },
    }
