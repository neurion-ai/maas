import json
import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.ids import generate_id
from maas.services.bootstrap import bootstrap_project
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
            self.assertEqual(
                payload["queue"]["review"]["batch_review"]["packets"][0]["packet_key"],
                "low_risk_verified_auto",
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
            self.assertEqual(
                detail_payload["review_decision"]["grouped_review_packet"]["packet_key"],
                "low_risk_verified_auto",
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
            self.assertEqual(response.json()["review_packets"][0]["packet_key"], "low_risk_verified_auto")
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
            self.assertEqual(
                detail_payload["review_decision"]["grouped_review_packet"]["packet_key"],
                "low_risk_verified_manual",
            )
            self.assertEqual(detail_payload["recovery_playbook"]["title"], "Low-risk verified review packet")

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
