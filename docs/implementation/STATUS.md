# MAAS Development Status

## Legend

- `[x]` completed in the current numbered delivery sequence
- `[ ]` not yet completed in the current numbered delivery sequence

The "Current Development Sequence" section below shows whether a completed item is already on `main` or still only exists on stacked branches.

## Current Development Sequence

- [x] `#81` is shipped on `main`
- [x] `#82` is implemented on the stacked branch `codex/project-aware-supervisor-orchestration`
- [x] `#83` is implemented on the stacked branch `codex/brownfield-file-backed-planning`
- [x] `#84` is implemented on the stacked branch `codex/recovery-circuit-breakers`
- [x] `#85` is implemented on the stacked branch `codex/project-isolated-provider-runtime`
- [x] `#86` is implemented on the stacked branch `codex/provider-job-queue`
- [x] `#87` is implemented on the stacked branch `codex/provider-job-queue`
- [x] `#88` is implemented on the stacked branch `codex/file-linked-task-scopes`
- [x] `#89` is implemented on the stacked branch `codex/brownfield-runbook-command-catalog`
- [x] `#90` is implemented on the stacked branch `codex/brownfield-runbook-command-catalog`
- [x] `#91` is implemented on the stacked branch `codex/brownfield-runbook-command-catalog`
- [x] `#92` is implemented on the stacked branch `codex/queue-capacity-controls`
- [x] `#93` is implemented on the stacked branch `codex/session-runner-envelopes`
- [x] `#94` is implemented on the stacked branch `codex/policy-driven-self-healing-v2`
- [x] `#95` is implemented on the stacked branch `codex/brownfield-onboarding-review-v2`
- [x] `#96` is implemented on the stacked branch `codex/remote-executor-worker-pool`
- [ ] `#97` is the next unfinished item in the current stacked sequence

## Extended Numbered Roadmap

- [x] `#81` Multi-project write path and project lifecycle
- [x] `#82` Project-aware supervisor and background orchestration
- [x] `#83` Brownfield file-backed planning and repo navigation
- [x] `#84` Policy-driven self-healing and circuit breakers
- [x] `#85` Sandboxed provider runners per project
- [x] `#86` Remote or queued provider execution beyond local CLI paths
- [x] `#87` Brownfield rescan and drift detection
- [x] `#88` File-linked task scopes and acceptance criteria
- [x] `#89` Brownfield runbook and command catalog
- [x] `#90` Portfolio view across projects
- [x] `#91` Background orchestration daemon
- [x] `#92` Queue and worker capacity management on top of the provider job queue
- [x] `#93` Stronger runner sandbox envelopes beyond the current per-project runtime isolation
- [x] `#94` Policy-driven self-healing v2
- [x] `#95` Brownfield onboarding review v2
- [x] `#96` Remote executor or worker pool
- [ ] `#97` Cross-project scheduler fairness and capacity policy
- [ ] `#98` Repo-grounded plan synthesis and refresh
- [ ] `#99` Verification runners and evidence capture
- [ ] `#100` Git-aware task workspaces and diff review
- [ ] `#101` Cross-project command center
- [ ] `#102` Queue and worker capacity controls
- [ ] `#103` Policy-driven approval and risk routing
- [ ] `#104` Cost, runtime, and quota controls
- [ ] `#105` Notifications and outbound integrations
- [ ] `#106` Incident timeline and replay

## Current Snapshot

- [x] MAAS is usable today as a greenfield local prototype with a real operator-facing control room.
- [x] The board-first workflow, steering controls, escalation queue, and first-pass resilience foundations are in place.
- [x] Local live-provider operation exists for Claude Code and OpenAI Codex behind explicit project configuration.
- [x] Operators can now work incidents from multiple surfaces: Alerts, Failures, Recovery, Overview, and the Artifact browser.
- [x] Brownfield codebase mapping, multi-project read scoping, and first-pass live-provider isolation hardening are now on `main`.
- [x] Adaptive scheduling feedback, manual replanning, and retry-exhaustion DLQ routing are now on `main`.
- [x] The current prototype is roughly `85-90%` complete for the single-project greenfield/operator-supervised shape.
- [ ] MAAS is not yet a production-ready autonomous platform.
- [ ] The broader roadmap still depends on deeper brownfield import, multi-project expansion, stronger isolation, better planning, broader providers, and stronger automation.

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
- [x] Provider status visibility with effective mode, runtime controls, config warnings, preflight readiness, recent run history, manual run controls, mode switching, and editable settings
- [x] Explicit scheduler scoring, board-visible scheduler rationale, and adaptive replanning guidance

### Control room and steering

