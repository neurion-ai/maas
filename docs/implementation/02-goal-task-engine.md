# Batch 2: Goal and Task Engine

## Scope

- goal tree persistence
- task DAG persistence through `task_dependencies`
- ready-task resolution for `blocks`
- review as a first-class task state
- acceptance criteria plumbing for `artifact_exists`, `test_passes`, `metric`, and `db_query`

## Non-Goals

- advanced replanning
- template learning
- merge/split automation

## Interface Notes

- scheduler returns task-first results
- board remains the main operational surface; goals stay inspectable separately

## Acceptance Tests

- blocked dependency prevents readiness
- completed blocker unlocks ready state
- review tasks remain visible on the board and in summary counters

