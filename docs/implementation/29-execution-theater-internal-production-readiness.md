# Execution Theater Internal-Production Readiness

## Goal

Harden Theater so it remains usable when branch lineage is partial, large, or unavailable.

This batch focuses on operator trust and render safety rather than adding new visual metaphors:

- degraded lineage states become explicit
- the tree stops trying to render every inactive branch at once
- Theater reports when it is capping lineage output to stay responsive

## Scope

This batch adds:

- degraded-state metadata in the Theater read model
- explicit lineage render limits for active and history branches
- capped active/history branch rendering in the UI
- clearer lineage-state messaging when lineage is unsupported, empty, or intentionally capped
- focused regression coverage for capped lineage rendering

It does not yet add:

- server push or a dedicated live transport
- commit-level graph rendering
- a full virtualization library for the tree

## Operator Effect

Theater should now fail softer:

- if git lineage is unavailable, the rest of Theater still renders and says why the branch pane is degraded
- if lineage is large, Theater shows the newest and most relevant branches first instead of rendering an unbounded tree
- if rendering is capped, the operator can see that the view is intentionally partial rather than silently incomplete

## Validation

This batch is validated by:

- focused Theater service regression coverage, including capped lineage rendering
- Python compile checks
- frontend production build
- diff cleanliness checks

## Follow-on Work

After this batch, the Theater tranche is complete enough to shift attention back to broader MAAS priorities unless a live-transport or richer replay mode becomes a higher-value next step.
