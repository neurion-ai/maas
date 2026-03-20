# MAAS Ideal UI Mockup

This is a standalone UI-only mockup for a rebooted MAAS product surface.

It is intentionally:
- disconnected from the MAAS backend
- isolated from the existing `web/` frontend
- built with plain HTML/CSS/JS so it can evolve quickly without inheriting current frontend constraints

## Open it

Simplest:

```bash
open mockups/ideal-maas-ui/index.html
```

Or serve it locally:

```bash
cd mockups/ideal-maas-ui
python3 -m http.server 4310
```

Then open:

`http://127.0.0.1:4310/`

## Product Model In This Mockup

- `Board`: default operator workspace
- `Execution`: runtime readiness, queue, and recent runs
- `Incidents`: failure queue and playbook detail
- `Projects`: import flow and portfolio health

The mockup is intentionally dense, board-first, and inspector-driven, borrowing:
- the compact board/detail model from Linear
- the live-system supervision feel from Paperclip
- the single-workspace mindset of modern kanban tools
