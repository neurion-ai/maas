# MAAS

MAAS is a Codex-first control plane for supervising autonomous work.

It exists for the gap between “an agent can do work” and “an operator can safely trust an always-on system.” MAAS turns goals into issue inventories, runs Codex inside a governed execution loop, keeps review and recovery explicit, promotes reusable memory, and makes the entire control flow observable through runs, logs, traces, and incidents.

## What It Is

MAAS is not a generic dashboard and not a thin Codex wrapper. The current product direction is:

- `Codex` as the MVP execution runtime
- `Goal`, `Issue`, `Run`, `Agent`, `Event`, and `Incident` as the core control objects
- one human operator supervising execution instead of manually driving every task
- explicit review, recovery, memory, and delivery loops around autonomous work

## Why It Exists

Autonomous execution only becomes useful when the surrounding control loop is trustworthy. MAAS is designed to answer:

- what is the system doing right now?
- what needs operator judgment?
- why is progress blocked?
- what output did Codex actually produce?
- what memory, checks, and recovery rules changed the result?

## Core Objects

- `Goal`
- `Issue`
- `Run`
- `Agent`
- `Event`
- `Incident`

## Operator Surfaces

- `Command`: what needs judgment now
- `Theater`: live issue ownership, run posture, and branch lineage in one execution map
- `Work`: shared `List | Board` view of issues plus detail and execution history
- `Issues`: approvals, blocked work, failed runs, grouped review, and recovery actions
- `Agents`: active ownership, execution threads, spawned work, and health
- `Runs`: live and historical execution truth
- `System`: logs, metrics, queue posture, and machine health
- `Projects`: create, import, clone, archive, delete, and posture management

## What Makes It Different

- project-level autopilot instead of manual “run cycle” babysitting
- first-class run history, traces, and live execution truth
- explicit review policy and grouped review packets
- recovery playbooks instead of raw failure queues
- retrieval-backed project memory with promotion, attribution, and usefulness tracking
- delivery prep, GitHub draft PR sync, and verification-gated handoff

## Current Status

Today MAAS is a substantial local prototype built around:

- a Python/FastAPI backend with SQLite-backed state
- a React control plane for Command, Theater, Work, Issues, Agents, Runs, System, and Projects
- goal intake, issue synthesis, autopilot, review, recovery, retrieval, delivery-prep, and GitHub sync flows
- a GitHub Project-driven execution workflow for tracked issues, PRs, and review state
- live and simulated Codex execution paths with operator-visible logs, traces, and artifacts

The implementation history is long because the product has pivoted several times. The public direction above is the one that matters now; the detailed historical roadmap is still preserved below for implementation tracking.

## Quick Start

Install the backend and frontend dependencies, then launch the API and web app locally:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

cd web
npm install
cd ..

