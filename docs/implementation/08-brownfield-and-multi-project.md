# Batch 8: Brownfield and Multi-Project

## Status On `main`

- [ ] Batch 8 is partially started on `main` through brownfield repo detection, onboarding approval gating, imported workflow and repo-area backlog seeding, brownfield codebase mapping, multi-project read scoping, and first-pass runtime isolation hardening.

## Current Stacked Branch Progress

- [x] `#81` multi-project write path and project lifecycle is shipped on `main`
- [x] `#82` project-aware supervisor and background orchestration is implemented on `codex/project-aware-supervisor-orchestration`
- [x] `#83` brownfield file-backed planning and repo navigation is implemented on `codex/brownfield-file-backed-planning`
- [x] `#84` policy-driven self-healing and circuit breakers is implemented on `codex/recovery-circuit-breakers`
- [x] `#85` sandboxed provider runners per project is implemented on `codex/project-isolated-provider-runtime`
- [x] `#86` remote or queued provider execution is implemented on `codex/provider-job-queue`
- [x] `#87` brownfield rescan and drift detection is implemented on `codex/provider-job-queue`
- [x] `#88` file-linked task scopes and acceptance criteria is implemented on `codex/file-linked-task-scopes`
- [x] `#89` brownfield runbook and command catalog is implemented on `codex/brownfield-runbook-command-catalog`
- [x] `#90` portfolio view across projects is implemented on `codex/brownfield-runbook-command-catalog`
- [x] `#91` background orchestration daemon is implemented on `codex/brownfield-runbook-command-catalog`
- [ ] `#92` queue and worker capacity management is the next unfinished step

## Extended Numbered Roadmap

- [x] `#81` Multi-project write path and project lifecycle
- [x] `#82` Project-aware supervisor and background orchestration
- [x] `#83` Brownfield file-backed planning and repo navigation
- [x] `#84` Policy-driven self-healing and circuit breakers
- [x] `#85` Sandboxed provider runners per project
- [x] `#86` Remote or queued provider execution beyond local CLI paths
- [x] `#87` Brownfield rescan and drift detection
- [ ] `#88` File-linked task scopes and acceptance criteria
- [ ] `#89` Brownfield runbook and command catalog
- [ ] `#90` Portfolio view across projects
- [ ] `#91` Background orchestration daemon
- [ ] `#92` Queue and worker capacity management on top of the provider job queue
- [ ] `#93` Stronger runner sandbox envelopes beyond the current per-project runtime isolation
- [ ] `#94` Policy-driven self-healing v2
- [ ] `#95` Brownfield onboarding review v2
- [ ] `#96` Remote executor or worker pool
- [ ] `#97` Cross-project scheduler fairness and capacity policy
- [ ] `#98` Repo-grounded plan synthesis and refresh
- [ ] `#99` Verification runners and evidence capture
- [ ] `#100` Git-aware task workspaces and diff review
- [ ] `#101` Cross-project command center
- [ ] `#102` Queue and worker capacity controls
- [ ] `#103` Policy-driven approval and risk routing
- [ ] `#104` Cost, runtime, and quota controls
- [ ] `#105` Notifications and outbound integrations
- [ ] `#106` Incident timeline and replay

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
