# Research 05: Dashboard & Real-Time Observability

**Date:** 2026-03-08
**Researcher:** Agent 05 (Dashboard & Observability Domain)
**Status:** Complete
**Validation:** Claims tagged with source basis per convention: (a) established practice, (b) observed in existing systems, (c) proposal

---

## Executive Summary

The dashboard is the human's only real-time window into an autonomous AI Agent Operating System. Unlike traditional monitoring dashboards that observe passive infrastructure, this dashboard observes an active system that makes decisions, allocates resources, and takes actions with real-world consequences. The design challenge is not "what metrics to show" -- it is "how to give a human meaningful oversight of 8+ autonomous agents without drowning them in noise or hiding critical failures behind summary statistics."

This document proposes a 7-page dashboard architecture organized around a strict information hierarchy: system health first, then agent status, then goal progress, then task details, then raw activity. The real-time update strategy uses a hybrid approach -- WebSocket push for critical events (agent death, goal failure, system alerts), SSE or polling for non-critical data (goal progress, task completion) -- with explicit acknowledgment of SQLite's single-writer limitation as a scaling constraint. Every UI element is justified by a concrete decision it enables the human to make. Elements that are "interesting but not actionable" are cut.

The existing HFT dashboard (React + Vite + TailwindCSS + Recharts, FastAPI backend, 9 pages, SQLite read-only, WebSocket live feed) provides a strong foundation. The general-purpose Agent OS dashboard retains its tech stack but replaces domain-specific pages (Positions, Live Trading, Backtests) with domain-agnostic pages (Goal Tree, Agent Roster, Artifacts Browser) while keeping the command center pattern.

**Key architectural decisions:**
1. Read-only dashboard with a narrow write surface for human steering (pause agent, escalate goal, send message) -- not a full CRUD command center
2. WebSocket for push events; 10-second polling for dashboard-level aggregates; 30-second polling for historical/analytical queries
3. Virtual scrolling for all unbounded lists (activity stream, trade log) to prevent DOM explosion
4. SQLite WAL mode is sufficient for the expected load (single-digit agents, sub-100 events/second) but becomes the first bottleneck to address if scale increases
5. Notification hierarchy: in-app toast for warnings, persistent banner for critical alerts, optional webhook/email for off-screen alerts

---

## Information Architecture

### The Hierarchy (Most Important to Least)

```
Level 0: SYSTEM HEALTH (always visible)
  "Is the system on fire?"
  - Overall status indicator (green/amber/red)
  - Active alerts count
  - Agent liveness summary (N/M alive)

Level 1: PROJECT CONTEXT (page header)
  "Which project am I looking at?"
  - Project selector (multi-project)
  - Current cycle / phase
  - Time since last human interaction

Level 2: GOAL PROGRESS (Command Center page)
  "Are we making progress toward the objective?"
  - Active goals with completion %
  - Blocked goals (amber) and failed goals (red)
  - Next expected milestone

Level 3: AGENT STATUS (Agent Roster page)
  "What is each agent doing right now?"
  - Agent cards: role, status, current task, heartbeat
  - Which agents are idle vs. working vs. error

Level 4: TASK DETAIL (Task Board page)
  "What are the individual work items?"
  - Task list with status, assignee, priority
  - Dependency graph (what's blocking what)

Level 5: RAW ACTIVITY (Activity Stream page)
  "What exactly happened and when?"
  - Chronological event stream
  - Agent-filtered or category-filtered views
  - Full details expandable per event
```

**Justification for this ordering (a: established UX research, Grafana best practices):** Users scan dashboards in a Z-pattern from top-left to bottom-right. The most critical information -- "is anything broken?" -- must be visible without scrolling or navigating. Goal progress answers the highest-value question ("is this working?"). Agent status answers the second question ("who is stuck?"). Task detail and raw activity serve investigation, not monitoring, and belong on dedicated pages.

**Reference -- Grafana:** Grafana's dashboard design guidelines recommend placing "the most significant elements at the top of the dashboard, trends in the middle, and details at the bottom." Their hierarchical dashboard pattern uses drill-downs from overview to detail, which maps directly to our Level 0-5 hierarchy. (Source: [Grafana Dashboard Best Practices](https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/best-practices/))

**Reference -- Datadog:** Datadog's executive dashboard guidelines recommend an "Overview group" at the top with service checks and the most important metrics, with details below. Their service map provides topology-level understanding before diving into individual service metrics. (Source: [Datadog Executive Dashboards](https://www.datadoghq.com/blog/datadog-executive-dashboards/))

### Visual Hierarchy Implementation

| Level | Visual Treatment | Position | Update Frequency |
|-------|-----------------|----------|-----------------|
| 0 | Persistent header bar, colored status pill | Top of every page | WebSocket push (instant) |
| 1 | Project selector dropdown + phase badge | Header bar right side | On navigation / 30s poll |
| 2 | Large stat cards + goal tree | Command Center main area | 10s poll |
| 3 | Agent cards grid | Agent Roster page | 10s poll + WebSocket heartbeat |
| 4 | Table / kanban columns | Task Board page | 10s poll |
| 5 | Scrollable event list | Activity Stream page | WebSocket push (batched) |

---

## Page Specifications

### Page 1: Command Center (Overview)

**Purpose:** The landing page. Answer the three most important questions in under 3 seconds: (1) Is the system healthy? (2) Are we making progress? (3) Is anything blocked or failed?

**Why the human needs this:** Without a single-screen summary, the human must check multiple pages to assess system state. This page eliminates that by surfacing the top-level health signal and the most critical items from every other page.

**Layout:**

```
+---------------------------------------------------------------+
| [Project: My Project v]  Goal 3 of 5 active           [Alerts: 0] |
+---------------------------------------------------------------+
| SYSTEM HEALTH                                                  |
| [OK] 6/6 agents alive  |  [OK] No alerts       |  [OK] System nominal |
+---------------------------------------------------------------+
| KEY METRICS (4-column stat cards, project-defined)             |
| Goals Done   | Active Now | Blocked      | Cost Today           |
+---------------------------------------------------------------+
| GOAL PROGRESS (mini goal tree)            | AGENT SUMMARY      |
| [>] Sprint 4: Ship v2.0 ........ 60%     | allocator: idle    |
|   [>] Research Phase ........... done     | researcher: running|
|   [>] Design & Build ........... active   | builder: idle      |
|   [ ] Testing .................. pending  | tester: idle       |
|   [ ] Release .................. pending  | reviewer: idle     |
|                                           |                    |
+---------------------------------------------------------------+
| RECENT ACTIVITY (last 10 entries)                              |
| 14:32 researcher produced artifact research_brief_042          |
| 14:28 allocator approved goal G-041                            |
| 14:15 reviewer completed validation check -- all clear         |
+---------------------------------------------------------------+
```

**Data Sources:**

**Core data sources (all projects):**

| Widget | DB Table(s) | Query | Update Frequency |
|--------|------------|-------|-----------------|
| System health bar | `agents` (heartbeat check) | `SELECT agent_id, status, last_heartbeat FROM agents` | 10s poll |
| Key metrics | `goals` (completion counts), `sessions` (cost tracking) | Goal status counts + session cost aggregation | 10s poll |
| Goal progress | `goals`, `tasks` (completion counts) | `SELECT status, COUNT(*) FROM tasks WHERE goal_id = ? GROUP BY status` | 10s poll |
| Agent summary | `agents` | `SELECT agent_id, role, status, current_task_id FROM agents` | 10s poll + WebSocket heartbeat events |
| Recent activity | `activity_log` | `SELECT * FROM activity_log ORDER BY timestamp DESC LIMIT 10` | WebSocket push (delta `WHERE id > last_seen`) |

