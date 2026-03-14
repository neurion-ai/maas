# MAAS

MAAS is a board-first multi-agent operating system. This repository now contains:

- a Python core with SQLite-backed state
- a greenfield bootstrap flow
- a FastAPI API exposing Kanban board read models
- a task scheduler surface with ready-queue refresh and acceptance evaluation
- a lightweight supervisor/lifecycle foundation
- implementation specs for the planned roadmap

## Quick Start

```bash
PYTHONPATH=src python3 -m maas init --project-root .
PYTHONPATH=src python3 -m maas db migrate --project-root .
PYTHONPATH=src python3 -m maas task ready --project-root . --refresh
PYTHONPATH=src python3 -m maas api --project-root .
```

The project bootstrap creates:

- `project.yaml`
- `.maas/`
- `.maas/state.db`
- `.maas/artifacts/`
- `.maas/logs/`
- `.maas/quarantine/`

## Core API

- `GET /api/health`
- `GET /api/board`
- `GET /api/goals`
- `GET /api/agents`
- `GET /api/activity`
- `GET /api/alerts`
- `GET /api/tasks/ready`
- `POST /api/tasks/actions/refresh-ready`
- `POST /api/tasks/{task_id}/actions/evaluate`

The primary operational surface is the Kanban board returned by `/api/board`.

## Task Engine Commands

- `maas task ready --project-root . --refresh`
- `maas task evaluate --project-root . --task-id <task_id>`

These commands expose the current dependency-aware ready queue and acceptance-gate evaluation flow from the CLI.
