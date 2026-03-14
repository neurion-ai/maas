# Batch 6: Security and Human Steering

## Scope

- role baselines from `project.yaml`
- task-scoped capability grants
- board-driven steering actions
- append-only audit trail for sensitive changes

## Current Implementation Notes

- board and alert actions now enforce the role-baseline `board_actions` permission
- denied attempts return a permission error and create audit entries
- task-scoped capability grants now exist for assigned execution work
- lifecycle start, heartbeat, activity, artifact, and end-session writes now enforce active task grants
- reassignment, halt, allocation, and bootstrap flows now grant or revoke task capabilities as task ownership changes
- escalation queues are still ahead of the current implementation

## Non-Goals

- OS-user isolation
- microVM sandboxing
- external identity provider integration

## Steering Actions

- pause/resume
- approve/reject review items
- reprioritize
- reassign
- halt

## Acceptance Tests

- forbidden action attempts are denied or escalated
- board-driven actions create audit entries
- board UI exposes steering controls for reprioritize, reassign, pause/resume, review, and halt
- lifecycle writes are denied when the assigned task capability grant is missing or revoked
