# MAAS Execution Workflow

## Purpose

MAAS now uses GitHub as the execution layer for active work. The docs stay intentionally thin:

- current truth: [README.md](../../README.md), [STATUS.md](STATUS.md), and this file
- history/reference: [00-master-roadmap.md](00-master-roadmap.md) plus the numbered implementation plans in this directory
- execution: GitHub issues, linked pull requests, and the [MAAS Delivery & Execution](https://github.com/orgs/neurion-ai/projects/4) project board

Do not create competing active roadmap, queue, or runbook docs when the board or issue should carry that state.

## GitHub Project Contract

Project:

- URL: <https://github.com/orgs/neurion-ai/projects/4>
- owner: `neurion-ai`
- repo: `neurion-ai/maas`

Use one GitHub issue per tracked task. When the work maps to a numbered roadmap item, include the roadmap identifier in the issue title, for example `Roadmap #229: Memory usefulness by item, not just by run`.

Project fields:

- `Queue`: `Now`, `Next`, `Background`, `Blocked`
- `Status`: `Todo`, `In Progress`, `Done`
- `Lane`: `Delivery`, `Planning`, `Review & Memory`, `Autonomy & Recovery`, `Observability`, `Brownfield`, `Workflow`
- `Priority`: `P0`, `P1`, `P2`
- `Size`: `S`, `M`, `L`
- `Code Review`: `Not Ready`, `Pending`, `Running`, `Passed`, `Changes Requested`
- `PR`: `Not Ready`, `Open`, `Merged`
- `Linked pull requests`: actual PR linkage

Board flow:

1. Create or refine the issue, then set `Queue`, `Lane`, `Priority`, `Size`, `Code Review = Not Ready`, and `PR = Not Ready`.
2. When implementation starts, set `Status = In Progress`.
3. When a PR opens, link the PR to the issue, set `PR = Open`, and set `Code Review = Pending`.
4. While review or verification is running, set `Code Review = Running`, then move it to `Passed` or `Changes Requested`.
5. When the PR merges, set `PR = Merged` and `Status = Done`.

MAAS now also repairs stale merged-state cards during reconciliation for this repo's own execution board. If a tracked issue is already closed by a merged PR, the reconcile path refreshes the project item to `PR = Merged` and `Code Review = Passed`.

## Lane Guidance

Use these lane defaults unless the issue clearly fits better elsewhere:

- `Delivery`: delivery execution, PR sync, verification gates, handoff posture
- `Planning`: goals, issue synthesis, explainability, critical path, planning truth
- `Review & Memory`: review packets, approval UX, memory usefulness, retrieval quality
- `Autonomy & Recovery`: autopilot governance, no-progress diagnosis, self-healing, recovery policy
- `Observability`: runs, traces, live posture, system visibility
- `Brownfield`: repo-grounding, onboarding depth, existing-code understanding
- `Workflow`: docs contract, project board, templates, operator workflow plumbing

## Initial Roadmap Inventory

The first GitHub-project-backed roadmap inventory after `#224` should preserve these identifiers:

- `#225` GitHub delivery execution and PR sync
- `#226` Goal-to-issue explainability and critical path view
- `#227` No-progress diagnosis with one-click remediation
- `#228` Review packets v4 and bulk decision UX
- `#229` Memory usefulness by item, not just by run
- `#230` Delivery verification gates
- `#231` Live run observability v2
- `#232` Autopilot governance v2
- `#233` Self-healing and repeated-failure suppression v3
- `#234` Brownfield depth pass

Track queue/status changes on the GitHub Project, not in this document.

## Project Views

GitHub CLI and API support field creation and item mutation cleanly, but the available GraphQL mutations in this environment do not expose `ProjectV2View` create or update operations. Saved-view setup therefore remains a manual GitHub UI step.

Create these views manually if they are not already present:

1. `Planning`: group by `Queue`
2. `Execution`: group by `Status`
3. `PR`: group by `PR`
4. `Code Review`: group by `Code Review`

Recommended UI steps:

1. Open <https://github.com/orgs/neurion-ai/projects/4>.
2. Rename the default `View 1` to `Planning`.
3. Switch `Planning` to `Board` layout and set `Group by -> Queue`.
4. Create a new `Board` view named `Execution` and set `Group by -> Status`.
5. Create a new `Board` view named `PR` and set `Group by -> PR`.
6. Create a new `Board` view named `Code Review` and set `Group by -> Code Review`.
7. In each view, keep `Lane`, `Priority`, `Size`, and linked PR details visible so issue posture stays readable without opening every card.

## Repo Update Rules

- update [README.md](../../README.md) when the product framing changes
- update [STATUS.md](STATUS.md) when the current truth or board contract changes
- update this file when the GitHub workflow contract changes
- update a numbered implementation doc only when preserving historical implementation detail is useful
- do not create new active-plan docs when a GitHub issue or project item is the right source of truth
