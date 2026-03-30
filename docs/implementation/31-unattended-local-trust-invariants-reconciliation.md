# Unattended Local Trust v1: Invariants and Reconciliation

## Goal

Start the unattended-local-trust program by making MAAS state inspectable, repairable, and consistent across operator surfaces after restart, stale execution drift, or stale delivery linkage.

## Scope

This batch adds:

- project-truth inspection for run, task, and agent ownership drift
- safe reconciliation for stale in-progress tasks, stale agent ownership, and missing in-project agent assignments
- startup and autopilot-loop reconciliation before new autonomous work proceeds
- reconciliation-backed truth warnings in `System`, `Overview`, and `Theater`
- manual `System` action support for running reconciliation on demand
- linked GitHub PR state refresh during reconciliation for already-synced delivery items

## Operator Effect

MAAS is harder to leave in a silently inconsistent state:

- restart no longer leaves stale active ownership invisible
- `System` shows truth warnings and exposes a `Reconcile Truth` action
- `Theater` and overview payloads now surface reconciliation-backed drift counts
- autopilot runs against reconciled truth instead of blindly trusting stale linkage

## Validation

This batch is validated by:

- focused reconciliation regressions in `tests/test_reconciliation_api.py`
- Theater topology regression coverage in `tests/test_theater_api.py`
- system diagnostics regression coverage in `tests/test_codex_mvp_api.py`
- backend compile validation with `PYTHONPATH=src .venv/bin/python -m compileall src/maas`
- frontend build validation with `cd web && npm run build`

## Notes

This batch does not yet automate GitHub project-field cleanup after merge or failure. That board-truth automation remains part of the later unattended-trust stop-state batch.

Reconciliation intentionally repairs only the safe, low-ambiguity cases. Duplicate active runs or duplicate active sessions still surface as warnings that require explicit operator judgment.
