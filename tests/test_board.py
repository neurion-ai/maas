import os
import tempfile
import unittest

from maas.db import connect
from maas.ids import generate_id
from maas.services.board import fetch_board
from maas.services.bootstrap import bootstrap_project
from maas.services.scheduler import refresh_ready_tasks


class BoardReadModelTest(unittest.TestCase):
    def test_board_cards_include_scheduler_rationale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Board Scheduler Test", description="Board scheduler test", project_type="custom")
            connection = connect(result["paths"])
            try:
                refresh_ready_tasks(connection)
                ready_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Define project workspace contracts'"
                ).fetchone()["task_id"]
                backoff_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Bootstrap migration runner'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'ready',
                        assigned_agent_id = NULL
                    WHERE task_id = ?
                    """,
                    (ready_task_id,),
                )
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'planned',
                        review_state = 'retry_backoff',
                        next_retry_at = '2999-01-01 00:00:00',
                        next_retry_reason = 'session_timed_out'
                    WHERE task_id = ?
                    """,
                    (backoff_task_id,),
                )
                connection.commit()
                board = fetch_board(connection)
            finally:
                connection.close()

            cards = {
                task["task_id"]: task
                for column in board["columns"]
                for task in column["tasks"]
            }
            ready_card = cards[ready_task_id]
            self.assertEqual(ready_card["scheduler_status"], "ready_for_allocation")
            self.assertIsNotNone(ready_card["scheduler_summary"])
            self.assertIsNotNone(ready_card["scheduler_score"])
            self.assertGreaterEqual(ready_card["scheduler_rank"], 1)
            self.assertTrue(any(factor["key"] == "priority" for factor in ready_card["scheduler_factors"]))
            self.assertIsNotNone(ready_card["scheduler_agent"])

            backoff_card = cards[backoff_task_id]
            self.assertEqual(backoff_card["scheduler_status"], "retry_backoff")
            self.assertIn("Cooling down", backoff_card["scheduler_summary"])

    def test_board_scheduler_rationale_honors_assignment_lock_for_ready_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Board Assignment Lock Test", description="Board assignment lock test", project_type="custom")
            connection = connect(result["paths"])
            try:
                project_id = connection.execute("SELECT project_id FROM projects LIMIT 1").fetchone()["project_id"]
                ready_task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Define project workspace contracts'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    INSERT INTO agents (
                        agent_id, project_id, role, display_name, status, permissions_json
                    ) VALUES (?, ?, 'builder', ?, 'idle', '{"board_actions": true}')
                    """,
                    ("agent_board_locked", project_id, "Board Locked Builder"),
                )
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = 'ready',
                        assigned_agent_id = 'agent_board_locked'
                    WHERE task_id = ?
                    """,
                    (ready_task_id,),
                )
                connection.commit()
                board = fetch_board(connection)
            finally:
                connection.close()

            card = next(
                task
                for column in board["columns"]
                for task in column["tasks"]
                if task["task_id"] == ready_task_id
            )
            self.assertEqual(card["scheduler_status"], "reserved_for_assigned_agent")
            self.assertEqual(card["scheduler_agent"]["id"], "agent_board_locked")
            self.assertIsNone(card["scheduler_rank"])
            self.assertIn("reserved for assigned agent", card["scheduler_summary"])

    def test_board_cards_include_adaptive_replan_guidance_for_brownfield_workflow_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Board Brownfield Guidance Test", description="Board brownfield guidance test", project_type="custom")
            connection = connect(result["paths"])
            try:
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Define project workspace contracts'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET title = 'Validate imported workflow: ci',
                        status = 'ready',
                        assigned_agent_id = NULL,
                        retry_count = 2,
                        review_state = 'retry_backoff',
                        next_retry_at = '2099-01-01 00:00:00',
                        next_retry_reason = 'session_failed'
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
                connection.commit()
                board = fetch_board(connection)
            finally:
                connection.close()

            card = next(
                task
                for column in board["columns"]
                for task in column["tasks"]
                if task["task_id"] == task_id
            )
            factor_keys = {factor["key"] for factor in card["scheduler_factors"]}
            self.assertIn("brownfield_bonus", factor_keys)
            self.assertEqual(card["replan_strategy"], "validate_imported_workflow")
            self.assertIn("workflow", card["replan_summary"].lower())

    def test_board_cards_include_brownfield_scope_and_validation_commands(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
            with open(os.path.join(tmpdir, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("# Brownfield Board\n")
            with open(os.path.join(tmpdir, "Makefile"), "w", encoding="utf-8") as handle:
                handle.write("test:\n\tpytest\n")
            with open(os.path.join(tmpdir, "src", "app.py"), "w", encoding="utf-8") as handle:
                handle.write("print('ok')\n")

            result = bootstrap_project(
                tmpdir,
                name="Board Brownfield Scope Test",
                description="Board brownfield scope test",
                project_type="custom",
            )
            connection = connect(result["paths"])
            try:
                board = fetch_board(connection)
            finally:
                connection.close()

            workflow_card = next(
                task
                for column in board["columns"]
                for task in column["tasks"]
                if task["title"] == "Validate imported workflow: test"
            )
            map_card = next(
                task
                for column in board["columns"]
                for task in column["tasks"]
                if task["title"] == "Map imported source area: src"
            )
            self.assertIn("Makefile", workflow_card["scoped_paths"])
            self.assertIn("make test", workflow_card["validation_commands"])
            self.assertIn("src/app.py", map_card["scoped_paths"])

    def test_board_cards_match_fallback_brownfield_workflow_titles_without_colon(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Board Brownfield Workflow Fallback Test", description="Board brownfield workflow fallback test", project_type="custom")
            connection = connect(result["paths"])
            try:
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Define project workspace contracts'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET title = 'Validate imported workflow entrypoints',
                        status = 'ready',
                        assigned_agent_id = NULL
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
                connection.commit()
                board = fetch_board(connection)
            finally:
                connection.close()

            card = next(
                task
                for column in board["columns"]
                for task in column["tasks"]
                if task["task_id"] == task_id
            )
            factor_keys = {factor["key"] for factor in card["scheduler_factors"]}
            self.assertIn("brownfield_bonus", factor_keys)
            self.assertEqual(card["replan_strategy"], "validate_imported_workflow")

    def test_board_returns_expected_core_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Board Test", description="Board test", project_type="custom")
            connection = connect(result["paths"])
            try:
                board = fetch_board(connection)
            finally:
                connection.close()

            labels = [column["title"] for column in board["columns"]]
            self.assertEqual(labels, ["Planned", "Ready", "In Progress", "Review", "Blocked", "Done", "Cancelled"])
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

    def test_board_cards_include_failure_rollup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Board Failure Test", description="Board failure test", project_type="custom")
            connection = connect(result["paths"])
            try:
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    INSERT INTO failure_log (
                        failure_id, project_id, task_id, session_id, agent_id, failure_type, summary, detail_json
                    )
                    SELECT ?, project_id, ?, session_id, agent_id, 'session_failed', 'Board-visible failure', '{}'
                    FROM sessions
                    WHERE task_id = ?
                    LIMIT 1
                    """,
                    (generate_id("fail"), task_id, task_id),
                )
                connection.commit()
                board = fetch_board(connection)
            finally:
                connection.close()

            matching_cards = [
                task
                for column in board["columns"]
                for task in column["tasks"]
                if task["task_id"] == task_id
            ]
            self.assertEqual(matching_cards[0]["failure_count"], 1)
            self.assertIsNotNone(matching_cards[0]["latest_failure_at"])

    def test_board_cards_include_retry_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = bootstrap_project(tmpdir, name="Board Retry Test", description="Board retry test", project_type="custom")
            connection = connect(result["paths"])
            try:
                task_id = connection.execute(
                    "SELECT task_id FROM tasks WHERE title = 'Implement FastAPI board endpoint'"
                ).fetchone()["task_id"]
                connection.execute(
                    """
                    UPDATE tasks
                    SET retry_count = 2,
                        last_retry_at = CURRENT_TIMESTAMP,
                        last_retry_reason = 'session_timed_out',
                        next_retry_at = '2999-01-01 00:00:00',
                        next_retry_reason = 'session_timed_out'
                    WHERE task_id = ?
                    """,
                    (task_id,),
                )
                connection.commit()
                board = fetch_board(connection)
            finally:
                connection.close()

            matching_cards = [
                task
                for column in board["columns"]
                for task in column["tasks"]
                if task["task_id"] == task_id
            ]
            self.assertEqual(matching_cards[0]["retry_count"], 2)
            self.assertEqual(matching_cards[0]["last_retry_reason"], "session_timed_out")
            self.assertIsNotNone(matching_cards[0]["last_retry_at"])
            self.assertEqual(matching_cards[0]["next_retry_at"], "2999-01-01 00:00:00")
            self.assertEqual(matching_cards[0]["next_retry_reason"], "session_timed_out")


if __name__ == "__main__":
    unittest.main()
