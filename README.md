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
- a React control room with operator actions for supervisor runs and idle-agent assignment
- board-side operator controls for review, reprioritize, reassign, pause/resume, and halt
- role-baseline permission enforcement for steering and alert actions
- an escalation queue for risky steering approvals
- implementation specs for the planned roadmap

## Implementation Snapshot

Legend:

- `[x]` shipped on `main`
- `[ ]` not fully shipped on `main`

### Shipped on `main`

- [x] Greenfield bootstrap with seeded goals, tasks, agents, alerts, and sessions
- [x] Board-first API and React control room
- [x] Ready-queue refresh, acceptance evaluation, and first-pass idle-agent allocation
- [x] Steering controls for review, reprioritize, reassign, pause/resume, and halt
- [x] Escalation queue for risky steering approvals
- [x] Failure-memory logging, quarantine visibility, repeated-failure alerts, incident-specific alert actions, and task recovery for failure-blocked work
- [x] Manual recover-and-requeue for failure-blocked tasks
- [x] Timed-out session auto-retry with tracked retry state
- [x] Quarantine queue workflow with restore and dismiss actions
- [x] Recovery for agents left in `error`
- [x] Real local Claude Code CLI integration behind explicit provider config
- [x] Real local OpenAI Codex CLI integration behind explicit provider config

### Still to do on `main`

- [ ] Broader automated restart, retry, backoff, and DLQ workflows
- [ ] Broader external provider coverage beyond the current local CLI paths
- [ ] Brownfield onboarding and multi-project support

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
- `GET /api/quarantine`
- `GET /api/live`
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
- operators can return failure-blocked tasks to the planning queue without resuming the old execution context
- timed-out sessions can auto-retry under project recovery policy with tracked retry state
- operators can recover timeout-stranded agents from `error` back to `idle` once no active session remains

## Provider Notes

- `python_script` is the reference local worker adapter
- `claude_code` supports both the simulated adapter and a real local `claude -p` path when enabled in `project.yaml`
- `openai_codex` supports both the simulated adapter and a real local `codex exec` path when enabled in `project.yaml`
