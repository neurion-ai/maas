# MAAS

MAAS is a board-first multi-agent operating system. This repository now contains:

- a Python core with SQLite-backed state
- a greenfield bootstrap flow
- a FastAPI API exposing Kanban board read models
- a lightweight supervisor/lifecycle foundation
- implementation specs for the planned roadmap

## Quick Start

```bash
PYTHONPATH=src python3 -m maas init --project-root .
PYTHONPATH=src python3 -m maas db migrate --project-root .
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

The primary operational surface is the Kanban board returned by `/api/board`.
