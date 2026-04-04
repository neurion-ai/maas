import json
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.ids import generate_id
from maas.services.bootstrap import bootstrap_project
from maas.services.projects import create_project
from maas.services.provider_runtime import queue_provider_task
from maas.services.security import TASK_EXECUTION_CAPABILITIES, grant_task_capabilities


def _insert_assigned_task(connection, project_id, goal_id, agent_id, title):
    task_id = generate_id("task")
    connection.execute(
        """
        INSERT INTO tasks (
            task_id, project_id, goal_id, title, description, status, priority, assigned_agent_id, acceptance_criteria_json
        ) VALUES (?, ?, ?, ?, '', 'assigned', 70, ?, '[]')
        """,
        (task_id, project_id, goal_id, title, agent_id),
    )
    grant_task_capabilities(
        connection,
        project_id,
        task_id,
        agent_id,
        TASK_EXECUTION_CAPABILITIES,
        granted_by="test_setup",
    )
    return task_id


class ProviderJobQueueApiTest(unittest.TestCase):
    def test_queue_task_creates_job_and_provider_overview_exposes_it(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Job Test", description="Provider job test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(connection, project_id, goal_id, "agent_reviewer", "Queue Python provider run")
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.post(
                "/api/providers/python_script/actions/queue-task",
                json={
                    "actor_id": "agent_allocator",
                    "project_id": project_id,
                    "agent_id": "agent_reviewer",
                    "task_id": task_id,
                },
            )

            self.assertEqual(response.status_code, 200)
            queued_job = response.json()
            self.assertEqual(queued_job["status"], "queued")

            providers_payload = client.get("/api/providers").json()
            providers = {provider["id"]: provider for provider in providers_payload["providers"]}
            self.assertEqual(providers["python_script"]["job_summary"]["queued_jobs"], 1)
            self.assertEqual(providers_payload["job_queue"][0]["job_id"], queued_job["job_id"])
            self.assertEqual(queued_job["operation_state"], "pending")
            self.assertFalse(queued_job["duplicate_suppressed"])

    def test_process_job_executes_queued_provider_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Job Process Test", description="Provider job test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(connection, project_id, goal_id, "agent_reviewer", "Process queued Python provider run")
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            queued_job = client.post(
                "/api/providers/python_script/actions/queue-task",
                json={
                    "actor_id": "agent_allocator",
                    "project_id": project_id,
                    "agent_id": "agent_reviewer",
                    "task_id": task_id,
                },
            ).json()

            response = client.post(
                f"/api/provider-jobs/{queued_job['job_id']}/actions/process",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(response.status_code, 200)
            processed_job = response.json()
            self.assertEqual(processed_job["status"], "completed")
            self.assertIsNotNone(processed_job["session_id"])
            self.assertIsNotNone(processed_job["artifact_id"])

            connection = connect(project_paths(tmpdir))
            try:
                job_row = connection.execute(
                    "SELECT status, session_id, artifact_id FROM provider_job_queue WHERE job_id = ?",
                    (queued_job["job_id"],),
                ).fetchone()
                session_row = connection.execute(
                    "SELECT status FROM sessions WHERE session_id = ?",
                    (processed_job["session_id"],),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(job_row["status"], "completed")
            self.assertEqual(session_row["status"], "completed")

    def test_duplicate_queue_task_reuses_existing_open_job(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Job Dedupe Test", description="Provider job dedupe", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(connection, project_id, goal_id, "agent_reviewer", "Deduped provider run")
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            first = client.post(
                "/api/providers/python_script/actions/queue-task",
                json={
                    "actor_id": "agent_allocator",
                    "project_id": project_id,
                    "agent_id": "agent_reviewer",
                    "task_id": task_id,
                },
            )
            second = client.post(
                "/api/providers/python_script/actions/queue-task",
                json={
                    "actor_id": "agent_allocator",
                    "project_id": project_id,
                    "agent_id": "agent_reviewer",
                    "task_id": task_id,
                },
            )

            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            self.assertEqual(first.json()["job_id"], second.json()["job_id"])
            self.assertFalse(first.json()["duplicate_suppressed"])
            self.assertTrue(second.json()["duplicate_suppressed"])
            self.assertEqual(second.json()["operation_state"], "pending")

            connection = connect(project_paths(tmpdir))
            try:
                count = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM provider_job_queue
                    WHERE project_id = ?
                      AND provider_id = 'python_script'
                      AND task_id = ?
                    """,
                    (project_id, task_id),
                ).fetchone()[0]
            finally:
                connection.close()

            self.assertEqual(count, 1)

    def test_duplicate_queue_task_reuses_existing_open_job_even_if_quotas_tighten(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Job Dedupe Quota Test", description="Provider job dedupe quota", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project = connection.execute("SELECT project_id, config_json FROM projects LIMIT 1").fetchone()
                project_id = project["project_id"]
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(connection, project_id, goal_id, "agent_reviewer", "Deduped provider run under tight quota")
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            first = client.post(
                "/api/providers/python_script/actions/queue-task",
                json={
                    "actor_id": "agent_allocator",
                    "project_id": project_id,
                    "agent_id": "agent_reviewer",
                    "task_id": task_id,
                },
            )
            self.assertEqual(first.status_code, 200)

            connection = connect(project_paths(tmpdir))
            try:
                project = connection.execute(
                    "SELECT config_json FROM projects WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
                config = json.loads(project["config_json"] or "{}")
                config["runtime_quotas"] = {"max_task_session_attempts": 1}
                connection.execute(
                    "UPDATE projects SET config_json = ? WHERE project_id = ?",
                    (json.dumps(config), project_id),
                )
                connection.execute(
                    """
                    INSERT INTO sessions (
                        session_id, project_id, agent_id, task_id, status, provider_type, progress_pct, status_message, ended_at
                    ) VALUES ('sess_existing_attempt', ?, 'agent_reviewer', ?, 'completed', 'python_script', 100, 'existing run', CURRENT_TIMESTAMP)
                    """,
                    (project_id, task_id),
                )
                connection.commit()
            finally:
                connection.close()

            second = client.post(
                "/api/providers/python_script/actions/queue-task",
                json={
                    "actor_id": "agent_allocator",
                    "project_id": project_id,
                    "agent_id": "agent_reviewer",
                    "task_id": task_id,
                },
            )

            self.assertEqual(second.status_code, 200)
            self.assertEqual(first.json()["job_id"], second.json()["job_id"])
            self.assertTrue(second.json()["duplicate_suppressed"])

    def test_queue_task_handles_null_dedupe_fallback_without_type_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Job Null Fallback Test", description="Provider job null fallback", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(connection, project_id, goal_id, "agent_reviewer", "Null fallback provider run")
                connection.commit()

                with mock.patch("maas.services.provider_runtime.insert_provider_job", return_value=None):
                    with self.assertRaises(ValueError):
                        queue_provider_task(
                            connection,
                            paths,
                            "python_script",
                            "agent_allocator",
                            project_id,
                            "agent_reviewer",
                            task_id,
                        )
            finally:
                connection.close()

    def test_process_job_returns_existing_completed_job_without_reprocessing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Job Idempotent Process Test", description="Provider job idempotent", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(connection, project_id, goal_id, "agent_reviewer", "Idempotent provider process")
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            queued_job = client.post(
                "/api/providers/python_script/actions/queue-task",
                json={
                    "actor_id": "agent_allocator",
                    "project_id": project_id,
                    "agent_id": "agent_reviewer",
                    "task_id": task_id,
                },
            ).json()
            first = client.post(
                f"/api/provider-jobs/{queued_job['job_id']}/actions/process",
                json={"actor_id": "agent_allocator"},
            )
            second = client.post(
                f"/api/provider-jobs/{queued_job['job_id']}/actions/process",
                json={"actor_id": "agent_allocator"},
            )

            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            self.assertEqual(second.json()["job_id"], queued_job["job_id"])
            self.assertEqual(second.json()["status"], "completed")
            self.assertTrue(second.json()["duplicate_suppressed"])
            self.assertEqual(second.json()["operation_state"], "succeeded")

    def test_process_next_provider_job_is_project_scoped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Job Scope Test", description="Provider job scope test", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                first_project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                first_goal_id = connection.execute(
                    "SELECT goal_id FROM goals WHERE project_id = ? ORDER BY created_at ASC LIMIT 1",
                    (first_project_id,),
                ).fetchone()["goal_id"]
                first_task_id = _insert_assigned_task(
                    connection,
                    first_project_id,
                    first_goal_id,
                    "agent_reviewer",
                    "First project queued provider run",
                )

                second_project = create_project(
                    connection,
                    paths,
                    actor_id="agent_allocator",
                    name="Second Project",
                    description="Second project",
                    project_type="custom",
                    mode="greenfield",
                    source_root=tmpdir,
                )["project"]
                second_project_id = second_project["project_id"]
                second_goal_id = connection.execute(
                    "SELECT goal_id FROM goals WHERE project_id = ? ORDER BY created_at ASC LIMIT 1",
                    (second_project_id,),
                ).fetchone()["goal_id"]
                second_agent_id = connection.execute(
                    "SELECT agent_id FROM agents WHERE project_id = ? AND role = 'reviewer' LIMIT 1",
                    (second_project_id,),
                ).fetchone()["agent_id"]
                second_task_id = _insert_assigned_task(
                    connection,
                    second_project_id,
                    second_goal_id,
                    second_agent_id,
                    "Second project queued provider run",
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            first_job = client.post(
                "/api/providers/python_script/actions/queue-task",
                json={
                    "actor_id": "agent_allocator",
                    "project_id": first_project_id,
                    "agent_id": "agent_reviewer",
                    "task_id": first_task_id,
                },
            ).json()
            second_job = client.post(
                "/api/providers/python_script/actions/queue-task",
                json={
                    "actor_id": "agent_allocator",
                    "project_id": second_project_id,
                    "agent_id": second_agent_id,
                    "task_id": second_task_id,
                },
            ).json()

            response = client.post(
                "/api/provider-jobs/actions/process-next",
                json={
                    "actor_id": "agent_allocator",
                    "project_id": second_project_id,
                },
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["processed"])
            self.assertEqual(payload["job"]["job_id"], second_job["job_id"])

            connection = connect(project_paths(tmpdir))
            try:
                first_status = connection.execute(
                    "SELECT status FROM provider_job_queue WHERE job_id = ?",
                    (first_job["job_id"],),
                ).fetchone()["status"]
                second_status = connection.execute(
                    "SELECT status FROM provider_job_queue WHERE job_id = ?",
                    (second_job["job_id"],),
                ).fetchone()["status"]
            finally:
                connection.close()

            self.assertEqual(first_status, "queued")
            self.assertEqual(second_status, "completed")

    def test_process_next_provider_job_skips_blocked_project_in_global_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Job Global Skip Test", description="Provider job global skip test", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                first_project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                first_goal_id = connection.execute(
                    "SELECT goal_id FROM goals WHERE project_id = ? ORDER BY created_at ASC LIMIT 1",
                    (first_project_id,),
                ).fetchone()["goal_id"]
                first_task_id = _insert_assigned_task(
                    connection,
                    first_project_id,
                    first_goal_id,
                    "agent_reviewer",
                    "First project blocked queued provider run",
                )

                second_project = create_project(
                    connection,
                    paths,
                    actor_id="agent_allocator",
                    name="Second Project",
                    description="Second project",
                    project_type="custom",
                    mode="greenfield",
                    source_root=tmpdir,
                )["project"]
                second_project_id = second_project["project_id"]
                second_goal_id = connection.execute(
                    "SELECT goal_id FROM goals WHERE project_id = ? ORDER BY created_at ASC LIMIT 1",
                    (second_project_id,),
                ).fetchone()["goal_id"]
                second_agent_id = connection.execute(
                    "SELECT agent_id FROM agents WHERE project_id = ? AND role = 'reviewer' LIMIT 1",
                    (second_project_id,),
                ).fetchone()["agent_id"]
                second_task_id = _insert_assigned_task(
                    connection,
                    second_project_id,
                    second_goal_id,
                    second_agent_id,
                    "Second project runnable queued provider run",
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            first_job = client.post(
                "/api/providers/python_script/actions/queue-task",
                json={
                    "actor_id": "agent_allocator",
                    "project_id": first_project_id,
                    "agent_id": "agent_reviewer",
                    "task_id": first_task_id,
                },
            ).json()
            second_job = client.post(
                "/api/providers/python_script/actions/queue-task",
                json={
                    "actor_id": "agent_allocator",
                    "project_id": second_project_id,
                    "agent_id": second_agent_id,
                    "task_id": second_task_id,
                },
            ).json()
            capacity_response = client.post(
                f"/api/projects/{first_project_id}/actions/update-provider-capacity",
                json={
                    "actor_id": "agent_allocator",
                    "queue_mode": "paused",
                    "max_running_jobs": 1,
                },
            )
            self.assertEqual(capacity_response.status_code, 200)

            response = client.post(
                "/api/provider-jobs/actions/process-next",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["processed"])
            self.assertEqual(payload["job"]["job_id"], second_job["job_id"])

            connection = connect(project_paths(tmpdir))
            try:
                first_status = connection.execute(
                    "SELECT status FROM provider_job_queue WHERE job_id = ?",
                    (first_job["job_id"],),
                ).fetchone()["status"]
                second_status = connection.execute(
                    "SELECT status FROM provider_job_queue WHERE job_id = ?",
                    (second_job["job_id"],),
                ).fetchone()["status"]
            finally:
                connection.close()

            self.assertEqual(first_status, "queued")
            self.assertEqual(second_status, "completed")

    def test_process_job_marks_failure_when_runtime_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Job Failure Test", description="Provider job failure test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(connection, project_id, goal_id, "agent_reviewer", "Fail queued provider run")
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            queued_job = client.post(
                "/api/providers/python_script/actions/queue-task",
                json={
                    "actor_id": "agent_allocator",
                    "project_id": project_id,
                    "agent_id": "agent_reviewer",
                    "task_id": task_id,
                },
            ).json()

            with mock.patch("maas.services.provider_runtime.produce_artifact", side_effect=RuntimeError("artifact blew up")):
                response = client.post(
                    f"/api/provider-jobs/{queued_job['job_id']}/actions/process",
                    json={"actor_id": "agent_allocator"},
                )

            self.assertEqual(response.status_code, 200)
            processed_job = response.json()
            self.assertEqual(processed_job["status"], "failed")
            self.assertEqual(processed_job["failure_kind"], "runtime_error")
            self.assertIn("artifact blew up", processed_job["failure_detail"])

            connection = connect(project_paths(tmpdir))
            try:
                job_row = connection.execute(
                    "SELECT status FROM provider_job_queue WHERE job_id = ?",
                    (queued_job["job_id"],),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(job_row["status"], "failed")

    def test_provider_worker_once_processes_job_and_exposes_worker_pool(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Worker Test", description="Provider worker test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(connection, project_id, goal_id, "agent_reviewer", "Worker processed provider run")
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            queued_job = client.post(
                "/api/providers/python_script/actions/queue-task",
                json={
                    "actor_id": "agent_allocator",
                    "project_id": project_id,
                    "agent_id": "agent_reviewer",
                    "task_id": task_id,
                },
            ).json()

            response = client.post(
                "/api/provider-workers/actions/run-once",
                json={
                    "worker_id": "worker:python_script",
                    "project_id": project_id,
                    "provider_id": "python_script",
                },
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["processed"])
            self.assertEqual(payload["job"]["job_id"], queued_job["job_id"])
            self.assertEqual(payload["job"]["status"], "completed")

            providers_payload = client.get("/api/providers").json()
            self.assertEqual(providers_payload["worker_summary"]["total_workers"], 1)
            self.assertEqual(providers_payload["worker_summary"]["idle_workers"], 1)
            self.assertEqual(providers_payload["worker_pool"][0]["worker_id"], "worker:python_script")
            self.assertEqual(providers_payload["worker_pool"][0]["last_job_status"], "completed")

    def test_provider_worker_once_clears_busy_state_when_job_claim_is_lost(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Worker Claim Race Test", description="Provider worker claim race test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(connection, project_id, goal_id, "agent_reviewer", "Worker claim race provider run")
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            queued_job = client.post(
                "/api/providers/python_script/actions/queue-task",
                json={
                    "actor_id": "agent_allocator",
                    "project_id": project_id,
                    "agent_id": "agent_reviewer",
                    "task_id": task_id,
                },
            ).json()

            with mock.patch("maas.services.provider_runtime.start_provider_job", return_value=None):
                response = client.post(
                    "/api/provider-workers/actions/run-once",
                    json={
                        "worker_id": "worker:python_script",
                        "project_id": project_id,
                        "provider_id": "python_script",
                    },
                )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertFalse(payload["processed"])
            self.assertEqual(payload["job"]["job_id"], queued_job["job_id"])
            self.assertEqual(payload["job"]["status"], "queued")

            providers_payload = client.get("/api/providers").json()
            self.assertEqual(providers_payload["worker_summary"]["busy_workers"], 0)
            self.assertEqual(providers_payload["worker_summary"]["idle_workers"], 1)
            self.assertIsNone(providers_payload["worker_pool"][0]["current_job_id"])
            self.assertEqual(providers_payload["worker_pool"][0]["last_job_status"], "queued")

    def test_process_next_and_worker_respect_project_provider_capacity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Capacity Test", description="Provider capacity test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(connection, project_id, goal_id, "agent_reviewer", "Capacity blocked provider run")
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            queued_job = client.post(
                "/api/providers/python_script/actions/queue-task",
                json={
                    "actor_id": "agent_allocator",
                    "project_id": project_id,
                    "agent_id": "agent_reviewer",
                    "task_id": task_id,
                },
            ).json()

            capacity_response = client.post(
                f"/api/projects/{project_id}/actions/update-provider-capacity",
                json={
                    "actor_id": "agent_allocator",
                    "queue_mode": "paused",
                    "max_running_jobs": 1,
                },
            )
            self.assertEqual(capacity_response.status_code, 200)

            blocked_next = client.post(
                "/api/provider-jobs/actions/process-next",
                json={"actor_id": "agent_allocator", "project_id": project_id, "provider_id": "python_script"},
            ).json()
            self.assertFalse(blocked_next["processed"])

            blocked_worker = client.post(
                "/api/provider-workers/actions/run-once",
                json={"worker_id": "worker:python_script", "project_id": project_id, "provider_id": "python_script"},
            ).json()
            self.assertFalse(blocked_worker["processed"])

            connection = connect(project_paths(tmpdir))
            try:
                job_row = connection.execute(
                    "SELECT status FROM provider_job_queue WHERE job_id = ?",
                    (queued_job["job_id"],),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(job_row["status"], "queued")

    def test_queue_task_respects_task_attempt_quota(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Quota Queue Test", description="Provider quota queue test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project = connection.execute("SELECT project_id, config_json FROM projects LIMIT 1").fetchone()
                project_id = project["project_id"]
                config = json.loads(project["config_json"] or "{}")
                config["runtime_quotas"] = {
                    "daily_run_limit": 0,
                    "daily_live_run_limit": 0,
                    "daily_runtime_seconds_limit": 0,
                    "max_task_session_attempts": 1,
                }
                connection.execute(
                    "UPDATE projects SET config_json = ? WHERE project_id = ?",
                    (json.dumps(config), project_id),
                )
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(connection, project_id, goal_id, "agent_reviewer", "Quota blocked provider run")
                connection.execute(
                    """
                    INSERT INTO sessions (
                        session_id, project_id, agent_id, task_id, status, provider_type, progress_pct, status_message, ended_at
                    ) VALUES ('sess_quota_attempt_existing', ?, 'agent_reviewer', ?, 'completed', 'python_script', 100, 'existing run', CURRENT_TIMESTAMP)
                    """,
                    (project_id, task_id),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.post(
                "/api/providers/python_script/actions/queue-task",
                json={
                    "actor_id": "agent_allocator",
                    "project_id": project_id,
                    "agent_id": "agent_reviewer",
                    "task_id": task_id,
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("Task session-attempt quota reached", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