- [x] Board API with server-side grouping and filters
- [x] Overview, goal tree, agent roster, activity, alerts, escalations, failures, and live snapshot read models
- [x] React control-room views for Overview, Board, Goal Tree, Agent Roster, Activity, Artifacts, Providers, Recovery, Failures, Alerts, and Escalations
- [x] Operator controls for review approve/reject
- [x] Operator controls for reprioritize, reassign, pause/resume, and halt
- [x] Operator controls for manual supervisor runs and assign-next from the roster
- [x] Operator controls for safe manual provider runs from the Providers view
- [x] Operator controls for switching provider execution mode from the Providers view
- [x] Operator controls for editing provider runtime settings from the Providers view
- [x] Operator controls for policy editing, retry override review, retry-backoff release, retry-state reset, task recovery, alert-backed recovery, quarantine actions, and artifact-level quarantine actions
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
- [x] Artifact browser visibility includes artifact state, quarantine metadata, missing-file detection, preview, guarded download, compare, lineage/provenance pivots, export bundles, and direct quarantine actions
- [x] First-class quarantine queue reads plus restore, dismiss, reopen, and restore+requeue actions
- [x] Dead-letter queue routing for retry-exhausted tasks plus Recovery visibility and finish-replan resolution
- [x] Failure-specific operator actions for repeated-failure incidents and recovery-linked alerts
- [x] Overview and Failures surfaces expose direct operator actions for recent failures and repeated-failure tasks
- [x] Operator recovery for failure-blocked tasks
- [x] Operator recover-and-requeue for failure-blocked tasks
- [x] Operator recovery for agents left in `error`

## Still To Do On `main`

### Scheduling and planning

- [ ] Broader scheduler-driven recovery and requeue policies
- [ ] More autonomous replanning beyond the current explicit scorer and manual replan queue

### Providers

- [ ] Broader external provider coverage beyond the current local CLI paths
- [ ] More complete provider runtime lifecycle coverage

### Resilience and recovery

- [ ] Broader automated restart and retry policies
- [ ] Broader DLQ and quarantine workflows beyond the current retry-exhaustion dead-letter path
- [ ] Broader failure-specific resolution flows beyond the current repeated-failure, recovery-linked, and quarantine incident actions
- [ ] Higher-level artifact retention and cleanup policy automation beyond the current browser, provenance, export, and incident-handling flows
- [ ] Broader self-healing and recovery orchestration

### Platform expansion

- [ ] Deeper brownfield onboarding and repo-derived execution planning
- [ ] Multi-project support beyond the current scoped read foundation
- [ ] Plugin and domain extension architecture
- [ ] Strong sandbox and isolation layers beyond the current live-provider guardrails

## Practical Summary

- [x] If the goal is a single-project local MAAS workspace with a human operator in the loop, the repo now covers most of the required surfaces.
- [x] The strongest areas today are board operations, recovery handling, failure memory, provider visibility, artifact inspection, and control-room tooling.
- [ ] The biggest remaining gaps are autonomous planning quality, broader provider/runtime coverage, stronger self-healing, and platform expansion beyond one greenfield project.

## Current Numbered Delivery Sequence

- [x] `#80` Provider runtime preflight and readiness checks
- [x] `#81` Multi-project write path and project lifecycle
- [x] `#82` Project-aware supervisor and background orchestration
- [x] `#83` Brownfield file-backed planning and repo navigation
- [x] `#84` Policy-driven self-healing and circuit breakers
- [x] `#85` Sandboxed provider runners per project
- [x] `#86` Remote or queued provider execution beyond local CLI paths
- [x] `#87` Brownfield rescan and drift detection
- [x] `#88` File-linked task scopes and acceptance criteria
- [x] `#89` Brownfield runbook and command catalog
- [x] `#90` Portfolio view across projects
- [x] `#91` Background orchestration daemon
- [x] `#92` Queue and worker capacity management on top of the provider job queue
- [x] `#93` Stronger runner sandbox envelopes beyond the current per-project runtime isolation
- [x] `#94` Policy-driven self-healing v2
- [x] `#95` Brownfield onboarding review v2
- [x] `#96` Remote executor or worker pool
- [ ] `#97` Cross-project scheduler fairness and capacity policy
- [ ] `#98` Repo-grounded plan synthesis and refresh
- [ ] `#99` Verification runners and evidence capture
- [ ] `#100` Git-aware task workspaces and diff review
- [ ] `#101` Cross-project command center
- [ ] `#102` Queue and worker capacity controls
- [ ] `#103` Policy-driven approval and risk routing
- [ ] `#104` Cost, runtime, and quota controls
- [ ] `#105` Notifications and outbound integrations
- [ ] `#106` Incident timeline and replay

## Batch View

- [x] Batch 1: Core kernel and scaffold
- [ ] Batch 2: Goal/task engine is only partially complete
- [ ] Batch 3: Runtime lifecycle and adapters are only partially complete
- [x] Batch 4: Greenfield onboarding
- [ ] Batch 5: Supervisor, dashboard, and Kanban V1 are only partially complete
- [ ] Batch 6: Security and human steering are only partially complete
- [ ] Batch 7: Resilience and failure memory are only partially complete
- [ ] Batch 8: Brownfield onboarding has started, but deeper import and multi-project expansion are still early
