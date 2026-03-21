# MAAS Codex MVP Autopilot and Memory Plan

Status: implemented on `codex/codex-mvp-autopilot-memory`

## Goal

Take the autonomy-scale Codex MVP from "operator can supervise it" to "operator can let it keep moving without constant manual nudges."

This batch is about reducing friction in the real loop:

- let projects run themselves continuously when policy allows
- make project creation and fresh testing less repetitive
- let approved work become reusable memory
- move review and execution-state truth out of page heuristics and into backend-owned reads

## Sequence

- [x] `#197` Autopilot execution mode and daemonized project loop
  - add project-level autopilot policy storage
  - keep enabled projects cycling in the background
  - expose live autopilot status, heartbeat, and last-cycle summary

- [x] `#198` Live Codex console and structured run timeline improvements
  - extend run detail with current step, phases, and memory context
  - keep run truth reusable across `Work`, `Runs`, `Agents`, and `System`

- [x] `#199` Recovery playbooks and one-click intervention groundwork
  - add backend-derived recovery playbooks to issue detail
  - make execution-state diagnosis explicit instead of leaving blocked/stale interpretation to the browser

- [x] `#200` Memory promotion and retrieval-backed execution context
  - add artifact-to-memory promotion
  - expose project memory reads and retrieval search hits
  - inject relevant memory into new Codex task prompts and log when that happens

- [x] `#201` Review burden reduction: grouped review and stronger auto-approval
  - move batch review into a backend-owned action
  - continue auto-approving low-risk review items before new launches

- [x] `#202` Fresh-start project templates and reset-adjacent lifecycle flows
  - add project templates to create/import flows
  - make greenfield scratch creation less manual

- [x] `#203` Better "why nothing is happening" diagnostics across `Command`, `Issues`, and `System`
  - expose canonical execution-state summaries
  - surface idle/stuck/draining reasons in operator-facing reads

- [x] `#204` Async operator notifications v2 and autopilot attention posture
  - expose autopilot notification posture and cycle state in `Command`
  - make the operator understand whether the project is actively self-driving or waiting for intervention

## What Landed

This branch adds a new always-on project loop:

- `/api/autopilot/status` shows project-level autopilot state
- `/api/projects/{project_id}/actions/update-autopilot` persists project-local autopilot policy
- enabled projects now have a background loop that can continue allocating, launching, and processing notifications

This branch also turns memory into something execution can use:

- `/api/artifacts/{artifact_id}/actions/promote-memory` promotes an output into durable project memory
- `/api/memory` exposes promoted memory with retrieval metadata
- retrieval-backed Codex prompts now include relevant approved memory automatically
- run detail now shows the memory context injected into a run

This branch reduces browser-owned heuristics:

- batch review is now a backend-owned issue action
- issue detail gets backend-derived recovery playbooks
- `System` renders backend execution-state truth instead of recomputing it locally

This branch also makes project startup more repeatable:

- project templates are listed from `/api/projects/templates`
- create/import flows can seed project defaults from template selection
- greenfield scratch creation no longer requires hand-building every field

## Why This Order

The current Codex MVP already has:

- command/work/issues/agents/system surfaces
- first-class runs
- retrieval search
- review policy and auto-approval primitives

The highest-value next step was to connect those pieces into a lower-touch operator loop.

That means:

- fewer manual cycles
- clearer truth about why the machine is idle or blocked
- reusable memory that improves future runs
- easier fresh-start testing

Without this batch, MAAS still felt like a system that could run, but not yet one that could keep going on its own.
