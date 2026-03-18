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
- `#100` exists on `codex/git-aware-task-workspaces`
- `#101` exists on `codex/cross-project-command-center`
- `#102` exists on `codex/queue-worker-capacity-governance`
- `#103` exists on `codex/queue-worker-capacity-governance`
- `#104` exists on `codex/queue-worker-capacity-governance`
- `#105` exists on `codex/queue-worker-capacity-governance`
- `#106` exists on `codex/queue-worker-capacity-governance`
- `#107` exists on `codex/ux-product-redesign`
- `#108` exists on `codex/ux-product-redesign`
- `#109` exists on `codex/ux-product-redesign`
- `#110` exists on `codex/ux-product-redesign`
- `#111` exists on `codex/ux-product-redesign`
- `#112` exists on `codex/ux-product-redesign`
- `#113` exists on `codex/ux-product-redesign`
- `#114` exists on `codex/ux-product-redesign`
- `#115` exists on `codex/ux-product-redesign`
- `#116` exists on `codex/ux-product-redesign`
- `#117` exists on `codex/linear-vibekanban-cockpit`
- `#118` exists on `codex/linear-vibekanban-cockpit`
- `#119` exists on `codex/linear-vibekanban-cockpit`
- `#120` exists on `codex/linear-vibekanban-cockpit`
- `#121` exists on `codex/linear-vibekanban-cockpit`
- `#122` exists on `codex/linear-vibekanban-cockpit`
- `#123` exists on `codex/linear-vibekanban-cockpit`
- `#124` exists on `codex/linear-vibekanban-cockpit`
- `#125` exists on `codex/linear-vibekanban-cockpit`
- `#126` exists on `codex/linear-vibekanban-cockpit`
- `#127` exists on `codex/linear-vibekanban-cockpit`
- `#128` exists on `codex/linear-vibekanban-cockpit`
- `#129` exists on `codex/linear-vibekanban-cockpit`
- `#130` exists on `codex/linear-vibekanban-cockpit`
- `#131` exists on `codex/linear-vibekanban-cockpit`
- `#132` exists on `codex/linear-vibekanban-cockpit`
- `#133` exists on `codex/linear-vibekanban-cockpit`
- `#134` exists on `codex/linear-vibekanban-cockpit`
- `#135` exists on `codex/linear-vibekanban-cockpit`
- `#136` exists on `codex/linear-vibekanban-cockpit`
- `#137` exists on `codex/linear-vibekanban-cockpit`
- `#138` exists on `codex/linear-vibekanban-cockpit`
- `#139` exists on `codex/linear-vibekanban-cockpit`
- `#140` exists on `codex/linear-vibekanban-cockpit`
- `#141` exists on `codex/linear-vibekanban-cockpit`
- `#142` exists on `codex/linear-vibekanban-cockpit`
- `#143` exists on `codex/linear-vibekanban-cockpit`
- `#144` exists on `codex/linear-vibekanban-cockpit`
- `#145` exists on `codex/linear-vibekanban-cockpit`
- `#146` exists on `codex/linear-vibekanban-cockpit`
- `#147` exists on `codex/linear-vibekanban-cockpit`
- `#148` exists on `codex/linear-vibekanban-cockpit`
- `#149` exists on `codex/linear-vibekanban-cockpit`
- `#150` exists on `codex/linear-vibekanban-cockpit`
- `#151` exists on `codex/linear-vibekanban-cockpit`

The current numbered `#81-#151` sequence is fully implemented on the stacked branch chain above `main`.

The current product-modeling sequence on `codex/linear-vibekanban-cockpit` now covers the Seraph-style cockpit pivot (`#127-#136`), the Linear/Vibekanban-inspired workflow cleanup (`#137-#146`), and the clarified Cockpit/Board role split (`#147-#151`).

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
- [ ] The biggest remaining roadmap buckets are project lifecycle/orchestration hardening, deeper brownfield execution, stronger recovery automation, stronger isolation, and broader provider/runtime coverage.

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
- [x] `#97` Cross-project scheduler fairness and capacity policy:
  prevent one project from starving others once multi-project orchestration is always-on.
- [x] `#98` Repo-grounded plan synthesis and refresh:
  generate and refresh task graphs directly from the brownfield codebase map and drift signals.
- [x] `#99` Verification runners and evidence capture:
  turn test/lint/build commands into first-class verification jobs with durable logs and artifacts.
- [x] `#100` Git-aware task workspaces and diff review:
  add task branches/worktrees, changed-file tracking, and reviewable diff artifacts.
- [x] `#101` Cross-project command center:
  add a portfolio-level operator surface for escalations, recovery pressure, and global system health.
