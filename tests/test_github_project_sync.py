import tempfile
import unittest
from unittest import mock

from maas.db import connect, project_paths
from maas.services.bootstrap import bootstrap_project
from maas.services.github_project_sync import inspect_github_project_truth, sync_github_project_truth


class GithubProjectSyncTest(unittest.TestCase):
    def test_inspect_github_project_truth_detects_stale_closed_issue_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="GitHub Sync Test", description="github sync", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                with mock.patch(
                    "maas.services.github_project_sync._remote_repo_name",
                    return_value="neurion-ai/maas",
                ), mock.patch(
                    "maas.services.github_project_sync._is_service_repo_root",
                    return_value=True,
                ), mock.patch(
                    "maas.services.github_project_sync._project_snapshot",
                    return_value=(
                        {
                            "id": "PVT_project",
                            "fields": {
                                "nodes": [
                                    {"id": "status", "name": "Status", "options": [{"id": "done", "name": "Done"}]},
                                    {"id": "review", "name": "Code Review", "options": [{"id": "passed", "name": "Passed"}]},
                                    {"id": "pr", "name": "PR", "options": [{"id": "merged", "name": "Merged"}]},
                                ]
                            },
                            "items": {
                                "nodes": [
                                    {
                                        "id": "item_1",
                                        "fieldValues": {
                                            "nodes": [
                                                {"name": "Pending", "field": {"name": "Code Review"}},
                                                {"name": "Open", "field": {"name": "PR"}},
                                                {"name": "Done", "field": {"name": "Status"}},
                                            ]
                                        },
                                        "content": {
                                            "number": 130,
                                            "state": "CLOSED",
                                            "repository": {"nameWithOwner": "neurion-ai/maas"},
                                            "closedByPullRequestsReferences": {
                                                "nodes": [{"number": 135, "state": "MERGED", "mergedAt": "2026-04-04T00:00:00Z"}]
                                            },
                                        },
                                    }
                                ]
                            },
                        },
                        {},
                        {"items_truncated": False, "open_prs_truncated": False},
                    ),
                ):
                    payload = inspect_github_project_truth(connection, project_id)
            finally:
                connection.close()

            self.assertTrue(payload["enabled"])
            self.assertEqual(payload["drift_count"], 1)
            self.assertEqual(payload["updates"][0]["desired"]["PR"], "Merged")
            self.assertEqual(payload["updates"][0]["desired"]["Code Review"], "Passed")

    def test_sync_github_project_truth_updates_each_stale_field(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bootstrap_project(tmpdir, name="GitHub Sync Update Test", description="github sync update", project_type="custom")
            paths = project_paths(tmpdir)
            connection = connect(paths)
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                with mock.patch(
                    "maas.services.github_project_sync._remote_repo_name",
                    return_value="neurion-ai/maas",
                ), mock.patch(
                    "maas.services.github_project_sync._is_service_repo_root",
                    return_value=True,
                ), mock.patch(
                    "maas.services.github_project_sync._project_snapshot",
                    return_value=(
                        {
                            "id": "PVT_project",
                            "fields": {
                                "nodes": [
                                    {"id": "status", "name": "Status", "options": [{"id": "done", "name": "Done"}]},
                                    {"id": "review", "name": "Code Review", "options": [{"id": "passed", "name": "Passed"}]},
                                    {"id": "pr", "name": "PR", "options": [{"id": "merged", "name": "Merged"}]},
                                ]
                            },
                            "items": {
                                "nodes": [
                                    {
                                        "id": "item_1",
                                        "fieldValues": {
                                            "nodes": [
                                                {"name": "Todo", "field": {"name": "Status"}},
                                                {"name": "Pending", "field": {"name": "Code Review"}},
                                                {"name": "Open", "field": {"name": "PR"}},
                                            ]
                                        },
                                        "content": {
                                            "number": 129,
                                            "state": "CLOSED",
                                            "repository": {"nameWithOwner": "neurion-ai/maas"},
                                            "closedByPullRequestsReferences": {
                                                "nodes": [{"number": 134, "state": "MERGED", "mergedAt": "2026-04-04T00:00:00Z"}]
                                            },
                                        },
                                    }
                                ]
                            },
                        },
                        {},
                        {"items_truncated": False, "open_prs_truncated": False},
                    ),
                ), mock.patch(
                    "maas.services.github_project_sync._gh_graphql",
                    return_value={"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "item_1"}}},
                ) as graphql_mock:
                    payload = sync_github_project_truth(connection, project_id)
            finally:
                connection.close()

            self.assertEqual(payload["updated_count"], 3)
            self.assertEqual(graphql_mock.call_count, 3)
