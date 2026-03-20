# MAAS Autonomous Organization UI Mockup

This is a standalone UI-only mockup for the pivoted MAAS product direction.

It is intentionally:

- disconnected from the existing MAAS backend
- isolated from the current `web/` frontend
- focused on product shape, information architecture, and operator workflow

The mockup models MAAS as:

- the control plane for autonomous organizations
- compatible with external runtimes such as `Codex`, `Claude Code`, `OpenClaw`, `Hermes`, `Seraph`, and others
- centered on five primary surfaces:
  - `Command`
  - `Workstreams`
  - `Agents`
  - `Incidents`
  - `Memory`

## Open it

Directly:

```bash
open /Users/bigcube/Desktop/repos/maas/mockups/org-control-plane-ui/index.html
```

Or serve it locally:

```bash
cd /Users/bigcube/Desktop/repos/maas/mockups/org-control-plane-ui
python3 -m http.server 4311
```

Then open:

`http://127.0.0.1:4311/`

## What It Demonstrates

- `Command`: organization status, decision queue, workstream map, capability health
- `Workstreams`: compact execution board with sticky inspector
- `Agents`: team grouping, handoffs, runtime health, ownership
- `Incidents`: one operator inbox grouped by actionability
- `Memory`: objectives, plans, decisions, evidence, and canonical memory

## What It Intentionally Avoids

- provider-zoo primary navigation
- giant hero sections and dashboard tile farms
- chat-first UX
- action-heavy cards
- exposing backend internals as the main operator model

## Related Docs

- [README.md](/Users/bigcube/Desktop/repos/maas/README.md)
- [09-autonomous-organization-pivot.md](/Users/bigcube/Desktop/repos/maas/docs/implementation/09-autonomous-organization-pivot.md)
