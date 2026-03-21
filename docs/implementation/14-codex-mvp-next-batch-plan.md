# MAAS Codex MVP Next Batch Plan

Status: implemented on `codex/codex-mvp-operator-scale`

## Goal

Take the current Codex MVP from "the shell and core loop basically work" to "an operator can run it at scale without getting lost, over-reviewing everything, or babysitting fragile execution."

The next batch should maximize three things:

- operator value
- real runtime capability
- simplicity of day-to-day use

The biggest remaining problem is no longer shell structure. It is the gap between:

- what the UI implies
- what the control loop actually does
- how much an operator still has to manually stitch together

## What Matters Most Now

The highest-value problems are:

1. `Work` and `Issues` still do not scale because there is no real retrieval layer
2. the run model is visible, but not yet a first-class controllable/replayable object
3. queue posture and detached execution still need stronger correctness semantics
4. too much operator review is still manual and unstructured
5. `Agents`, `System`, and `Projects` are useful, but they still feel secondary and fragmented rather than part of one operating model

## Next PR Sequence

- [x] `#179` Queue posture and detached-execution correctness
  - make `draining` real instead of treating it like `paused`
  - make detached worker dispatch lease-safe and capacity-safe
  - prevent duplicate dispatch and queue-state ambiguity

- [x] `#180` Live run liveness and safe cancellation
  - add explicit live-run stop/cancel controls
  - keep heartbeats truthful during long Codex CLI runs
  - normalize halt/cancel/session-end semantics around one task/run state machine

- [x] `#181` Provider strategy and readiness-aware auto-launch
  - replace hardcoded Codex auto-launch assumptions with project-level preferred runtime strategy
  - gate auto-launch on readiness and preflight posture
  - keep the operator model simple: `Run next cycle` should just do the right thing

- [x] `#182` Retrieval, search, filters, and saved scopes for `Work` and `Issues`
  - add real search/filtering for issue volume
  - let operators narrow by status, goal, agent, review state, blocked reason, and project
  - add saved scopes for recurring operator workflows

- [x] `#183` Exception-first `Issues` workflow and batch review
  - make `Issues` an intervention surface, not just a list split
  - group by reason and recommended action
  - add batch review/approval for low-risk repetitive cases

- [x] `#184` First-class run record and replay surface
  - build one canonical run detail/replay model
  - unify startup config, execution mode, activity phases, outputs, checks, and failure details
  - link to it from `Work`, `Agents`, and `System`

- [x] `#185` Agent execution truth and stuck-run diagnostics
  - make `Agents` show current execution thread, recent evidence, and stale/error state
  - improve `System` with queue age, run age, heartbeat lag, and stuck-run visibility
  - reduce duplicate “history feed” concepts

- [x] `#186` Verification-driven review policy and auto-advance
  - use checks/evidence/policy to auto-advance low-risk work out of manual review
  - reserve human review for meaningful exceptions
  - make the review queue smaller and more important

- [x] `#187` Projects shell unification and clean-start flow
  - bring `Projects` fully into the Codex MVP shell
  - simplify create/import/archive/delete/reset flows
  - make starting a fresh test project obvious and low-friction

## What This Batch Landed

- truthful queue posture with explicit `running`, `draining`, and `paused` launch behavior
- readiness-aware launch strategy with persisted preferred provider selection
- shared search, filters, and saved scopes across `Work` and `Issues`
- exception-first `Issues` workflow with low-risk batch approval
- first-class run detail reads reused from `Work`, `Agents`, and `System`
- stronger agent and system diagnostics for stale runs, heartbeat age, and selected run inspection
- verification-driven auto-approval policy with project-level controls
- cleaner project lifecycle controls, including fresh test workspaces and safer archive/delete behavior

## Recommended Order

1. `#179-#181`
   This fixes the execution loop itself so the machine behaves more truthfully and more autonomously.

2. `#182-#183`
   This makes the product usable once issue volume and review load increase.

3. `#184-#185`
   This makes the machine debuggable and trustworthy when things go wrong.

4. `#186-#187`
   This reduces operator burden and removes friction around clean starts and project lifecycle.

## What Not To Build In This Batch

- new top-level surfaces
- org-chart or agent-theater features
- broader provider-zoo UX
- more dashboard tiles or visual churn
- deeper domain expansion before the Codex control loop is truly reliable

## Residual Risks

This batch materially improves operator value, but it does not fully solve:

- detached-worker lease safety under heavier concurrency than the current tests cover
- richer run replay/phase reconstruction beyond the session-envelope detail model
- broader saved-scope ergonomics and operator presets
- more expressive project reset flows beyond create/archive/delete

## Validation Priorities

Every PR in this batch should bias toward:

- real operator-path tests
- clear runtime-state invariants
- regression coverage for queue/run/review transitions
- removal of split-brain read models
- UI truthfulness under live and simulated modes
