# Batch 1: Core Kernel and Scaffold

## Status On `main`

- [x] Batch 1 is shipped on `main`.

## Shipped On `main`

- [x] Python package layout under `src/maas/`
- [x] Root `migrations/`
- [x] `.maas/` workspace creation
- [x] `project.yaml` defaults and persistence
- [x] Initial SQLite schema for project, goal, task, agent, session, artifact, activity, alert, and audit records
- [x] CLI commands for `init`, `db migrate`, `api`, and `supervisor`
- [x] `tasks.status` support for `planned`, `ready`, `assigned`, `in_progress`, `review`, `blocked`, `done`, and `cancelled`
- [x] Seeded greenfield projects create a board-visible backlog immediately

## Non-Goals

- brownfield discovery
- production auth
- full provider execution

## Acceptance Checklist

- [x] Bootstrap creates `project.yaml`
- [x] Bootstrap creates `.maas/state.db`
- [x] Migrations apply cleanly
- [x] Seeded board has all core columns

## Dependencies

- none
