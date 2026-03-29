import json
import os
import subprocess
import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.ids import generate_id
from maas.services.bootstrap import bootstrap_project
from maas.services.escalations import request_escalation
from maas.services.git_workspaces import prepare_task_git_workspace
from maas.services.lifecycle import end_session, produce_artifact, start_session
from maas.services.verification import run_task_verification


def _init_git_repo(root):
    subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "MAAS Tests"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class DashboardApiTest(unittest.TestCase):
    def test_overview_and_goal_tree_shapes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Dashboard Test", description="Dashboard test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    INSERT INTO failure_log (
                        failure_id, project_id, task_id, session_id, agent_id, failure_type, summary, detail_json
                    )
                    SELECT ?, project_id, ?, session_id, agent_id, 'session_failed', 'Dashboard-visible failure', '{}'
                    FROM sessions
                    WHERE task_id = ?
                    LIMIT 1
                    """,
                    (generate_id("fail"), task_id, task_id),
                )
                connection.commit()
            finally:
                connection.close()
            client = TestClient(create_app(tmpdir))

            overview = client.get("/api/overview")
            self.assertEqual(overview.status_code, 200)
            overview_payload = overview.json()
            self.assertEqual(overview_payload["project"]["name"], "Dashboard Test")
            self.assertGreaterEqual(overview_payload["summary"]["tasks_total"], 1)
            self.assertEqual(overview_payload["summary"]["failures_total"], 1)
            self.assertIn("active_work", overview_payload)
            self.assertIn("recent_activity", overview_payload)
            self.assertIn("recent_failures", overview_payload)

            goal_tree = client.get("/api/goals/tree")
            self.assertEqual(goal_tree.status_code, 200)
            goal_tree_payload = goal_tree.json()
            self.assertGreaterEqual(goal_tree_payload["total_goals"], 1)
            self.assertGreaterEqual(len(goal_tree_payload["roots"]), 1)
            self.assertIn("children", goal_tree_payload["roots"][0])

    def test_overview_exposes_brownfield_onboarding_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, ".github", "workflows"), exist_ok=True)
            with open(os.path.join(tmpdir, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("# Imported Project\n")
            with open(os.path.join(tmpdir, "pyproject.toml"), "w", encoding="utf-8") as handle:
                handle.write(
                    """
[project]
name = "imported-project"

[project.scripts]
lint = "example:main"
""".strip()
                )
            with open(os.path.join(tmpdir, ".github", "workflows", "ci.yml"), "w", encoding="utf-8") as handle:
                handle.write("name: CI\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n")
            with open(os.path.join(tmpdir, "src", "app.py"), "w", encoding="utf-8") as handle:
                handle.write("print('hello')\n")

            bootstrap_project(tmpdir, name="Brownfield Dashboard Test", description="dashboard brownfield", project_type="custom")
            client = TestClient(create_app(tmpdir))

            overview_payload = client.get("/api/overview").json()

            self.assertEqual(overview_payload["onboarding"]["mode"], "brownfield")
            self.assertEqual(overview_payload["onboarding"]["review_status"], "review_pending")
            self.assertTrue(overview_payload["onboarding"]["review_required"])
            self.assertEqual(overview_payload["onboarding"]["pending_gated_tasks"], 5)
            self.assertEqual(
                overview_payload["onboarding"]["discovery_summary"]["primary_language"],
                "python",
            )
            self.assertGreaterEqual(
                len(overview_payload["onboarding"]["discovery_summary"]["workflow_details"]),
                1,
            )
            self.assertGreaterEqual(
                len(overview_payload["onboarding"]["discovery_summary"]["runbook_commands"]),
                1,
            )
            self.assertGreaterEqual(
                len(overview_payload["onboarding"]["discovery_summary"]["codebase_map"]),
                1,
            )
            self.assertTrue(
                any(
                    item["name"] == "src"
                    for item in overview_payload["onboarding"]["discovery_summary"]["codebase_map"]
                )
            )
            src_entry = next(
                item
                for item in overview_payload["onboarding"]["discovery_summary"]["codebase_map"]
                if item["name"] == "src"
            )
            self.assertIn(
                "src/app.py",
                src_entry["sample_files"],
            )
            self.assertIn(
                "src",
                overview_payload["onboarding"]["discovery_summary"]["repo_areas"],
            )
            self.assertIn(
                "python_script:lint",
                [
                    item["label"]
                    for item in overview_payload["onboarding"]["discovery_summary"]["runbook_commands"]
                ],
            )
            self.assertEqual(overview_payload["onboarding"]["review_overrides"]["ignored_paths"], [])
            self.assertGreater(overview_payload["onboarding"]["repo_plan_preview"]["generated_task_count"], 0)
            self.assertIsNone(overview_payload["onboarding"]["repo_plan_state"])

    def test_overview_exposes_repo_plan_state_after_brownfield_approval(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
            with open(os.path.join(tmpdir, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("# Imported Project\n")
            with open(os.path.join(tmpdir, "pyproject.toml"), "w", encoding="utf-8") as handle:
                handle.write(
                    """
