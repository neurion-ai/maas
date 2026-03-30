# Execution Theater Field and Agent Motion

## Goal

Strengthen the Theater execution field so it shows real agent ownership and runtime posture directly in the field instead of only in the side focus panel.

This batch keeps the Theater surface navigation-first, but it makes the field itself feel live:

- issue cards keep stable slots for ownership
- agent tokens move only when their task ownership or runtime target changes
- idle and attention agents stay visible in a reserve dock instead of disappearing from the field

## Scope

This batch adds:

- measured agent anchors inside issue cards and in a reserve dock
- a token overlay that animates agents between those anchors as live data refreshes
- stronger issue, run, agent, and task-linked branch focus synchronization when selecting a token or run
- clearer in-field posture for stale runs and review or attention states

It does not yet add:

- richer branch-tree behavior beyond the current lineage foundation
- degraded-state and performance hardening for larger topologies
- a separate Theater-specific mutation model

## UI Shape

The top panel is now composed of three parts:

1. `Agent motion dock`
   Unattached or non-field agents remain visible in grouped reserve sections:
   - `Needs attention`
   - `Working off field`
   - `Waiting on review`
   - `Idle reserve`

2. `Execution lanes`
   Issue cards keep stable ordering and reserve explicit anchor slots for currently attached agents.

3. `Token overlay`
   Agent tokens are rendered once and repositioned to the correct anchor as data changes, which gives motion without reflowing the cards themselves.

The movement is intentionally constrained. Tokens should not drift or animate on every refresh; they should only move when the underlying assignment or visible target changes.

## Operator Effect

The result is a better answer to:

- which agent is actually attached to this issue right now?
- which agents are idle versus waiting versus in trouble?
- which run is stale enough to deserve attention before opening a deeper page?

The Theater page remains a coordination surface, not a second issue editor.

## Validation

This batch is validated by:

- frontend production build
- diff cleanliness checks
- focused manual validation of selection routing and token motion across live refreshes

Frontend test infrastructure is still intentionally light in this repo, so build plus direct review remains the primary local signal for this batch.

## Follow-on Batches

The next Theater slices should build on this field behavior:

- richer branch, worktree, and PR lineage interaction
- degraded rendering and partial-data fallbacks
- performance caps, instrumentation, and broader internal-production hardening
