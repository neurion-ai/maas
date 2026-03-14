# Batch 7: Resilience and Failure Memory

## Scope

- stale session detection
- restart and timeout paths
- DLQ and quarantine groundwork
- structured failure memory retrieval
- board and alert visibility for unhealthy work

## Non-Goals

- advanced semantic hallucination detection
- full compensation workflows

## Acceptance Tests

- stale sessions move to timeout and produce an alert
- repeated failed work can be surfaced for human review
- quarantined artifacts are isolated from normal flow

