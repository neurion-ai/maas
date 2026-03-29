"""Execution Theater read model."""

from __future__ import annotations

from datetime import datetime, timezone

from maas.services.board import fetch_board
from maas.services.codex_mvp import fetch_runs
from maas.services.dashboard import fetch_agent_roster, fetch_overview
from maas.services.delivery import fetch_delivery_overview
from maas.services.git_workspaces import fetch_latest_git_workspace_by_task
from maas.services.projects import resolve_project


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
        return "delivery"
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
    overview = fetch_overview(connection, project_id=scoped_project_id)
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
                    "base_branch": workspace.get("base_ref") or ((delivery_item.get("github_pr") or {}).get("base_branch") if delivery_item else None),
                    "head_commit": workspace.get("head_commit"),
                    "dirty_file_count": workspace.get("dirty_file_count", 0),
                    "change_summary": workspace.get("change_summary"),
                    "latest_activity_at": workspace.get("updated_at") or ((delivery_item.get("github_pr") or {}).get("synced_at") if delivery_item else None),
                    "is_active": issue_row["status"] not in {"done", "cancelled"},
                    "pr_id": None,
                    "depth": 0,
                },
            )
            if workspace.get("worktree_path") and not branch_node.get("worktree_path"):
                branch_node["worktree_path"] = workspace.get("worktree_path")
            if workspace.get("updated_at") and (
                not branch_node.get("latest_activity_at") or workspace["updated_at"] > branch_node["latest_activity_at"]
            ):
                branch_node["latest_activity_at"] = workspace.get("updated_at")
            issue_to_branch.append({"issue_id": task_id, "branch_id": branch_id})

            github_pr = (delivery_item or {}).get("github_pr") or None
            if github_pr:
                pr_id = str(github_pr.get("number") or github_pr.get("artifact_id") or branch_name)
                pull_requests[pr_id] = {
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
                }
                branch_node["pr_id"] = pr_id
                branch_to_pr.append({"branch_id": branch_id, "pr_id": pr_id})
            if branch_node.get("base_branch"):
                branch_to_base.append({"branch_id": branch_id, "base_branch": branch_node["base_branch"]})

    agents = []
    for agent in roster["agents"]:
        agents.append(
            {
                "agent_id": agent.get("agent_id"),
                "name": agent.get("display_name"),
                "role": agent.get("role"),
                "status": agent.get("status"),
                "current_task_id": agent.get("current_task_id"),
                "current_task_title": agent.get("current_task_title"),
                "current_run_id": runs_by_task.get(agent.get("current_task_id"), [{}])[0].get("session_id")
                if agent.get("current_task_id")
                else None,
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
    branch_list.sort(key=lambda branch: branch.get("branch_name") or "")
    branch_list.sort(key=_branch_recency_value, reverse=True)
    branch_list.sort(key=lambda branch: 0 if branch.get("is_active") else 1)

    branch_groups = []
    grouped = {}
    for branch in branch_list:
        base_branch = branch.get("base_branch") or "unbased"
        grouped.setdefault(base_branch, []).append(branch["branch_id"])
    for base_branch, branch_ids in grouped.items():
        branch_groups.append({"base_branch": base_branch, "branch_ids": branch_ids})

    git_supported = bool(delivery_payload.get("git", {}).get("is_git_repo")) or any(
        issue.get("git_workspace_supported") for issue in issues
    )
    branch_data_state = "available" if branch_list else ("unsupported" if not git_supported else "empty")

    lane_rank = {key: index for index, key in enumerate(THEATER_LANE_ORDER)}

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
        "pull_requests": list(pull_requests.values()),
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
