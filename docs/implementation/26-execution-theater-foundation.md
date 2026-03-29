# Execution Theater Foundation

## Goal

Add a new top-level `Theater` surface that lets an operator see the live execution topology of one project in one place:

- issue lanes that stay stable as work moves
- current agent ownership and run posture
- branch, worktree, and PR lineage beneath the issue field

This first batch is intentionally read-only and navigation-first. It should not become a second mutation-heavy control surface.

## Scope

This batch adds:

- a new backend read model at `/api/theater`
- a new top-level `Theater` route in the web app
- cross-surface focus routing into existing `Work`, `Issues`, `Agents`, and `Runs` pages
- a branch or worktree lineage pane derived from existing git-workspace and delivery truth

It does not yet add:

- animated agent motion beyond standard UI refresh
- commit-level graph rendering
- a dedicated socket protocol
- new operator mutations that bypass the existing control surfaces

## Read Model

`/api/theater` aggregates existing sources of truth:

- `board` for issue posture and priority
- `runs` for live execution state
- `agents` for ownership and heartbeat posture
- git workspaces for branch and worktree state
- delivery sync state for PR linkage
- overview for project and brownfield trust context

The payload is structured as:

- `project`
- `summary`
- `issues`
- `agents`
- `runs`
- `branches`
- `pull_requests`
- `links`
- `layout`

The frontend should consume those explicit links rather than reverse-engineering topology ad hoc.

## UI Shape

The `Theater` page is split into:

1. `Execution Field`
   A stable lane view for issues across:
   - `planned`
   - `ready`
   - `assigned`
   - `in_progress`
   - `review`
   - `blocked`
   - `delivery`
   - `done_recent`

2. `Lineage`
   A lower scrolling tree grouped by base branch, with active branches above historical ones.

3. `Focus`
   A side panel that keeps the currently selected issue, agent, run, and branch or PR in one place, then deep-links into the existing detailed pages when the operator needs to act.

## Validation

This batch is validated by:

- Python compile checks for the backend
- frontend production build
- a focused Theater service regression covering issue, run, branch, and PR topology

An API-path Theater test is also committed, but local execution of some FastAPI `TestClient` flows still remains unreliable in this shell wrapper, so the direct service regression remains the primary local signal.

## Follow-on Batches

The later Theater batches should layer on top of this foundation:

- execution-field motion and stronger cross-highlighting
- richer branch or worktree lineage behavior
- degraded states, performance caps, instrumentation, and broader internal-production hardening