./scripts/maas-dev up
./scripts/maas-dev status
```

The managed local preview workflow:

- creates or reuses a demo workspace under `/tmp/maas-dev/workspace`
- imports this repo into that workspace as a brownfield project
- starts the API on `0.0.0.0:8000` and the web app on `0.0.0.0:5173`
- keeps pid files and logs under `/tmp/maas-dev`
- remembers the last selected workspace and port settings under `/tmp/maas-dev/dev-config.json`

Stop or restart the stack with:

```bash
./scripts/maas-dev down
./scripts/maas-dev restart
```

If `:8000` or `:5173` is already occupied on your machine, pass explicit overrides such as
`./scripts/maas-dev --web-port 5183 up` or `./scripts/maas-dev --api-port 8001 --web-port 5183 up`.
`status`, `restart`, and `down` reuse the last selected settings from `/tmp/maas-dev/dev-config.json`.
If you want localhost-only binding instead of LAN exposure, pass `--api-host 127.0.0.1 --web-host 127.0.0.1`.

You can still bootstrap and run MAAS manually from the CLI when needed:

```bash
PYTHONPATH=src python3 -m maas init --project-root .
PYTHONPATH=src python3 -m maas db migrate --project-root .
PYTHONPATH=src python3 -m maas api --project-root .
cd web && npm run dev
```

## Product Direction

Relevant design and roadmap documents:

- [Autonomous Organization Pivot](docs/implementation/09-autonomous-organization-pivot.md)
- [UI Reset](docs/implementation/10-ui-reset.md)
- [Codex MVP Shape](docs/implementation/11-codex-mvp-shape.md)
- [Codex MVP Integration Plan](docs/implementation/12-codex-mvp-integration-plan.md)
- [Codex MVP Hardening Plan](docs/implementation/13-codex-mvp-hardening-plan.md)
- [Codex MVP Next Batch Plan](docs/implementation/14-codex-mvp-next-batch-plan.md)
- [Codex MVP Autonomy-Scale Plan](docs/implementation/15-codex-mvp-autonomy-scale-plan.md)
- [Codex MVP Autopilot and Memory Plan](docs/implementation/16-codex-mvp-autopilot-memory-plan.md)
- [Codex MVP Control-Loop Hardening Plan](docs/implementation/17-codex-mvp-control-loop-hardening-plan.md)
- [Codex MVP Doctor, Planning, and Delivery Loop Plan](docs/implementation/18-codex-mvp-doctor-delivery-loop-plan.md)
- [Codex MVP Delivery Execution and Verification Plan](docs/implementation/19-codex-mvp-delivery-execution-verification-plan.md)
- [Codex MVP Explainability, Review, and Memory Plan](docs/implementation/20-codex-mvp-explainability-review-memory-plan.md)
- [Codex MVP Control-Loop Governance and Observability Plan](docs/implementation/21-codex-mvp-control-loop-governance-observability-plan.md)
- [Codex MVP Brownfield Depth Pass](docs/implementation/22-codex-mvp-brownfield-depth-pass.md)
- [Codex MVP Brownfield Execution Leverage](docs/implementation/23-codex-mvp-brownfield-execution-leverage.md)
- [Codex MVP Brownfield Drift, Refresh, and Trust](docs/implementation/24-codex-mvp-brownfield-drift-refresh-trust.md)
- [Execution Theater Foundation](docs/implementation/26-execution-theater-foundation.md)
- [Execution Theater Field and Agent Motion](docs/implementation/27-execution-theater-field-agent-motion.md)
- [Execution Theater Branch, Worktree, and PR Lineage](docs/implementation/28-execution-theater-branch-worktree-pr-lineage.md)
- [Execution Theater Internal-Production Readiness](docs/implementation/29-execution-theater-internal-production-readiness.md)
- [Local Dev Lifecycle Scripts](docs/implementation/30-local-dev-lifecycle-scripts.md)

There is also a standalone product mockup for the current direction in [mockups/maas-codex-mvp/README.md](mockups/maas-codex-mvp/README.md).

## Execution Workflow

Active planning and execution now live in GitHub, not in the numbered implementation docs.

- execution layer: [MAAS Delivery & Execution](https://github.com/orgs/neurion-ai/projects/4)
- current-truth docs: [README.md](README.md), [docs/implementation/STATUS.md](docs/implementation/STATUS.md), and [docs/implementation/WORKFLOW.md](docs/implementation/WORKFLOW.md)
- history/reference docs: the numbered implementation docs under [docs/implementation](docs/implementation/)

Use one GitHub issue per tracked task or roadmap item, keep project fields truthful, and link the PR once code work starts.

## Roadmap and Implementation History

The rest of this README tracks shipped implementation and numbered delivery history as archive/reference.

## Implementation Snapshot

Legend:

- `[x]` completed in the current numbered delivery sequence
- `[ ]` not yet completed in the current numbered delivery sequence

Use the stacked-branch references below to see whether a completed item is already on `main` or only exists on stacked branches.

Historical stacked development chain above `main`:

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
- `#161` exists on `codex/codex-mvp-shell-integration`
- `#162` exists on `codex/codex-mvp-shell-integration`
- `#163` exists on `codex/codex-mvp-shell-integration`
- `#164` exists on `codex/codex-mvp-shell-integration`
- `#165` exists on `codex/codex-mvp-shell-integration`
- `#166` exists on `codex/codex-mvp-shell-integration`
- `#167` exists on `codex/codex-mvp-shell-integration`
- `#168` exists on `codex/codex-mvp-shell-integration`
- `#169` exists on `codex/codex-mvp-shell-integration`
- `#170` exists on `codex/codex-mvp-shell-integration`
- `#171` exists on `codex/codex-mvp-hardening`
- `#172` exists on `codex/codex-mvp-hardening`
- `#173` exists on `codex/codex-mvp-hardening`
- `#174` exists on `codex/codex-mvp-hardening`
- `#175` exists on `codex/codex-mvp-hardening`
- `#176` exists on `codex/codex-mvp-hardening`
- `#177` exists on `codex/codex-mvp-hardening`
- `#178` exists on `codex/codex-mvp-hardening`

