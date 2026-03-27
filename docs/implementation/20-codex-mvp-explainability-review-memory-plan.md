# MAAS Codex MVP Explainability, Review, and Memory Plan

Status: implemented on `codex/goal-explainability-review-memory-usefulness`

## Goal

Take MAAS from "goal synthesis, grouped review, and usefulness-scored memory exist" to "the operator can see why a synthesized issue exists, what is currently on the critical path, review related low-risk issues as a real packet, and judge memory usefulness item by item."

This branch implements the second post-`#224` batch:

- `#226` Goal-to-issue explainability and critical path view
- `#228` Review packets v4 and bulk decision UX
- `#229` Memory usefulness by item, not just by run

## Sequence

- [x] `#226` Goal-to-issue explainability and critical path view
  - expose a goal-plan explainability read model over synthesized issues
  - show why each synthesized issue exists, what it depends on, and what it unlocks
  - surface the current critical path and current focus in both goal planning and issue detail

- [x] `#228` Review packets v4 and bulk decision UX
  - extend grouped review packets with packet scope and per-issue membership
  - let the operator inspect packet contents before applying a bulk decision
  - support packet-scoped partial selection so one PR batch does not force all-or-nothing review clicks

- [x] `#229` Memory usefulness by item, not just by run
  - explain why a memory item matched the current issue or retrieval query
  - expose item-level usefulness summaries from reuse, success, and failure history
  - feed that item usefulness back into prompt construction and issue detail instead of leaving it implicit in run history

## What Landed

- goal planning now returns synthesized-step explainability plus a current critical-path view
- issue detail now shows why a goal-linked issue exists, what it depends on, and whether it sits on the current critical path
- review packets now include their actual member issues and packet scope so bulk review is inspectable before action
- the `Issues` surface now supports packet-scoped selection instead of only blind approve-all / reject-all actions
- memory retrieval now exposes match reasons and usefulness summaries per artifact, and prompt assembly includes that item-level signal

## Why This Order

The delivery and verification batch made shipping truthful, but the operator still had to infer too much in three places:

- why a synthesized issue existed
- what a grouped review packet actually contained
- whether a retrieved memory item was useful because of one successful run or because it had repeatedly helped

This batch closes those gaps in the same operator loop:

- planning gets explainability
- review gets inspectable bulk decisions
- memory gets item-level usefulness instead of opaque scoring
