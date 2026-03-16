import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.ids import generate_id
from maas.services.bootstrap import bootstrap_project
from maas.services.escalations import request_escalation
from maas.services.lifecycle import end_session, produce_artifact, start_session


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
