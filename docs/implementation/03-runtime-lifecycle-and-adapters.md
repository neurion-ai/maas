# Batch 3: Runtime Lifecycle and Adapters

## Scope

- lifecycle operations:
  - `start_session`
  - `heartbeat`
  - `log_activity`
  - `produce_artifact`
  - `end_session`
- CLI and API entrypoints for lifecycle
- provider registry for Claude Code, OpenAI Codex, and Python Script
- simulated worker path for local validation

## Current Implementation Notes

- provider execution now routes through concrete local adapters for `python_script`, `claude_code`, and `openai_codex`
- adapter runs create provider-specific activity entries and artifacts while still using the shared lifecycle contract
- lifecycle starts now validate `provider_type` against the provider registry
- live external provider APIs and CLI integrations are still ahead of the current implementation

## Non-Goals

- live network calls to provider APIs
- advanced provider failover
- credential management

## Interface Notes

- lifecycle operations are idempotent at the service level where feasible
- board state should update based on session and task transitions

## Acceptance Tests

- starting a session marks the agent running
- heartbeats update task progress
- ending a completed session moves `in_progress` work to `review`
- one task can be executed end-to-end by each simulated provider adapter and leave consistent session/artifact/activity state behind
