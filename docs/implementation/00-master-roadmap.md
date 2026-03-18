# MAAS Master Roadmap

## Summary

MAAS is being implemented as a single-project, greenfield-first, board-first agent operating system. The first shipped slice centers the Kanban board, seeded task graph, SQLite blackboard, and lifecycle contract so humans can see work moving from planned to done.

## Current Status

This roadmap now needs to be read alongside the actual implementation status in `docs/implementation/STATUS.md`.

Legend for numbered roadmap checklists:

- `[x]` completed in the current numbered delivery sequence
- `[ ]` not yet completed in the current numbered delivery sequence

Use "Current stacked development chain above `main`" to see which completed items are on `main` versus stacked branches.

Current stacked development chain above `main`:

- `#82` exists on `codex/project-aware-supervisor-orchestration`
- `#83` exists on `codex/brownfield-file-backed-planning`
- `#84` exists on `codex/recovery-circuit-breakers`
- `#85` exists on `codex/project-isolated-provider-runtime`
- `#86` exists on `codex/provider-job-queue`
- `#87` exists on `codex/provider-job-queue`
- `#88` exists on `codex/file-linked-task-scopes`
- `#89` exists on `codex/brownfield-runbook-command-catalog`
- `#90` exists on `codex/brownfield-runbook-command-catalog`
- `#91` exists on `codex/brownfield-runbook-command-catalog`
- `#92` exists on `codex/queue-capacity-controls`
- `#93` exists on `codex/session-runner-envelopes`
- `#94` exists on `codex/policy-driven-self-healing-v2`
- `#95` exists on `codex/brownfield-onboarding-review-v2`
- `#96` exists on `codex/remote-executor-worker-pool`
- `#97` exists on `codex/cross-project-scheduler-fairness`
- `#98` exists on `codex/repo-grounded-plan-synthesis`
- `#99` exists on `codex/verification-runners-evidence-capture`
- `#100` is the next unfinished item in sequence

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

## Current Numbered Delivery Sequence

- [x] `#80` Provider runtime preflight and readiness checks:
  let operators verify live runtime readiness before task execution by checking CLI availability, required auth env, and persisted readiness state in the Providers surface.
- [x] `#81` Multi-project write path and project lifecycle:
  move beyond read scoping by adding create/import/archive flows, project-scoped write operations, and explicit lifecycle management for multiple repos.
- [x] `#82` Project-aware supervisor and background orchestration:
  make the scheduler, supervisor, live transport, and recovery automation operate cleanly per project instead of assuming a single active workspace loop.
- [x] `#83` Brownfield file-backed planning and repo navigation:
  turn brownfield discovery into file-linked task graphs, code-area navigation, and reviewable imported workflow execution plans that operators can actually steer.
- [x] `#84` Policy-driven self-healing and circuit breakers:
  expand the current recovery workbench into guarded automation for recover/requeue/quarantine/escalate decisions with explicit stop conditions.
- [x] `#85` Sandboxed provider runners per project:
  strengthen runtime isolation by moving from sanitized subprocess envs to clearer per-project runtime boundaries and safer execution sandboxes.
- [x] `#86` Remote or queued provider execution beyond local CLI paths:
  add the next meaningful execution mode after local CLI paths, such as a queued or remote runner, once readiness and isolation are strong enough.
- [x] `#87` Brownfield rescan and drift detection:
  rerun imported-repo discovery, detect meaningful changes, and reopen onboarding review when the codebase drifts.
- [x] `#88` File-linked task scopes and acceptance criteria:
  make brownfield seeded work concrete by attaching real paths and derived validation commands.
- [x] `#89` Brownfield runbook and command catalog:
  turn discovered workflow signals into a reviewable operator runbook with concrete command recipes.
- [x] `#90` Portfolio view across projects:
  add a cross-project operational surface for health, alerts, sessions, recovery pressure, and provider readiness.
- [x] `#91` Background orchestration daemon:
  add a reusable orchestration pass that coordinates supervisor and queued provider job processing across projects.
- [x] `#92` Queue and worker capacity controls:
  expose per-provider queue pause and per-pass limits so queued execution can be throttled safely.
- [x] `#93` Stronger runner sandbox envelopes beyond the current per-project runtime isolation:
  add per-session runner envelopes with isolated temp/home/cache roots and persisted run manifests.
- [x] `#94` Policy-driven self-healing v2:
  expand circuit breakers into richer automatic recover/defer/replan/DLQ decisions with explicit stop conditions.
- [x] `#95` Brownfield onboarding review v2:
  let operators edit ignored paths, accepted workflows, and runbook commands before imported work is released.
