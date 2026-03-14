# MAAS Master Roadmap

## Summary

MAAS is being implemented as a single-project, greenfield-first, board-first agent operating system. The first shipped slice centers the Kanban board, seeded task graph, SQLite blackboard, and lifecycle contract so humans can see work moving from planned to done.

## Current Status

This roadmap now needs to be read alongside the actual implementation status:

| Batch | Status | Notes |
|---|---|---|
| 1. Core kernel and scaffold | Implemented | Python package, CLI, SQLite migrations, `.maas/` workspace, `project.yaml`, greenfield bootstrap |
| 2. Goal/task engine | Partial | Goal records, task DAG storage, board-visible task states, dependency-aware ready refresh, acceptance evaluation, first-pass assignment |
| 3. Runtime lifecycle and adapters | Partial | Lifecycle operations, API/CLI entrypoints, provider registry, and concrete simulated adapters for Python Script, Claude Code, and OpenAI Codex |
| 4. Greenfield onboarding | Implemented | `maas init`, generated workspace, seeded backlog, project-understanding artifact |
| 5. Supervisor, dashboard, and Kanban V1 | Partial | Board API, board UI, control-room views, supervisor loop, ready refresh, idle-agent allocation, overview/roster operator controls, roster/overview/goal tree reads |
| 6. Security and human steering | Partial | Review, reprioritize, reassign, pause/resume, halt actions with audit logging, board controls, role-baseline gating, task-scoped execution grants, and escalation queue approvals |
| 7. Resilience and failure memory | Early | Stale-session detection, failure logging for failed/timed-out sessions, repeated-failure alerts, and read-model visibility exist; broader recovery is still pending |
| 8. Brownfield and multi-project | Not started | Still roadmap only |

## In-Flight Work

The current development branch is extending the human-steering layer with a real escalation queue:

- escalation queue storage and migration
- request, approve, and reject flows in the API and CLI
- escalation visibility in overview and live read models
- control-room queue visibility for operator approvals

Until that branch merges, treat those items as in progress rather than shipped.

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

- SQLite migrations and a migration runner
- greenfield bootstrap with seeded goals, agents, tasks, alerts, and sessions
- FastAPI read models for board, overview, goal tree, agents, activity, alerts, and providers
- task actions for ready queue refresh, allocator assignment, and acceptance evaluation
- supervisor run endpoint and CLI orchestration pass
- control-room actions for manual supervisor runs and idle-agent assignment
- board controls for reprioritize, reassign, pause/resume, review, and halt
- role-baseline permission enforcement for steering and alert actions
- task capability grant storage plus lifecycle enforcement for start, heartbeat, activity, artifact, and end-session actions
- escalation queue storage plus operator approve/reject flows for risky steering actions
- failure-log storage plus read models for recent failures and repeated-failure tasks
- concrete simulated provider adapters for Python Script, Claude Code, and OpenAI Codex
- lifecycle API/CLI surface
- a React control-room shell under `web/` with Board, Overview, Goal Tree, Agent Roster, Activity, Alerts, and Escalations views

## Recommended Reading Order

For someone joining development now:

1. Read this file for batch ordering and current status.
2. Read `README.md` for the current runnable surface.
3. Read batch docs `01` through `05` for implemented and partially implemented areas.
4. Read `06` through `08` as forward-looking roadmap/spec material.
