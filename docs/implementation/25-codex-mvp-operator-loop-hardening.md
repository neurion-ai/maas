# Codex MVP Operator Loop Hardening

Status: implemented as follow-on GitHub Project batch issue `#112`.

## Goal

Reduce ambiguity between the operator inbox, Command, review, recovery, and notification delivery so operators can see one coherent attention queue and the safest next action.

## Implemented Shape

- operator inbox items now carry explicit operator actions instead of only navigation targets
- notification delivery failures now surface retry actions directly in the shared operator loop and route to `Command` instead of hiding only in `Portfolio`
- autopilot posture now explains blocking or gating causes from the current governance gate and exposes the first actionable resume or retry step
- brownfield onboarding conflicts in the operator loop now normalize review state from the actual review task instead of trusting stale config alone
- Command now renders shared control-loop actions and a notification recovery section from the same operator workflow payload used by the top-level attention inbox

## Why This Batch Exists

The earlier control-loop work exposed review pressure, stale runs, and notification failures, but the operator experience still had three gaps:

- the shared inbox could tell you that something was wrong without exposing the action that would actually clear it
- notification delivery recovery lived mostly in `Portfolio`, which made the main project-scoped loop in `Command` incomplete
- autopilot posture still defaulted to broad labels like "constrained" or "waiting" even when there was a more precise stop condition and a clear operator fix

This batch closes those gaps by turning the shared operator workflow into a genuinely actionable read model.

## Validation

- backend compile checks pass
- frontend production build passes
- targeted governance regression tests pass
- direct service-level validation passes for:
  - autopilot posture exposing resume actions for paused or zero-capacity projects
  - notification failure items surfacing retry-now and process-next actions in the operator loop
  - brownfield review conflicts disappearing when the review task is already approved even if config state is stale

## Notes

- focused FastAPI `TestClient` runs in this shell wrapper remained unreliable as a primary validation signal, so the batch was validated through direct service-level checks plus compile/build coverage