[project]
name = "imported-project"

[project.scripts]
lint = "example:main"
""".strip()
                )
            with open(os.path.join(tmpdir, "src", "app.py"), "w", encoding="utf-8") as handle:
                handle.write("print('hello')\n")

            bootstrap_project(tmpdir, name="Brownfield Repo Plan Test", description="dashboard brownfield repo plan", project_type="custom")
            client = TestClient(create_app(tmpdir))
            review_task_id = client.get("/api/overview").json()["onboarding"]["review_task_id"]
            review_response = client.post(
                f"/api/tasks/{review_task_id}/actions/review",
                json={"actor_id": "agent_reviewer", "decision": "approve"},
            )
            self.assertEqual(review_response.status_code, 200)

            overview_payload = client.get("/api/overview").json()
            self.assertEqual(overview_payload["onboarding"]["review_status"], "approved")
            self.assertIsNotNone(overview_payload["onboarding"]["repo_plan_state"])
            self.assertFalse(overview_payload["onboarding"]["repo_plan_state"]["stale"])
            self.assertGreater(overview_payload["onboarding"]["repo_plan_state"]["generated_task_count"], 0)
            self.assertEqual(
                overview_payload["onboarding"]["repo_plan_state"]["active_task_count"],
                overview_payload["onboarding"]["repo_plan_state"]["generated_task_count"],
            )
            verification_item = next(
                item
                for item in overview_payload["onboarding"]["repo_plan_state"]["items"]
                if item["task_kind"] == "verification_recipe"
            )
            self.assertTrue(verification_item["task_id"])
            self.assertTrue(verification_item["issue_key"])
            self.assertGreaterEqual(len(verification_item["linked_items"]), 1)

    def test_overview_repo_plan_items_expose_execution_leverage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
            with open(os.path.join(tmpdir, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("# Imported Project\n")
            with open(os.path.join(tmpdir, "pyproject.toml"), "w", encoding="utf-8") as handle:
                handle.write(
                    """
[project]
name = "imported-project"

