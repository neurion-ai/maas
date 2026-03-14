import os
import sqlite3
import tempfile
import unittest

from maas.services.bootstrap import bootstrap_project


class BootstrapProjectTest(unittest.TestCase):
    def test_bootstrap_creates_config_workspace_and_seeded_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Test MAAS", description="Bootstrap test", project_type="custom")
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "project.yaml")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, ".maas", "state.db")))
            self.assertTrue(os.path.exists(result["paths"].understanding_path))

            connection = sqlite3.connect(result["paths"].db_path)
            project_count = connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
            task_count = connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            connection.close()

            self.assertEqual(project_count, 1)
            self.assertGreaterEqual(task_count, 6)


if __name__ == "__main__":
    unittest.main()

