# Core Architecture & Data Model — Research Output

**Research Agent:** 01-core-architecture
**Date:** 2026-03-08
**Status:** Complete
**Validation:** Claims tagged with source basis: (a) established distributed systems / database practice, (b) observed in existing multi-agent systems (Anthropic, OpenAI Codex, LangGraph, etc.), (c) novel proposal. Confidence marked [HIGH], [MEDIUM], or [LOW].

---

## Executive Summary

The AI Agent Operating System requires a minimal but complete set of foundational abstractions: **Projects**, **Goals** (hierarchical, forming a DAG), **Tasks** (leaf-level executable units), **Agents** (with sessions), **Artifacts** (versioned outputs), and **Events** (append-only audit trail). The central design principle is the **blackboard architecture** — a single SQLite database serves as the shared knowledge base that all agents read from and write to, with no direct agent-to-agent messaging required. Concurrency is handled through SQLite WAL mode combined with optimistic locking via version columns, which is sufficient for the expected scale (tens of concurrent agents, not thousands). Identity uses **prefixed ULIDs** (e.g., `goal_01JBK3...`, `task_01JBK4...`) for time-sortability, uniqueness without coordination, and human readability. Project-specific rules (like "Sharpe > 1.5 for promotion" in a trading fund, or "test coverage >= 80%" in a SaaS project) are expressed as declarative JSON gate definitions stored in a `gates` table, avoiding both over-engineered DSLs and under-structured freeform text.

---

## 1. Proposed Abstractions

### 1.1 Minimum Entity Set

| Entity | Purpose | Confidence |
|--------|---------|------------|
| **Project** | Top-level container; defines domain, config, gates | [HIGH] |
| **Goal** | Hierarchical objective with acceptance criteria; forms a DAG | [HIGH] |
| **Task** | Leaf-level executable unit assigned to an agent session | [HIGH] |
| **Agent** | A registered agent identity (role, capabilities, status) | [HIGH] |
| **Session** | A single agent execution run (bounded by start/end time) | [HIGH] |
| **Artifact** | A structured output produced by a task (file + metadata) | [HIGH] |
| **Event** | Append-only log of all state changes (audit trail) | [MEDIUM] |
| **Gate** | A declarative acceptance check tied to a goal or lifecycle transition | [MEDIUM] |

### 1.2 Justification for Each

**Project** — Required because the system is project-independent. A single installation may run multiple projects (a hedge fund AND a SaaS product). The project defines the domain vocabulary, promotion criteria, and resource constraints. Without it, domain-specific configuration has no home. [HIGH]

**Goal** — The fundamental unit of intent. Goals decompose hierarchically: a top-level goal ("Launch SaaS product" or "Build profitable trading fund") breaks into sub-goals ("Build authentication system", "Research alpha opportunities") which break further. Goals carry acceptance criteria that are machine-checkable. This is the primary mechanism through which the allocator agent steers the system. [HIGH]

**Task** — Distinct from goals because tasks are the *executable* units. A goal like "Research user onboarding drop-off" may produce multiple tasks: "Query analytics for funnel metrics", "Analyze session recordings", "Write research brief". Similarly, a trading goal might produce "Fetch funding rate data", "Analyze open interest patterns", "Write alpha hypothesis". Tasks are what agents actually pick up and work on. Collapsing goals and tasks into one entity was considered and rejected — goals need richer lifecycle management (acceptance criteria, stop conditions, priority scoring) while tasks need simpler execution semantics (assigned, in_progress, done). [HIGH]

**Agent** — Represents a persistent identity across sessions. An agent has a role, capabilities, and a track record. The same "researcher" agent may run across many sessions. Agent identity is separate from session identity because we need to track agent-level metrics (total tasks completed, failure rate, specialization) independent of any single run. [HIGH]

**Session** — A single execution of an agent (one Claude Code invocation, one Codex run, one script execution). Sessions are bounded by start/end timestamps and track resource consumption (tokens used, cost, duration). Sessions are the unit of failure — when something crashes, it is a session that crashes, not an agent. [HIGH]

**Artifact** — Structured outputs that persist beyond the session that created them. Research briefs, design specs, validation reports, code files. Artifacts are stored on the filesystem but tracked in the database with metadata (type, path, producing task, version). Storing artifact *content* in the DB was considered and rejected — file sizes can be large (parquet files, charts), and filesystem storage is simpler for version control integration. [HIGH]

**Event** — An append-only log of every significant state change. This is the audit trail that makes the system debuggable. "Goal X transitioned from active to completed", "Task Y was assigned to agent Z", "Gate check failed: metric 1.2 < required threshold 1.5". Events are never mutated or deleted. This is separate from the mutable state tables because it preserves history that the current-state tables overwrite. [MEDIUM] — the question is whether this is essential at launch or can be added later. I argue it is essential because debugging multi-agent systems without an event log is extremely painful, but the schema cost is low (one table).

**Gate** — Declarative acceptance checks that guard lifecycle transitions. For example, "a feature can only move from `staging` to `production` if test coverage >= 80% AND p95 latency < 200ms AND no critical bugs open" (SaaS), or "a strategy can only be promoted if Sharpe > 1.5 AND MaxDD < 15%" (trading). Gates make promotion criteria explicit and machine-checkable rather than relying on agent judgment. [MEDIUM] — gates could alternatively be encoded as Python functions in a plugin system, but declarative JSON is simpler to inspect, modify, and version.

### 1.3 What Was Considered and Rejected

**Message / Inbox** — Some existing agent systems (including the HFT fund prototype that inspired this design) have a `messages` table for agent-to-agent communication. In the blackboard architecture, this is unnecessary. Agents communicate by writing state to the blackboard (creating tasks, updating goals, producing artifacts). Direct messaging creates hidden state, coupling between agents, and ordering dependencies. The blackboard pattern from the 1970s HEARSAY-II system and recent research (2025-2026) on LLM-based multi-agent blackboard systems confirms that shared-state coordination outperforms direct messaging for this class of problems. [HIGH] — Messages are an anti-pattern for this architecture.

**Team / Crew** — Some frameworks (CrewAI) model agents as teams with roles. This is a human org simulation anti-pattern. Agents do not need to "know" each other — they need to know the state of the blackboard. The allocator/manager agent assigns tasks; agents do not need team membership to function. [HIGH]

**Workflow / Pipeline** — LangGraph uses explicit graph-based workflows. This is useful for deterministic pipelines but over-constraining for an agent OS where goals decompose dynamically. Goal DAGs + task dependencies provide the same ordering guarantees without hardcoding the workflow shape. [MEDIUM] — there may be cases where reusable workflow templates are valuable (see Plan Templates in Section 5), but these should be advisory, not enforced infrastructure.

---

## 2. Goal Hierarchy

### 2.1 Structure: DAG (not Tree) [HIGH]

Goals form a **directed acyclic graph**, not a strict tree. A goal can have multiple parents. Example: "Improve error logging" serves both the parent goal "Reduce incident response time" and "Improve operational reliability". A tree would force an artificial choice of single parentage.

However, the primary decomposition is tree-like (one parent is the "primary" parent). Multiple parents are expressed through a `goal_dependencies` junction table, not by duplicating the goal.

### 2.2 Depth Limits [MEDIUM]

Recommended maximum depth: **4 levels**.

| Level | Name | Example (SaaS) | Example (ML Research) | Example (Trading) |
|-------|------|----------------|----------------------|-------------------|
| 0 | Mission | "Launch SaaS product" | "Publish SOTA results on benchmark X" | "Build profitable crypto fund" |
| 1 | Objective | "Build authentication system" | "Improve model accuracy past 92%" | "Find alpha in derivatives flow" |
| 2 | Initiative | "Implement OAuth2 provider" | "Experiment with attention variants" | "Research BTC funding rate patterns" |
| 3 | Deliverable | "Write OAuth2 token endpoint" | "Run ablation study on head count" | "Produce research brief on seasonality" |

Deeper than 4 levels is a sign of premature decomposition. Leaf goals should map cleanly to 1-3 tasks. [MEDIUM] — some domains may need 5 levels, but starting with a 4-level recommendation and relaxing later is safer than starting unconstrained.

### 2.3 Goal Metadata

Each goal carries:

