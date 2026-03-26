import json
import os
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.ids import generate_id
from maas.services.bootstrap import bootstrap_project
from maas.services.delivery import _git_repo_snapshot, fetch_delivery_overview
from maas.services.environment_doctor import _git_status, fetch_environment_doctor
from maas.services.goal_planning import create_goal, synthesize_goal_issues, _goal_issue_specs
from maas.services.memory import retrieve_relevant_memory

class CodexMvpApiTest(unittest.TestCase):
    def test_issue_index_groups_review_and_blocked_work_with_batch_review_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Codex Issue Index Test", description="codex issue index", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                tasks = connection.execute(
                    """
                    SELECT task_id, project_id, assigned_agent_id, title
                    FROM tasks
                    ORDER BY created_at ASC
                    LIMIT 4
                    """
                ).fetchall()
                review_task = tasks[0]
                high_priority_review = tasks[1]
                blocked_failure = tasks[2]
                blocked_dependency = tasks[3]

                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'review', priority = 60, review_state = 'review_requested'
                    WHERE task_id = ?
                    """,
                    (review_task["task_id"],),
                )
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'review', priority = 92, review_state = 'review_requested'
                    WHERE task_id = ?
                    """,
                    (high_priority_review["task_id"],),
                )
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'blocked', review_state = 'timed_out'
                    WHERE task_id = ?
                    """,
                    (blocked_failure["task_id"],),
                )
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'blocked', review_state = 'awaiting_dependency'
                    WHERE task_id = ?
                    """,
                    (blocked_dependency["task_id"],),
                )
                connection.execute(
                    """
                    INSERT INTO verification_runs (
                        verification_run_id, project_id, task_id, command, status, exit_code, output_excerpt,
                        artifact_id, actor_id, started_at, finished_at
                    ) VALUES (
                        ?, ?, ?, 'pytest tests/test_review.py', 'passed', 0, '1 passed',
                        NULL, 'agent_reviewer', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """,
                    (generate_id("vrf"), review_task["project_id"], review_task["task_id"]),
                )
                connection.execute(
                    """
                    INSERT INTO failure_log (
                        failure_id, project_id, task_id, session_id, agent_id, failure_type, summary, detail_json
                    ) VALUES (?, ?, ?, NULL, ?, 'session_timed_out', 'Codex run timed out', '{}')
                    """,
                    (generate_id("fail"), blocked_failure["project_id"], blocked_failure["task_id"], blocked_failure["assigned_agent_id"]),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.get("/api/issues/index")
            self.assertEqual(response.status_code, 200)
            payload = response.json()

            self.assertGreaterEqual(payload["summary"]["review"], 2)
            self.assertGreaterEqual(payload["summary"]["blocked_failures"], 1)
            self.assertGreaterEqual(payload["summary"]["blocked_dependencies"], 1)
            self.assertEqual(payload["summary"]["batch_review_eligible"], 1)
            self.assertEqual(payload["queue"]["review"]["batch_review"]["eligible_task_ids"], [review_task["task_id"]])
            self.assertEqual(len(payload["queue"]["review"]["batch_review"]["packets"]), 1)
            self.assertTrue(
                payload["queue"]["review"]["batch_review"]["packets"][0]["packet_key"].startswith("low_risk_verified_auto:")
            )
            self.assertEqual(
                payload["queue"]["review"]["batch_review"]["packets"][0]["eligible_task_ids"],
                [review_task["task_id"]],
            )

            review_items = {item["task_id"]: item for item in payload["queue"]["review"]["items"]}
            self.assertTrue(review_items[review_task["task_id"]]["batch_review_eligible"])
            self.assertEqual(review_items[review_task["task_id"]]["review_eligibility"]["decision_mode"], "auto_approve")
            self.assertTrue(review_items[review_task["task_id"]]["review_eligibility"]["auto_approve_eligible"])
            self.assertIsNone(review_items[review_task["task_id"]]["review_eligibility"]["why_not_auto_approved"])
            self.assertFalse(review_items[high_priority_review["task_id"]]["batch_review_eligible"])
            self.assertEqual(
                review_items[high_priority_review["task_id"]]["batch_review_reason"],
                "Priority is above the low-risk review threshold for batch or automatic approval.",
            )
            self.assertEqual(
                review_items[high_priority_review["task_id"]]["review_eligibility"]["why_not_auto_approved"],
                "Priority is above the low-risk review threshold for batch or automatic approval.",
            )

            failure_task_ids = {item["task_id"] for item in payload["queue"]["blocked_failures"]["items"]}
            dependency_task_ids = {item["task_id"] for item in payload["queue"]["blocked_dependencies"]["items"]}
            self.assertIn(blocked_failure["task_id"], failure_task_ids)
            self.assertIn(blocked_dependency["task_id"], dependency_task_ids)

            detail_response = client.get(f"/api/issues/{review_task['task_id']}")
            self.assertEqual(detail_response.status_code, 200)
            detail_payload = detail_response.json()
            self.assertEqual(detail_payload["review_decision"]["status"], "low_risk_review")
            self.assertTrue(detail_payload["review_decision"]["batch_review_eligible"])
            self.assertEqual(detail_payload["review_decision"]["decision_mode"], "auto_approve")
            self.assertTrue(
                detail_payload["review_decision"]["grouped_review_packet"]["packet_key"].startswith("low_risk_verified_auto:")
            )
            self.assertEqual(detail_payload["recovery_playbook"]["title"], "Low-risk review should auto-advance")

    def test_batch_review_endpoint_approves_low_risk_items(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Codex Batch Review Test", description="codex batch review", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task = connection.execute(
                    """
                    SELECT task_id, project_id
                    FROM tasks
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'review', priority = 50, review_state = 'review_requested'
                    WHERE task_id = ?
                    """,
                    (task["task_id"],),
                )
                connection.execute(
                    """
                    INSERT INTO verification_runs (
                        verification_run_id, project_id, task_id, command, status, exit_code, output_excerpt,
                        artifact_id, actor_id, started_at, finished_at
                    ) VALUES (
                        ?, ?, ?, 'pytest tests/test_batch.py', 'passed', 0, '1 passed',
                        NULL, 'agent_reviewer', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """,
                    (generate_id("vrf"), task["project_id"], task["task_id"]),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.post(
                "/api/issues/actions/batch-review",
                json={
                    "actor_id": "agent_allocator",
                    "decision": "approve",
                    "task_ids": [task["task_id"]],
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["decision"], "approve")
            self.assertTrue(response.json()["review_packets"][0]["packet_key"].startswith("low_risk_verified_auto:"))
            self.assertEqual(response.json()["review_packets"][0]["eligible_task_ids"], [task["task_id"]])

            connection = connect(paths)
            try:
                task_row = connection.execute(
                    "SELECT status, review_state FROM tasks WHERE task_id = ?",
                    (task["task_id"],),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(task_row["status"], "done")
            self.assertEqual(task_row["review_state"], "approved")

    def test_batch_review_endpoint_rejects_manual_only_items(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Codex Manual Review Test", description="codex manual review", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task = connection.execute(
                    """
                    SELECT task_id
                    FROM tasks
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'review', priority = 95, review_state = 'review_requested'
                    WHERE task_id = ?
                    """,
                    (task["task_id"],),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.post(
                "/api/issues/actions/batch-review",
                json={
                    "actor_id": "agent_allocator",
                    "decision": "approve",
                    "task_ids": [task["task_id"]],
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("low-risk review threshold", response.json()["detail"])

            connection = connect(paths)
            try:
                task_row = connection.execute(
                    "SELECT status, review_state FROM tasks WHERE task_id = ?",
                    (task["task_id"],),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(task_row["status"], "review")
            self.assertEqual(task_row["review_state"], "review_requested")

    def test_batch_review_requires_tasks_from_the_same_packet(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Codex Mixed Packet Test", description="codex mixed packet", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                tasks = connection.execute(
                    """
                    SELECT task_id, project_id, title
                    FROM tasks
                    ORDER BY created_at ASC
                    LIMIT 2
                    """
                ).fetchall()
                first_task, second_task = tasks
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'review', priority = 50, review_state = 'review_requested'
                    WHERE task_id IN (?, ?)
                    """,
                    (first_task["task_id"], second_task["task_id"]),
                )
                connection.execute(
                    "UPDATE tasks SET goal_id = NULL WHERE task_id = ?",
                    (second_task["task_id"],),
                )
                for task in tasks:
                    connection.execute(
                        """
                        INSERT INTO verification_runs (
                            verification_run_id, project_id, task_id, command, status, exit_code, output_excerpt,
                            artifact_id, actor_id, started_at, finished_at
                        ) VALUES (
                            ?, ?, ?, 'pytest tests/test_batch.py', 'passed', 0, '1 passed',
                            NULL, 'agent_reviewer', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                        )
                        """,
                        (generate_id("vrf"), task["project_id"], task["task_id"]),
                    )
                connection.commit()
            finally:
                connection.close()

            with TestClient(create_app(tmpdir)) as client:
                response = client.post(
                    "/api/issues/actions/batch-review",
                    json={
                        "actor_id": "agent_allocator",
                        "decision": "approve",
                        "task_ids": [first_task["task_id"], second_task["task_id"]],
                    },
                )

            self.assertEqual(response.status_code, 400)
            self.assertIn("same grouped review packet", response.json()["detail"])

    def test_issue_index_uses_full_verification_history_for_batch_review(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Codex Verification History Test", description="codex verification history", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task = connection.execute(
                    """
                    SELECT task_id, project_id
                    FROM tasks
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'review', priority = 50, review_state = 'review_requested'
                    WHERE task_id = ?
                    """,
                    (task["task_id"],),
                )
                connection.execute(
                    """
                    INSERT INTO verification_runs (
                        verification_run_id, project_id, task_id, command, status, exit_code, output_excerpt,
                        artifact_id, actor_id, started_at, finished_at
                    ) VALUES (
                        ?, ?, ?, 'pytest tests/test_history.py', 'failed', 1, '1 failed',
                        NULL, 'agent_reviewer', DATETIME('now', '-2 minutes'), DATETIME('now', '-2 minutes')
                    )
                    """,
                    (generate_id("vrf"), task["project_id"], task["task_id"]),
                )
                connection.execute(
                    """
                    INSERT INTO verification_runs (
                        verification_run_id, project_id, task_id, command, status, exit_code, output_excerpt,
                        artifact_id, actor_id, started_at, finished_at
                    ) VALUES (
                        ?, ?, ?, 'pytest tests/test_history.py', 'passed', 0, '1 passed',
                        NULL, 'agent_reviewer', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """,
                    (generate_id("vrf"), task["project_id"], task["task_id"]),
                )
                connection.commit()
            finally:
                connection.close()

            with TestClient(create_app(tmpdir)) as client:
                response = client.get("/api/issues/index")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            review_item = next(item for item in payload["queue"]["review"]["items"] if item["task_id"] == task["task_id"])
            self.assertFalse(review_item["batch_review_eligible"])
            self.assertIn("did not pass", review_item["batch_review_reason"])

    def test_issue_detail_exposes_batch_review_packet_when_auto_approve_is_disabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Codex Batch Packet Test", description="codex batch packet", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task = connection.execute(
                    """
                    SELECT task_id, project_id
                    FROM tasks
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'review', priority = 50, review_state = 'review_requested'
                    WHERE task_id = ?
                    """,
                    (task["task_id"],),
                )
                connection.execute(
                    """
                    UPDATE projects
                    SET config_json = json_set(
                        config_json,
                        '$.review_policy.auto_approve_low_risk', json('false'),
                        '$.review_policy.max_priority_for_auto_approve', 60,
                        '$.review_policy.require_verification_pass', json('true')
                    )
                    WHERE project_id = ?
                    """,
                    (task["project_id"],),
                )
                connection.execute(
                    """
                    INSERT INTO verification_runs (
                        verification_run_id, project_id, task_id, command, status, exit_code, output_excerpt,
                        artifact_id, actor_id, started_at, finished_at
                    ) VALUES (
                        ?, ?, ?, 'pytest tests/test_packet.py', 'passed', 0, '1 passed',
                        NULL, 'agent_reviewer', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """,
                    (generate_id("vrf"), task["project_id"], task["task_id"]),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            detail_response = client.get(f"/api/issues/{task['task_id']}")
            self.assertEqual(detail_response.status_code, 200)
            detail_payload = detail_response.json()

            self.assertEqual(detail_payload["review_decision"]["decision_mode"], "batch_review")
            self.assertTrue(detail_payload["review_decision"]["batch_review_eligible"])
            self.assertFalse(detail_payload["review_decision"]["auto_approve_eligible"])
            self.assertEqual(
                detail_payload["review_decision"]["why_not_auto_approved"],
                "This issue qualifies for the low-risk review packet, but project policy still requires a human or batch approval step.",
            )
            self.assertTrue(
                detail_payload["review_decision"]["grouped_review_packet"]["packet_key"].startswith("low_risk_verified_manual:")
            )
            self.assertEqual(detail_payload["recovery_playbook"]["title"], "Low-risk verified review packet")

    def test_goal_resynthesis_clears_stale_internal_dependencies(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Goal Refresh Test", description="goal refresh", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                goal = create_goal(
                    connection,
                    "agent_allocator",
                    None,
                    "Launch issue synthesis",
                    "Turn the objective into executable MAAS tasks.",
                    priority=82,
                )
                first_pass = synthesize_goal_issues(connection, None, goal["goal_id"], "agent_allocator", refresh=True)
                self.assertEqual(first_pass["task_count"], 5)
                dependency_count = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM task_dependencies
                    JOIN tasks dependent ON dependent.task_id = task_dependencies.target_task_id
                    JOIN tasks blocking ON blocking.task_id = task_dependencies.source_task_id
                    WHERE task_dependencies.project_id = ?
                      AND dependency_type = 'blocks'
                      AND dependent.goal_id = ?
                      AND blocking.goal_id = ?
                    """,
                    (first_pass["project_id"], goal["goal_id"], goal["goal_id"]),
                ).fetchone()[0]
                self.assertEqual(dependency_count, 4)

                project_row = connection.execute(
                    "SELECT project_type, config_json FROM projects WHERE project_id = ?",
                    (first_pass["project_id"],),
                ).fetchone()
                goal_row = connection.execute(
                    "SELECT title, description, priority FROM goals WHERE goal_id = ?",
                    (goal["goal_id"],),
                ).fetchone()
                shortened_specs = _goal_issue_specs(goal_row, project_row)[:3]
                with mock.patch("maas.services.goal_planning._goal_issue_specs", return_value=shortened_specs):
                    second_pass = synthesize_goal_issues(connection, None, goal["goal_id"], "agent_allocator", refresh=True)

                self.assertEqual(second_pass["task_count"], 3)
                dependency_count = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM task_dependencies
                    JOIN tasks dependent ON dependent.task_id = task_dependencies.target_task_id
                    JOIN tasks blocking ON blocking.task_id = task_dependencies.source_task_id
                    WHERE task_dependencies.project_id = ?
                      AND dependency_type = 'blocks'
                      AND dependent.goal_id = ?
                      AND blocking.goal_id = ?
                    """,
                    (second_pass["project_id"], goal["goal_id"], goal["goal_id"]),
                ).fetchone()[0]
                self.assertEqual(dependency_count, 2)
            finally:
                connection.close()

    def test_memory_promotion_feeds_memory_index_retrieval_and_issue_detail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Codex Memory Test", description="codex memory", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task = connection.execute(
                    """
                    SELECT task_id, project_id
                    FROM tasks
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                connection.execute(
                    """
                    UPDATE tasks
                    SET title = 'Prepare quant packet', description = 'Use prior packet memory for review.'
                    WHERE task_id = ?
                    """,
                    (task["task_id"],),
                )
                artifact_path = os.path.join(paths.artifacts_dir, "quant-packet.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("quant packet summary\nrisk notes and replay data\n")
                artifact_id = generate_id("art")
                connection.execute(
                    """
                    INSERT INTO artifacts (
                        artifact_id, project_id, task_id, session_id, artifact_type, path, metadata_json
                    ) VALUES (?, ?, ?, NULL, 'note', ?, '{}')
                    """,
                    (artifact_id, task["project_id"], task["task_id"], artifact_path),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            promote_response = client.post(
                f"/api/artifacts/{artifact_id}/actions/promote-memory",
                json={
                    "actor_id": "agent_allocator",
                    "title": "Quant packet memory",
                    "summary": "Reusable packet summary for quant review.",
                    "tags": ["quant", "packet"],
                },
            )
            self.assertEqual(promote_response.status_code, 200)

            memory_response = client.get("/api/memory")
            self.assertEqual(memory_response.status_code, 200)
            memory_payload = memory_response.json()
            self.assertEqual(memory_payload["items"][0]["artifact_id"], artifact_id)
            self.assertEqual(memory_payload["items"][0]["title"], "Quant packet memory")
            self.assertEqual(memory_payload["items"][0]["freshness"], "fresh")
            self.assertEqual(memory_payload["items"][0]["age_days"], 0)
            self.assertFalse(memory_payload["items"][0]["stale"])

            retrieval_response = client.get("/api/retrieval/search", params={"search": "quant packet"})
            self.assertEqual(retrieval_response.status_code, 200)
            retrieval_payload = retrieval_response.json()
            self.assertGreaterEqual(retrieval_payload["summary"]["memory_hits"], 1)
            self.assertEqual(retrieval_payload["memory"][0]["artifact_id"], artifact_id)

            detail_response = client.get(f"/api/issues/{task['task_id']}")
            self.assertEqual(detail_response.status_code, 200)
            detail_payload = detail_response.json()
            self.assertGreaterEqual(len(detail_payload["memory_context"]), 1)
            self.assertEqual(detail_payload["memory_context"][0]["artifact_id"], artifact_id)
            self.assertEqual(detail_payload["memory_context"][0]["freshness"], "fresh")

    def test_memory_retrieval_prefers_newer_promoted_items_on_score_ties(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Codex Memory Recency Test", description="codex memory recency", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task = connection.execute(
                    """
                    SELECT task_id, project_id
                    FROM tasks
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                connection.execute(
                    """
                    UPDATE tasks
                    SET title = 'Quant rollout runbook', description = 'Apply the latest quant rollout runbook.'
                    WHERE task_id = ?
                    """,
                    (task["task_id"],),
                )

                older_path = os.path.join(paths.artifacts_dir, "quant-runbook-old.txt")
                with open(older_path, "w", encoding="utf-8") as handle:
                    handle.write("quant rollout runbook\nold guidance\n")
                newer_path = os.path.join(paths.artifacts_dir, "quant-runbook-new.txt")
                with open(newer_path, "w", encoding="utf-8") as handle:
                    handle.write("quant rollout runbook\nnew guidance\n")

                older_artifact_id = generate_id("art")
                newer_artifact_id = generate_id("art")
                connection.execute(
                    """
                    INSERT INTO artifacts (
                        artifact_id, project_id, task_id, session_id, artifact_type, path, metadata_json, created_at
                    ) VALUES (?, ?, ?, NULL, 'note', ?, ?, ?)
                    """,
                    (
                        older_artifact_id,
                        task["project_id"],
                        task["task_id"],
                        older_path,
                        json.dumps(
                            {
                                "memory": {
                                    "promoted": True,
                                    "title": "Quant rollout runbook",
                                    "summary": "Old guidance",
                                    "tags": ["quant", "runbook"],
                                    "promoted_at": "2026-03-20T10:00:00+00:00",
                                    "promoted_by": "agent_allocator",
                                }
                            }
                        ),
                        "2026-03-20T10:00:00+00:00",
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO artifacts (
                        artifact_id, project_id, task_id, session_id, artifact_type, path, metadata_json, created_at
                    ) VALUES (?, ?, ?, NULL, 'note', ?, ?, ?)
                    """,
                    (
                        newer_artifact_id,
                        task["project_id"],
                        task["task_id"],
                        newer_path,
                        json.dumps(
                            {
                                "memory": {
                                    "promoted": True,
                                    "title": "Quant rollout runbook",
                                    "summary": "New guidance",
                                    "tags": ["quant", "runbook"],
                                    "promoted_at": "2026-03-21T10:00:00+00:00",
                                    "promoted_by": "agent_allocator",
                                }
                            }
                        ),
                        "2026-03-21T10:00:00+00:00",
                    ),
                )
                connection.commit()

                memory_entries = retrieve_relevant_memory(
                    connection,
                    task["project_id"],
                    "Quant rollout runbook",
                    task_description="Apply the latest quant rollout runbook.",
                    goal_title=None,
                    limit=1,
                )
            finally:
                connection.close()

            self.assertEqual(len(memory_entries), 1)
            self.assertEqual(memory_entries[0]["artifact_id"], newer_artifact_id)

    def test_memory_promotion_requires_authorized_actor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Codex Memory Permission Test", description="codex memory permission", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task = connection.execute(
                    """
                    SELECT task_id, project_id
                    FROM tasks
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                artifact_path = os.path.join(paths.artifacts_dir, "memory-denied.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("secret memory\n")
                artifact_id = generate_id("art")
                connection.execute(
                    """
                    INSERT INTO artifacts (
                        artifact_id, project_id, task_id, session_id, artifact_type, path, metadata_json
                    ) VALUES (?, ?, ?, NULL, 'note', ?, '{}')
                    """,
                    (artifact_id, task["project_id"], task["task_id"], artifact_path),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.post(
                f"/api/artifacts/{artifact_id}/actions/promote-memory",
                json={"actor_id": "not_a_real_actor"},
            )
            self.assertEqual(response.status_code, 403)

    def test_run_detail_exposes_memory_context_and_system_execution_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Codex Run Memory Test", description="codex run memory", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task = connection.execute(
                    """
                    SELECT task_id, project_id, assigned_agent_id
                    FROM tasks
                    WHERE assigned_agent_id IS NOT NULL
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                session_id = generate_id("sess")
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'in_progress'
                    WHERE task_id = ?
                    """,
                    (task["task_id"],),
                )
                connection.execute(
                    """
                    INSERT INTO sessions (
                        session_id, project_id, agent_id, task_id, status, provider_type, progress_pct,
                        status_message, last_heartbeat_at, started_at, ended_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, 'active', 'openai_codex', 40,
                        'Codex is using prior packet memory', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL, CURRENT_TIMESTAMP
                    )
                    """,
                    (session_id, task["project_id"], task["assigned_agent_id"], task["task_id"]),
                )
                connection.execute(
                    """
                    INSERT INTO activity_log (
                        activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
                    ) VALUES (?, ?, ?, ?, 'memory_context_loaded', 'runtime', ?, ?, 'info')
                    """,
                    (
                        generate_id("act"),
                        task["project_id"],
                        task["assigned_agent_id"],
                        task["task_id"],
                        "Injected project memory into the Codex prompt.",
                        json.dumps(
                            {
                                "session_id": session_id,
                                "memory_items": [
                                    {
                                        "artifact_id": "art_mem_1",
                                        "title": "Quant packet memory",
                                        "summary": "Reusable packet context",
                                        "tags": ["quant", "packet"],
                                        "score": 3,
                                        "freshness": "fresh",
                                        "age_days": 0,
                                        "stale": False,
                                    }
                                ],
                            }
                        ),
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            run_response = client.get(f"/api/runs/{session_id}")
            self.assertEqual(run_response.status_code, 200)
            run_payload = run_response.json()
            self.assertEqual(run_payload["session_id"], session_id)
            self.assertGreaterEqual(len(run_payload["memory_context"]), 1)
            self.assertEqual(run_payload["memory_context"][0]["artifact_id"], "art_mem_1")
            self.assertEqual(run_payload["memory_context"][0]["freshness"], "fresh")
            self.assertGreaterEqual(len(run_payload["phases"]), 1)

            diagnostics_response = client.get("/api/system/diagnostics")
            self.assertEqual(diagnostics_response.status_code, 200)
            diagnostics_payload = diagnostics_response.json()
            self.assertIsNotNone(diagnostics_payload["execution_state"])
            self.assertIn("state", diagnostics_payload["execution_state"])

    def test_retrieval_search_returns_issue_run_artifact_and_event_hits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Codex Retrieval Test", description="codex retrieval", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task = connection.execute(
                    """
                    SELECT task_id, project_id, assigned_agent_id, title
                    FROM tasks
                    WHERE assigned_agent_id IS NOT NULL
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                session_id = generate_id("sess")
                connection.execute(
                    """
                    UPDATE tasks
                    SET title = 'Prepare quant packet', description = 'Packet contains risk review context', status = 'in_progress'
                    WHERE task_id = ?
                    """,
                    (task["task_id"],),
                )
                connection.execute(
                    """
                    INSERT INTO sessions (
                        session_id, project_id, agent_id, task_id, status, provider_type, progress_pct,
                        status_message, last_heartbeat_at, started_at, ended_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, 'active', 'openai_codex', 45,
                        'Generating packet summary', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL, CURRENT_TIMESTAMP
                    )
                    """,
                    (session_id, task["project_id"], task["assigned_agent_id"], task["task_id"]),
                )
                artifact_path = os.path.join(paths.artifacts_dir, "packet-summary.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("packet artifact\n")
                connection.execute(
                    """
                    INSERT INTO artifacts (
                        artifact_id, project_id, task_id, session_id, artifact_type, path, metadata_json
                    ) VALUES (?, ?, ?, ?, 'note', ?, '{}')
                    """,
                    (generate_id("art"), task["project_id"], task["task_id"], session_id, artifact_path),
                )
                connection.execute(
                    """
                    INSERT INTO activity_log (
                        activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
                    ) VALUES (?, ?, ?, ?, 'packet_generated', 'runtime', ?, ?, 'info')
                    """,
                    (
                        generate_id("act"),
                        task["project_id"],
                        task["assigned_agent_id"],
                        task["task_id"],
                        "Generated packet summary for operator review.",
                        json.dumps({"session_id": session_id}),
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.get("/api/retrieval/search", params={"search": "packet"})
            self.assertEqual(response.status_code, 200)
            payload = response.json()

            self.assertGreaterEqual(payload["summary"]["issue_hits"], 1)
            self.assertGreaterEqual(payload["summary"]["run_hits"], 1)
            self.assertGreaterEqual(payload["summary"]["artifact_hits"], 1)
            self.assertGreaterEqual(payload["summary"]["event_hits"], 1)
            self.assertEqual(payload["issues"][0]["task_id"], task["task_id"])
            self.assertEqual(payload["runs"][0]["session_id"], session_id)
            self.assertEqual(payload["artifacts"][0]["task_id"], task["task_id"])
            self.assertEqual(payload["events"][0]["task_id"], task["task_id"])

            wrong_agent_response = client.get(
                "/api/retrieval/search",
                params={"search": "packet", "agent_id": "agent_missing"},
            )
            self.assertEqual(wrong_agent_response.status_code, 200)
            wrong_agent_payload = wrong_agent_response.json()
            self.assertEqual(wrong_agent_payload["summary"]["total_hits"], 0)

            priority_response = client.get(
                "/api/retrieval/search",
                params={"search": "packet", "priority_min": 999},
            )
            self.assertEqual(priority_response.status_code, 200)
            priority_payload = priority_response.json()
            self.assertEqual(priority_payload["summary"]["total_hits"], 0)

    def test_run_index_lists_recent_runs_with_state_details(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Codex Run Index Test", description="codex runs", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task = connection.execute(
                    """
                    SELECT task_id, project_id, assigned_agent_id, title, goal_id
                    FROM tasks
                    WHERE assigned_agent_id IS NOT NULL
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                project_id = task["project_id"]
                session_id = generate_id("sess")
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'in_progress', review_state = NULL
                    WHERE task_id = ?
                    """,
                    (task["task_id"],),
                )
                connection.execute(
                    """
                    INSERT INTO sessions (
                        session_id, project_id, agent_id, task_id, status, provider_type, progress_pct,
                        status_message, last_heartbeat_at, started_at, ended_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, 'active', 'openai_codex', 35,
                        'Codex is synthesizing a review packet', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL, CURRENT_TIMESTAMP
                    )
                    """,
                    (session_id, project_id, task["assigned_agent_id"], task["task_id"]),
                )
                connection.execute(
                    """
                    INSERT INTO activity_log (
                        activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
                    ) VALUES (?, ?, ?, ?, 'provider_adapter_started', 'runtime', ?, ?, 'info')
                    """,
                    (
                        generate_id("act"),
                        project_id,
                        task["assigned_agent_id"],
                        task["task_id"],
                        "Codex adapter started live execution.",
                        json.dumps(
                            {
                                "session_id": session_id,
                                "execution_mode": "codex_cli",
                                "external_runtime": "codex_cli",
                            }
                        ),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO artifacts (
                        artifact_id, project_id, task_id, session_id, artifact_type, path, metadata_json
                    ) VALUES (?, ?, ?, ?, 'note', ?, '{}')
                    """,
                    (generate_id("art"), project_id, task["task_id"], session_id, os.path.join(paths.artifacts_dir, "run-note.txt")),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.get("/api/runs")
            self.assertEqual(response.status_code, 200)
            payload = response.json()

            self.assertGreaterEqual(payload["summary"]["active_runs"], 1)
            self.assertEqual(payload["summary"]["stale_runs"], 0)
            run = next(item for item in payload["items"] if item["session_id"] == session_id)
            self.assertEqual(run["session_id"], session_id)
            self.assertEqual(run["task_id"], task["task_id"])
            self.assertEqual(run["task_status"], "in_progress")
            self.assertEqual(run["execution_mode"], "codex_cli")
            self.assertEqual(run["external_runtime"], "codex_cli")
            self.assertTrue(run["is_live"])
            self.assertFalse(run["is_stale"])
            self.assertEqual(run["artifact_count"], 1)
            self.assertIn("heartbeating", run["diagnostic_summary"])
            self.assertIn("Let the run continue", run["recommended_action"])

    def test_system_diagnostics_exposes_suspect_runs_and_stale_agents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Codex Diagnostics Test", description="codex diagnostics", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task = connection.execute(
                    """
                    SELECT task_id, project_id, assigned_agent_id
                    FROM tasks
                    WHERE assigned_agent_id IS NOT NULL
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                session_id = generate_id("sess")
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'in_progress'
                    WHERE task_id = ?
                    """,
                    (task["task_id"],),
                )
                connection.execute(
                    """
                    UPDATE agents
                    SET last_heartbeat_at = DATETIME('now', '-180 seconds')
                    WHERE agent_id = ?
                    """,
                    (task["assigned_agent_id"],),
                )
                connection.execute(
                    """
                    INSERT INTO sessions (
                        session_id, project_id, agent_id, task_id, status, provider_type, progress_pct,
                        status_message, last_heartbeat_at, started_at, ended_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, 'active', 'openai_codex', 35,
                        'Codex is synthesizing a review packet', DATETIME('now', '-180 seconds'), CURRENT_TIMESTAMP, NULL, CURRENT_TIMESTAMP
                    )
                    """,
                    (session_id, task["project_id"], task["assigned_agent_id"], task["task_id"]),
                )
                connection.execute(
                    """
                    INSERT INTO activity_log (
                        activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
                    ) VALUES (?, ?, ?, ?, 'provider_adapter_started', 'runtime', ?, ?, 'info')
                    """,
                    (
                        generate_id("act"),
                        task["project_id"],
                        task["assigned_agent_id"],
                        task["task_id"],
                        "Codex adapter started live execution.",
                        json.dumps(
                            {
                                "session_id": session_id,
                                "execution_mode": "codex_cli",
                                "external_runtime": "codex_cli",
                            }
                        ),
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.get("/api/system/diagnostics")
            self.assertEqual(response.status_code, 200)
            payload = response.json()

            self.assertEqual(payload["summary"]["suspect_runs"], 1)
            self.assertEqual(payload["summary"]["stale_agents"], 1)
            self.assertEqual(payload["suspect_runs"][0]["session_id"], session_id)
            self.assertTrue(payload["suspect_runs"][0]["is_stale"])
            self.assertEqual(payload["stale_agents"][0]["agent_id"], task["assigned_agent_id"])
            self.assertEqual(payload["stale_agents"][0]["focus_run_session_id"], session_id)

    def test_run_cancel_action_halts_linked_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Codex Run Cancel Test", description="codex cancel", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task = connection.execute(
                    """
                    SELECT task_id, project_id, assigned_agent_id
                    FROM tasks
                    WHERE assigned_agent_id IS NOT NULL
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                session_id = generate_id("sess")
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'in_progress'
                    WHERE task_id = ?
                    """,
                    (task["task_id"],),
                )
                connection.execute(
                    """
                    INSERT INTO sessions (
                        session_id, project_id, agent_id, task_id, status, provider_type, progress_pct,
                        status_message, last_heartbeat_at, started_at, ended_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, 'active', 'openai_codex', 10,
                        'Codex is running', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL, CURRENT_TIMESTAMP
                    )
                    """,
                    (session_id, task["project_id"], task["assigned_agent_id"], task["task_id"]),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.post(
                f"/api/runs/{session_id}/actions/cancel",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["session_id"], session_id)
            self.assertEqual(payload["status"], "cancelled")

            connection = connect(paths)
            try:
                task_row = connection.execute(
                    "SELECT status, review_state FROM tasks WHERE task_id = ?",
                    (task["task_id"],),
                ).fetchone()
                session_row = connection.execute(
                    "SELECT status FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                self.assertEqual(task_row["status"], "cancelled")
                self.assertEqual(task_row["review_state"], "halted_by_operator")
                self.assertEqual(session_row["status"], "cancelled")
            finally:
                connection.close()

    def test_issue_detail_exposes_live_run_console(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Codex Live Console Test", description="codex live console", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task = connection.execute(
                    """
                    SELECT task_id, project_id, assigned_agent_id, title
                    FROM tasks
                    WHERE assigned_agent_id IS NOT NULL
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                project_id = task["project_id"]
                session_id = generate_id("sess")
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'in_progress', progress_pct = 60
                    WHERE task_id = ?
                    """,
                    (task["task_id"],),
                )
                connection.execute(
                    """
                    INSERT INTO sessions (
                        session_id, project_id, agent_id, task_id, status, provider_type, progress_pct,
                        status_message, last_heartbeat_at, started_at, ended_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, 'active', 'openai_codex', 60,
                        'OpenAI Codex CLI is executing live CLI work', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL, CURRENT_TIMESTAMP
                    )
                    """,
                    (session_id, project_id, task["assigned_agent_id"], task["task_id"]),
                )
                envelope = paths.ensure_runtime_envelope(project_id, session_id)
                with open(os.path.join(envelope["root"], "runtime-output.txt"), "w", encoding="utf-8") as handle:
                    handle.write("draft output\nstep 1 complete\n")
                with open(os.path.join(envelope["root"], "stdout.log"), "w", encoding="utf-8") as handle:
                    handle.write("stdout line 1\nstdout line 2\n")
                with open(os.path.join(envelope["root"], "stderr.log"), "w", encoding="utf-8") as handle:
                    handle.write("stderr line 1\n")
                connection.execute(
                    """
                    INSERT INTO activity_log (
                        activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
                    ) VALUES (?, ?, ?, ?, 'provider_adapter_started', 'runtime', ?, ?, 'info')
                    """,
                    (
                        generate_id("act"),
                        project_id,
                        task["assigned_agent_id"],
                        task["task_id"],
                        "OpenAI Codex adapter started local execution.",
                        json.dumps(
                            {
                                "session_id": session_id,
                                "timeout_seconds": 900,
                                "command": ["codex", "exec", "Task: example"],
                                "runtime_root": envelope["root"],
                                "execution_mode": "codex_cli",
                                "external_runtime": "codex_cli",
                            }
                        ),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO activity_log (
                        activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
                    ) VALUES (?, ?, ?, ?, 'provider_execution_progress', 'runtime', ?, ?, 'info')
                    """,
                    (
                        generate_id("act"),
                        project_id,
                        task["assigned_agent_id"],
                        task["task_id"],
                        "OpenAI Codex adapter is executing the live CLI provider run.",
                        json.dumps({"session_id": session_id}),
                    ),
                )
                for index in range(15):
                    connection.execute(
                        """
                        INSERT INTO activity_log (
                            activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
                        ) VALUES (?, ?, ?, ?, 'provider_execution_progress', 'runtime', ?, ?, 'info')
                        """,
                        (
                            generate_id("act"),
                            project_id,
                            task["assigned_agent_id"],
                            task["task_id"],
                            f"progress tick {index}",
                            json.dumps({"session_id": session_id, "tick": index}),
                        ),
                    )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.get(f"/api/issues/{task['task_id']}")
            self.assertEqual(response.status_code, 200)
            payload = response.json()

            self.assertIsNotNone(payload["run_console"])
            self.assertEqual(payload["run_console"]["session_id"], session_id)
            self.assertTrue(payload["run_console"]["is_live"])
            self.assertEqual(payload["run_console"]["timeout_seconds"], 900)
            self.assertEqual(payload["run_console"]["command"], ["codex", "exec", "Task: example"])
            self.assertEqual(payload["run_console"]["execution_mode"], "codex_cli")
            self.assertEqual(payload["run_console"]["external_runtime"], "codex_cli")
            self.assertIn("step 1 complete", payload["run_console"]["output_preview"]["content"])
            self.assertIn("stdout line 2", payload["run_console"]["stdout_preview"]["content"])
            self.assertIn("stderr line 1", payload["run_console"]["stderr_preview"]["content"])
            self.assertGreaterEqual(len(payload["run_console"]["activity"]), 2)

            run_response = client.get(f"/api/runs/{session_id}")
            self.assertEqual(run_response.status_code, 200)
            run_payload = run_response.json()
            self.assertEqual(run_payload["session_id"], session_id)
            self.assertEqual(run_payload["task_id"], task["task_id"])
            self.assertEqual(run_payload["execution_mode"], "codex_cli")
            self.assertEqual(run_payload["external_runtime"], "codex_cli")
            self.assertTrue(run_payload["is_live"])
            self.assertIn("step 1 complete", run_payload["output_preview"]["content"])

    def test_issue_detail_exposes_relationships_runs_history_and_stable_issue_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Codex MVP Test", description="codex mvp", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                tasks = connection.execute(
                    """
                    SELECT task_id, project_id, title, assigned_agent_id, goal_id
                    FROM tasks
                    ORDER BY created_at ASC, task_id ASC
                    """
                ).fetchall()
                project_id = tasks[0]["project_id"]
                selected_task = next(row for row in tasks if row["title"] == "Validate seeded lifecycle semantics")
                dependency_task = next(row for row in tasks if row["title"] == "Implement FastAPI board endpoint")
                unlocked_task = next(
                    row
                    for row in tasks
                    if row["task_id"] not in {selected_task["task_id"], dependency_task["task_id"]}
                )

                connection.execute(
                    """
                    INSERT INTO task_dependencies (
                        dependency_id, project_id, source_task_id, target_task_id, dependency_type
                    ) VALUES (?, ?, ?, ?, 'blocks')
                    """,
                    (generate_id("dep"), project_id, dependency_task["task_id"], selected_task["task_id"]),
                )
                connection.execute(
                    """
                    INSERT INTO task_dependencies (
                        dependency_id, project_id, source_task_id, target_task_id, dependency_type
                    ) VALUES (?, ?, ?, ?, 'informs')
                    """,
                    (generate_id("dep"), project_id, selected_task["task_id"], unlocked_task["task_id"]),
                )

                session_id = generate_id("sess")
                connection.execute(
                    """
                    INSERT INTO sessions (
                        session_id, project_id, agent_id, task_id, status, provider_type, progress_pct,
                        status_message, last_heartbeat_at, started_at, ended_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, 'active', 'codex_cli', 100,
                        'Completed review draft', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL, CURRENT_TIMESTAMP
                    )
                    """,
                    (session_id, project_id, selected_task["assigned_agent_id"], selected_task["task_id"]),
                )

                artifact_path = os.path.join(result["paths"].artifacts_dir, "codex-mvp-review.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("review packet\n")
                connection.execute(
                    """
                    INSERT INTO artifacts (
                        artifact_id, project_id, task_id, session_id, artifact_type, path, metadata_json
                    ) VALUES (?, ?, ?, ?, 'note', ?, '{}')
                    """,
                    (generate_id("art"), project_id, selected_task["task_id"], session_id, artifact_path),
                )

                connection.execute(
                    """
                    INSERT INTO verification_runs (
                        verification_run_id, project_id, task_id, command, status, exit_code, output_excerpt,
                        artifact_id, actor_id, started_at, finished_at
                    ) VALUES (
                        ?, ?, ?, 'pytest tests/test_dashboard.py', 'passed', 0, '1 passed',
                        NULL, 'agent_reviewer', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """,
                    (generate_id("vrf"), project_id, selected_task["task_id"]),
                )
                connection.execute(
                    """
                    INSERT INTO activity_log (
                        activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
                    ) VALUES (?, ?, ?, ?, 'provider_adapter_started', 'runtime', ?, ?, 'info')
                    """,
                    (
                        generate_id("act"),
                        project_id,
                        selected_task["assigned_agent_id"],
                        selected_task["task_id"],
                        "Codex adapter started local execution.",
                        json.dumps(
                            {
                                "session_id": session_id,
                                "execution_mode": "local_simulation",
                                "external_runtime": "local_simulation",
                            }
                        ),
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))

            board_payload = client.get("/api/board").json()
            selected_board_task = next(
                task
                for column in board_payload["columns"]
                for task in column["tasks"]
                if task["task_id"] == selected_task["task_id"]
            )

            response = client.get(f"/api/issues/{selected_task['task_id']}")
            self.assertEqual(response.status_code, 200)
            payload = response.json()

            self.assertEqual(payload["task"]["task_id"], selected_task["task_id"])
            self.assertEqual(payload["task"]["issue_key"], selected_board_task["issue_key"])
            self.assertGreaterEqual(len(payload["history"]), 1)
            self.assertEqual(payload["runs"][0]["session_id"], session_id)
            self.assertEqual(payload["runs"][0]["execution_mode"], "local_simulation")
            self.assertEqual(payload["verification_runs"][0]["command"], "pytest tests/test_dashboard.py")
            self.assertEqual(payload["artifacts"][0]["artifact_type"], "note")
            self.assertEqual(payload["relationships"]["depends_on"][0]["task_id"], dependency_task["task_id"])
            self.assertEqual(payload["relationships"]["depends_on"][0]["issue_key"], next(
                task["issue_key"]
                for column in board_payload["columns"]
                for task in column["tasks"]
                if task["task_id"] == dependency_task["task_id"]
            ))
            self.assertEqual(payload["relationships"]["unlocks"][0]["task_id"], unlocked_task["task_id"])

    def test_agent_detail_exposes_owned_issues_runs_and_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Codex Agent Detail Test", description="codex agent detail", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                agent = connection.execute(
                    """
                    SELECT agent_id, project_id
                    FROM agents
                    WHERE role = 'builder'
                    LIMIT 1
                    """
                ).fetchone()
                task = connection.execute(
                    """
                    SELECT task_id, title
                    FROM tasks
                    WHERE assigned_agent_id = ?
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (agent["agent_id"],),
                ).fetchone()
                session_id = generate_id("sess")
                connection.execute(
                    """
                    INSERT INTO sessions (
                        session_id, project_id, agent_id, task_id, status, provider_type, progress_pct,
                        status_message, last_heartbeat_at, started_at, ended_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, 'active', 'codex_cli', 42,
                        'Running codex thread', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL, CURRENT_TIMESTAMP
                    )
                    """,
                    (session_id, agent["project_id"], agent["agent_id"], task["task_id"]),
                )
                connection.execute(
                    """
                    INSERT INTO activity_log (
                        activity_id, project_id, agent_id, task_id, action, category, description, details_json, severity
                    ) VALUES (?, ?, ?, ?, 'provider_adapter_started', 'runtime', ?, ?, 'info')
                    """,
                    (
                        generate_id("act"),
                        agent["project_id"],
                        agent["agent_id"],
                        task["task_id"],
                        "Codex adapter started local execution.",
                        json.dumps(
                            {
                                "session_id": session_id,
                                "execution_mode": "codex_cli",
                                "external_runtime": "codex_cli",
                            }
                        ),
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.get(f"/api/agents/{agent['agent_id']}")
            self.assertEqual(response.status_code, 200)
            payload = response.json()

            self.assertEqual(payload["agent"]["agent_id"], agent["agent_id"])
            self.assertTrue(payload["owned_issues"])
            self.assertEqual(payload["owned_issues"][0]["task_id"], task["task_id"])
            self.assertEqual(payload["runs"][0]["session_id"], session_id)
            self.assertEqual(payload["runs"][0]["execution_mode"], "codex_cli")
            self.assertIn("heartbeating", payload["runs"][0]["diagnostic_summary"])
            self.assertGreaterEqual(len(payload["history"]), 1)

    def test_environment_doctor_goal_planning_and_delivery_endpoints(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Codex Doctor Test", description="doctor", project_type="custom")
            paths = project_paths(tmpdir)
            client = TestClient(create_app(tmpdir))

            doctor_response = client.get("/api/environment/doctor")
            self.assertEqual(doctor_response.status_code, 200)
            doctor_payload = doctor_response.json()
            self.assertIn(doctor_payload["summary"]["status"], {"blocked", "simulation_only", "attention", "ready"})
            self.assertIn("status", doctor_payload["progress"])

            goal_response = client.post(
                "/api/goals",
                json={
                    "actor_id": "agent_allocator",
                    "title": "Launch issue synthesis",
                    "description": "Turn the objective into executable MAAS tasks.",
                    "goal_type": "initiative",
                    "priority": 82,
                },
            )
            self.assertEqual(goal_response.status_code, 200)
            goal_payload = goal_response.json()["goal"]

            synthesize_response = client.post(
                f"/api/goals/{goal_payload['goal_id']}/actions/synthesize",
                json={"actor_id": "agent_allocator", "refresh": True},
            )
            self.assertEqual(synthesize_response.status_code, 200)
            synthesize_payload = synthesize_response.json()
            self.assertGreaterEqual(synthesize_payload["created_count"], 1)
            self.assertTrue(synthesize_payload["task_ids"])

            planning_response = client.get("/api/goals/planning")
            self.assertEqual(planning_response.status_code, 200)
            planning_payload = planning_response.json()
            self.assertGreaterEqual(planning_payload["summary"]["total_goals"], 1)
            self.assertGreaterEqual(planning_payload["summary"]["open_issue_count"], 1)

            task_id = synthesize_payload["task_ids"][0]
            connection = connect(paths)
            try:
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'review', review_state = 'review_requested'
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
                artifact_path = os.path.join(paths.artifacts_dir, "delivery-test.txt")
                os.makedirs(os.path.dirname(artifact_path), exist_ok=True)
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("diff --git a/app.py b/app.py\n+print('delivery')\n")
                connection.execute(
                    """
                    INSERT INTO artifacts (
                        artifact_id, project_id, task_id, session_id, artifact_type, path, metadata_json
                    ) VALUES (?, (SELECT project_id FROM tasks WHERE task_id = ?), ?, NULL, 'git_diff', ?, '{}')
                    """,
                    (generate_id("art"), task_id, task_id, artifact_path),
                )
                connection.commit()
            finally:
                connection.close()

            delivery_response = client.get("/api/delivery")
            self.assertEqual(delivery_response.status_code, 200)
            delivery_payload = delivery_response.json()
            self.assertGreaterEqual(delivery_payload["summary"]["candidate_count"], 1)
            delivery_item = next(item for item in delivery_payload["items"] if item["task_id"] == task_id)
            self.assertEqual(delivery_item["delivery_kind"], "diff")

            draft_response = client.post(
                f"/api/tasks/{task_id}/actions/prepare-pr-draft",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(draft_response.status_code, 200)
            draft_payload = draft_response.json()
            self.assertTrue(draft_payload["gh_command"].startswith("gh pr create"))
            self.assertTrue(os.path.exists(draft_payload["body_path"]))

    def test_delivery_overview_does_not_build_temp_bundles_on_refresh(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Delivery Refresh Test", description="delivery refresh", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task = connection.execute(
                    """
                    SELECT task_id, project_id
                    FROM tasks
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'review', review_state = 'review_requested'
                    WHERE task_id = ?
                    """,
                    (task["task_id"],),
                )
                artifact_path = os.path.join(paths.artifacts_dir, "delivery-refresh.txt")
                os.makedirs(os.path.dirname(artifact_path), exist_ok=True)
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("diff --git a/app.py b/app.py\n+print('refresh')\n")
                connection.execute(
                    """
                    INSERT INTO artifacts (
                        artifact_id, project_id, task_id, session_id, artifact_type, path, metadata_json
                    ) VALUES (?, ?, ?, NULL, 'git_diff', ?, '{}')
                    """,
                    (generate_id("art"), task["project_id"], task["task_id"], artifact_path),
                )
                connection.commit()

                with mock.patch(
                    "maas.services.delivery.build_artifact_export_bundle",
                    side_effect=AssertionError("delivery overview should not create export bundles"),
                ):
                    payload = fetch_delivery_overview(connection, paths, task["project_id"])
            finally:
                connection.close()

            item = next(entry for entry in payload["items"] if entry["task_id"] == task["task_id"])
            self.assertTrue(item["bundle_ready"])

    def test_board_review_eligibility_uses_full_verification_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Board Verification History Test", description="board verification history", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task = connection.execute(
                    """
                    SELECT task_id, project_id
                    FROM tasks
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'review', priority = 50, review_state = 'review_requested'
                    WHERE task_id = ?
                    """,
                    (task["task_id"],),
                )
                for index in range(11):
                    status = "failed" if index == 0 else "passed"
                    connection.execute(
                        """
                        INSERT INTO verification_runs (
                            verification_run_id, project_id, task_id, command, status, exit_code, output_excerpt,
                            artifact_id, actor_id, started_at, finished_at
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, NULL, 'agent_reviewer',
                            DATETIME('now', ?), DATETIME('now', ?)
                        )
                        """,
                        (
                            generate_id("vrf"),
                            task["project_id"],
                            task["task_id"],
                            "pytest tests/test_history.py",
                            status,
                            1 if status == "failed" else 0,
                            status,
                            "-{0} minutes".format(120 - index),
                            "-{0} minutes".format(120 - index),
                        ),
                    )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            board_payload = client.get("/api/board").json()
            board_task = next(
                item
                for column in board_payload["columns"]
                for item in column["tasks"]
                if item["task_id"] == task["task_id"]
            )

            self.assertFalse(board_task["batch_review_eligible"])
            self.assertEqual(
                board_task["review_eligibility"]["why_not_batch_reviewed"],
                "One or more verification runs did not pass.",
            )
            response = client.post(
                "/api/issues/actions/batch-review",
                json={
                    "actor_id": "agent_allocator",
                    "decision": "approve",
                    "task_ids": [task["task_id"]],
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("did not pass", response.json()["detail"])

    def test_environment_doctor_does_not_block_on_nonpreferred_provider_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Doctor Provider Test", description="doctor provider", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                with mock.patch(
                    "maas.services.environment_doctor.list_provider_status",
                    return_value=[
                        {
                            "id": "openai_codex",
                            "name": "OpenAI Codex",
                            "effective_execution_mode": "codex_cli",
                            "execution_mode": "codex_cli",
                            "is_runnable": True,
                            "configurable_runtime_controls": {"cli_command": "codex"},
                            "config_warnings": [],
                            "notes": None,
                        },
                        {
                            "id": "claude_code",
                            "name": "Claude Code",
                            "effective_execution_mode": "codex_cli",
                            "execution_mode": "codex_cli",
                            "is_runnable": False,
                            "configurable_runtime_controls": {"cli_command": "claude"},
                            "config_warnings": ["CLI not installed"],
                            "notes": "CLI not installed",
                        },
                    ],
                ), mock.patch(
                    "maas.services.environment_doctor._cli_available",
                    side_effect=lambda command: command == "codex",
                ), mock.patch(
                    "maas.services.environment_doctor._codex_auth_available",
                    return_value=True,
                ):
                    payload = fetch_environment_doctor(connection, paths, project_id)
            finally:
                connection.close()

            self.assertNotEqual(payload["summary"]["status"], "blocked")
            provider_checks = {item["code"]: item for item in payload["checks"] if item["code"].startswith("provider_")}
            self.assertEqual(provider_checks["provider_openai_codex"]["status"], "passed")
            self.assertEqual(provider_checks["provider_claude_code"]["status"], "warning")

    def test_goal_creation_rejects_parent_goal_from_another_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Cross Project Parent Test", description="cross project parent", project_type="custom")
            with TestClient(create_app(tmpdir)) as client:
                second_project = client.post(
                    "/api/projects",
                    json={
                        "actor_id": "agent_allocator",
                        "name": "Second Project",
                        "description": "secondary",
                        "project_type": "custom",
                        "mode": "greenfield",
                    },
                ).json()["project"]
            connection = connect(project_paths(tmpdir))
            try:
                project_rows = connection.execute(
                    "SELECT project_id FROM projects ORDER BY created_at ASC"
                ).fetchall()
                first_project_id = project_rows[0]["project_id"]
                parent_goal = create_goal(
                    connection,
                    "agent_allocator",
                    first_project_id,
                    "Parent goal",
                    "first project goal",
                )
                with self.assertRaisesRegex(ValueError, "parent goal not found"):
                    create_goal(
                        connection,
                        "agent_allocator",
                        second_project["project_id"],
                        "Child goal",
                        "should fail",
                        parent_goal_id=parent_goal["goal_id"],
                    )
            finally:
                connection.close()

    def test_prepare_pr_draft_rejects_non_delivery_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Delivery Guard Test", description="delivery guard", project_type="custom")
            client = TestClient(create_app(tmpdir))
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task = connection.execute(
                    """
                    SELECT task_id
                    FROM tasks
                    WHERE status = 'planned'
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
            finally:
                connection.close()

            response = client.post(
                f"/api/tasks/{task['task_id']}/actions/prepare-pr-draft",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("not ready for delivery", response.json()["detail"])

    def test_delivery_reads_include_gate_and_issue_detail_delivery_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Delivery Reads Test", description="delivery reads", project_type="custom")
            client = TestClient(create_app(tmpdir))
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task = connection.execute(
                    """
                    SELECT task_id, project_id
                    FROM tasks
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'review', review_state = 'review_requested'
                    WHERE task_id = ?
                    """,
                    (task["task_id"],),
                )
                artifact_path = os.path.join(paths.artifacts_dir, "delivery-read.txt")
                os.makedirs(os.path.dirname(artifact_path), exist_ok=True)
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("diff --git a/app.py b/app.py\n+print('delivery reads')\n")
                connection.execute(
                    """
                    INSERT INTO artifacts (
                        artifact_id, project_id, task_id, session_id, artifact_type, path, metadata_json
                    ) VALUES (?, ?, ?, NULL, 'git_diff', ?, '{}')
                    """,
                    (generate_id("art"), task["project_id"], task["task_id"], artifact_path),
                )
                connection.commit()
            finally:
                connection.close()

            git_snapshot = {
                "is_git_repo": True,
                "branch": "feature/delivery-reads",
                "default_branch": "main",
                "dirty": False,
                "gh_installed": True,
            }
            with mock.patch("maas.services.delivery._git_repo_snapshot", return_value=git_snapshot):
                delivery_response = client.get("/api/delivery")
                self.assertEqual(delivery_response.status_code, 200)
                delivery_payload = delivery_response.json()
                item = next(entry for entry in delivery_payload["items"] if entry["task_id"] == task["task_id"])
                self.assertEqual(item["delivery_gate"]["status"], "attention")
                self.assertIn("No explicit delivery verification commands", item["delivery_gate"]["summary"])

                task_delivery_response = client.get(f"/api/tasks/{task['task_id']}/delivery")
                self.assertEqual(task_delivery_response.status_code, 200)
                self.assertEqual(task_delivery_response.json()["delivery_gate"]["status"], "attention")

                issue_detail_response = client.get(f"/api/issues/{task['task_id']}")
                self.assertEqual(issue_detail_response.status_code, 200)
                issue_delivery = issue_detail_response.json()["delivery"]
                self.assertEqual(issue_delivery["delivery_gate"]["status"], "attention")
                self.assertIsNone(issue_delivery["github_pr"])

    def test_sync_github_pr_creates_draft_and_persists_sync_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Delivery Sync Test", description="delivery sync", project_type="custom")
            client = TestClient(create_app(tmpdir))
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task = connection.execute(
                    """
                    SELECT task_id, project_id
                    FROM tasks
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'review',
                        review_state = 'review_requested',
                        acceptance_criteria_json = ?
                    WHERE task_id = ?
                    """,
                    (
                        json.dumps([{"type": "test_passes", "command": "pytest tests/test_delivery.py"}]),
                        task["task_id"],
                    ),
                )
                artifact_path = os.path.join(paths.artifacts_dir, "delivery-sync.txt")
                os.makedirs(os.path.dirname(artifact_path), exist_ok=True)
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("diff --git a/app.py b/app.py\n+print('delivery sync')\n")
                connection.execute(
                    """
                    INSERT INTO artifacts (
                        artifact_id, project_id, task_id, session_id, artifact_type, path, metadata_json
                    ) VALUES (?, ?, ?, NULL, 'git_diff', ?, '{}')
                    """,
                    (generate_id("art"), task["project_id"], task["task_id"], artifact_path),
                )
                connection.execute(
                    """
                    INSERT INTO verification_runs (
                        verification_run_id, project_id, task_id, command, status, exit_code, output_excerpt,
                        artifact_id, actor_id, started_at, finished_at
                    ) VALUES (
                        ?, ?, ?, 'pytest tests/test_delivery.py', 'passed', 0, 'delivery ok',
                        NULL, 'agent_reviewer', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """,
                    (generate_id("vrf"), task["project_id"], task["task_id"]),
                )
                connection.commit()
            finally:
                connection.close()

            git_snapshot = {
                "is_git_repo": True,
                "branch": "feature/delivery-sync",
                "default_branch": "main",
                "dirty": False,
                "gh_installed": True,
            }
            list_calls = {"count": 0}

            def fake_run(command, **kwargs):
                args = tuple(command)
                completed = mock.Mock()
                completed.returncode = 0
                completed.stdout = ""
                completed.stderr = ""
                if args[:3] == ("gh", "pr", "list"):
                    list_calls["count"] += 1
                    if list_calls["count"] == 1:
                        completed.stdout = "[]"
                    else:
                        completed.stdout = json.dumps(
                            [
                                {
                                    "number": 17,
                                    "url": "https://example.test/pr/17",
                                    "state": "OPEN",
                                    "isDraft": True,
                                    "title": "[MAAS] Delivery Sync",
                                    "headRefName": "feature/delivery-sync",
                                    "baseRefName": "main",
                                }
                            ]
                        )
                elif args[:3] == ("gh", "pr", "create"):
                    completed.stdout = "https://example.test/pr/17\n"
                elif args[:3] == ("gh", "pr", "view"):
                    completed.stdout = json.dumps(
                        {
                            "number": 17,
                            "url": "https://example.test/pr/17",
                            "state": "OPEN",
                            "isDraft": True,
                            "title": "[MAAS] Delivery Sync",
                            "headRefName": "feature/delivery-sync",
                            "baseRefName": "main",
                        }
                    )
                else:  # pragma: no cover - guards the expected call set
                    raise AssertionError(f"unexpected command: {command}")
                return completed

            with mock.patch("maas.services.delivery._git_repo_snapshot", return_value=git_snapshot), mock.patch(
                "maas.services.delivery.subprocess.run", side_effect=fake_run
            ):
                response = client.post(
                    f"/api/tasks/{task['task_id']}/actions/sync-github-pr",
                    json={"actor_id": "agent_allocator"},
                )
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["mode"], "created")
                self.assertEqual(payload["github_pr"]["number"], 17)
                self.assertEqual(payload["delivery_gate"]["status"], "ready")

                delivery_response = client.get(f"/api/tasks/{task['task_id']}/delivery")
                self.assertEqual(delivery_response.status_code, 200)
                self.assertEqual(delivery_response.json()["github_pr"]["number"], 17)

    def test_sync_github_pr_rejects_failed_delivery_gate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Delivery Gate Test", description="delivery gate", project_type="custom")
            client = TestClient(create_app(tmpdir))
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                task = connection.execute(
                    """
                    SELECT task_id, project_id
                    FROM tasks
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'review',
                        review_state = 'review_requested',
                        acceptance_criteria_json = ?
                    WHERE task_id = ?
                    """,
                    (
                        json.dumps([{"type": "test_passes", "command": "pytest tests/test_delivery.py"}]),
                        task["task_id"],
                    ),
                )
                artifact_path = os.path.join(paths.artifacts_dir, "delivery-gate.txt")
                os.makedirs(os.path.dirname(artifact_path), exist_ok=True)
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("diff --git a/app.py b/app.py\n+print('delivery gate')\n")
                connection.execute(
                    """
                    INSERT INTO artifacts (
                        artifact_id, project_id, task_id, session_id, artifact_type, path, metadata_json
                    ) VALUES (?, ?, ?, NULL, 'git_diff', ?, '{}')
                    """,
                    (generate_id("art"), task["project_id"], task["task_id"], artifact_path),
                )
                connection.execute(
                    """
                    INSERT INTO verification_runs (
                        verification_run_id, project_id, task_id, command, status, exit_code, output_excerpt,
                        artifact_id, actor_id, started_at, finished_at
                    ) VALUES (
                        ?, ?, ?, 'pytest tests/test_delivery.py', 'failed', 1, 'delivery failed',
                        NULL, 'agent_reviewer', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """,
                    (generate_id("vrf"), task["project_id"], task["task_id"]),
                )
                connection.commit()
            finally:
                connection.close()

            git_snapshot = {
                "is_git_repo": True,
                "branch": "feature/delivery-gate",
                "default_branch": "main",
                "dirty": False,
                "gh_installed": True,
            }
            with mock.patch("maas.services.delivery._git_repo_snapshot", return_value=git_snapshot):
                response = client.post(
                    f"/api/tasks/{task['task_id']}/actions/sync-github-pr",
                    json={"actor_id": "agent_allocator"},
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("verification", response.json()["detail"].lower())

    def test_git_helpers_accept_worktree_style_git_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, ".git"), "w", encoding="utf-8") as handle:
                handle.write("gitdir: /tmp/fake-worktree\n")

            def fake_run(command, **kwargs):
                args = tuple(command)
                completed = mock.Mock()
                completed.returncode = 0
                completed.stdout = ""
                if args == ("git", "rev-parse", "--is-inside-work-tree"):
                    completed.stdout = "true\n"
                elif args == ("git", "rev-parse", "--abbrev-ref", "HEAD"):
                    completed.stdout = "main\n"
                elif args == ("git", "symbolic-ref", "refs/remotes/origin/HEAD"):
                    completed.stdout = "refs/remotes/origin/main\n"
                elif args == ("git", "status", "--porcelain"):
                    completed.stdout = ""
                else:  # pragma: no cover - guards the expected call set
                    raise AssertionError(f"unexpected git command: {command}")
                return completed

            with mock.patch("maas.services.environment_doctor.subprocess.run", side_effect=fake_run):
                doctor_git = _git_status(tmpdir)
            with mock.patch("maas.services.delivery.subprocess.run", side_effect=fake_run), mock.patch(
                "maas.services.delivery.shutil.which", return_value="/usr/bin/gh"
            ):
                delivery_git = _git_repo_snapshot(tmpdir)

            self.assertTrue(doctor_git["is_git_repo"])
            self.assertEqual(doctor_git["branch"], "main")
            self.assertEqual(doctor_git["default_branch"], "main")
            self.assertTrue(delivery_git["is_git_repo"])
            self.assertEqual(delivery_git["branch"], "main")
            self.assertEqual(delivery_git["default_branch"], "main")