The current operator-value and capability sequence in [docs/implementation/14-codex-mvp-next-batch-plan.md](docs/implementation/14-codex-mvp-next-batch-plan.md) is now implemented on `codex/codex-mvp-operator-scale`. It adds truthful queue posture, readiness-aware launch strategy, shared `Work`/`Issues` scopes, first-class run detail reads, stronger agent/system execution diagnostics, verification-driven auto-approval, and cleaner fresh-project lifecycle controls.

The current autonomy-scale sequence in [docs/implementation/15-codex-mvp-autonomy-scale-plan.md](docs/implementation/15-codex-mvp-autonomy-scale-plan.md) is now implemented on `codex/codex-mvp-autonomy-scale`. It adds first-class `Runs`, backend-owned exception grouping, retrieval across issues/runs/artifacts/events, clone-for-fresh-run project lifecycle, stronger stale-run diagnostics, cross-project supervision in `Projects`, and an async attention loop with optional desktop notifications.

The current autopilot-and-memory sequence in [docs/implementation/16-codex-mvp-autopilot-memory-plan.md](docs/implementation/16-codex-mvp-autopilot-memory-plan.md) is now implemented on `codex/codex-mvp-autopilot-memory`. It adds project templates, project-level autopilot, memory promotion and retrieval-backed Codex prompts, backend-owned batch review, and stronger execution-state truth across `Command`, `Issues`, `System`, and issue detail.

The current control-loop hardening sequence in [docs/implementation/17-codex-mvp-control-loop-hardening-plan.md](docs/implementation/17-codex-mvp-control-loop-hardening-plan.md) is now implemented on `codex/codex-mvp-control-loop-hardening`. It adds durable autopilot lease state, a backend-owned operator inbox, lifecycle-safe clone posture resets, grouped review packet truth, notification failure integration, and fresher execution-memory attribution.

The current doctor, planning, and delivery-loop sequence in [docs/implementation/18-codex-mvp-doctor-delivery-loop-plan.md](docs/implementation/18-codex-mvp-doctor-delivery-loop-plan.md) is now implemented on `codex/codex-mvp-doctor-delivery-loop`. It adds an environment doctor, first-class goal creation and synthesis, delivery candidate reads plus PR-draft preparation, stronger autopilot governance gates, goal-scoped review packets, and usefulness-aware execution memory.

The current product-modeling sequence on `codex/linear-vibekanban-cockpit` now covers the cockpit pivot (`#127-#136`), the Linear/Vibekanban-inspired workflow cleanup (`#137-#146`), and the clarified Cockpit/Board role split (`#147-#151`).

The current Codex-MVP integration sequence on `codex/codex-mvp-shell-integration` carries that product reset into the real app with a new shell, canonical issue identity, issue detail and agent detail read models, and integrated `Command` / `Work` / `Issues` / `Agents` / `System` surfaces.

The current hardening sequence on `codex/codex-mvp-hardening` makes the integrated MVP truthful in live use: explicit run-cycle vs launch posture controls, review-first issue detail, simulation/live warnings, project delete plus fresh workspace creation, and tighter lifecycle regressions.

