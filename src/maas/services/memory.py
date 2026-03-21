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
        entries.sort(key=lambda item: (-item["score"], item.get("promoted_at") or "", item["created_at"]), reverse=False)
        entries = sorted(
            entries,
            key=lambda item: (-item["score"], item.get("promoted_at") or item["created_at"] or ""),
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
    scored.sort(key=lambda item: (-item["score"], item.get("promoted_at") or item["created_at"] or ""))
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
            }
            for entry in memory_entries
        ],
    }
