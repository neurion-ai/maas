# MAAS Master Roadmap

## Summary

MAAS is being implemented as a single-project, greenfield-first, board-first agent operating system. The first shipped slice centers the Kanban board, seeded task graph, SQLite blackboard, and lifecycle contract so humans can see work moving from planned to done.

## Current Status

This roadmap now needs to be read alongside the actual implementation status in `docs/implementation/STATUS.md`.

Legend for the checklist column:

- `[x]` shipped on `main`
- `[ ]` not fully shipped on `main`

Current stacked development chain above `main`:

- `#82` exists on `codex/project-aware-supervisor-orchestration`
- `#83` exists on `codex/brownfield-file-backed-planning`
- `#84` exists on `codex/recovery-circuit-breakers`
- `#85` exists on `codex/project-isolated-provider-runtime`
- `#86` exists on `codex/provider-job-queue`
- `#87` exists on `codex/provider-job-queue`
- `#88` is the next unfinished item in sequence

| Batch | Checklist | Notes |
|---|---|---|
| 1. Core kernel and scaffold | `[x]` | Python package, CLI, SQLite migrations, `.maas/` workspace, `project.yaml`, greenfield bootstrap |
| 2. Goal/task engine | `[ ]` | Goal records, task DAG storage, board-visible task states, dependency-aware ready refresh, acceptance evaluation, first-pass assignment |
| 3. Runtime lifecycle and adapters | `[ ]` | Lifecycle operations, API/CLI entrypoints, provider registry, concrete simulated adapters for Python Script, Claude Code, and OpenAI Codex, plus local Claude and Codex CLI paths, provider runtime status/history reads, preflight readiness checks, manual provider runs, provider mode switching, and editable provider settings |
| 4. Greenfield onboarding | `[x]` | `maas init`, generated workspace, seeded backlog, project-understanding artifact |
| 5. Supervisor, dashboard, and Kanban V1 | `[ ]` | Board API, board UI, control-room views, supervisor loop, ready refresh, idle-agent allocation, overview/roster operator controls, board/overview/goal tree/failure/provider/artifact reads, artifact browser with preview/download/compare/provenance/export flows, artifact-row operator actions, live websocket transport, and overview/failure/recovery action controls |
| 6. Security and human steering | `[ ]` | Review, reprioritize, reassign, pause/resume, halt actions with audit logging, board controls, role-baseline gating, task-scoped execution grants, and escalation queue approvals |
| 7. Resilience and failure memory | `[ ]` | Stale-session detection, failure logging for failed/timed-out sessions, timed-out and failed-session auto-retry, explicit scheduler feedback, manual replanning, retry-exhaustion DLQ routing, quarantine queue restore/dismiss/reopen workflows, repeated-failure alerts, failure-action read-model visibility across Failures/Overview/Recovery/Artifacts, and task plus agent recovery exist; broader recovery is still pending |
| 8. Brownfield and multi-project | `[ ]` | Brownfield onboarding, codebase mapping, multi-project read scoping, and first-pass runtime isolation have started on `main`; deeper import, project lifecycle, background orchestration, broader project architecture, and stronger isolation are still pending |

## Progress Summary

- [x] The shipped repository now covers most of the greenfield single-project operator loop.
- [x] Brownfield onboarding has started on `main` with repo detection, approval gating, imported workflow/repo-area backlog seeding, and overview visibility.
- [x] The current implementation is roughly `85-90%` complete for that prototype target.
- [ ] The repository is still much earlier against the broader long-horizon roadmap.
- [ ] The biggest remaining roadmap buckets are project lifecycle/orchestration, deeper brownfield execution, stronger recovery automation, stronger isolation, and broader provider/runtime coverage.

## Next Recommended PR Sequence

- [x] `#80` Provider runtime preflight and readiness checks:
  let operators verify live runtime readiness before task execution by checking CLI availability, required auth env, and persisted readiness state in the Providers surface.
- [x] `#81` Multi-project write path and project lifecycle:
  move beyond read scoping by adding create/import/archive flows, project-scoped write operations, and explicit lifecycle management for multiple repos.
- [ ] `#82` Project-aware supervisor and background orchestration:
  make the scheduler, supervisor, live transport, and recovery automation operate cleanly per project instead of assuming a single active workspace loop.
- [ ] `#83` Brownfield file-backed planning and repo navigation:
  turn brownfield discovery into file-linked task graphs, code-area navigation, and reviewable imported workflow execution plans that operators can actually steer.
- [ ] `#84` Policy-driven self-healing and circuit breakers:
  expand the current recovery workbench into guarded automation for recover/requeue/quarantine/escalate decisions with explicit stop conditions.
- [ ] `#85` Sandboxed provider runners per project:
  strengthen runtime isolation by moving from sanitized subprocess envs to clearer per-project runtime boundaries and safer execution sandboxes.
- [ ] `#86` Remote or queued provider execution beyond local CLI paths:
  add the next meaningful execution mode after local CLI paths, such as a queued or remote runner, once readiness and isolation are strong enough.

## Current Stacked Branch Progress

- [x] `#81` is shipped on `main`
- [x] `#82` is implemented on `codex/project-aware-supervisor-orchestration`
- [x] `#83` is implemented on `codex/brownfield-file-backed-planning`
- [x] `#84` is implemented on `codex/recovery-circuit-breakers`
- [x] `#85` is implemented on `codex/project-isolated-provider-runtime`
- [x] `#86` is implemented on `codex/provider-job-queue`
- [x] `#87` is implemented on `codex/provider-job-queue`
- [ ] `#88` is the next unfinished item

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
- [x] FastAPI read models for board, overview, goal tree, agents, activity, alerts, failures, live, artifacts, and providers
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
- [x] Provider runtime status/read-model visibility including config warnings, recent run history, manual run targets, provider mode state, and editable settings
- [x] Lifecycle API/CLI surface
- [x] A React control-room shell under `web/` with Board, Overview, Goal Tree, Agent Roster, Activity, Artifacts, Providers, Recovery, Failures, Alerts, and Escalations views plus provider run, mode, settings, and recovery controls
- [x] Artifact detail workflows for preview, guarded download, same-task compare, same-session lineage, dependency-linked provenance, and task/session export bundles

## Recommended Reading Order

For someone joining development now:

1. Read this file for batch ordering and current status.
2. Read `README.md` for the current runnable surface.
3. Read batch docs `01` through `05` for implemented and partially implemented areas.
4. Read `06` through `08` as forward-looking roadmap/spec material.
