# Batch 7: Resilience and Failure Memory

## Scope

- stale session detection
- restart and timeout paths
- DLQ and quarantine groundwork
- structured failure memory retrieval
- board and alert visibility for unhealthy work

## Current Implementation Notes

- failed sessions and timed-out sessions now write into `failure_log`
- the supervisor raises a critical alert when the same task accumulates repeated failures
- board cards, overview, live snapshot, and a dedicated failures API now expose failure-memory state
- restart policies, DLQ handling, and automated recovery remain ahead of the current implementation

## Non-Goals

- advanced semantic hallucination detection
- full compensation workflows

## Acceptance Tests

- stale sessions move to timeout and produce an alert
- repeated failed work can be surfaced for human review
- quarantined artifacts are isolated from normal flow
- failed sessions create failure-memory records and block the affected task for follow-up