### Current project state

- [x] MAAS is now a substantial single-project, greenfield, operator-supervised prototype.
- [x] The core loop exists end to end: bootstrap, board, supervisor, provider execution, failure handling, quarantine, recovery, and artifact inspection.
- [x] For that current prototype shape, the repo is roughly `85-90%` complete.
- [ ] For the broader roadmap vision, the repo is still materially incomplete.

### Shipped on `main`

- [x] Greenfield bootstrap with seeded goals, tasks, agents, alerts, and sessions
- [x] Board-first API and React control room
- [x] Ready-queue refresh, acceptance evaluation, and first-pass idle-agent allocation
- [x] Steering controls for review, reprioritize, reassign, pause/resume, and halt
- [x] Escalation queue for risky steering approvals
- [x] Failure-memory logging, quarantine visibility, repeated-failure alerts, incident-specific alert actions, and task recovery for failure-blocked work
- [x] Manual recover-and-requeue for failure-blocked tasks
- [x] Timed-out and failed-session auto-retry with tracked retry state
- [x] Explicit scheduler scoring, board-visible scheduler rationale, and adaptive replan guidance
- [x] Manual replanning queue plus dead-letter routing for retry-exhausted work
- [x] Quarantine queue workflow with restore, dismiss, reopen, and restore+requeue actions
- [x] Recovery for agents left in `error`
- [x] Real local Claude Code CLI integration behind explicit provider config
- [x] Real local OpenAI Codex CLI integration behind explicit provider config
- [x] Provider status visibility with effective mode, runtime controls, config warnings, preflight readiness, recent run history, manual run controls, mode switching, and editable settings
- [x] Artifact browser and artifact-state visibility in the control room
- [x] Artifact browser supports preview, guarded download, compare, lineage/provenance pivots, and task/session export bundles
- [x] Artifact browser operator actions for restore, restore-and-requeue, dismiss, and reopen on quarantined artifacts
- [x] Shared live transport with websocket, SSE, and polling fallback status in the control room shell

### Still to do on `main`

- [ ] Product UX simplification, clearer mental model, and stronger first-run guidance
- [ ] Visually strong dual light/dark theme and a real design system instead of the current admin-tool feel
- [ ] Broader automated restart, retry, backoff, and self-healing workflows beyond the current DLQ path
- [ ] Broader external provider coverage beyond the current local CLI paths
- [ ] Higher-level artifact retention policy automation beyond the current browser, provenance, and export flows
- [ ] Deeper brownfield onboarding and multi-project execution support
- [ ] Stronger sandboxing and isolation guarantees
- [ ] Project-aware background orchestration beyond the current multi-project read scope

### Current numbered delivery sequence

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

### Current stacked branch progress

- [x] `#81` is already shipped on `main`
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

The current numbered `#81-#126` sequence is fully implemented on the stacked branch chain above `main`.

### UX and product-design sequence now implemented on the stacked branch

- [x] `#107` Information architecture reset and navigation collapse:
  reduce the current top-level control-room sprawl to a smaller set of primary surfaces with clearer user-language labels and a stronger product mental model.
- [x] `#108` Design system and dual light/dark theme foundation:
  introduce semantic color, spacing, typography, and elevation tokens plus persistent light/dark modes so the UI no longer feels like an internal admin tool.
- [x] `#109` Home command center with recommended actions:
  replace the current overloaded overview posture with a “what needs attention / what should I do next” landing experience.
- [x] `#110` Guided onboarding and first-run experience:
  add create/import/setup flows that explain what MAAS is doing, what the project state means, and what the next safe step is.
- [x] `#111` Unified Work surface for board, plan, and task detail:
  merge board, goal tree, and repo-grounded planning into a single execution workspace with richer task detail and evidence drawers.
- [x] `#112` Unified Runs surface for agents, providers, verification, and outputs:
  stop splitting execution state across separate silos and present one coherent operator view of active work and produced evidence.
