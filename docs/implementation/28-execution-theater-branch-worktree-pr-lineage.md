# Execution Theater Branch, Worktree, and PR Lineage

## Goal

Make the lower Theater pane behave like a real lineage view instead of a flat list of branch cards.

This batch strengthens the branch/worktree/PR model so operators can answer:

- which branch is stacked on top of which base?
- which work is active versus only recent history?
- which PR belongs to this branch line?

## Scope

This batch adds:

- explicit lineage metadata in the Theater read model:
  - `parent_branch_id`
  - `lineage_root_base`
  - `lineage_state`
  - `recency_rank`
- grouped lineage sections with separate active and historical branch lists
- ancestry-aware highlighting when a branch is focused from either the field or the tree
- collapsed recent-history sections so active work stays visible first

It does not yet add:

- full degraded-state and performance hardening for very large lineages
- commit-level visualization
- Theater-specific mutation controls

## UI Shape

Each base branch group now renders as:

1. `Active line`
   Active branches stay expanded and visible, with indentation reflecting tracked parent/child lineage.

2. `Recent history`
   Inactive branches remain available but start collapsed so merged or older work does not crowd current work.

3. `Focus context`
   Selecting a branch highlights the surrounding lineage context instead of only one isolated branch card.

## Validation

This batch is validated by:

- Python compile checks
- focused Theater service regression coverage for nested branch lineage
- frontend production build
- diff cleanliness checks

## Follow-on Batches

The next Theater slice should focus on internal-production readiness:

- degraded rendering when branch/worktree data is partial
- performance caps and virtualization for larger trees
- broader instrumentation and regression coverage
