import json
import os
import subprocess
import tempfile
import unittest

from maas.db import connect, project_paths
from maas.ids import generate_id
from maas.services.bootstrap import bootstrap_project
from maas.services.git_workspaces import prepare_task_git_workspace
from maas.services.theater import fetch_theater
from testsupport import api_client


def _init_git_repo(root):
    subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "MAAS Tests"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class TheaterApiTest(unittest.TestCase):
    def _seed_theater_topology(self, tmpdir):
        bootstrap_project(tmpdir, name="Theater Topology Test", description="theater topology", project_type="custom")
        _init_git_repo(tmpdir)

        paths = project_paths(tmpdir)
        connection = connect(paths)
        try:
            tasks = connection.execute(
                """
                SELECT task_id, project_id, title, assigned_agent_id
                FROM tasks
                ORDER BY created_at ASC
                LIMIT 4
                """
            ).fetchall()
            active_task = tasks[0]
            delivery_task = tasks[1]
            review_task = tasks[2]
            done_task = tasks[3]
            agent_id = active_task["assigned_agent_id"]
            other_agent_id = connection.execute(
                """
                SELECT agent_id
                FROM agents
                WHERE project_id = ?
                  AND agent_id != ?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (active_task["project_id"], agent_id),
            ).fetchone()["agent_id"]

            connection.execute(
                """
                UPDATE tasks
                SET status = 'in_progress',
                    assigned_agent_id = ?
                WHERE task_id = ?
                """,
                (agent_id, active_task["task_id"]),
            )
            connection.execute(
                """
                UPDATE tasks
                SET status = 'review',
                    review_state = 'review_requested'
                WHERE task_id = ?
                """,
                (delivery_task["task_id"],),
            )
            connection.execute(
                """
                UPDATE tasks
                SET status = 'review',
                    review_state = 'review_requested'
                WHERE task_id = ?
                """,
                (review_task["task_id"],),
            )
            connection.execute(
                """
                UPDATE tasks
                SET status = 'done',
                    review_state = 'approved'
                WHERE task_id = ?
                """,
                (done_task["task_id"],),
            )

            active_workspace = prepare_task_git_workspace(
                connection,
                paths,
                active_task["task_id"],
                actor_id="agent_allocator",
                commit=False,
            )
            delivery_workspace = prepare_task_git_workspace(
                connection,
                paths,
                delivery_task["task_id"],
                actor_id="agent_allocator",
                commit=False,
            )

            session_id = generate_id("sess")
            connection.execute(
                """
                INSERT INTO sessions (
                    session_id, project_id, agent_id, task_id, status, provider_type, progress_pct,
                    status_message, last_heartbeat_at, started_at, ended_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, 'completed', 'openai_codex', 100,
                    'Earlier run finished', DATETIME('now', '-20 minutes'), DATETIME('now', '-30 minutes'), DATETIME('now', '-20 minutes'), CURRENT_TIMESTAMP
                )
                """,
                (generate_id("sess"), active_task["project_id"], agent_id, active_task["task_id"]),
            )
            connection.execute(
                """
                INSERT INTO sessions (
                    session_id, project_id, agent_id, task_id, status, provider_type, progress_pct,
                    status_message, last_heartbeat_at, started_at, ended_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, 'completed', 'openai_codex', 100,
                    'Historical run from another agent', DATETIME('now', '-10 minutes'), DATETIME('now', '-15 minutes'),
                    DATETIME('now', '-10 minutes'), CURRENT_TIMESTAMP
                )
                """,
                (generate_id("sess"), active_task["project_id"], other_agent_id, active_task["task_id"]),
            )

            connection.execute(
                """
                INSERT INTO sessions (
                    session_id, project_id, agent_id, task_id, status, provider_type, progress_pct,
                    status_message, last_heartbeat_at, started_at, ended_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, 'active', 'openai_codex', 48,
                    'Implementing topology view', CURRENT_TIMESTAMP, DATETIME('now', '-5 minutes'), NULL, CURRENT_TIMESTAMP
                )
                """,
                (session_id, active_task["project_id"], agent_id, active_task["task_id"]),
            )

            draft_path = os.path.join(tmpdir, "delivery-pr.md")
            with open(draft_path, "w", encoding="utf-8") as handle:
                handle.write("draft body\n")
            connection.execute(
                """
                INSERT INTO artifacts (
                    artifact_id, project_id, task_id, session_id, artifact_type, path, metadata_json
                ) VALUES (?, ?, ?, NULL, 'delivery_github_pr_sync', ?, ?)
                """,
                (
                    generate_id("art"),
                    delivery_task["project_id"],
                    delivery_task["task_id"],
                    draft_path,
                    json.dumps(
                        {
                            "github_pr": {
                                "mode": "updated",
                                "number": 999,
                                "url": "https://github.com/neurion-ai/maas/pull/999",
                                "state": "OPEN",
                                "is_draft": True,
                                "title": "[MAAS] Theater foundation",
                                "head_branch": delivery_workspace["branch_name"],
                                "base_branch": "main",
                            }
                        }
                    ),
                ),
            )
            connection.commit()
            return {
                "project_id": active_task["project_id"],
                "active_task_id": active_task["task_id"],
                "delivery_task_id": delivery_task["task_id"],
                "review_task_id": review_task["task_id"],
                "done_task_id": done_task["task_id"],
                "session_id": session_id,
                "active_agent_id": agent_id,
                "active_branch": active_workspace["branch_name"],
                "delivery_branch": delivery_workspace["branch_name"],
            }
        finally:
            connection.close()

    def _assert_topology_payload(self, payload, context):
        self.assertGreaterEqual(payload["summary"]["agent_count"], 1)
        self.assertGreaterEqual(payload["summary"]["active_run_count"], 1)
        self.assertGreaterEqual(payload["summary"]["branch_count"], 2)
        self.assertEqual(payload["summary"]["pull_request_count"], 1)

        active_issue = next(item for item in payload["issues"] if item["task_id"] == context["active_task_id"])
        delivery_issue = next(item for item in payload["issues"] if item["task_id"] == context["delivery_task_id"])
        review_issue = next(item for item in payload["issues"] if item["task_id"] == context["review_task_id"])
        done_issue = next(item for item in payload["issues"] if item["task_id"] == context["done_task_id"])
        self.assertEqual(active_issue["lane_key"], "in_progress")
        self.assertEqual(active_issue["current_run_session_id"], context["session_id"])
        self.assertEqual(active_issue["git_workspace_branch"], context["active_branch"])
        self.assertEqual(delivery_issue["lane_key"], "delivery")
        self.assertEqual(delivery_issue["github_pr_state"], "OPEN")
        self.assertEqual(review_issue["lane_key"], "review")
        self.assertEqual(done_issue["lane_key"], "done_recent")

        run_link = next(link for link in payload["links"]["issue_to_run"] if link["issue_id"] == context["active_task_id"])
        self.assertEqual(run_link["run_id"], context["session_id"])

        branch_ids = {branch["branch_name"] for branch in payload["branches"]}
        self.assertIn(context["active_branch"], branch_ids)
        self.assertIn(context["delivery_branch"], branch_ids)

        pr = payload["pull_requests"][0]
        self.assertEqual(pr["number"], 999)
        self.assertEqual(pr["head_branch"], context["delivery_branch"])
        self.assertEqual(pr["base_branch"], "main")

        active_agent = next(item for item in payload["agents"] if item["agent_id"] == context["active_agent_id"])
        self.assertEqual(active_agent["current_run_id"], context["session_id"])

    def test_fetch_theater_service_exposes_issue_run_branch_and_pr_topology(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            context = self._seed_theater_topology(tmpdir)
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                payload = fetch_theater(connection, paths, project_id=context["project_id"])
            finally:
                connection.close()

            self._assert_topology_payload(payload, context)

    def test_theater_exposes_issue_run_branch_and_pr_topology(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            context = self._seed_theater_topology(tmpdir)

            with api_client(tmpdir) as client:
                response = client.get("/api/theater")
                self.assertEqual(response.status_code, 200)
                payload = response.json()
            self._assert_topology_payload(payload, context)
