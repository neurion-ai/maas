# 21. Codex MVP Control-Loop Governance, Observability, and Recovery Plan

Status: implemented on branch after roadmap batch `#226 + #228 + #229`, before brownfield depth pass.

This batch covers roadmap items:
- `#227` No-progress diagnosis with one-click remediation
- `#231` Live run observability v2
- `#232` Autopilot governance v2
- `#233` Self-healing and repeated-failure suppression v3

## Intent

Strengthen MAAS as a supervising control plane instead of only a task board:
- explain why progress is stalled in typed, actionable terms
- expose richer live-run posture and cross-loop attention signals
- make autopilot governance legible instead of a single opaque block reason
- surface suppression state explicitly when automation is paused behind retries, circuit breakers, quarantine, or repeated failures

## Implemented shape

### 1. No-progress diagnosis with one-click remediation

Environment doctor progress now returns typed `operator_actions`, not only prose recommendations.

Covered one-click actions include:
- run next orchestrator cycle
- resume launches
- set launch capacity to `1` and resume
- enable autopilot
- recover and requeue blocked work
- move blocked work into replanning
- resolve repeated-failure incidents

The Command surface renders these directly from the doctor payload and from specific progress reasons.

### 2. Live run observability v2

Run list and run detail now carry a structured observability block:
- state
- attention level
- summary
- detail
- last activity timestamp
- last activity action
- activity count

System diagnostics now also report:
- live run summary
- suspect runs
- stale agents
- queue pressure
- cross-loop `attention_items`

### 3. Autopilot governance v2

Autopilot governance now exposes:
- policy thresholds for review queue, blocked queue, stale runs, repeated failures, and notification failures
- multi-signal governance state instead of only one reason/detail pair
- blocking vs non-blocking signals
- typed operator action hooks where the control loop can safely recommend a direct intervention

The old top-level `blocked` / `reason` / `detail` fields remain for compatibility, but the UI should prefer the richer `signals` array.

### 4. Suppression and repeated-failure suppression v3

System diagnostics now include a normalized suppression model spanning:
- retry backoff
- open circuit breakers
- quarantine-held work
- repeated-failure incidents

Each suppression item includes:
- suppression kind
- linked task context when available
- summary/detail
- since-when timestamp
- one operator action to clear or advance the hold safely

This keeps recovery pressure visible outside the dedicated Recovery page.

## Surface changes

Primary UI surfaces updated:
- `Command`
- `Runs`
- `System`

Primary service/read-model changes:
- `environment_doctor`
- `autopilot`
- `codex_mvp`
- `recovery_policy`
- shared typed `operator_actions`

## Validation focus

Validation for this batch should continue to emphasize:
- direct service-level tests for doctor, governance, diagnostics, and suppression read models
- Python compile checks
- frontend production build

FastAPI `TestClient` endpoint tests remain useful when stable in the runtime, but service-level assertions are the main regression guard for this batch.
