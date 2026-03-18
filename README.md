# MAAS

MAAS is a board-first multi-agent operating system. This repository now contains:

- a Python core with SQLite-backed state
- a greenfield bootstrap flow
- a FastAPI API exposing Kanban board read models
- a task scheduler surface with ready-queue refresh and acceptance evaluation
- an allocator surface for assigning ready tasks to idle agents
- a supervisor pass for readiness refresh, allocation, and stale-session recovery
- a lightweight supervisor/lifecycle foundation
- task-scoped capability grants for execution, heartbeats, activity, artifacts, and session completion
- failure-memory logging with repeated-failure alerting and dashboard visibility
- operator recovery for failure-blocked tasks
- operator recovery for error-state agents
- concrete simulated runtime adapters for Python Script, Claude Code, and OpenAI Codex, plus optional local Claude/Codex CLI modes
- a React control room with operator actions for supervisor runs, idle-agent assignment, provider visibility, provider runs, provider mode switching, and provider settings updates
- board-side operator controls for review, reprioritize, reassign, pause/resume, and halt
- role-baseline permission enforcement for steering and alert actions
- an escalation queue for risky steering approvals
- implementation specs for the planned roadmap

## Implementation Snapshot

Legend:

- `[x]` completed in the current numbered delivery sequence
- `[ ]` not yet completed in the current numbered delivery sequence

Use the "Current stacked branch progress" section below to see whether a completed item is already on `main` or only exists on stacked branches.

Current stacked development chain above `main`:

- `#82` exists on `codex/project-aware-supervisor-orchestration`
- `#83` exists on `codex/brownfield-file-backed-planning`
- `#84` exists on `codex/recovery-circuit-breakers`
- `#85` exists on `codex/project-isolated-provider-runtime`
- `#86` exists on `codex/provider-job-queue`
- `#87` exists on `codex/provider-job-queue`
- `#88` exists on `codex/file-linked-task-scopes`
- `#89` exists on `codex/brownfield-runbook-command-catalog`
- `#90` exists on `codex/brownfield-runbook-command-catalog`
- `#91` exists on `codex/brownfield-runbook-command-catalog`
- `#92` exists on `codex/queue-capacity-controls`
- `#93` exists on `codex/session-runner-envelopes`
- `#94` exists on `codex/policy-driven-self-healing-v2`
- `#95` exists on `codex/brownfield-onboarding-review-v2`
- `#96` exists on `codex/remote-executor-worker-pool`
- `#97` exists on `codex/cross-project-scheduler-fairness`
- `#98` exists on `codex/repo-grounded-plan-synthesis`
- `#99` is the next unfinished step in the current sequence

### Current project state

- [x] MAAS is now a substantial single-project, greenfield, operator-supervised prototype.
- [x] The core loop exists end to end: bootstrap, board, supervisor, provider execution, failure handling, quarantine, recovery, and artifact inspection.
- [x] For that current prototype shape, the repo is roughly `85-90%` complete.
- [ ] For the broader roadmap vision, the repo is still materially incomplete.

### Shipped on `main`

- [x] Greenfield bootstrap with seeded goals, tasks, agents, alerts, and sessions
- [x] Board-first API and React control room
- [x] Ready-queue refresh, acceptance evaluation, and first-pass idle-agent allocation
- [x] Steering controls for review, reprioritize, reassign, pause/resume, and halt
- [x] Escalation queue for risky steering approvals
- [x] Failure-memory logging, quarantine visibility, repeated-failure alerts, incident-specific alert actions, and task recovery for failure-blocked work
- [x] Manual recover-and-requeue for failure-blocked tasks
- [x] Timed-out and failed-session auto-retry with tracked retry state
- [x] Explicit scheduler scoring, board-visible scheduler rationale, and adaptive replan guidance
- [x] Manual replanning queue plus dead-letter routing for retry-exhausted work
- [x] Quarantine queue workflow with restore, dismiss, reopen, and restore+requeue actions
- [x] Recovery for agents left in `error`
- [x] Real local Claude Code CLI integration behind explicit provider config
- [x] Real local OpenAI Codex CLI integration behind explicit provider config
- [x] Provider status visibility with effective mode, runtime controls, config warnings, preflight readiness, recent run history, manual run controls, mode switching, and editable settings
- [x] Artifact browser and artifact-state visibility in the control room
- [x] Artifact browser supports preview, guarded download, compare, lineage/provenance pivots, and task/session export bundles
- [x] Artifact browser operator actions for restore, restore-and-requeue, dismiss, and reopen on quarantined artifacts
- [x] Shared live transport with websocket, SSE, and polling fallback status in the control room shell