- [x] `#113` Unified Incidents surface for failures, alerts, recovery, and timeline:
  turn incident response into one guided workbench with clear playbooks instead of four separate mechanism-heavy pages.
- [x] `#114` Portfolio and project-management UX redesign:
  improve project switching, lifecycle actions, cross-project health, and multi-project supervision without burying the user in policy forms.
- [x] `#115` Command palette, contextual actions, empty states, and inline guidance:
  make advanced functionality discoverable without overwhelming the default UI.
- [x] `#116` Accessibility, responsiveness, and visual-polish pass:
  finish the redesign with mobile/tablet behavior, keyboard-first interactions, stronger hierarchy, and usability QA.

### Dense operator control-room sequence now implemented on the stacked branch

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
- [ ] `#127` Seraph-style cockpit shell pivot:
  replace the page-and-card shell with a fixed-height cockpit shell, compact top bar, internal scroll regions, and explicit workspace modes such as ops, focus, and review.
- [ ] `#128` Panel workspace and windowed composition:
  reorganize the default experience into persistent left-rail, center-workspace, and right-rail panels with panel-scoped overflow instead of stacked sections.
- [ ] `#129` Cockpit command bar and telemetry strip:
  collapse navigation, project switching, live transport state, run controls, and quick commands into one dense operator bar.
- [ ] `#130` Dense agent rail:
  rebuild agent visibility as a compact live rail with status, current work, recent meaningful events, and fast intervention hooks.
- [ ] `#131` Center kanban workspace rewrite:
  make the board the primary workspace with denser cards, fewer empty lanes, scoped backlog access, and better ops/focus/review modes.
- [ ] `#132` Right ops rail for incidents and ticker:
  merge the curated feed, approvals, alerts, and incident shortcuts into one compact ops rail instead of separate dashboard blocks.
- [ ] `#133` Inspector and evidence workspace:
  turn selected-task context into a true inspector with goal path, repo scope, verification, git diff, artifacts, and history in one persistent panel.
- [ ] `#134` Utility drawers for projects, providers, and settings:
  move lifecycle forms, provider settings, quotas, and policy editors out of the primary workspace into drawers and advanced utility windows.
- [ ] `#135` Cockpit typography and theme system:
  replace the current generic card styling with a denser mono-forward cockpit system inspired by Seraph’s shell without copying its game flavor.
- [ ] `#136` Remove legacy page surfaces and finish the cockpit interaction model:
  delete or demote the old dashboard/page paradigm so MAAS reads as one coherent cockpit instead of multiple competing UI systems.

### Extended numbered roadmap

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
- [x] `#106` Incident timeline and replay

## Quick Start

```bash
PYTHONPATH=src python3 -m maas init --project-root .
PYTHONPATH=src python3 -m maas db migrate --project-root .
PYTHONPATH=src python3 -m maas task ready --project-root . --refresh
PYTHONPATH=src python3 -m maas task allocate --project-root .
PYTHONPATH=src python3 -m maas supervisor --project-root . --once
PYTHONPATH=src python3 -m maas api --project-root .
```

The project bootstrap creates:

- `project.yaml`
- `.maas/`
- `.maas/state.db`
- `.maas/artifacts/`
- `.maas/logs/`
- `.maas/quarantine/`

## Core API

- `GET /api/health`
- `GET /api/board`
- `GET /api/goals`
- `GET /api/agents`
- `GET /api/activity`
- `GET /api/alerts`
- `GET /api/escalations`
- `GET /api/failures`
- `GET /api/artifacts`
- `GET /api/artifacts/export`
- `GET /api/quarantine`
- `GET /api/live`
- `WS /api/live/ws`
- `GET /api/overview`
- `GET /api/goals/tree`
- `GET /api/providers`
- `GET /api/tasks/ready`
- `GET /api/tasks/{task_id}/capabilities`
- `POST /api/escalations/request`
- `POST /api/escalations/{escalation_id}/actions/approve`
- `POST /api/escalations/{escalation_id}/actions/reject`
- `POST /api/providers/{provider_id}/actions/run-task`
- `POST /api/tasks/actions/refresh-ready`
- `POST /api/tasks/actions/allocate-ready`
- `POST /api/tasks/{task_id}/actions/evaluate`
- `POST /api/tasks/{task_id}/actions/recover`
- `POST /api/tasks/{task_id}/actions/recover-and-requeue`
- `POST /api/tasks/{task_id}/actions/resolve-repeated-failures`
- `POST /api/quarantine/{queue_id}/actions/restore`
- `POST /api/quarantine/{queue_id}/actions/dismiss`
- `POST /api/agents/{agent_id}/actions/assign-next`
- `POST /api/agents/{agent_id}/actions/recover`
- `POST /api/supervisor/run`

