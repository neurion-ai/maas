# MAAS Development Status

## Legend

- `[x]` shipped on `main`
- `[ ]` not fully shipped on `main`
- In-flight branch work should be tracked in open PRs, not in this file.

## Current Snapshot

- [x] MAAS is usable today as a greenfield local prototype with a real operator-facing control room.
- [x] The board-first workflow, steering controls, escalation queue, and first-pass resilience foundations are in place.
- [ ] MAAS is not yet a production-ready autonomous platform.

## Shipped On `main`

### Core platform

- [x] Python package under `src/maas/`
- [x] SQLite-backed state with migrations
- [x] `.maas/` local workspace layout
- [x] `project.yaml` generation and loading
- [x] CLI entrypoints for init, migrate, API, supervisor, board, task, agent, worker, lifecycle, failure, and escalation operations

### Work orchestration

- [x] Goal and task records persisted in SQLite
- [x] Board-visible task states: `planned`, `ready`, `assigned`, `in_progress`, `review`, `blocked`, `done`, `cancelled`
- [x] Dependency storage for `blocks`, `informs`, and `conflicts`
- [x] Seeded greenfield backlog and project-understanding artifact
- [x] Dependency-aware ready-queue refresh
- [x] Idle-agent allocation and manual assign-next controls
- [x] Acceptance evaluation for `artifact_exists`, `metric`, `db_query`, and `test_passes`

### Runtime and provider layer

- [x] Lifecycle operations: `start_session`, `heartbeat`, `log_activity`, `produce_artifact`, `end_session`
- [x] Simulated local worker/runtime execution path
- [x] Provider-dispatched runtime path for `python_script`, `claude_code`, and `openai_codex`
- [x] Shared lifecycle contract for provider activity and artifact output
- [x] Real local Claude Code CLI execution path behind explicit provider config
- [x] Real local OpenAI Codex CLI execution path behind explicit provider config
- [x] Provider status visibility with effective mode, runtime controls, config warnings, recent run history, manual run controls, mode switching, and editable settings

### Control room and steering

- [x] Board API with server-side grouping and filters
- [x] Overview, goal tree, agent roster, activity, alerts, escalations, failures, and live snapshot read models
- [x] React control-room views for Overview, Board, Goal Tree, Agent Roster, Activity, Providers, Failures, Alerts, and Escalations
- [x] Operator controls for review approve/reject
- [x] Operator controls for reprioritize, reassign, pause/resume, and halt
- [x] Operator controls for manual supervisor runs and assign-next from the roster
- [x] Operator controls for safe manual provider runs from the Providers view
- [x] Operator controls for switching provider execution mode from the Providers view
- [x] Operator controls for editing provider runtime settings from the Providers view
- [x] Role-baseline `board_actions` permission enforcement for steering and alert actions
- [x] Audit logging for steering actions
- [x] Escalation queue request, approve, and reject flows in API, CLI, and control room

### Security and execution permissions

- [x] Task-scoped capability grants for assigned execution work
- [x] Lifecycle enforcement for start, heartbeat, activity, artifact, and end-session writes
- [x] Grant revocation on task halt, reassignment, recovery, and session completion

### Resilience and failure handling

- [x] Stale-session detection in the supervisor pass
- [x] Failure-memory logging for failed and timed-out sessions
- [x] Timed-out session auto-retry with retry state surfaced in task and failure reads
- [x] Failed-session auto-retry with retry state surfaced in task and failure reads
- [x] Repeated-failure alerts for tasks with repeated failures
- [x] Failure visibility in board, overview, live, and dedicated failures reads
- [x] Quarantine details are visible in recent failure reads and the control-room failure surfaces
- [x] First-class quarantine queue reads plus restore, dismiss, reopen, and restore+requeue actions
- [x] Failure-specific operator actions for repeated-failure incidents and recovery-linked alerts
- [x] Overview and Failures surfaces expose direct operator actions for recent failures and repeated-failure tasks
- [x] Operator recovery for failure-blocked tasks
- [x] Operator recover-and-requeue for failure-blocked tasks
- [x] Operator recovery for agents left in `error`

## Still To Do On `main`

### Scheduling and planning

- [ ] Advanced replanning loop
- [ ] Smarter allocator and scheduling policies beyond the current heuristic pass
- [ ] Broader scheduler-driven recovery and requeue policies

### Providers

- [ ] Broader external provider coverage beyond the current local CLI paths
- [ ] More complete provider runtime lifecycle coverage

### Resilience and recovery

- [ ] Broader automated restart and retry policies
- [ ] Broader DLQ and quarantine workflows
- [ ] Broader failure-specific resolution flows beyond the current repeated-failure and recovery-linked incidents
- [ ] Broader self-healing and recovery orchestration

### Platform expansion

- [ ] Brownfield onboarding pipeline
- [ ] Multi-project support
- [ ] Plugin and domain extension architecture
- [ ] Strong sandbox and isolation layers

## Batch View

- [x] Batch 1: Core kernel and scaffold
- [ ] Batch 2: Goal/task engine is only partially complete
- [ ] Batch 3: Runtime lifecycle and adapters are only partially complete
- [x] Batch 4: Greenfield onboarding
- [ ] Batch 5: Supervisor, dashboard, and Kanban V1 are only partially complete
- [ ] Batch 6: Security and human steering are only partially complete
- [ ] Batch 7: Resilience and failure memory are only partially complete
- [ ] Batch 8: Brownfield and multi-project expansion has not started
