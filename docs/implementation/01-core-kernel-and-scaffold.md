# Batch 1: Core Kernel and Scaffold

## Scope

- Python package layout under `src/maas/`
- root `migrations/`
- `.maas/` workspace creation
- `project.yaml` defaults and persistence
- initial SQLite schema for project, goal, task, agent, session, artifact, activity, alert, and audit records
- CLI commands: `init`, `db migrate`, `api`, `supervisor`

## Non-Goals

- brownfield discovery
- production auth
- full provider execution

## Schema and Interface Changes

- `tasks.status` supports `planned`, `ready`, `assigned`, `in_progress`, `review`, `blocked`, `done`, `cancelled`
- seeded greenfield projects create a board-visible backlog immediately

## Acceptance Tests

- bootstrap creates `project.yaml`
- bootstrap creates `.maas/state.db`
- migrations apply cleanly
- seeded board has all core columns

## Dependencies

- none

