import json
import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.ids import generate_id
from maas.services.bootstrap import bootstrap_project
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

            review_items = {item["task_id"]: item for item in payload["queue"]["review"]["items"]}
            self.assertTrue(review_items[review_task["task_id"]]["batch_review_eligible"])
            self.assertFalse(review_items[high_priority_review["task_id"]]["batch_review_eligible"])
            self.assertEqual(review_items[high_priority_review["task_id"]]["batch_review_reason"], "Priority is above the low-risk batch-review threshold.")

            failure_task_ids = {item["task_id"] for item in payload["queue"]["blocked_failures"]["items"]}
            dependency_task_ids = {item["task_id"] for item in payload["queue"]["blocked_dependencies"]["items"]}
            self.assertIn(blocked_failure["task_id"], failure_task_ids)
            self.assertIn(blocked_dependency["task_id"], dependency_task_ids)

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
