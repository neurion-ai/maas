# MAAS Wireframes

## 1. Command

Goal:
- understand the organization in one screen
- know what needs judgment now

```
+----------------------------------------------------------------------------------+
| Top bar: Org switcher | Search/Command | Org status | Review decisions | Mode    |
+----------------------------------------------------------------------------------+
| Decision Queue        | Active Workstream Map                     | Capability   |
|-----------------------|-------------------------------------------| Health       |
| [Critical approval]   | [Workstream A: Awaiting decision]         | Team A       |
| [Policy exception]    | [Workstream B: On track]                  | Team B       |
| [Budget choice]       | [Workstream C: Blocked]                   | Team C       |
|                       | [Workstream D: Running]                   | Runtime risk |
|                       |                                           | Handoff risk |
+----------------------------------------------------------------------------------+
| Recent meaningful transitions                                                   |
+----------------------------------------------------------------------------------+
```

Above the fold:
- org status
- decision queue
- workstream map
- capability health
- meaningful transitions

Not here:
- full board
- raw logs
- provider controls

## 2. Workstreams

Goal:
- supervise execution
- inspect one workstream deeply

```
+----------------------------------------------------------------------------------+
| Top bar: Filters | Search | Saved views | Needs attention                         |
+----------------------------------------------------------------------------------+
| Ready            | In Progress      | Review / Decision | Blocked                |
|------------------|------------------|-------------------|------------------------|
| [Card]           | [Card]           | [Card]            | [Card]                 |
| [Card]           | [Card]           | [Card]            | [Card]                 |
| [Card]           |                  |                   |                        |
+-----------------------------------------------------------+----------------------+
| Inspector: selected workstream                            |                      |
| - why this exists                                         |                      |
| - next safe action                                        |                      |
| - evidence                                                |                      |
| - scope                                                   |                      |
| - linked incident                                         |                      |
| - action buttons                                          |                      |
+-----------------------------------------------------------+----------------------+
```

Cards:
- title
- priority
- owner
- one risk/progress signal

No inline control panel cards.

## 3. Agents

Goal:
- see ownership, handoffs, health, overload

```
+----------------------------------------------------------------------------------+
| Team summary left rail | Agent groups by status                | Handoff / Detail |
|------------------------|---------------------------------------|------------------|
| Research               | Working                               | Handoff queue    |
| Platform               | [Agent row]                           | [From -> To]     |
| Growth                 | [Agent row]                           | [From -> To]     |
| Governance             | Needs review                          |                  |
|                        | [Agent row]                           | Selected agent   |
|                        | Blocked                               | - current work   |
|                        | [Agent row]                           | - waiting on     |
|                        | Idle                                  | - last action    |
|                        | [Agent row]                           | - risk state     |
+----------------------------------------------------------------------------------+
```

## 4. Incidents

Goal:
- one operator inbox

```
+----------------------------------------------------------------------------------+
| Act now             | Needs approval      | Needs diagnosis     | Contained         |
|---------------------|---------------------|---------------------|-------------------|
| [Incident row]      | [Incident row]      | [Incident row]      | [Incident row]    |
| [Incident row]      |                     |                     |                   |
+---------------------------------------------------------------+------------------+
| Selected incident                                             | Actions          |
| - what happened                                               | [primary CTA]    |
| - impact                                                      | [fallback]       |
| - recommendation                                              |                  |
| - evidence                                                    |                  |
+---------------------------------------------------------------+------------------+
```

## 5. Memory

Goal:
- trusted operational memory

```
+----------------------------------------------------------------------------------+
| Objective / Plan       | Decisions / Evidence              | Canonical Memory   |
|------------------------|-----------------------------------|--------------------|
| [Objective]            | [Decision in force]               | [Canonical record] |
| [Current plan]         | [Evidence package]                | [Canonical record] |
|                        | [Open question]                   |                    |
+---------------------------------------------------------------+------------------+
| Selected memory item                                                        |
| - current truth                                                             |
| - why it matters                                                            |
| - provenance / freshness                                                    |
| - promote / revise / supersede controls                                     |
+----------------------------------------------------------------------------------+
```

## Shell Rules

- 5 primary surfaces only
- no duplicate cockpit vs board problem
- cards summarize, inspector explains
- operators see decisions before dashboards
- runtime/provider details are utility views, not the main product
