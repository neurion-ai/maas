# Codex MVP Brownfield Drift, Refresh, and Trust

Status: implemented as follow-on GitHub Project batch issue `#113`.

## Goal

Keep brownfield repo-grounded plans trustworthy as imported repositories drift and refreshes supersede older synthesized guidance.

## Implemented Shape

- brownfield rescans now classify drift as `low`, `medium`, or `high` instead of treating every change as equally disruptive
- low-severity drift remains visible but no longer automatically reopens import review or stales the repo-grounded plan
- repo-plan state now exposes one shared trust summary with safe-to-execute posture, drift severity, and recommended next action
- repo-plan state and brownfield issue detail now expose lineage for superseded and historical synthesized tasks plus recent refresh history
- Overview, Work, Command, and issue detail now render consistent brownfield trust and stale-plan warnings from the same backend read model

## Why This Batch Exists

`#111` made brownfield grounding executable, but the control plane still had two trust gaps:

- all imported drift looked equally dangerous, even when it was only a small file-count change inside an existing area
- operators could see the current repo plan, but not enough lineage to explain which older synthesized guidance had been superseded by refreshes

This batch closes that gap by making drift severity explicit, preserving superseded-plan visibility, and surfacing the same trust posture everywhere operators act.

## Validation

- backend compile checks pass
- frontend production build passes
- direct service-level validation passes for:
  - low-severity drift staying executable without reopening brownfield review
  - material drift forcing stale-plan posture
  - refreshed repo-plan lineage surfacing superseded synthesized tasks in overview and issue detail

## Notes

- focused `pytest` runs in this shell wrapper remained unreliable as a primary validation signal, so the batch was validated through direct service-level checks plus compile/build coverage
