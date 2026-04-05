Status: implemented as unattended-local-trust batch issue `#132`.

# Unattended Local Trust v1: Overnight Soak and Fault Injection

## What shipped

- persisted trust runs with cycle history, trust reports, and replayable incident snapshots
- deterministic fault injection for notification delivery, provider runtime, git workspace preparation, and GitHub delivery sync
- direct trust-run handling for forced review holds and restart-time stale-session reconciliation
- `System` diagnostics now expose the latest trust run, including applied faults, incident count, and recent cycle summaries
- a new `scripts/maas-trust-run` helper for long-running local soak execution outside the browser

## Why this batch exists

The previous unattended-trust batches made truth repair, retry safety, and stop states coherent. That still does not prove MAAS is safe to leave running. This batch turns the trust claim into evidence:

- use the real control loop
- inject deterministic failures into the real side-effect paths
- capture what happened as replayable incidents
- persist one trust report that `System` can surface directly

## Main implementation points

- `migrations/0018_trust_runs_and_fault_injection.sql`
  - adds `trust_runs`
  - adds `fault_injections`
  - adds `trust_run_incidents`
- `src/maas/services/fault_injection.py`
  - schedules, activates, consumes, and skips persisted faults
- `src/maas/services/trust_runs.py`
  - executes the soak loop
  - schedules the default fault plan
  - captures trust incidents and replay payloads
  - produces the persisted trust report
- runtime hooks:
  - `notifications.py` consumes `notification/deliver`
  - `provider_runtime.py` consumes `provider/runtime`
  - `git_workspaces.py` consumes `git_workspace/prepare`
  - `delivery.py` consumes `delivery/sync`
- `System`
  - exposes the latest trust run via `/api/system/diagnostics`
  - can launch a trust soak directly from the page

## Default soak profile

The current default profile is deterministic and cycle-based:

1. provider runtime failure
2. notification delivery failure
3. git workspace preparation failure
4. GitHub delivery sync failure
5. forced review hold
6. restart-time stale-session reconciliation

Longer runs can still use the same six-step profile with more sleep between cycles via `scripts/maas-trust-run`.

## Operator workflow

- quick local sample from the UI:
  - open `System`
  - run `Run Trust Soak`
- longer unattended run from the shell:

```bash
PYTHONPATH=src ./scripts/maas-trust-run --project-root /path/to/workspace --cycles 12 --sleep-seconds 60
```

The resulting trust report is persisted in the project database and will show up in `System` diagnostics on the next refresh.

## Residual gap after this batch

This batch records trust evidence, but it does not yet enforce an explicit unattended go/no-go gate. That remains the follow-on trust-closure batch:

- use the soak evidence to define hard blockers
- expose one eligibility signal for unattended operation
- refuse intentional unattended mode until the trust gate is green
