# MAAS Codex MVP Shape

## Thesis

The near-term MAAS product should not be a generic autonomous-organization shell and it should not be a provider marketplace.

For the MVP, MAAS should be:

- the control plane for `Codex`-driven autonomous work
- an operator product for steering issues, runs, agents, and incidents
- a system that makes autonomous execution observable, reviewable, and recoverable

This is deliberately narrower than the earlier autonomous-organization pitch.

## Product Model

Keep the first-class model small:

- `Goal`: why the work exists
- `Issue`: the unit of supervised work
- `Run`: one concrete execution attempt on an issue
- `Agent`: a Codex-backed worker or spawned subagent
- `Event`: a meaningful state change or execution milestone
- `Incident`: any failure, approval gate, blocked state, or recovery condition

Everything else should be secondary or advanced.

## Runtime Assumption

For the MVP:

- execution is `Codex-only`
- MAAS owns orchestration, review gates, history, logs, metrics, and recovery
- runtime/provider plurality is explicitly de-scoped from the default UX

That means the UI should not center:

- provider pickers
- runtime marketplaces
- adapter-specific admin surfaces

## Primary Surfaces

### 1. Command

Purpose:
- tell the operator what matters right now

Must show:
- approvals waiting
- blocked critical work
- active runs
- recently landed work
- current pressure and failure signals

Primary question:
- `What needs my judgment now?`

### 2. Work

Purpose:
- be the main operational surface

Must include:
- a shared `List | Board` view of the same issues
- search and filters
- a right-side detail pane
- active threads and linked runs
- blocked reason and recommended next action

Primary question:
- `What work exists and how is it moving?`

### 3. Issues

Purpose:
- hold exceptions and operator intervention

Must show:
- approvals
- blocked work
- failed runs
- repeated failures
- recovery recommendations
- resolved history for issues that recently landed or were cleared

Primary question:
- `Why is work not flowing?`

### 4. Agents

Purpose:
- show who is doing what right now

Must show:
- active issue ownership
- spawned subagents
- current run
- status (`running`, `blocked`, `waiting`, `idle`, `failed`)
- last meaningful action
- current outputs or evidence

Primary question:
- `Which agents or subagents are actually moving the work?`

### 5. System

Purpose:
- expose the machine and prove that it is healthy

Must show:
- logs
- metrics
- queue pressure
- stale runs
- failed runs
- agent health
- run traces
- Codex invocation and artifact visibility

Primary question:
- `Is the machine healthy, and if not, why not?`

## History Model

`History` should not be a top-level page in the MVP.

Instead, history should be embedded where it helps decisions:

- issue execution history inside `Work`
- issue and incident timelines inside `Issues`
- per-agent activity inside `Agents`
- raw traces and logs inside `System`

The history model should feel Git-like:

- issue created
- assigned
- subagent spawned
- branch or attempt opened
- output produced
- review requested
- blocked
- retried
- recovered
- accepted
- closed

## Relationship Model

Task relationships should not default to one giant graph.

Instead:

- `Work` cards show compact relationship signals:
  - dependency count
  - unlock count
  - active branch count
- issue detail shows a focused relationship map:
  - `Depends on`
  - `This issue`
  - `Unlocks`
- related work on the same goal appears as a secondary strip
- resolved work shows what landing it unlocked

This keeps relationship data readable at scale while still making dependencies and downstream impact obvious.

## UX Rules

- `Issues` and `Board` are two views of the same work, not separate products
- task cards summarize; detail panes explain
- no human-company theater or org-chart metaphors in the MVP
- no runtime marketplace UX in the MVP
- logs and metrics exist, but do not dominate the home surface
- every blocked issue must explain:
  - why it is blocked
  - whether operator action is required
  - what MAAS recommends next

## Anti-Patterns

Avoid:

- fake company hierarchy
- duplicate top-level surfaces for the same state
- agent personality theater
- raw event feeds as the main product
- giant dashboard tile farms
- making MAAS look like a generic PM tool with AI garnish
- making MAAS look like a Codex wrapper with no operator value

## Mockup

The current standalone mockup for this MVP direction lives in:

- [mockups/maas-codex-mvp/README.md](/Users/bigcube/Desktop/repos/maas/mockups/maas-codex-mvp/README.md)
