# Batch 3: Runtime Lifecycle and Adapters

## Status On `main`

- [ ] Batch 3 is only partially shipped on `main`.

## Shipped On `main`

- [x] Lifecycle operations: `start_session`, `heartbeat`, `log_activity`, `produce_artifact`, `end_session`
- [x] CLI and API entrypoints for lifecycle
- [x] Provider registry for Claude Code, OpenAI Codex, and Python Script
- [x] Simulated worker path for local validation
- [x] Provider execution routed through concrete local adapters for `python_script`, `claude_code`, and `openai_codex`
- [x] Provider runs create provider-specific activity entries and artifacts while still using the shared lifecycle contract
- [x] Lifecycle starts validate `provider_type` against the provider registry

## Still To Do On `main`

- [ ] Live external provider APIs and CLI integrations

## Non-Goals

- live network calls to provider APIs
- advanced provider failover
- credential management

## Interface Checklist

- [x] Lifecycle operations are idempotent at the service level where feasible
- [x] Board state updates based on session and task transitions

## Acceptance Checklist

- [x] Starting a session marks the agent running
- [x] Heartbeats update task progress
- [x] Ending a completed session moves `in_progress` work to `review`
- [x] Simulated provider adapters can execute a task end-to-end and leave consistent session, artifact, and activity state behind
