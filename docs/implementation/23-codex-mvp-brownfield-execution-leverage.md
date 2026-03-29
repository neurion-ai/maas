# Codex MVP Brownfield Execution Leverage

Status: implemented after `#234` / brownfield depth pass as the first follow-on GitHub Project batch issue (`#111`).

## Goal

Turn brownfield repo grounding into something operators can run from, not just inspect.

## Implemented Shape

- repo-plan preview and stored repo-plan state now expose live execution metadata for each synthesized brownfield item
- verification-recipe items carry runnable command lists plus latest verification status and command
- repo-area plan items carry git-workspace readiness, branch/diff posture, and linked verification coverage
- Projects view now shows brownfield execution packs with direct actions to open the task, run verification, and prepare or refresh a git workspace
- Issues detail now shows the same brownfield execution posture for the current synthesized task and exposes direct verification or workspace actions when applicable

## Why This Batch Exists

`#234` made brownfield grounding trustworthy. The missing next step was execution leverage:

- can the imported verification recipe be run right now?
- does the scoped repo-area task already have a workspace?
- which repo-area issue is actually covered by this verification recipe?
- can an operator move from brownfield grounding to execution without manually stitching together Work, repo browsing, and git state?

This batch closes that gap by attaching live execution state directly to the brownfield repo-plan items that overview and issue-detail surfaces already read.

## Validation

- backend compile checks pass
- direct service-level validation passes for:
  - live repo-plan state carrying latest verification posture
  - live repo-plan state carrying git-workspace readiness
  - issue-detail brownfield grounding reflecting the same execution metadata
- frontend production build passes

## Notes

- focused `pytest` runs in this shell wrapper remained unreliable as a primary validation signal, so the batch was verified through direct service-level checks instead of claiming flaky API-path coverage
