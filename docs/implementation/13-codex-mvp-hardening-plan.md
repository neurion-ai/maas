# MAAS Codex MVP Hardening Plan

## Goal

Take the integrated Codex MVP from "new shell working against real data" to "truthful, steerable, and debuggable during live use".

This batch fixes the problems that showed up under real operator testing:

- ambiguous `Run` / `Pause` / `Resume` semantics
- simulation and live Codex runs looking the same
- review panels surfacing metadata before evidence
- board lanes hiding the difference between planned, ready, and assigned work
- agents, projects, and lifecycle controls staying technically functional but operationally confusing

## Batch

- [x] `#171` Truthful run-state and control model
  - split one-shot cycle execution from launch posture
  - surface `Launches running / paused / draining` honestly
  - stop overloading one button with multiple meanings

- [x] `#172` Review-first issue detail
  - put decision summary, output, and checks above the fold
  - move actions after evidence instead of before it
  - add explicit simulation warning when the evidence came from `local_simulation`

- [x] `#173` Live run console and trace quality
  - keep live console for active runs
  - include execution mode/runtime details in issue-level run history
  - make completed traces readable without displacing review-critical evidence

- [x] `#174` Work flow clarity and board semantics
  - show `Planned`, `Ready`, `Assigned`, `In progress`, `Review`, and `Blocked` separately
  - stop hiding `assigned` work inside a generic `Todo` bucket

- [x] `#175` Agents usability pass
  - fix duplicated/overlapping agent identity rows
  - separate identity, status, current task, and heartbeat cleanly

- [x] `#176` Project lifecycle and clean-start UX
  - support true greenfield workspace creation without faking `source_root`
  - add project delete
  - explain archive restrictions before the user clicks

- [x] `#177` Simulation/live boundary hardening
  - show simulation-vs-live runtime posture truthfully in `System`
  - make simulated review evidence visibly distinct from real Codex output

- [x] `#178` End-to-end reliability and regression suite
  - add lifecycle and issue-detail regression coverage for the new behavior

## Landed On `codex/codex-mvp-hardening`

This branch adds:

- truthful `Run next cycle` plus separate launch posture controls in `Command` and `Work`
- review-first issue detail with artifact selection, checks list, simulation warning, and secondary trace placement
- issue/run read models that expose `execution_mode` and `external_runtime`
- more honest `System` runtime posture summaries
- greenfield workspace provisioning and project deletion
- archive disabled reasons in `Projects`
- tighter agent-row layout in `Agents`

## Validation

- `python3 -m py_compile src/maas/services/projects.py src/maas/services/codex_mvp.py src/maas/api.py src/maas/cli.py tests/test_projects_api.py tests/test_codex_mvp_api.py`
- `PYTHONPATH=src python3 -m unittest tests.test_projects_api tests.test_codex_mvp_api tests.test_api_board_actions tests.test_orchestrator_api`
- `cd web && npm run build`
- `git diff --check`
