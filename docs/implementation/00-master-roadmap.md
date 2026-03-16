# MAAS Master Roadmap

## Summary

MAAS is being implemented as a single-project, greenfield-first, board-first agent operating system. The first shipped slice centers the Kanban board, seeded task graph, SQLite blackboard, and lifecycle contract so humans can see work moving from planned to done.

## Current Status

This roadmap now needs to be read alongside the actual implementation status in `docs/implementation/STATUS.md`.

Legend for the checklist column:

- `[x]` shipped on `main`
- `[ ]` not fully shipped on `main`

| Batch | Checklist | Notes |
|---|---|---|
| 1. Core kernel and scaffold | `[x]` | Python package, CLI, SQLite migrations, `.maas/` workspace, `project.yaml`, greenfield bootstrap |
| 2. Goal/task engine | `[ ]` | Goal records, task DAG storage, board-visible task states, dependency-aware ready refresh, acceptance evaluation, first-pass assignment |
| 3. Runtime lifecycle and adapters | `[ ]` | Lifecycle operations, API/CLI entrypoints, provider registry, concrete simulated adapters for Python Script, Claude Code, and OpenAI Codex, plus local Claude and Codex CLI paths and provider runtime status/history reads |
| 4. Greenfield onboarding | `[x]` | `maas init`, generated workspace, seeded backlog, project-understanding artifact |
| 5. Supervisor, dashboard, and Kanban V1 | `[ ]` | Board API, board UI, control-room views, supervisor loop, ready refresh, idle-agent allocation, overview/roster operator controls, and board/overview/goal tree/failure/provider reads |
| 6. Security and human steering | `[ ]` | Review, reprioritize, reassign, pause/resume, halt actions with audit logging, board controls, role-baseline gating, task-scoped execution grants, and escalation queue approvals |
| 7. Resilience and failure memory | `[ ]` | Stale-session detection, failure logging for failed/timed-out sessions, timed-out session auto-retry, quarantine queue restore/dismiss workflows, repeated-failure alerts, read-model visibility, and task plus agent recovery exist; broader recovery is still pending |
| 8. Brownfield and multi-project | `[ ]` | Still roadmap only |

## Delivery Order

1. Core kernel and scaffold
2. Goal/task engine
3. Runtime lifecycle and adapters
4. Greenfield onboarding
5. Supervisor, dashboard, and Kanban V1
6. Security and human steering
7. Resilience and failure memory
8. Brownfield and multi-project expansion

## Stable Interfaces

- `project.yaml`
- `.maas/` workspace
- `maas` CLI
- lifecycle operations
- task-first `/api/board` response contract

## Current Implementation Slice

This repository now includes:

- [x] SQLite migrations and a migration runner
- [x] Greenfield bootstrap with seeded goals, agents, tasks, alerts, and sessions
- [x] FastAPI read models for board, overview, goal tree, agents, activity, alerts, failures, live, and providers
- [x] Task actions for ready queue refresh, allocator assignment, acceptance evaluation, failure-blocked task recovery, repeated-failure triage, and recover-and-requeue
- [x] Supervisor run endpoint and CLI orchestration pass
- [x] Control-room actions for manual supervisor runs, idle-agent assignment, and error-agent recovery
- [x] Board controls for reprioritize, reassign, pause/resume, review, and halt
- [x] Role-baseline permission enforcement for steering and alert actions
- [x] Task capability grant storage plus lifecycle enforcement for start, heartbeat, activity, artifact, and end-session actions
- [x] Escalation queue storage plus operator approve/reject flows for risky steering actions
- [x] Failure-log storage plus read models for recent failures and repeated-failure tasks
- [x] Concrete simulated provider adapters for Python Script, Claude Code, and OpenAI Codex
- [x] Local Claude Code CLI integration behind explicit provider config
- [x] Local OpenAI Codex CLI integration behind explicit provider config
- [x] Provider runtime status/read-model visibility including config warnings and recent run history
- [x] Lifecycle API/CLI surface
- [x] A React control-room shell under `web/` with Board, Overview, Goal Tree, Agent Roster, Activity, Providers, Failures, Alerts, and Escalations views

## Recommended Reading Order

For someone joining development now:

1. Read this file for batch ordering and current status.
2. Read `README.md` for the current runnable surface.
3. Read batch docs `01` through `05` for implemented and partially implemented areas.
4. Read `06` through `08` as forward-looking roadmap/spec material.
