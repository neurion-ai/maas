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
            self.assertIn("filter_options", board)
            self.assertIn("selected_filters", board)

    def test_assigned_tasks_stay_visible_in_ready_column(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Assigned Board Test", description="Assigned board test", project_type="custom")
            connection = connect(result["paths"])
            try:
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Wire the scheduler and board read model'"
                ).fetchone()["task_id"]
                connection.execute(
                    "UPDATE tasks SET status = 'assigned' WHERE task_id = ?",
                    (task_id,),
                )
                connection.commit()
                board = fetch_board(connection)
            finally:
                connection.close()

            ready_column = next(column for column in board["columns"] if column["key"] == "ready")
            matching_cards = [task for task in ready_column["tasks"] if task["task_id"] == task_id]
            self.assertEqual(len(matching_cards), 1)
            self.assertEqual(matching_cards[0]["status"], "assigned")


if __name__ == "__main__":
    unittest.main()
