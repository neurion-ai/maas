# Batch 7: Resilience and Failure Memory

## Status On `main`

- [ ] Batch 7 is only partially shipped on `main`.

## Shipped On `main`

- [x] Stale session detection
- [x] Restart and timeout handling for stale sessions
- [x] Structured failure memory retrieval
- [x] Board and alert visibility for unhealthy work
- [x] Failed sessions and timed-out sessions write into `failure_log`
- [x] The supervisor raises a critical alert when the same task accumulates repeated failures
- [x] Board cards, overview, live snapshot, and a dedicated failures API expose failure-memory state
- [x] Failed and timed-out session artifacts are isolated under `.maas/quarantine/`
- [x] Quarantine details are visible in failure reads and overview failure surfaces
- [x] Timed-out sessions can auto-retry under project recovery policy
- [x] Failed sessions can auto-retry under project recovery policy
- [x] A first-class quarantine queue exposes open, restored, and dismissed incidents
- [x] Operators can resolve repeated-failure incidents from the Alerts view without changing task state
- [x] Operators can recover failure-blocked tasks
- [x] Operators can recover-and-requeue failure-blocked tasks
- [x] Operators can restore, dismiss, reopen, or restore-and-requeue quarantine-queue incidents
- [x] Recent failure and overview surfaces expose direct failure operator actions for recover, restore, dismiss, reopen, and repeated-failure resolution
- [x] Operators can recover agents left in `error`

## Still To Do On `main`

- [ ] Broader automated restart and retry policies
- [ ] Broader DLQ and quarantine workflows
- [ ] Broader automated recovery orchestration

## Non-Goals

- advanced semantic hallucination detection
- full compensation workflows

## Acceptance Checklist

- [x] Stale sessions move to timeout and produce an alert
- [x] Repeated failed work can be surfaced for human review
- [x] Quarantined artifacts are isolated from normal flow
- [x] Failed sessions create failure-memory records and block the affected task for follow-up
- [x] Operators can inspect quarantine details through failure reads
