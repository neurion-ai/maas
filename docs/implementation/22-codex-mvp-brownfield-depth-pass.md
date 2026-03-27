# Codex MVP Brownfield Depth Pass

Status: implemented after roadmap batch `#227 + #231 + #232 + #233`, before final merge of roadmap `#234`.

## Goal

Deepen MAAS support for existing codebases without regressing the Codex-first control loop.

## Implemented Shape

- repo-grounded brownfield plan items now carry linked task and issue state, not just synthesized counts
- repo-plan active counts are computed from the actual current synthesized backlog instead of refresh deltas
- brownfield issue detail now exposes scoped paths, validation commands, matched imported runbook/workflow signals, matched codebase areas, and repo-plan linkage
- overview brownfield repo-plan reads now surface issue linkage and linked synthesized items for operator trust
- work/task inspection now shows matched repo-plan issue linkage instead of path-only matching

## Why This Batch Exists

Brownfield onboarding, repo scanning, and repo-grounded plan synthesis already existed. The missing depth was operator trust:

- which imported signal produced this task?
- which synthesized issue actually carries that plan item now?
- is the stored repo plan stale or still trustworthy?
- how does a brownfield issue map back to repo paths, validation commands, and imported operating model signals?

This batch closes those gaps in the read models and operator surfaces.

## Validation

- backend compile checks pass
- focused brownfield service validation passes for:
  - truthful repo-plan active counts after onboarding approval
  - linked synthesized repo-plan task state in overview reads
  - brownfield issue-detail grounding for repo-plan tasks
- frontend production build passes