The primary operational surface is the Kanban board returned by `/api/board`.

## Task Engine Commands

- `maas task ready --project-root . --refresh`
- `maas task allocate --project-root .`
- `maas task allocate --project-root . --agent-id <agent_id>`
- `maas task evaluate --project-root . --task-id <task_id>`
- `maas task recover --project-root . --task-id <task_id> --actor-id <agent_id>`
- `maas task recover-and-requeue --project-root . --task-id <task_id> --actor-id <agent_id>`
- `maas task resolve-repeated-failures --project-root . --task-id <task_id> --actor-id <agent_id>`
- `maas agent recover --project-root . --agent-id <agent_id> --actor-id <agent_id>`
- `maas supervisor --project-root . --once`
- `maas failure list --project-root .`
- `maas quarantine list --project-root .`
- `maas quarantine restore --project-root . --queue-id <queue_id> --actor-id <agent_id>`
- `maas quarantine dismiss --project-root . --queue-id <queue_id> --actor-id <agent_id>`
- `maas escalation list --project-root .`
- `maas escalation request --project-root . --project-id <project_id> --actor-id <agent_id> --action-type halt_task|reassign_task|pause_agent|resume_agent --resource-type task|agent --resource-id <resource_id>`
- `maas escalation approve --project-root . --escalation-id <escalation_id> --actor-id <agent_id>`
- `maas escalation reject --project-root . --escalation-id <escalation_id> --actor-id <agent_id>`
- `maas worker --project-root . --provider-type python_script|claude_code|openai_codex ...`

These commands expose the current dependency-aware ready queue, allocator flow, acceptance-gate evaluation, supervisor orchestration pass, and escalation approval flow from the CLI.

## Security Notes

- board and alert actions are gated by role-baseline `board_actions` permissions from `project.yaml`
- task execution now uses task-scoped capability grants, so lifecycle writes are limited to the assigned agent and task
- board cards and the task capabilities API expose the currently active task grants
- risky task and agent interventions can now be routed through an escalation queue instead of being executed immediately
- failed and timed-out sessions are now recorded in failure memory and can raise repeated-failure alerts
- quarantined failure artifacts are isolated under `.maas/quarantine/` and surfaced through the failure-memory reads
- first-class quarantine queue reads and actions now track open, restored, and dismissed artifact incidents
- recent failure and overview surfaces expose direct operator actions for recovery, restore, dismiss, reopen, and repeated-failure resolution
- operators can return failure-blocked tasks to the planning queue without resuming the old execution context
- timed-out and failed sessions can auto-retry under project recovery policy with tracked retry state
- operators can recover timeout-stranded agents from `error` back to `idle` once no active session remains

## Provider Notes

- `python_script` is the reference local worker adapter
- `claude_code` supports both the simulated adapter and a real local `claude -p` path when enabled in `project.yaml`
- `openai_codex` supports both the simulated adapter and a real local `codex exec` path when enabled in `project.yaml`
- `/api/providers` and the Providers view expose configured mode, effective mode, config warnings, recent provider runs, safe manual run targets, mode switching, and editable runtime settings
- `/api/artifacts` and the Artifacts view expose artifact state, missing-file detection, quarantine metadata, and server-side filtering
- artifact detail now includes preview, guarded single-file download, task/session export bundles, same-task compare, same-session lineage, and dependency-linked provenance pivots
