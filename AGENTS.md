# AGENTS.md - MAAS Repository Instructions

## Project Context

MAAS is a Codex-first control plane for supervising autonomous work.

Core objects:

- `Goal`
- `Issue`
- `Run`
- `Agent`
- `Event`
- `Incident`

Main operator surfaces:

- `Command`
- `Work`
- `Issues`
- `Agents`
- `Runs`
- `System`
- `Projects`

## Docs Contract

Use a strict split between current truth, execution, and history:

- current truth: [README.md](README.md), [docs/implementation/STATUS.md](docs/implementation/STATUS.md), and [docs/implementation/WORKFLOW.md](docs/implementation/WORKFLOW.md)
- execution layer: GitHub issues, linked PRs, and the [MAAS Delivery & Execution](https://github.com/orgs/neurion-ai/projects/4) project
- history/reference: [docs/implementation/00-master-roadmap.md](docs/implementation/00-master-roadmap.md) and the numbered implementation docs

Rules:

- do not create competing active roadmap, queue, or runbook docs
- do not treat the numbered implementation docs as the live execution queue
- keep roadmap identifiers in issue titles when work maps to numbered items

## Project Board Contract

Expected project fields:

- `Queue`
- `Status`
- `Lane`
- `Priority`
- `Size`
- `Code Review`
- `Linked pull requests`
- `PR`

Board flow:

1. Issue created or refined: set `Queue`, `Lane`, `Priority`, `Size`, `Code Review = Not Ready`, `PR = Not Ready`
2. Work starts: set `Status = In Progress`
3. PR opens: link the PR, set `PR = Open`, set `Code Review = Pending`
4. Review or validation runs: set `Code Review = Running`, then `Passed` or `Changes Requested`
5. Merge: set `PR = Merged`, set `Status = Done`

## Working Rules

- read the current-truth docs before substantial roadmap or workflow changes
- use one GitHub issue per tracked task
- open a PR for repo behavior changes
- run delegated review for non-trivial PRs when your runtime supports it
- verify claims against actual files, command output, tests, or API responses before concluding