- [x] `#102` Queue and worker capacity controls:
  broaden capacity governance beyond per-provider pass limits into queue concurrency and drain controls.
- [x] `#103` Policy-driven approval and risk routing:
  route risky actions into approval flows based on project policy and touched scope.
- [x] `#104` Cost, runtime, and quota controls:
  enforce per-project and per-provider usage budgets.
- [x] `#105` Notifications and outbound integrations:
  push important incidents out of the dashboard via webhooks or messaging integrations.
- [x] `#106` Incident timeline and replay:
  add a correlated incident history so operators can reconstruct what happened across tasks, alerts, sessions, and recovery actions.
- [x] `#107` Information architecture reset and navigation collapse:
  reduce the current top-level page sprawl into a smaller set of primary surfaces with user-language labels and a clearer mental model.
- [x] `#108` Design system and dual light/dark theme foundation:
  introduce semantic design tokens and persistent light/dark modes so the control room feels like a real product, not an internal admin tool.
- [x] `#109` Home command center with recommended actions:
  create a single landing surface that prioritizes “what needs attention” and “what should I do next” over raw subsystem telemetry.
- [x] `#110` Guided onboarding and first-run experience:
  add a setup flow for project creation/import, brownfield review, runtime readiness, and first supervised pass.
- [x] `#111` Unified Work surface for board, plan, and task detail:
  merge board, goal tree, and repo-grounded planning into one execution workspace with richer task detail and evidence.
- [x] `#112` Unified Runs surface for agents, providers, verification, and outputs:
  merge execution telemetry and output inspection into one coherent operator view.
- [x] `#113` Unified Incidents surface for failures, alerts, recovery, and timeline:
  replace the current mechanism-heavy page split with one incident workbench and clearer playbooks.
- [x] `#114` Portfolio and project-management UX redesign:
  improve multi-project supervision, lifecycle actions, and project switching without exposing policy forms as the default experience.
- [x] `#115` Command palette, contextual actions, empty states, and inline guidance:
  make advanced capabilities discoverable while keeping the default UI simple.
- [x] `#116` Accessibility, responsiveness, and visual-polish pass:
  finish the redesign with keyboard-first interactions, mobile/tablet behavior, hierarchy cleanup, and usability QA.
- [x] `#117` Shell density reset:
  remove the oversized landing-page shell and replace it with a compact top strip, tighter navigation, and smaller controls.
- [x] `#118` Default control room layout:
  make the landing screen a dense three-pane operator cockpit with agents on the left, kanban in the center, and ops context on the right.
- [x] `#119` Compact kanban redesign:
  replace oversized cards with compact execution cards that expose assignee, goal, evidence signals, and failure pressure at a glance.
- [x] `#120` Agent roster and interaction view:
  turn agents into first-class visible actors with status, current work, heartbeat, and quick intervention hooks.
- [x] `#121` Curated live ticker:
  add a dense meaningful-event feed so the system feels alive without turning into raw telemetry spam.
- [x] `#122` Goal/subgoal/task relationship explorer:
  expose selected-task goal lineage, sibling work, repo-plan matches, and recent task-specific history in one inspector.
- [x] `#123` Incident rail and playbooks:
  surface actionable incidents directly in the right rail instead of forcing operators to hunt through separate admin pages.
- [x] `#124` Evidence and verification drawer:
  put verification state, git diff evidence, artifacts, and task history next to the selected task.
- [x] `#125` Project status and portfolio command bar:
  move project selection, health, alert load, and transport/runtime status into a compact top command strip.
- [x] `#126` Remove legacy hero UX and final dense visual pass:
  shrink typography, card heights, and button scale across the control room so the product reads like an operations cockpit instead of a landing page.
- [x] `#127` Seraph-style cockpit shell pivot:
  replace the page-and-card shell with a fixed-height cockpit shell, compact top bar, internal scroll regions, and explicit workspace modes such as ops, focus, and review.
- [x] `#128` Panel workspace and windowed composition:
  reorganize the default experience into persistent left-rail, center-workspace, and right-rail panels with panel-scoped overflow instead of stacked sections.
- [x] `#129` Cockpit command bar and telemetry strip:
  collapse navigation, project switching, live transport state, run controls, and quick commands into one dense operator bar.
- [x] `#130` Dense agent rail:
  rebuild agent visibility as a compact live rail with status, current work, recent meaningful events, and fast intervention hooks.
- [x] `#131` Center kanban workspace rewrite:
  make the board the primary workspace with denser cards, fewer empty lanes, scoped backlog access, and better ops/focus/review modes.
- [x] `#132` Right ops rail for incidents and ticker:
  merge the curated feed, approvals, alerts, and incident shortcuts into one compact ops rail instead of separate dashboard blocks.
