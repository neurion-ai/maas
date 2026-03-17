import json
import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.ids import generate_id
from maas.services.bootstrap import bootstrap_project


class ProjectsApiTest(unittest.TestCase):
    def _insert_second_project(self, connection):
        project_id = generate_id("proj")
        goal_id = generate_id("goal")
        agent_id = generate_id("agent")
        task_id = generate_id("task")
        connection.execute(
            """
            INSERT INTO projects (project_id, name, description, project_type, config_json)
            VALUES (?, 'Second Project', 'secondary', 'custom', ?)
            """,
            (project_id, json.dumps({"project": {"name": "Second Project"}})),
        )
        connection.execute(
            """
            INSERT INTO goals (
                goal_id, project_id, title, description, status, goal_type, priority, acceptance_criteria_json
            ) VALUES (?, ?, 'Second Project Goal', 'goal', 'active', 'strategic', 90, '[]')
            """,
            (goal_id, project_id),
        )
        connection.execute(
            """
            INSERT INTO agents (agent_id, project_id, role, display_name, status, permissions_json)
            VALUES (?, ?, 'allocator', 'Second Allocator', 'running', '{}')
            """,
            (agent_id, project_id),
        )
        connection.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, goal_id, title, description, status, priority, assigned_agent_id,
                acceptance_criteria_json, progress_pct, review_state, last_heartbeat_at
            ) VALUES (?, ?, ?, 'Second project scoped task', 'scoped', 'in_progress', 99, ?, '[]', 30, NULL, CURRENT_TIMESTAMP)
            """,
            (task_id, project_id, goal_id, agent_id),
        )
        connection.execute(
            """
            INSERT INTO activity_log (
                activity_id, project_id, agent_id, task_id, action, category, description, severity
            ) VALUES (?, ?, ?, ?, 'project_marker', 'steering', 'Second project activity marker', 'info')
            """,
            (generate_id("act"), project_id, agent_id, task_id),
        )
        connection.execute(
            """
            INSERT INTO alerts (
                alert_id, project_id, severity, title, description, status
            ) VALUES (?, ?, 'warning', 'Second project alert', 'Scoped alert', 'open')
            """,
            (generate_id("alert"), project_id),
        )
        connection.commit()
        return project_id

    def test_projects_endpoint_lists_multiple_projects(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                self._insert_second_project(connection)
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            payload = client.get("/api/projects").json()

            self.assertEqual(len(payload["projects"]), 2)
            self.assertEqual(payload["projects"][0]["name"], "Primary Project")
            self.assertEqual(payload["projects"][1]["name"], "Second Project")

    def test_core_read_models_can_be_scoped_to_selected_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Primary Project", description="primary", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                second_project_id = self._insert_second_project(connection)
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            projects = client.get("/api/projects").json()["projects"]
            second_project_id = projects[1]["project_id"]

            overview_payload = client.get("/api/overview", params={"project_id": second_project_id}).json()
            board_payload = client.get("/api/board", params={"project_id": second_project_id}).json()
            live_payload = client.get("/api/live", params={"project_id": second_project_id}).json()
            activity_payload = client.get("/api/activity", params={"project_id": second_project_id}).json()

            self.assertEqual(overview_payload["project"]["name"], "Second Project")
            self.assertTrue(
                any(
                    task["title"] == "Second project scoped task"
                    for column in board_payload["columns"]
                    for task in column["tasks"]
                )
            )
            self.assertEqual(live_payload["counts"]["alerts_open"], 1)
            self.assertEqual(activity_payload[0]["description"], "Second project activity marker")
