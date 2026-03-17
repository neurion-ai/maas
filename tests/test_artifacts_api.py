import json
import os
import tempfile
import unittest
import zipfile

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.ids import generate_id
from maas.services.artifacts import ARTIFACT_PREVIEW_MAX_BYTES
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

    def test_artifact_detail_api_exposes_preview_metadata_and_download(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Artifacts Detail Test",
                description="Artifacts detail test",
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
                    ("agent_artifact_detail", project_id, "Artifact Detail Agent"),
                )
                task_id = "task_artifact_detail"
                connection.execute(
                    """
                    INSERT INTO tasks (
                        task_id, project_id, title, description, status, priority, acceptance_criteria_json
                    ) VALUES (?, ?, 'Artifact detail task', '', 'ready', 60, '[]')
                    """,
                    (task_id, project_id),
                )
                grant_task_capabilities(
                    connection,
                    project_id,
                    task_id,
                    "agent_artifact_detail",
                    TASK_EXECUTION_CAPABILITIES,
                    granted_by="test_setup",
                )
                connection.commit()

                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_detail",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting artifact detail test",
                )
                artifact_path = os.path.join(result["paths"].artifacts_dir, "detail-artifact.json")
                artifact_body = '{\n  "result": "ok",\n  "notes": "artifact detail"\n}\n'
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write(artifact_body)
                artifact_id = produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    artifact_type="provider_report",
                    path=artifact_path,
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))

            detail_response = client.get(f"/api/artifacts/{artifact_id}")
            self.assertEqual(detail_response.status_code, 200)
            detail_payload = detail_response.json()
            self.assertEqual(detail_payload["artifact_id"], artifact_id)
            self.assertEqual(detail_payload["preview"]["kind"], "json")
            self.assertIn('"result": "ok"', detail_payload["preview"]["content"])
            self.assertEqual(detail_payload["metadata"], {})
            self.assertEqual(detail_payload["download_url"], f"/api/artifacts/{artifact_id}/download")

            download_response = client.get(detail_payload["download_url"])
            self.assertEqual(download_response.status_code, 200)
            self.assertEqual(download_response.text, artifact_body)
            self.assertEqual(detail_payload["task_export_url"], f"/api/artifacts/export?task_id={task_id}")
            self.assertEqual(detail_payload["session_export_url"], f"/api/artifacts/export?session_id={session_id}")

    def test_artifact_export_api_returns_task_bundle_with_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Artifacts Export Test",
                description="Artifacts export test",
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
                    ("agent_artifact_export", project_id, "Artifact Export Agent"),
                )
                task_id = "task_artifact_export"
                connection.execute(
                    """
                    INSERT INTO tasks (
                        task_id, project_id, title, description, status, priority, acceptance_criteria_json
                    ) VALUES (?, ?, 'Artifact export task', '', 'ready', 60, '[]')
                    """,
                    (task_id, project_id),
                )
                grant_task_capabilities(
                    connection,
                    project_id,
                    task_id,
                    "agent_artifact_export",
                    TASK_EXECUTION_CAPABILITIES,
                    granted_by="test_setup",
                )
                connection.commit()

                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_export",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting artifact export test",
                )
                exportable_path = os.path.join(result["paths"].artifacts_dir, "exportable.txt")
                with open(exportable_path, "w", encoding="utf-8") as handle:
                    handle.write("export me\n")
                produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    artifact_type="note",
                    path=exportable_path,
                )
                missing_path = os.path.join(result["paths"].artifacts_dir, "missing-export.txt")
                with open(missing_path, "w", encoding="utf-8") as handle:
                    handle.write("gone\n")
                produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    artifact_type="provider_report",
                    path=missing_path,
                )
                os.remove(missing_path)
                connection.commit()
            finally:
                connection.close()

            response = TestClient(create_app(tmpdir)).get(f"/api/artifacts/export?task_id={task_id}")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["content-type"], "application/zip")
            self.assertIn(f'task-{task_id}-artifacts.zip', response.headers["content-disposition"])

            with tempfile.NamedTemporaryFile(suffix=".zip") as handle:
                handle.write(response.content)
                handle.flush()
                with zipfile.ZipFile(handle.name) as archive:
                    names = set(archive.namelist())
                    self.assertIn("manifest.json", names)
                    exported_artifacts = [name for name in names if name.startswith("artifacts/")]
                    self.assertEqual(len(exported_artifacts), 1)
                    manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

            self.assertEqual(manifest["scope_type"], "task")
            self.assertEqual(manifest["scope_id"], task_id)
            self.assertEqual(manifest["artifact_count"], 2)
            included_entries = [entry for entry in manifest["artifacts"] if entry["included"]]
            skipped_entries = [entry for entry in manifest["artifacts"] if not entry["included"]]
            self.assertEqual(len(included_entries), 1)
            self.assertEqual(included_entries[0]["file_name"], "exportable.txt")
            self.assertEqual(len(skipped_entries), 1)
            self.assertEqual(skipped_entries[0]["reason"], "missing_file")

    def test_artifact_export_api_rejects_invalid_scope(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(
                tmpdir,
                name="Artifacts Export Scope Test",
                description="Artifacts export scope test",
                project_type="custom",
            )
            client = TestClient(create_app(tmpdir))

            response = client.get("/api/artifacts/export")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["detail"], "exactly one export scope is required")

            response = client.get("/api/artifacts/export?task_id=t1&session_id=s1")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["detail"], "exactly one export scope is required")

    def test_artifact_purge_api_removes_scope_rows_and_local_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Artifacts Purge Test",
                description="Artifacts purge test",
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
                    ("agent_artifact_purge", project_id, "Artifact Purge Agent"),
                )
                task_id = "task_artifact_purge"
                connection.execute(
                    """
                    INSERT INTO tasks (
                        task_id, project_id, title, description, status, priority, acceptance_criteria_json
                    ) VALUES (?, ?, 'Artifact purge task', '', 'ready', 60, '[]')
                    """,
                    (task_id, project_id),
                )
                grant_task_capabilities(
                    connection,
                    project_id,
                    task_id,
                    "agent_artifact_purge",
                    TASK_EXECUTION_CAPABILITIES,
                    granted_by="test_setup",
                )
                connection.commit()

                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_purge",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting artifact purge test",
                )
                first_path = os.path.join(result["paths"].artifacts_dir, "purge-first.txt")
                with open(first_path, "w", encoding="utf-8") as handle:
                    handle.write("purge first\n")
                produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    artifact_type="note",
                    path=first_path,
                )
                missing_path = os.path.join(result["paths"].artifacts_dir, "purge-missing.txt")
                with open(missing_path, "w", encoding="utf-8") as handle:
                    handle.write("gone\n")
                produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    artifact_type="provider_report",
                    path=missing_path,
                )
                os.remove(missing_path)
                external_path = os.path.join(tmpdir, "external-preserved.txt")
                with open(external_path, "w", encoding="utf-8") as handle:
                    handle.write("keep external\n")
                produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    artifact_type="note",
                    path=external_path,
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.post(f"/api/tasks/{task_id}/artifacts/actions/purge", json={"actor_id": "agent_artifact_purge"})

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["scope_type"], "task")
            self.assertEqual(payload["scope_id"], task_id)
            self.assertEqual(payload["deleted_artifact_count"], 3)
            self.assertEqual(payload["deleted_file_count"], 1)
            self.assertEqual(payload["missing_file_count"], 1)
            self.assertEqual(payload["preserved_path_count"], 1)
            self.assertFalse(os.path.exists(first_path))
            self.assertTrue(os.path.exists(external_path))

            connection = connect(project_paths(tmpdir))
            try:
                remaining_count = connection.execute("SELECT COUNT(*) AS count FROM artifacts WHERE task_id = ?", (task_id,)).fetchone()[
                    "count"
                ]
            finally:
                connection.close()
            self.assertEqual(remaining_count, 0)

    def test_artifact_purge_api_rejects_open_quarantine_scope(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Artifacts Purge Quarantine Test",
                description="Artifacts purge quarantine test",
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
                    ("agent_artifact_purge_quarantine", project_id, "Artifact Purge Quarantine Agent"),
                )
                task_id = "task_artifact_purge_quarantine"
                connection.execute(
                    """
                    INSERT INTO tasks (
                        task_id, project_id, title, description, status, priority, acceptance_criteria_json
                    ) VALUES (?, ?, 'Artifact purge quarantine task', '', 'ready', 60, '[]')
                    """,
                    (task_id, project_id),
                )
                grant_task_capabilities(
                    connection,
                    project_id,
                    task_id,
                    "agent_artifact_purge_quarantine",
                    TASK_EXECUTION_CAPABILITIES,
                    granted_by="test_setup",
                )
                connection.commit()

                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_purge_quarantine",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting artifact purge quarantine test",
                )
                artifact_path = os.path.join(result["paths"].artifacts_dir, "purge-quarantine.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("quarantine\n")
                produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    artifact_type="provider_report",
                    path=artifact_path,
                )
                end_session(
                    connection,
                    session_id,
                    "failed",
                    "Artifact purge quarantine failure",
                    project_paths=result["paths"],
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.post(
                f"/api/sessions/{session_id}/artifacts/actions/purge",
                json={"actor_id": "agent_artifact_purge_quarantine"},
            )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["detail"], "Cannot purge artifacts from an open quarantine incident")

    def test_artifact_detail_api_marks_missing_preview_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(
                tmpdir,
                name="Artifacts Missing Detail Test",
                description="Artifacts missing detail test",
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
                    ("agent_artifact_missing_detail", project_id, "Artifact Missing Detail Agent"),
                )
                task_id = "task_artifact_missing_detail"
                connection.execute(
                    """
                    INSERT INTO tasks (
                        task_id, project_id, title, description, status, priority, acceptance_criteria_json
                    ) VALUES (?, ?, 'Artifact missing detail task', '', 'ready', 60, '[]')
                    """,
                    (task_id, project_id),
                )
                grant_task_capabilities(
                    connection,
                    project_id,
                    task_id,
                    "agent_artifact_missing_detail",
                    TASK_EXECUTION_CAPABILITIES,
                    granted_by="test_setup",
                )
                connection.commit()

                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_missing_detail",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting artifact missing detail test",
                )
                artifact_path = os.path.join(tmpdir, "missing-detail-artifact.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("missing soon\n")
                artifact_id = produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    artifact_type="note",
                    path=artifact_path,
                )
                os.remove(artifact_path)
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))

            detail_response = client.get(f"/api/artifacts/{artifact_id}")
            self.assertEqual(detail_response.status_code, 200)
            detail_payload = detail_response.json()
            self.assertEqual(detail_payload["preview"]["kind"], "unavailable")
            self.assertEqual(detail_payload["preview"]["reason"], "missing_file")
            self.assertIsNone(detail_payload["download_url"])

            download_response = client.get(f"/api/artifacts/{artifact_id}/download")
            self.assertEqual(download_response.status_code, 404)

    def test_artifact_detail_api_does_not_expose_download_for_external_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(
                tmpdir,
                name="Artifacts External Download Test",
                description="Artifacts external download test",
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
                    ("agent_artifact_external_download", project_id, "Artifact External Download Agent"),
                )
                task_id = "task_artifact_external_download"
                connection.execute(
                    """
                    INSERT INTO tasks (
                        task_id, project_id, title, description, status, priority, acceptance_criteria_json
                    ) VALUES (?, ?, 'Artifact external download task', '', 'ready', 60, '[]')
                    """,
                    (task_id, project_id),
                )
                grant_task_capabilities(
                    connection,
                    project_id,
                    task_id,
                    "agent_artifact_external_download",
                    TASK_EXECUTION_CAPABILITIES,
                    granted_by="test_setup",
                )
                connection.commit()

                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_external_download",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting external download test",
                )
                artifact_path = os.path.join(tempfile.gettempdir(), "external-download-artifact.txt")
                with open(artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("external artifact\n")
                artifact_id = produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    artifact_type="note",
                    path=artifact_path,
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))

            detail_response = client.get(f"/api/artifacts/{artifact_id}")
            self.assertEqual(detail_response.status_code, 200)
            detail_payload = detail_response.json()
            self.assertIsNone(detail_payload["download_url"])
            self.assertIsNone(detail_payload["download_content_type"])

            download_response = client.get(f"/api/artifacts/{artifact_id}/download")
            self.assertEqual(download_response.status_code, 404)

            os.remove(artifact_path)

    def test_artifact_detail_api_does_not_expose_download_for_directory_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Artifacts Directory Download Test",
                description="Artifacts directory download test",
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
                    ("agent_artifact_directory_download", project_id, "Artifact Directory Download Agent"),
                )
                task_id = "task_artifact_directory_download"
                connection.execute(
                    """
                    INSERT INTO tasks (
                        task_id, project_id, title, description, status, priority, acceptance_criteria_json
                    ) VALUES (?, ?, 'Artifact directory download task', '', 'ready', 60, '[]')
                    """,
                    (task_id, project_id),
                )
                grant_task_capabilities(
                    connection,
                    project_id,
                    task_id,
                    "agent_artifact_directory_download",
                    TASK_EXECUTION_CAPABILITIES,
                    granted_by="test_setup",
                )
                connection.commit()

                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_directory_download",
                    task_id=task_id,
                    provider_type="python_script",
                    status_message="Starting directory download test",
                )
                artifact_dir_path = os.path.join(result["paths"].artifacts_dir, "directory-artifact")
                os.makedirs(artifact_dir_path, exist_ok=True)
                artifact_id = produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id=task_id,
                    artifact_type="note",
                    path=artifact_dir_path,
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))

            detail_response = client.get(f"/api/artifacts/{artifact_id}")
            self.assertEqual(detail_response.status_code, 200)
            detail_payload = detail_response.json()
            self.assertTrue(detail_payload["exists"])
            self.assertEqual(detail_payload["preview"]["kind"], "unavailable")
            self.assertEqual(detail_payload["preview"]["reason"], "not_a_file")
            self.assertIsNone(detail_payload["download_url"])

            download_response = client.get(f"/api/artifacts/{artifact_id}/download")
            self.assertEqual(download_response.status_code, 404)

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

    def test_artifacts_api_rejects_invalid_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(
                tmpdir,
                name="Artifacts Limit Test",
                description="Artifacts limit test",
                project_type="custom",
            )

            response = TestClient(create_app(tmpdir)).get("/api/artifacts?limit=abc")

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["detail"], "limit must be an integer")

    def test_artifacts_api_supports_server_side_filters_and_pagination(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Artifacts Filter Test",
                description="Artifacts filter test",
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
                    ("agent_artifact_filter", project_id, "Artifact Filter Agent"),
                )
                for index in range(3):
                    task_id = f"task_artifact_filter_{index}"
                    connection.execute(
                        """
                        INSERT INTO tasks (
                            task_id, project_id, title, description, status, priority, acceptance_criteria_json
                        ) VALUES (?, ?, ?, '', 'ready', 60, '[]')
                        """,
                        (task_id, project_id, f"Artifact filter task {index}"),
                    )
                    grant_task_capabilities(
                        connection,
                        project_id,
                        task_id,
                        "agent_artifact_filter",
                        TASK_EXECUTION_CAPABILITIES,
                        granted_by="test_setup",
                    )
                    session_id = start_session(
                        connection,
                        project_id=project_id,
                        agent_id="agent_artifact_filter",
                        task_id=task_id,
                        provider_type="python_script",
                        status_message=f"Starting artifact filter task {index}",
                    )
                    artifact_path = os.path.join(result["paths"].artifacts_dir, f"filter-artifact-{index}.txt")
                    with open(artifact_path, "w", encoding="utf-8") as handle:
                        handle.write(f"filter {index}\n")
                    produce_artifact(
                        connection,
                        project_id=project_id,
                        session_id=session_id,
                        task_id=task_id,
                        artifact_type="note" if index < 2 else "provider_report",
                        path=artifact_path,
                    )
                    if index == 0:
                        end_session(
                            connection,
                            session_id,
                            "failed",
                            "Filtered quarantined artifact",
                            project_paths=result["paths"],
                        )
                    elif index == 1:
                        os.remove(artifact_path)
                        end_session(connection, session_id, "completed", "Completed missing-file artifact")
                    else:
                        end_session(connection, session_id, "completed", "Completed artifact")
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))

            filtered_payload = client.get(
                "/api/artifacts?state=quarantined&artifact_type=note&search=filter-artifact&limit=1"
            ).json()
            self.assertEqual(filtered_payload["filtered_count"], 1)
            self.assertEqual(len(filtered_payload["items"]), 1)
            self.assertEqual(filtered_payload["items"][0]["artifact_state"], "quarantined")
            self.assertEqual(filtered_payload["selected_filters"]["state"], "quarantined")
            self.assertEqual(filtered_payload["selected_filters"]["artifact_type"], "note")

            missing_payload = client.get("/api/artifacts?missing_only=true&limit=1&offset=0").json()
            self.assertEqual(missing_payload["filtered_count"], 1)
            self.assertFalse(missing_payload["items"][0]["exists"])
            self.assertTrue(missing_payload["selected_filters"]["missing_only"])

            session_id = filtered_payload["items"][0]["session_id"]
            session_payload = client.get(f"/api/artifacts?session_id={session_id}").json()
            self.assertEqual(session_payload["filtered_count"], 1)
            self.assertEqual(session_payload["items"][0]["session_id"], session_id)
            self.assertEqual(session_payload["selected_filters"]["session_id"], session_id)

    def test_artifacts_api_exposes_quarantine_operator_actions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Artifacts Action Test",
                description="Artifacts action test",
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
                    ("agent_artifact_actions", project_id, "Artifact Actions Agent"),
                )

                task_specs = (
                    ("task_artifact_requeue", "Recoverable quarantined task"),
                    ("task_artifact_restore", "Restore-only quarantined task"),
                    ("task_artifact_reopen", "Dismissed quarantined task"),
                )
                for task_id, title in task_specs:
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
                        "agent_artifact_actions",
                        TASK_EXECUTION_CAPABILITIES,
                        granted_by="test_setup",
                    )

                requeue_session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_actions",
                    task_id="task_artifact_requeue",
                    provider_type="python_script",
                    status_message="Starting recoverable quarantine test",
                )
                requeue_artifact_path = os.path.join(result["paths"].artifacts_dir, "artifact-requeue.txt")
                with open(requeue_artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("recoverable\n")
                produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=requeue_session_id,
                    task_id="task_artifact_requeue",
                    artifact_type="provider_report",
                    path=requeue_artifact_path,
                )
                end_session(
                    connection,
                    requeue_session_id,
                    "failed",
                    "Recoverable quarantine failure",
                    project_paths=result["paths"],
                )

                restore_session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_actions",
                    task_id="task_artifact_restore",
                    provider_type="python_script",
                    status_message="Starting nonrecoverable quarantine test",
                )
                restore_artifact_path = os.path.join(result["paths"].artifacts_dir, "artifact-restore.txt")
                with open(restore_artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("restore-only\n")
                produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=restore_session_id,
                    task_id="task_artifact_restore",
                    artifact_type="provider_report",
                    path=restore_artifact_path,
                )
                end_session(
                    connection,
                    restore_session_id,
                    "failed",
                    "Restore-only quarantine failure",
                    project_paths=result["paths"],
                )
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'review', review_state = NULL
                    WHERE task_id = 'task_artifact_restore'
                    """
                )

                reopen_session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_actions",
                    task_id="task_artifact_reopen",
                    provider_type="python_script",
                    status_message="Starting dismissed quarantine test",
                )
                reopen_artifact_path = os.path.join(result["paths"].artifacts_dir, "artifact-reopen.txt")
                with open(reopen_artifact_path, "w", encoding="utf-8") as handle:
                    handle.write("reopen\n")
                produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=reopen_session_id,
                    task_id="task_artifact_reopen",
                    artifact_type="provider_report",
                    path=reopen_artifact_path,
                )
                end_session(
                    connection,
                    reopen_session_id,
                    "failed",
                    "Dismissed quarantine failure",
                    project_paths=result["paths"],
                )
                connection.execute(
                    "UPDATE quarantine_queue SET status = 'dismissed' WHERE session_id = ?",
                    (reopen_session_id,),
                )
                connection.commit()
            finally:
                connection.close()

            payload = TestClient(create_app(tmpdir)).get("/api/artifacts?state=quarantined&limit=10").json()

            artifacts_by_task = {item["task_id"]: item for item in payload["items"]}

            requeue_item = artifacts_by_task["task_artifact_requeue"]
            self.assertEqual(requeue_item["quarantine_queue_status"], "open")
            self.assertEqual(requeue_item["operator_action"]["action"], "restore_and_requeue_quarantine_entry")
            self.assertEqual(requeue_item["secondary_operator_action"]["action"], "dismiss_quarantine_entry")

            restore_item = artifacts_by_task["task_artifact_restore"]
            self.assertEqual(restore_item["quarantine_queue_status"], "open")
            self.assertEqual(restore_item["operator_action"]["action"], "restore_quarantine_entry")
            self.assertEqual(restore_item["secondary_operator_action"]["action"], "dismiss_quarantine_entry")

            reopen_item = artifacts_by_task["task_artifact_reopen"]
            self.assertEqual(reopen_item["quarantine_queue_status"], "dismissed")
            self.assertEqual(reopen_item["operator_action"]["action"], "reopen_quarantine_entry")
            self.assertIsNone(reopen_item.get("secondary_operator_action"))

    def test_artifact_detail_api_exposes_related_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Artifacts Related Test",
                description="Artifacts related test",
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
                    ("agent_artifact_related", project_id, "Artifact Related Agent"),
                )
                connection.execute(
                    """
                    INSERT INTO tasks (
                        task_id, project_id, title, description, status, priority, acceptance_criteria_json
                    ) VALUES
                        ('task_artifact_related', ?, 'Artifact related task', '', 'ready', 60, '[]'),
                        ('task_artifact_unrelated', ?, 'Artifact unrelated task', '', 'ready', 60, '[]')
                    """,
                    (project_id, project_id),
                )
                for task_id in ("task_artifact_related", "task_artifact_unrelated"):
                    grant_task_capabilities(
                        connection,
                        project_id,
                        task_id,
                        "agent_artifact_related",
                        TASK_EXECUTION_CAPABILITIES,
                        granted_by="test_setup",
                    )
                connection.commit()

                first_session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_related",
                    task_id="task_artifact_related",
                    provider_type="python_script",
                    status_message="Starting first related artifact",
                )
                first_path = os.path.join(result["paths"].artifacts_dir, "related-first.txt")
                with open(first_path, "w", encoding="utf-8") as handle:
                    handle.write("first\n")
                first_artifact_id = produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=first_session_id,
                    task_id="task_artifact_related",
                    artifact_type="note",
                    path=first_path,
                )
                end_session(connection, first_session_id, "completed", "Completed first related artifact")
                connection.execute(
                    "UPDATE tasks SET status = 'ready', review_state = NULL WHERE task_id = 'task_artifact_related'"
                )
                grant_task_capabilities(
                    connection,
                    project_id,
                    "task_artifact_related",
                    "agent_artifact_related",
                    TASK_EXECUTION_CAPABILITIES,
                    granted_by="test_setup",
                )

                second_session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_related",
                    task_id="task_artifact_related",
                    provider_type="python_script",
                    status_message="Starting second related artifact",
                )
                second_path = os.path.join(result["paths"].artifacts_dir, "related-second.txt")
                with open(second_path, "w", encoding="utf-8") as handle:
                    handle.write("second\n")
                second_artifact_id = produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=second_session_id,
                    task_id="task_artifact_related",
                    artifact_type="provider_report",
                    path=second_path,
                )
                end_session(connection, second_session_id, "completed", "Completed second related artifact")

                unrelated_session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_related",
                    task_id="task_artifact_unrelated",
                    provider_type="python_script",
                    status_message="Starting unrelated artifact",
                )
                unrelated_path = os.path.join(result["paths"].artifacts_dir, "unrelated.txt")
                with open(unrelated_path, "w", encoding="utf-8") as handle:
                    handle.write("unrelated\n")
                produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=unrelated_session_id,
                    task_id="task_artifact_unrelated",
                    artifact_type="note",
                    path=unrelated_path,
                )
                connection.commit()
            finally:
                connection.close()

            payload = TestClient(create_app(tmpdir)).get(f"/api/artifacts/{first_artifact_id}").json()

            self.assertEqual(payload["artifact_id"], first_artifact_id)
            related_ids = [entry["artifact_id"] for entry in payload["related_artifacts"]]
            self.assertIn(second_artifact_id, related_ids)
            self.assertNotIn(first_artifact_id, related_ids)
            self.assertEqual(len(related_ids), 1)
            self.assertEqual(payload["lineage_summary"]["task_artifact_count"], 2)
            self.assertEqual(payload["lineage_summary"]["session_artifact_count"], 1)
            self.assertEqual(payload["session_artifacts"], [])

    def test_artifact_detail_api_exposes_session_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Artifacts Session Lineage Test",
                description="Artifacts session lineage test",
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
                    ("agent_artifact_session_lineage", project_id, "Artifact Session Lineage Agent"),
                )
                connection.execute(
                    """
                    INSERT INTO tasks (
                        task_id, project_id, title, description, status, priority, acceptance_criteria_json
                    ) VALUES (?, ?, 'Artifact session lineage task', '', 'ready', 60, '[]')
                    """,
                    ("task_artifact_session_lineage", project_id),
                )
                grant_task_capabilities(
                    connection,
                    project_id,
                    "task_artifact_session_lineage",
                    "agent_artifact_session_lineage",
                    TASK_EXECUTION_CAPABILITIES,
                    granted_by="test_setup",
                )
                connection.commit()

                session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_session_lineage",
                    task_id="task_artifact_session_lineage",
                    provider_type="python_script",
                    status_message="Starting session lineage artifact",
                )
                first_path = os.path.join(result["paths"].artifacts_dir, "session-lineage-first.txt")
                with open(first_path, "w", encoding="utf-8") as handle:
                    handle.write("session first\n")
                first_artifact_id = produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id="task_artifact_session_lineage",
                    artifact_type="note",
                    path=first_path,
                )
                second_path = os.path.join(result["paths"].artifacts_dir, "session-lineage-second.txt")
                with open(second_path, "w", encoding="utf-8") as handle:
                    handle.write("session second\n")
                second_artifact_id = produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    task_id="task_artifact_session_lineage",
                    artifact_type="provider_report",
                    path=second_path,
                )
                connection.commit()
            finally:
                connection.close()

            payload = TestClient(create_app(tmpdir)).get(f"/api/artifacts/{first_artifact_id}").json()

            self.assertEqual(payload["lineage_summary"]["task_artifact_count"], 2)
            self.assertEqual(payload["lineage_summary"]["session_artifact_count"], 2)
            self.assertEqual(len(payload["session_artifacts"]), 1)
            self.assertEqual(payload["session_artifacts"][0]["artifact_id"], second_artifact_id)
            self.assertEqual(payload["session_artifacts"][0]["session_id"], session_id)

    def test_artifact_detail_api_exposes_dependency_linked_task_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Artifacts Dependency Lineage Test",
                description="Artifacts dependency lineage test",
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
                    ("agent_artifact_dependency_lineage", project_id, "Artifact Dependency Lineage Agent"),
                )
                for task_id, title in (
                    ("task_artifact_upstream", "Artifact upstream task"),
                    ("task_artifact_focus", "Artifact focus task"),
                    ("task_artifact_downstream", "Artifact downstream task"),
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
                        "agent_artifact_dependency_lineage",
                        TASK_EXECUTION_CAPABILITIES,
                        granted_by="test_setup",
                    )

                connection.execute(
                    """
                    INSERT INTO task_dependencies (
                        dependency_id, project_id, source_task_id, target_task_id, dependency_type
                    ) VALUES (?, ?, 'task_artifact_upstream', 'task_artifact_focus', 'blocks')
                    """,
                    (generate_id("dep"), project_id),
                )
                connection.execute(
                    """
                    INSERT INTO task_dependencies (
                        dependency_id, project_id, source_task_id, target_task_id, dependency_type
                    ) VALUES (?, ?, 'task_artifact_focus', 'task_artifact_downstream', 'informs')
                    """,
                    (generate_id("dep"), project_id),
                )
                connection.commit()

                upstream_session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_dependency_lineage",
                    task_id="task_artifact_upstream",
                    provider_type="python_script",
                    status_message="Starting upstream artifact",
                )
                upstream_path = os.path.join(result["paths"].artifacts_dir, "dependency-upstream.txt")
                with open(upstream_path, "w", encoding="utf-8") as handle:
                    handle.write("upstream\n")
                produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=upstream_session_id,
                    task_id="task_artifact_upstream",
                    artifact_type="note",
                    path=upstream_path,
                )
                end_session(connection, upstream_session_id, "completed", "Completed upstream artifact")
                connection.execute(
                    "UPDATE tasks SET status = 'ready', review_state = NULL WHERE task_id = 'task_artifact_focus'"
                )
                grant_task_capabilities(
                    connection,
                    project_id,
                    "task_artifact_focus",
                    "agent_artifact_dependency_lineage",
                    TASK_EXECUTION_CAPABILITIES,
                    granted_by="test_setup",
                )

                focus_session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_dependency_lineage",
                    task_id="task_artifact_focus",
                    provider_type="python_script",
                    status_message="Starting focus artifact",
                )
                focus_path = os.path.join(result["paths"].artifacts_dir, "dependency-focus.txt")
                with open(focus_path, "w", encoding="utf-8") as handle:
                    handle.write("focus\n")
                focus_artifact_id = produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=focus_session_id,
                    task_id="task_artifact_focus",
                    artifact_type="provider_report",
                    path=focus_path,
                )
                end_session(connection, focus_session_id, "completed", "Completed focus artifact")
                connection.execute(
                    "UPDATE tasks SET status = 'ready', review_state = NULL WHERE task_id = 'task_artifact_downstream'"
                )
                grant_task_capabilities(
                    connection,
                    project_id,
                    "task_artifact_downstream",
                    "agent_artifact_dependency_lineage",
                    TASK_EXECUTION_CAPABILITIES,
                    granted_by="test_setup",
                )

                downstream_session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_dependency_lineage",
                    task_id="task_artifact_downstream",
                    provider_type="python_script",
                    status_message="Starting downstream artifact",
                )
                downstream_path = os.path.join(result["paths"].artifacts_dir, "dependency-downstream.txt")
                with open(downstream_path, "w", encoding="utf-8") as handle:
                    handle.write("downstream\n")
                produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=downstream_session_id,
                    task_id="task_artifact_downstream",
                    artifact_type="note",
                    path=downstream_path,
                )
                connection.commit()
            finally:
                connection.close()

            payload = TestClient(create_app(tmpdir)).get(f"/api/artifacts/{focus_artifact_id}").json()

            self.assertEqual(len(payload["upstream_task_artifacts"]), 1)
            self.assertEqual(payload["upstream_task_artifacts"][0]["task_id"], "task_artifact_upstream")
            self.assertEqual(payload["upstream_task_artifacts"][0]["dependency_type"], "blocks")
            self.assertEqual(payload["upstream_task_artifacts"][0]["artifact_count"], 1)
            self.assertEqual(
                payload["upstream_task_artifacts"][0]["recent_artifacts"][0]["file_name"],
                "dependency-upstream.txt",
            )

            self.assertEqual(len(payload["downstream_task_artifacts"]), 1)
            self.assertEqual(payload["downstream_task_artifacts"][0]["task_id"], "task_artifact_downstream")
            self.assertEqual(payload["downstream_task_artifacts"][0]["dependency_type"], "informs")
            self.assertEqual(payload["downstream_task_artifacts"][0]["artifact_count"], 1)
            self.assertEqual(
                payload["downstream_task_artifacts"][0]["recent_artifacts"][0]["file_name"],
                "dependency-downstream.txt",
            )

    def test_artifact_compare_api_returns_unified_diff_for_text_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Artifacts Compare Test",
                description="Artifacts compare test",
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
                    ("agent_artifact_compare", project_id, "Artifact Compare Agent"),
                )
                connection.execute(
                    """
                    INSERT INTO tasks (
                        task_id, project_id, title, description, status, priority, acceptance_criteria_json
                    ) VALUES (?, ?, 'Artifact compare task', '', 'ready', 60, '[]')
                    """,
                    ("task_artifact_compare", project_id),
                )
                grant_task_capabilities(
                    connection,
                    project_id,
                    "task_artifact_compare",
                    "agent_artifact_compare",
                    TASK_EXECUTION_CAPABILITIES,
                    granted_by="test_setup",
                )
                connection.commit()

                left_session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_compare",
                    task_id="task_artifact_compare",
                    provider_type="python_script",
                    status_message="Starting left artifact",
                )
                left_path = os.path.join(result["paths"].artifacts_dir, "compare-left.txt")
                with open(left_path, "w", encoding="utf-8") as handle:
                    handle.write("alpha\nbeta\n")
                left_artifact_id = produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=left_session_id,
                    task_id="task_artifact_compare",
                    artifact_type="note",
                    path=left_path,
                )
                end_session(connection, left_session_id, "completed", "Completed left artifact")
                connection.execute(
                    "UPDATE tasks SET status = 'ready', review_state = NULL WHERE task_id = 'task_artifact_compare'"
                )
                grant_task_capabilities(
                    connection,
                    project_id,
                    "task_artifact_compare",
                    "agent_artifact_compare",
                    TASK_EXECUTION_CAPABILITIES,
                    granted_by="test_setup",
                )

                right_session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_compare",
                    task_id="task_artifact_compare",
                    provider_type="python_script",
                    status_message="Starting right artifact",
                )
                right_path = os.path.join(result["paths"].artifacts_dir, "compare-right.txt")
                with open(right_path, "w", encoding="utf-8") as handle:
                    handle.write("alpha\ngamma\n")
                right_artifact_id = produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=right_session_id,
                    task_id="task_artifact_compare",
                    artifact_type="note",
                    path=right_path,
                )
                connection.commit()
            finally:
                connection.close()

            payload = TestClient(create_app(tmpdir)).get(
                f"/api/artifacts/{left_artifact_id}/compare/{right_artifact_id}"
            ).json()

            self.assertTrue(payload["comparable"])
            self.assertEqual(payload["left"]["artifact_id"], left_artifact_id)
            self.assertEqual(payload["right"]["artifact_id"], right_artifact_id)
            self.assertIn("--- compare-left.txt", payload["unified_diff"])
            self.assertIn("+++ compare-right.txt", payload["unified_diff"])
            self.assertIn("-beta", payload["unified_diff"])
            self.assertIn("+gamma", payload["unified_diff"])

    def test_artifact_compare_api_reports_preview_unavailable_for_binary_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Artifacts Compare Binary Test",
                description="Artifacts compare binary test",
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
                    ("agent_artifact_compare_binary", project_id, "Artifact Compare Binary Agent"),
                )
                connection.execute(
                    """
                    INSERT INTO tasks (
                        task_id, project_id, title, description, status, priority, acceptance_criteria_json
                    ) VALUES (?, ?, 'Artifact compare binary task', '', 'ready', 60, '[]')
                    """,
                    ("task_artifact_compare_binary", project_id),
                )
                grant_task_capabilities(
                    connection,
                    project_id,
                    "task_artifact_compare_binary",
                    "agent_artifact_compare_binary",
                    TASK_EXECUTION_CAPABILITIES,
                    granted_by="test_setup",
                )
                connection.commit()

                text_session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_compare_binary",
                    task_id="task_artifact_compare_binary",
                    provider_type="python_script",
                    status_message="Starting text artifact",
                )
                text_path = os.path.join(result["paths"].artifacts_dir, "compare-text.txt")
                with open(text_path, "w", encoding="utf-8") as handle:
                    handle.write("plain text\n")
                text_artifact_id = produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=text_session_id,
                    task_id="task_artifact_compare_binary",
                    artifact_type="note",
                    path=text_path,
                )
                end_session(connection, text_session_id, "completed", "Completed text artifact")
                connection.execute(
                    "UPDATE tasks SET status = 'ready', review_state = NULL WHERE task_id = 'task_artifact_compare_binary'"
                )
                grant_task_capabilities(
                    connection,
                    project_id,
                    "task_artifact_compare_binary",
                    "agent_artifact_compare_binary",
                    TASK_EXECUTION_CAPABILITIES,
                    granted_by="test_setup",
                )

                binary_session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_compare_binary",
                    task_id="task_artifact_compare_binary",
                    provider_type="python_script",
                    status_message="Starting binary artifact",
                )
                binary_path = os.path.join(result["paths"].artifacts_dir, "compare-binary.bin")
                with open(binary_path, "wb") as handle:
                    handle.write(b"\x00binary")
                binary_artifact_id = produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=binary_session_id,
                    task_id="task_artifact_compare_binary",
                    artifact_type="provider_report",
                    path=binary_path,
                )
                connection.commit()
            finally:
                connection.close()

            payload = TestClient(create_app(tmpdir)).get(
                f"/api/artifacts/{text_artifact_id}/compare/{binary_artifact_id}"
            ).json()

            self.assertFalse(payload["comparable"])
            self.assertEqual(payload["reason"], "preview_unavailable")
            self.assertIsNone(payload["unified_diff"])
            self.assertEqual(payload["right"]["preview"]["reason"], "binary_file")

    def test_artifact_compare_api_marks_preview_truncation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Artifacts Compare Truncation Test",
                description="Artifacts compare truncation test",
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
                    ("agent_artifact_compare_truncated", project_id, "Artifact Compare Truncated Agent"),
                )
                connection.execute(
                    """
                    INSERT INTO tasks (
                        task_id, project_id, title, description, status, priority, acceptance_criteria_json
                    ) VALUES (?, ?, 'Artifact compare truncation task', '', 'ready', 60, '[]')
                    """,
                    ("task_artifact_compare_truncated", project_id),
                )
                grant_task_capabilities(
                    connection,
                    project_id,
                    "task_artifact_compare_truncated",
                    "agent_artifact_compare_truncated",
                    TASK_EXECUTION_CAPABILITIES,
                    granted_by="test_setup",
                )
                connection.commit()

                left_session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_compare_truncated",
                    task_id="task_artifact_compare_truncated",
                    provider_type="python_script",
                    status_message="Starting left truncated artifact",
                )
                prefix = "a" * ARTIFACT_PREVIEW_MAX_BYTES
                left_path = os.path.join(result["paths"].artifacts_dir, "compare-truncated-left.txt")
                with open(left_path, "w", encoding="utf-8") as handle:
                    handle.write(prefix + "left-tail\n")
                left_artifact_id = produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=left_session_id,
                    task_id="task_artifact_compare_truncated",
                    artifact_type="note",
                    path=left_path,
                )
                end_session(connection, left_session_id, "completed", "Completed left truncated artifact")
                connection.execute(
                    "UPDATE tasks SET status = 'ready', review_state = NULL WHERE task_id = 'task_artifact_compare_truncated'"
                )
                grant_task_capabilities(
                    connection,
                    project_id,
                    "task_artifact_compare_truncated",
                    "agent_artifact_compare_truncated",
                    TASK_EXECUTION_CAPABILITIES,
                    granted_by="test_setup",
                )

                right_session_id = start_session(
                    connection,
                    project_id=project_id,
                    agent_id="agent_artifact_compare_truncated",
                    task_id="task_artifact_compare_truncated",
                    provider_type="python_script",
                    status_message="Starting right truncated artifact",
                )
                right_path = os.path.join(result["paths"].artifacts_dir, "compare-truncated-right.txt")
                with open(right_path, "w", encoding="utf-8") as handle:
                    handle.write(prefix + "right-tail\n")
                right_artifact_id = produce_artifact(
                    connection,
                    project_id=project_id,
                    session_id=right_session_id,
                    task_id="task_artifact_compare_truncated",
                    artifact_type="note",
                    path=right_path,
                )
                connection.commit()
            finally:
                connection.close()

            payload = TestClient(create_app(tmpdir)).get(
                f"/api/artifacts/{left_artifact_id}/compare/{right_artifact_id}"
            ).json()

            self.assertTrue(payload["comparable"])
            self.assertTrue(payload["truncated"])
            self.assertEqual(payload["unified_diff"], "")

    def test_artifacts_api_rejects_invalid_offset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(
                tmpdir,
                name="Artifacts Offset Test",
                description="Artifacts offset test",
                project_type="custom",
            )

            response = TestClient(create_app(tmpdir)).get("/api/artifacts?offset=-1")

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["detail"], "offset must be zero or greater")


if __name__ == "__main__":
    unittest.main()
