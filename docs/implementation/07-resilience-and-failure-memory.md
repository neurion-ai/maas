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
- [x] Operators can recover failure-blocked tasks
- [x] Operators can recover agents left in `error`

## Still To Do On `main`

- [ ] Automated restart policies
- [ ] DLQ and quarantine workflows
- [ ] Broader automated recovery orchestration

## Non-Goals

- advanced semantic hallucination detection
- full compensation workflows

## Acceptance Checklist

- [x] Stale sessions move to timeout and produce an alert
- [x] Repeated failed work can be surfaced for human review
- [ ] Quarantined artifacts are isolated from normal flow
- [x] Failed sessions create failure-memory records and block the affected task for follow-up
