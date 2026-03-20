# Autonomous-Organization Pivot

> Note: this document captures the broader long-range pivot thinking. The current near-term product direction is narrower and is documented in [11-codex-mvp-shape.md](/Users/bigcube/Desktop/repos/maas/docs/implementation/11-codex-mvp-shape.md).

## Thesis

MAAS should become the control plane for autonomous organizations.

It should not present itself primarily as a software-delivery dashboard, a provider admin console, or a chat wrapper around single-agent sessions. Its job is to let one human operator define objectives, supervise teams of agents, route work into the best available runtimes, approve key decisions, intervene on incidents, and preserve trusted organizational memory.

## Product Model

Keep the first-class ontology tight:

- `Organization`: the top-level operating boundary
- `Objective`: the current mission or operating target
- `Team`: a stable functional grouping of agents
- `Agent`: a runtime-backed unit of execution with ownership and accountability
- `Workstream`: the unit of coordinated work the operator supervises
- `Run`: an execution instance or work loop
- `Incident`: any failure, approval, policy issue, or blocked state requiring operator attention
- `Memory`: plans, decisions, evidence, and canonical knowledge

De-emphasize or demote these from the primary model:

- `Mission`
- `Initiative`
- `Decision` as a separate top-level navigation item
- raw provider/runtime objects
- low-level queue types

Those concepts can still exist in the data model, but they should not dominate the first product pass.

## What MAAS Owns

MAAS should own:

- objective decomposition and routing
- team and agent coordination
- a normalized runtime contract
- approval gates and policy enforcement
- incident handling and recovery posture
- memory, evidence, and auditability
- operator control over autonomy

External runtimes should own:

- task-level reasoning loops
- tool use and local execution
- code or artifact generation
- runtime-specific session mechanics

This lets MAAS work with `Codex`, `Claude Code`, `OpenClaw`, `Hermes`, `Seraph`, and other capable systems without becoming a thin compatibility matrix.

## Runtime Contract

MAAS should speak one runtime contract to all agent systems:

- capabilities
- permission posture
- heartbeat/progress events
- checkpoint/state semantics
- output/evidence format
- failure taxonomy
- interrupt/stop semantics
- approval-sensitive action hooks

The UI should expose operational state from this contract, not provider-specific adapter noise by default.

## Primary Surfaces

### 1. Command

Purpose:
- organization-level command center

Must show above the fold:
- one org status line
- decision queue
- active workstream map
- capability health by team/runtime cluster
- recent meaningful transitions

Primary CTA:
- `Review decision queue`

### 2. Workstreams

Purpose:
- execution flow and intervention

Must include:
- compact board
- persistent right-side inspector
- dense cards that summarize only what matters
- selection-first interaction model

### 3. Agents

Purpose:
- staffing, coordination, handoffs, and runtime health

Must show:
- grouping by status or team
- current ownership
- handoff queue
- unhealthy agents and overloaded teams

### 4. Incidents

Purpose:
- one operator inbox for all exceptions

Must group by actionability:
- act now
- needs approval
- needs diagnosis
- contained/watchlist

### 5. Memory

Purpose:
- trusted operational memory, not a document graveyard

Must separate:
- working memory
- canonical memory

Should emphasize:
- current objective
- active plan
- decisions in force
- newest evidence
- unresolved questions

## UX Rules

- The product should feel like a premium control plane, not a tile dashboard.
- The operator should answer "what needs my judgment now?" within seconds.
- Task/workstream cards should be summaries, not mini control panels.
- Runtime/provider details should live in secondary surfaces or drawers.
- The UI should feel alive, but not theatrical.
- The org metaphor should remain operational, not fictional.
- The product should default to safety and explainability, not raw flexibility.

## Anti-Patterns To Avoid

- duplicated main surfaces for the same concept
- provider-zoo primary navigation
- giant hero sections and metric farms
- agent personality theater
- raw logs as the default operator view
- blending planning, execution, onboarding, and incident response into one page
- exposing backend terminology like `supervisor`, `orchestrator`, `worker pass`, and queue internals as default UX

## Initial Reboot Sequence

- `#152` Product ontology reset
- `#153` Runtime contract normalization
- `#154` Command surface
- `#155` Workstreams surface
- `#156` Agents surface
- `#157` Incidents surface
- `#158` Memory surface
- `#159` Guided intake flow
- `#160` Policy and control-posture model

## Mockup

The standalone UI-only mockup for this pivot lives in:

- [mockups/org-control-plane-ui/README.md](/Users/bigcube/Desktop/repos/maas/mockups/org-control-plane-ui/README.md)
