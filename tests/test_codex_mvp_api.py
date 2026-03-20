import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.ids import generate_id
from maas.services.bootstrap import bootstrap_project
class CodexMvpApiTest(unittest.TestCase):
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
            self.assertGreaterEqual(len(payload["history"]), 1)
