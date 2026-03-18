# Batch 8: Brownfield and Multi-Project

## Status On `main`

- [ ] Batch 8 is partially started on `main` through brownfield repo detection, onboarding approval gating, imported workflow and repo-area backlog seeding, brownfield codebase mapping, multi-project read scoping, and first-pass runtime isolation hardening.

## Current Stacked Branch Progress

- [x] `#81` multi-project write path and project lifecycle is shipped on `main`
- [x] `#82` project-aware supervisor and background orchestration is implemented on `codex/project-aware-supervisor-orchestration`
- [x] `#83` brownfield file-backed planning and repo navigation is implemented on `codex/brownfield-file-backed-planning`
- [x] `#84` policy-driven self-healing and circuit breakers is implemented on `codex/recovery-circuit-breakers`
- [x] `#85` sandboxed provider runners per project is implemented on `codex/project-isolated-provider-runtime`
- [ ] `#86` remote or queued provider execution is the next unfinished step

## Still To Do On `main`

- [ ] Deeper brownfield execution planning beyond the current codebase map and imported backlog
- [ ] Multi-project routing beyond the current read-surface foundation
- [ ] Dashboard and plugin extensions for cross-project operation
- [ ] Stronger runtime isolation for imported repos beyond the current live-provider guardrails

## Non-Goals

- replacing existing project workflows
- forcing a single domain model on imported repos

## Acceptance Checklist

- [x] Brownfield fixture produces a reviewable understanding artifact
- [x] Multi-project API routing isolates project data correctly
