Status: implemented as unattended-local-trust batch issue `#131`.

# Unattended Local Trust v1: Stop States and Operator Truth

## What shipped

- one canonical stop-state payload shared across operator inbox items, issue detail, system diagnostics, and Theater attention
- issue detail now surfaces the same stop-state summary and next action used by the operator loop
- System now renders suspect runs, stale agents, and cross-loop attention using canonical stop-state reason keys and copy
- Theater now exposes the same top stop states instead of only topology and truth warnings
- reconciliation now also checks the MAAS GitHub Project and repairs stale merged-state cards for closed issues linked to merged PRs

## Why this batch exists

Retry safety and reconciliation are not enough for unattended trust if the operator wakes up to four different explanations of why work stopped. This batch makes the stop reason itself a first-class shared object and closes the stale-board gap that kept merged execution history out of sync with the GitHub Project.

## Main implementation notes

- `src/maas/services/stop_states.py` defines the canonical stop-state shape and mappings for review, recovery, stale-run, policy-conflict, and notification-failure conditions
- `src/maas/services/operator_inbox.py` now attaches stop-state payloads to raw inbox items and workflow items
- `src/maas/services/codex_mvp.py` now exposes stop-state payloads on suspect runs, stale agents, attention items, and issue detail
- `src/maas/services/theater.py` now adds a top-level attention section sourced from the same operator workflow stop-state payloads
- `src/maas/services/github_project_sync.py` adds GitHub Project inspection and synchronization for repo-owned execution issues
- `src/maas/services/reconciliation.py` now triggers project-board truth sync with cooldown and records the sync result in reconciliation output

## Validation

- `PYTHONPATH=src .venv/bin/python -m compileall src/maas tests/test_operator_inbox_api.py tests/test_reconciliation_api.py tests/test_theater_api.py tests/test_codex_mvp_api.py tests/test_github_project_sync.py`
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_github_project_sync.py -q`
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_reconciliation_api.py -q -k board_sync`
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_theater_api.py -q -k fetch_theater_service`
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_codex_mvp_api.py -q -k canonical_stop_state_for_blocked_recovery`
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_operator_inbox_api.py -q -k exposes_canonical_stop_states`
- `cd web && npm run build`
- `git diff --check`

## Follow-on

The next unattended-local-trust batches should assume stop states are now canonical and use them directly for soak reporting, trust gates, and replayable incident evidence rather than re-deriving local status copy.
