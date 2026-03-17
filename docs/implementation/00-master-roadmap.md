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
| 3. Runtime lifecycle and adapters | `[ ]` | Lifecycle operations, API/CLI entrypoints, provider registry, concrete simulated adapters for Python Script, Claude Code, and OpenAI Codex, plus local Claude and Codex CLI paths, provider runtime status/history reads, manual provider runs, provider mode switching, and editable provider settings |
| 4. Greenfield onboarding | `[x]` | `maas init`, generated workspace, seeded backlog, project-understanding artifact |
| 5. Supervisor, dashboard, and Kanban V1 | `[ ]` | Board API, board UI, control-room views, supervisor loop, ready refresh, idle-agent allocation, overview/roster operator controls, board/overview/goal tree/failure/provider/artifact reads, artifact browser with preview/download/compare/provenance/export flows, artifact-row operator actions, live websocket transport, and overview/failure/recovery action controls |
| 6. Security and human steering | `[ ]` | Review, reprioritize, reassign, pause/resume, halt actions with audit logging, board controls, role-baseline gating, task-scoped execution grants, and escalation queue approvals |
| 7. Resilience and failure memory | `[ ]` | Stale-session detection, failure logging for failed/timed-out sessions, timed-out and failed-session auto-retry, quarantine queue restore/dismiss/reopen workflows, repeated-failure alerts, failure-action read-model visibility across Failures/Overview/Recovery/Artifacts, and task plus agent recovery exist; broader recovery is still pending |
| 8. Brownfield and multi-project | `[ ]` | Brownfield onboarding has started on `main`; deeper import, multi-project, and isolation are still pending |

## Progress Summary

- [x] The shipped repository now covers most of the greenfield single-project operator loop.
- [x] Brownfield onboarding has started on `main` with repo detection, approval gating, imported workflow/repo-area backlog seeding, and overview visibility.
- [x] The current implementation is roughly `85-90%` complete for that prototype target.
- [ ] The repository is still much earlier against the broader long-horizon roadmap.
- [ ] The biggest remaining roadmap buckets are deeper brownfield import, multi-project expansion, stronger isolation, smarter planning and scheduling, broader provider/runtime coverage, and stronger recovery automation.

## Next Recommended PR Sequence

- [ ] `#75` Brownfield codebase map and repo-derived planning:
  extend brownfield import from summary signals into a real codebase map with detected services, tests, packages, and runnable workflows that seed more concrete reviewable task graphs.
- [ ] `#76` Multi-project foundation:
  introduce first-class project scoping for read models, provider config, artifact roots, recovery policy, and operator surfaces so one MAAS workspace can manage more than one project safely.
- [ ] `#77` Runtime sandbox and isolation hardening:
  add stricter provider execution boundaries, artifact-path isolation, and command/runtime guardrails so live-provider and brownfield execution surfaces are safer.
- [ ] `#78` Adaptive replanning and scheduler feedback:
  expand the explicit scheduler into a feedback loop that can demote, split, or defer stuck work based on retry pressure, failures, and brownfield repo signals.
- [ ] `#79` Policy-driven self-healing and DLQ automation:
  turn the current recovery workbench into a stronger automation layer with circuit breakers, quarantine policies, and guarded automatic recovery/escalation decisions.
- [ ] `#80` Broader provider/runtime coverage:
  add the next live execution modes beyond local CLI paths once scheduling, isolation, and recovery policy are strong enough to support them.

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
