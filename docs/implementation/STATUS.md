# MAAS Development Status

## Where We Are

MAAS is no longer at the “just architecture docs” phase. The project has a real runnable foundation and is now in the **early productization** stage:

- backend core exists
- greenfield bootstrap exists
- board-first workflow exists
- basic steering exists
- dashboard/control-room UI exists

The system is best described as **an operational prototype with real infrastructure**, not a finished platform.

## What Is Shipped

### Core platform

- Python package under `src/maas/`
- SQLite-backed state with migrations
- `.maas/` local workspace layout
- `project.yaml` generation and loading
- CLI entrypoints for init, migrate, API, supervisor, board, worker, and lifecycle operations

### Work orchestration

- goals and tasks persisted in SQLite
- board-visible task states:
  - `planned`
  - `ready`
  - `assigned`
  - `in_progress`
  - `review`
  - `blocked`
  - `done`
  - `cancelled`
- dependency storage for `blocks`, `informs`, and `conflicts`
- seeded greenfield backlog

### Runtime and steering

- lifecycle operations:
  - `start_session`
  - `heartbeat`
  - `log_activity`
  - `produce_artifact`
  - `end_session`
- simulated worker path for local execution
- steering actions:
  - review approve/reject
  - reprioritize
  - reassign
  - agent pause/resume
- audit logging for steering actions

### Dashboard

- board API with server-side grouping
- server-side board filters
- overview read model
- goal tree read model
- enriched agent roster read model
- activity feed
- React control-room shell with:
  - Overview
  - Board
  - Goal Tree
  - Agent Roster
  - Activity

## What Is Partial

### Scheduling and planning

- ready-task resolution exists, with dependency/conflict-aware refresh semantics
- acceptance criteria evaluation exists for `artifact_exists`, `metric`, `db_query`, and `test_passes`
- task evaluation is exposed through both CLI and API surfaces
- allocator logic is still minimal
- no advanced replanning loop yet

### Providers

- provider registry exists
- local simulation exists
- real Claude Code / OpenAI Codex runtime execution is not complete yet

### Supervisor and resilience

- stale-session detection exists
- alert generation exists
- broader self-healing, DLQ handling, and failure memory remain incomplete

### Security

- operator actions are audited
- full permission enforcement and capability-token infrastructure are not complete

## What Is Not Started

- brownfield onboarding pipeline
- multi-project support
- plugin/domain extension architecture
- serious sandbox/isolation layers
- advanced failure memory and recovery orchestration

## Current Development Focus

Current work is moving deeper into the goal/task engine with:

- dependency-aware ready queue refresh
- acceptance-gate evaluation
- scheduler-facing task commands and API actions

If the current task-evaluation branch is not yet merged, treat those scheduler features as in progress rather than available on `main`.

## Practical Assessment

If someone asks “can MAAS be used right now?”, the honest answer is:

- Yes, as a greenfield local prototype and operator-facing foundation.
- No, not yet as a fully autonomous production platform.

The project is roughly in the **late Batch 2 through Batch 6 foundation zone** of the roadmap:

- Batches 1 and 4 are effectively in place.
- Batch 2 is moving from storage/plumbing into real orchestration behavior.
- Batches 3, 5, and 6 are partially in place.
- Batches 7 and 8 are mostly ahead of us.
