import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.services.bootstrap import bootstrap_project


class RepoBrowserApiTest(unittest.TestCase):
    def test_repo_tree_and_file_preview_expose_brownfield_source_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "src", "utils"), exist_ok=True)
            with open(os.path.join(tmpdir, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("# Imported Repo\n")
            with open(os.path.join(tmpdir, "pyproject.toml"), "w", encoding="utf-8") as handle:
                handle.write("[project]\nname='imported'\n")
            with open(os.path.join(tmpdir, "src", "app.py"), "w", encoding="utf-8") as handle:
                handle.write("print('hello brownfield')\n")
            with open(os.path.join(tmpdir, "src", "utils", "helpers.py"), "w", encoding="utf-8") as handle:
                handle.write("def helper():\n    return 'ok'\n")

            bootstrap_project(tmpdir, name="Repo Browser Test", description="repo browser", project_type="custom")
            client = TestClient(create_app(tmpdir))

            root_tree = client.get("/api/repo/tree")
            self.assertEqual(root_tree.status_code, 200)
            root_entries = root_tree.json()["entries"]
            self.assertTrue(any(item["path"] == "src" and item["kind"] == "directory" for item in root_entries))
            self.assertFalse(any(item["path"] == ".maas" for item in root_entries))
            self.assertFalse(any(item["path"] == "project.yaml" for item in root_entries))

            src_tree = client.get("/api/repo/tree", params={"path": "src"})
            self.assertEqual(src_tree.status_code, 200)
            src_entries = src_tree.json()["entries"]
            self.assertTrue(any(item["path"] == "src/app.py" and item["previewable"] for item in src_entries))
            self.assertTrue(any(item["path"] == "src/utils" and item["kind"] == "directory" for item in src_entries))

            file_preview = client.get("/api/repo/file", params={"path": "src/app.py"})
            self.assertEqual(file_preview.status_code, 200)
            payload = file_preview.json()
            self.assertEqual(payload["content_kind"], "text")
            self.assertIn("hello brownfield", payload["content"])
            self.assertEqual(payload["parent_path"], "src")

    def test_repo_browser_rejects_escaping_or_non_file_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
            with open(os.path.join(tmpdir, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("# Imported Repo\n")
            with open(os.path.join(tmpdir, "src", "app.py"), "w", encoding="utf-8") as handle:
                handle.write("print('hello')\n")

            bootstrap_project(tmpdir, name="Repo Browser Guard Test", description="repo browser guard", project_type="custom")
            client = TestClient(create_app(tmpdir))

            escape_response = client.get("/api/repo/file", params={"path": "../README.md"})
            self.assertEqual(escape_response.status_code, 400)

            directory_response = client.get("/api/repo/file", params={"path": "src"})
            self.assertEqual(directory_response.status_code, 400)