### Still to do on `main`

- [ ] Broader automated restart, retry, backoff, and self-healing workflows beyond the current DLQ path
- [ ] Broader external provider coverage beyond the current local CLI paths
- [ ] Higher-level artifact retention policy automation beyond the current browser, provenance, and export flows
- [ ] Deeper brownfield onboarding and multi-project execution support
- [ ] Stronger sandboxing and isolation guarantees
- [ ] Project-aware background orchestration beyond the current multi-project read scope

### Current numbered delivery sequence

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
- [x] `#97` Cross-project scheduler fairness and capacity policy
- [x] `#98` Repo-grounded plan synthesis and refresh
- [ ] `#99` Verification runners and evidence capture
- [ ] `#100` Git-aware task workspaces and diff review
- [ ] `#101` Cross-project command center
- [ ] `#102` Queue and worker capacity controls
- [ ] `#103` Policy-driven approval and risk routing
- [ ] `#104` Cost, runtime, and quota controls
- [ ] `#105` Notifications and outbound integrations
- [ ] `#106` Incident timeline and replay

### Current stacked branch progress

- [x] `#81` is already shipped on `main`
- [x] `#82` is implemented on `codex/project-aware-supervisor-orchestration`
- [x] `#83` is implemented on `codex/brownfield-file-backed-planning`
- [x] `#84` is implemented on `codex/recovery-circuit-breakers`
- [x] `#85` is implemented on `codex/project-isolated-provider-runtime`
- [x] `#86` is implemented on `codex/provider-job-queue`
- [x] `#87` is implemented on `codex/provider-job-queue`
- [x] `#88` is implemented on `codex/file-linked-task-scopes`
- [x] `#89` is implemented on `codex/brownfield-runbook-command-catalog`
- [x] `#90` is implemented on `codex/brownfield-runbook-command-catalog`
- [x] `#91` is implemented on `codex/brownfield-runbook-command-catalog`
- [x] `#92` is implemented on `codex/queue-capacity-controls`
- [x] `#93` is implemented on `codex/session-runner-envelopes`
- [x] `#94` is implemented on `codex/policy-driven-self-healing-v2`
- [x] `#95` is implemented on `codex/brownfield-onboarding-review-v2`
- [x] `#96` is implemented on `codex/remote-executor-worker-pool`
- [x] `#97` is implemented on `codex/cross-project-scheduler-fairness`
- [x] `#98` is implemented on `codex/repo-grounded-plan-synthesis`
- [ ] `#99` is the next unfinished item

### Extended numbered roadmap

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
- [x] `#97` Cross-project scheduler fairness and capacity policy
- [x] `#98` Repo-grounded plan synthesis and refresh
- [ ] `#99` Verification runners and evidence capture
- [ ] `#100` Git-aware task workspaces and diff review
- [ ] `#101` Cross-project command center
- [ ] `#102` Queue and worker capacity controls
- [ ] `#103` Policy-driven approval and risk routing
- [ ] `#104` Cost, runtime, and quota controls
- [ ] `#105` Notifications and outbound integrations
- [ ] `#106` Incident timeline and replay

## Quick Start

```bash
PYTHONPATH=src python3 -m maas init --project-root .
PYTHONPATH=src python3 -m maas db migrate --project-root .
PYTHONPATH=src python3 -m maas task ready --project-root . --refresh
PYTHONPATH=src python3 -m maas task allocate --project-root .
PYTHONPATH=src python3 -m maas supervisor --project-root . --once
PYTHONPATH=src python3 -m maas api --project-root .
```

The project bootstrap creates:

- `project.yaml`
- `.maas/`
- `.maas/state.db`
- `.maas/artifacts/`
- `.maas/logs/`
- `.maas/quarantine/`

## Core API