| Field | Type | Purpose | Confidence |
|-------|------|---------|------------|
| `goal_id` | TEXT (ULID) | Unique identifier | [HIGH] |
| `project_id` | TEXT (FK) | Owning project | [HIGH] |
| `parent_goal_id` | TEXT (FK, nullable) | Primary parent in hierarchy | [HIGH] |
| `title` | TEXT | Human-readable title | [HIGH] |
| `description` | TEXT | Detailed description | [HIGH] |
| `status` | TEXT (enum) | Current lifecycle state | [HIGH] |
| `priority` | INTEGER (1-10) | Allocator-assigned priority | [HIGH] |
| `acceptance_criteria` | TEXT (JSON) | Machine-checkable criteria | [HIGH] |
| `stop_conditions` | TEXT (JSON) | When to abandon this goal | [MEDIUM] |
| `depth` | INTEGER | Level in hierarchy (0=mission) | [MEDIUM] |
| `created_by` | TEXT (FK) | Agent that proposed this goal | [HIGH] |
| `assigned_to` | TEXT (FK, nullable) | Agent responsible for this goal | [MEDIUM] |
| `confidence` | REAL (0.0-1.0) | Current confidence in achievability | [MEDIUM] |
| `version` | INTEGER | Optimistic locking version | [HIGH] |
| `created_at` | TIMESTAMP | Creation time | [HIGH] |
| `updated_at` | TIMESTAMP | Last modification time | [HIGH] |

---

## 3. State Machines

### 3.1 Goal States [HIGH]

```
                              +------------+
                    +-------->| abandoned  |
                    |         +------------+
                    |
+----------+   +---+---+   +---------+   +-----------+
| proposed +-->| active +-->| blocked +-->|  active   | (unblocked)
+----------+   +---+---+   +---------+   +-----------+
                   |
                   |         +-----------+
                   +-------->| completed |
                   |         +-----------+
                   |
                   |         +--------+
                   +-------->| failed |
                             +--------+
```

| From | To | Trigger | Requires Human? |
|------|----|---------|-----------------|
| `proposed` | `active` | Allocator approves | No (allocator agent) |
| `proposed` | `abandoned` | Allocator rejects | No |
| `active` | `completed` | All acceptance criteria pass | No |
| `active` | `failed` | Stop conditions met OR unrecoverable error | No |
| `active` | `blocked` | Dependency failed or external blocker | No |
| `active` | `abandoned` | Allocator deprioritizes | No |
| `blocked` | `active` | Blocker resolved | No |
| `failed` | `active` | Manual retry with new approach | Yes (human or allocator) |

**Design choice:** No transition requires mandatory human approval in the default configuration. The allocator agent acts as the decision-maker. However, projects can configure specific transitions to require human approval via the gate system (e.g., "deploying to production requires human sign-off"). [HIGH]

### 3.2 Task States [HIGH]

```
+---------+   +----------+   +-------------+   +--------+   +------+
| pending +-->| assigned +-->| in_progress +-->| review +-->| done |
+---------+   +----------+   +------+------+   +--------+   +------+
                                     |
                              +------+------+
                              |   blocked   |
                              +------+------+
                                     |
                              +------+------+
                              |  cancelled  |
                              +-------------+
                              +-------------+
                              |   failed    |
                              +-------------+
```

| From | To | Trigger |
|------|----|---------|
| `pending` | `assigned` | Allocator assigns to agent |
| `assigned` | `in_progress` | Agent begins work (session started) |
| `in_progress` | `done` | Agent completes, output validated |
| `in_progress` | `failed` | Unrecoverable error during execution |
| `in_progress` | `blocked` | Missing dependency or external blocker |
| `in_progress` | `review` | Agent requests review from allocator |
| `review` | `done` | Allocator approves output |
| `review` | `in_progress` | Allocator requests changes |
| `blocked` | `in_progress` | Blocker resolved |
| `*` | `cancelled` | Allocator cancels (parent goal changed) |

### 3.3 Agent States [HIGH]

```
+--------------+   +-------+   +---------+
| registered  +-->|  idle  |<--+ running |
+--------------+   +---+---+   +---+-----+
                       |           |
                       |      +----+----+
                       |      |  error  |
                       |      +---------+
                       |
                  +----+-----+
                  | disabled |
                  +----------+
```

| From | To | Trigger |
|------|----|---------|
| `registered` | `idle` | Agent initialization complete |
| `idle` | `running` | Session started, task picked up |
| `running` | `idle` | Session ended normally |
| `running` | `error` | Session crashed or timed out |
| `error` | `idle` | Error acknowledged, agent reset |
| `idle` | `disabled` | Admin/allocator disables agent |
| `disabled` | `idle` | Admin/allocator re-enables agent |

### 3.4 Session States [HIGH]

```
+---------+   +---------+   +-----------+
| started +-->| running +-->| completed |
+---------+   +---+-----+   +-----------+
                  |
             +----+----+
             | crashed |
             +---------+
             +----------+
             | timed_out|
             +----------+
```

Sessions are lightweight — they track a single execution run. The key data they carry is resource consumption: tokens_used, cost, duration, and the task(s) they worked on.

---

## 4. Proposed Schema

### 4.1 Design Principles

1. **SQLite as the sole data store for operational state.** [HIGH] — (a) This is an established, proven choice. SQLite handles the expected concurrency (tens of agents) well in WAL mode. No need for PostgreSQL, Redis, or message queues at this scale. (b) SkyPilot uses SQLite with WAL for concurrent agent job scheduling in production. Claude Code uses SQLite for memory/state persistence across sessions.

2. **Prefixed ULIDs as primary keys for all domain entities.** [HIGH] — (a) ULIDs are 128-bit identifiers with a 48-bit millisecond timestamp prefix and 80 bits of randomness, encoded as 26-character Crockford Base32 strings. They are lexicographically sortable (time-ordered), globally unique without coordination, and more compact than UUIDs. (b) The prefix pattern follows Stripe's prefixed ID philosophy (`ch_`, `cus_`, `sub_`), which is [widely praised for developer experience](https://brandur.org/nanoglyphs/026-ids). Note: UUID v7 (standardized in RFC 9562, April 2024) is a viable alternative that combines time-ordering with UUID ecosystem compatibility, but ULIDs are more compact (26 chars vs 36) and already well-supported in Python.

