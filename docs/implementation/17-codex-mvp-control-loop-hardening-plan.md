# MAAS Codex MVP Control-Loop Hardening Plan

Status: implemented on `codex/codex-mvp-control-loop-hardening`

## Goal

Take the current Codex-first MAAS MVP from “autopilot exists” to “the control loop is durable, explainable, and safe to leave running.”

This batch is about removing split-brain control logic and making the operator trust one canonical backend-owned loop:

- durable autopilot ownership and heartbeat state
- one operator inbox built from backend signals instead of browser heuristics
- safer lifecycle controls when cloning or resetting projects
- clearer grouped review and recovery semantics
- governed memory freshness so promoted memory stays attributable

## Sequence

- [x] `#205` Durable autopilot ownership and lease model
  - add durable autopilot runtime lease state
  - expose lease owner, last heartbeat, last summary, and truthful runtime posture
  - make autopilot survive process-local control flow better

- [x] `#206` Lifecycle-safe project controls
  - reset cloned projects into a safe posture
  - stop clones from inheriting live autopilot state, open launch posture, or outbound webhooks

- [x] `#207` Canonical execution-state projection
  - add backend-owned `/api/operator-inbox`
  - derive operator-loop posture and attention items from backend reads, not browser stitching

- [x] `#208` Unified review gate
  - group batch-review packets in backend issue reads
  - expose consistent review eligibility, decision mode, and packet metadata

- [x] `#209` Recovery controller and playbooks
  - continue pushing recovery guidance into backend issue/run/system reads
  - keep operator actions tied to recommended recovery posture instead of page-local guesswork

- [x] `#210` Memory governance and attribution
  - add freshness metadata to promoted memory
  - keep run/issue memory context attributable and visibly fresh vs stale

- [x] `#211` Review burden reduction v2
  - expand grouped review packets
  - keep auto-approval and grouped manual review reasons explicit

- [x] `#212` Operator inbox
  - aggregate review pressure, stale runs, blocked recovery, policy conflicts, and notification failures
  - expose recommended view routing and operator action labels

- [x] `#213` Notification reliability and overdue decisions
  - add retry budgeting, dedupe-aware summaries, and notification failure attention signals
  - integrate notification delivery degradation into the operator inbox

- [x] `#214` Autonomy correctness regression suite
  - add tests for autopilot lease ownership
  - add tests for operator inbox aggregation
  - add clone safety and notification retry regressions

## What Landed

This batch makes the control loop backend-owned:

- `/api/operator-inbox` now returns a canonical operator inbox and autopilot posture
- the app shell consumes that backend workflow instead of rebuilding attention state from multiple endpoints
- notification failures, policy conflicts, stale runs, review pressure, and blocked recovery now share one attention queue

This batch also makes autonomy more durable:

- autopilot runtime leases are stored durably
- status reads now show lease owner, loop counts, heartbeat truth, and last summary even without a local in-process loop object
- cloned projects reset to a safe posture instead of inheriting live autonomy settings

And it makes review and memory more explainable:

- grouped review packets are exposed directly by backend issue reads
- review reasons distinguish manual review, grouped review, and auto-approval
- promoted memory now carries freshness metadata so runs and issues can show whether reused guidance is fresh or stale

## Why This Order

The previous batches already delivered:

- project-level autopilot
- runs, recovery playbooks, and review policy
- notification and async attention groundwork
- retrieval-backed memory

The highest-value next step was to unify those pieces into one truthful control loop so the operator no longer has to reconcile:

- autopilot state in one place
- review pressure in another
- notification failures somewhere else
- and live execution posture from several different reads

This batch fixes that coherence problem first.
