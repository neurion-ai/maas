# Unattended Local Trust v1: Idempotent Side Effects and Retry Safety

## Goal

Make MAAS external-effect paths safe under retry, restart, and duplicate execution so unattended local runs do not create duplicate PRs, duplicate provider work, duplicate notifications, or falsely ready git workspaces.

## Scope

This batch adds:

- durable notification processing claims with lease-based duplicate suppression
- truthful notification operation-state metadata for queued, running, succeeded, retryable-failed, and terminal-failed deliveries
- provider-job duplicate suppression when the same task/provider pair is queued or processed more than once
- operation-state metadata on provider-job reads for queue, run, completion, and failure posture
- persisted git-workspace prepare state, attempt counts, last mode, and last error details
- safer git-workspace prepare behavior when the expected path already exists but is not a managed worktree
- delivery GitHub PR sync metadata that reports the latest external result and retry posture

## Operator Effect

MAAS is less likely to repeat side effects or hide partial-failure posture:

- processing a notification twice no longer redelivers a sent webhook
- `process next notification` skips actively claimed deliveries instead of racing them
- queueing the same provider task twice reuses the existing open job instead of creating duplicates
- processing an already completed provider job returns the existing result rather than erroring or replaying work
- git-workspace preparation now records whether a workspace was reused, attached to an existing branch, created fresh, or failed
- delivery sync reads now expose the latest external GitHub PR result in a uniform operation-state shape

## Validation

This batch is validated by:

- focused regressions in `tests/test_notifications_api.py`
- focused regressions in `tests/test_provider_jobs_api.py`
- focused regressions in `tests/test_git_workspaces_api.py`
- delivery sync metadata coverage in `tests/test_codex_mvp_api.py`
- backend compile validation with `PYTHONPATH=src .venv/bin/python -m compileall src/maas`
- direct service-level validation for notification claim skipping, provider duplicate suppression, workspace prepare-state reuse/failure, and delivery sync metadata
- frontend build validation with `cd web && npm run build`

## Notes

The FastAPI `TestClient` harness still hangs in this shell wrapper for parts of the API-path test suite, so this batch relies on direct service-level validation for the side-effect semantics themselves when the wrapper does not return.

This batch intentionally stops short of full cross-surface stop-state unification. Canonical operator stop reasons and project-board truth automation remain part of the later unattended-trust stop-state batch.
