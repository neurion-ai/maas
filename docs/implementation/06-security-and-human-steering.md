# Batch 6: Security and Human Steering

## Scope

- role baselines from `project.yaml`
- task-scoped capability grants
- board-driven steering actions
- append-only audit trail for sensitive changes

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
