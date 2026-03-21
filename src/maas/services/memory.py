"""Promoted project memory and retrieval-backed execution context."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
from typing import Iterable

from maas.ids import generate_id
from maas.services.security import ensure_board_action_allowed


MEMORY_PREVIEW_MAX_CHARS = 2000
MEMORY_CONTEXT_MAX_CHARS = 5000
MEMORY_FRESH_AFTER_DAYS = 7
MEMORY_STALE_AFTER_DAYS = 30


def _load_json(value):
    try:
        payload = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _dump_json(payload):
    return json.dumps(payload, sort_keys=True)


def _tokenize(text):
    normalized = re.findall(r"[a-z0-9_./-]+", (text or "").lower())
    return [token for token in normalized if len(token) > 1]


def _score_tokens(query_tokens: Iterable[str], candidate_text: str):
    query = list(query_tokens)
    if not query:
        return 0
    haystack = set(_tokenize(candidate_text))
    return sum(1 for token in query if token in haystack)


def _artifact_preview(path):
    if not path or not os.path.exists(path) or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            content = handle.read(MEMORY_PREVIEW_MAX_CHARS + 1)
    except OSError:
        return None
    truncated = len(content) > MEMORY_PREVIEW_MAX_CHARS
    if truncated:
        content = content[:MEMORY_PREVIEW_MAX_CHARS]
    return {"content": content.strip(), "truncated": truncated}


def _age_days(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
    return max(0, int(delta.total_seconds() // 86400))


def _freshness(age_days):
    if age_days is None:
        return "unknown"
    if age_days >= MEMORY_STALE_AFTER_DAYS:
        return "stale"
    if age_days >= MEMORY_FRESH_AFTER_DAYS:
        return "aging"
    return "fresh"


def _memory_freshness_fields(promoted_at):
    age_days = _age_days(promoted_at)
    freshness = _freshness(age_days)
    return {
        "age_days": age_days,
        "freshness": freshness,
        "stale": freshness == "stale",
    }


def _memory_usage_fields(memory_payload):
    used_count = int(memory_payload.get("used_count") or 0)
    success_count = int(memory_payload.get("success_count") or 0)
    failure_count = int(memory_payload.get("failure_count") or 0)
    attempts = success_count + failure_count
    success_ratio = (success_count / attempts) if attempts else None
    usefulness_score = success_count * 2 - failure_count
    if attempts and success_ratio is not None:
        usefulness_score += success_ratio
    if usefulness_score >= 3:
        usefulness = "high"
    elif usefulness_score >= 1:
        usefulness = "medium"
    elif failure_count and usefulness_score < 0:
        usefulness = "low"
    else:
        usefulness = "unknown"
    return {
        "used_count": used_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "success_ratio": success_ratio,
        "usefulness_score": usefulness_score,
        "usefulness": usefulness,
        "last_used_at": memory_payload.get("last_used_at"),
        "last_run_outcome": memory_payload.get("last_run_outcome"),
    }


def _memory_recency_sort_key(value):
    if not value:
        return 0
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).timestamp()


def _memory_summary_from_preview(preview):
    if not preview or not preview.get("content"):
        return "Promoted artifact with no inline preview available."
    lines = [line.strip() for line in preview["content"].splitlines() if line.strip()]
    if not lines:
        return "Promoted artifact with no inline preview available."
    return lines[0][:180]


def promote_artifact_to_memory(connection, artifact_id, actor_id, title=None, summary=None, tags=None):
    artifact = connection.execute(
        """
        SELECT artifact_id, project_id, task_id, session_id, artifact_type, path, metadata_json, created_at
        FROM artifacts
        WHERE artifact_id = ?
        """,
        (artifact_id,),
    ).fetchone()
    if artifact is None:
        raise ValueError("artifact not found")
    ensure_board_action_allowed(connection, actor_id, artifact["project_id"], "promote_memory", "artifact", artifact_id)

    metadata = _load_json(artifact["metadata_json"])
    preview = _artifact_preview(artifact["path"])
    promoted_at = datetime.now(timezone.utc).isoformat()
    memory_payload = {
        "promoted": True,
        "title": (title or "").strip() or metadata.get("memory", {}).get("title") or os.path.basename(artifact["path"]) or artifact_id,
        "summary": (summary or "").strip() or metadata.get("memory", {}).get("summary") or _memory_summary_from_preview(preview),
        "tags": sorted({tag.strip() for tag in (tags or metadata.get("memory", {}).get("tags") or []) if isinstance(tag, str) and tag.strip()}),
        "promoted_at": promoted_at,
        "promoted_by": actor_id,
        "artifact_type": artifact["artifact_type"],
        "task_id": artifact["task_id"],
        "session_id": artifact["session_id"],
        "used_count": int((metadata.get("memory") or {}).get("used_count") or 0),
        "success_count": int((metadata.get("memory") or {}).get("success_count") or 0),
        "failure_count": int((metadata.get("memory") or {}).get("failure_count") or 0),
        "last_used_at": (metadata.get("memory") or {}).get("last_used_at"),
        "last_run_outcome": (metadata.get("memory") or {}).get("last_run_outcome"),
    }
    metadata["memory"] = memory_payload
    connection.execute(
        "UPDATE artifacts SET metadata_json = ? WHERE artifact_id = ?",
        (_dump_json(metadata), artifact_id),
    )
    connection.execute(
        """
        INSERT INTO audit_trail (
            audit_id, project_id, actor_id, action_type, resource_type, resource_id, detail_json
        ) VALUES (?, ?, ?, 'promote_memory', 'artifact', ?, ?)
        """,
        (
            generate_id("audit"),
            artifact["project_id"],
            actor_id,
            artifact_id,
            json.dumps(memory_payload),
        ),
    )
    connection.execute(
        """
        INSERT INTO activity_log (
            activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
        ) VALUES (?, ?, ?, ?, 'memory_promoted', 'memory', ?, ?, 'info')
        """,
        (
            generate_id("act"),
            artifact["project_id"],
            actor_id,
            artifact["task_id"],
            "Promoted an artifact into reusable project memory.",
            json.dumps({"artifact_id": artifact_id, "memory": memory_payload}),
        ),
    )
    connection.commit()
    return {
        "artifact_id": artifact_id,
        "project_id": artifact["project_id"],
        "memory": memory_payload,
        "preview": preview,
    }


def _update_memory_usage(connection, artifact_ids, usage_update):
    resolved_ids = [artifact_id for artifact_id in (artifact_ids or []) if artifact_id]
    if not resolved_ids:
        return 0
    updated = 0
    for artifact_id in resolved_ids:
        row = connection.execute(
            """
            SELECT metadata_json
            FROM artifacts
            WHERE artifact_id = ?
            """,
            (artifact_id,),
        ).fetchone()
        if row is None:
            continue
        metadata = _load_json(row["metadata_json"])
        memory = metadata.get("memory") or {}
        if not memory.get("promoted"):
            continue
        merged = dict(memory)
        merged.update({key: value for key, value in usage_update.items() if value is not None})
        metadata["memory"] = merged
        connection.execute(
            "UPDATE artifacts SET metadata_json = ? WHERE artifact_id = ?",
            (_dump_json(metadata), artifact_id),
        )
        updated += 1
    return updated


def record_memory_injection(connection, artifact_ids):
    now = datetime.now(timezone.utc).isoformat()
    resolved_ids = [artifact_id for artifact_id in (artifact_ids or []) if artifact_id]
    if not resolved_ids:
        return 0
    updated = 0
    for artifact_id in resolved_ids:
        row = connection.execute(
            """
            SELECT metadata_json
            FROM artifacts
            WHERE artifact_id = ?
            """,
            (artifact_id,),
        ).fetchone()
        if row is None:
            continue
        metadata = _load_json(row["metadata_json"])
        memory = metadata.get("memory") or {}
        if not memory.get("promoted"):
            continue
        memory["used_count"] = int(memory.get("used_count") or 0) + 1
        memory["last_used_at"] = now
        metadata["memory"] = memory
        connection.execute(
            "UPDATE artifacts SET metadata_json = ? WHERE artifact_id = ?",
            (_dump_json(metadata), artifact_id),
        )
        updated += 1
    return updated


def record_memory_outcome(connection, artifact_ids, outcome):
    now = datetime.now(timezone.utc).isoformat()
    resolved_ids = [artifact_id for artifact_id in (artifact_ids or []) if artifact_id]
    if not resolved_ids:
        return 0
    updated = 0
    for artifact_id in resolved_ids:
        row = connection.execute(
            """
            SELECT metadata_json
            FROM artifacts
            WHERE artifact_id = ?
            """,
            (artifact_id,),
        ).fetchone()
        if row is None:
            continue
        metadata = _load_json(row["metadata_json"])
        memory = metadata.get("memory") or {}
        if not memory.get("promoted"):
            continue
        if outcome == "completed":
            memory["success_count"] = int(memory.get("success_count") or 0) + 1
        else:
            memory["failure_count"] = int(memory.get("failure_count") or 0) + 1
        memory["last_run_outcome"] = outcome
        memory["last_used_at"] = now
        metadata["memory"] = memory
        connection.execute(
            "UPDATE artifacts SET metadata_json = ? WHERE artifact_id = ?",
            (_dump_json(metadata), artifact_id),
        )
        updated += 1
    return updated


def fetch_project_memory(connection, project_id, limit=40, search=None):
    rows = connection.execute(
        """
        SELECT artifact_id, project_id, task_id, session_id, artifact_type, path, metadata_json, created_at
        FROM artifacts
        WHERE project_id = ?
        ORDER BY created_at DESC, artifact_id DESC
        """,
        (project_id,),
    ).fetchall()
    entries = []
    query_tokens = _tokenize(search or "")
    for row in rows:
        metadata = _load_json(row["metadata_json"])
        memory = metadata.get("memory") or {}
        if not memory.get("promoted"):
            continue
        entry = {
            "artifact_id": row["artifact_id"],
            "task_id": row["task_id"],
            "session_id": row["session_id"],
            "artifact_type": row["artifact_type"],
            "path": row["path"],
            "created_at": row["created_at"],
            "title": memory.get("title") or os.path.basename(row["path"]) or row["artifact_id"],
            "summary": memory.get("summary") or "",
            "tags": memory.get("tags") or [],
            "promoted_at": memory.get("promoted_at"),
            "promoted_by": memory.get("promoted_by"),
            "preview": _artifact_preview(row["path"]),
            **_memory_freshness_fields(memory.get("promoted_at")),
            **_memory_usage_fields(memory),
        }
        if query_tokens:
            candidate = " ".join([entry["title"], entry["summary"], " ".join(entry["tags"] or [])])
            score = _score_tokens(query_tokens, candidate)
            if score <= 0:
                continue
            entry["score"] = score
        else:
            entry["score"] = 0
        entries.append(entry)
    if query_tokens:
        entries = sorted(
            entries,
            key=lambda item: (
                -item["score"],
                -float(item.get("usefulness_score") or 0),
                item.get("freshness") == "stale",
                -(item.get("success_ratio") or 0),
                -_memory_recency_sort_key(item.get("promoted_at") or item["created_at"]),
            ),
        )
    else:
        entries = sorted(
            entries,
            key=lambda item: (
                -float(item.get("usefulness_score") or 0),
                item.get("freshness") == "stale",
                -_memory_recency_sort_key(item.get("promoted_at") or item["created_at"]),
            ),
        )
    return entries[:limit]


def retrieve_relevant_memory(connection, project_id, task_title, task_description=None, goal_title=None, limit=3):
    query_text = " ".join(filter(None, [task_title, task_description, goal_title]))
    query_tokens = _tokenize(query_text)
    if not query_tokens:
        return []
    candidates = fetch_project_memory(connection, project_id, limit=200)
    scored = []
    for candidate in candidates:
        candidate_text = " ".join(
            [
                candidate.get("title") or "",
                candidate.get("summary") or "",
                " ".join(candidate.get("tags") or []),
                candidate.get("preview", {}).get("content") or "",
            ]
        )
        score = _score_tokens(query_tokens, candidate_text)
        if score <= 0:
            continue
        candidate_copy = dict(candidate)
        candidate_copy["score"] = score
        scored.append(candidate_copy)
    scored.sort(
        key=lambda item: (
            item["score"],
            float(item.get("usefulness_score") or 0),
            item.get("success_ratio") or 0,
            -(item.get("age_days") or 0),
            item.get("promoted_at") or item["created_at"] or "",
        ),
        reverse=True,
    )
    return scored[:limit]


def build_task_prompt(connection, task_id):
    row = connection.execute(
        """
        SELECT tasks.project_id, tasks.title, tasks.description, goals.title AS goal_title
        FROM tasks
        LEFT JOIN goals ON goals.goal_id = tasks.goal_id
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if row is None:
        return {
            "prompt": "Complete task {0} and summarize the result.".format(task_id),
            "memory_context": [],
        }
    description = (row["description"] or "").strip()
    base_prompt = "Task: {0}".format(row["title"])
    if description:
        base_prompt += "\n\nContext:\n{0}".format(description)

    memory_entries = retrieve_relevant_memory(
        connection,
        row["project_id"],
        row["title"],
        task_description=row["description"],
        goal_title=row["goal_title"],
        limit=3,
    )
    if memory_entries:
        memory_lines = []
        current_length = 0
        for entry in memory_entries:
            snippet = (entry.get("preview", {}) or {}).get("content") or entry.get("summary") or ""
            snippet = snippet.strip()
            if len(snippet) > 800:
                snippet = snippet[:800].rstrip() + "…"
            block = "- {title}: {summary}".format(
                title=entry.get("title") or entry["artifact_id"],
                summary=snippet or entry.get("summary") or "No summary available.",
            )
            if current_length + len(block) > MEMORY_CONTEXT_MAX_CHARS:
                break
            memory_lines.append(block)
            current_length += len(block)
        if memory_lines:
            base_prompt += "\n\nRelevant project memory:\n{0}".format("\n".join(memory_lines))
    base_prompt += "\n\nReturn a concise completion summary."
    return {
        "prompt": base_prompt,
        "memory_context": [
            {
                "artifact_id": entry["artifact_id"],
                "task_id": entry.get("task_id"),
                "title": entry.get("title"),
                "summary": entry.get("summary"),
                "tags": entry.get("tags") or [],
                "score": entry.get("score", 0),
                "promoted_at": entry.get("promoted_at"),
                "age_days": entry.get("age_days"),
                "freshness": entry.get("freshness"),
                "stale": entry.get("stale"),
                "used_count": entry.get("used_count"),
                "success_count": entry.get("success_count"),
                "failure_count": entry.get("failure_count"),
                "success_ratio": entry.get("success_ratio"),
                "usefulness_score": entry.get("usefulness_score"),
                "usefulness": entry.get("usefulness"),
            }
            for entry in memory_entries
        ],
    }
