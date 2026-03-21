# MAAS Codex MVP Autonomy-Scale Plan

Status: implemented on `codex/codex-mvp-autonomy-scale`

## Goal

Take the current Codex MVP from "a workable operator shell" to "a system an operator can trust under real autonomous load."

This batch is about reducing guesswork:

- make `run` a first-class object
- make interruption and recovery more truthful
- reduce frontend-derived heuristics
- keep project lifecycle simple enough for repeated real testing

## Sequence

- [x] `#188` First-class run page and replay foundation
  - add a canonical run index/read model
  - add a dedicated `Runs` surface in the React app
  - wire stable navigation into run detail from `Work`, `Agents`, and `System`
  - expose run-scoped output, logs, activity, artifacts, and next-step guidance

- [x] `#189` Safe interruption and drain/resume surface
  - add explicit run cancel from the run surface
  - keep launch posture controls visible on the run surface
  - make stale-run diagnosis and operator next-step clearer

- [x] `#190` Exception-first `Issues` v2
  - move issue queue grouping and batch-review eligibility into backend read models
  - stop duplicating policy heuristics in the browser

- [x] `#191` Memory and retrieval foundation
  - search beyond loaded board rows
  - make prior outputs, checks, incidents, and history retrievable

- [x] `#192` Policy-driven autonomy v2
  - strengthen auto-advance and auto-review reasoning
  - surface why a task was or was not auto-approved

- [x] `#193` Project lifecycle simplification
  - simplify fresh-start testing further
  - add safer reset/clone semantics where justified

- [x] `#194` Stuck-run and stale-agent diagnostics
  - move more liveness diagnosis into backend truth instead of page heuristics

- [x] `#195` Multi-project supervision pass
  - give the operator a better cross-project execution and exception view

- [x] `#196` Notifications and async operator loop
  - reduce the need to stare at the UI continuously

## What Landed So Far

The first slice of this batch adds a real `Runs` page backed by canonical session data instead of provider-queue rows.

That includes:

- canonical run index API
- dedicated `Runs` tab in the real app shell
- shared run detail card reused across surfaces
- explicit stop/cancel from run detail
- replay entry point via recover-and-requeue for blocked linked issues
- backend-derived stale-run diagnostics and recommended next action
- direct navigation into runs from `Work`, `Agents`, and `System`

The next landed slice reduces frontend guesswork in the operator queue:

- canonical `/api/issues/index` read model for review and blocked work
- backend-derived operator buckets on issue cards
- backend-derived low-risk batch-review eligibility and reasons
- `Issues` page rendered from backend queue buckets instead of browser heuristics
- `Command` page reusing the same issue queue truth

The current branch also extends agent execution truth:

- agent-detail runs now expose execution mode, stale/live state, diagnostics, and recommended next action
- `Agents` surfaces that execution diagnosis directly instead of only showing raw heartbeat age

The current branch now also lands the first backend-owned system diagnostics pass:

- canonical `/api/system/diagnostics` read model for suspect runs, stale agents, and queue pressure
- `System` now renders that backend truth instead of recomputing stale diagnostics in the browser

The final slice of this batch makes the operator loop more autonomous at scale:

- retrieval search now spans issues, runs, artifacts, and events through `/api/retrieval/search`
- project lifecycle now supports clone-for-fresh-run without destructive reset
- portfolio and `Projects` now expose cross-project review queues, blocked failures, suspect runs, and stale agents
- the shell now includes an attention queue plus optional desktop notifications so the operator does not need to stare at the app continuously

## Why This Order

The run object is the strongest source of truth for what MAAS is actually doing.

Before expanding memory, notifications, or broader autonomy, the operator needs one place to answer:

- what is running
- what happened
- what looks stuck
- how do I stop it safely
- what should I do next
