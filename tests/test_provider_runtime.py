import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.db import connect, project_paths
from maas.ids import generate_id
from maas.services.bootstrap import bootstrap_project
from maas.services.provider_runtime import run_provider_task
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


class ProviderRuntimeTest(unittest.TestCase):
    def _update_recovery_config(self, connection, **recovery_updates):
        project = connection.execute("SELECT project_id, config_json FROM projects LIMIT 1").fetchone()
        config = json.loads(project["config_json"] or "{}")
        recovery = dict(config.get("recovery") or {})
        recovery.update(recovery_updates)
        config["recovery"] = recovery
        connection.execute(
            "UPDATE projects SET config_json = ? WHERE project_id = ?",
            (json.dumps(config), project["project_id"]),
        )
        return project["project_id"]

    def _enable_claude_code_cli(self, connection):
        project = connection.execute("SELECT project_id, config_json FROM projects LIMIT 1").fetchone()
        config = json.loads(project["config_json"] or "{}")
        providers = config.setdefault("providers", {})
        providers["claude_code"] = {
            "mode": "claude_cli",
            "cli_command": "claude",
            "timeout_seconds": 120,
            "permission_mode": "acceptEdits",
            "model": "sonnet",
        }
        connection.execute(
            "UPDATE projects SET config_json = ? WHERE project_id = ?",
            (json.dumps(config), project["project_id"]),
        )
        return project["project_id"]

    def _enable_openai_codex_cli(self, connection):
        project = connection.execute("SELECT project_id, config_json FROM projects LIMIT 1").fetchone()
        config = json.loads(project["config_json"] or "{}")
        providers = config.setdefault("providers", {})
        providers["openai_codex"] = {
            "mode": "codex_cli",
            "cli_command": "codex",
            "timeout_seconds": 120,
            "sandbox": "workspace-write",
            "model": "gpt-5-codex",
        }
        connection.execute(
            "UPDATE projects SET config_json = ? WHERE project_id = ?",
            (json.dumps(config), project["project_id"]),
        )
        return project["project_id"]

    def _set_provider_config(self, connection, provider_id, provider_config):
        project = connection.execute("SELECT project_id, config_json FROM projects LIMIT 1").fetchone()
        config = json.loads(project["config_json"] or "{}")
        providers = config.setdefault("providers", {})
        providers[provider_id] = provider_config
        connection.execute(
            "UPDATE projects SET config_json = ? WHERE project_id = ?",
            (json.dumps(config), project["project_id"]),
        )
        return project["project_id"]

    def test_providers_endpoint_reports_runtime_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Endpoint Test", description="Provider endpoint test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            payload = client.get("/api/providers").json()
            provider_ids = {provider["id"] for provider in payload["providers"]}

            self.assertEqual(provider_ids, {"python_script", "claude_code", "openai_codex"})
            self.assertTrue(all(provider["supports_worker_execution"] for provider in payload["providers"]))
            self.assertTrue(all(provider["execution_mode"] == "local_simulation" for provider in payload["providers"]))
            self.assertTrue(
                all(provider["configured_execution_mode"] == "local_simulation" for provider in payload["providers"])
            )
            self.assertTrue(all(provider["lifecycle_version"] == "provider_runtime_v1" for provider in payload["providers"]))
            self.assertTrue(
                all(
                    provider["lifecycle_phases"]
                    == [
                        "session_started",
                        "workspace_prepared",
                        "execution_running",
                        "artifact_recorded",
                        "session_completed",
                    ]
                    for provider in payload["providers"]
                )
            )
            self.assertTrue(
                all(
                    sorted(provider["run_summary"].keys())
                    == [
                        "active_runs",
                        "cancelled_runs",
                        "completed_runs",
                        "failed_runs",
                        "last_run_at",
                        "latest_failure_at",
                        "latest_failure_kind",
                        "nonzero_exit_failures",
                        "runtime_failures",
                        "timed_out_runs",
                        "timeout_failures",
                        "total_runs",
                    ]
                    for provider in payload["providers"]
                )
            )
            self.assertTrue(all(isinstance(provider["recent_runs"], list) for provider in payload["providers"]))
            providers = {provider["id"]: provider for provider in payload["providers"]}
            self.assertTrue(all(provider["guardrails"] for provider in providers.values()))
            self.assertEqual(providers["claude_code"]["recent_runs"], [])
            self.assertEqual(providers["openai_codex"]["recent_runs"], [])
            self.assertGreaterEqual(len(providers["python_script"]["recent_runs"]), 1)
            self.assertTrue(all("task_id" in target for target in payload["run_targets"]))
            self.assertTrue(all("agent_id" in target for target in payload["run_targets"]))
            self.assertTrue(
                all(target["status"] in ("planned", "ready", "assigned") for target in payload["run_targets"])
            )

    def test_providers_endpoint_reflects_configured_openai_codex_cli_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Config Test", description="Provider config test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                self._enable_openai_codex_cli(connection)
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            payload = client.get("/api/providers").json()
            providers = {provider["id"]: provider for provider in payload["providers"]}

            self.assertEqual(providers["openai_codex"]["execution_mode"], "codex_cli")
            self.assertEqual(providers["openai_codex"]["configured_execution_mode"], "codex_cli")
            self.assertEqual(providers["openai_codex"]["status"], "configured")
            self.assertTrue(providers["openai_codex"]["supports_live_api"])
            self.assertEqual(providers["openai_codex"]["effective_execution_mode"], "codex_cli")
            self.assertTrue(providers["openai_codex"]["is_runnable"])
            self.assertEqual(
                providers["openai_codex"]["runtime_controls"],
                {
                    "cli_command": "codex",
                    "timeout_seconds": 120,
                    "sandbox": "workspace-write",
                    "model": "gpt-5-codex",
                },
            )

    def test_providers_endpoint_reflects_configured_claude_code_cli_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Claude Provider Config Test", description="Claude provider config test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                self._enable_claude_code_cli(connection)
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            payload = client.get("/api/providers").json()
            providers = {provider["id"]: provider for provider in payload["providers"]}

            self.assertEqual(providers["claude_code"]["execution_mode"], "claude_cli")
            self.assertEqual(providers["claude_code"]["configured_execution_mode"], "claude_cli")
            self.assertEqual(providers["claude_code"]["status"], "configured")
            self.assertTrue(providers["claude_code"]["supports_live_api"])
            self.assertEqual(providers["claude_code"]["effective_execution_mode"], "claude_cli")
            self.assertTrue(providers["claude_code"]["is_runnable"])
            self.assertEqual(
                providers["claude_code"]["runtime_controls"],
                {
                    "cli_command": "claude",
                    "timeout_seconds": 120,
                    "permission_mode": "acceptEdits",
                    "model": "sonnet",
                },
            )

    def test_providers_endpoint_marks_claude_cli_without_permission_mode_as_misconfigured(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Claude Provider Config Test", description="Claude provider config test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                self._set_provider_config(
                    connection,
                    "claude_code",
                    {
                        "mode": "claude_cli",
                        "cli_command": "claude",
                        "timeout_seconds": 120,
                        "permission_mode": "",
                        "model": "sonnet",
                    },
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            payload = client.get("/api/providers").json()
            provider = {item["id"]: item for item in payload["providers"]}["claude_code"]

            self.assertEqual(provider["status"], "misconfigured")
            self.assertFalse(provider["is_runnable"])
            self.assertIn("permission_mode must not be empty", " ".join(provider["config_warnings"]))

    def test_providers_endpoint_reports_misconfigured_live_provider(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Config Test", description="Provider config test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                self._set_provider_config(
                    connection,
                    "openai_codex",
                    {
                        "mode": "codex_cli",
                        "cli_command": "",
                        "timeout_seconds": 0,
                        "sandbox": "workspace-write",
                        "model": "gpt-5-codex",
                    },
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            payload = client.get("/api/providers").json()
            providers = {provider["id"]: provider for provider in payload["providers"]}

            self.assertEqual(providers["openai_codex"]["status"], "misconfigured")
            self.assertEqual(providers["openai_codex"]["configured_execution_mode"], "codex_cli")
            self.assertIsNone(providers["openai_codex"]["effective_execution_mode"])
            self.assertEqual(providers["openai_codex"]["execution_mode"], "unavailable")
            self.assertFalse(providers["openai_codex"]["is_runnable"])
            self.assertFalse(providers["openai_codex"]["supports_live_api"])
            self.assertGreaterEqual(len(providers["openai_codex"]["config_warnings"]), 1)

    def test_providers_endpoint_reports_non_string_provider_config_as_misconfigured(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Config Test", description="Provider config test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                self._set_provider_config(
                    connection,
                    "claude_code",
                    {
                        "mode": 1,
                        "cli_command": 123,
                        "timeout_seconds": 120,
                        "permission_mode": "acceptEdits",
                        "model": "sonnet",
                    },
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            payload = client.get("/api/providers").json()
            providers = {provider["id"]: provider for provider in payload["providers"]}

            self.assertEqual(providers["claude_code"]["status"], "misconfigured")
            self.assertEqual(providers["claude_code"]["execution_mode"], "unavailable")
            self.assertIsNone(providers["claude_code"]["effective_execution_mode"])
            self.assertFalse(providers["claude_code"]["is_runnable"])
            self.assertIn("Claude Code mode must be a string.", providers["claude_code"]["config_warnings"])

    def test_provider_mode_endpoint_updates_runtime_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Config Test", description="Provider config test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            response = client.post(
                "/api/providers/openai_codex/actions/set-mode",
                json={"actor_id": "agent_allocator", "mode": "codex_cli"},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["configured_execution_mode"], "codex_cli")
            self.assertEqual(payload["execution_mode"], "codex_cli")
            self.assertEqual(payload["status"], "configured")

            revert_response = client.post(
                "/api/providers/openai_codex/actions/set-mode",
                json={"actor_id": "agent_allocator", "mode": "local_simulation"},
            )
            self.assertEqual(revert_response.status_code, 200)
            self.assertEqual(revert_response.json()["configured_execution_mode"], "local_simulation")

    def test_provider_mode_update_preserves_other_provider_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Config Test", description="Provider config test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            claude_response = client.post(
                "/api/providers/claude_code/actions/set-mode",
                json={"actor_id": "agent_allocator", "mode": "claude_cli"},
            )
            self.assertEqual(claude_response.status_code, 200)

            codex_response = client.post(
                "/api/providers/openai_codex/actions/set-mode",
                json={"actor_id": "agent_allocator", "mode": "codex_cli"},
            )
            self.assertEqual(codex_response.status_code, 200)

            payload = client.get("/api/providers").json()
            providers = {provider["id"]: provider for provider in payload["providers"]}
            self.assertEqual(providers["claude_code"]["configured_execution_mode"], "claude_cli")
            self.assertEqual(providers["openai_codex"]["configured_execution_mode"], "codex_cli")
            self.assertEqual(providers["claude_code"]["runtime_controls"]["cli_command"], "claude")
            self.assertEqual(providers["openai_codex"]["runtime_controls"]["cli_command"], "codex")

    def test_provider_mode_endpoint_requires_board_action_permission(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Config Test", description="Provider config test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            response = client.post(
                "/api/providers/openai_codex/actions/set-mode",
                json={"actor_id": "agent_researcher", "mode": "codex_cli"},
            )
            self.assertEqual(response.status_code, 403)
            self.assertIn("board actions", response.json()["detail"].lower())

    def test_provider_preflight_reports_simulation_ready_for_local_simulation_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Preflight Test", description="Provider preflight test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            response = client.post(
                "/api/providers/python_script/actions/run-preflight",
                json={"actor_id": "agent_allocator"},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "simulation_ready")

            providers = {provider["id"]: provider for provider in client.get("/api/providers").json()["providers"]}
            self.assertEqual(providers["python_script"]["latest_preflight"]["status"], "simulation_ready")

    def test_provider_preflight_checks_live_runtime_readiness(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Preflight Test", description="Provider preflight test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                self._enable_openai_codex_cli(connection)
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            os.environ["OPENAI_API_KEY"] = "test-openai-key"
            try:
                with mock.patch("maas.services.provider_runtime.shutil.which", return_value="/usr/bin/codex"):
                    with mock.patch(
                        "maas.services.provider_runtime.subprocess.run",
                        return_value=mock.Mock(returncode=0, stdout="codex 1.2.3\n", stderr=""),
                    ) as run_mock:
                        response = client.post(
                            "/api/providers/openai_codex/actions/run-preflight",
                            json={"actor_id": "agent_allocator"},
                        )
            finally:
                os.environ.pop("OPENAI_API_KEY", None)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "passed")
            self.assertEqual(run_mock.call_count, 1)

            providers = {provider["id"]: provider for provider in client.get("/api/providers").json()["providers"]}
            preflight = providers["openai_codex"]["latest_preflight"]
            self.assertEqual(preflight["status"], "passed")
            self.assertIn("codex 1.2.3", preflight["summary"])
            self.assertEqual(preflight["execution_mode"], "codex_cli")

    def test_provider_preflight_fails_when_required_auth_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Preflight Test", description="Provider preflight test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                self._enable_claude_code_cli(connection)
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            with mock.patch("maas.services.provider_runtime.shutil.which", return_value="/usr/bin/claude"):
                with mock.patch("maas.services.provider_runtime.subprocess.run") as run_mock:
                    response = client.post(
                        "/api/providers/claude_code/actions/run-preflight",
                        json={"actor_id": "agent_allocator"},
                    )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "failed")
            self.assertIn("ANTHROPIC_API_KEY", " ".join(response.json()["issues"]))
            self.assertFalse(run_mock.called)

            providers = {provider["id"]: provider for provider in client.get("/api/providers").json()["providers"]}
            self.assertEqual(providers["claude_code"]["latest_preflight"]["status"], "failed")

    def test_provider_preflight_requires_board_action_permission(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Preflight Test", description="Provider preflight test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            response = client.post(
                "/api/providers/python_script/actions/run-preflight",
                json={"actor_id": "agent_researcher"},
            )
            self.assertEqual(response.status_code, 403)

    def test_provider_settings_endpoint_updates_runtime_controls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Config Test", description="Provider config test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            response = client.post(
                "/api/providers/openai_codex/actions/set-settings",
                json={
                    "actor_id": "agent_allocator",
                    "settings": {
                        "cli_command": "codex-beta",
                        "timeout_seconds": 45,
                        "sandbox": "workspace-write",
                        "model": "gpt-5-mini",
                    },
                },
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["configurable_runtime_controls"]["cli_command"], "codex-beta")
            self.assertEqual(payload["configurable_runtime_controls"]["timeout_seconds"], 45)
            self.assertEqual(payload["configurable_runtime_controls"]["model"], "gpt-5-mini")

    def test_provider_settings_endpoint_rejects_invalid_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Config Test", description="Provider config test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            response = client.post(
                "/api/providers/openai_codex/actions/set-settings",
                json={
                    "actor_id": "agent_allocator",
                    "settings": {
                        "timeout_seconds": 0,
                    },
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("timeout_seconds", response.json()["detail"])

    def test_provider_settings_endpoint_rejects_cli_command_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Config Test", description="Provider config test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            response = client.post(
                "/api/providers/openai_codex/actions/set-settings",
                json={
                    "actor_id": "agent_allocator",
                    "settings": {
                        "cli_command": "../bin/codex",
                    },
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("cli_command must be an executable name", response.json()["detail"])

    def test_provider_settings_endpoint_rejects_unsafe_live_modes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Config Test", description="Provider config test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            codex_response = client.post(
                "/api/providers/openai_codex/actions/set-settings",
                json={
                    "actor_id": "agent_allocator",
                    "settings": {
                        "sandbox": "danger-full-access",
                    },
                },
            )
            self.assertEqual(codex_response.status_code, 400)
            self.assertIn("sandbox must be one of", codex_response.json()["detail"])

            claude_response = client.post(
                "/api/providers/claude_code/actions/set-settings",
                json={
                    "actor_id": "agent_allocator",
                    "settings": {
                        "permission_mode": "bypassPermissions",
                    },
                },
            )
            self.assertEqual(claude_response.status_code, 400)
            self.assertIn("permission_mode must be one of", claude_response.json()["detail"])

    def test_provider_settings_endpoint_requires_board_action_permission(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Config Test", description="Provider config test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            response = client.post(
                "/api/providers/openai_codex/actions/set-settings",
                json={
                    "actor_id": "agent_researcher",
                    "settings": {
                        "model": "gpt-5-mini",
                    },
                },
            )
            self.assertEqual(response.status_code, 403)

    def test_provider_run_task_executes_each_adapter_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Runtime Test", description="Provider runtime test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                provider_tasks = {
                    "python_script": _insert_assigned_task(
                        connection, project_id, goal_id, "agent_allocator", "Run Python Script adapter"
                    ),
                    "claude_code": _insert_assigned_task(
                        connection, project_id, goal_id, "agent_researcher", "Run Claude Code adapter"
                    ),
                    "openai_codex": _insert_assigned_task(
                        connection, project_id, goal_id, "agent_reviewer", "Run OpenAI Codex adapter"
                    ),
                }
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            agent_by_provider = {
                "python_script": "agent_allocator",
                "claude_code": "agent_researcher",
                "openai_codex": "agent_reviewer",
            }

            for provider_id, task_id in provider_tasks.items():
                response = client.post(
                    "/api/providers/{0}/actions/run-task".format(provider_id),
                    json={
                        "project_id": project_id,
                        "agent_id": agent_by_provider[provider_id],
                        "task_id": task_id,
                    },
                )
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["provider"]["id"], provider_id)
                self.assertEqual(payload["execution"]["execution_mode"], "local_simulation")
                self.assertEqual(payload["execution"]["lifecycle_version"], "provider_runtime_v1")
                self.assertEqual(payload["execution"]["artifact_type"], "provider_report")
                self.assertEqual(
                    payload["execution"]["lifecycle_phases"],
                    [
                        "session_started",
                        "workspace_prepared",
                        "execution_running",
                        "artifact_recorded",
                        "session_completed",
                    ],
                )

            connection = connect(project_paths(tmpdir))
            try:
                for provider_id, task_id in provider_tasks.items():
                    session = connection.execute(
                        """
                        SELECT provider_type, status
                        FROM sessions
                        WHERE task_id = ?
                        ORDER BY started_at DESC
                        LIMIT 1
                        """,
                        (task_id,),
                    ).fetchone()
                    task = connection.execute(
                        "SELECT status FROM tasks WHERE task_id = ?",
                        (task_id,),
                    ).fetchone()
                    artifact = connection.execute(
                        """
                        SELECT artifact_type, metadata_json
                        FROM artifacts
                        WHERE task_id = ?
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        (task_id,),
                    ).fetchone()
                    activity_rows = connection.execute(
                        """
                        SELECT action, details_json
                        FROM activity_log
                        WHERE task_id = ?
                          AND action IN (
                              'provider_adapter_started',
                              'provider_workspace_prepared',
                              'provider_execution_progress',
                              'provider_artifact_recorded',
                              'provider_adapter_completed'
                          )
                        ORDER BY rowid ASC
                        """,
                        (task_id,),
                    ).fetchall()

                    self.assertEqual(session["provider_type"], provider_id)
                    self.assertEqual(session["status"], "completed")
                    self.assertEqual(task["status"], "review")
                    self.assertEqual(artifact["artifact_type"], "provider_report")
                    artifact_metadata = json.loads(artifact["metadata_json"])
                    self.assertEqual(artifact_metadata["provider_type"], provider_id)
                    self.assertEqual(artifact_metadata["execution_mode"], "local_simulation")
                    self.assertEqual(artifact_metadata["lifecycle_version"], "provider_runtime_v1")
                    self.assertEqual(
                        artifact_metadata["lifecycle_phases"],
                        [
                            "session_started",
                            "workspace_prepared",
                            "execution_running",
                            "artifact_recorded",
                            "session_completed",
                        ],
                    )
                    self.assertEqual(len(activity_rows), 5)
                    self.assertEqual(
                        [row["action"] for row in activity_rows],
                        [
                            "provider_adapter_started",
                            "provider_workspace_prepared",
                            "provider_execution_progress",
                            "provider_artifact_recorded",
                            "provider_adapter_completed",
                        ],
                    )
                    self.assertEqual(
                        [json.loads(row["details_json"])["phase"] for row in activity_rows],
                        [
                            "session_started",
                            "workspace_prepared",
                            "execution_running",
                            "artifact_recorded",
                            "session_completed",
                        ],
                    )
                    self.assertTrue(
                        all(
                            json.loads(row["details_json"])["lifecycle_version"] == "provider_runtime_v1"
                            for row in activity_rows
                        )
                    )
            finally:
                connection.close()

            providers_payload = client.get("/api/providers").json()
            providers = {provider["id"]: provider for provider in providers_payload["providers"]}
            for provider_id, task_id in provider_tasks.items():
                self.assertEqual(providers[provider_id]["run_summary"]["completed_runs"], 1)
                self.assertEqual(providers[provider_id]["run_summary"]["failed_runs"], 0)
                self.assertGreaterEqual(providers[provider_id]["run_summary"]["total_runs"], 1)
                self.assertEqual(providers[provider_id]["recent_runs"][0]["task_id"], task_id)
                self.assertEqual(providers[provider_id]["recent_runs"][0]["status"], "completed")

    def test_providers_endpoint_limits_recent_runs_per_provider(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Runtime Test", description="Provider runtime test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_ids = []
                for index in range(4):
                    task_ids.append(
                        _insert_assigned_task(
                            connection,
                            project_id,
                            goal_id,
                            "agent_allocator",
                            "Run Python Script adapter {0}".format(index),
                        )
                    )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            for task_id in task_ids:
                response = client.post(
                    "/api/providers/python_script/actions/run-task",
                    json={
                        "project_id": project_id,
                        "agent_id": "agent_allocator",
                        "task_id": task_id,
                    },
                )
                self.assertEqual(response.status_code, 200)

            providers_payload = client.get("/api/providers").json()
            providers = {provider["id"]: provider for provider in providers_payload["providers"]}
            self.assertEqual(providers["python_script"]["run_summary"]["completed_runs"], 4)
            self.assertEqual(len(providers["python_script"]["recent_runs"]), 3)

    def test_providers_endpoint_includes_manual_run_targets_with_execute_grants(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Runtime Test", description="Provider runtime test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                runnable_task_id = _insert_assigned_task(
                    connection,
                    project_id,
                    goal_id,
                    "agent_allocator",
                    "Run provider-target task",
                )
                blocked_task_id = generate_id("task")
                connection.execute(
                    """
                    INSERT INTO tasks (
                        task_id, project_id, goal_id, title, description, status, priority, assigned_agent_id, acceptance_criteria_json, next_retry_at
                    ) VALUES (?, ?, ?, ?, '', 'assigned', 65, ?, '[]', datetime('now', '+10 minutes'))
                    """,
                    (blocked_task_id, project_id, goal_id, "Skip cooldown task", "agent_allocator"),
                )
                no_grant_task_id = generate_id("task")
                connection.execute(
                    """
                    INSERT INTO tasks (
                        task_id, project_id, goal_id, title, description, status, priority, assigned_agent_id, acceptance_criteria_json
                    ) VALUES (?, ?, ?, ?, '', 'assigned', 60, ?, '[]')
                    """,
                    (no_grant_task_id, project_id, goal_id, "Skip no-grant task", "agent_allocator"),
                )
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            payload = client.get("/api/providers").json()
            run_target_ids = {target["task_id"] for target in payload["run_targets"]}

            self.assertIn(runnable_task_id, run_target_ids)
            self.assertNotIn(blocked_task_id, run_target_ids)
            self.assertNotIn(no_grant_task_id, run_target_ids)

    def test_lifecycle_start_rejects_unknown_provider(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Validation Test", description="Provider validation test", project_type="custom")
            client = TestClient(create_app(tmpdir))

            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE status = 'ready' LIMIT 1"
                ).fetchone()["task_id"]
            finally:
                connection.close()

            response = client.post(
                "/api/lifecycle/start",
                json={
                    "project_id": project_id,
                    "agent_id": "agent_allocator",
                    "task_id": task_id,
                    "provider_type": "unknown_provider",
                    "status_message": "test",
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("Unsupported provider type", response.json()["detail"])

    def test_provider_run_task_rejects_misconfigured_live_provider(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Runtime Test", description="Provider runtime test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = self._set_provider_config(
                    connection,
                    "openai_codex",
                    {
                        "mode": "codex_cli",
                        "cli_command": "codex",
                        "timeout_seconds": 0,
                        "sandbox": "workspace-write",
                        "model": "gpt-5-codex",
                    },
                )
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(connection, project_id, goal_id, "agent_reviewer", "Run misconfigured OpenAI Codex adapter")
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.post(
                "/api/providers/openai_codex/actions/run-task",
                json={
                    "project_id": project_id,
                    "agent_id": "agent_reviewer",
                    "task_id": task_id,
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("timeout_seconds must be greater than zero", response.json()["detail"])

    def test_provider_run_task_rejects_non_string_provider_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Runtime Test", description="Provider runtime test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = self._set_provider_config(
                    connection,
                    "openai_codex",
                    {
                        "mode": "codex_cli",
                        "cli_command": 123,
                        "timeout_seconds": 120,
                        "sandbox": "workspace-write",
                        "model": "gpt-5-codex",
                    },
                )
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(connection, project_id, goal_id, "agent_reviewer", "Run invalid OpenAI Codex adapter")
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.post(
                "/api/providers/openai_codex/actions/run-task",
                json={
                    "project_id": project_id,
                    "agent_id": "agent_reviewer",
                    "task_id": task_id,
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("cli_command must be a string", response.json()["detail"])

    def test_provider_run_task_rejects_blank_claude_permission_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Runtime Test", description="Provider runtime test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = self._set_provider_config(
                    connection,
                    "claude_code",
                    {
                        "mode": "claude_cli",
                        "cli_command": "claude",
                        "timeout_seconds": 120,
                        "permission_mode": "",
                        "model": "sonnet",
                    },
                )
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(connection, project_id, goal_id, "agent_researcher", "Run invalid Claude adapter")
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            response = client.post(
                "/api/providers/claude_code/actions/run-task",
                json={
                    "project_id": project_id,
                    "agent_id": "agent_researcher",
                    "task_id": task_id,
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("permission_mode must not be empty", response.json()["detail"])

    def test_openai_codex_cli_mode_executes_real_command_path_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Codex CLI Test", description="Codex CLI test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = self._enable_openai_codex_cli(connection)
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(connection, project_id, goal_id, "agent_reviewer", "Run Codex CLI adapter")
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))

            os.environ["OPENAI_API_KEY"] = "test-openai-key"
            os.environ["UNRELATED_SECRET"] = "should-not-leak"

            def write_codex_output(command, cwd, capture_output, text, timeout, check, env):
                self.assertEqual(command[0:2], ["codex", "exec"])
                self.assertIn("--model", command)
                self.assertEqual(env["OPENAI_API_KEY"], "test-openai-key")
                self.assertNotIn("UNRELATED_SECRET", env)
                self.assertTrue(env["TMPDIR"].startswith(os.path.join(tmpdir, ".maas", "runtime")))
                self.assertEqual(env["MAAS_PROJECT_ROOT"], tmpdir)
                output_file = command[command.index("-o") + 1]
                with open(output_file, "w", encoding="utf-8") as handle:
                    handle.write("Codex completed the task.")
                completed = mock.Mock()
                completed.returncode = 0
                completed.stdout = "{\"event\":\"done\"}\n"
                completed.stderr = ""
                return completed

            try:
                with mock.patch("maas.services.provider_runtime.subprocess.run", side_effect=write_codex_output) as run_mock:
                    response = client.post(
                        "/api/providers/openai_codex/actions/run-task",
                        json={
                            "project_id": project_id,
                            "agent_id": "agent_reviewer",
                            "task_id": task_id,
                        },
                    )
            finally:
                os.environ.pop("OPENAI_API_KEY", None)
                os.environ.pop("UNRELATED_SECRET", None)

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["execution"]["execution_mode"], "codex_cli")
            self.assertEqual(payload["provider"]["status"], "configured")
            self.assertEqual(run_mock.call_count, 1)

            connection = connect(project_paths(tmpdir))
            try:
                artifact = connection.execute(
                    """
                    SELECT artifact_type, metadata_json, path
                    FROM artifacts
                    WHERE task_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (task_id,),
                ).fetchone()
                with open(artifact["path"], "r", encoding="utf-8") as handle:
                    artifact_content = handle.read()
                activity_rows = connection.execute(
                    """
                    SELECT action, details_json
                    FROM activity_log
                    WHERE task_id = ? AND action IN (
                        'provider_adapter_started',
                        'provider_workspace_prepared',
                        'provider_execution_progress',
                        'provider_artifact_recorded',
                        'provider_adapter_completed'
                    )
                    ORDER BY rowid ASC
                    """,
                    (task_id,),
                ).fetchall()
            finally:
                connection.close()

            self.assertEqual(artifact["artifact_type"], "provider_report")
            self.assertIn("Codex completed the task.", artifact_content)
            artifact_metadata = json.loads(artifact["metadata_json"])
            self.assertEqual(artifact_metadata["execution_mode"], "codex_cli")
            self.assertEqual(len(activity_rows), 5)
            self.assertTrue(
                all(json.loads(row["details_json"]).get("external_runtime") == "codex_cli" for row in activity_rows)
            )

    def test_claude_code_cli_mode_executes_real_command_path_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Claude CLI Test", description="Claude CLI test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = self._enable_claude_code_cli(connection)
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(connection, project_id, goal_id, "agent_researcher", "Run Claude CLI adapter")
                connection.commit()
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))

            os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key"
            os.environ["UNRELATED_SECRET"] = "should-not-leak"

            def write_claude_output(command, cwd, capture_output, text, timeout, check, env):
                self.assertEqual(command[0:2], ["claude", "-p"])
                self.assertIn("--permission-mode", command)
                self.assertIn("--add-dir", command)
                self.assertEqual(env["ANTHROPIC_API_KEY"], "test-anthropic-key")
                self.assertNotIn("UNRELATED_SECRET", env)
                self.assertTrue(env["TMPDIR"].startswith(os.path.join(tmpdir, ".maas", "runtime")))
                self.assertEqual(env["MAAS_PROJECT_ROOT"], tmpdir)
                completed = mock.Mock()
                completed.returncode = 0
                completed.stdout = "Claude completed the task.\n"
                completed.stderr = ""
                return completed

            try:
                with mock.patch("maas.services.provider_runtime.subprocess.run", side_effect=write_claude_output) as run_mock:
                    response = client.post(
                        "/api/providers/claude_code/actions/run-task",
                        json={
                            "project_id": project_id,
                            "agent_id": "agent_researcher",
                            "task_id": task_id,
                        },
                    )
            finally:
                os.environ.pop("ANTHROPIC_API_KEY", None)
                os.environ.pop("UNRELATED_SECRET", None)

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["execution"]["execution_mode"], "claude_cli")
            self.assertEqual(payload["provider"]["status"], "configured")
            self.assertEqual(run_mock.call_count, 1)

            connection = connect(project_paths(tmpdir))
            try:
                artifact = connection.execute(
                    """
                    SELECT artifact_type, metadata_json, path
                    FROM artifacts
                    WHERE task_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (task_id,),
                ).fetchone()
                with open(artifact["path"], "r", encoding="utf-8") as handle:
                    artifact_content = handle.read()
                activity_rows = connection.execute(
                    """
                    SELECT action, details_json
                    FROM activity_log
                    WHERE task_id = ? AND action IN (
                        'provider_adapter_started',
                        'provider_workspace_prepared',
                        'provider_execution_progress',
                        'provider_artifact_recorded',
                        'provider_adapter_completed'
                    )
                    ORDER BY rowid ASC
                    """,
                    (task_id,),
                ).fetchall()
            finally:
                connection.close()

            self.assertEqual(artifact["artifact_type"], "provider_report")
            self.assertIn("Claude completed the task.", artifact_content)
            artifact_metadata = json.loads(artifact["metadata_json"])
            self.assertEqual(artifact_metadata["execution_mode"], "claude_cli")
            self.assertEqual(len(activity_rows), 5)
            self.assertTrue(
                all(json.loads(row["details_json"]).get("external_runtime") == "claude_cli" for row in activity_rows)
            )

    def test_provider_run_task_rejects_paths_outside_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Path Test", description="Provider path test", project_type="custom")
            client = TestClient(create_app(tmpdir))
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
            finally:
                connection.close()

            invalid_cases = [
                ("/tmp/escape.txt", "agent_allocator"),
                ("../escape.txt", "agent_researcher"),
                ("../../etc/passwd", "agent_reviewer"),
            ]
            for invalid_path, agent_id in invalid_cases:
                connection = connect(project_paths(tmpdir))
                try:
                    task_id = _insert_assigned_task(
                        connection, project_id, goal_id, agent_id, "Run adapter with invalid path {0}".format(invalid_path)
                    )
                    connection.commit()
                finally:
                    connection.close()

                response = client.post(
                    "/api/providers/python_script/actions/run-task",
                    json={
                        "project_id": project_id,
                        "agent_id": agent_id,
                        "task_id": task_id,
                        "artifact_path": invalid_path,
                    },
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn(".maas/artifacts", response.json()["detail"])
                connection = connect(project_paths(tmpdir))
                try:
                    session_count = connection.execute(
                        "SELECT COUNT(*) AS count FROM sessions WHERE task_id = ?",
                        (task_id,),
                    ).fetchone()["count"]
                    self.assertEqual(session_count, 0)
                finally:
                    connection.close()

    def test_provider_run_task_does_not_write_artifact_when_session_start_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Atomicity Test", description="Provider atomicity test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(
                    connection, project_id, goal_id, "agent_allocator", "Run adapter with rejected assignment"
                )
                connection.execute(
                    "UPDATE tasks SET assigned_agent_id = 'agent_reviewer' WHERE task_id = ?",
                    (task_id,),
                )
                connection.commit()
            finally:
                connection.close()

            artifact_name = "should-not-exist.txt"
            artifact_full_path = os.path.join(tmpdir, ".maas", "artifacts", artifact_name)
            client = TestClient(create_app(tmpdir))
            response = client.post(
                "/api/providers/python_script/actions/run-task",
                json={
                    "project_id": project_id,
                    "agent_id": "agent_allocator",
                    "task_id": task_id,
                    "artifact_path": artifact_name,
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertFalse(os.path.exists(artifact_full_path))

    def test_provider_run_task_marks_session_failed_and_cleans_up_untracked_artifact_on_runtime_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Failure Test", description="Provider failure test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(
                    connection, project_id, goal_id, "agent_allocator", "Run adapter with runtime failure"
                )
                connection.commit()
            finally:
                connection.close()

            artifact_name = "provider-failure.txt"
            artifact_full_path = os.path.join(tmpdir, ".maas", "artifacts", artifact_name)

            connection = connect(project_paths(tmpdir))
            try:
                with self.assertRaises(RuntimeError):
                    with mock.patch(
                        "maas.services.provider_runtime.produce_artifact",
                        side_effect=RuntimeError("artifact store unavailable"),
                    ):
                        run_provider_task(
                            connection,
                            project_paths=project_paths(tmpdir),
                            project_id=project_id,
                            agent_id="agent_allocator",
                            task_id=task_id,
                            provider_type="python_script",
                            artifact_path=artifact_name,
                        )
            finally:
                connection.close()

            self.assertFalse(os.path.exists(artifact_full_path))

            connection = connect(project_paths(tmpdir))
            try:
                session = connection.execute(
                    """
                    SELECT status, status_message
                    FROM sessions
                    WHERE task_id = ?
                    ORDER BY started_at DESC
                    LIMIT 1
                    """,
                    (task_id,),
                ).fetchone()
                task = connection.execute(
                    "SELECT status, review_state FROM tasks WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                failure = connection.execute(
                    """
                    SELECT failure_type, summary
                    FROM failure_log
                    WHERE task_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (task_id,),
                ).fetchone()
                failed_activity = connection.execute(
                    """
                    SELECT details_json
                    FROM activity_log
                    WHERE task_id = ? AND action = 'provider_adapter_failed'
                    ORDER BY rowid DESC
                    LIMIT 1
                    """,
                    (task_id,),
                ).fetchone()

                self.assertEqual(session["status"], "failed")
                self.assertIn("artifact store unavailable", session["status_message"])
                self.assertEqual(task["status"], "blocked")
                self.assertEqual(task["review_state"], "session_failed")
                self.assertEqual(failure["failure_type"], "session_failed")
                self.assertIn("artifact store unavailable", failure["summary"])
                self.assertEqual(json.loads(failed_activity["details_json"])["phase"], "session_failed")
            finally:
                connection.close()

    def test_provider_run_task_auto_retries_failed_session_when_policy_allows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Failed Retry Test", description="Provider failed retry test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = self._update_recovery_config(
                    connection,
                    auto_retry_failed_sessions=True,
                    max_failed_session_retries=1,
                    failed_session_retry_cooldown_seconds=75,
                    retry_backoff_multiplier=2,
                    retry_backoff_max_seconds=900,
                )
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(
                    connection, project_id, goal_id, "agent_allocator", "Run adapter with auto-retried runtime failure"
                )
                connection.commit()
            finally:
                connection.close()

            artifact_name = "provider-failed-retry.txt"
            connection = connect(project_paths(tmpdir))
            try:
                with self.assertRaises(RuntimeError):
                    with mock.patch(
                        "maas.services.provider_runtime.produce_artifact",
                        side_effect=RuntimeError("artifact store unavailable"),
                    ):
                        run_provider_task(
                            connection,
                            project_paths=project_paths(tmpdir),
                            project_id=project_id,
                            agent_id="agent_allocator",
                            task_id=task_id,
                            provider_type="python_script",
                            artifact_path=artifact_name,
                        )
            finally:
                connection.close()

            connection = connect(project_paths(tmpdir))
            try:
                task = connection.execute(
                    """
                    SELECT status, review_state, retry_count, last_retry_reason, next_retry_at, next_retry_reason
                    FROM tasks
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
                failure = connection.execute(
                    """
                    SELECT failure_type, summary
                    FROM failure_log
                    WHERE task_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (task_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(task["status"], "planned")
            self.assertEqual(task["review_state"], "retry_backoff")
            self.assertEqual(task["retry_count"], 1)
            self.assertEqual(task["last_retry_reason"], "session_failed")
            self.assertEqual(task["next_retry_reason"], "session_failed")
            self.assertIsNotNone(task["next_retry_at"])
            self.assertEqual(failure["failure_type"], "session_failed")
            self.assertIn("artifact store unavailable", failure["summary"])

    def test_provider_run_task_handles_invalid_failed_retry_config_during_failure_teardown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(
                tmpdir,
                name="Provider Invalid Recovery Config Test",
                description="Provider invalid recovery config test",
                project_type="custom",
            )
            connection = connect(project_paths(tmpdir))
            try:
                project_id = self._update_recovery_config(
                    connection,
                    auto_retry_failed_sessions=True,
                    max_failed_session_retries="",
                    failed_session_retry_cooldown_seconds="",
                )
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(
                    connection, project_id, goal_id, "agent_allocator", "Run adapter with invalid failed retry config"
                )
                connection.commit()
            finally:
                connection.close()

            connection = connect(project_paths(tmpdir))
            try:
                with self.assertRaises(RuntimeError):
                    with mock.patch(
                        "maas.services.provider_runtime.produce_artifact",
                        side_effect=RuntimeError("artifact store unavailable"),
                    ):
                        run_provider_task(
                            connection,
                            project_paths=project_paths(tmpdir),
                            project_id=project_id,
                            agent_id="agent_allocator",
                            task_id=task_id,
                            provider_type="python_script",
                            artifact_path="provider-invalid-config.txt",
                        )
            finally:
                connection.close()

            connection = connect(project_paths(tmpdir))
            try:
                session = connection.execute(
                    """
                    SELECT status, status_message
                    FROM sessions
                    WHERE task_id = ?
                    ORDER BY started_at DESC
                    LIMIT 1
                    """,
                    (task_id,),
                ).fetchone()
                task = connection.execute(
                    """
                    SELECT status, review_state, retry_count, last_retry_reason, next_retry_at, next_retry_reason
                    FROM tasks
                    WHERE task_id = ?
                    """,
                    (task_id,),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(session["status"], "failed")
            self.assertIn("artifact store unavailable", session["status_message"])
            self.assertEqual(task["status"], "planned")
            self.assertEqual(task["review_state"], "retry_backoff")
            self.assertEqual(task["retry_count"], 1)
            self.assertEqual(task["last_retry_reason"], "session_failed")
            self.assertIsNotNone(task["next_retry_at"])
            self.assertEqual(task["next_retry_reason"], "session_failed")

    def test_provider_run_task_restores_preexisting_artifact_on_runtime_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Provider Preserve Artifact Test", description="Provider preserve test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(
                    connection, project_id, goal_id, "agent_allocator", "Run adapter against existing artifact"
                )
                connection.commit()
            finally:
                connection.close()

            artifact_name = "existing-provider-artifact.txt"
            artifact_full_path = os.path.join(tmpdir, ".maas", "artifacts", artifact_name)
            with open(artifact_full_path, "w", encoding="utf-8") as handle:
                handle.write("preexisting artifact content")

            connection = connect(project_paths(tmpdir))
            try:
                with self.assertRaises(RuntimeError):
                    with mock.patch(
                        "maas.services.provider_runtime.produce_artifact",
                        side_effect=RuntimeError("artifact store unavailable"),
                    ):
                        run_provider_task(
                            connection,
                            project_paths=project_paths(tmpdir),
                            project_id=project_id,
                            agent_id="agent_allocator",
                            task_id=task_id,
                            provider_type="python_script",
                            artifact_path=artifact_name,
                        )
            finally:
                connection.close()

            self.assertTrue(os.path.exists(artifact_full_path))
            with open(artifact_full_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "preexisting artifact content")

    def test_openai_codex_cli_failure_preserves_preexisting_artifact(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Codex CLI Failure Test", description="Codex CLI failure test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = self._enable_openai_codex_cli(connection)
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(connection, project_id, goal_id, "agent_reviewer", "Run failing Codex CLI adapter")
                connection.commit()
            finally:
                connection.close()

            artifact_name = "existing-codex-artifact.txt"
            artifact_full_path = os.path.join(tmpdir, ".maas", "artifacts", artifact_name)
            with open(artifact_full_path, "w", encoding="utf-8") as handle:
                handle.write("preexisting codex artifact")

            connection = connect(project_paths(tmpdir))
            try:
                with self.assertRaises(RuntimeError):
                    with mock.patch(
                        "maas.services.provider_runtime.subprocess.run",
                        return_value=mock.Mock(returncode=1, stdout="", stderr="codex exploded"),
                    ):
                        run_provider_task(
                            connection,
                            project_paths=project_paths(tmpdir),
                            project_id=project_id,
                            agent_id="agent_reviewer",
                            task_id=task_id,
                            provider_type="openai_codex",
                            artifact_path=artifact_name,
                        )
            finally:
                connection.close()

            self.assertTrue(os.path.exists(artifact_full_path))
            with open(artifact_full_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "preexisting codex artifact")

    def test_claude_code_cli_failure_preserves_preexisting_artifact(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Claude CLI Failure Test", description="Claude CLI failure test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = self._enable_claude_code_cli(connection)
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(connection, project_id, goal_id, "agent_researcher", "Run failing Claude CLI adapter")
                connection.commit()
            finally:
                connection.close()

            artifact_name = "existing-claude-artifact.txt"
            artifact_full_path = os.path.join(tmpdir, ".maas", "artifacts", artifact_name)
            with open(artifact_full_path, "w", encoding="utf-8") as handle:
                handle.write("preexisting claude artifact")

            connection = connect(project_paths(tmpdir))
            try:
                with self.assertRaises(RuntimeError):
                    with mock.patch(
                        "maas.services.provider_runtime.subprocess.run",
                        return_value=mock.Mock(returncode=1, stdout="", stderr="claude exploded"),
                    ):
                        run_provider_task(
                            connection,
                            project_paths=project_paths(tmpdir),
                            project_id=project_id,
                            agent_id="agent_researcher",
                            task_id=task_id,
                            provider_type="claude_code",
                            artifact_path=artifact_name,
                        )
            finally:
                connection.close()

            self.assertTrue(os.path.exists(artifact_full_path))
            with open(artifact_full_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "preexisting claude artifact")

    def test_providers_endpoint_classifies_codex_timeout_failures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Codex Timeout Test", description="Codex timeout test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = self._enable_openai_codex_cli(connection)
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(connection, project_id, goal_id, "agent_reviewer", "Run timed out Codex CLI adapter")
                connection.commit()
            finally:
                connection.close()

            connection = connect(project_paths(tmpdir))
            try:
                with self.assertRaises(Exception):
                    with mock.patch(
                        "maas.services.provider_runtime.subprocess.run",
                        side_effect=subprocess.TimeoutExpired(cmd=["codex", "exec"], timeout=120),
                    ):
                        run_provider_task(
                            connection,
                            project_paths=project_paths(tmpdir),
                            project_id=project_id,
                            agent_id="agent_reviewer",
                            task_id=task_id,
                            provider_type="openai_codex",
                        )
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            payload = client.get("/api/providers").json()
            providers = {provider["id"]: provider for provider in payload["providers"]}
            recent_run = providers["openai_codex"]["recent_runs"][0]
            run_summary = providers["openai_codex"]["run_summary"]

            self.assertEqual(recent_run["status"], "failed")
            self.assertEqual(recent_run["execution_mode"], "codex_cli")
            self.assertEqual(recent_run["external_runtime"], "codex_cli")
            self.assertEqual(recent_run["failure_kind"], "timeout")
            self.assertIn("timed out", recent_run["failure_detail"])
            self.assertEqual(run_summary["timeout_failures"], 1)
            self.assertEqual(run_summary["latest_failure_kind"], "timeout")

    def test_providers_endpoint_classifies_claude_nonzero_exit_failures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="Claude Exit Test", description="Claude exit test", project_type="custom")
            connection = connect(project_paths(tmpdir))
            try:
                project_id = self._enable_claude_code_cli(connection)
                goal_id = connection.execute("SELECT goal_id FROM goals ORDER BY created_at ASC LIMIT 1").fetchone()["goal_id"]
                task_id = _insert_assigned_task(connection, project_id, goal_id, "agent_researcher", "Run nonzero Claude CLI adapter")
                connection.commit()
            finally:
                connection.close()

            connection = connect(project_paths(tmpdir))
            try:
                with self.assertRaises(Exception):
                    with mock.patch(
                        "maas.services.provider_runtime.subprocess.run",
                        return_value=mock.Mock(returncode=7, stdout="", stderr="permission denied"),
                    ):
                        run_provider_task(
                            connection,
                            project_paths=project_paths(tmpdir),
                            project_id=project_id,
                            agent_id="agent_researcher",
                            task_id=task_id,
                            provider_type="claude_code",
                        )
            finally:
                connection.close()

            client = TestClient(create_app(tmpdir))
            payload = client.get("/api/providers").json()
            providers = {provider["id"]: provider for provider in payload["providers"]}
            recent_run = providers["claude_code"]["recent_runs"][0]
            run_summary = providers["claude_code"]["run_summary"]

            self.assertEqual(recent_run["status"], "failed")
            self.assertEqual(recent_run["execution_mode"], "claude_cli")
            self.assertEqual(recent_run["external_runtime"], "claude_cli")
            self.assertEqual(recent_run["failure_kind"], "nonzero_exit")
            self.assertIn("status 7", recent_run["failure_detail"])
            self.assertEqual(run_summary["nonzero_exit_failures"], 1)
            self.assertEqual(run_summary["latest_failure_kind"], "nonzero_exit")

if __name__ == "__main__":
    unittest.main()
