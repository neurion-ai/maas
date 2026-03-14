"""Minimal task scheduling helpers."""

import json


def resolve_ready_tasks(connection):
    rows = connection.execute(
        """
        SELECT task_id, title, priority
        FROM tasks
        WHERE status IN ('planned', 'assigned')
          AND task_id NOT IN (
              SELECT target_task_id
              FROM task_dependencies td
              JOIN tasks blockers ON blockers.task_id = td.source_task_id
              WHERE td.dependency_type = 'blocks'
                AND blockers.status != 'done'
          )
        ORDER BY priority DESC, created_at ASC
        """
    ).fetchall()
    return [{"task_id": row["task_id"], "title": row["title"], "priority": row["priority"]} for row in rows]


def evaluate_acceptance(task_row, project_paths):
    criteria = json.loads(task_row["acceptance_criteria_json"] or "[]")
    results = []
    for criterion in criteria:
        criterion_type = criterion.get("type")
        if criterion_type == "artifact_exists":
            results.append({"type": criterion_type, "passed": True, "reason": "Placeholder evaluation in scaffold."})
        elif criterion_type == "metric":
            results.append({"type": criterion_type, "passed": False, "reason": "Metric evaluators are not wired yet."})
        elif criterion_type == "db_query":
            results.append({"type": criterion_type, "passed": False, "reason": "Query evaluators are not wired yet."})
        elif criterion_type == "test_passes":
            results.append({"type": criterion_type, "passed": False, "reason": "Test command evaluator is not wired yet."})
        else:
            results.append({"type": criterion_type, "passed": False, "reason": "Unknown criterion type."})
    return results

