Status: implemented as unattended-local-trust batch issue `#133`.

# Unattended Local Trust v1: Final Closure and Trust Gate

## Goal

Close the last gap between “we can run fault-injected trust soaks” and “MAAS can truthfully tell the operator whether this project is safe to leave unattended overnight right now.”

## What shipped

- `src/maas/services/trust_gate.py`
  - adds the unattended trust gate
  - derives eligibility from the latest persisted trust run, current truth warnings, autopilot posture, and launch posture
  - exposes explicit statuses:
    - `unverified`
    - `blocked`
    - `eligible`
    - `armed`
    - `armed_blocked`
  - blocks intentional unattended mode until the project is actually eligible
- `src/maas/services/trust_runs.py`
  - trust soak cycles now reconcile after each injected cycle
  - trust reports distinguish tolerated canonical stop-state holds from genuine unreconciled truth mismatches
  - a passing soak now means “the control loop stayed truthful after repair,” not merely “the cycle finished”
- `src/maas/api.py`
  - adds `POST /api/projects/{project_id}/actions/update-unattended-mode`
- `src/maas/services/codex_mvp.py`
  - System diagnostics now include `trust_gate`
- `web/src/pages/CodexSystemPage.tsx`
  - System now shows:
    - trust gate status
    - exact blockers
    - direct arm/disarm control
    - existing trust soak history underneath the gate
- `web/src/lib/controlRoomApi.ts`
  - adds project unattended-mode update support

## Why this matters

The previous batch could prove that MAAS survives deterministic injected failures and record replayable incidents, but it still left one practical question unanswered:

- “Can I leave this project unattended tonight?”

This batch makes that answer explicit, durable, and operator-visible.

## Trust gate rules

The project is only `eligible` when:

- the latest trust soak completed successfully
- the latest trust soak report is `passed`
- the soak covered at least the required cycle count
- the soak evidence is still fresh
- no duplicate side effects were recorded
- no unreconciled truth mismatches remain
- autopilot is enabled
- launch posture is `running`
- provider capacity is above zero

If the operator tries to arm unattended mode before those conditions hold, MAAS rejects the request and reports the blockers directly.

## Final closure behavior

- arming unattended mode first runs reconciliation
- reconciliation remains the canonical path for:
  - truth repair
  - delivery refresh
  - GitHub project truth sync
- the trust gate uses that repaired state rather than stale pre-reconcile drift

## Validation

- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_trust_gate_api.py -q`
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_trust_runs_api.py -q`
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_reconciliation_api.py -q -k "system_diagnostics_and_theater_surface_truth_warnings"`
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_codex_mvp_api.py -q -k "system_diagnostics_include_run_observability_and_suppression"`
- `cd web && npm run build`

## Outcome

With this batch, unattended-local-trust v1 is no longer just a collection of mechanisms. MAAS now exposes one explicit go/no-go signal for unattended overnight use and refuses intentional unattended mode until the trust prerequisites are green.
