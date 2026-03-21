import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.ids import generate_id
from maas.services.bootstrap import bootstrap_project
from maas.services.orchestrator import list_provider_status as original_list_provider_status
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


class OrchestratorApiTest(unittest.TestCase):
    def test_orchestrator_run_auto_launches_codex_work_when_requested(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(
                tmpdir,
                name="Orchestrator Codex Launch Test",
                description="orchestrator codex launch test",
                project_type="custom",
            )
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute(
                    "SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1"
                ).fetchone()["goal_id"]
                connection.execute("UPDATE tasks SET status = 'done', review_state = 'approved'")
                task_id = _insert_assigned_task(
                    connection,
                    project_id,
                    goal_id,
                    "agent_reviewer",
                    "Auto launch Codex work",
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.post(
                "/api/orchestrator/run",
                json={"allocate_limit": 0, "provider_job_limit": 2, "auto_launch_assigned_work": True},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["provider_jobs_queued"], 1)
            self.assertEqual(payload["provider_jobs_processed"], 1)
            self.assertTrue(
                any(
                    any(job["task_id"] == task_id and job["provider_id"] == "openai_codex" for job in project_run["queued_jobs"])
                    for project_run in payload["project_runs"]
                )
            )

            connection = connect(paths)
            try:
                job_row = connection.execute(
                    """
                    SELECT provider_id, status, session_id
                    FROM provider_job_queue
                    WHERE task_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (task_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(job_row["provider_id"], "openai_codex")
            self.assertEqual(job_row["status"], "completed")
            self.assertIsNotNone(job_row["session_id"])

    def test_orchestrator_run_processes_provider_jobs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Orchestrator Test",
                description="orchestrator test",
                project_type="custom",
            )
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute(
                    "SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1"
                ).fetchone()["goal_id"]
                task_id = _insert_assigned_task(
                    connection,
                    project_id,
                    goal_id,
                    "agent_reviewer",
                    "Queued provider work for orchestrator",
                )
                queued_job = queue_provider_task(
                    connection,
                    paths,
                    provider_id="python_script",
                    actor_id="agent_allocator",
                    project_id=project_id,
                    agent_id="agent_reviewer",
                    task_id=task_id,
                )
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.post(
                "/api/orchestrator/run",
                json={"allocate_limit": 2, "provider_job_limit": 2},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["provider_jobs_processed"], 1)
            self.assertTrue(
                any(
                    any(job["job_id"] == queued_job["job_id"] for job in project_run["processed_jobs"])
                    for project_run in payload["project_runs"]
                )
            )

            connection = connect(paths)
            try:
                job_row = connection.execute(
                    "SELECT status, session_id FROM provider_job_queue WHERE job_id = ?",
                    (queued_job["job_id"],),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(job_row["status"], "completed")
            self.assertIsNotNone(job_row["session_id"])

    def test_orchestrator_run_dispatches_live_codex_work_to_detached_workers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(
                tmpdir,
                name="Orchestrator Detached Codex Test",
                description="orchestrator detached codex test",
                project_type="custom",
            )
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute(
                    "SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1"
                ).fetchone()["goal_id"]
                connection.execute("UPDATE tasks SET status = 'done', review_state = 'approved'")
                task_id = _insert_assigned_task(
                    connection,
                    project_id,
                    goal_id,
                    "agent_reviewer",
                    "Detached live Codex work",
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            with patch("maas.services.orchestrator._provider_uses_detached_workers", return_value=True), patch(
                "maas.services.orchestrator.launch_detached_provider_workers",
                return_value=["pworker_test_1"],
            ) as launch_workers:
                response = client.post(
                    "/api/orchestrator/run",
                    json={"allocate_limit": 0, "provider_job_limit": 2, "auto_launch_assigned_work": True},
                )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["provider_jobs_queued"], 1)
            self.assertEqual(payload["provider_jobs_processed"], 0)
            self.assertEqual(payload["provider_jobs_dispatched"], 1)
            launch_workers.assert_called_once()

            connection = connect(paths)
            try:
                job_row = connection.execute(
                    """
                    SELECT provider_id, status, session_id
                    FROM provider_job_queue
                    WHERE task_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (task_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(job_row["provider_id"], "openai_codex")
            self.assertEqual(job_row["status"], "queued")
            self.assertIsNone(job_row["session_id"])

    def test_orchestrator_run_dispatches_preexisting_live_jobs_to_detached_workers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(
                tmpdir,
                name="Orchestrator Existing Detached Jobs Test",
                description="orchestrator existing detached jobs test",
                project_type="custom",
            )
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute(
                    "SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1"
                ).fetchone()["goal_id"]
                connection.execute("UPDATE tasks SET status = 'done', review_state = 'approved'")
                task_id = _insert_assigned_task(
                    connection,
                    project_id,
                    goal_id,
                    "agent_reviewer",
                    "Existing queued live Codex work",
                )
                queued_job = queue_provider_task(
                    connection,
                    paths,
                    provider_id="openai_codex",
                    actor_id="agent_allocator",
                    project_id=project_id,
                    agent_id="agent_reviewer",
                    task_id=task_id,
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            with patch("maas.services.orchestrator._provider_uses_detached_workers", return_value=True), patch(
                "maas.services.orchestrator.launch_detached_provider_workers",
                return_value=["pworker_existing_1"],
            ) as launch_workers:
                response = client.post(
                    "/api/orchestrator/run",
                    json={"allocate_limit": 0, "provider_job_limit": 2, "auto_launch_assigned_work": False},
                )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["provider_jobs_queued"], 0)
            self.assertEqual(payload["provider_jobs_processed"], 0)
            self.assertEqual(payload["provider_jobs_dispatched"], 1)
            launch_workers.assert_called_once()

            project_run = payload["project_runs"][0]
            self.assertEqual(project_run["provider_jobs_queued"], 0)
            self.assertEqual(project_run["provider_jobs_processed"], 0)
            self.assertEqual(project_run["provider_jobs_dispatched"], 1)

            connection = connect(paths)
            try:
                job_row = connection.execute(
                    "SELECT status FROM provider_job_queue WHERE job_id = ?",
                    (queued_job["job_id"],),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(job_row["status"], "queued")

    def test_orchestrator_honors_provider_queue_pause_and_limit_controls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(
                tmpdir,
                name="Orchestrator Queue Controls Test",
                description="orchestrator queue control test",
                project_type="custom",
            )
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute(
                    "SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1"
                ).fetchone()["goal_id"]
                first_task_id = _insert_assigned_task(
                    connection,
                    project_id,
                    goal_id,
                    "agent_reviewer",
                    "Queued provider work one",
                )
                second_task_id = _insert_assigned_task(
                    connection,
                    project_id,
                    goal_id,
                    "agent_reviewer",
                    "Queued provider work two",
                )
                first_job = queue_provider_task(
                    connection,
                    paths,
                    provider_id="python_script",
                    actor_id="agent_allocator",
                    project_id=project_id,
                    agent_id="agent_reviewer",
                    task_id=first_task_id,
                )
                second_job = queue_provider_task(
                    connection,
                    paths,
                    provider_id="python_script",
                    actor_id="agent_allocator",
                    project_id=project_id,
                    agent_id="agent_reviewer",
                    task_id=second_task_id,
                )
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            paused_response = client.post(
                "/api/providers/python_script/actions/set-settings",
                json={"actor_id": "agent_allocator", "settings": {"queue_paused": True, "job_limit_per_pass": 1}},
            )
            self.assertEqual(paused_response.status_code, 200)

            paused_run = client.post(
                "/api/orchestrator/run",
                json={"allocate_limit": 2, "provider_job_limit": 3},
            ).json()
            self.assertEqual(paused_run["provider_jobs_processed"], 0)

            resumed_response = client.post(
                "/api/providers/python_script/actions/set-settings",
                json={"actor_id": "agent_allocator", "settings": {"queue_paused": False, "job_limit_per_pass": 1}},
            )
            self.assertEqual(resumed_response.status_code, 200)

            limited_run = client.post(
                "/api/orchestrator/run",
                json={"allocate_limit": 2, "provider_job_limit": 3},
            ).json()
            self.assertEqual(limited_run["provider_jobs_processed"], 1)

            connection = connect(paths)
            try:
                statuses = {
                    row["job_id"]: row["status"]
                    for row in connection.execute(
                        "SELECT job_id, status FROM provider_job_queue ORDER BY created_at ASC"
                    ).fetchall()
                }
            finally:
                connection.close()

            self.assertEqual(statuses[first_job["job_id"]], "completed")
            self.assertEqual(statuses[second_job["job_id"]], "queued")

    def test_orchestrator_draining_processes_queued_work_without_auto_launching_new_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(
                tmpdir,
                name="Orchestrator Draining Test",
                description="orchestrator draining test",
                project_type="custom",
            )
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute(
                    "SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1"
                ).fetchone()["goal_id"]
                connection.execute("UPDATE tasks SET status = 'done', review_state = 'approved'")
                queued_task_id = _insert_assigned_task(
                    connection,
                    project_id,
                    goal_id,
                    "agent_reviewer",
                    "Queued draining work",
                )
                launch_ready_task_id = _insert_assigned_task(
                    connection,
                    project_id,
                    goal_id,
                    "agent_reviewer",
                    "Assigned but not yet queued",
                )
                queued_job = queue_provider_task(
                    connection,
                    paths,
                    provider_id="python_script",
                    actor_id="agent_allocator",
                    project_id=project_id,
                    agent_id="agent_reviewer",
                    task_id=queued_task_id,
                )
                connection.execute(
                    """
                    UPDATE projects
                    SET config_json = json_set(
                        json_set(config_json, '$.provider_capacity.queue_mode', 'draining'),
                        '$.provider_capacity.preferred_provider_id',
                        'python_script'
                    )
                    WHERE project_id = ?
                    """,
                    (project_id,),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            payload = client.post(
                "/api/orchestrator/run",
                json={"allocate_limit": 0, "provider_job_limit": 2, "auto_launch_assigned_work": True},
            ).json()

            self.assertEqual(payload["provider_jobs_queued"], 0)
            self.assertEqual(payload["provider_jobs_processed"], 1)
            self.assertEqual(payload["project_runs"][0]["launch_provider_id"], None)

            connection = connect(paths)
            try:
                job_rows = connection.execute(
                    "SELECT task_id, status FROM provider_job_queue ORDER BY created_at ASC"
                ).fetchall()
            finally:
                connection.close()

            self.assertEqual(len(job_rows), 1)
            self.assertEqual(job_rows[0]["task_id"], queued_task_id)
            self.assertEqual(job_rows[0]["status"], "completed")

    def test_orchestrator_auto_launch_uses_project_preferred_provider(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(
                tmpdir,
                name="Orchestrator Preferred Provider Test",
                description="orchestrator preferred provider test",
                project_type="custom",
            )
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute(
                    "SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1"
                ).fetchone()["goal_id"]
                connection.execute("UPDATE tasks SET status = 'done', review_state = 'approved'")
                task_id = _insert_assigned_task(
                    connection,
                    project_id,
                    goal_id,
                    "agent_reviewer",
                    "Launch through preferred provider",
                )
                connection.execute(
                    """
                    UPDATE projects
                    SET config_json = json_set(config_json, '$.provider_capacity.preferred_provider_id', 'python_script')
                    WHERE project_id = ?
                    """,
                    (project_id,),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.post(
                "/api/orchestrator/run",
                json={"allocate_limit": 0, "provider_job_limit": 2, "auto_launch_assigned_work": True},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["provider_jobs_queued"], 1)
            self.assertEqual(payload["project_runs"][0]["launch_provider_id"], "python_script")

            connection = connect(paths)
            try:
                job_row = connection.execute(
                    """
                    SELECT provider_id, status
                    FROM provider_job_queue
                    WHERE task_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (task_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(job_row["provider_id"], "python_script")
            self.assertEqual(job_row["status"], "completed")

    def test_orchestrator_falls_back_when_preferred_provider_is_not_ready(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(
                tmpdir,
                name="Orchestrator Preferred Fallback Test",
                description="orchestrator preferred fallback test",
                project_type="custom",
            )
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute(
                    "SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1"
                ).fetchone()["goal_id"]
                connection.execute("UPDATE tasks SET status = 'done', review_state = 'approved'")
                task_id = _insert_assigned_task(
                    connection,
                    project_id,
                    goal_id,
                    "agent_reviewer",
                    "Launch through fallback provider",
                )
                connection.execute(
                    """
                    UPDATE projects
                    SET config_json = json_set(config_json, '$.provider_capacity.preferred_provider_id', 'python_script')
                    WHERE project_id = ?
                    """,
                    (project_id,),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            with patch("maas.services.orchestrator.list_provider_status") as list_provider_status:
                def side_effect(*_args, **_kwargs):
                    statuses = original_list_provider_status(*_args, **_kwargs)
                    for provider in statuses:
                        if provider["id"] == "python_script":
                            provider["status"] = "misconfigured"
                            provider["is_runnable"] = False
                    return statuses

                list_provider_status.side_effect = side_effect
                response = client.post(
                    "/api/orchestrator/run",
                    json={"allocate_limit": 0, "provider_job_limit": 2, "auto_launch_assigned_work": True},
                )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["provider_jobs_queued"], 1)
            self.assertEqual(payload["project_runs"][0]["launch_provider_id"], "openai_codex")

            connection = connect(paths)
            try:
                job_row = connection.execute(
                    """
                    SELECT provider_id, status
                    FROM provider_job_queue
                    WHERE task_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (task_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(job_row["provider_id"], "openai_codex")
            self.assertEqual(job_row["status"], "completed")


if __name__ == "__main__":
    unittest.main()
