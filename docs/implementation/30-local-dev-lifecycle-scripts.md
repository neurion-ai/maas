# Local Dev Lifecycle Scripts

## Goal

Add one repo-level workflow for starting, stopping, restarting, and checking MAAS locally without hand-running backend and frontend commands.

## Scope

This batch adds:

- `scripts/maas-dev` with `up`, `down`, `restart`, and `status`
- a managed MAAS workspace under `/tmp/maas-dev/workspace`
- automatic brownfield import of this repo into that managed workspace
- pid files and logs under `/tmp/maas-dev`
- persisted runtime settings under `/tmp/maas-dev/dev-config.json`
- a configurable Vite API proxy target so the wrapper owns the backend port cleanly

## Operator Effect

Local preview is now operational instead of ad hoc:

- one command starts the API and frontend
- the repo root stays free of generated `.maas` state
- `status` reports the workspace, URLs, pid state, and log locations
- `status`, `restart`, and `down` reuse the last selected ports and workspace settings
- `restart` and `down` work against the managed processes instead of requiring terminal cleanup

## Validation

This batch is validated by:

- running `scripts/maas-dev up`
- running `scripts/maas-dev status`
- running `scripts/maas-dev restart`
- running `scripts/maas-dev down`
- checking `GET /api/health` from the managed backend
- checking the frontend root on the configured web port

## Notes

The wrapper assumes backend dependencies are installed in `.venv` and frontend dependencies are installed in `web/node_modules`.

If the default ports are already busy, the operator can override them with `--api-port` and `--web-port`.
The wrapper binds on `0.0.0.0` by default for local-network demos; pass `--api-host 127.0.0.1 --web-host 127.0.0.1` for localhost-only use.
