# Batch 2: Goal and Task Engine

## Status On `main`

- [ ] Batch 2 is only partially shipped on `main`.

## Shipped On `main`

- [x] Goal tree persistence
- [x] Task DAG persistence through `task_dependencies`
- [x] Ready-task resolution for `blocks`
- [x] Review as a first-class task state
- [x] Acceptance criteria plumbing for `artifact_exists`, `test_passes`, `metric`, and `db_query`
- [x] Task evaluation exposed through API and CLI surfaces
- [x] First-pass idle-agent allocation for ready work

## Still To Do On `main`

- [ ] Advanced replanning
- [ ] Template learning
- [ ] Task merge and split automation

## Interface Checklist

- [x] Scheduler returns task-first results
- [x] Board remains the main operational surface while goals stay inspectable separately

## Acceptance Checklist

- [x] Blocked dependency prevents readiness
- [x] Completed blocker unlocks ready state
- [x] Review tasks remain visible on the board and in summary counters