3. **Version columns for optimistic locking.** [HIGH] — (a) Every mutable entity gets a `version INTEGER DEFAULT 1` column. Updates include `WHERE version = ?` and `SET version = version + 1`. This is an established concurrency control pattern documented in [Peewee ORM](https://charlesleifer.com/blog/optimistic-locking-in-peewee-orm/) and [SQLAlchemy](https://oneuptime.com/blog/post/2026-01-25-optimistic-locking-sqlalchemy/view) for SQLite specifically. It assumes conflicts are rare (which they are when an allocator assigns tasks to specific agents) and only detects conflicts at write time.

4. **JSON columns for flexible structured data.** [HIGH] — (a) SQLite has native JSON support via `json()`, `json_extract()`, `json_each()` etc. (built-in since 3.38.0). SQLite 3.45.0+ also supports JSONB (binary JSON) format which reduces parsing overhead for repeated access. Expression indexes can be created on JSON paths (`CREATE INDEX idx ON t(json_extract(col, '$.field'))`) for query performance. Using JSON columns for acceptance criteria, parameters, metadata, and similar semi-structured data avoids schema explosion while remaining queryable. [VERIFIED per SQLite JSON1 documentation.](https://sqlite.org/json1.html)

5. **Append-only events table for audit trail.** [MEDIUM] — Every state change is recorded as an event. This provides full history without complicating the mutable state tables.

6. **CHECK constraints for enums.** [HIGH] — Enforcing valid states at the database level prevents the class of bugs where an agent writes an invalid status string.

### 4.2 SQL CREATE Statements

```sql
-- ============================================================
-- PRAGMA configuration (applied on every connection)
-- ============================================================
-- PRAGMA journal_mode = WAL;
-- PRAGMA busy_timeout = 5000;
-- PRAGMA synchronous = NORMAL;
-- PRAGMA foreign_keys = ON;
-- PRAGMA cache_size = -64000;  -- 64MB cache

-- ============================================================
-- PROJECTS
-- ============================================================
CREATE TABLE projects (
    project_id    TEXT PRIMARY KEY,              -- ULID, prefixed: proj_01JBK3...
    name          TEXT NOT NULL,
    description   TEXT,
    status        TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active', 'paused', 'archived')),
    config        TEXT NOT NULL DEFAULT '{}',    -- JSON: domain-specific settings
    gates_config  TEXT NOT NULL DEFAULT '{}',    -- JSON: gate definitions (see Section 5)
    created_by    TEXT,                          -- agent_id or 'human'
    version       INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);

-- ============================================================
-- AGENTS
-- ============================================================
CREATE TABLE agents (
    agent_id      TEXT PRIMARY KEY,              -- ULID, prefixed: agent_01JBK3...
    project_id    TEXT NOT NULL,
    name          TEXT NOT NULL,
    role          TEXT NOT NULL,                  -- e.g., 'allocator', 'researcher', 'coder'
    provider      TEXT NOT NULL DEFAULT 'claude', -- 'claude', 'openai', 'custom'
    model         TEXT,                           -- e.g., 'opus', 'sonnet', 'o3'
    capabilities  TEXT NOT NULL DEFAULT '[]',     -- JSON array of capability tags
    status        TEXT NOT NULL DEFAULT 'registered'
                  CHECK (status IN ('registered', 'idle', 'running', 'error', 'disabled')),
    config        TEXT NOT NULL DEFAULT '{}',     -- JSON: agent-specific config
    total_sessions    INTEGER NOT NULL DEFAULT 0,
    total_tasks_done  INTEGER NOT NULL DEFAULT 0,
    total_tokens_used INTEGER NOT NULL DEFAULT 0,
    total_cost        REAL NOT NULL DEFAULT 0.0,
    last_heartbeat    TEXT,
    version       INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (project_id) REFERENCES projects(project_id)
);

-- ============================================================
-- SESSIONS
-- ============================================================
CREATE TABLE sessions (
    session_id    TEXT PRIMARY KEY,              -- ULID, prefixed: sess_01JBK3...
    agent_id      TEXT NOT NULL,
    task_id       TEXT,                          -- nullable: session may do setup/monitoring
    status        TEXT NOT NULL DEFAULT 'started'
                  CHECK (status IN ('started', 'running', 'completed', 'crashed', 'timed_out')),
    started_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    ended_at      TEXT,
    tokens_used   INTEGER NOT NULL DEFAULT 0,
    cost          REAL NOT NULL DEFAULT 0.0,
    error_message TEXT,
    metadata      TEXT NOT NULL DEFAULT '{}',    -- JSON: provider-specific session data
    version       INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id),
    FOREIGN KEY (task_id)  REFERENCES tasks(task_id)
);

-- ============================================================
-- GOALS
-- ============================================================
CREATE TABLE goals (
    goal_id           TEXT PRIMARY KEY,          -- ULID, prefixed: goal_01JBK3...
    project_id        TEXT NOT NULL,
    parent_goal_id    TEXT,                      -- NULL for top-level mission goals
    title             TEXT NOT NULL,
    description       TEXT,
    status            TEXT NOT NULL DEFAULT 'proposed'
                      CHECK (status IN (
                          'proposed', 'active', 'blocked', 'completed',
                          'failed', 'abandoned'
                      )),
    priority          INTEGER NOT NULL DEFAULT 5
                      CHECK (priority BETWEEN 1 AND 10),
    depth             INTEGER NOT NULL DEFAULT 0,
    acceptance_criteria TEXT NOT NULL DEFAULT '[]',  -- JSON array of criteria objects
    stop_conditions     TEXT NOT NULL DEFAULT '[]',  -- JSON array of stop condition objects
    confidence        REAL DEFAULT NULL,             -- 0.0-1.0, agent's belief in achievability
    created_by        TEXT NOT NULL,                 -- agent_id
    assigned_to       TEXT,                          -- agent_id responsible
    started_at        TEXT,
    completed_at      TEXT,
    version           INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (project_id)     REFERENCES projects(project_id),
    FOREIGN KEY (parent_goal_id) REFERENCES goals(goal_id),
    FOREIGN KEY (created_by)     REFERENCES agents(agent_id),
    FOREIGN KEY (assigned_to)    REFERENCES agents(agent_id)
);

-- Junction table for goal-to-goal dependencies (DAG edges beyond parent)
CREATE TABLE goal_dependencies (
    goal_id       TEXT NOT NULL,
    depends_on    TEXT NOT NULL,
    dependency_type TEXT NOT NULL DEFAULT 'requires'
                  CHECK (dependency_type IN ('requires', 'benefits_from', 'conflicts_with')),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    PRIMARY KEY (goal_id, depends_on),
    FOREIGN KEY (goal_id)    REFERENCES goals(goal_id),
    FOREIGN KEY (depends_on) REFERENCES goals(goal_id),
    CHECK (goal_id != depends_on)
);

-- ============================================================
-- TASKS
-- ============================================================
CREATE TABLE tasks (
    task_id       TEXT PRIMARY KEY,              -- ULID, prefixed: task_01JBK3...
    goal_id       TEXT NOT NULL,                 -- every task belongs to a goal
    project_id    TEXT NOT NULL,
    title         TEXT NOT NULL,
    description   TEXT,
    task_type     TEXT NOT NULL
                  CHECK (task_type IN (
                      'research', 'design', 'implementation', 'validation',
                      'review', 'monitoring', 'infrastructure', 'bug_fix',
                      'data_collection', 'analysis'
                  )),
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN (
                      'pending', 'assigned', 'in_progress', 'blocked',
                      'review', 'done', 'failed', 'cancelled'
                  )),
    priority      INTEGER NOT NULL DEFAULT 5
                  CHECK (priority BETWEEN 1 AND 10),
    assigned_to   TEXT,                          -- agent_id
    created_by    TEXT NOT NULL,                 -- agent_id
    depends_on    TEXT NOT NULL DEFAULT '[]',    -- JSON array of task_ids
    input_artifact_ids  TEXT NOT NULL DEFAULT '[]',  -- JSON array of artifact_ids
    output_artifact_ids TEXT NOT NULL DEFAULT '[]',  -- JSON array of artifact_ids
    acceptance_criteria TEXT NOT NULL DEFAULT '[]',   -- JSON array
    metadata      TEXT NOT NULL DEFAULT '{}',
    assigned_at   TEXT,
    started_at    TEXT,
    completed_at  TEXT,
    version       INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (goal_id)     REFERENCES goals(goal_id),
    FOREIGN KEY (project_id)  REFERENCES projects(project_id),
    FOREIGN KEY (assigned_to) REFERENCES agents(agent_id),
    FOREIGN KEY (created_by)  REFERENCES agents(agent_id)
);

-- ============================================================
-- ARTIFACTS
-- ============================================================
CREATE TABLE artifacts (
    artifact_id   TEXT PRIMARY KEY,              -- ULID, prefixed: artf_01JBK3...
    project_id    TEXT NOT NULL,
    task_id       TEXT,                           -- nullable: some artifacts are manual inputs
    goal_id       TEXT,
    artifact_type TEXT NOT NULL,
                  -- NOTE: No CHECK constraint on artifact_type.
                  -- Core types: 'code', 'data', 'config', 'report', 'review', 'other'
                  -- Domain-specific types (e.g., 'research_brief', 'strategy_spec',
                  -- 'backtest_report', 'risk_report', 'experiment_log', 'deploy_manifest')
                  -- are registered in project.yaml and validated at the application layer.
    title         TEXT NOT NULL,
    description   TEXT,
    file_path     TEXT NOT NULL,                  -- relative to project artifact root
    mime_type     TEXT,                            -- e.g., 'application/json', 'text/markdown'
    size_bytes    INTEGER,
    checksum      TEXT,                            -- SHA-256 of file contents
    produced_by   TEXT,                            -- agent_id
    version_num   INTEGER NOT NULL DEFAULT 1,     -- artifact version (not optimistic lock)
    parent_artifact_id TEXT,                       -- previous version of this artifact
    metadata      TEXT NOT NULL DEFAULT '{}',      -- JSON
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (project_id)         REFERENCES projects(project_id),
    FOREIGN KEY (task_id)            REFERENCES tasks(task_id),
    FOREIGN KEY (goal_id)            REFERENCES goals(goal_id),
    FOREIGN KEY (produced_by)        REFERENCES agents(agent_id),
    FOREIGN KEY (parent_artifact_id) REFERENCES artifacts(artifact_id)
);

-- ============================================================
-- GATES (declarative acceptance checks)
-- ============================================================
CREATE TABLE gates (
    gate_id       TEXT PRIMARY KEY,              -- ULID, prefixed: gate_01JBK3...
    project_id    TEXT NOT NULL,
    name          TEXT NOT NULL,                  -- e.g., 'staging_promotion', 'experiment_approval'
    description   TEXT,
    entity_type   TEXT NOT NULL                   -- what this gate applies to
                  CHECK (entity_type IN ('goal', 'task', 'artifact', 'lifecycle')),
    trigger_transition TEXT,                      -- e.g., 'staging->production', 'draft->approved'
    conditions    TEXT NOT NULL DEFAULT '[]',     -- JSON array of condition objects
    -- Each condition: {"field": "metric_name", "op": ">=", "value": 1.5}
    requires_human BOOLEAN NOT NULL DEFAULT 0,   -- if true, human must approve
    enabled       BOOLEAN NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (project_id) REFERENCES projects(project_id)
);

-- ============================================================
-- EVENTS (append-only audit trail)
-- ============================================================
CREATE TABLE events (
    event_id      TEXT PRIMARY KEY,              -- ULID, prefixed: evt_01JBK3...
    project_id    TEXT NOT NULL,
    entity_type   TEXT NOT NULL,                  -- 'goal', 'task', 'agent', 'session', 'artifact'
    entity_id     TEXT NOT NULL,                  -- the ID of the affected entity
    event_type    TEXT NOT NULL,                  -- 'status_changed', 'created', 'assigned', etc.
    agent_id      TEXT,                           -- who caused this event
    session_id    TEXT,                           -- in which session
    old_value     TEXT,                           -- JSON: previous state (for changes)
    new_value     TEXT,                           -- JSON: new state
    description   TEXT,                           -- human-readable description
    severity      TEXT NOT NULL DEFAULT 'info'
                  CHECK (severity IN ('debug', 'info', 'warning', 'error', 'critical')),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
    -- No updated_at: events are immutable
    -- No version: events are never updated
);

-- ============================================================
-- FAILURE MEMORY (per Research 02, Pattern 8: Structured Failure Memory)
-- Records of what went wrong and why, queried by future agents
-- to avoid repeating mistakes.
-- ============================================================
CREATE TABLE failure_memory (
    failure_id    TEXT PRIMARY KEY,              -- ULID, prefixed: fail_01JBK3...
    project_id    TEXT NOT NULL,
    source_type   TEXT NOT NULL,                 -- What entity failed
                  -- Core types: 'goal', 'task', 'artifact'
                  -- Domain-specific types (e.g., 'strategy', 'hypothesis', 'backtest',
                  -- 'experiment', 'deployment') are validated at the application layer.
    source_id     TEXT NOT NULL,                 -- ID of the thing that failed
    family_id     TEXT,                          -- Grouping for related failures
    failure_type  TEXT NOT NULL,
                  -- Core failure types (domain-agnostic):
                  --   'data_quality', 'implementation_bug', 'insufficient_data',
                  --   'infeasible', 'timeout', 'hallucination', 'drift', 'other'
                  -- Domain-specific failure types (registered in project.yaml):
                  --   Trading: 'edge_decay', 'cost_sensitivity', 'regime_dependent',
                  --            'overfitting', 'correlation'
                  --   ML: 'convergence_failure', 'distribution_shift', 'overfitting'
                  --   SaaS: 'regression', 'performance_degradation', 'compatibility'
                  -- Validated at the application layer, not via CHECK constraint.
    failure_stage TEXT NOT NULL
                  CHECK (failure_stage IN ('research', 'design', 'implementation',
                                           'validation', 'deployment', 'monitoring')),
    what_failed   TEXT NOT NULL,
    why_it_failed TEXT NOT NULL,
    evidence      TEXT,                          -- JSON: supporting data
    lesson        TEXT NOT NULL,                 -- What to learn
    avoid_repeating TEXT,                        -- Specific negative constraint for future agents
    severity      TEXT DEFAULT 'medium'
                  CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    expires_at    TEXT,                          -- Time-based decay: when this lesson expires
    created_by    TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (project_id) REFERENCES projects(project_id),
    FOREIGN KEY (created_by) REFERENCES agents(agent_id)
);

-- ============================================================
-- CONFIDENCE CALIBRATION (per Research 02, Pattern 7)
-- Tracks predicted vs. actual outcomes to calibrate agent
-- confidence scores over time.
-- ============================================================
CREATE TABLE confidence_calibration (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    TEXT NOT NULL,
    agent_id      TEXT NOT NULL,
    output_type   TEXT NOT NULL,                  -- e.g., 'hypothesis', 'prediction', 'estimate'
    entity_id     TEXT NOT NULL,                  -- What was the prediction about
    reported_confidence REAL NOT NULL
                  CHECK (reported_confidence BETWEEN 0.0 AND 1.0),
    actual_outcome TEXT NOT NULL,                 -- 'success', 'failure', 'partial'
    outcome_metric REAL,                          -- Quantitative measure if available
    notes         TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (project_id) REFERENCES projects(project_id),
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);

-- ============================================================
-- KEY-VALUE STORE (for lightweight project-level state)
-- ============================================================
CREATE TABLE kv_store (
    project_id    TEXT NOT NULL,
    key           TEXT NOT NULL,
    value         TEXT NOT NULL,
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    PRIMARY KEY (project_id, key),
    FOREIGN KEY (project_id) REFERENCES projects(project_id)
);

-- ============================================================
-- INDEXES
-- ============================================================

-- Goals
CREATE INDEX idx_goals_project     ON goals(project_id, status);
CREATE INDEX idx_goals_parent      ON goals(parent_goal_id);
CREATE INDEX idx_goals_status      ON goals(status);
CREATE INDEX idx_goals_assigned    ON goals(assigned_to);

-- Tasks
CREATE INDEX idx_tasks_goal        ON tasks(goal_id);
CREATE INDEX idx_tasks_project     ON tasks(project_id, status);
CREATE INDEX idx_tasks_status      ON tasks(status);
CREATE INDEX idx_tasks_assigned    ON tasks(assigned_to, status);

-- Sessions
CREATE INDEX idx_sessions_agent    ON sessions(agent_id);
CREATE INDEX idx_sessions_task     ON sessions(task_id);
CREATE INDEX idx_sessions_status   ON sessions(status);

-- Artifacts
CREATE INDEX idx_artifacts_project ON artifacts(project_id);
CREATE INDEX idx_artifacts_task    ON artifacts(task_id);
CREATE INDEX idx_artifacts_goal    ON artifacts(goal_id);
CREATE INDEX idx_artifacts_type    ON artifacts(artifact_type);

-- Events (heavily queried for debugging/dashboards)
CREATE INDEX idx_events_entity     ON events(entity_type, entity_id);
CREATE INDEX idx_events_project    ON events(project_id, created_at);
CREATE INDEX idx_events_type       ON events(event_type);
CREATE INDEX idx_events_agent      ON events(agent_id);
CREATE INDEX idx_events_session    ON events(session_id);
CREATE INDEX idx_events_created    ON events(created_at);

-- Gates
CREATE INDEX idx_gates_project     ON gates(project_id);
CREATE INDEX idx_gates_entity_type ON gates(entity_type);

-- Failure Memory
CREATE INDEX idx_failures_project  ON failure_memory(project_id);
CREATE INDEX idx_failures_family   ON failure_memory(family_id);
CREATE INDEX idx_failures_source   ON failure_memory(source_type, source_id);
CREATE INDEX idx_failures_type     ON failure_memory(failure_type);
CREATE INDEX idx_failures_expires  ON failure_memory(expires_at);

-- Confidence Calibration
CREATE INDEX idx_calibration_agent ON confidence_calibration(agent_id);
CREATE INDEX idx_calibration_type  ON confidence_calibration(output_type);

-- ============================================================
-- TRIGGERS (append-only protection)
-- Per Research 06: append-only audit tables prevent tampering
-- ============================================================
CREATE TRIGGER IF NOT EXISTS prevent_event_delete
BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT, 'events table is append-only: DELETE is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS prevent_event_update
BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'events table is append-only: UPDATE is forbidden');
END;
```

### 4.3 Schema Design Decisions

**Why TEXT timestamps instead of TIMESTAMP type:** SQLite does not have a native TIMESTAMP type — it stores timestamps as TEXT, REAL, or INTEGER regardless of the declared type. Using ISO 8601 TEXT format (`strftime('%Y-%m-%dT%H:%M:%f', 'now')`) is explicit, human-readable, sortable, and avoids the confusion of SQLite's type affinity system. [HIGH] — This is established SQLite best practice, not a novel design decision.

**Why `version INTEGER` on mutable tables:** Optimistic locking. When agent A reads a goal with version=3, then agent B updates it (version becomes 4), agent A's subsequent update will fail because `WHERE version = 3` matches zero rows. The application layer detects this (rows_affected == 0) and retries with a fresh read. This is a well-established concurrency pattern that works well with SQLite's single-writer model. [HIGH]

**Why separate `goals` and `tasks` tables:** Goals are about *what* to achieve. Tasks are about *how* to achieve it. Goals have richer lifecycle semantics (acceptance criteria, stop conditions, confidence tracking, hierarchical decomposition). Tasks have simpler execution semantics (assigned to agent, in_progress, done). Merging them forces awkward overloading of fields. The HFT fund prototype (which inspired this design) already has a `tasks` table — this design adds `goals` as the layer above. [HIGH]

**Why `events` is separate from `activity_log`:** The HFT fund prototype has an `activity_log` table. The proposed `events` table is more structured: it explicitly tracks entity_type, entity_id, old_value, new_value. This makes it possible to reconstruct the full history of any entity by querying `WHERE entity_id = ?`. The activity_log pattern (free-text description) is useful for human-readable logging but not for programmatic state reconstruction. [MEDIUM]

**Why no `messages` table:** The blackboard architecture eliminates the need for direct agent-to-agent messaging. Agents communicate by mutating shared state: creating tasks, updating goal status, producing artifacts. The control unit (allocator agent) reads the blackboard and assigns work. This is simpler, more observable (all state is in one place), and avoids the ordering/delivery guarantees that messaging systems require. [HIGH]

---

## 5. Project Configuration Model

### 5.1 Approach: Declarative JSON Gates + Project Config [HIGH]

Project-specific rules are expressed in two places:

1. **`projects.config`** — A JSON blob with domain-specific settings (symbols, risk parameters, fee structures, etc.)
2. **`gates` table** — Declarative acceptance checks that guard lifecycle transitions

This avoids both extremes:
- **Too rigid:** Hardcoding rules in application code (cannot change without redeployment)
- **Too flexible:** A full DSL or plugin system (over-engineered for the current need)

### 5.2 Gate Definition Format

**Example: SaaS deployment promotion gate**

```json
{
  "conditions": [
    {"field": "test_coverage_pct", "op": ">=", "value": 80, "source": "artifact_metadata"},
    {"field": "p95_latency_ms", "op": "<=", "value": 200, "source": "artifact_metadata"},
    {"field": "critical_bugs", "op": "==", "value": 0, "source": "artifact_metadata"}
  ],
  "logic": "AND",
  "on_fail": "reject_with_feedback",
  "on_pass": "promote"
}
```

**Example: Trading strategy promotion gate (domain-specific)**

```json
{
  "conditions": [
    {"field": "sharpe_ratio", "op": ">=", "value": 1.5, "source": "domain_table:backtest_runs"},
    {"field": "max_drawdown_pct", "op": "<=", "value": 0.15, "source": "domain_table:backtest_runs"},
    {"field": "total_trades", "op": ">=", "value": 100, "source": "domain_table:backtest_runs"},
    {"field": "profit_factor", "op": ">", "value": 1.3, "source": "domain_table:backtest_runs"}
  ],
  "logic": "AND",
  "on_fail": "reject_with_feedback",
  "on_pass": "promote"
}
```

**Supported operators:** `>=`, `<=`, `>`, `<`, `==`, `!=`, `in`, `not_in`, `between`, `regex`

**Source resolution:** The `source` field tells the gate evaluator where to find the value. Common sources:
- `artifact_metadata` — extract from the artifact's JSON metadata
- `kv_store` — look up in the project key-value store
- `goal_field` — read directly from the goal record
- `domain_table:<table_name>` — query a project-specific domain table (declared in `project.yaml`)

### 5.3 Example Project Configurations

The `projects.config` JSON blob is fully domain-specific. Here are examples across different project types:

**SaaS Application:**
```json
{
  "domain": "saas",
  "environments": ["development", "staging", "production"],
  "deployment": {
    "provider": "aws",
    "min_test_coverage_pct": 80,
    "max_p95_latency_ms": 200
  },
  "quality": {
    "require_review": true,
    "max_open_critical_bugs": 0
  }
}
```

**ML Research:**
```json
{
  "domain": "ml_research",
  "compute": {
    "gpu_type": "A100",
    "max_gpu_hours_per_experiment": 24
  },
  "experiments": {
    "baseline_accuracy": 0.92,
    "target_accuracy": 0.95,
    "max_concurrent_runs": 4
  }
}
```

**Trading Fund (domain-specific):**
```json
{
  "domain": "crypto_hedge_fund",
  "initial_capital": 100000.0,
  "currency": "USDT",
  "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
  "risk": {
    "max_position_pct": 0.05,
    "max_drawdown_pct": 0.10,
    "max_exposure_pct": 0.80
  },
  "backtest": {
    "min_trades": 100,
    "min_sharpe": 1.5,
    "max_drawdown_pct": 0.15
  }
}
```

### 5.4 Alternatives Considered and Rejected

**Python plugin system (callable gates):** More powerful but introduces code execution in the data layer, making the system harder to inspect, version, and debug. Declarative JSON covers 90%+ of gate use cases. For the remaining 10%, a `gate_type: 'custom'` with a Python function reference can be added later. [MEDIUM]

**Full DSL (domain-specific language):** Massively over-engineered. Writing a parser, interpreter, and debugger for a custom language is months of work that does not add proportional value. JSON with a fixed operator set is "good enough" and universally understood. [HIGH]

**YAML config files only:** Some projects use YAML for all configuration (e.g., the HFT fund prototype uses `config/settings.yaml`). This works for static configuration but does not support per-entity gate checks (e.g., different promotion criteria for different goal types). The gates table provides entity-level granularity. The YAML file remains useful for deployment-level config (hosts, ports, API keys) that does not belong in the agent DB. [HIGH]

---

## 6. Artifact System

### 6.1 Hybrid: Filesystem Storage + Database Tracking [HIGH]

Artifacts are stored as **files on the filesystem** and tracked by **metadata rows in the database**.

**Why not store content in the database:**
- Artifact files can be large (parquet datasets, chart images, multi-page reports)
- SQLite BLOB performance degrades for items larger than approximately 100KB (this is documented SQLite guidance: items smaller than ~100KB are faster in SQLite, larger items are faster on filesystem) [NEEDS_VALIDATION — this threshold was from older SQLite documentation; the exact crossover point may have shifted]
- Filesystem storage integrates naturally with git version control
- Agents (especially Claude Code) already work natively with files

**Why not filesystem only:**
- Need to query artifacts by type, producing agent, associated task/goal
- Need to track versions and lineage (which artifact replaced which)
- Need to verify integrity (checksums)

### 6.2 Directory Convention

```
{project_root}/
  artifacts/
    research/         # Research briefs, hypotheses, literature reviews
    designs/          # Design specs, architecture docs
    validations/      # Test results, validation reports
    code/             # Implementation files (if not in src/)
    data/             # Processed datasets, features
    reviews/          # Review documents, audit reports
    {domain}/         # Domain-specific subdirs (declared in project.yaml)
                      #   e.g., backtests/, risk_reports/ (trading)
                      #   e.g., experiments/, model_runs/ (ML research)
                      #   e.g., deployments/, incidents/ (SaaS)
```

The `file_path` column in the `artifacts` table stores the path relative to the project's artifact root. This makes the system portable — moving the project directory does not break artifact references.

### 6.3 Versioning

Artifacts are **append-only with lineage tracking**. When an agent produces a new version of an artifact, it creates a new row with `parent_artifact_id` pointing to the previous version and `version_num` incremented. The old file is never overwritten — a new file is created (e.g., `research_brief_v2.md`). This provides full audit trail and rollback capability.

**Why not git-based versioning:** Git is excellent for source code but heavyweight for operational artifacts that change frequently. The database provides faster queries ("show me all v2+ research briefs from this week") than git log parsing. However, the artifact directory *can* also be git-tracked for backup/collaboration purposes — the two systems are complementary, not competing. [MEDIUM]

---

## 7. Concurrency & Consistency Model

### 7.1 SQLite WAL Mode [HIGH]

**Established fact:** SQLite WAL (Write-Ahead Logging) mode allows concurrent readers and a single writer. Readers do not block the writer, and the writer does not block readers. However, only one write transaction can be active at any time — concurrent writers are serialized. This is a fundamental SQLite limitation, not a configuration issue.

**Verification:** This is confirmed by the [official SQLite WAL documentation](https://sqlite.org/wal.html) and is the most well-documented aspect of SQLite's concurrency model.

**Implication for our system:** With tens of concurrent agents (not thousands), the single-writer constraint is acceptable. Each write transaction should be short (update a status, insert an event, create a task). Long-running reads (dashboard queries, reporting) will not block writes.

### 7.2 Connection Configuration

Every connection to the database MUST apply these PRAGMAs:

```sql
PRAGMA journal_mode = WAL;           -- Enable WAL mode
PRAGMA busy_timeout = 5000;          -- Wait up to 5s for write lock
PRAGMA synchronous = NORMAL;         -- Durability vs. performance tradeoff
PRAGMA foreign_keys = ON;            -- Enforce referential integrity
PRAGMA cache_size = -64000;          -- 64MB page cache
```

**`busy_timeout = 5000`:** When a writer is active and another writer attempts to write, SQLite will retry for up to 5 seconds before returning SQLITE_BUSY. For our workload (agents writing small state updates), 5 seconds is generous. [HIGH]

**`synchronous = NORMAL`:** In WAL mode, NORMAL provides a good balance — transactions are durable against application crashes but not OS crashes. FULL would be safer but slower. Since this is an operational coordination database (not a system of record for external transactions), NORMAL is appropriate. [HIGH]

### 7.3 Write Transaction Pattern [HIGH]

All write operations MUST use `BEGIN IMMEDIATE` transactions:

```python
def update_task_status(db, task_id: str, new_status: str, version: int) -> bool:
    """Update task status with optimistic locking.

    Returns True if update succeeded, False if version conflict.
    """
    with db:
        db.execute("BEGIN IMMEDIATE")
        cursor = db.execute(
            """UPDATE tasks
               SET status = ?, version = version + 1,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now')
               WHERE task_id = ? AND version = ?""",
            (new_status, task_id, version)
        )
        if cursor.rowcount == 0:
            db.execute("ROLLBACK")
            return False
        # Also insert an event
        db.execute(
            """INSERT INTO events (event_id, project_id, entity_type, entity_id,
                                   event_type, old_value, new_value)
               VALUES (?, ?, 'task', ?, 'status_changed', ?, ?)""",
            (generate_ulid('evt'), project_id, task_id,
             json.dumps({"status": old_status}),
             json.dumps({"status": new_status}))
        )
        db.execute("COMMIT")
        return True
```

**Why `BEGIN IMMEDIATE`:** (a) Established SQLite best practice. `BEGIN DEFERRED` (the default) can cause deadlocks when a read transaction attempts to upgrade to a write transaction while another connection holds a read lock. `BEGIN IMMEDIATE` acquires the write lock upfront, which triggers the `busy_timeout` retry loop immediately rather than failing with a deadlock. As [Bert Hubert documents](https://berthub.eu/articles/posts/a-brief-post-on-sqlite3-database-locked-despite-timeout/): "If you are seeing SQLITE_BUSY errors despite setting a busy timeout, you should use BEGIN IMMEDIATE." The [SQLite forum confirms](https://sqlite.org/forum/forumpost/04ed1d235b) that IMMEDIATE transactions use a different lock type that allows concurrent readers while blocking only other writers, and critically ensures `busy_timeout` is respected. This is the single most impactful fix for SQLITE_BUSY errors in concurrent environments. [HIGH] [VERIFIED]

### 7.4 Optimistic Locking Protocol [HIGH]

1. **Read** the entity and its `version` field
2. **Process** (agent does its work — may take seconds to minutes)
3. **Write** with `WHERE version = {read_version}` and `SET version = version + 1`
4. **If rowcount == 0:** Another agent modified this entity. Re-read and retry (or escalate to allocator for conflict resolution)

This is a well-established concurrency control pattern. It works well when conflicts are rare — and in our system, conflicts *should* be rare because the allocator agent assigns tasks to specific agents, so two agents should rarely be modifying the same entity.

### 7.5 Event Sourcing: Considered and Partially Adopted [MEDIUM]

Full event sourcing (deriving all current state from replaying events) was considered and rejected for the primary state tables. Reasons:

- **Complexity:** Rebuilding current state from events requires projection logic, event ordering guarantees, and snapshot management. This adds significant complexity.
- **Query performance:** "What tasks are currently assigned to agent X?" is a simple query against the `tasks` table but requires scanning/projecting all task events in an event-sourced system.
- **SQLite fit:** Event sourcing systems typically use databases optimized for append-heavy workloads with good range query performance. SQLite can do this but it is not its sweet spot.

**What we adopted:** The `events` table provides the audit trail benefits of event sourcing (full history, reproducibility) without the complexity of deriving current state from events. The mutable state tables are the source of truth; the events table is a supplementary record. This is sometimes called "event logging" as distinct from "event sourcing". [MEDIUM]

### 7.6 What About Multiple Machines? [MEDIUM]

**Current assumption:** All agents run on the same machine and access the same SQLite file. This is sufficient for the first deployment (one developer machine or server running multiple Claude Code / Codex instances).

**Established fact:** SQLite WAL mode does not work over network filesystems. All processes must access the database file on a local filesystem.

**Future scaling path:** If the system needs to run across multiple machines, the options are:
1. **Turso** — SQLite-compatible distributed database. Turso has announced concurrent writes achieving up to 4x write throughput over standard SQLite, removing SQLITE_BUSY errors via an MVCC implementation. [NEEDS_VALIDATION — Turso concurrent writes was in tech preview as of 2025; verify production readiness before adopting.]
2. **PostgreSQL migration** — The schema is designed to be portable. TEXT primary keys, standard SQL types, and JSON columns all translate directly to PostgreSQL. This is the safest long-term path if true multi-node scaling is needed.
3. **HTTP API wrapper** — Wrap the SQLite database in a thin HTTP API (FastAPI) that serializes all writes through a single server process. Agents connect via HTTP instead of direct file access. Per Research 06, this is Phase 2 of the permission enforcement roadmap and serves double duty as a scaling mechanism.

**Note on SQLite BEGIN CONCURRENT:** SQLite has an experimental `BEGIN CONCURRENT` extension that allows non-conflicting writes to partially overlap in WAL mode. However, conflict detection is at the page level (not row level), so colocated rows can still conflict. This feature is only available in a special branch and is NOT part of mainline SQLite as of March 2026. [VERIFIED per sqlite.org documentation.] Do not depend on it for production.

Option 3 is the most likely near-term path if multi-machine support is needed. [MEDIUM]

---

## 8. Identity System

### 8.1 Prefixed ULIDs [HIGH]

Every entity is identified by a **prefixed ULID**: a human-readable prefix followed by an underscore followed by a 26-character ULID.

| Entity | Prefix | Example |
|--------|--------|---------|
| Project | `proj_` | `proj_01JARQ5N5E5G4R3K16YPMB3GVH` |
| Goal | `goal_` | `goal_01JARQ5P2M4H7T8N22XQMC4DVK` |
| Task | `task_` | `task_01JARQ5Q9A3F6S7M33YRND5EWL` |
| Agent | `agent_` | `agent_01JARQ5R7B2E5R6L44ZSPE6FXM` |
| Session | `sess_` | `sess_01JARQ5S5C1D4Q5K55ATQF7GYN` |
| Artifact | `artf_` | `artf_01JARQ5T3D0C3P4J66BURG8HZP` |
| Event | `evt_` | `evt_01JARQ5V1E9B2N3H77CVSH9JAQ` |
| Gate | `gate_` | `gate_01JARQ5W0F8A1M2G88DWTK0KBR` |

### 8.2 Why ULIDs Over Other Options

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **Auto-increment INTEGER** | Simple, compact, fast | Not globally unique, reveals ordering/count, requires DB coordination | Rejected |
| **UUID v4** | Globally unique, no coordination | Not sortable, poor index locality in B-trees, 36 chars with hyphens | Rejected |
| **UUID v7** | Time-sortable, globally unique | Newer standard, less library support than ULID | Viable alternative |
| **ULID** | Time-sortable, globally unique, 26 chars (compact), wide library support | Slightly more storage than integers | **Selected** |
| **CUID2** | Secure, collision-resistant | Not time-sortable | Rejected |

**Key advantages of ULID for this system:**
1. **No coordination needed:** Multiple agents can generate IDs independently without contacting the database. This eliminates a synchronization point. [HIGH]
2. **Time-sortable:** `SELECT * FROM events ORDER BY event_id` naturally returns events in chronological order. This is useful for debugging and dashboard display. [HIGH]
3. **Human-readable with prefix:** When debugging, `goal_01JARQ5P...` immediately tells you what kind of entity you are looking at. Without prefix, you would need to look up the ID in every table. [HIGH]
4. **Compact:** 26 characters vs UUID's 36 characters (with hyphens). In a system with millions of events, this adds up. [MEDIUM]

### 8.3 Generation

```python
import ulid

def generate_id(prefix: str) -> str:
    """Generate a prefixed ULID.

    Args:
        prefix: Entity type prefix (e.g., 'goal', 'task', 'evt')

    Returns:
        Prefixed ULID string, e.g., 'goal_01JARQ5P2M4H7T8N22XQMC4DVK'
    """
    return f"{prefix}_{ulid.new()}"
```

The `python-ulid` package provides ULID generation. Monotonicity within the same millisecond is handled by the ULID spec (random component is incremented). [HIGH]

---

## 9. Migration Path for Existing Projects (Brownfield Onboarding)

The Agent OS supports brownfield adoption: existing projects with their own database schemas can adopt the OS incrementally. The core schema is a superset that adds `projects`, `goals`, `sessions`, `artifacts`, `gates`, and `events` alongside existing tables.

### 9.1 General Migration Strategy [MEDIUM]

1. **Phase 1 -- Add new tables alongside existing ones.** Create core OS tables (`projects`, `goals`, `sessions`, `artifacts`, `gates`, `events`, `kv_store`) without modifying existing tables. Create a default project that wraps the current system.

2. **Phase 2 -- Bridge existing tasks to goals.** Create goals for existing logical groupings. Link existing tasks to these goals via `goal_id` foreign key.

3. **Phase 3 -- Classify domain tables.** Existing domain-specific tables (e.g., `strategies` and `backtest_runs` in a trading project, `experiments` and `model_runs` in an ML project, `deployments` and `feature_flags` in a SaaS project) become domain tables declared in `project.yaml`. They reference the core schema via `project_id` and `goal_id` foreign keys but retain their domain-specific columns and constraints.

4. **Phase 4 -- Deprecate replaced patterns.** Remove direct messaging tables (replaced by blackboard). Consolidate key-value state into `kv_store`. Update logging references to use `events`.

This phased approach means the system is never broken -- the old schema continues to work while the new schema is populated alongside it.

### 9.2 Example: HFT Fund Prototype Migration

The HFT fund prototype that inspired this design has tables for `agents`, `tasks`, `strategies`, `backtest_runs`, `research_hypotheses`, `paper_trades`, `fund_state`, `activity_log`, and `messages`. Its migration would move `strategies`, `backtest_runs`, `research_hypotheses`, and `paper_trades` into domain tables declared in `project.yaml`; replace `fund_state` with `kv_store`; replace `messages` with blackboard coordination; and bridge `activity_log` to `events`. This is documented as a reference implementation for brownfield adoption.

---

## 10. Open Questions

### 10.1 Goal Depth and Granularity [MEDIUM]

How deep should goal decomposition go in practice? The schema supports arbitrary depth, but the recommendation of 4 levels is based on intuition, not empirical data. Real-world usage may reveal that 3 levels is sufficient or that 5 is necessary for complex domains.

**Proposed resolution:** Start with 4 levels as a soft limit (enforced by allocator agent policy, not schema constraint) and adjust based on real usage patterns.

### 10.2 Event Table Growth [MEDIUM]

The events table is append-only and will grow indefinitely. For a system running continuously with tens of agents, this could reach millions of rows per month.

**Proposed resolution:** Implement periodic archival. Events older than N days are moved to an archive table or exported to parquet files. The main events table is kept lean for dashboard queries. A `retention_days` config in the project settings controls this.

### 10.3 Gate Evaluation Complexity [LOW]

The declarative JSON gate format handles simple comparisons well (coverage >= 80%, latency < 200ms). But some acceptance criteria are inherently complex ("the new model's predictions must not be correlated with the existing ensemble at r > 0.9", or "the deployment must not regress any p99 latency SLO"). How far should the declarative format stretch before falling back to custom Python evaluation?

**Proposed resolution:** Start with the simple operator set. Add a `gate_type: 'custom'` option that references a Python function by dotted path (e.g., `'myproject.gates.slo_regression_check'`). This is a pragmatic escape hatch, not a plugin system.

### 10.4 Multi-Project Isolation [LOW]

The schema supports multiple projects, but how isolated should they be? Can agents work across projects? Can goals in one project depend on goals in another?

**Proposed resolution:** Start with strict isolation (agents belong to one project, no cross-project dependencies). Revisit if a real use case emerges.

### 10.5 Acceptance Criteria Format [MEDIUM]

The `acceptance_criteria` JSON field needs a well-defined schema. Currently proposed as an array of condition objects similar to gates. But some acceptance criteria are qualitative ("the research brief must identify at least 3 falsifiable hypotheses") and resist machine checking.

**Proposed resolution:** Support both machine-checkable criteria (same format as gates) and human-review criteria (plain text with `"check_type": "human_review"`). The allocator agent or a human can mark human-review criteria as passed/failed.

### 10.6 ULID Library Choice [LOW]

Multiple Python ULID libraries exist (`python-ulid`, `ulid-py`, `ulid2`). Need to verify which is actively maintained and supports monotonic sorting within the same millisecond.

**Proposed resolution:** Evaluate `python-ulid` (most popular) and `ulid-py` before implementation. [NEEDS_VALIDATION]

### 10.7 Domain Tables vs. Pure Artifact Model [MEDIUM]

Should domain-specific entities (e.g., strategies/backtest_runs in trading, experiments/model_runs in ML, deployments/incidents in SaaS) live as dedicated tables or be modeled entirely through artifacts + metadata? Dedicated tables provide better query performance and schema enforcement. The pure artifact model is more flexible but loses type safety.

**Proposed resolution:** Keep dedicated domain tables. They reference the core schema (project_id, goal_id) but maintain their own domain-specific columns and constraints. The Agent OS core schema defines the "operating system" layer; domain tables are the "application" layer. This is analogous to how an OS provides processes and files while applications define their own data structures.

---

## Summary of Confidence Levels

| Decision | Confidence | Rationale |
|----------|------------|-----------|
| SQLite as sole operational store | [HIGH] | Proven at this scale, established pattern |
| WAL mode + busy_timeout + BEGIN IMMEDIATE | [HIGH] | Established SQLite best practices |
| Blackboard architecture (no messages) | [HIGH] | Supported by 50 years of AI systems research and recent LLM-agent studies |
| Prefixed ULIDs for identity | [HIGH] | Well-understood tradeoffs, strong fit for use case |
| Optimistic locking via version columns | [HIGH] | Established concurrency pattern |
| Separate goals and tasks tables | [HIGH] | Different lifecycle semantics justify separation |
| Declarative JSON gates | [HIGH] | Simple, inspectable, covers 90%+ of cases |
| Append-only events table | [MEDIUM] | Essential for debugging but growth management is an open question |
| Hybrid artifact system (files + DB metadata) | [HIGH] | Standard practice for document management |
| 4-level goal depth recommendation | [MEDIUM] | Reasonable starting point but needs empirical validation |
| Event logging (not full event sourcing) | [MEDIUM] | Pragmatic tradeoff -- full ES adds complexity without proportional benefit at this scale |
| Goal DAG (not tree) | [HIGH] | Real-world goals have multiple dependency relationships |
| No multi-machine support at launch | [MEDIUM] | Correct prioritization but limits future scale |

---

## Cross-References to Other Research Outputs

| Research | Relevance to Core Architecture |
|----------|-------------------------------|
| **02: AI-Native Coordination Patterns** | Blackboard architecture (Pattern 1) is the foundational coordination model for this schema. Fan-Out/Fan-In (Pattern 2) motivates the goal DAG structure. Typed Work Packets (Pattern 5) inform the acceptance_criteria and gate designs. Structured Failure Memory (Pattern 8) drives the `failure_memory` table. Confidence-Weighted Decisions (Pattern 7) drives the `confidence_calibration` table. |
| **06: Security, Permissions & Human Steering** | Permission enforcement layered on top of this schema. Table-level and row-level access control via `db_tool.py` wrapper. Capability tokens reference agent_id and task_id from core tables. Append-only trigger pattern for events table originates here. Escalation protocol uses events table for audit. |
| **08: Failure Modes, Resilience & Self-Healing** | Recovery protocols (RP1-RP6) operate on entities defined in this schema. Heartbeat detection uses `agents.last_heartbeat` and `sessions.status`. Partial write cleanup references artifact quarantine states. The `failure_memory` table is the persistent store for the structured failure records that RP3 and RP4 generate. |
| **04: Goal & Planning System** | Goal decomposition, acceptance criteria, and plan templates defined here are the structural foundation that the planning system operates on. The DAG structure, stop conditions, and depth recommendations are directly implemented in this schema. |

---

## Sources

### SQLite Documentation (Primary Technical References)
- [SQLite WAL Documentation](https://sqlite.org/wal.html) — Concurrent read/write behavior, single-writer limitation [VERIFIED]
- [SQLite Isolation](https://sqlite.org/isolation.html) — Transaction isolation levels
- [SQLite BEGIN CONCURRENT (experimental)](https://www.sqlite.org/src/doc/begin-concurrent/doc/begin_concurrent.md) — Multi-writer extension, NOT mainline as of 2026 [VERIFIED]
- [SQLite File Locking and Concurrency](https://sqlite.org/lockingv3.html) — Lock states, busy handling
- [SQLite JSON1 Functions](https://sqlite.org/json1.html) — json_extract, json_each, JSONB (3.45+) [VERIFIED]
- [SQLite Foreign Keys](https://sqlite.org/foreignkeys.html) — Must be enabled per connection via PRAGMA [VERIFIED]
- [SQLite Busy Timeout API](https://sqlite.org/c3ref/busy_timeout.html) — C API documentation

### Practical SQLite Concurrency Guides
- [Bert Hubert: SQLITE_BUSY Despite Timeout](https://berthub.eu/articles/posts/a-brief-post-on-sqlite3-database-locked-despite-timeout/) — Why BEGIN IMMEDIATE is essential [VERIFIED]
- [SkyPilot: Abusing SQLite to Handle Concurrency](https://blog.skypilot.co/abusing-sqlite-to-handle-concurrency/) — Production experience with concurrent agent access [VERIFIED]
- [SQLite on Rails: Improving Concurrency](https://fractaledmind.com/2023/12/11/sqlite-on-rails-improving-concurrency/) — WAL mode configuration guidance
- [Oldmoe: Concurrent Write Transactions in SQLite](https://oldmoe.blog/2024/07/08/the-write-stuff-concurrent-write-transactions-in-sqlite/) — Deep dive on write concurrency
- [Fixing Claude Code Concurrent Sessions with SQLite WAL](https://dev.to/daichikudo/fixing-claude-codes-concurrent-session-problem-implementing-memory-mcp-with-sqlite-wal-mode-o7k)

### Optimistic Locking
- [Optimistic Locking with Version Column (Medium)](https://medium.com/@sumit-s/optimistic-locking-concurrency-control-with-a-version-column-2e3db2a8120d) — Pattern description
- [Optimistic Locking in Peewee ORM](https://charlesleifer.com/blog/optimistic-locking-in-peewee-orm/) — SQLite implementation
- [Optimistic Locking in SQLAlchemy (2026)](https://oneuptime.com/blog/post/2026-01-25-optimistic-locking-sqlalchemy/view) — Modern implementation

### Identity and Primary Key Design
- [ULID Specification](https://github.com/ulid/spec) — Canonical ULID spec
- [Identity Crisis: Sequence vs UUID (Brandur)](https://brandur.org/nanoglyphs/026-ids) — Stripe's prefixed ID philosophy [VERIFIED]
- [UUID vs ULID vs Integer IDs (ByteAether)](https://byteaether.github.io/2025/uuid-vs-ulid-vs-integer-ids-a-technical-guide-for-modern-systems/) — Comprehensive comparison
- [ULIDs and Primary Keys (Dave Allie)](https://blog.daveallie.com/ulid-primary-keys/) — B-tree performance considerations

### Multi-Agent Architecture
- [Anthropic: How We Built Our Multi-Agent Research System](https://www.anthropic.com/engineering/multi-agent-research-system) — Lead + subagent architecture, 90.2% improvement [VERIFIED]
- [Claude Code Agent Teams Documentation](https://code.claude.com/docs/en/agent-teams) — Shared task board, inter-agent coordination
- [Anthropic Opus 4.6 Agent Teams (TechCrunch)](https://techcrunch.com/2026/02/05/anthropic-releases-opus-4-6-with-new-agent-teams/)
- [Exploring Advanced LLM Multi-Agent Systems Based on Blackboard Architecture (arxiv:2507.01701)](https://arxiv.org/html/2507.01701v1)
- [LLM-Based Multi-Agent Blackboard System (arxiv:2510.01285)](https://arxiv.org/abs/2510.01285)
- [Confluent: Four Design Patterns for Event-Driven Multi-Agent Systems](https://www.confluent.io/blog/event-driven-multi-agent-systems/)
- [Multi-Agent Systems: Shared Persistent State (Medium)](https://medium.com/@aiforhuman/multi-agent-systems-shared-persistent-state-bd33a1b5030f)
- [Blackboard System (Wikipedia)](https://en.wikipedia.org/wiki/Blackboard_system)

### Task Planning and Goal Decomposition
- [Hierarchical Task Network (Wikipedia)](https://en.wikipedia.org/wiki/Hierarchical_task_network) — HTN formalism supports DAG decomposition
- [LLM Agent Task Decomposition Strategies](https://apxml.com/courses/agentic-llm-memory-architectures/chapter-4-complex-planning-tool-integration/task-decomposition-strategies)
- [Directed Acyclic Graph (Wikipedia)](https://en.wikipedia.org/wiki/Directed_acyclic_graph) — DAG properties and applications

### Event Sourcing and State Management
- [Event-Driven vs State-Based Systems (Confluent)](https://developer.confluent.io/courses/event-sourcing/event-driven-vs-state-based/) — Comparison of approaches
- [Event Sourcing Pattern (Azure Architecture Center)](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing)

### Industry Context
- [Multi-Agent Frameworks Explained for Enterprise AI (2026)](https://www.adopt.ai/blog/multi-agent-frameworks) — 72% enterprise adoption of multi-agent architectures
- [AI Agents Becoming Operating Systems (Klizos, 2026)](https://klizos.com/ai-agents-are-becoming-operating-systems-in-2026/)
- [Agentic AI Roadmap 2026 (FrankX)](https://www.frankx.ai/blog/agentic-ai-roadmap-2026)
- [AI Agent Frameworks Compared 2026](https://openagents.org/blog/posts/2026-02-23-open-source-ai-agent-frameworks-compared)
- [GitHub: agent-blackboard](https://github.com/claudioed/agent-blackboard) — Multi-agent coordination via shared blackboard
