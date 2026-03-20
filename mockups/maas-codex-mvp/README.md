# MAAS Codex MVP Mockup

This is a standalone UI-only mockup for the corrected MAAS MVP direction.

It is intentionally:

- separate from the current `web/` frontend
- separate from the earlier failed mockups
- focused on `Codex-only` execution for the MVP
- built around the real MAAS operator loop instead of a fake company metaphor

## Product Shape

The mockup uses these primary surfaces:

- `Command`
- `Work`
- `Issues`
- `Agents`
- `System`

Core model:

- `Goal`
- `Issue`
- `Run`
- `Agent`
- `Event`
- `Incident`

Key ideas shown in the mockup:

- shared `List | Board` views of the same work
- issue detail with outputs, active branches, and run history
- focused relationship maps for dependencies, downstream unlocks, and related work
- multiple agents/subagents working on one issue in parallel
- Git-like execution history embedded in the product
- operator queue and blocked-work visibility
- system logs, metrics, traces, and queue health

## Scenario States

The mockup includes three scenario states:

- `Starting work`
- `Working at scale`
- `Resolving pressure`

These are meant to make the product feel alive and fully working rather than empty.

## Open It

```bash
open /Users/bigcube/Desktop/repos/maas/mockups/maas-codex-mvp/index.html
```

Or serve it:

```bash
cd /Users/bigcube/Desktop/repos/maas/mockups/maas-codex-mvp
python3 -m http.server 4313
```

Then open:

`http://127.0.0.1:4313/`
