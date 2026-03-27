# MAAS Codex MVP Delivery Execution and Verification Plan

Status: implemented on `codex/github-delivery-execution-and-verification-gates`

## Goal

Take MAAS from "delivery candidates and PR-draft preparation exist" to "the operator can see whether delivery is actually safe, then create or update a real GitHub draft PR from the control plane."

This branch implements the first post-`#224` batch:

- `#225` GitHub delivery execution and PR sync
- `#230` Delivery verification gates

It also records the proposed split for the remaining `#225-#234` work:

1. `#225 + #230` GitHub delivery execution, PR sync, and delivery verification gates
2. `#226 + #228 + #229` Goal explainability, critical path, review packets v4, and memory usefulness by item
3. `#227 + #231 + #232 + #233` No-progress remediation, live run observability v2, autopilot governance v2, and self-healing / repeated-failure suppression v3
4. `#234` Brownfield depth pass

## Sequence

- [x] `#225` GitHub delivery execution and PR sync
  - extend delivery reads with GitHub PR state instead of draft-only posture
  - add a backend action that creates or updates a draft PR through `gh`
  - persist synced PR state back into MAAS so `Command` and issue detail stay truthful

- [x] `#230` Delivery verification gates
  - evaluate delivery posture from task state, artifacts, verification runs, and branch readiness
  - block GitHub sync when delivery evidence or verification is missing
  - keep draft preparation available even when the GitHub delivery gate is blocked

## What Landed

- `/api/delivery` now returns delivery-gate truth, prepared-draft state, and the latest synced GitHub PR state per candidate
- `/api/tasks/{task_id}/delivery` exposes the same delivery read model for issue detail and targeted UI refresh
- `/api/tasks/{task_id}/actions/sync-github-pr` now creates or updates a real draft PR through `gh`
- issue detail and `Command` now show delivery gate status, synced PR state, and separate actions for draft preparation vs GitHub sync

## Why This Order

The current product already had:

- goal intake and issue synthesis
- delivery candidates
- PR-draft artifact preparation

The missing step was execution truth. Without it, delivery still stopped at "here is a Markdown body you could use later."

This batch closes that gap while keeping safety explicit:

- show whether delivery is actually ready
- let the operator sync a draft PR directly
- record what MAAS synced so later decisions are grounded in state, not memory