- [x] `#133` Inspector and evidence workspace:
  turn selected-task context into a true inspector with goal path, repo scope, verification, git diff, artifacts, and history in one persistent panel.
- [x] `#134` Utility drawers for projects, providers, and settings:
  move lifecycle forms, provider settings, quotas, and policy editors out of the primary workspace into drawers and advanced utility windows.
- [x] `#135` Cockpit typography and theme system:
  replace the current generic card styling with a denser mono-forward cockpit system inspired by Seraph’s shell without copying its game flavor.
- [x] `#136` Remove legacy page surfaces and finish the cockpit interaction model:
  delete or demote the old dashboard/page paradigm so MAAS reads as one coherent cockpit instead of multiple competing UI systems.
- [x] `#137` Guided onboarding takeover:
  make import and first-run feel like one flow by surfacing the selected project, onboarding status, and next action before portfolio administration.
- [x] `#138` Compact issue cards and inspector-first steering:
  turn task cards into compact summaries and move steering controls into a persistent inspector instead of embedding forms in every card.
- [x] `#139` Board-first workflow defaults:
  make the board and cockpit the obvious operating destinations while demoting advanced portfolio and settings surfaces.
- [x] `#140` Import and create drawers:
  move repo import and project creation into compact secondary panels with folder picking and clearer CTA text.
- [x] `#141` Project next-step workflow:
  show one clear “what to do next” block for the selected project, especially for brownfield onboarding and gated imported work.
- [x] `#142` Curated live-ops priorities:
  keep agents, incidents, and feed visible while suppressing low-value control clutter and backend-first terminology.
- [x] `#143` Linear/Vibekanban-inspired board polish:
  tighten lane summaries, card hierarchy, and workspace density so the main board reads like an issue system instead of an admin dashboard.
- [x] `#144` Utility and settings demotion:
  keep provider, portfolio, and policy controls available, but push them behind advanced panes instead of default workflow surfaces.
- [x] `#145` Dense typography and dark-theme cleanup:
  reduce oversized type and blank space while fixing dark-theme readability and panel contrast.
- [x] `#146` Remove remaining inline control clutter:
  strip default work surfaces down to the minimum needed to scan, inspect, and act quickly.
- [x] `#147` Distinct Cockpit and Board roles:
  keep Cockpit as a supervisor-only monitoring surface and Board as the only task workspace with the inspector.
- [x] `#148` Guided brownfield review/start flow:
  turn imported-repo onboarding into one visible takeover on the Board with direct review, rescan, and plan-refresh actions.
- [x] `#149` Unified Run action and advanced control demotion:
  collapse supervisor/orchestrator into one default `Run` action for normal users and push internal runtime language out of the main workspace.
- [x] `#150` Intent-first project setup flow:
  replace the always-open generic project form with a simpler `Import repo` vs `New workspace` chooser.
- [x] `#151` Inspector-visible board interaction model:
  keep the task inspector persistently visible and make board-card selection, not inline card actions, the dominant interaction model.

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
- [x] `#100` is implemented on `codex/git-aware-task-workspaces`
- [x] `#101` is implemented on `codex/cross-project-command-center`
- [x] `#102` is implemented on `codex/queue-worker-capacity-governance`
- [x] `#103` is implemented on `codex/queue-worker-capacity-governance`
- [x] `#104` is implemented on `codex/queue-worker-capacity-governance`
- [x] `#105` is implemented on `codex/queue-worker-capacity-governance`
- [x] `#106` is implemented on `codex/queue-worker-capacity-governance`
- [x] `#107` is implemented on `codex/ux-product-redesign`
- [x] `#108` is implemented on `codex/ux-product-redesign`
- [x] `#109` is implemented on `codex/ux-product-redesign`
- [x] `#110` is implemented on `codex/ux-product-redesign`
- [x] `#111` is implemented on `codex/ux-product-redesign`
- [x] `#112` is implemented on `codex/ux-product-redesign`
- [x] `#113` is implemented on `codex/ux-product-redesign`
- [x] `#114` is implemented on `codex/ux-product-redesign`
- [x] `#115` is implemented on `codex/ux-product-redesign`
- [x] `#116` is implemented on `codex/ux-product-redesign`

The current numbered `#81-#116` sequence is fully implemented on the stacked branch chain above `main`.

The UX and product-design `#107-#116` sequence is now implemented on `codex/ux-product-redesign`.

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
- [x] `#100` Git-aware task workspaces and diff review
- [x] `#101` Cross-project command center
- [x] `#102` Queue and worker capacity controls
- [x] `#103` Policy-driven approval and risk routing
- [x] `#104` Cost, runtime, and quota controls
- [x] `#105` Notifications and outbound integrations
- [x] `#106` Incident timeline and replay
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
