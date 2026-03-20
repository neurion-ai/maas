# MAAS Codex MVP Integration Plan

## Goal

Move the standalone mockup in [mockups/maas-codex-mvp/README.md](/Users/bigcube/Desktop/repos/maas/mockups/maas-codex-mvp/README.md) into the real product without repeating the earlier mistake of redesigning the UI while keeping fragmented read models underneath it.

The correct migration seam is:

- keep the current React/Vite app foundation
- keep the current FastAPI backend and SQLite state
- replace fragmented page composition with new aggregate read models
- integrate the mockup surface by surface

## Core Integration Rules

1. `Work` is the center of gravity.
   - `List` and `Board` must be two views of the same issue dataset.

2. The frontend must stop composing whole old pages inside new pages.
   - new surfaces need their own data contracts and own layout logic

3. The MVP remains `Codex-only`.
   - runtime plurality stays out of the default UX

4. Synthetic mockup semantics must not leak into production.
   - no fake counts
   - no duplicated source of truth
   - no hand-maintained queue rows that drift from issue state

5. History, incidents, and agent state must all resolve back to the same issue and run model.

## Existing Reusable Seams

Frontend:

- [web/src/App.tsx](/Users/bigcube/Desktop/repos/maas/web/src/App.tsx)
- [web/src/lib/controlRoomApi.ts](/Users/bigcube/Desktop/repos/maas/web/src/lib/controlRoomApi.ts)
- [web/src/lib/useLivePulse.ts](/Users/bigcube/Desktop/repos/maas/web/src/lib/useLivePulse.ts)
- [web/src/types.ts](/Users/bigcube/Desktop/repos/maas/web/src/types.ts)
- [web/src/pages/WorkPage.tsx](/Users/bigcube/Desktop/repos/maas/web/src/pages/WorkPage.tsx)
- [web/src/components/TaskInspector.tsx](/Users/bigcube/Desktop/repos/maas/web/src/components/TaskInspector.tsx)

Backend:

- [src/maas/services/board.py](/Users/bigcube/Desktop/repos/maas/src/maas/services/board.py)
- [src/maas/services/dashboard.py](/Users/bigcube/Desktop/repos/maas/src/maas/services/dashboard.py)
- [src/maas/services/timeline.py](/Users/bigcube/Desktop/repos/maas/src/maas/services/timeline.py)
- [src/maas/services/provider_runtime.py](/Users/bigcube/Desktop/repos/maas/src/maas/services/provider_runtime.py)
- [src/maas/services/verification.py](/Users/bigcube/Desktop/repos/maas/src/maas/services/verification.py)
- [src/maas/api.py](/Users/bigcube/Desktop/repos/maas/src/maas/api.py)

These already expose most of the raw state we need, but not yet in the correct operator-facing shape.

## Main Gaps

### 1. Unified issue model is missing

Today the product has board cards, overview slices, failures, timeline events, verification runs, and artifacts, but not one canonical issue read model that joins:

- task
- goal
- assigned agents
- active runs
- issue history
- incidents
- latest outputs
- relationship data

### 2. Command is still fragmented

The mockup `Command` surface needs:

- approvals waiting
- blocked critical work
- active runs
- latest landed changes
- current pressure

Today this data exists across:

- overview
- failures
- alerts
- escalations
- provider queue
- timeline

but it is not exposed as one contract.

### 3. Agents view is too shallow

Current roster data is not enough for the intended UI. The real `Agents` surface needs:

- current issue ownership
- active run
- spawned subagents
- last meaningful action
- outputs/evidence
- health

### 4. System surface needs a machine contract

Logs, metrics, queues, run traces, and failure pressure exist in pieces. The UI needs one system-oriented read model instead of scraping several pages worth of data.

## Integration PR Sequence

- [x] `#161` Frontend shell and token migration
  - move the mockup visual system into the real React app
  - keep current routing/data intact
  - do not rewrite product logic yet

- [x] `#162` Canonical issue read model and API
  - add one backend contract for `Work`
  - derive both list and board from the same issue set
  - include relationship counts, latest run, latest evidence, and blocked reason

- [x] `#163` Real `Work` surface integration
  - replace the current `WorkPage` data wiring with the new issue read model
  - integrate `List | Board`
  - integrate the new right-side issue inspector

- [x] `#164` Command read model and page integration
  - aggregate approvals, blocked critical work, landed changes, and execution pressure
  - replace the current top-level dashboard composition with a dedicated command contract

- [x] `#165` Issues queue and resolved-history integration
  - make `Issues` derive from the canonical issue + incident model
  - remove hand-maintained or duplicated queue state in the UI
  - ensure resolved items drill down into the same issue detail model

- [x] `#166` Embedded Git-like event/history model
  - expose issue/run/event history through one normalized contract
  - reuse it across `Work`, `Issues`, `Agents`, and `System`
  - ensure every timeline entry resolves back to issue or run identity

- [x] `#167` Agent execution and execution-thread model
  - build a real agent page/read model from tasks, runs, activity, and issue ownership
  - stop showing decorative or synthetic agent trees

- [x] `#168` System surface integration
  - unify logs, queue pressure, traces, failure counts, and stale-run health
  - build one machine-level page instead of exposing several subsystem pages

- [x] `#169` Guided intake and first-run flow
  - integrate mockup-style first-run/operator loop into the real product
  - remove current confusion around what to click first and what `Run` means

- [x] `#170` Legacy-page removal and integration hardening
  - delete superseded pages and dead CSS
  - remove old aggregate-page wrappers that just embed legacy pages
  - finalize test coverage and regression safeguards

## Landed On `codex/codex-mvp-shell-integration`

The current branch now includes:

- a new Codex-MVP shell in the real React app with `Command`, `Work`, `Issues`, `Agents`, `System`, and `Projects`
- stable backend-derived issue identity across board, issue detail, command, and agent surfaces
- a dedicated issue-detail aggregate endpoint
- a dedicated agent-detail aggregate endpoint
- real `Work` list/board views with a shared right-side inspector
- `Command`, `Issues`, `Agents`, and `System` surfaces backed by real backend state instead of standalone-mockup data
- first-run/project routing that lands users in the new `Command` / `Work` flow instead of the old cockpit shell
- targeted API coverage for the new issue-detail and agent-detail models

## Verification Strategy

Every integration PR should carry:

- backend read-model tests
- API contract tests
- frontend rendering tests for empty, single-item, and large-pipeline states
- one scenario fixture per surface:
  - startup
  - working at scale
  - resolving pressure

Specific risks to test:

- list and board drifting from each other
- project filters breaking selected issue state
- relationship links selecting hidden issues incorrectly
- agent pages disagreeing with issue branch/run history
- timeline and incident feeds duplicating or omitting events
- mockup-only decorative counts leaking into production

## Subagent Review Notes

Frontend migration review:

- reuse the current React/Vite shell and data layer
- migrate shell first, then `Work`, then `Command` / `Issues`, then `Agents` / `System`
- delete legacy silo pages only after the new surfaces have fully absorbed their workflows

Key local QA findings:

- the standalone mockup still has duplicated operator-queue data outside the canonical work model
- synthetic relationship wiring is still brittle and order-dependent
- mockup headline counts are intentionally lively but not fully derived from the generated dataset

These are acceptable in the mockup, but must not survive integration.
