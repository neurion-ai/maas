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
  - halt
- audit logging for steering actions
- task-scoped capability grants for assigned execution work
- failed and timed-out sessions now write to failure memory

### Dashboard

- board API with server-side grouping
- server-side board filters
- overview read model
- goal tree read model
- enriched agent roster read model
- activity feed
- overview control for manual supervisor runs
- agent-roster control for assigning the next task to idle agents
- board controls for reprioritize, reassign, halt, review, and pause/resume
- React control-room shell with:
  - Overview
  - Board
  - Goal Tree
  - Agent Roster
  - Activity

## What Is Partial

### Scheduling and planning

- ready-task resolution exists, with dependency/conflict-aware refresh semantics
- allocator assignment exists for idle agents and ready work
- acceptance criteria evaluation exists for `artifact_exists`, `metric`, `db_query`, and `test_passes`
- task evaluation is exposed through both CLI and API surfaces
- allocator logic is still heuristic and intentionally lightweight
- no advanced replanning loop yet

### Providers

- provider registry exists
- local simulation exists
- real Claude Code / OpenAI Codex runtime execution is not complete yet

### Supervisor and resilience

- stale-session detection exists
- supervisor pass now refreshes readiness and allocates idle agents
- alert generation exists
- failure memory now records failed and timed-out sessions
- repeated task failures now raise critical alerts and appear in board/overview/live read models
- broader self-healing, DLQ handling, and recovery workflows remain incomplete

### Security

- operator actions are audited
- board-driven steering now covers most of the Batch 6 control surface
- role-baseline `board_actions` permission enforcement now gates steering and alert actions
- task execution now requires task-scoped capability grants for start, heartbeat, activity, artifact, and end-session writes
- escalation queues and broader capability-token distribution are still incomplete

## What Is Not Started

- brownfield onboarding pipeline
- multi-project support
- plugin/domain extension architecture
- serious sandbox/isolation layers
- advanced failure memory and recovery orchestration

## Current Development Focus

Current work is moving deeper into the goal/task engine with:

- dependency-aware ready queue refresh
- idle-agent task allocation
- acceptance-gate evaluation
- scheduler/supervisor task commands and API actions
- operator controls for manual supervisor runs and assign-next actions
- board-side steering controls for reprioritize, reassign, and halt
- permission-gated steering and alert actions
- failure-memory logging and repeated-failure surfacing

If the current supervisor branch is not yet merged, treat those orchestration features as in progress rather than available on `main`.

## Practical Assessment

If someone asks “can MAAS be used right now?”, the honest answer is:

- Yes, as a greenfield local prototype and operator-facing foundation.
- No, not yet as a fully autonomous production platform.

If the current permission-enforcement branch is not yet merged, treat the role-gated steering and alert actions as in progress rather than available on `main`.

The project is roughly in the **late Batch 2 through Batch 6 foundation zone** of the roadmap:

- Batches 1 and 4 are effectively in place.
- Batch 2 now includes readiness, evaluation, and first-pass assignment behavior.
- Batches 3, 5, and 6 are partially in place, with the supervisor participating in orchestration and steering now permission-gated at the role baseline.
- Batch 6 now also includes task-scoped execution grants tied to task assignment.
- Batch 7 now has its first real failure-memory foundation, but most recovery automation is still ahead of us.
- Batch 8 is still mostly ahead of us.
