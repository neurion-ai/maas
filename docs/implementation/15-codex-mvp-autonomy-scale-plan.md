# MAAS Codex MVP Autonomy-Scale Plan

Status: in progress on `codex/codex-mvp-autonomy-scale`

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

- [ ] `#190` Exception-first `Issues` v2
  - move issue queue grouping and batch-review eligibility into backend read models
  - stop duplicating policy heuristics in the browser

- [ ] `#191` Memory and retrieval foundation
  - search beyond loaded board rows
  - make prior outputs, checks, incidents, and history retrievable

- [ ] `#192` Policy-driven autonomy v2
  - strengthen auto-advance and auto-review reasoning
  - surface why a task was or was not auto-approved

- [ ] `#193` Project lifecycle simplification
  - simplify fresh-start testing further
  - add safer reset/clone semantics where justified

- [ ] `#194` Stuck-run and stale-agent diagnostics
  - move more liveness diagnosis into backend truth instead of page heuristics

- [ ] `#195` Multi-project supervision pass
  - give the operator a better cross-project execution and exception view

- [ ] `#196` Notifications and async operator loop
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

## Why This Order

The run object is the strongest source of truth for what MAAS is actually doing.

Before expanding memory, notifications, or broader autonomy, the operator needs one place to answer:

- what is running
- what happened
- what looks stuck
- how do I stop it safely
- what should I do next