[project.scripts]
lint = "example:main"
""".strip()
                )
            with open(os.path.join(tmpdir, "src", "app.py"), "w", encoding="utf-8") as handle:
                handle.write("print('hello')\n")
            _init_git_repo(tmpdir)

            bootstrap_project(tmpdir, name="Brownfield Execution Leverage Test", description="dashboard execution leverage", project_type="custom")
            client = TestClient(create_app(tmpdir))
            review_task_id = client.get("/api/overview").json()["onboarding"]["review_task_id"]
            review_response = client.post(
                f"/api/tasks/{review_task_id}/actions/review",
                json={"actor_id": "agent_reviewer", "decision": "approve"},
            )
            self.assertEqual(review_response.status_code, 200)

            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                verification_task = connection.execute(
                    """
                    SELECT task_id
                    FROM tasks
                    WHERE synthesis_origin = 'repo_grounded_plan'
                      AND synthesis_key LIKE 'runbook:%'
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                repo_area_task = connection.execute(
                    """
                    SELECT task_id
                    FROM tasks
                    WHERE synthesis_origin = 'repo_grounded_plan'
                      AND synthesis_key LIKE 'area:%'
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
                connection.execute(
                    """
                    UPDATE tasks
                    SET acceptance_criteria_json = '[{"type":"test_passes","command":"python -c \\"print(123)\\"","timeout_seconds":30}]'
                    WHERE task_id = ?
                    """,
                    (verification_task["task_id"],),
                )
                connection.commit()

                run_task_verification(connection, paths, verification_task["task_id"], "agent_allocator")
                prepare_task_git_workspace(connection, paths, repo_area_task["task_id"], "agent_allocator")
            finally:
                connection.close()

            overview_payload = client.get("/api/overview").json()
            repo_plan_items = overview_payload["onboarding"]["repo_plan_state"]["items"]
            verification_item = next(item for item in repo_plan_items if item["task_kind"] == "verification_recipe")
            repo_area_item = next(item for item in repo_plan_items if item["task_kind"] == "repo_area_plan")

            self.assertTrue(verification_item["validation_commands"])
            self.assertEqual(verification_item["latest_verification_status"], "passed")
            self.assertEqual(verification_item["latest_verification_command"], "python -c \"print(123)\"")
            self.assertGreaterEqual(verification_item["covered_repo_area_count"], 1)
            self.assertTrue(repo_area_item["git_workspace_supported"])
            self.assertTrue(repo_area_item["git_workspace_prepared"])
            self.assertTrue(repo_area_item["git_workspace_branch"].startswith("maas/"))
            self.assertGreaterEqual(repo_area_item["supporting_verification_recipe_count"], 1)

    def test_overview_exposes_repo_plan_trust_and_lineage_after_refresh(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "tests"), exist_ok=True)
            with open(os.path.join(tmpdir, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("# Imported Project\n")
            with open(os.path.join(tmpdir, "pyproject.toml"), "w", encoding="utf-8") as handle:
                handle.write(
                    """
[project]
name = "imported-project"

[project.scripts]
lint = "example:main"
""".strip()
                )
            with open(os.path.join(tmpdir, "src", "app.py"), "w", encoding="utf-8") as handle:
                handle.write("print('hello')\n")
            with open(os.path.join(tmpdir, "tests", "test_app.py"), "w", encoding="utf-8") as handle:
                handle.write("def test_ok():\n    assert True\n")

            bootstrap_project(tmpdir, name="Brownfield Trust Test", description="dashboard brownfield trust", project_type="custom")
            client = TestClient(create_app(tmpdir))
            review_task_id = client.get("/api/overview").json()["onboarding"]["review_task_id"]
            approve_response = client.post(
                f"/api/tasks/{review_task_id}/actions/review",
                json={"actor_id": "agent_reviewer", "decision": "approve"},
            )
            self.assertEqual(approve_response.status_code, 200)

            connection = connect(project_paths(tmpdir))
            try:
                project = connection.execute("SELECT project_id, config_json FROM projects LIMIT 1").fetchone()
                config = json.loads(project["config_json"] or "{}")
                config["onboarding"]["review_overrides"]["accepted_workflow_labels"] = []
                config["onboarding"]["review_overrides"]["accepted_runbook_labels"] = []
                connection.execute(
                    "UPDATE projects SET config_json = ? WHERE project_id = ?",
                    (json.dumps(config), project["project_id"]),
                )
                connection.commit()
            finally:
                connection.close()

            refresh_response = client.post(
                f"/api/projects/{project['project_id']}/actions/refresh-repo-plan",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(refresh_response.status_code, 200)

            overview_payload = client.get("/api/overview").json()
            trust = overview_payload["onboarding"]["repo_plan_state"]["trust"]
            lineage = overview_payload["onboarding"]["repo_plan_state"]["lineage"]

            self.assertEqual(trust["state"], "fresh")
            self.assertTrue(trust["safe_to_execute"])
            self.assertGreaterEqual(lineage["superseded_task_count"], 1)
            self.assertGreaterEqual(len(lineage["superseded_items"]), 1)
            self.assertGreaterEqual(len(lineage["recent_refreshes"]), 1)

    def test_overview_marks_repo_area_workspace_supported_from_git_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = os.path.join(tmpdir, "repo")
            source_root = os.path.join(repo_root, "apps", "service")
            os.makedirs(os.path.join(source_root, "src"), exist_ok=True)
            with open(os.path.join(source_root, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("# Imported Project\n")
            with open(os.path.join(source_root, "pyproject.toml"), "w", encoding="utf-8") as handle:
                handle.write(
                    """
[project]
name = "imported-project"

[project.scripts]
lint = "example:main"
""".strip()
                )
            with open(os.path.join(source_root, "src", "app.py"), "w", encoding="utf-8") as handle:
                handle.write("print('hello')\n")
            _init_git_repo(repo_root)

            bootstrap_project(
                source_root,
                name="Brownfield Nested Git Support Test",
                description="dashboard nested git support",
                project_type="custom",
            )
            client = TestClient(create_app(source_root))
            review_task_id = client.get("/api/overview").json()["onboarding"]["review_task_id"]
            review_response = client.post(
                f"/api/tasks/{review_task_id}/actions/review",
                json={"actor_id": "agent_reviewer", "decision": "approve"},
            )
            self.assertEqual(review_response.status_code, 200)

            overview_payload = client.get("/api/overview").json()
            repo_area_item = next(
                item
                for item in overview_payload["onboarding"]["repo_plan_state"]["items"]
                if item["task_kind"] == "repo_area_plan"
            )
            self.assertTrue(repo_area_item["git_workspace_supported"])

    def test_overview_filters_brownfield_summary_using_review_overrides(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "tests"), exist_ok=True)
            with open(os.path.join(tmpdir, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("# Imported Project\n")
            with open(os.path.join(tmpdir, "pyproject.toml"), "w", encoding="utf-8") as handle:
                handle.write(
                    """
[project]
name = "imported-project"

[project.scripts]
lint = "example:main"
""".strip()
                )
            with open(os.path.join(tmpdir, "Makefile"), "w", encoding="utf-8") as handle:
                handle.write("test:\n\tpytest\n")
            with open(os.path.join(tmpdir, "src", "app.py"), "w", encoding="utf-8") as handle:
                handle.write("print('hello')\n")
            with open(os.path.join(tmpdir, "tests", "test_app.py"), "w", encoding="utf-8") as handle:
                handle.write("def test_ok():\n    assert True\n")

            bootstrap_project(
                tmpdir,
                name="Filtered Brownfield Dashboard Test",
                description="dashboard brownfield",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
            try:
                project = connection.execute("SELECT project_id, config_json FROM projects LIMIT 1").fetchone()
                config = json.loads(project["config_json"] or "{}")
                config["onboarding"]["review_overrides"] = {
                    "ignored_paths": ["tests"],
                    "accepted_workflow_labels": ["python_script:lint"],
                    "accepted_runbook_labels": ["python_script:lint"],
                }
                connection.execute(
                    "UPDATE projects SET config_json = ? WHERE project_id = ?",
                    (json.dumps(config), project["project_id"]),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            overview_payload = client.get("/api/overview").json()

            self.assertEqual(overview_payload["onboarding"]["review_overrides"]["ignored_paths"], ["tests"])
            self.assertEqual(
                overview_payload["onboarding"]["discovery_summary"]["workflow_labels"],
                ["python_script:lint"],
            )
            self.assertEqual(
                [item["label"] for item in overview_payload["onboarding"]["discovery_summary"]["runbook_commands"]],
                ["python_script:lint"],
            )
            codebase_names = [
                item["name"] for item in overview_payload["onboarding"]["discovery_summary"]["codebase_map"]
            ]
            self.assertIn("src", codebase_names)
            self.assertNotIn("tests", codebase_names)

    def test_overview_repeated_failure_summary_is_not_capped_to_top_five(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Dashboard Failure Count Test", description="Dashboard failure count test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                for index in range(6):
                    task_id = f"task_repeat_{index}"
                    connection.execute(
                        """
                        INSERT INTO tasks (
                            task_id, project_id, title, description, status, priority, acceptance_criteria_json
                        ) VALUES (?, ?, ?, '', 'blocked', 50, '[]')
                        """,
                        (task_id, project_id, f"Repeated failure task {index}"),
                    )
                    for failure_index in range(2):
                        connection.execute(
                            """
                            INSERT INTO failure_log (
                                failure_id, project_id, task_id, failure_type, summary, detail_json
                            ) VALUES (?, ?, ?, 'session_failed', ?, '{}')
                            """,
                            (
                                generate_id("fail"),
                                project_id,
                                task_id,
                                f"failure {failure_index}",
                            ),
                        )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            overview_payload = client.get("/api/overview").json()
            live_payload = client.get("/api/live").json()

            self.assertEqual(overview_payload["summary"]["repeated_failure_tasks"], 6)
            self.assertEqual(len(overview_payload["repeated_failures"]), 5)
            self.assertEqual(live_payload["counts"]["repeated_failure_tasks"], 6)

    def test_overview_recent_failures_include_quarantined_artifact_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Dashboard Quarantine Test",
                description="Dashboard quarantine test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE status = 'ready' LIMIT 1"
                ).fetchone()["task_id"]
                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_allocator",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting dashboard quarantine test",
                )
                artifact_path = os.path.join(result["paths"].artifacts_dir, "dashboard-quarantine-note.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("dashboard quarantine\n")
                produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    artifact_type="note",
                    path=artifact_path,
                )
                end_session(
                    connection,
                    session_id,
                    "failed",
                    "Dashboard failure with quarantined artifact",
                    project_paths=result["paths"],
                )
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            overview_payload = client.get("/api/overview").json()
            recent_failure = overview_payload["recent_failures"][0]

            self.assertEqual(recent_failure["failure_type"], "session_failed")
            self.assertEqual(recent_failure["quarantined_artifact_count"], 1)
            self.assertEqual(recent_failure["quarantined_artifacts"][0]["quarantined_from_path"], artifact_path)

    def test_overview_recent_failures_include_operator_actions_for_quarantined_work(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Dashboard Failure Actions Test",
                description="Dashboard failure actions test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE status = 'ready' LIMIT 1"
                ).fetchone()["task_id"]
                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_allocator",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting dashboard failure actions test",
                )
                artifact_path = os.path.join(result["paths"].artifacts_dir, "dashboard-failure-actions-note.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("dashboard action\n")
                produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    artifact_type="note",
                    path=artifact_path,
                )
                end_session(
                    connection,
                    session_id,
                    "failed",
                    "Dashboard failure with actions",
                    project_paths=result["paths"],
                )
                queue_id = connection.execute(
                    "SELECT queue_id FROM quarantine_queue WHERE session_id = ?",
                    (session_id,),
                ).fetchone()["queue_id"]
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            recent_failure = client.get("/api/overview").json()["recent_failures"][0]

            self.assertEqual(
                recent_failure["operator_action"],
                {
                    "action": "restore_and_requeue_quarantine_entry",
                    "label": "Restore + requeue",
                    "resource_type": "quarantine",
                    "resource_id": queue_id,
                    "related_task_id": task_id,
                },
            )
            self.assertEqual(
                recent_failure["secondary_operator_action"],
                {
                    "action": "dismiss_quarantine_entry",
                    "label": "Dismiss",
                    "resource_type": "quarantine",
                    "resource_id": queue_id,
                    "related_task_id": task_id,
                },
            )

    def test_overview_repeated_failures_include_operator_actions_when_alert_is_open(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(
                tmpdir,
                name="Dashboard Repeated Failure Actions Test",
                description="Dashboard repeated failure actions test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Define project workspace contracts'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    INSERT INTO failure_log (
                        failure_id, project_id, task_id, failure_type, summary, detail_json
                    ) VALUES
                        (?, ?, ?, 'session_failed', 'First repeated failure', '{}'),
                        (?, ?, ?, 'session_failed', 'Second repeated failure', '{}')
                    """,
                    (generate_id("fail"), project_id, task_id, generate_id("fail"), project_id, task_id),
                )
                connection.execute(
                    """
                    INSERT INTO alerts (
                        alert_id, project_id, severity, title, description, status
                    ) VALUES (
                        ?,
                        ?,
                        'critical',
                        'Repeated task failures',
                        ?,
                        'open'
                    )
                    """,
                    (
                        generate_id("alert"),
                        project_id,
                        "Task {0} (Define project workspace contracts) has failed 2 times. Latest failure: Second repeated failure".format(
                            task_id
                        ),
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            repeated_failure = client.get("/api/overview").json()["repeated_failures"][0]

            self.assertEqual(
                repeated_failure["operator_action"],
                {
                    "action": "resolve_repeated_failures",
                    "label": "Resolve repeated failures",
                    "resource_type": "task",
                    "resource_id": task_id,
                },
            )

    def test_agent_roster_is_enriched(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Roster Test", description="Roster test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            roster = client.get("/api/agents")
            self.assertEqual(roster.status_code, 200)
            payload = roster.json()
            self.assertIn("agents", payload)
            self.assertGreaterEqual(len(payload["agents"]), 1)
            self.assertIn("display_name", payload["agents"][0])
            self.assertIn("heartbeat_age_seconds", payload["agents"][0])

    def test_overview_includes_open_escalation_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Escalation Overview Test", description="Escalation overview test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE status = 'ready' LIMIT 1"
                ).fetchone()["task_id"]
                request_escalation(
                    connection,
                    project_id=project_id,
                    actor_id="agent_builder",
                    action_type="halt_task",
                    resource_type="task",
                    resource_id=task_id,
                    reason="Need operator approval",
                )
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            overview_payload = client.get("/api/overview").json()

            self.assertEqual(overview_payload["summary"]["escalations_open"], 1)


if __name__ == "__main__":
    unittest.main()
