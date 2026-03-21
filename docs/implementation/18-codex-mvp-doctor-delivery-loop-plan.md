# MAAS Codex MVP Doctor, Planning, and Delivery Loop Plan

Status: implemented on `codex/codex-mvp-doctor-delivery-loop`

## Goal

Take the Codex-first MAAS MVP from “the operator can supervise autonomous work” to “the operator can start safely, define a goal, synthesize work, deliver outputs, and leave autopilot on with clearer governance.”

This batch closes the product loop that was still missing after the control-loop hardening pass:

- environment and launch readiness
- goal intake and goal-to-issue synthesis
- delivery candidates and draft PR preparation
- stronger autopilot governance and no-progress diagnostics
- grouped review packets that scale better
- memory usefulness signals instead of memory as a static store

## Sequence

- [x] `#215` Environment doctor and live-launch readiness
  - add a project-scoped environment doctor read model
  - verify Codex CLI, auth, git/source-root posture, provider mode, goal presence, and GitHub readiness
  - expose one operator-facing summary: ready, warning, or blocked

- [x] `#216` Goal intake and planning surface
  - add first-class goal creation
  - expose active goals and their current synthesized/open issue counts
  - integrate doctor, goals, and delivery into `Command`

- [x] `#217` Goal-to-issue synthesis and refresh loop
  - synthesize deterministic issue sets from a goal
  - refresh/cancel stale synthesized tasks without splitting brain from existing tasks
  - wire dependency chains so generated issues explain the critical path

- [x] `#218` Deliverable surface for diffs, reports, and output bundles
  - add a delivery overview over review/done tasks
  - classify outputs into diff/report/bundle/artifact delivery candidates
  - expose recent delivery candidates in `Command`

- [x] `#219` GitHub delivery loop and PR-draft preparation
  - prepare PR-draft artifacts from delivery-ready tasks
  - show GitHub readiness and gh-compatible commands
  - surface delivery actions from issue detail and command-center delivery candidates

- [x] `#220` Autopilot governance: budgets, stop conditions, and schedule windows
  - extend autopilot policy with schedule windows and queue thresholds
  - stop or hold autopilot when doctor posture is blocked
  - expose governance-gate truth in autopilot status

- [x] `#221` No-progress diagnostics and explicit blocked reasons
  - use doctor and governance state to make “why nothing is happening” explicit
  - surface progress diagnostics and recommended actions in the doctor panel

- [x] `#222` Review packets v3 and grouped approval
  - scope grouped review packets by goal/review-state
  - feed packet truth into board, issue detail, and operator inbox paths
  - keep manual/batch/auto review reasons explicit

- [x] `#223` Memory feedback, decay, and usefulness scoring
  - record memory injection and run outcomes
  - score memory by usage, success ratio, recency, and freshness
  - expose usefulness in issue detail and retrieval ordering

- [x] `#224` Async supervision v3 and overdue decision posture
  - extend operator attention with grouped review packets and overdue review pressure
  - keep doctor/governance signals actionable from async supervision surfaces

## What Landed

This batch makes project start truthful:

- `/api/environment/doctor` now returns one backend-owned readiness read with checks, progress posture, and recommended actions
- `Command` and `Projects` surface that doctor instead of asking the operator to infer setup posture from several screens
- autopilot can now stop or refuse to continue when doctor posture is blocked

It also makes goals and delivery first-class:

- goals can be created and refreshed through backend APIs
- issue synthesis creates deterministic task inventories tied back to a goal
- delivery overview and PR-draft preparation turn completed/reviewed work into concrete deliverables

And it improves autonomy quality:

- grouped review packets are now scoped more intelligently
- memory is ranked by usefulness and success, not just similarity and recency
- issue detail and command surfaces can show why memory was likely useful and what delivery action is next

## Why This Order

The previous batches gave MAAS:

- durable autopilot
- one operator inbox
- runs, review, recovery, and memory attribution

The highest-value missing step was to stop dropping the operator into the middle of the loop.

This batch fixes the missing ends of the product:

- safe start
- goal definition
- task synthesis
- delivery output

That makes the system feel more like a complete autonomous worker instead of a supervised execution console.
