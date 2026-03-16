import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.services.bootstrap import bootstrap_project
from maas.services.failure_memory import restore_quarantined_session_artifacts
from maas.services.lifecycle import end_session, produce_artifact, start_session
from maas.services.security import TASK_EXECUTION_CAPABILITIES, grant_task_capabilities


class ArtifactsApiTest(unittest.TestCase):
    def test_artifacts_api_exposes_active_quarantined_and_restored_states(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Artifacts API Test",
                description="Artifacts API test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                test_agents = (
                    ("agent_artifact_active", "Artifact Active Agent"),
                    ("agent_artifact_quarantined", "Artifact Quarantined Agent"),
                    ("agent_artifact_restored", "Artifact Restored Agent"),
                )
                for agent_id, display_name in test_agents:
                    connection.execute(
                        """
                        INSERT INTO agents (
                            agent_id, project_id, role, display_name, status, permissions_json
                        ) VALUES (?, ?, 'builder', ?, 'idle', '{"board_actions": true}')
                        """,
                        (agent_id, project_id, display_name),
                    )

                for task_id, title, agent_id in (
                    ("task_artifact_active", "Artifact active task", "agent_artifact_active"),
                    ("task_artifact_quarantined", "Artifact quarantined task", "agent_artifact_quarantined"),
                    ("task_artifact_restored", "Artifact restored task", "agent_artifact_restored"),
                ):
                    connection.execute(
                        """
                        INSERT INTO tasks (
                            task_id, project_id, title, description, status, priority, acceptance_criteria_json
                        ) VALUES (?, ?, ?, '', 'ready', 60, '[]')
                        """,
                        (task_id, project_id, title),
                    )
                    grant_task_capabilities(
                        connection,
                        project_id,
                        task_id,
                        agent_id,
                        TASK_EXECUTION_CAPABILITIES,
                        granted_by="test_setup",
                    )
                connection.commit()
                task_rows = connection.execute(
                    """
                    SELECT task_id
                    FROM tasks
                    WHERE task_id IN ('task_artifact_active', 'task_artifact_quarantined', 'task_artifact_restored')
                    ORDER BY created_at ASC
                    LIMIT 3
                    """
                ).fetchall()
                active_task_id = task_rows[0]["task_id"]
                quarantined_task_id = task_rows[1]["task_id"]
                restored_task_id = task_rows[2]["task_id"]

                active_session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_active",
                    task_id=active_task_id,
                    provider_type="python_script",
                    status_message="Starting active artifact test",
                )
                active_artifact_path = os.path.join(result["paths"].artifacts_dir, "active-artifact.txt")
                with open(active_artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("active\n")
                produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=active_session_id,
                    task_id=active_task_id,
                    artifact_type="note",
                    path=active_artifact_path,
                )

                quarantined_session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_quarantined",
                    task_id=quarantined_task_id,
                    provider_type="python_script",
                    status_message="Starting quarantined artifact test",
                )
                quarantined_artifact_path = os.path.join(result["paths"].artifacts_dir, "quarantined-artifact.txt")
                with open(quarantined_artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("quarantined\n")
                produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=quarantined_session_id,
                    task_id=quarantined_task_id,
                    artifact_type="provider_report",
                    path=quarantined_artifact_path,
                )
                end_session(
                    connection,
                    quarantined_session_id,
                    "failed",
                    "Quarantined artifact failure",
                    project_paths=result["paths"],
                )

                restored_session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_restored",
                    task_id=restored_task_id,
                    provider_type="python_script",
                    status_message="Starting restored artifact test",
                )
                restored_artifact_path = os.path.join(result["paths"].artifacts_dir, "restored-artifact.txt")
                with open(restored_artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("restored\n")
                produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=restored_session_id,
                    task_id=restored_task_id,
                    artifact_type="provider_report",
                    path=restored_artifact_path,
                )
                end_session(
                    connection,
                    restored_session_id,
                    "failed",
                    "Restored artifact failure",
                    project_paths=result["paths"],
                )
                restore_quarantined_session_artifacts(connection, result["paths"], restored_session_id)
                connection.commit()
            finally:
                connection.close()

            payload = TestClient(create_app(tmpdir)).get("/api/artifacts").json()

            self.assertEqual(payload["summary"]["total_artifacts"], 3)
            self.assertEqual(payload["summary"]["active_artifacts"], 1)
            self.assertEqual(payload["summary"]["quarantined_artifacts"], 1)
            self.assertEqual(payload["summary"]["restored_artifacts"], 1)

            artifacts_by_state = {item["artifact_state"]: item for item in payload["items"]}
            self.assertEqual(artifacts_by_state["active"]["task_id"], active_task_id)
            self.assertEqual(artifacts_by_state["quarantined"]["task_id"], quarantined_task_id)
            self.assertEqual(artifacts_by_state["quarantined"]["quarantined_from_path"], quarantined_artifact_path)
            self.assertEqual(artifacts_by_state["restored"]["task_id"], restored_task_id)
            self.assertTrue(artifacts_by_state["restored"]["restored_from_quarantine"])
            self.assertEqual(artifacts_by_state["restored"]["provider_type"], "python_script")

    def test_artifacts_api_tracks_external_and_missing_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(
                tmpdir,
                name="Artifacts External Test",
                description="Artifacts external test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                connection.execute(
                    """
                    INSERT INTO agents (
                        agent_id, project_id, role, display_name, status, permissions_json
                    ) VALUES (?, ?, 'builder', ?, 'idle', '{"board_actions": true}')
                    """,
                    ("agent_artifact_external", project_id, "Artifact External Agent"),
                )
                task_id = "task_artifact_external"
                connection.execute(
                    """
                    INSERT INTO tasks (
                        task_id, project_id, title, description, status, priority, acceptance_criteria_json
                    ) VALUES (?, ?, 'Artifact external task', '', 'ready', 60, '[]')
                    """,
                    (task_id, project_id),
                )
                grant_task_capabilities(
                    connection,
                    project_id,
                    task_id,
                    "agent_artifact_external",
                    TASK_EXECUTION_CAPABILITIES,
                    granted_by="test_setup",
                )
                connection.commit()
                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_external",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting external artifact test",
                )
                external_artifact_path = os.path.join(tmpdir, "external-artifact.txt")
                with open(external_artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("external\n")
                produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    artifact_type="note",
                    path=external_artifact_path,
                )
                os.remove(external_artifact_path)
            finally:
                connection.close()

            payload = TestClient(create_app(tmpdir)).get("/api/artifacts").json()

            self.assertEqual(payload["summary"]["total_artifacts"], 1)
            self.assertEqual(payload["summary"]["external_artifacts"], 1)
            self.assertEqual(payload["summary"]["missing_files"], 1)
            self.assertEqual(payload["items"][0]["artifact_state"], "external")
            self.assertFalse(payload["items"][0]["exists"])
            self.assertEqual(payload["provider_types"][0]["provider_type"], "python_script")


if __name__ == "__main__":
    unittest.main()
