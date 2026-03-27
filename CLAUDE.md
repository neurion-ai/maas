# MAAS Project Notes

## Goal

MAAS is building a Codex-first control plane for supervising autonomous work.

## Current Contract

- current truth lives in [README.md](README.md), [docs/implementation/STATUS.md](docs/implementation/STATUS.md), and [docs/implementation/WORKFLOW.md](docs/implementation/WORKFLOW.md)
- active execution lives in GitHub issues and the [MAAS Delivery & Execution](https://github.com/orgs/neurion-ai/projects/4) project
- numbered implementation docs are historical/reference material, not the live queue

## Working Norms

- use one tracked GitHub issue per task
- preserve roadmap identifiers in issue titles when a task maps to a numbered roadmap item
- keep project fields truthful: `Queue`, `Status`, `Lane`, `Priority`, `Size`, `Code Review`, `PR`
- link PRs to issues once implementation starts
- for non-trivial changes, run review/delegated review and verify claims before merge

## Product Shape

Core objects:

- `Goal`
- `Issue`
- `Run`
- `Agent`
- `Event`
- `Incident`

Main surfaces:

- `Command`
- `Work`
- `Issues`
- `Agents`
- `Runs`
- `System`
- `Projects`
