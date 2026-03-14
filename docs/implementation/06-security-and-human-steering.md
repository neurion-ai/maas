# Batch 6: Security and Human Steering

## Status On `main`

- [ ] Batch 6 is only partially shipped on `main`.

## Shipped On `main`

- [x] Role baselines from `project.yaml`
- [x] Task-scoped capability grants
- [x] Board-driven steering actions
- [x] Append-only audit trail for sensitive changes
- [x] Board and alert actions enforce the role-baseline `board_actions` permission
- [x] Denied attempts return a permission error and create audit entries
- [x] Lifecycle start, heartbeat, activity, artifact, and end-session writes enforce active task grants
- [x] Reassignment, halt, allocation, and bootstrap flows grant or revoke task capabilities as task ownership changes
- [x] Escalation queues exist for halt, reassign, pause, and resume requests
- [x] Escalation requests can be listed and resolved through API, CLI, and the control-room Escalations view

## Still To Do On `main`

- [ ] OS-user isolation
- [ ] microVM sandboxing
- [ ] External identity provider integration

## Steering Checklist

- [x] pause and resume
- [x] approve and reject review items
- [x] reprioritize
- [x] reassign
- [x] halt

## Acceptance Checklist

- [x] Forbidden action attempts are denied or escalated
- [x] Board-driven actions create audit entries
- [x] Board UI exposes steering controls for reprioritize, reassign, pause/resume, review, and halt
- [x] Lifecycle writes are denied when the assigned task capability grant is missing or revoked
- [x] Escalation approvals and rejections are permission-gated, audited, and visible in the queue read model
