# Batch 5: Supervisor, Dashboard, and Kanban V1

## Status On `main`

- [ ] Batch 5 is only partially shipped on `main`.

## Shipped On `main`

- [x] Supervisor one-shot loop for stale heartbeats, ready refresh, and idle-agent allocation
- [x] Alert creation for stale sessions
- [x] Task-first `/api/board` response
- [x] React board shell as the primary operator view
- [x] Supporting reads for overview, goals, agents, activity, alerts, failures, escalations, and providers
- [x] React control-room views for Overview, Board, Goal Tree, Agent Roster, Activity, Providers, Failures, Alerts, and Escalations
- [x] Operator controls for manual supervisor runs and assign-next actions
- [x] Providers view can trigger safe manual provider runs for assigned tasks
- [x] Providers view can switch provider execution mode between simulation and available local live modes
- [x] Providers view can edit provider runtime settings
- [x] Overview and Failures views expose direct failure operator actions instead of remaining read-only summaries
- [x] Current implementation includes a `cancelled` board column so halted work remains visible to operators

## Still To Do On `main`

- [ ] Production websocket transport
- [ ] Multi-project board routing
- [ ] Artifact browser polish

## Board Contract Checklist

### Column shape

- [x] `key`
- [x] `title`
- [x] `tasks`

### Task card shape

- [x] `task_id`
- [x] `title`
- [x] `status`
- [x] `priority`
- [x] `progress_pct`
- [x] `heartbeat_age_seconds`
- [x] `age_hours`
- [x] `review_state`
- [x] Linked goal
- [x] Assigned agent

## Acceptance Checklist

- [x] Board response groups tasks server-side
- [x] Board summary includes active agents, blocked tasks, and review tasks
- [x] Stale supervisor findings create alerts and block affected in-progress work
- [x] Overview can trigger a supervisor pass and show structured results
- [x] Agent roster can assign the next ready task to an idle agent
