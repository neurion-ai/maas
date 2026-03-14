import tempfile
import unittest

from maas.db import connect
from maas.services.board import fetch_board
from maas.services.bootstrap import bootstrap_project


class BoardReadModelTest(unittest.TestCase):
    def test_board_returns_expected_core_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Board Test", description="Board test", project_type="custom")
            connection = connect(result["paths"])
            try:
                board = fetch_board(connection)
            finally:
                connection.close()

            labels = [column["title"] for column in board["columns"]]
            self.assertEqual(labels, ["Planned", "Ready", "In Progress", "Review", "Blocked", "Done"])
            self.assertGreater(board["summary"]["total_tasks"], 0)
            self.assertIn("generated_at", board)
            self.assertIn("filters", board)


if __name__ == "__main__":
    unittest.main()
