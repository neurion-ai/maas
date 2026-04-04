"""GitHub Project truth synchronization for the MAAS execution board."""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from maas.services.projects import resolve_project


DEFAULT_GITHUB_REPO = "neurion-ai/maas"
DEFAULT_GITHUB_ORG = "neurion-ai"
DEFAULT_GITHUB_PROJECT_NUMBER = 4
BOARD_SYNC_COOLDOWN_SECONDS = 300
SERVICE_REPO_ROOT = str(Path(__file__).resolve().parents[3])


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


def _remote_repo_name(source_root):
    if not source_root or not os.path.isdir(source_root):
        return None
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=source_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    value = (result.stdout or "").strip()
    if not value:
        return None
    normalized = value.rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    ssh_match = re.search(r"[:/]([^/:]+/[^/:]+)$", normalized)
    return ssh_match.group(1) if ssh_match else None


def _is_service_repo_root(source_root):
    if not source_root or not os.path.isdir(source_root):
        return False
    try:
        return os.path.samefile(source_root, SERVICE_REPO_ROOT)
    except OSError:
        return False


def _activity_timestamp(connection, project_id, action):
    row = connection.execute(
        """
        SELECT created_at
        FROM activity_log
        WHERE project_id = ?
          AND action = ?
        ORDER BY created_at DESC, rowid DESC
        LIMIT 1
        """,
        (project_id, action),
    ).fetchone()
    return row["created_at"] if row else None


def _gh_graphql(query):
    result = subprocess.run(
        ["gh", "api", "graphql", "-f", "query={0}".format(query)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "GitHub GraphQL query failed").strip())
    payload = json.loads(result.stdout or "{}")
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"]))
    return payload.get("data") or {}


def _project_snapshot(repo_full_name=DEFAULT_GITHUB_REPO, project_number=DEFAULT_GITHUB_PROJECT_NUMBER):
    owner, repo = repo_full_name.split("/", 1)
    query = """
    query {{
      organization(login: "{owner}") {{
        projectV2(number: {project_number}) {{
          id
          fields(first: 20) {{
            nodes {{
              ... on ProjectV2SingleSelectField {{
                id
                name
                options {{
                  id
                  name
                }}
              }}
            }}
          }}
          items(first: 100) {{
            nodes {{
              id
              fieldValues(first: 20) {{
                nodes {{
                  ... on ProjectV2ItemFieldSingleSelectValue {{
                    name
                    optionId
                    field {{
                      ... on ProjectV2FieldCommon {{
                        name
                      }}
                    }}
                  }}
                }}
              }}
              content {{
                ... on Issue {{
                  number
                  state
                  repository {{
                    nameWithOwner
                  }}
                  closedByPullRequestsReferences(first: 10) {{
                    nodes {{
                      number
                      state
                      mergedAt
                    }}
                  }}
                }}
              }}
            }}
          }}
        }}
      }}
      repository(owner: "{owner}", name: "{repo}") {{
        pullRequests(first: 100, states: OPEN, orderBy: {{field: UPDATED_AT, direction: DESC}}) {{
          nodes {{
            number
            closingIssuesReferences(first: 20) {{
              nodes {{
                number
              }}
            }}
          }}
        }}
      }}
    }}
    """.format(owner=owner, repo=repo, project_number=int(project_number))
    data = _gh_graphql(query)
    project = ((data.get("organization") or {}).get("projectV2")) or {}
    open_pulls = ((data.get("repository") or {}).get("pullRequests") or {}).get("nodes") or []
    open_pr_numbers_by_issue = {}
    for pull_request in open_pulls:
        for issue in (pull_request.get("closingIssuesReferences") or {}).get("nodes") or []:
            open_pr_numbers_by_issue.setdefault(issue.get("number"), []).append(pull_request.get("number"))
    project_items = ((project.get("items") or {}).get("nodes") or [])
    return project, open_pr_numbers_by_issue, {
        "items_truncated": len(project_items) >= 100,
        "open_prs_truncated": len(open_pulls) >= 100,
    }


def _field_lookup(project):
    lookup = {}
    for field in (project.get("fields") or {}).get("nodes") or []:
        if not isinstance(field, dict):
            continue
        lookup[field.get("name")] = {
            "id": field.get("id"),
            "options": {option.get("name"): option.get("id") for option in field.get("options") or [] if option.get("name")},
        }
    return lookup


def _item_field_values(item):
    values = {}
    for node in (item.get("fieldValues") or {}).get("nodes") or []:
        field_name = ((node.get("field") or {}).get("name")) if isinstance(node, dict) else None
        if field_name:
            values[field_name] = node.get("name")
    return values


def _desired_fields(issue, current_fields):
    desired = {}
    state = issue.get("state")
    merged_prs = [
        pr
        for pr in (issue.get("closedByPullRequestsReferences") or {}).get("nodes") or []
        if pr.get("mergedAt")
    ]
    if state == "CLOSED":
        desired["Status"] = "Done"
        if merged_prs:
            desired["PR"] = "Merged"
            desired["Code Review"] = "Passed"
    changes = {
        field_name: option_name
        for field_name, option_name in desired.items()
        if current_fields.get(field_name) != option_name
    }
    return changes