**Domain data sources (declared in `project.yaml` under `dashboard_panels`):** Projects may inject additional stat cards that query domain tables. For example, an HFT project adds Equity, PnL, Drawdown, Active Strategies (from `fund_state`, `portfolio_snapshots`, `strategies`). A SaaS project adds Uptime, Active Incidents, Deployment Count (from `incidents`, `deployments`). An ML research project adds Experiments Running, Best Metric, GPU Hours (from `experiments`, `model_runs`). The dashboard loads these via the plugin system described in the Domain Plugin Architecture section.

**Existing codebase mapping:** The current `Overview.jsx` shows fund metrics (equity, PnL, drawdown, strategies) and an equity curve chart. The general-purpose version replaces the equity curve with the mini goal tree + agent summary grid. Domain-specific metrics (equity, PnL) move to the HFT domain plugin. The stat cards component (`StatCard`) can be reused directly.

---

### Page 2: Goal Tree

**Purpose:** Visualize the hierarchical goal structure of the current project. Show what the system is trying to achieve, what has been completed, what is in progress, and what is blocked.

**Why the human needs this:** Goals are the highest-level unit of work. Without this view, the human can see tasks and agent activity but cannot assess whether the overall objective is on track. The goal tree bridges the gap between "what are agents doing" (tactical) and "is the project succeeding" (strategic).

**Layout:**

```
+---------------------------------------------------------------+
| GOAL TREE                                        [Expand All] |
+---------------------------------------------------------------+
| [-] Sprint 4: Ship v2.0                            In Progress|
|   [+] Research: Evaluate approaches                 Done       |
|   [-] Design: Define architecture                   In Progress|
|     [>] G-041: API gateway design                   Approved   |
|     [>] G-042: Auth service design                  Proposed   |
|     [x] G-039: Monolith approach                    Rejected   |
|   [ ] Build: Implementation                         Pending    |
|     [ ] T-015: Implement API gateway                Not Started|
|   [ ] Test: Validation                              Pending    |
|   [ ] Release: Deploy to staging                    Pending    |
+---------------------------------------------------------------+
| GOAL DETAIL (selected item panel, right side or below)        |
| G-041: API gateway design                                      |
| Status: Approved | Proposed by: researcher | Score: 7.2/10    |
| Description: Evaluate Kong vs custom gateway...               |
| Linked task: TASK-078 (assigned to builder, pending)          |
+---------------------------------------------------------------+
```

**Visualization approach:** Indented list with expand/collapse, not a graph view. Justification: (a) trees with fewer than 50 nodes are more readable as indented lists than as node-link diagrams (established UX research); (b) the goal hierarchy is inherently ordered (phases are sequential), which indented lists represent better than spatial graphs; (c) implementation is simpler and more performant.

**Reference -- Linear:** Linear's project views use flat lists with indentation and inline status indicators. Their approach is "clean and purposefully minimal, with a layout that avoids clutter by eliminating busy sidebars, pop-ups, or excessive tabs." The goal tree adopts this philosophy -- each node shows title, status badge, and nothing else until clicked. (Source: [Linear UI Redesign](https://linear.app/now/how-we-redesigned-the-linear-ui))

**Color coding:**

