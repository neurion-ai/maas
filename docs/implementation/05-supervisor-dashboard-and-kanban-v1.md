# Batch 5: Supervisor, Dashboard, and Kanban V1

## Scope

- supervisor one-shot loop for stale heartbeats, ready refresh, and idle-agent allocation
- alert creation for stale sessions
- task-first `/api/board` response
- React board shell as the primary operator view
- supporting reads for goals, agents, activity, alerts, and providers
- operator controls for manual supervisor runs and assign-next actions

## Board Contract

Each board column should include:

- `key`
- `title`
- `tasks`

Each task card should include:

- `task_id`
- `title`
- `status`
- `priority`
- `progress_pct`
- `heartbeat_age_seconds`
- `age_hours`
- `review_state`
- linked goal
- assigned agent

## Non-Goals

- production websockets
- multi-project board routing
- artifact browser polish

## Acceptance Tests

- board response groups tasks server-side
- board summary includes active agents, blocked tasks, and review tasks
- stale supervisor findings create alerts and block affected in-progress work
- overview can trigger a supervisor pass and show structured results
- agent roster can assign the next ready task to an idle agent