def inspect_github_project_truth(
    connection,
    project_id,
    *,
    repo_full_name=DEFAULT_GITHUB_REPO,
    project_number=DEFAULT_GITHUB_PROJECT_NUMBER,
):
    project = resolve_project(connection, project_id, include_archived=True)
    source_root = project["source_root"] if project else None
    remote_repo = _remote_repo_name(source_root)
    if remote_repo != repo_full_name or not _is_service_repo_root(source_root):
        return {
            "enabled": False,
            "skipped": True,
            "reason": "repo_not_managed_by_execution_board",
            "repo_full_name": repo_full_name,
            "project_number": project_number,
            "drift_count": 0,
            "updated_count": 0,
            "updates": [],
            "warnings": [],
            "synced_at": None,
        }
    try:
        project_snapshot, _open_pr_numbers_by_issue, snapshot_meta = _project_snapshot(
            repo_full_name=repo_full_name,
            project_number=project_number,
        )
    except (RuntimeError, OSError, ValueError) as exc:
        return {
            "enabled": True,
            "skipped": False,
            "reason": "github_query_failed",
            "repo_full_name": repo_full_name,
            "project_number": project_number,
            "drift_count": 0,
            "updated_count": 0,
            "updates": [],
            "warnings": [{"detail": str(exc)}],
            "synced_at": None,
        }
    warnings = []
    if snapshot_meta.get("items_truncated") or snapshot_meta.get("open_prs_truncated"):
        warnings.append(
            {
                "detail": "GitHub project sync snapshot is truncated and was skipped to avoid partial truth updates.",
            }
        )
        return {
            "enabled": True,
            "skipped": False,
            "reason": "github_snapshot_truncated",
            "repo_full_name": repo_full_name,
            "project_number": project_number,
            "project_id": project_snapshot.get("id"),
            "field_lookup": _field_lookup(project_snapshot),
            "drift_count": 0,
            "updated_count": 0,
            "updates": [],
            "warnings": warnings,
            "synced_at": None,
        }
    field_lookup = _field_lookup(project_snapshot)
    drift = []
    for item in (project_snapshot.get("items") or {}).get("nodes") or []:
        issue = item.get("content") or {}
        if issue.get("repository", {}).get("nameWithOwner") != repo_full_name:
            continue
        current_fields = _item_field_values(item)
        desired = _desired_fields(issue, current_fields)
        if not desired:
            continue
        drift.append(
            {
                "item_id": item.get("id"),
                "issue_number": issue.get("number"),
                "desired": desired,
                "current": current_fields,
            }
        )
    return {
        "enabled": True,
        "skipped": False,
        "reason": None,
        "repo_full_name": repo_full_name,
        "project_number": project_number,
        "project_id": project_snapshot.get("id"),
        "field_lookup": field_lookup,
        "drift_count": len(drift),
        "updated_count": 0,
        "updates": drift,
        "warnings": warnings,
        "synced_at": None,
    }


def sync_github_project_truth(
    connection,
    project_id,
    *,
    repo_full_name=DEFAULT_GITHUB_REPO,
    project_number=DEFAULT_GITHUB_PROJECT_NUMBER,
):
    inspection = inspect_github_project_truth(
        connection,
        project_id,
        repo_full_name=repo_full_name,
        project_number=project_number,
    )
    if inspection.get("skipped") or inspection.get("warnings"):
        return inspection
    project_id_value = inspection.get("project_id")
    field_lookup = inspection.get("field_lookup") or {}
    updates = []
    warnings = []
    for item in inspection.get("updates") or []:
        item_id = item.get("item_id")
        issue_number = item.get("issue_number")
        for field_name, option_name in (item.get("desired") or {}).items():
            field = field_lookup.get(field_name) or {}
            field_id = field.get("id")
            option_id = (field.get("options") or {}).get(option_name)
            if not field_id or not option_id:
                warnings.append({"detail": "Missing field mapping for {0} -> {1}".format(field_name, option_name)})
                continue
            mutation = """
            mutation {{
              updateProjectV2ItemFieldValue(
                input: {{
                  projectId: "{project_id}"
                  itemId: "{item_id}"
                  fieldId: "{field_id}"
                  value: {{ singleSelectOptionId: "{option_id}" }}
                }}
              ) {{
                projectV2Item {{
                  id
                }}
              }}
            }}
            """.format(project_id=project_id_value, item_id=item_id, field_id=field_id, option_id=option_id)
            try:
                _gh_graphql(mutation)
            except RuntimeError as exc:
                warnings.append({"detail": str(exc), "issue_number": issue_number, "field_name": field_name})
                continue
            updates.append(
                {
                    "issue_number": issue_number,
                    "field_name": field_name,
                    "from": (item.get("current") or {}).get(field_name),
                    "to": option_name,
                }
            )
    return {
        **inspection,
        "updated_count": len(updates),
        "updates": updates,
        "warnings": warnings,
        "synced_at": _utc_now_iso() if not warnings else None,
    }


def maybe_sync_github_project_truth(
    connection,
    project_id,
    *,
    repo_full_name=DEFAULT_GITHUB_REPO,
    project_number=DEFAULT_GITHUB_PROJECT_NUMBER,
    cooldown_seconds=BOARD_SYNC_COOLDOWN_SECONDS,
):
    latest_sync_at = _activity_timestamp(connection, project_id, "github_project_truth_synced")
    latest_sync = _parse_timestamp(latest_sync_at)
    if latest_sync and (_utc_now() - latest_sync).total_seconds() < max(0, int(cooldown_seconds or 0)):
        return {
            "enabled": True,
            "skipped": True,
            "reason": "cooldown_active",
            "repo_full_name": repo_full_name,
            "project_number": project_number,
            "drift_count": 0,
            "updated_count": 0,
            "updates": [],
            "warnings": [],
            "synced_at": latest_sync_at,
        }
    return sync_github_project_truth(
        connection,
        project_id,
        repo_full_name=repo_full_name,
        project_number=project_number,
    )
