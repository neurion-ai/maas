# MAAS UI Reset

> Note: this document explains why the previous UI direction failed. The current near-term product shape is captured in [11-codex-mvp-shape.md](/Users/bigcube/Desktop/repos/maas/docs/implementation/11-codex-mvp-shape.md).

## Why The Previous UI Work Failed

The previous MAAS frontend and mockup work failed for structural reasons, not cosmetic ones.

Main failures:

- it reused the visual grammar of an internal ops console
- it treated every subsystem as equally important
- it leaked backend/control-plane concepts directly into the UI
- it tried to solve a product-model problem with layout and theme changes
- it stayed too close to the old MAAS board/execution/incidents split
- it looked like a denser version of the same failed UI instead of a genuinely new product

The result was a product that felt:

- confusing
- cluttered
- too technical in the wrong places
- visually heavy
- not obviously useful on first contact

This document resets the frontend direction from zero.

## Visual Reference Direction

The target feel is closer to:

- Paperclip for product framing and org-level clarity
- Linear for density, issue cards, and inspect/detail behavior
- modern SaaS/product design for typography, spacing, and restraint

It should *not* feel like:

- a sci-fi cockpit
- a traditional admin dashboard
- a debugging console
- a runtime-adapter control panel
- a chat app

## Product Framing

MAAS is the control plane for autonomous organizations.

The human operator is not managing tasks manually. The human is:

- defining and steering objectives
- supervising workstreams
- reviewing decisions
- intervening on incidents
- maintaining trust in the system

The product should feel like a premium operating surface for an autonomous org, not a developer tool.

## First Principles

### 1. One clear object per surface

Every primary surface must have one obvious unit of attention:

- `Command`: org state and decisions
- `Workstreams`: active work
- `Agents`: teams, ownership, and handoffs
- `Incidents`: exception handling
- `Memory`: trusted knowledge

### 2. Cards summarize, panels explain

Cards are never mini control rooms.

Cards should only summarize:

- what this is
- current state
- owner
- why it matters
- one signal of risk or progress

Deeper actions, evidence, context, and history live in an inspector or detail panel.

### 3. Default UI should be decision-first

The operator must immediately understand:

- what needs attention
- what the org is doing
- what to approve
- what is blocked
- what changed recently

### 4. Runtime/provider detail is secondary

MAAS may support many agentic runtimes, but runtime adapters are not the main UI model.

The user should see:

- healthy / degraded / blocked
- which team or workstream is affected
- what action is recommended

Not:

- provider tables
- queue implementation types
- low-level worker/process concepts

### 5. Design for trust, not spectacle

The UI should feel alive, but never theatrical.

That means:

- meaningful transitions instead of noisy feeds
- visible decisions instead of generic status counts
- evidence and rationale instead of “agent personality”

## Navigation Model

Only 5 primary surfaces:

- `Command`
- `Workstreams`
- `Agents`
- `Incidents`
- `Memory`

Optional secondary utility areas:

- `Runs`
- `Policies`
- `Settings`

These should not dominate first-run UX.

## Surface Specs

### Command

Purpose:
- understand the organization in one screen

Above the fold:
- organization status
- decision queue
- active workstream map
- capability health by team
- meaningful recent changes

Primary CTA:
- `Review decisions`

### Workstreams

Purpose:
- see how work is moving

Structure:
- compact board
- sticky right-side inspector
- search/filter strip

Default lanes:
- `Ready`
- `In progress`
- `Review`
- `Blocked`
- `Backlog`

### Agents

Purpose:
- understand ownership, handoffs, and runtime health

Default groupings:
- working
- needs review
- blocked
- idle

Show:
- team
- role
- current work
- last meaningful action
- waiting on
- risk state

### Incidents

Purpose:
- one operator inbox

Group by actionability:
- act now
- needs approval
- needs diagnosis
- contained

Every incident should say:
- what happened
- impact
- recommendation
- safe fallback
- evidence

### Memory

Purpose:
- trusted organizational memory

Primary layers:
- objectives
- plans
- decisions
- evidence
- canonical memory

Key rule:
- separate provisional/working memory from canonical memory

## Visual Rules

- desktop-first
- dense but readable
- clean typography
- soft but sharp panels
- restrained color
- no oversized hero sections
- no giant metrics strips
- no low-value empty space

Typography:

- primary headings should be compact
- labels should be quiet and consistent
- cards should use short vertical rhythm

Theme:

- closer to Paperclip’s premium product feel than to the previous MAAS hard-panel console
- warmer, lighter hierarchy
- clearer content blocks
- less border noise

## What To Avoid

- giant dashboard card farms
- duplicated surfaces for the same concept
- action-heavy cards
- hard technical jargon in primary views
- fake agent personas
- provider-zoo UX
- trying to make the product feel “cool” before it feels obvious

## Rebuild Sequence

1. lock the ontology and primary surfaces
2. design the visual system and shell
3. build low-fidelity wireframes for all 5 surfaces
4. validate the first-run user journey
5. only then produce a high-fidelity mockup

## Immediate Conclusion

The previous mockup direction should be treated as failed.

Do not iterate it.

The next UI work should start from this reset document and produce a genuinely new product surface.

## First Replacement Mockup

The first Paperclip-leaning replacement mockup for this reset lives in:

- [mockups/org-control-plane-paperclip/README.md](/Users/bigcube/Desktop/repos/maas/mockups/org-control-plane-paperclip/README.md)

It is still only a mockup, but it is intentionally separate from the older failed UI experiments.