- `GET /api/health`
- `GET /api/board`
- `GET /api/goals`
- `GET /api/agents`
- `GET /api/activity`
- `GET /api/alerts`
- `GET /api/escalations`
- `GET /api/failures`
- `GET /api/artifacts`
- `GET /api/artifacts/export`
- `GET /api/quarantine`
- `GET /api/live`
- `WS /api/live/ws`
- `GET /api/overview`
- `GET /api/goals/tree`
- `GET /api/providers`
- `GET /api/tasks/ready`
- `GET /api/tasks/{task_id}/capabilities`
- `POST /api/escalations/request`
- `POST /api/escalations/{escalation_id}/actions/approve`
- `POST /api/escalations/{escalation_id}/actions/reject`
- `POST /api/providers/{provider_id}/actions/run-task`
- `POST /api/tasks/actions/refresh-ready`
- `POST /api/tasks/actions/allocate-ready`
- `POST /api/tasks/{task_id}/actions/evaluate`
- `POST /api/tasks/{task_id}/actions/recover`
- `POST /api/tasks/{task_id}/actions/recover-and-requeue`
- `POST /api/tasks/{task_id}/actions/resolve-repeated-failures`
- `POST /api/quarantine/{queue_id}/actions/restore`
- `POST /api/quarantine/{queue_id}/actions/dismiss`
- `POST /api/agents/{agent_id}/actions/assign-next`
- `POST /api/agents/{agent_id}/actions/recover`
- `POST /api/supervisor/run`

The primary operational surface is the Kanban board returned by `/api/board`.

## Task Engine Commands

- `maas task ready --project-root . --refresh`
- `maas task allocate --project-root .`
- `maas task allocate --project-root . --agent-id <agent_id>`
- `maas task evaluate --project-root . --task-id <task_id>`
- `maas task recover --project-root . --task-id <task_id> --actor-id <agent_id>`
- `maas task recover-and-requeue --project-root . --task-id <task_id> --actor-id <agent_id>`
- `maas task resolve-repeated-failures --project-root . --task-id <task_id> --actor-id <agent_id>`
- `maas agent recover --project-root . --agent-id <agent_id> --actor-id <agent_id>`
- `maas supervisor --project-root . --once`
- `maas failure list --project-root .`
- `maas quarantine list --project-root .`
- `maas quarantine restore --project-root . --queue-id <queue_id> --actor-id <agent_id>`
- `maas quarantine dismiss --project-root . --queue-id <queue_id> --actor-id <agent_id>`
- `maas escalation list --project-root .`
- `maas escalation request --project-root . --project-id <project_id> --actor-id <agent_id> --action-type halt_task|reassign_task|pause_agent|resume_agent --resource-type task|agent --resource-id <resource_id>`
- `maas escalation approve --project-root . --escalation-id <escalation_id> --actor-id <agent_id>`
- `maas escalation reject --project-root . --escalation-id <escalation_id> --actor-id <agent_id>`
- `maas worker --project-root . --provider-type python_script|claude_code|openai_codex ...`

These commands expose the current dependency-aware ready queue, allocator flow, acceptance-gate evaluation, supervisor orchestration pass, and escalation approval flow from the CLI.

## Security Notes

- board and alert actions are gated by role-baseline `board_actions` permissions from `project.yaml`
- task execution now uses task-scoped capability grants, so lifecycle writes are limited to the assigned agent and task
- board cards and the task capabilities API expose the currently active task grants
- risky task and agent interventions can now be routed through an escalation queue instead of being executed immediately
- failed and timed-out sessions are now recorded in failure memory and can raise repeated-failure alerts
- quarantined failure artifacts are isolated under `.maas/quarantine/` and surfaced through the failure-memory reads
- first-class quarantine queue reads and actions now track open, restored, and dismissed artifact incidents
- recent failure and overview surfaces expose direct operator actions for recovery, restore, dismiss, reopen, and repeated-failure resolution
- operators can return failure-blocked tasks to the planning queue without resuming the old execution context
- timed-out and failed sessions can auto-retry under project recovery policy with tracked retry state
- operators can recover timeout-stranded agents from `error` back to `idle` once no active session remains

## Provider Notes

- `python_script` is the reference local worker adapter
- `claude_code` supports both the simulated adapter and a real local `claude -p` path when enabled in `project.yaml`
- `openai_codex` supports both the simulated adapter and a real local `codex exec` path when enabled in `project.yaml`
- `/api/providers` and the Providers view expose configured mode, effective mode, config warnings, recent provider runs, safe manual run targets, mode switching, and editable runtime settings
- `/api/artifacts` and the Artifacts view expose artifact state, missing-file detection, quarantine metadata, and server-side filtering
- artifact detail now includes preview, guarded single-file download, task/session export bundles, same-task compare, same-session lineage, and dependency-linked provenance pivots
