# Batch 5: Supervisor, Dashboard, and Kanban V1

## Status On `main`

- [ ] Batch 5 is only partially shipped on `main`.

## Shipped On `main`

- [x] Supervisor one-shot loop for stale heartbeats, ready refresh, and idle-agent allocation
- [x] Alert creation for stale sessions
- [x] Task-first `/api/board` response
- [x] React board shell as the primary operator view
- [x] Supporting reads for overview, goals, agents, activity, alerts, failures, escalations, artifacts, and providers
- [x] React control-room views for Overview, Board, Goal Tree, Agent Roster, Activity, Artifacts, Providers, Recovery, Failures, Alerts, and Escalations
- [x] Operator controls for manual supervisor runs and assign-next actions
- [x] Providers view can trigger safe manual provider runs for assigned tasks
- [x] Providers view can switch provider execution mode between simulation and available local live modes
- [x] Providers view can edit provider runtime settings
- [x] Overview and Failures views expose direct failure operator actions instead of remaining read-only summaries
- [x] Current implementation includes a `cancelled` board column so halted work remains visible to operators
- [x] Live transport now prefers websocket, falls back to SSE, and only then uses polling
- [x] Artifact browser includes artifact-state visibility, quarantine context, server-side filtering, preview, guarded download, compare, lineage/provenance pivots, task/session export bundles, and row-level quarantine actions

## Still To Do On `main`

- [ ] Product information architecture simplification and clearer top-level navigation
- [ ] Home command center that recommends next actions instead of exposing subsystem sprawl
- [ ] Guided onboarding and first-run operator workflow
- [ ] Unified Work, Runs, and Incidents surfaces instead of separate mechanism-heavy pages
- [ ] Dark/light theme system and stronger visual hierarchy
- [ ] Multi-project board routing
- [ ] Higher-level artifact retention controls and cleanup workflows beyond the current browser and row-level incident actions

## UX/Product Sequence On `codex/ux-product-redesign`

- [x] `#107` Information architecture reset and navigation collapse
- [x] `#108` Design system and dual light/dark theme foundation
- [x] `#109` Home command center with recommended actions
- [x] `#110` Guided onboarding and first-run experience
- [x] `#111` Unified Work surface for board, plan, and task detail
- [x] `#112` Unified Runs surface for agents, providers, verification, and outputs
- [x] `#113` Unified Incidents surface for failures, alerts, recovery, and timeline
- [x] `#114` Portfolio and project-management UX redesign
- [x] `#115` Command palette, contextual actions, empty states, and inline guidance
- [x] `#116` Accessibility, responsiveness, and visual-polish pass

## Dense Control-Room Sequence On `codex/dense-control-room-redesign`

- [x] `#117` Shell density reset
- [x] `#118` Default control room layout
- [x] `#119` Compact kanban redesign
- [x] `#120` Agent roster and interaction view
- [x] `#121` Curated live ticker
- [x] `#122` Goal/subgoal/task relationship explorer
- [x] `#123` Incident rail and playbooks
- [x] `#124` Evidence and verification drawer
- [x] `#125` Project status and portfolio command bar
- [x] `#126` Remove legacy hero UX and final dense visual pass

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
