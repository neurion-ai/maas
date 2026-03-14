# MAAS Master Roadmap

## Summary

MAAS is being implemented as a single-project, greenfield-first, board-first agent operating system. The first shipped slice centers the Kanban board, seeded task graph, SQLite blackboard, and lifecycle contract so humans can see work moving from planned to done.

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
- FastAPI read models for board, goals, agents, activity, alerts, and providers
- lifecycle API/CLI surface
- a React board shell under `web/`

