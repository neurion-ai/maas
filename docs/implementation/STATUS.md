# MAAS Development Status

## Current Product Direction

MAAS is pivoting away from the previous "board-first software delivery control room" framing toward a Codex-first autonomous-work control plane.

The corrected near-term thesis is:

- MAAS is the control plane for Codex-driven autonomous work
- the MVP is explicitly `Codex-only`
- MAAS owns orchestration, state transitions, review gates, logs, metrics, incident handling, and operator control

The operator-facing nouns should be kept tight:

- `Goal`
- `Issue`
- `Run`
- `Agent`
- `Event`
- `Incident`

The intended primary surfaces are:

- `Command`
- `Theater`
- `Work`
- `Issues`
- `Agents`
- `Runs`
- `System`
- `Projects`

This matters because a large amount of code below still reflects the earlier software-delivery phase. The historical implementation checklist remains useful as implementation history, but it should not be mistaken for the current MVP shape.

## Current Truth and Execution Contract

Use the MAAS docs and GitHub project with a strict split:

- current truth: [README.md](../../README.md), [STATUS.md](STATUS.md), and [WORKFLOW.md](WORKFLOW.md)
- active execution: [MAAS Delivery & Execution](https://github.com/orgs/neurion-ai/projects/4)
- history/reference: [00-master-roadmap.md](00-master-roadmap.md) and the numbered implementation docs in this directory

Rules:

- do not use the numbered implementation docs as the active queue
- do not create competing active roadmap, status, queue, or runbook files
- keep roadmap identifiers in GitHub issue titles when work maps to numbered items, for example `Roadmap #226: Goal-to-issue explainability and critical path view`

`main` now includes the shipped post-`#224` slices through `#234`. Follow-on batch planning now lives in GitHub issues and the project board instead of new active-plan docs.
The current unattended-local-trust hardening program is tracked in GitHub batches `#129-#133`, with Batch `#129` establishing reconciliation-backed truth inspection and repair and Batch `#130` making notification, provider, git-workspace, and GitHub-sync side effects retry-safe and idempotent.

See:

- [README.md](../../README.md)
- [09-autonomous-organization-pivot.md](09-autonomous-organization-pivot.md)
- [10-ui-reset.md](10-ui-reset.md)
- [11-codex-mvp-shape.md](11-codex-mvp-shape.md)
- [12-codex-mvp-integration-plan.md](12-codex-mvp-integration-plan.md)
- [13-codex-mvp-hardening-plan.md](13-codex-mvp-hardening-plan.md)
- [14-codex-mvp-next-batch-plan.md](14-codex-mvp-next-batch-plan.md)
- [15-codex-mvp-autonomy-scale-plan.md](15-codex-mvp-autonomy-scale-plan.md)
- [16-codex-mvp-autopilot-memory-plan.md](16-codex-mvp-autopilot-memory-plan.md)
- [17-codex-mvp-control-loop-hardening-plan.md](17-codex-mvp-control-loop-hardening-plan.md)
- [18-codex-mvp-doctor-delivery-loop-plan.md](18-codex-mvp-doctor-delivery-loop-plan.md)
- [19-codex-mvp-delivery-execution-verification-plan.md](19-codex-mvp-delivery-execution-verification-plan.md)
- [20-codex-mvp-explainability-review-memory-plan.md](20-codex-mvp-explainability-review-memory-plan.md)
- [21-codex-mvp-control-loop-governance-observability-plan.md](21-codex-mvp-control-loop-governance-observability-plan.md)
- [22-codex-mvp-brownfield-depth-pass.md](22-codex-mvp-brownfield-depth-pass.md)
- [23-codex-mvp-brownfield-execution-leverage.md](23-codex-mvp-brownfield-execution-leverage.md)
- [24-codex-mvp-brownfield-drift-refresh-trust.md](24-codex-mvp-brownfield-drift-refresh-trust.md)
- [26-execution-theater-foundation.md](26-execution-theater-foundation.md)
- [27-execution-theater-field-agent-motion.md](27-execution-theater-field-agent-motion.md)
- [28-execution-theater-branch-worktree-pr-lineage.md](28-execution-theater-branch-worktree-pr-lineage.md)
- [29-execution-theater-internal-production-readiness.md](29-execution-theater-internal-production-readiness.md)
- [30-local-dev-lifecycle-scripts.md](30-local-dev-lifecycle-scripts.md)
- [31-unattended-local-trust-invariants-reconciliation.md](31-unattended-local-trust-invariants-reconciliation.md)
- [32-unattended-local-trust-idempotent-side-effects.md](32-unattended-local-trust-idempotent-side-effects.md)
- [mockups/maas-codex-mvp/README.md](../../mockups/maas-codex-mvp/README.md)

## GitHub Project Contract

The project board is the execution layer. Each tracked task should have one GitHub issue, one truthful project item, and a linked PR once implementation starts.

Project fields:

- `Queue`: `Now`, `Next`, `Background`, `Blocked`
- `Status`: `Todo`, `In Progress`, `Done`
- `Lane`: `Delivery`, `Planning`, `Review & Memory`, `Autonomy & Recovery`, `Observability`, `Brownfield`, `Workflow`
- `Priority`: `P0`, `P1`, `P2`
- `Size`: `S`, `M`, `L`
- `Code Review`: `Not Ready`, `Pending`, `Running`, `Passed`, `Changes Requested`
- `PR`: `Not Ready`, `Open`, `Merged`
- `Linked pull requests`: actual GitHub linkage

Board flow:

- issue created or refined: set `Queue`, `Lane`, `Priority`, `Size`, `Code Review = Not Ready`, and `PR = Not Ready`
- work starts: set `Status = In Progress`
- PR opens: link the PR to the issue, set `PR = Open`, and set `Code Review = Pending`
- review or validation runs: set `Code Review = Running`, then either `Passed` or `Changes Requested`
- merge: set `PR = Merged` and `Status = Done`

## Legend

- `[x]` completed in the current numbered delivery sequence
- `[ ]` not yet completed in the current numbered delivery sequence

The historical sequence below shows whether a completed item is already on `main` or still only exists on stacked branches. Post-`#224` planning and sequencing now live in the GitHub project, not in this file.

## Historical Development Sequence

- [x] `#81` is shipped on `main`
- [x] `#82` is implemented on the stacked branch `codex/project-aware-supervisor-orchestration`
- [x] `#83` is implemented on the stacked branch `codex/brownfield-file-backed-planning`
- [x] `#84` is implemented on the stacked branch `codex/recovery-circuit-breakers`
- [x] `#85` is implemented on the stacked branch `codex/project-isolated-provider-runtime`
- [x] `#86` is implemented on the stacked branch `codex/provider-job-queue`
- [x] `#87` is implemented on the stacked branch `codex/provider-job-queue`
- [x] `#88` is implemented on the stacked branch `codex/file-linked-task-scopes`
- [x] `#89` is implemented on the stacked branch `codex/brownfield-runbook-command-catalog`
- [x] `#90` is implemented on the stacked branch `codex/brownfield-runbook-command-catalog`
- [x] `#91` is implemented on the stacked branch `codex/brownfield-runbook-command-catalog`
- [x] `#92` is implemented on the stacked branch `codex/queue-capacity-controls`
- [x] `#93` is implemented on the stacked branch `codex/session-runner-envelopes`
- [x] `#94` is implemented on the stacked branch `codex/policy-driven-self-healing-v2`
- [x] `#95` is implemented on the stacked branch `codex/brownfield-onboarding-review-v2`
- [x] `#96` is implemented on the stacked branch `codex/remote-executor-worker-pool`
- [x] `#97` is implemented on the stacked branch `codex/cross-project-scheduler-fairness`
- [x] `#98` is implemented on the stacked branch `codex/repo-grounded-plan-synthesis`
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
- [x] `#117` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#118` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#119` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#120` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#121` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#122` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#123` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#124` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#125` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#126` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#127` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#128` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#129` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#130` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#131` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#132` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#133` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#134` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#135` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#136` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#137` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#138` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#139` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#140` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#141` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#142` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#143` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#144` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#145` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#146` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#147` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#148` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#149` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#150` is implemented on `codex/linear-vibekanban-cockpit`
- [x] `#151` is implemented on `codex/linear-vibekanban-cockpit`

The current numbered `#81-#151` sequence is fully implemented on the stacked branch chain above `main`.

The current product-modeling sequence on `codex/linear-vibekanban-cockpit` now covers the cockpit pivot (`#127-#136`), the Linear/Vibekanban-inspired workflow cleanup (`#137-#146`), and the clarified Cockpit/Board role split (`#147-#151`).

- [x] `#161` is implemented on `codex/codex-mvp-shell-integration`
- [x] `#162` is implemented on `codex/codex-mvp-shell-integration`
- [x] `#163` is implemented on `codex/codex-mvp-shell-integration`
- [x] `#164` is implemented on `codex/codex-mvp-shell-integration`
- [x] `#165` is implemented on `codex/codex-mvp-shell-integration`
- [x] `#166` is implemented on `codex/codex-mvp-shell-integration`
- [x] `#167` is implemented on `codex/codex-mvp-shell-integration`
- [x] `#168` is implemented on `codex/codex-mvp-shell-integration`
- [x] `#169` is implemented on `codex/codex-mvp-shell-integration`
- [x] `#170` is implemented on `codex/codex-mvp-shell-integration`
- [x] `#171` is implemented on `codex/codex-mvp-hardening`
- [x] `#172` is implemented on `codex/codex-mvp-hardening`
- [x] `#173` is implemented on `codex/codex-mvp-hardening`
- [x] `#174` is implemented on `codex/codex-mvp-hardening`
- [x] `#175` is implemented on `codex/codex-mvp-hardening`
- [x] `#176` is implemented on `codex/codex-mvp-hardening`
- [x] `#177` is implemented on `codex/codex-mvp-hardening`
- [x] `#178` is implemented on `codex/codex-mvp-hardening`
- [x] `#179` is implemented on `codex/codex-mvp-operator-scale`
- [x] `#180` is implemented on `codex/codex-mvp-operator-scale`
- [x] `#181` is implemented on `codex/codex-mvp-operator-scale`
- [x] `#182` is implemented on `codex/codex-mvp-operator-scale`
- [x] `#183` is implemented on `codex/codex-mvp-operator-scale`
- [x] `#184` is implemented on `codex/codex-mvp-operator-scale`
- [x] `#185` is implemented on `codex/codex-mvp-operator-scale`
- [x] `#186` is implemented on `codex/codex-mvp-operator-scale`
- [x] `#187` is implemented on `codex/codex-mvp-operator-scale`
- [x] `#188` is implemented on `codex/codex-mvp-autonomy-scale`
- [x] `#189` is implemented on `codex/codex-mvp-autonomy-scale`
- [x] `#190` is implemented on `codex/codex-mvp-autonomy-scale`
- [x] `#191` is implemented on `codex/codex-mvp-autonomy-scale`
- [x] `#192` is implemented on `codex/codex-mvp-autonomy-scale`
- [x] `#193` is implemented on `codex/codex-mvp-autonomy-scale`
- [x] `#194` is implemented on `codex/codex-mvp-autonomy-scale`
- [x] `#195` is implemented on `codex/codex-mvp-autonomy-scale`
- [x] `#196` is implemented on `codex/codex-mvp-autonomy-scale`
- [x] `#197` is implemented on `codex/codex-mvp-autopilot-memory`
- [x] `#198` is implemented on `codex/codex-mvp-autopilot-memory`
- [x] `#199` is implemented on `codex/codex-mvp-autopilot-memory`
- [x] `#200` is implemented on `codex/codex-mvp-autopilot-memory`
- [x] `#201` is implemented on `codex/codex-mvp-autopilot-memory`
- [x] `#202` is implemented on `codex/codex-mvp-autopilot-memory`
- [x] `#203` is implemented on `codex/codex-mvp-autopilot-memory`
- [x] `#204` is implemented on `codex/codex-mvp-autopilot-memory`
- [x] `#205` is implemented on `codex/codex-mvp-control-loop-hardening`
- [x] `#206` is implemented on `codex/codex-mvp-control-loop-hardening`
- [x] `#207` is implemented on `codex/codex-mvp-control-loop-hardening`
- [x] `#208` is implemented on `codex/codex-mvp-control-loop-hardening`
- [x] `#209` is implemented on `codex/codex-mvp-control-loop-hardening`
- [x] `#210` is implemented on `codex/codex-mvp-control-loop-hardening`
- [x] `#211` is implemented on `codex/codex-mvp-control-loop-hardening`
- [x] `#212` is implemented on `codex/codex-mvp-control-loop-hardening`
- [x] `#213` is implemented on `codex/codex-mvp-control-loop-hardening`
- [x] `#214` is implemented on `codex/codex-mvp-control-loop-hardening`
- [x] `#215` is implemented on `codex/codex-mvp-doctor-delivery-loop`
- [x] `#216` is implemented on `codex/codex-mvp-doctor-delivery-loop`
- [x] `#217` is implemented on `codex/codex-mvp-doctor-delivery-loop`
- [x] `#218` is implemented on `codex/codex-mvp-doctor-delivery-loop`
- [x] `#219` is implemented on `codex/codex-mvp-doctor-delivery-loop`
- [x] `#220` is implemented on `codex/codex-mvp-doctor-delivery-loop`
- [x] `#221` is implemented on `codex/codex-mvp-doctor-delivery-loop`
- [x] `#222` is implemented on `codex/codex-mvp-doctor-delivery-loop`
- [x] `#223` is implemented on `codex/codex-mvp-doctor-delivery-loop`
- [x] `#224` is implemented on `codex/codex-mvp-doctor-delivery-loop`
- [x] `#225` is shipped on `main`
- [x] `#226` is implemented on `codex/goal-explainability-review-memory-usefulness`
- [x] `#228` is implemented on `codex/goal-explainability-review-memory-usefulness`
- [x] `#229` is implemented on `codex/goal-explainability-review-memory-usefulness`
- [x] `#230` is shipped on `main`

## Historical Numbered Roadmap

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
- [x] `#127` Seraph-style cockpit shell pivot
- [x] `#128` Panel workspace and windowed composition
- [x] `#129` Cockpit command bar and telemetry strip
- [x] `#130` Dense agent rail
- [x] `#131` Center kanban workspace rewrite
- [x] `#132` Right ops rail for incidents and ticker
- [x] `#133` Inspector and evidence workspace
- [x] `#134` Utility drawers for projects, providers, and settings
- [x] `#135` Cockpit typography and theme system
- [x] `#136` Remove legacy page surfaces and finish the cockpit interaction model
- [x] `#137` Guided onboarding takeover
- [x] `#138` Compact issue cards and inspector-first steering
- [x] `#139` Board-first workflow defaults
- [x] `#140` Import and create drawers
- [x] `#141` Project next-step workflow
- [x] `#142` Curated live-ops priorities
- [x] `#143` Linear/Vibekanban-inspired board polish
- [x] `#144` Utility and settings demotion
- [x] `#145` Dense typography and dark-theme cleanup
- [x] `#146` Remove remaining inline control clutter
- [x] `#147` Distinct Cockpit and Board roles
- [x] `#148` Guided brownfield review/start flow
- [x] `#149` Unified Run action and advanced control demotion
- [x] `#150` Intent-first project setup flow
- [x] `#151` Inspector-visible board interaction model

## Current Snapshot

- [x] MAAS is usable today as a greenfield local prototype with a real operator-facing control room.
- [x] The board-first workflow, steering controls, escalation queue, and first-pass resilience foundations are in place.
- [x] Local live-provider operation exists for Claude Code and OpenAI Codex behind explicit project configuration.
- [x] Operators can now work incidents from multiple surfaces: Alerts, Failures, Recovery, Overview, and the Artifact browser.
- [x] Brownfield codebase mapping, multi-project read scoping, and first-pass live-provider isolation hardening are now on `main`.
- [x] Adaptive scheduling feedback, manual replanning, and retry-exhaustion DLQ routing are now on `main`.
- [x] The current prototype is roughly `85-90%` complete for the single-project greenfield/operator-supervised shape.
- [ ] MAAS is not yet a production-ready autonomous platform.
- [x] The stacked UX redesign now provides a simpler mental model, dual-theme shell, guided home surface, unified Work/Runs/Incidents pages, and command-palette navigation on top of the existing backend stack.
- [x] The current dense-control-room branch goes further by replacing the oversized hero/dashboard posture with a compact operator cockpit: top status strip, agent rail, dense kanban, incident rail, curated ticker, and selected-task evidence inspector.
- [x] The current Codex-MVP integration branch now replaces that shell in the real app with `Command`, `Work`, `Issues`, `Agents`, `System`, and `Projects`, backed by stable issue identity plus issue-detail and agent-detail aggregates.
- [x] The hardening batch on `main` now makes run posture, review detail, live-vs-simulated truth, project lifecycle, and agent layout materially more honest under real use.
- [x] The current autopilot-and-memory batch now adds always-on project loops, template-backed project creation, artifact-to-memory promotion, retrieval-backed Codex prompts, backend-owned batch review, and more truthful execution-state diagnostics.
- [ ] The next highest-value gaps are deeper live Codex streaming, richer recovery playbooks, stronger memory governance, and broader low-touch autonomy under real long-running load.
- [ ] The broader roadmap still depends on deeper brownfield import, multi-project expansion, stronger isolation, better planning, broader providers, and stronger automation.

## Shipped On `main`

### Core platform

- [x] Python package under `src/maas/`
- [x] SQLite-backed state with migrations
- [x] `.maas/` local workspace layout
- [x] `project.yaml` generation and loading
- [x] CLI entrypoints for init, migrate, API, supervisor, board, task, agent, worker, lifecycle, failure, and escalation operations

### Work orchestration

- [x] Goal and task records persisted in SQLite
- [x] Board-visible task states: `planned`, `ready`, `assigned`, `in_progress`, `review`, `blocked`, `done`, `cancelled`
- [x] Dependency storage for `blocks`, `informs`, and `conflicts`
- [x] Seeded greenfield backlog and project-understanding artifact
- [x] Dependency-aware ready-queue refresh
- [x] Idle-agent allocation and manual assign-next controls
- [x] Acceptance evaluation for `artifact_exists`, `metric`, `db_query`, and `test_passes`

### Runtime and provider layer

- [x] Lifecycle operations: `start_session`, `heartbeat`, `log_activity`, `produce_artifact`, `end_session`
- [x] Simulated local worker/runtime execution path
- [x] Provider-dispatched runtime path for `python_script`, `claude_code`, and `openai_codex`
- [x] Shared lifecycle contract for provider activity and artifact output
- [x] Real local Claude Code CLI execution path behind explicit provider config
- [x] Real local OpenAI Codex CLI execution path behind explicit provider config
- [x] Provider status visibility with effective mode, runtime controls, config warnings, preflight readiness, recent run history, manual run controls, mode switching, and editable settings
- [x] Explicit scheduler scoring, board-visible scheduler rationale, and adaptive replanning guidance

### Control room and steering

- [x] Board API with server-side grouping and filters
- [x] Overview, goal tree, agent roster, activity, alerts, escalations, failures, and live snapshot read models
- [x] React control-room views for Overview, Board, Goal Tree, Agent Roster, Activity, Artifacts, Providers, Recovery, Failures, Alerts, and Escalations
- [x] Operator controls for review approve/reject
- [x] Operator controls for reprioritize, reassign, pause/resume, and halt
- [x] Operator controls for manual supervisor runs and assign-next from the roster
- [x] Operator controls for safe manual provider runs from the Providers view
- [x] Operator controls for switching provider execution mode from the Providers view
- [x] Operator controls for editing provider runtime settings from the Providers view
- [x] Operator controls for policy editing, retry override review, retry-backoff release, retry-state reset, task recovery, alert-backed recovery, quarantine actions, and artifact-level quarantine actions
- [x] Role-baseline `board_actions` permission enforcement for steering and alert actions
- [x] Audit logging for steering actions
- [x] Escalation queue request, approve, and reject flows in API, CLI, and control room

### Security and execution permissions

- [x] Task-scoped capability grants for assigned execution work
- [x] Lifecycle enforcement for start, heartbeat, activity, artifact, and end-session writes
- [x] Grant revocation on task halt, reassignment, recovery, and session completion

### Resilience and failure handling

- [x] Stale-session detection in the supervisor pass
- [x] Failure-memory logging for failed and timed-out sessions
- [x] Timed-out session auto-retry with retry state surfaced in task and failure reads
- [x] Failed-session auto-retry with retry state surfaced in task and failure reads
- [x] Repeated-failure alerts for tasks with repeated failures
- [x] Failure visibility in board, overview, live, and dedicated failures reads
- [x] Quarantine details are visible in recent failure reads and the control-room failure surfaces
- [x] Artifact browser visibility includes artifact state, quarantine metadata, missing-file detection, preview, guarded download, compare, lineage/provenance pivots, export bundles, and direct quarantine actions
- [x] First-class quarantine queue reads plus restore, dismiss, reopen, and restore+requeue actions
- [x] Dead-letter queue routing for retry-exhausted tasks plus Recovery visibility and finish-replan resolution
- [x] Failure-specific operator actions for repeated-failure incidents and recovery-linked alerts
- [x] Overview and Failures surfaces expose direct operator actions for recent failures and repeated-failure tasks
- [x] Operator recovery for failure-blocked tasks
- [x] Operator recover-and-requeue for failure-blocked tasks
- [x] Operator recovery for agents left in `error`

## Still To Do On `main`

### Product UX and design

- [ ] Information architecture simplification and a clearer product mental model
- [ ] Guided onboarding and first-run operator workflow
- [ ] Unified execution and incident workbenches instead of the current page sprawl
- [ ] Dark/light theme system, stronger visual hierarchy, and overall usability polish

### Scheduling and planning

- [ ] Broader scheduler-driven recovery and requeue policies
- [ ] More autonomous replanning beyond the current explicit scorer and manual replan queue

### Providers

- [ ] Broader external provider coverage beyond the current local CLI paths
- [ ] More complete provider runtime lifecycle coverage

### Resilience and recovery

- [ ] Broader automated restart and retry policies
- [ ] Broader DLQ and quarantine workflows beyond the current retry-exhaustion dead-letter path
- [ ] Broader failure-specific resolution flows beyond the current repeated-failure, recovery-linked, and quarantine incident actions
- [ ] Higher-level artifact retention and cleanup policy automation beyond the current browser, provenance, export, and incident-handling flows
- [ ] Broader self-healing and recovery orchestration

### Platform expansion

- [ ] Deeper brownfield onboarding and repo-derived execution planning
- [ ] Multi-project support beyond the current scoped read foundation
- [ ] Plugin and domain extension architecture
- [ ] Strong sandbox and isolation layers beyond the current live-provider guardrails

## Practical Summary

- [x] If the goal is a single-project local MAAS workspace with a human operator in the loop, the repo now covers most of the required surfaces.
- [x] The strongest areas today are board operations, recovery handling, failure memory, provider visibility, artifact inspection, and control-room tooling.
- [ ] The biggest remaining gaps are autonomous planning quality, broader provider/runtime coverage, stronger self-healing, and platform expansion beyond one greenfield project.

## Current Numbered Delivery Sequence

- [x] `#80` Provider runtime preflight and readiness checks
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

## Batch View

- [x] Batch 1: Core kernel and scaffold
- [ ] Batch 2: Goal/task engine is only partially complete
- [ ] Batch 3: Runtime lifecycle and adapters are only partially complete
- [x] Batch 4: Greenfield onboarding
- [ ] Batch 5: Supervisor, dashboard, and Kanban V1 are only partially complete
- [ ] Batch 6: Security and human steering are only partially complete
- [ ] Batch 7: Resilience and failure memory are only partially complete
- [ ] Batch 8: Brownfield onboarding has started, but deeper import and multi-project expansion are still early