- [x] `#96` Remote executor or worker pool:
  add execution beyond direct local CLI runs by introducing queued remote workers.
- [ ] `#97` Cross-project scheduler fairness and capacity policy:
  prevent one project from starving others once multi-project orchestration is always-on.
- [ ] `#98` Repo-grounded plan synthesis and refresh:
  generate and refresh task graphs directly from the brownfield codebase map and drift signals.
- [x] `#99` Verification runners and evidence capture:
  turn test/lint/build commands into first-class verification jobs with durable logs and artifacts.
- [ ] `#100` Git-aware task workspaces and diff review:
  add task branches/worktrees, changed-file tracking, and reviewable diff artifacts.
- [ ] `#101` Cross-project command center:
  add a portfolio-level operator surface for escalations, recovery pressure, and global system health.
- [ ] `#102` Queue and worker capacity controls:
  broaden capacity governance beyond per-provider pass limits into queue concurrency and drain controls.
- [ ] `#103` Policy-driven approval and risk routing:
  route risky actions into approval flows based on project policy and touched scope.
- [ ] `#104` Cost, runtime, and quota controls:
  enforce per-project and per-provider usage budgets.
- [ ] `#105` Notifications and outbound integrations:
  push important incidents out of the dashboard via webhooks or messaging integrations.
- [ ] `#106` Incident timeline and replay:
  add a correlated incident history so operators can reconstruct what happened across tasks, alerts, sessions, and recovery actions.

## Current Stacked Branch Progress

- [x] `#81` is shipped on `main`
- [x] `#82` is implemented on `codex/project-aware-supervisor-orchestration`
- [x] `#83` is implemented on `codex/brownfield-file-backed-planning`
- [x] `#84` is implemented on `codex/recovery-circuit-breakers`
- [x] `#85` is implemented on `codex/project-isolated-provider-runtime`
- [x] `#86` is implemented on `codex/provider-job-queue`
- [x] `#87` is implemented on `codex/provider-job-queue`
- [x] `#88` is implemented on `codex/file-linked-task-scopes`
- [x] `#89` is implemented on `codex/brownfield-runbook-command-catalog`
- [x] `#90` is implemented on `codex/brownfield-runbook-command-catalog`
- [x] `#91` is implemented on `codex/brownfield-runbook-command-catalog`
- [x] `#92` is implemented on `codex/queue-capacity-controls`
- [x] `#93` is implemented on `codex/session-runner-envelopes`
- [x] `#94` is implemented on `codex/policy-driven-self-healing-v2`
- [x] `#95` is implemented on `codex/brownfield-onboarding-review-v2`
- [x] `#96` is implemented on `codex/remote-executor-worker-pool`
- [x] `#97` is implemented on `codex/cross-project-scheduler-fairness`
- [x] `#98` is implemented on `codex/repo-grounded-plan-synthesis`
- [x] `#99` is implemented on `codex/verification-runners-evidence-capture`
- [ ] `#100` is the next unfinished item

## Extended Numbered Roadmap

- [x] `#81` Multi-project write path and project lifecycle
- [x] `#82` Project-aware supervisor and background orchestration
- [x] `#83` Brownfield file-backed planning and repo navigation
- [x] `#84` Policy-driven self-healing and circuit breakers
- [x] `#85` Sandboxed provider runners per project
- [x] `#86` Remote or queued provider execution beyond local CLI paths
- [x] `#87` Brownfield rescan and drift detection
- [x] `#88` File-linked task scopes and acceptance criteria
- [x] `#89` Brownfield runbook and command catalog
- [x] `#90` Portfolio view across projects
- [x] `#91` Background orchestration daemon
- [x] `#92` Queue and worker capacity management on top of the provider job queue
- [x] `#93` Stronger runner sandbox envelopes beyond the current per-project runtime isolation
- [x] `#94` Policy-driven self-healing v2
- [x] `#95` Brownfield onboarding review v2
- [x] `#96` Remote executor or worker pool
- [x] `#97` Cross-project scheduler fairness and capacity policy
- [x] `#98` Repo-grounded plan synthesis and refresh
- [x] `#99` Verification runners and evidence capture
- [ ] `#100` Git-aware task workspaces and diff review
- [ ] `#101` Cross-project command center
- [ ] `#102` Queue and worker capacity controls
- [ ] `#103` Policy-driven approval and risk routing
- [ ] `#104` Cost, runtime, and quota controls
- [ ] `#105` Notifications and outbound integrations
- [ ] `#106` Incident timeline and replay

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