| Status | Color | Icon |
|--------|-------|------|
| Done / Approved | Emerald (#10b981) | Checkmark |
| In Progress / Active | Blue (#3b82f6) | Spinning dot |
| Pending / Not Started | Gray (#6b7280) | Empty circle |
| Blocked | Amber (#f59e0b) | Warning triangle |
| Failed / Rejected | Red (#ef4444) | X mark |

**Data Sources:**

**Core data sources (all projects):**

| Widget | DB Table(s) | Query | Update Frequency |
|--------|------------|-------|-----------------|
| Goal tree nodes | `goals` (parent_goal_id for hierarchy) | `SELECT goal_id, title, status, parent_goal_id FROM goals ORDER BY priority DESC` | 10s poll |
| Task nodes | `tasks` (leaf-level work items) | `SELECT task_id, title, status, goal_id FROM tasks WHERE goal_id = ? ORDER BY priority DESC` | 10s poll |
| Goal detail panel | `goals` + `tasks` + `artifacts` (joined) | Single-row fetch by selected ID | On click (user-triggered) |

**Domain data sources (optional, via plugins):** Projects may register additional node types that appear in the goal tree. For example, an HFT project links `research_hypotheses` and `strategies` as child nodes under their parent goals, showing hypothesis scores and strategy lifecycle status. A SaaS project might link `incidents` or `feature_flags`. An ML research project might link `experiments` and `model_runs`. These are loaded by querying domain tables declared in `project.yaml` and rendered as supplementary nodes in the tree.

**[PERF_RISK]: Tree rendering with >200 nodes.** If the task tree grows beyond ~200 nodes with full expansion, recursive rendering may cause noticeable lag on lower-powered devices. Mitigation: default to collapsed state with only top-level goals expanded; use `React.memo` on tree nodes to prevent re-renders when only one node's status changes; cap visible depth to 4 levels.

---

### Page 3: Agent Roster

**Purpose:** Show the status, current task, and recent history of every agent in the system. This is the "who is doing what" page.

**Why the human needs this:** When something is slow or broken, the first question is "which agent is responsible?" The agent roster answers this instantly. It also reveals idle capacity (agents with no task) and stuck agents (running but no progress).

**Layout:**

```
+---------------------------------------------------------------+
| AGENT ROSTER                                   [6 agents, 2 active] |
+---------------------------------------------------------------+
| +-------------------+  +-------------------+  +-------------------+ |
| | allocator         |  | researcher        |  | builder           | |
| | Project Lead      |  | Research          |  | Implementation    | |
| | [IDLE]            |  | [RUNNING]         |  | [IDLE]            | |
| | Last heartbeat:   |  | Last heartbeat:   |  | Last heartbeat:   | |
| |   12s ago         |  |   3s ago          |  |   8s ago          | |
| | Current task:     |  | Current task:     |  | Current task:     | |
| |   none            |  |   TASK-078        |  |   none            | |
| | Runs: 47          |  |   "Research API   |  | Runs: 12          | |
| |                   |  |    approaches"    |  |                   | |
| | [Claude Code]     |  | [Claude Code]     |  | [Claude Code]     | |
| +-------------------+  +-------------------+  +-------------------+ |
| +-------------------+  +-------------------+  +-------------------+ |
| | tester            |  | reviewer          |  | ops_monitor       | |
| | Validation        |  | Quality Review    |  | Ops Monitoring    | |
| | [IDLE]            |  | [IDLE]            |  | [IDLE]            | |
| | ...               |  | ...               |  | Last run: 14:15   | |
| +-------------------+  +-------------------+  +-------------------+ |
+---------------------------------------------------------------+
| AGENT DETAIL (click to expand)                                 |
| researcher -- Session History                                  |
| 14:30 Started task TASK-078                                    |
| 14:28 Received assignment from allocator                       |
| 14:15 Completed task TASK-077 (goal G-041 approved)            |
| 14:00 Started task TASK-077                                    |
+---------------------------------------------------------------+
```

**Agent Card Design:**

Each card is a compact rectangle (approximately 250px wide) containing:

1. **Agent name + role** (top, bold) -- identifies who this is
2. **Status badge** -- the single most important signal. Uses the same color scheme as goal tree. **Justification:** Status answers "do I need to worry about this agent?"
3. **Heartbeat recency** -- "Ns ago" format. Turns amber if >60s, red if >90s (threshold = 3x heartbeat interval of 30s per Research 08). **Justification:** A stale heartbeat is the fastest signal that an agent has crashed or hung.
4. **Current task** -- title truncated to 2 lines. **Justification:** Links agent to the work it is doing, enabling the human to assess whether the agent is on the right track.
5. **Run count** -- total sessions. Low-priority metadata but useful for assessing agent utilization over time.
6. **Provider icon** -- Claude Code icon, Codex icon, or script icon. **Justification:** When multiple providers are in use, the human needs to know which provider an agent is using for debugging and cost tracking.

**What was cut (and why):**
- Token usage per agent: nice to have, but not actionable in real-time. Belongs in a cost analytics page, not the roster.
- Full agent logs: too noisy for a card. The activity stream page handles this.
- Agent "mood" or sentiment: meaningless for AI agents. Anti-pattern from Research 02 (simulating human attributes).

**Data Sources:**

| Widget | DB Table(s) | Query | Update Frequency |
|--------|------------|-------|-----------------|
| Agent cards | `agents` | `SELECT agent_id, name, role, status, current_task_id, last_heartbeat, total_runs FROM agents` | 10s poll + WebSocket heartbeat |
| Current task title | `tasks` (joined) | `SELECT title FROM tasks WHERE task_id = ?` for each agent's `current_task_id` | 10s poll (joined in single query) |
| Agent detail history | `activity_log` | `SELECT * FROM activity_log WHERE agent_id = ? ORDER BY timestamp DESC LIMIT 20` | On click (user-triggered) |

**Reference -- Datadog:** Datadog's infrastructure host map provides at-a-glance status for many entities using color-coded hexagonal tiles. Our agent roster adapts this pattern to a card grid, which is better for <20 entities where each card needs text content (host maps work for hundreds of entities with purely visual encoding). (Source: [Datadog Service Map](https://www.datadoghq.com/blog/service-map/))

---

### Page 4: Task Board

**Purpose:** Show all tasks in the system with their status, assignment, priority, and dependencies. This is the operational work-tracking view.

**Why the human needs this:** Tasks are the unit of work that agents execute. The human needs to see: (1) what is in progress, (2) what is blocked and why, (3) what is done, and (4) what is queued. This enables intervention decisions: reassign a blocked task, reprioritize the queue, cancel unnecessary work.

**Layout options:**

**Option A -- Table view (recommended default):** The current `Tasks.jsx` implementation uses a table with columns for Title, Type, Status, Assigned To, Priority, and Created date. This is effective for scanning and filtering. Retain it as the default.

**Option B -- Kanban columns:** Columns for Pending, In Progress, Blocked, Review, Done. Better for visualizing flow but worse for large task counts. Offer as an alternative view toggle.

**Reference -- Linear:** Linear offers multiple display modes (list, board, timeline) switchable by the user. "Dashboards let you bring together insights from across teams and projects onto a single page. Insights can be explored directly by clicking into any slice or metric to view underlying issues without leaving the dashboard." We adopt this multi-view approach. (Source: [Linear Dashboards](https://linear.app/docs/dashboards))

**Enhancements over existing implementation:**

1. **Dependency visualization:** When a task is selected, highlight its dependencies (blocked-by / blocks) with connecting lines or a mini dependency subgraph. **Justification:** The `depends_on` JSON field in the tasks table captures this data but the current UI does not expose it. A blocked task is only actionable if the human can see WHAT is blocking it.

2. **Time-in-status indicator:** Show how long a task has been in its current status. Tasks stuck in "in_progress" for >30 minutes should display an amber indicator. **Justification:** Duration-in-status is the simplest leading indicator of a stalled agent.

3. **Bulk actions (steering):** Select multiple tasks and change priority or cancel. Requires write API endpoint. See Human Steering Interface section.

**Data Sources:**

| Widget | DB Table(s) | Query | Update Frequency |
|--------|------------|-------|-----------------|
| Task table/board | `tasks` | `SELECT * FROM tasks ORDER BY priority DESC, created_at DESC` | 10s poll |
| Dependency links | `tasks` (depends_on JSON) | Parse `depends_on` JSON for each task, resolve to task_ids | On task selection (user-triggered) |
| Task detail | `tasks` + `activity_log` | `SELECT * FROM tasks WHERE task_id = ?` + `SELECT * FROM activity_log WHERE description LIKE '%' || ? || '%' ORDER BY timestamp DESC LIMIT 10` | On click |

---

### Page 5: Activity Stream

**Purpose:** A chronological, filterable log of every action taken by every agent. This is the investigation tool -- used when something went wrong and the human needs to understand the sequence of events.

**Why the human needs this:** The agent roster shows CURRENT state. The activity stream shows HISTORY. Post-incident, the human needs to reconstruct what happened: which agent did what, in what order, with what result. This is the equivalent of reading application logs, but structured and filterable.

**Layout:**

```
+---------------------------------------------------------------+
| ACTIVITY STREAM                               [Filters v]     |
| Agent: [All v]  Category: [All v]  Severity: [All v]         |
| Time range: [Last 1 hour v]                                   |
+---------------------------------------------------------------+
| 14:32:15  researcher  research   Produced artifact art_042     |
|           "Evaluated 3 approaches, recommending option B..."   |
| 14:28:03  allocator   task       Approved goal G-041           |
|           Details: score=7.2, novelty=6, feasibility=8, edge=7|
| 14:15:44  ops_monitor system     Health check complete         |
|           All metrics within limits. No alerts.                |
| 14:00:12  researcher  research   Started research task TASK-077|
|           Focus: evaluate API gateway architectures            |
| ...                                                            |
+---------------------------------------------------------------+
```

**Filtering dimensions:**
- **Agent** (dropdown, multi-select): filter by one or more agents
- **Category** (dropdown): system, research, task, communication, and any domain-specific categories declared in `project.yaml`
- **Severity** (dropdown): debug, info, warning, error, critical
- **Time range** (preset or custom): last 1h, 6h, 24h, 7d, custom

**[PERF_RISK]: Activity stream unbounded growth.** The `activity_log` table grows without limit. The current API limits to 50 entries, but the UI should support infinite scroll with cursor-based pagination (using the `id` column as cursor). Without virtualization, rendering 500+ entries will cause visible frame drops.

**Mitigation:** Use TanStack Virtual for the activity list. TanStack Virtual "virtualizes only the visible content for massive scrollable DOM nodes at 60FPS" and renders only visible items plus a small buffer, dynamically swapping DOM elements as the user scrolls. This keeps DOM size constant regardless of data volume. (Source: [TanStack Virtual](https://tanstack.com/virtual/latest))

**[PERF_RISK]: WebSocket delta delivery for activity events.** The current WebSocket implementation (`websocket.py`) polls `activity_log WHERE id > last_activity_id` every 2 seconds. At 100+ events/second, this means 200+ rows per WebSocket tick, each serialized to JSON and sent to all connected clients. At 10 connected dashboard tabs, this is 2000 JSON objects per tick.

**Mitigation strategy:**
1. **Client-side batching:** Accumulate WebSocket events in a buffer and flush to the UI at most once per second (requestAnimationFrame cadence). This prevents React re-renders from exceeding 1/second.
2. **Server-side aggregation:** For the activity stream, group events by 1-second windows on the server side. Instead of sending 100 individual events, send a batch of 100 events as a single WebSocket message.
3. **Severity filtering on the server:** Allow the client to subscribe to a minimum severity level. Debug events (which are the most voluminous) should not be pushed by default.
4. **Backpressure:** If the WebSocket send buffer grows beyond a threshold (e.g., 1000 queued messages), drop debug-level events and send a "events_dropped" meta-event so the UI can display "[N events suppressed]".

**Data Sources:**

| Widget | DB Table(s) | Query | Update Frequency |
|--------|------------|-------|-----------------|
| Activity list | `activity_log` | `SELECT * FROM activity_log WHERE id > ? ORDER BY id ASC LIMIT 50` (cursor pagination) | WebSocket push (delta, 2s server poll) |
| Filtered view | `activity_log` | Same + `AND agent_id = ?` / `AND category = ?` / `AND severity = ?` | On filter change (user-triggered fetch) |

---

### Page 6: Artifacts Browser

**Purpose:** Browse the file-based artifacts produced by agents: research briefs, design specs, validation reports, review outputs, audit logs.

**Why the human needs this:** Agents produce artifacts as their primary deliverable. The activity log tells you THAT an agent wrote a research brief; the artifacts browser lets you READ the brief. Without this, the human must SSH into the server and navigate the filesystem.

**Layout:**

```
+---------------------------------------------------------------+
| ARTIFACTS BROWSER                                              |
+---------------------------------------------------------------+
| [research/]  [specs/]  [reports/]  [reviews/]  [audits/]      |
+---------------------------------------------------------------+
| research/                                                      |
|   api_gateway_evaluation_20260307.md         7.2 KB  Mar 7    |
|   auth_architecture_review_20260307.md       5.1 KB  Mar 7    |
|   caching_strategy_20260305.md               8.4 KB  Mar 5    |
+---------------------------------------------------------------+
| PREVIEW (selected file)                                        |
| # API Gateway Evaluation -- Research Brief                     |
| **Recommendation:** Kong with custom plugins...               |
| **Confidence:** 0.72                                           |
| **Sources evaluated:** Kong, Envoy, AWS API Gateway, custom   |
| ...                                                            |
+---------------------------------------------------------------+
```

**Implementation:** The backend serves file listings from `agent_comms/artifacts/` via a new API endpoint. Markdown files are rendered client-side using a lightweight markdown renderer (e.g., react-markdown). JSON files are displayed with syntax highlighting.

**No write access.** The human can read artifacts but not edit them through the dashboard. Artifact editing happens through the agent system or direct file access. **Justification:** The dashboard is an observation tool. Modifying artifacts through the UI would bypass the agent coordination protocol (blackboard pattern from Research 02) and create a state inconsistency risk.

**Data Sources:**

| Widget | DB Table(s) / Source | Query / Method | Update Frequency |
|--------|---------------------|---------------|-----------------|
| Directory listing | Filesystem: `agent_comms/artifacts/` | New API: `GET /api/artifacts?dir=research` (os.listdir, stat) | 30s poll |
| File preview | Filesystem | New API: `GET /api/artifacts/read?path=research/file.md` (read file) | On click (user-triggered) |
| File metadata links | `artifacts` table (core) + domain tables via plugins | Cross-reference file path to DB entity | On click |

**Security consideration (from Research 06):** The artifacts API must sanitize the `path` parameter to prevent directory traversal attacks (`../../etc/passwd`). Restrict to `agent_comms/artifacts/` and reject any path containing `..`.

---

### Page 7: Settings & Configuration

**Purpose:** Display (and in limited cases modify) system configuration: risk parameters, agent definitions, polling intervals, notification preferences.

**Why the human needs this:** The human needs to verify that the system is configured correctly without reading YAML files. For the write surface: the human needs to be able to adjust risk limits and notification preferences without restarting the system.

**Layout:**

```
+---------------------------------------------------------------+
| SETTINGS                                                       |
+---------------------------------------------------------------+
| PROJECT CONFIGURATION (read-only, from project.yaml)          |
|   Project: My Project                                          |
|   Type: custom                                                 |
|   Agent Roles: allocator, researcher, builder, tester, reviewer|
|   Plan Templates: 3 universal + 2 domain-specific             |
+---------------------------------------------------------------+
| SYSTEM LIMITS (editable)                                       |
|   Max Session Cost: [$50]  Max Concurrent Agents: [5]         |
|   Heartbeat Timeout: [90s]  Max Retries Per Task: [3]         |
|   [Save Changes]                                               |
+---------------------------------------------------------------+
| DOMAIN CONFIGURATION (project-specific, editable)              |
|   (Rendered from project.yaml `dashboard_panels.settings`)     |
|   HFT example: Capital, Symbols, Risk Limits, Fee Model       |
|   SaaS example: Deploy Targets, Feature Flag Defaults          |
|   ML example: GPU Budget, Default Epochs, Dataset Paths        |
+---------------------------------------------------------------+
| NOTIFICATION PREFERENCES (editable)                            |
|   [x] In-app toasts for warnings                              |
|   [x] Persistent banner for critical alerts                    |
|   [ ] Email on agent death (email: __________)                |
|   [ ] Webhook on alert (URL: __________)                      |
|   [Save Changes]                                               |
+---------------------------------------------------------------+
| AGENT DEFINITIONS (read-only, from project.yaml)               |
|   allocator: Project Lead (provider: Claude Code)              |
|   researcher: Research (provider: Claude Code)                 |
|   ...                                                          |
+---------------------------------------------------------------+
```

**Core data sources (all projects):**

| Widget | Source | Update Frequency |
|--------|--------|-----------------|
| Project configuration | `project.yaml` (loaded at startup) | Static (reload on restart) |
| System limits | Core config table (key-value) | On load + after save |
| Notification prefs | New `notification_config` table or core config keys | On load + after save |
| Agent definitions | `agents` table | 30s poll |

**Domain data sources (project-specific):** The domain configuration section is rendered dynamically from `project.yaml` under `dashboard_panels.settings`. Each project type declares its own editable settings. For example, an HFT project exposes risk limits and trading parameters from `fund_state`. A SaaS project exposes deployment targets from `deployments_config`. The dashboard reads the field definitions from `project.yaml` and renders appropriate input controls.

---

## Real-Time Update Strategy

### The Problem

The system needs to show live updates for:
- Agent heartbeats (every 30s per agent = ~12 events/minute at 6 agents)
- Activity log entries (variable, 0-100+/minute during active cycles)
- Goal/task state changes (phase transitions: <1/minute)
- Critical alerts (rare but urgent: <1/hour normally)
- Domain-specific events (project-dependent: 0-50/minute, e.g., trading events in HFT, deployment events in SaaS)

The backend is SQLite in WAL mode, which supports concurrent reads but only a single writer at a time. The dashboard opens read-only connections (`?mode=ro`), so it never contends with agent writes.

### Technology Choice: Hybrid WebSocket + Polling

**Decision:** Use WebSocket for pushed event streams; use polling (via TanStack Query's `refetchInterval`) for aggregate/dashboard data.

**Rationale (from best practices research):**

The 2025 consensus on real-time web technologies is: "Start with SSE for simple one-way push notifications. Upgrade to WebSockets when you need interactive features or bidirectional communication." (Source: [SSE vs WebSockets vs Polling 2025](https://dev.to/haraf/server-sent-events-sse-vs-websockets-vs-long-polling-whats-best-in-2025-5ep8))

For our dashboard:
- **WebSocket is justified** because we need bidirectional communication for human steering (sending commands back to the server) and because the existing implementation already uses WebSocket.
- **Polling is justified for aggregate data** (goal progress, agent roster, task board) because these are computed queries that benefit from caching and debouncing, not raw event streams.
- **SSE is not recommended** because it provides no advantage over our existing WebSocket infrastructure and would add a second real-time transport to maintain.

### Update Frequency Matrix

**Core data (all projects):**

| Data Category | Transport | Frequency | Justification |
|---------------|-----------|-----------|---------------|
| Critical alerts (agent death, goal failure) | WebSocket push | Instant (<1s) | Human must know immediately. Delay is unacceptable. |
| Activity log deltas | WebSocket push | 2s server-side poll, 1s client-side batch | Near-real-time is sufficient. Batching prevents UI thrash. |
| Agent heartbeats | Polling (TanStack Query) | 10s `refetchInterval` | Heartbeat data changes slowly (30s agent interval). 10s polling is sufficient. |
| Task board | Polling | 10s | Tasks change infrequently (minutes between updates). |
| Goal tree | Polling | 10s | Goals change even less frequently. |
| Artifacts directory | Polling | 30s | Files are written infrequently. |
| Settings / config | Polling | Manual refresh / 60s | Configuration rarely changes. |

**Domain data (project-specific, registered by plugins):**

| Data Category | Transport | Frequency | Justification |
|---------------|-----------|-----------|---------------|
| Domain events (e.g., trading events, deployment status) | WebSocket push | 2s server-side poll | Domain-specific real-time data. Plugins declare which tables to poll. |
| Domain state (e.g., fund equity, experiment progress) | WebSocket push | 2s | Low cost. Plugins declare which key-value pairs to push. |
| Domain historical (e.g., equity curves, experiment runs) | Polling | 30s | Historical data is append-only. 30s is more than sufficient. |

### WebSocket Protocol

The current WebSocket implementation (`websocket.py`) uses a simple JSON envelope:

```json
{
  "type": "activity" | "agent_status" | "goal_progress",
  "data": [...]
}
```

**Proposed extensions for general-purpose Agent OS:**

```json
// Agent status change (new)
{
  "type": "agent_status",
  "data": {
    "agent_id": "researcher",
    "status": "running",
    "current_task_id": "TASK-078",
    "last_heartbeat": "2026-03-08T14:32:00Z"
  }
}

// Critical alert (new)
{
  "type": "alert",
  "severity": "critical",
  "data": {
    "alert_type": "agent_death",
    "agent_id": "researcher",
    "message": "Agent researcher has not sent heartbeat for 90 seconds",
    "timestamp": "2026-03-08T14:35:30Z"
  }
}

// Goal progress update (new)
{
  "type": "goal_progress",
  "data": {
    "goal_id": "cycle_18",
    "completion_pct": 0.60,
    "active_tasks": 3,
    "blocked_tasks": 0,
    "failed_tasks": 0
  }
}
```

### SQLite Scalability Assessment

**Current state:** SQLite WAL mode with read-only dashboard connections. This is well-suited for the current scale.

**Capacity analysis:**
- WAL mode allows concurrent readers with one writer (a: established, per [SQLite WAL docs](https://sqlite.org/wal.html))
- Read-only connections (`?mode=ro`) never block or are blocked by writers
- The dashboard's WebSocket loop polls the DB every 2 seconds. At 6 tables queried per tick, this is ~3 queries/second of read load -- negligible for SQLite
- Agent writes (heartbeats, activity log, task updates) are low-frequency: ~1-10 writes/second during active cycles

**[PERF_RISK]: Checkpoint starvation under concurrent long-running readers.** SQLite WAL mode requires periodic checkpoints to move data from the WAL file to the main database. "If a database has many concurrent overlapping readers and there is always at least one active reader, then no checkpoints will be able to complete and hence the WAL file will grow without bound." (Source: [SQLite WAL docs](https://sqlite.org/wal.html))

**Mitigation:** The dashboard's read-only connections are short-lived (context manager in `db.py` opens and closes per request). As long as no single read transaction holds open for more than a few seconds, checkpoint starvation will not occur. **Do not** use persistent read connections or long-running transactions in the dashboard backend. The current implementation (`get_db()` context manager) is correct.

**[PERF_RISK]: WAL mode does not work over network filesystems.** "WAL requires all processes to share a small amount of memory and processes on separate host machines obviously cannot share memory with each other." (Source: [SQLite WAL docs](https://sqlite.org/wal.html)) If the dashboard server runs on a different machine from the agents, SQLite will not work. **Mitigation:** Run all components on the same host, or migrate to PostgreSQL/Litestream for multi-host deployment. This is a known architectural constraint, not a bug.

**Scaling threshold:** If the system grows beyond ~20 agents or ~1000 events/second, the single-writer limitation will become the bottleneck (writers queue behind each other). At that point, consider: (1) Litestream for read replicas, (2) PostgreSQL migration, or (3) event streaming through a separate append-only store (e.g., a second SQLite DB for the event stream).

---

## Human Steering Interface Design

### Philosophy: Observation-First, Intervention-Narrow

The dashboard is primarily a **read-only observation tool**. The human steering surface is deliberately narrow to prevent accidental interference with autonomous agent operations. This aligns with Research 06's security model: "The core challenge is not preventing attacks from external adversaries -- it is preventing autonomous agents from causing catastrophic harm through error, drift, or inter-agent manipulation while still allowing them enough freedom to be useful."

The same principle applies to the human: give them enough control to intervene when necessary, but not so much that they accidentally break the system by clicking the wrong button.

### Allowed Actions (Write Surface)

**Core actions (all projects):**

| Action | One-Click or Confirm? | Mechanism | Justification |
|--------|----------------------|-----------|---------------|
| **Pause an agent** | One-click (toggle) | Set `agents.status = 'idle'` + send SIGTERM | Immediate safety action. Speed matters more than confirmation. |
| **Resume an agent** | One-click (toggle) | Set `agents.status = 'running'` + spawn process | Reversal of pause. Low risk. |
| **Escalate a goal** | Confirm (modal) | Set `goals.priority = 10` + send message to allocator | Changes operational priority. Human should confirm which goal. |
| **Cancel a task** | Confirm (modal) | Set `tasks.status = 'cancelled'` | Destructive action. Cancelling a task may orphan dependent tasks. |
| **Send message to agent** | Confirm (modal with text field) | Write to `messages` table (to_agent = selected) | Free-text input requires review before sending. |
| **Halt all agents** | Confirm (red button with "type HALT to confirm") | Set system halt flag + broadcast halt event | Emergency action with maximum confirmation friction. |
| **Override goal status** | Confirm (modal) | Update `goals.status` | Human overrides agent judgment. Should be traceable. |

**Domain actions (registered via plugins):** Projects may register additional steering actions. For example, an HFT project adds "Halt all trading" (sets `fund_state.trading_active = 'false'`) and "Update risk limits" (modifies trading parameters). A SaaS project might add "Freeze deployments" or "Toggle feature flag". Domain actions are declared in `project.yaml` under `dashboard_panels.actions` and rendered alongside core actions in the steering interface.

### Actions NOT Allowed Through Dashboard

- **Spawn a new agent**: This is a Claude Code / terminal operation, not a dashboard action. The dashboard observes agents; it does not manage their lifecycle at the process level.
- **Edit source code**: Code editing belongs in an IDE, not a dashboard.
- **Modify database schema**: Infrastructure change, not an operational action.
- **Delete any record**: The system is append-only by design (Research 02, blackboard pattern). Records can be marked as archived/cancelled but never deleted.

### Audit Trail for Human Actions

Every human action through the dashboard writes to the `activity_log`:

```json
{
  "agent_id": "human_operator",
  "action": "pause_agent",
  "category": "system",
  "description": "Human paused agent 'researcher' via dashboard",
  "details": {"target_agent": "researcher", "reason": "investigating stall"},
  "severity": "warning"
}
```

This creates an auditable record of human interventions, which is critical for post-incident analysis and for the system to learn from human overrides.

**Reference -- Linear:** Linear's approach is "designed so that you can take actions in multiple ways using buttons, keyboard shortcuts, contextual menus, or by searching for the action in the command line." We adopt this for the steering interface: actions are available through both on-card buttons (click) and a command palette (keyboard shortcut Cmd+K). (Source: [Linear Concepts](https://linear.app/docs/conceptual-model))

### Command Palette

A Cmd+K command palette (inspired by Linear, GitHub, and VS Code) provides keyboard-first access to all steering actions:

```
[Cmd+K] Search actions...
> Pause researcher
> Escalate goal G-041
> Send message to allocator
> Halt all agents
> Go to Agent Roster
> Go to Goal Tree
```

**Justification:** The human may have the dashboard open but not be actively clicking. A command palette enables fast intervention from the keyboard without hunting for the right page and button. This is particularly important for emergency actions (halt all agents).

---

## Alert & Notification System

### Alert Severity Tiers

| Tier | Trigger | Response | Channel |
|------|---------|----------|---------|
| **Critical** | Agent death (F1), cascading failure (F9), system halt, domain-specific emergencies (registered via plugins) | Persistent red banner at top of every page. Audio alert (optional). Cannot be dismissed without acknowledgment. | In-app banner + optional email/webhook |
| **Warning** | Agent stall (F2/F10), task blocked >30 min, cost budget >50% consumed, agent drift detected (F4) | Toast notification (bottom-right, persists for 30s). Badge on the notification bell icon. | In-app toast + badge |
| **Info** | Task completed, goal approved/rejected, acceptance criteria met, goal phase transition | Badge on notification bell icon. Listed in notification center (click to expand). | In-app badge only |
| **Debug** | Heartbeat received, routine DB writes, polling ticks | Not shown in UI by default. Available in Activity Stream with severity=debug filter. | None (log only) |

### Notification Delivery Architecture

```
Agent writes event to DB
       |
       v
WebSocket poll (2s) detects new event in activity_log (or domain event tables)
       |
       v
Server classifies severity
       |
       +--[critical]--> WebSocket push {type: "alert", severity: "critical"}
       |                  |
       |                  +--> In-app: persistent banner
       |                  +--> External: webhook POST (if configured)
       |                  +--> External: email via SMTP (if configured)
       |
       +--[warning]---> WebSocket push {type: "alert", severity: "warning"}
       |                  |
       |                  +--> In-app: toast notification
       |
       +--[info]-------> WebSocket push {type: "activity", ...}
       |                  |
       |                  +--> In-app: badge counter increment
       |
       +--[debug]------> Not pushed. Available via REST API filter.
```

**Reference -- Grafana:** Grafana's alerting system separates alert generation from alert delivery using "contact points" that define how and where notifications are sent. Their system supports grouping multiple alerts into a single notification to reduce noise. We adopt this grouping principle: if 3 agents die within 10 seconds, the dashboard shows ONE critical banner ("3 agents down") rather than 3 separate banners. (Source: [Grafana Alerting Notifications](https://grafana.com/docs/grafana/latest/alerting/fundamentals/notifications/))

### Alert Deduplication and Grouping

**Problem:** A single failure can generate many events. If the researcher agent crashes, the system may produce: (1) heartbeat timeout event, (2) task stall event, (3) dependent task blocked event, (4) cycle phase blocked event. Showing 4 separate critical alerts overwhelms the human.

**Solution:** Group alerts by root cause using a 10-second deduplication window:
1. When a critical alert arrives, buffer it for 10 seconds.
2. During the buffer window, any additional alerts with the same `agent_id` or `goal_id` are grouped into the same alert.
3. After 10 seconds, display the grouped alert: "Agent 'researcher' down -- 3 related impacts: task TASK-078 stalled, phase blocked, dependent tasks blocked."

**[PERF_RISK]: Alert storm.** If the system enters a cascading failure state, hundreds of alerts may be generated per second. Without deduplication, the UI becomes unusable.

**Mitigation:** The 10-second buffer window limits the maximum alert render rate to 6 alerts/minute per root cause. Additionally, implement a global alert rate limiter: if >20 alerts arrive in any 10-second window, suppress individual alerts and display a single meta-alert: "ALERT STORM: [N] events in last 10 seconds. System may be in cascading failure. Click to view details."

### Notification Center UI

A notification bell icon in the top-right header bar shows the count of unacknowledged notifications. Clicking opens a dropdown panel:

```
+-----------------------------------+
| NOTIFICATIONS (7 unread)    [Clear All] |
+-----------------------------------+
| [!] CRITICAL 14:35                |
|   Agent 'researcher' down         |
|   No heartbeat for 90s            |
|   [Acknowledge] [View Details]    |
+-----------------------------------+
| [!] WARNING 14:20                 |
|   Task TASK-078 blocked >30min    |
|   Waiting on dependency TASK-077  |
+-----------------------------------+
| [i] INFO 14:15                    |
|   Goal G-023 completed            |
|   All acceptance criteria met     |
+-----------------------------------+
```

**Data source:** Notifications are derived from the `activity_log` table (and any domain event tables registered by plugins), filtered by severity >= info, and stored client-side in the React state (not a separate DB table). Acknowledged notifications are tracked in localStorage to persist across page refreshes.

---

## Multi-Project Navigation

### Project Model

The Agent OS can manage multiple independent projects (e.g., SaaS Platform, ML Research, Data Pipeline). Each project has its own:
- SQLite database (`agent_comms/db/{project_id}.db`)
- Artifact directory (`agent_comms/artifacts/{project_id}/`)
- Agent roster (agents table, scoped by project)
- Configuration (`config/{project_id}/settings.yaml`)

### Navigation Design

```
+---------------------------------------------------------------+
| [> My Project v]  3 of 5 goals active    [Alerts: 0] [Bell] |
+---------------------------------------------------------------+
|                                                                |
| Project selector dropdown:                                     |
| +---------------------------+                                  |
| | SaaS Platform      [*]   |  <-- current                    |
| | ML Research Project       |                                  |
| | Data Pipeline             |                                  |
| +---------------------------+                                  |
| | + New Project             |                                  |
| +---------------------------+                                  |
```

**Switching projects:** Changes the backend DB connection and refreshes all dashboard data. All pages are project-scoped. The URL includes the project ID: `/projects/{project-slug}/command-center`.

**Global view (cross-project):** A dedicated "All Projects" option in the selector shows a summary card for each project: name, status (healthy/warning/error), agent count, last activity timestamp. This is the entry point for users managing multiple projects.

**Reference -- Linear:** Linear supports multi-account and multi-workspace navigation with "seamless switching between accounts." Their approach is a workspace selector in the top-left corner, which maps directly to our project selector. (Source: [Linear Guide](https://www.morgen.so/blog-posts/linear-project-management))

### Implementation Approach

**Phase 1 (current):** Single-project mode. The project selector is hidden. All data comes from one SQLite DB.

**Phase 2:** Multi-project mode. The FastAPI backend accepts a `project_id` path parameter. The `get_db()` function is parameterized to open the correct database. The frontend stores the selected project in URL state and React context.

**Backend change:**
```python
# Before (single project)
DB_PATH = Path("agent_comms/db/project.db")

# After (multi-project)
def get_db_path(project_id: str) -> Path:
    base = Path("agent_comms/db")
    path = base / f"{project_id}.db"
    if not path.exists():
        raise HTTPException(404, f"Project {project_id} not found")
    return path
```

**[PERF_RISK]: Multiple SQLite databases.** Each project opens its own SQLite file. If the dashboard has 10 projects and each WebSocket tick queries all of them for the global view, that is 10x the I/O. **Mitigation:** The global view queries only project-level summary data (one query per project: `SELECT COUNT(*), status FROM goals GROUP BY status` + `SELECT COUNT(*) FROM agents WHERE status = 'active'`) -- not full dashboard data. Full data is loaded only for the selected project.

---

## Existing Dashboard: Migration Path (HFT Fund Example)

The current HFT dashboard has 9 pages. This migration illustrates how an existing domain-specific dashboard maps to the general-purpose Agent OS dashboard:

| Current Page | Agent OS Page | Migration Strategy |
|-------------|--------------|-------------------|
| Overview | **Command Center** | Retain stat cards. Replace equity curve with goal progress + agent summary. Add system health bar. |
| Strategies | **Goal Tree** (partially) | Strategy lifecycle maps to goal tree nodes. Strategy detail becomes a node detail panel. |
| Positions | *Domain-specific plugin* | Not in the general-purpose dashboard. Available as an HFT-specific tab or plugin. |
| Live Trading | *Domain-specific plugin* | Not general-purpose. Moves to a domain plugin. |
| Research | **Goal Tree** (partially) | Hypotheses become nodes in the goal tree under research phases. |
| Agent Activity | **Activity Stream** | Direct mapping. Enhance with virtual scrolling and severity filtering. |
| Tasks | **Task Board** | Direct mapping. Add dependency visualization and kanban view option. |
| Backtests | *Domain-specific plugin* | Not general-purpose. Becomes a domain plugin. |
| Risk | **Settings** (partially) + **Command Center** (risk metrics) | Risk gauges move to command center health bar. Risk limits move to settings. Risk alerts feed into the notification system. |

### Domain Plugin Architecture

Domain-specific pages (Positions, Live Trading, Backtests) are not removed -- they become **plugins** that register additional navigation items and pages. The plugin system:

1. Each plugin is a directory under `dashboard/src/plugins/{domain}/`
2. A plugin exports: `{ navItems: [], routes: [], apiRoutes: [] }`
3. The main `App.jsx` dynamically loads plugins and merges their nav items and routes
4. Example plugins by project type:
   - **HFT Fund:** Positions, Live Trading, Backtests, Risk Detail
   - **SaaS Platform:** Deployments, Incidents, Feature Flags, Uptime
   - **ML Research:** Experiments, Model Registry, GPU Usage, Dataset Browser

This pattern applies to any existing dashboard: domain-specific pages become plugins, while core agent management pages remain in the general-purpose dashboard.

---

## Technical Implementation Notes

### Frontend Stack (Retained)

- **React 18+** with functional components and hooks
- **Vite** for dev server and build
- **TailwindCSS** for styling (existing dark theme)
- **TanStack Query** for data fetching with `refetchInterval` (existing: 10s default)
- **Recharts** for charts (progress timelines, metric histories, domain-specific visualizations)
- **React Router** for client-side routing (existing)
- **TanStack Virtual** (new) for virtualized lists in Activity Stream and Trade Log

### Backend Stack (Retained)

- **FastAPI** for REST API and WebSocket
- **SQLite** in WAL mode, read-only connections for dashboard
- **Starlette WebSocket** for live event push
- **uvicorn** for ASGI server

### New API Endpoints Required

| Endpoint | Method | Purpose | DB Table(s) |
|----------|--------|---------|-------------|
| `GET /api/artifacts` | GET | List files in artifacts directory | Filesystem |
| `GET /api/artifacts/read` | GET | Read a single artifact file | Filesystem |
| `GET /api/goals/tree` | GET | Hierarchical goal tree with child tasks | `goals`, `tasks` |
| `POST /api/agents/{id}/pause` | POST | Pause an agent | `agents` |
| `POST /api/agents/{id}/resume` | POST | Resume an agent | `agents` |
| `POST /api/messages` | POST | Send a message to an agent | `messages` |
| `POST /api/tasks/{id}/cancel` | POST | Cancel a task | `tasks` |
| `PUT /api/settings/system` | PUT | Update system limits | Core config table |
| `PUT /api/settings/domain` | PUT | Update domain-specific settings | Domain tables (per `project.yaml`) |
| `PUT /api/settings/notifications` | PUT | Update notification preferences | Core config / new table |
| `GET /api/projects` | GET | List all projects (multi-project) | Filesystem scan |

### WebSocket Message Types (Complete)

**Core message types (all projects):**

| Type | Direction | Content | Frequency |
|------|-----------|---------|-----------|
| `activity` | Server -> Client | Delta batch from `activity_log` | Every 2s (if new events) |
| `agent_status` | Server -> Client | Agent status change | On change |
| `alert` | Server -> Client | Critical/warning alert | On event (instant) |
| `goal_progress` | Server -> Client | Goal completion update | Every 10s |
| `command` | Client -> Server | Human steering action | On user action |
| `subscribe` | Client -> Server | Filter subscription (severity, agent) | On filter change |

**Domain message types (registered by plugins):** Projects may register additional WebSocket message types for domain-specific real-time data. For example, an HFT project registers `fund_state` (key-value pairs, every 2s) and `trading_events` (delta batch from `trading_events`, every 2s). A SaaS project might register `deployment_status` and `incident_updates`. Domain message types are declared in `project.yaml` under `dashboard_panels.websocket_types`, and the WebSocket server polls the corresponding domain tables alongside core tables.

---

## Open Questions

### 1. Should the dashboard support mobile?

The current design is desktop-first (250px sidebar, multi-column layouts). Mobile support would require a responsive layout with a hamburger menu and stacked cards. **Recommendation:** Defer. The primary user is a human at a workstation monitoring autonomous agents. Mobile access is a "check on things while away" use case, not a primary interaction mode. If needed, a stripped-down mobile view showing only Level 0 (system health) and Level 1 (alerts) would cover 90% of the mobile use case.

### 2. How should the dashboard handle offline/disconnected state?

If the WebSocket disconnects (network issue, server restart), the dashboard should: (1) show a yellow "Disconnected" banner, (2) attempt reconnection with exponential backoff (1s, 2s, 4s, 8s, max 30s), (3) on reconnect, fetch full state (not just deltas) to avoid missing events during the gap. The existing `api.js` WebSocket hook handles reconnection with `ws.current.onerror`, but does not implement backoff or state resynchronization. This needs enhancement.

### 3. What is the dashboard's own observability?

The dashboard itself is a service that can fail. Should it report its own health to the agent system? **Recommendation:** Yes, minimally. The dashboard backend should write a heartbeat to a `dashboard_health` key in the core config table every 30 seconds. If the dashboard goes down, the ops_monitor agent can detect it (no heartbeat for 90s) and alert via an alternative channel (webhook/email, since the in-app channel is down).

### 4. Should activity log entries be immutable?

The current schema allows updates and deletes on `activity_log`. For audit integrity (Research 06 recommends append-only with cryptographic chaining), the dashboard should never expose delete/update operations on activity records. The API should enforce this with read-only access to `activity_log`. **Recommendation:** Make `activity_log` append-only at the schema level (remove UPDATE/DELETE permissions for the dashboard's DB user, though SQLite does not natively support per-user permissions -- enforce in the API layer).

### 5. How to handle dashboard performance with large historical datasets?

If the system runs for months, tables like `activity_log` and `audit_trail` (core) as well as domain tables will contain millions of rows. Queries like "last 30 days of activity" will remain fast due to the timestamp index, but queries like "count of all activities by agent" will slow down.

**Recommendation:**
- Maintain materialized aggregates in the core config KV store (e.g., `total_activity_count`, `total_tasks_completed`)
- Implement time-based pagination for all list views (never `SELECT *` without a LIMIT and time bound)
- Archive old data to a separate SQLite file after 90 days (new API: `GET /api/archive/{table}`)

### 6. Dark mode only, or theme toggle?

The existing dashboard is dark-themed (gray-950 background, gray-900 cards). Dark mode is standard for operations/monitoring dashboards (reduces eye strain during long sessions). **Recommendation:** Keep dark mode as default. Do not invest in a light theme unless user feedback demands it. This is a monitoring dashboard, not a consumer product.

### 7. Accessibility considerations?

The current dashboard uses color as the primary status indicator (green/amber/red). This is insufficient for color-blind users (~8% of males). **Recommendation:** Augment every color indicator with an icon or text label. The color scheme proposals in this document already pair colors with icons (checkmark, spinning dot, warning triangle, X mark). Ensure all interactive elements are keyboard-navigable (tab order, aria-labels). The command palette (Cmd+K) inherently improves keyboard accessibility.

### 8. Rate limiting on the write API?

The human steering endpoints (pause agent, cancel task, halt all agents) need rate limiting to prevent accidental rapid-fire clicks. **Recommendation:** Debounce on the client side (500ms) and rate limit on the server side (max 1 write per endpoint per second). The "halt all agents" endpoint should have a cooldown of 60 seconds after activation.

---

## References and Sources

- [Grafana Dashboard Best Practices](https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/best-practices/) -- Visual hierarchy, Z-pattern layout, dashboard structure
- [Grafana Dashboard Design Blog](https://grafana.com/blog/2024/07/03/getting-started-with-grafana-best-practices-to-design-your-first-dashboard/) -- Information hierarchy, overview-to-detail drill-down
- [Grafana Alerting Notifications](https://grafana.com/docs/grafana/latest/alerting/fundamentals/notifications/) -- Alert grouping, notification policies, contact points
- [Grafana Webhook Notifier](https://grafana.com/docs/grafana/latest/alerting/configure-notifications/manage-contact-points/integrations/webhook-notifier/) -- Webhook delivery, HMAC signatures
- [Datadog Executive Dashboards](https://www.datadoghq.com/blog/datadog-executive-dashboards/) -- Executive overview layout, widget placement
- [Datadog Service Map](https://www.datadoghq.com/blog/service-map/) -- Topology visualization, at-a-glance service status
- [Datadog WebSocket Observability](https://docs.datadoghq.com/tracing/guide/websocket_observability/) -- WebSocket trace architecture, per-message tracing, sampling
- [Datadog Dashboard Widgets](https://docs.datadoghq.com/dashboards/) -- Widget types, layout patterns
- [Linear UI Redesign](https://linear.app/now/how-we-redesigned-the-linear-ui) -- Minimal interface philosophy, structured layouts
- [Linear Dashboards](https://linear.app/docs/dashboards) -- Cross-team dashboard insights, direct exploration
- [Linear Dashboard Best Practices](https://linear.app/now/dashboards-best-practices) -- Dashboard composition guidance
- [Linear Concepts](https://linear.app/docs/conceptual-model) -- Workspace/team/project hierarchy, keyboard-first interaction
- [Linear Guide: Setup, Best Practices](https://www.morgen.so/blog-posts/linear-project-management) -- Multi-workspace navigation, keyboard shortcuts, notification channels
- [SSE vs WebSockets vs Polling 2025](https://dev.to/haraf/server-sent-events-sse-vs-websockets-vs-long-polling-whats-best-in-2025-5ep8) -- Technology selection guidance
- [SSE vs WebSockets for Real-Time 2026](https://oneuptime.com/blog/post/2026-01-27-sse-vs-websockets/view) -- Updated comparison with production recommendations
- [WebSocket vs SSE vs Polling: Choosing Real-time 2025](https://potapov.me/en/make/websocket-sse-longpolling-realtime) -- Decision framework
- [SQLite WAL Mode](https://sqlite.org/wal.html) -- Concurrent read/write, checkpoint starvation, network filesystem limitation
- [SQLite Concurrent Writes](https://oldmoe.blog/2024/07/08/the-write-stuff-concurrent-write-transactions-in-sqlite/) -- Single-writer limitation, BEGIN CONCURRENT
- [How SQLite Scales Read Concurrency (Fly.io)](https://fly.io/blog/sqlite-internals-wal/) -- WAL internals, read scaling
- [TanStack Virtual](https://tanstack.com/virtual/latest) -- Headless virtualization for large lists, 60FPS scrolling
- [TanStack Virtual Performance Guide](https://blog.logrocket.com/speed-up-long-lists-tanstack-virtual/) -- Practical implementation, key assignment
- [Best AI Agent Observability Tools 2026 (Arize)](https://arize.com/blog/best-ai-observability-tools-for-autonomous-agents-in-2026/) -- Agent trace visualization, decision path reconstruction
- [Top AI Agent Observability Platforms 2026 (Maxim)](https://www.getmaxim.ai/articles/top-5-ai-agent-observability-platforms-in-2026/) -- Modern observability patterns, LangSmith/Langfuse
- [AI Observability Buyer's Guide 2026 (Braintrust)](https://www.braintrust.dev/articles/best-ai-observability-tools-2026) -- Evaluation-integrated observability
- [5 Observability & AI Trends 2026 (LogicMonitor)](https://www.logicmonitor.com/blog/observability-ai-trends-2026) -- Autonomous IT operating model
- [Shadcn Tree View](https://github.com/MrLightful/shadcn-tree-view) -- Hierarchical expand/collapse component
- [React D3 Tree](https://www.npmjs.com/package/react-d3-tree) -- Interactive tree graph rendering
- [MUI X Tree View](https://mui.com/x/react-tree-view/) -- Hierarchical navigation component

---

## Appendix A: Complete Data Source Map

This table consolidates every data source referenced in the page specifications, deduplicated and sorted by table name. It serves as a backend implementation checklist. Core tables are part of the Agent OS schema; domain tables are project-specific and declared in `project.yaml`.

**Core tables (all projects):**

| DB Table / Source | Pages That Read It | Columns Used | Index Required |
|------------------|--------------------|-------------|----------------|
| `agents` | Command Center, Agent Roster | agent_id, name, role, status, current_task_id, last_heartbeat, total_runs | idx on status |
| `activity_log` | Command Center (last 10), Activity Stream, Agent Roster (detail) | All columns | idx on agent_id, category, timestamp, id |
| `goals` | Command Center (progress), Goal Tree | goal_id, title, status, parent_goal_id, priority | idx on status, parent_goal_id |
| `tasks` | Command Center (goal progress), Goal Tree, Task Board | All columns | idx on status, assigned_to, goal_id |
| `sessions` | Agent Roster (detail) | All columns | idx on agent_id, status |
| `artifacts` | Artifacts Browser, Goal Tree (linked) | All columns | idx on session_id, type |
| `messages` | Human Steering (write) | All columns | idx on to_agent, status |
| Filesystem: `agent_comms/artifacts/` | Artifacts Browser | Directory listing + file content | N/A (filesystem) |
| Filesystem: `project.yaml` | Settings (read-only) | Full file | N/A (filesystem) |

**Domain tables (project-specific, loaded by plugins):**

Domain tables are declared in `project.yaml` under `domain_tables` and queried by domain plugins. The core dashboard never references them directly. Examples:

| Project Type | Domain Tables | Used By (Plugin Pages) |
|-------------|---------------|----------------------|
| HFT Fund | `fund_state`, `strategies`, `research_hypotheses`, `backtest_runs`, `paper_trades`, `paper_positions`, `portfolio_snapshots`, `trading_events` | Positions, Live Trading, Backtests, Risk Detail |
| SaaS Platform | `deployments`, `incidents`, `feature_flags`, `uptime_checks` | Deployments, Incidents, Feature Flags |
| ML Research | `experiments`, `model_runs`, `dataset_versions`, `gpu_usage` | Experiments, Model Registry, GPU Dashboard |

---

## Appendix B: WebSocket Message Volume Estimation

Estimating WebSocket bandwidth to validate that the hybrid approach is sustainable.

**Assumptions:**
- 6 agents, 1 active at a time (typical), 3 active during fan-out phases
- Activity log: ~5 events/minute during idle, ~60 events/minute during active work, peak ~200 events/minute during parallel execution
- Domain events (project-specific): 0-50/minute depending on project type and phase (e.g., trading events in HFT, deployment events in SaaS)
- Goal/agent status: lightweight state updates, ~200 bytes per message
- 1-3 connected dashboard clients

**Per-tick (2-second) payload size:**

| Message Type | Events/Tick (typical) | Events/Tick (peak) | Bytes/Event | Bytes/Tick (typical) | Bytes/Tick (peak) |
|-------------|----------------------|--------------------|-----------|--------------------|-------------------|
| goal_progress | 1 (always sent) | 1 | ~200 | 200 | 200 |
| activity | 0-2 | 6-7 | ~300 | 0-600 | 2,100 |
| domain events | 0 | 1 | ~400 | 0 | 400 |
| **Total** | | | | **~800** | **~2,700** |

**Per-second bandwidth:** ~400 bytes typical, ~1,350 bytes peak. Per client per day: ~34 MB typical, ~116 MB peak. This is negligible for a local network dashboard.

**[PERF_RISK] assessment:** At these volumes, WebSocket overhead is not a concern. The bottleneck would be SQLite query latency on the server side, not network bandwidth. The 2-second server-side poll interval is conservative; it could be reduced to 1 second without measurable impact.

**At scale (20 agents, 1000 events/second):** Payload per tick would be ~600KB (2000 events * 300 bytes). This is still manageable per-client but requires the server-side batching and severity filtering described in the Activity Stream section. At this scale, consider switching from polling-the-DB to a proper pub/sub system (Redis, or an in-process event bus).
