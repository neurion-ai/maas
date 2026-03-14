# Research 04: Hierarchical Goal & Planning System

**Date:** 2026-03-08
**Researcher:** Agent 04 (Goal & Planning System)
**Status:** Complete

---

## Executive Summary

An AI Agent Operating System needs a goal and planning layer that bridges the gap between high-level human intent ("build a profitable hedge fund") and atomic agent actions ("fetch 1h BTC/USDT OHLCV data for 2025-Q4"). This document defines the complete architecture for that layer: a goal data model, a state machine governing goal lifecycles, a decomposition strategy inspired by Hierarchical Task Networks (HTN) but adapted for LLM agents, a DAG-based dependency resolver, an adaptive replanning protocol with circuit breakers against infinite loops, and a reusable plan template system.

The central design thesis: **goals are structured data objects with machine-checkable acceptance criteria, organized in a DAG, decomposed by the allocator agent on-demand (not upfront), and subject to adaptive replanning bounded by explicit stop conditions.** This avoids two failure modes -- over-planning (spending tokens on plans that will change) and under-planning (agents flailing without direction).

Key distinctions from traditional project management:
- **Decomposition is lazy, not eager.** Goals are decomposed one level at a time, only when an agent is about to work on them. Deep upfront planning wastes tokens because plans change. [This is novel for AI agents.]
- **Acceptance criteria are executable predicates, not prose.** Every goal carries machine-checkable conditions (SQL queries, metric thresholds, file existence checks). [This is novel for AI agents -- traditional PM uses human-verified acceptance criteria.]
- **Replanning is automatic but bounded.** When a plan fails, the system replans -- but with a hard limit on replan attempts, token budget, and wall-clock time. [This is novel for AI agents -- traditional PM replans through human meetings.]
- **The DAG is dynamic, not static.** New nodes (goals, tasks) can be inserted at runtime as the system learns. [This is informed by DynTaskMAS (ICAPS 2025) and Microsoft CORPGEN (2026).]

What is NOT novel here: priority scoring, dependency graphs, and state machines are established project management concepts. The novelty is in their adaptation for autonomous LLM agents with bounded context windows, no persistent memory, and stochastic output.

---

## Goal Data Model

### Core Entity: `goal`

```sql
CREATE TABLE goals (
    goal_id         TEXT PRIMARY KEY,
    parent_goal_id  TEXT REFERENCES goals(goal_id),  -- NULL for top-level
    title           TEXT NOT NULL,
    description     TEXT,
    goal_type       TEXT NOT NULL CHECK(goal_type IN (
        'strategic', 'tactical', 'operational', 'task'
    )),
    status          TEXT NOT NULL DEFAULT 'proposed' CHECK(status IN (
        'proposed', 'approved', 'active', 'blocked',
        'completed', 'failed', 'abandoned'
    )),
    priority        REAL DEFAULT 0.5 CHECK(priority >= 0.0 AND priority <= 1.0),
    owner_agent_id  TEXT,
    created_by      TEXT NOT NULL,

    -- Acceptance criteria (machine-checkable)
    acceptance_criteria JSON NOT NULL DEFAULT '[]',
    -- Format: [{"type": "metric", "metric": "sharpe", "op": ">=", "value": 1.5},
    --          {"type": "sql", "query": "SELECT count(*) FROM ...", "op": ">=", "value": 100},
    --          {"type": "file_exists", "path": "agent_comms/artifacts/strategies/momentum_v1.json"},
    --          {"type": "human_approval", "approver": "hf_manager"}]

    -- Stop conditions (when to abandon pursuit)
    stop_conditions JSON NOT NULL DEFAULT '[]',
    -- Format: [{"type": "max_attempts", "value": 3},
    --          {"type": "max_tokens", "value": 500000},
    --          {"type": "max_wall_clock", "value": "2h"},
    --          {"type": "diminishing_returns", "metric": "sharpe", "min_improvement": 0.1}]

    -- Decomposition metadata
    decomposition_strategy TEXT CHECK(decomposition_strategy IN (
        'manual', 'allocator', 'template', 'collaborative'
    )),
    template_id     TEXT,  -- If decomposed from a plan template

    -- Tracking
    attempt_count   INTEGER DEFAULT 0,
    tokens_spent    INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    deadline        TIMESTAMP,

    -- Relationships
    depends_on      JSON DEFAULT '[]',  -- List of goal_ids that must complete first
    blocks          JSON DEFAULT '[]',  -- List of goal_ids that depend on this

    -- Failure context
    failure_reason  TEXT,
    replan_history  JSON DEFAULT '[]'
    -- Format: [{"attempt": 1, "plan": "...", "outcome": "failed", "reason": "..."},
    --          {"attempt": 2, "plan": "...", "outcome": "completed"}]
);
```

### Goal Type Hierarchy

The four-level hierarchy mirrors Microsoft CORPGEN's multi-horizon decomposition (Strategic/Tactical/Operational) but adds a `task` level for atomic agent work. CORPGEN demonstrated that decomposing corporate objectives across three temporal scales -- Strategic (monthly), Tactical (daily), and Operational (per-cycle) -- achieves up to 3.5x improvement over flat baselines. We adopt and extend this with a fourth level.

| Level | Type | Time Horizon | Example (Trading) | Example (SaaS) | Decomposed By |
|-------|------|-------------|-------------------|-----------------|---------------|
| 0 | `strategic` | Months-quarters | "Achieve 15% annualized return with Sharpe > 1.5" | "Reach 1000 paying users by Q3" | Human + Allocator |
| 1 | `tactical` | Days-weeks | "Research and deploy 3 uncorrelated alpha strategies" | "Build and launch user onboarding flow" | Allocator agent |
| 2 | `operational` | Hours-days | "Backtest momentum strategy on BTC/USDT 1h data" | "Implement email verification endpoint" | Allocator agent |
| 3 | `task` | Minutes-hours | "Fetch BTC/USDT 1h OHLCV for 2025-01 to 2026-01" | "Write unit tests for email validator" | Assigned agent (self-decompose if needed) |

**Design decision: four levels, no more.**

Going deeper than four levels creates decomposition overhead that exceeds the value of granularity. At the `task` level, the assigned agent should be able to complete the work within a single context window. If it cannot, the task is too large and should be split into sub-tasks at the same level -- but this is the agent's responsibility, not the planning system's.

**Trading domain example:**
```
Strategic: "Build profitable, risk-managed crypto fund"
  |-- Tactical: "Research momentum-based alpha strategies"
  |     |-- Operational: "Backtest MACD crossover on BTC/USDT"
  |     |     |-- Task: "Fetch BTC/USDT 1h data for 2024-2026"
  |     |     |-- Task: "Run backtest with default MACD params"
  |     |     +-- Task: "Run parameter sweep on fast/slow periods"
  |     +-- Operational: "Backtest RSI mean-reversion on ETH/USDT"
  |           |-- Task: "Fetch ETH/USDT 1h data for 2024-2026"
  |           +-- Task: "Run backtest with RSI(14) thresholds 30/70"
  +-- Tactical: "Implement portfolio risk management"
        +-- Operational: "Set up position sizing with Kelly criterion"
              |-- Task: "Implement Kelly fraction calculator"
              +-- Task: "Integrate with execution engine"
```

**Software development domain example:**
```
Strategic: "Launch MVP SaaS product by Q2 2026"
  |-- Tactical: "Build user authentication system"
  |     |-- Operational: "Implement OAuth2 login flow"
  |     |     |-- Task: "Set up NextAuth.js with Google provider"
  |     |     |-- Task: "Create user table in PostgreSQL"
  |     |     +-- Task: "Write integration tests for login flow"
  |     +-- Operational: "Implement role-based access control"
  |           |-- Task: "Define role enum and permissions table"
  |           +-- Task: "Write middleware for route protection"
  +-- Tactical: "Build billing and subscription system"
        +-- Operational: "Integrate Stripe for payments"
              |-- Task: "Implement Stripe webhook handler"
              +-- Task: "Create subscription management UI"
```

### Relationships Between Goals

Goals relate to each other in three ways:

1. **Parent-child** (decomposition): A tactical goal is decomposed from a strategic goal. Stored via `parent_goal_id`.
2. **Dependency** (ordering): Goal B depends on Goal A completing first. Stored via `depends_on` JSON array.
3. **Blocking** (inverse dependency): Goal A blocks Goal B. Stored via `blocks` JSON array (maintained for query convenience; derived from `depends_on`).

[FRAGILE] **Cross-level dependencies.** A task in one tactical branch may depend on an operational goal in another branch (e.g., "backtest momentum strategy" depends on "implement data fetcher" from the infrastructure branch). These cross-cutting dependencies are the hardest to manage and the most common source of planning errors in practice. The system must support them but should flag them for allocator review whenever they are created.

---

## Goal State Machine

### States and Transitions

```
proposed ---> approved ---> active ---> completed
                |             |
                |             |---> blocked ---> active (when unblocked)
                |             |
                |             |---> failed ---> active (if replanned)
                |             |                +---> abandoned (if stop condition hit)
                |             |
                |             +---> abandoned
                |
                +---> abandoned (rejected before activation)
```

### State Definitions

| State | Meaning | Entry Condition | Exit Condition |
|-------|---------|----------------|---------------|
| `proposed` | Goal has been suggested but not yet vetted | Any agent or human creates it | Allocator reviews and scores it |
| `approved` | Goal is accepted and queued for work | Allocator scores composite >= 5.5 (or human approves) | Allocator assigns it to an agent |
| `active` | An agent is currently working on this goal | Agent available and assigned | Agent completes, fails, or gets blocked |
| `blocked` | Goal cannot proceed because a dependency is unmet | System detects unsatisfied dependency | All blocking dependencies resolve to `completed` |
| `completed` | All acceptance criteria are met | Automated criteria check passes | Cannot be exited normally (human-only reopen) |
| `failed` | The current attempt did not meet acceptance criteria | Agent reports failure OR criteria check fails OR stop condition fires | Allocator creates a replan or abandons |
| `abandoned` | Goal will not be pursued further | Max replans exceeded, or allocator/human decides to give up | Human only (reopen) |

### Transition Triggers

| Transition | Trigger | Automated? | Required Data |
|-----------|---------|-----------|--------------|
| proposed -> approved | Allocator reviews: composite score >= threshold | Yes (with human override) | Priority score computed |
| proposed -> abandoned | Allocator rejects: score < threshold, or human vetoes | Yes or manual | Rejection reason logged |
| approved -> active | Agent assigned and begins execution | Yes | Agent availability confirmed |
| active -> completed | All acceptance criteria evaluate to true | Yes (machine-checked) | Criteria evaluation log |
| active -> blocked | Dependency monitor detects unmet dependency | Yes | Which dependency is blocking |
| active -> failed | Agent reports failure, criteria check fails, or stop condition triggers | Yes | Failure reason required |
| active -> abandoned | Human or allocator decides goal is no longer valuable | Manual or auto | Abandonment reason required |
| blocked -> active | All blocking dependencies resolve to `completed` | Yes | Dependencies re-checked |
| failed -> active | Allocator creates replan and reactivates | Yes (within limits) | replan_count < max_attempts |
| failed -> abandoned | Max replan attempts reached, or allocator gives up | Yes or manual | Stop condition log |

### Can Goals Be Re-opened? Split? Merged?

**Re-opened:** Yes, but only by a human. Use case: a completed goal's output is later found defective (e.g., a backtest passed but the strategy fails in paper trading, revealing a bug in the backtest). The human sets `status = 'active'` and resets the context. Autonomous agents cannot do this -- it would create instability in the dependency graph, because downstream goals may have already started work based on the "completed" status.

**Split:** Yes. A goal that turns out to be too large can be split into two or more sibling goals under the same parent. The allocator does this during decomposition or replanning. The original goal is marked `abandoned` with reason "split into [goal_id_1, goal_id_2]" and the new goals inherit its dependencies and parent. This is a common operation -- initial estimates of goal scope are frequently wrong.

**Trading example of split:** "Research momentum strategies" is operational but the allocator realizes it covers both trend-following and mean-reversion. Split into "Research trend-following momentum" and "Research mean-reversion momentum" -- each scoped enough for a single researcher agent.

**Software example of split:** "Build authentication system" is scoped as operational but turns out to encompass OAuth, session management, and password reset. Split into three separate operational goals.

**Merged:** Rarely, and only by the allocator. If two goals turn out to address the same problem, one is marked `abandoned` (reason: "merged into [goal_id]") and its tasks are re-parented to the surviving goal. [YAGNI_RISK] -- Merging is complex (re-parenting tasks, reconciling acceptance criteria, updating dependency pointers) and may not arise often enough to justify implementing up front. Start without it and add if needed.

---

## Decomposition Strategy

### Who Decomposes?

The **allocator agent** (in our hedge fund, the hf_manager) is the primary decomposer. This is a deliberate centralization choice.

**Why not let agents self-decompose?** Because decomposition requires knowledge of the full goal tree, available resources, and strategic priorities. Individual agents have scoped context -- they do not see the whole picture. Letting agents self-decompose leads to:
- Redundant sub-goals across branches (two agents independently decide they need to build a data fetcher)
- Inconsistent granularity (one agent decomposes into 3 tasks, another into 30)
- Priority inversion (an agent decomposes based on what is interesting, not what is important)

This finding is consistent with the broader multi-agent literature. Anthropic's multi-agent research system uses a lead agent that decomposes tasks for subagents; OpenAI Codex uses a coordinator that dispatches to parallel worktrees. In both cases, decomposition is centralized, execution is distributed.

**Exception: task-level self-decomposition.** An agent assigned a `task` goal that turns out to be too large may split it into sub-tasks. But it must write these sub-tasks to the blackboard, not just handle them internally. This keeps the dependency graph accurate and progress visible.

**Trading example:** The hf_manager reviews the fund state, sees that portfolio correlation is too high, and creates a tactical goal: "Research uncorrelated alpha strategies." It decomposes this into operational goals: "Investigate derivatives flow signals," "Investigate cross-exchange arbitrage," "Investigate on-chain regime detection." Each is assigned to a researcher agent. The researchers do NOT further decompose -- they execute and produce artifacts.

**Software development example:** The allocator reviews the product roadmap, sees that user retention is low, and creates a tactical goal: "Build user onboarding flow." It decomposes into: "Design onboarding UX wireframes," "Implement onboarding API endpoints," "Write onboarding analytics events." Each goes to the appropriate specialist agent.

### When to Decompose: Lazy Decomposition

**Core principle: decompose one level at a time, just before work begins.**

This is the most important design decision in the planning system. Traditional project management (and classical HTN planning) favors upfront decomposition -- break the whole problem down before starting. For AI agents, this is wasteful because:

1. **Plans change.** Research reveals new information. Backtests fail. Dependencies shift. Any plan made more than one cycle ahead is likely to be revised.
2. **Tokens are expensive.** Deep upfront decomposition consumes allocator tokens on speculation rather than execution. Anthropic's research found that token usage explains 80% of performance variance -- wasting tokens on speculative plans is a direct drag on quality.
3. **Context windows are limited.** The allocator cannot hold a full deep plan tree in context. Lazy decomposition keeps the working set small and focused.

**Protocol:**
1. At the start of each cycle, the allocator queries: `SELECT * FROM goals WHERE status = 'approved' AND goal_type IN ('strategic', 'tactical') ORDER BY priority DESC`
2. For the highest-priority goal, check: does it have child goals? If not, decompose it one level.
3. For child goals that are `approved` and ready for work, decompose them into tasks.
4. Assign tasks to agents and mark them `active`.
5. Do NOT decompose anything that is not yet approved or not yet needed.

[FRAGILE] **When lazy decomposition fails:** If a goal requires long-lead-time dependencies (e.g., "collect 6 months of historical data before backtesting"), lazy decomposition may discover this too late. Mitigation: the allocator should do a lightweight "look-ahead" scan when approving goals, flagging any with long-lead-time requirements. This is not full decomposition -- it is a quick check for known slow dependencies. In HTN planning terms, this is the difference between "total-order decomposition" (plan everything up front) and "partial-order decomposition" (plan enough to identify critical constraints, defer details).

### Leaf-Level Granularity: How Deep Should the Tree Go?

**Rule: A task is small enough when a single agent can complete it within one context window** (approximately 100K-200K tokens of total work, including reading context, reasoning, executing, and writing output). In practice:

- **Research tasks:** 1-2 hours of agent time, producing one research brief or hypothesis
- **Implementation tasks:** One function, one module, or one test file
- **Backtest tasks:** One strategy on one symbol on one timeframe
- **Data tasks:** One data fetch, one transformation, one validation

If a task requires more context than fits in a single agent invocation, it should be split. This aligns with Anthropic's finding that distributing tokens across multiple focused agents outperforms concentrating them in a single overloaded agent by ~90%.

**Trading example -- too coarse:** "Backtest all momentum strategies on all symbols" -- this requires holding multiple strategies and multiple datasets simultaneously. Split by strategy and symbol.

**Trading example -- too fine:** "Set the MACD fast period to 12" -- this is a parameter, not a task. It is part of "Run backtest with MACD parameters."

**Software example -- too coarse:** "Build the entire API layer" -- this is an operational goal, not a task. Split by endpoint group.

**Software example -- too fine:** "Add a newline at end of file" -- this is a code formatting detail, not a task.

---

## Acceptance Criteria & Stop Conditions

### Acceptance Criteria Format

Every goal carries an `acceptance_criteria` JSON array. Each criterion is an executable predicate -- not prose, not a hope, not a vague intention. The system evaluates all criteria programmatically when an agent reports completion, and the goal transitions to `completed` only if ALL criteria pass.

**Supported criterion types:**

| Type | Description | Example | Verifier |
|------|------------|---------|----------|
| `metric` | Numeric metric against threshold | `{"type":"metric","metric":"sharpe","op":">=","value":1.5}` | Query backtest_runs table |
| `sql` | Arbitrary SQL returns expected result | `{"type":"sql","query":"SELECT count(*) FROM paper_trades WHERE strategy_id='macd_v1'","op":">=","value":100}` | Execute against fund.db |
| `file_exists` | Artifact file was produced | `{"type":"file_exists","path":"agent_comms/artifacts/strategies/macd_v1.json"}` | os.path.exists() |
| `schema_valid` | Output matches JSON schema | `{"type":"schema_valid","path":"...","schema":"strategy_spec_v1"}` | jsonschema.validate() |
| `test_passes` | Unit/integration tests pass | `{"type":"test_passes","command":"uv run pytest tests/unit/test_macd.py"}` | Exit code == 0 |
| `lint_clean` | Code passes linting | `{"type":"lint_clean","command":"uv run ruff check src/hft/strategy/implementations/macd.py"}` | Exit code == 0 |
| `human_approval` | Requires human sign-off | `{"type":"human_approval","approver":"hf_manager"}` | Manual flag in DB |
| `composite` | Multiple criteria combined | `{"type":"composite","op":"AND","criteria":[...]}` | Recursive evaluation |

**Trading domain example -- acceptance criteria for "Backtest MACD strategy":**
```json
[
  {"type": "metric", "source": "backtest_runs", "strategy_id": "macd_v1",
   "metric": "sharpe_ratio", "op": ">=", "value": 1.5},
  {"type": "metric", "source": "backtest_runs", "strategy_id": "macd_v1",
   "metric": "max_drawdown", "op": ">=", "value": -0.15},
  {"type": "metric", "source": "backtest_runs", "strategy_id": "macd_v1",
   "metric": "trade_count", "op": ">=", "value": 100},
  {"type": "metric", "source": "backtest_runs", "strategy_id": "macd_v1",
   "metric": "profit_factor", "op": ">=", "value": 1.3}
]
```

**Software development domain example -- acceptance criteria for "Implement OAuth2 login":**
```json
[
  {"type": "test_passes", "command": "uv run pytest tests/integration/test_oauth.py"},
  {"type": "lint_clean", "command": "uv run ruff check src/auth/oauth.py"},
  {"type": "file_exists", "path": "src/auth/oauth.py"},
  {"type": "schema_valid", "path": "openapi.json", "schema": "openapi_3.1"}
]
```

### The Hard Problem: Acceptance Criteria for Creative and Research Tasks

[FRAGILE] How do you machine-check "did the researcher produce a good hypothesis"? You cannot fully. This is a genuinely hard unsolved problem. Options, in order of reliability:

1. **Structural checks** (did the output have the right format, with hypothesis/evidence/confidence fields populated?) -- Machine-checkable, but only checks form, not substance. A beautifully formatted garbage hypothesis passes this check.
2. **Novelty check via failure memory** (is this hypothesis meaningfully different from previously rejected ones?) -- Partially machine-checkable via embedding similarity against the failure_memory table. Catches the most obvious repeats but not subtle repackaging.
3. **Allocator review** (the manager agent reads the hypothesis and scores it on Novelty/Feasibility/Edge) -- This is subjective and non-deterministic. Two runs of the allocator may score the same hypothesis differently. But it is the best available option for judging research quality.
4. **Downstream validation** (accept provisionally; validate by whether the strategy derived from the hypothesis passes backtest) -- Most reliable signal but introduces long feedback loops. A bad hypothesis wastes a full design-implement-backtest cycle before being caught.

**Recommended approach:** Use structural checks (1) as a mandatory gate, novelty checks (2) as a warning, and allocator review (3) as the primary decision point. Accept that research quality cannot be fully automated. Build the pipeline to tolerate some false positives -- bad hypotheses that pass research review will be caught at the backtest stage. The cost of a false positive (one wasted backtest cycle) is acceptable; the cost of being too strict at the research gate (missing genuine alpha) is not.

### Stop Conditions

Stop conditions prevent the system from pursuing a goal indefinitely. They are the "circuit breakers" of the planning system. Without them, a failing goal can consume unlimited tokens and wall-clock time in a replan loop.

**Supported stop condition types:**

| Type | Description | Default | Example |
|------|------------|---------|---------|
| `max_attempts` | Max number of replan-and-retry cycles | 3 | Strategy fails backtest 3 times -> abandon |
| `max_tokens` | Token budget ceiling for all work on this goal | 500,000 | Research burns 500K tokens without viable output -> abandon |
| `max_wall_clock` | Maximum elapsed wall-clock time | 4h operational, 1w tactical | Backtest runs for 4 hours without completing -> investigate |
| `diminishing_returns` | Improvement falls below threshold between attempts | 0.1 (metric-specific) | Replan #2: Sharpe 1.1, Replan #3: Sharpe 1.15 (only 0.05 delta) -> abandon |
| `progress_stall` | No meaningful output for a duration | 30 min for tasks, 2h for operational | Agent produces no artifacts for 2 hours -> escalate |

[YAGNI_RISK] `cost_benefit` stop condition (estimated remaining cost exceeds estimated remaining value). Appealing in theory but requires accurate cost and value estimation, both of which are hard to compute for AI agent work. Defer unless experience shows it is needed.

**When a stop condition fires:**
1. The goal transitions to `failed` (if mid-execution) or stays `failed` (if post-attempt).
2. If `attempt_count >= max_attempts`, the goal transitions to `abandoned`.
3. A structured failure record is written per Research 08's failure memory schema.
4. The allocator is notified to consider whether the parent goal needs replanning.
5. Dependent goals are evaluated -- they may need to be blocked or abandoned via the chain-stuck detector.

**Trading example -- stop conditions in action:**
- Attempt 1: MACD(12,26) on BTC/USDT 1h. Sharpe 0.8 (below 1.5 threshold). Fail reason: "Signal too noisy on 1h bars."
- Attempt 2 (replanned: different timeframe): MACD(12,26) on BTC/USDT 4h. Sharpe 1.1. Fail reason: "Insufficient trades (45 < 100 minimum)."
- Attempt 3 (replanned: intermediate timeframe): MACD(12,26) on BTC/USDT 2h. Sharpe 1.2. Still below 1.5.
- `max_attempts=3` fires. Goal abandoned. Failure record: "MACD crossover on BTC does not achieve Sharpe > 1.5 across tested timeframes and parameter ranges."
- Parent tactical goal "Research momentum strategies" creates a new operational goal exploring dual-momentum (absolute + relative), informed by the failure record.

**Software development example -- stop conditions in action:**
- Attempt 1: WebSocket real-time notification implementation. Integration tests fail (race condition in connection handling).
- Attempt 2 (replanned: switch to Server-Sent Events): Performance test shows 450ms latency (threshold: 200ms).
- Attempt 3 (replanned: SSE + Redis pub/sub for fan-out): Passes all criteria. (Stop condition did not need to fire because attempt 3 succeeded.)
- Had attempt 3 failed, the allocator would face a strategic question: is real-time notification essential, or can we fall back to polling? This is the kind of decision that should escalate to the parent goal level.

---

## Dependency Resolution

### DAG Structure

Goals and their dependencies form a Directed Acyclic Graph (DAG). The tree structure (parent-child via `parent_goal_id`) defines decomposition. The DAG structure (via `depends_on` JSON arrays) defines execution ordering across the tree. A goal in one branch can depend on a goal in another branch.

The system MUST enforce acyclicity. A goal cannot depend on itself, directly or transitively. Cycle detection runs whenever a new dependency is added.

**Dependency types:**

| Type | Description | Example (Trading) | Example (Software) |
|------|------------|-------------------|-------------------|
| `finish-to-start` | B cannot start until A completes | "Backtest strategy" depends on "Implement strategy" | "Deploy to staging" depends on "Pass integration tests" |
| `output-to-input` | B needs A's output artifact as input | "Design strategy spec" needs research hypothesis file | "Generate API docs" needs OpenAPI schema file |
| `resource` | B needs a resource A is using (mutex) | Two backtests competing for GPU (rare) | Two deploys targeting the same server |

[YAGNI_RISK] **`start-to-start` and `finish-to-finish` dependencies** (from traditional project scheduling) add complexity without clear value for AI agents. An agent either needs another goal's output or it does not. These dependency types exist to model partial overlap in human work (e.g., "testing can start before coding finishes if some modules are ready"). AI agents do not work this way -- they process complete inputs and produce complete outputs. Start with `finish-to-start` only.

### Dependency Resolution Algorithm

```python
def get_ready_goals(db) -> list[Goal]:
    """Return goals that are approved/active and have all dependencies met."""
    all_goals = db.query(
        "SELECT * FROM goals WHERE status IN ('approved', 'active')"
    )
    ready = []
    for goal in all_goals:
        deps = json.loads(goal.depends_on)
        if not deps:
            ready.append(goal)
            continue
        dep_statuses = db.query(
            "SELECT goal_id, status FROM goals WHERE goal_id IN (?)",
            deps
        )
        if all(d.status == 'completed' for d in dep_statuses):
            ready.append(goal)
        elif any(d.status in ('failed', 'abandoned') for d in dep_statuses):
            mark_blocked(goal,
                reason=f"Dependency {d.goal_id} is {d.status}")
    return sorted(ready, key=lambda g: g.priority, reverse=True)
```

This is intentionally simple. DynTaskMAS (ICAPS 2025) demonstrated that dynamic task graph scheduling achieves 21-33% execution time reduction with a DAG-based approach. Their key insight: the DAG generator should continuously update the graph as tasks complete, because new information may reveal that previously blocked tasks are now unblocked, or that new tasks are needed. Our `get_ready_goals` function is called at the start of each scheduling cycle, achieving the same dynamic re-evaluation.

### What Happens When a Dependency Fails?

This is a critical design question with three possible strategies:

1. **Block and wait** (default). The dependent goal is blocked until the dependency is resolved (replanned, reassigned, or manually completed). This is conservative -- it never makes a decision on behalf of the allocator.
2. **Cascade fail**. If a dependency fails, all dependents automatically fail too. This is aggressive -- a single failure can wipe out an entire branch. Appropriate only when the dependency is truly essential (no alternative exists).
3. **Conditional proceed**. The dependent goal proceeds with degraded inputs (e.g., cached data instead of fresh data, mock service instead of real API). Requires the goal to declare which dependencies are "hard" (must have) vs. "soft" (nice to have).

**Recommended approach:** Default to **block and wait**. The allocator reviews blocked goals each cycle and decides: replan the dependency, find an alternative, or cascade the failure. Automatic cascade is too aggressive for most scenarios.

[FRAGILE] **Deadlock / chain-stuck detection.** If Goal A is blocked by Goal B, which is blocked by Goal C, which is `abandoned`, the entire chain is permanently stuck. The dependency resolver must detect this:

```python
def detect_stuck_chains(db):
    """Find goals blocked by chains terminating in failed/abandoned goals."""
    blocked = db.query("SELECT * FROM goals WHERE status = 'blocked'")
    for goal in blocked:
        chain = trace_dependency_chain(goal)
        terminal = chain[-1]
        if terminal.status in ('failed', 'abandoned'):
            escalate(goal,
                reason=f"Blocked by chain ending at "
                       f"{terminal.goal_id} ({terminal.status})")
```

**Trading example:** "Paper trade momentum strategy" is blocked by "Backtest momentum strategy," which is blocked by "Implement momentum strategy," which failed because the coder could not resolve a dependency conflict in the strategy registry. The chain-stuck detector fires and escalates to the hf_manager, who can reassign the implementation, provide guidance, or abandon the tactical branch.

**Software example:** "Deploy to production" is blocked by "Pass security audit," which is blocked by "Fix XSS vulnerability," which has been abandoned after 3 attempts. The chain-stuck detector fires. The allocator decides whether to re-approach the XSS fix from a different angle, bring in a different agent, or defer the production deploy.

### DAG Complexity: How Much is Too Much?

[YAGNI_RISK] **Critical path analysis, resource leveling, and Gantt-chart-style scheduling** are standard project management techniques. For AI agents, they add implementation complexity without proportionate benefit because:

- AI agents have near-zero context-switching cost (unlike humans who need 20+ minutes to re-enter flow state)
- Agent "resources" are elastically scalable (spawn more agents)
- Cycle times are short (hours, not weeks), so critical path optimization saves minutes, not months
- The allocator's priority-weighted selection among ready goals is an adequate scheduler for our scale

**Recommended approach:** Simple topological sort for ordering, priority-weighted selection among ready goals, and nothing more elaborate. Do not build a full-blown project scheduler unless the system handles 100+ concurrent goals and scheduler quality becomes a bottleneck.

---

## Adaptive Replanning Protocol

### When Replanning Triggers

Replanning occurs when the current plan is no longer viable. The system detects this through several trigger mechanisms:

| Trigger | Detection Method | Example (Trading) | Example (Software) |
|---------|-----------------|-------------------|-------------------|
| Goal fails acceptance criteria | Automated criteria check | Backtest Sharpe = 0.8, threshold 1.5 | Integration tests fail |
| Agent reports impossibility | Agent writes failure artifact | "Data source does not provide required field" | "Library X is incompatible with Python 3.12" |
| Dependency fails | Dependency monitor | Required exchange API goes offline | Upstream microservice deprecated |
| New information invalidates plan | Allocator review / external signal | Market regime change makes strategy thesis invalid | Competitor launches identical feature |
| Stop condition fires (but parent still active) | Stop condition monitor | Third attempt on sub-goal fails | Budget for sprint exhausted |
| Resource constraint changes | Budget/cost tracker | Token budget for cycle exhausted | API rate limit hit |

### Who Replans?

The **allocator agent** (hf_manager) is the sole replanner. Individual agents do not replan -- they report failure and return control to the allocator.

**Why centralized replanning?**
- Replanning requires awareness of the full goal tree, available resources, and strategic priorities. An individual agent sees only its scoped task.
- Distributed replanning leads to conflicting plans (Agent A replans around Goal X while Agent B assumes Goal X will complete).
- The allocator has the authority to reallocate resources, change priorities, and abandon goals.
- This mirrors real organizational decision-making: IBM's research on AI agent planning notes that "replanning is most effective when a coordinator agent maintains a global view of the task state and can make trade-offs that individual task executors cannot."

**Exception: tactical adaptation within a task.** An agent may try a different approach within the same goal scope without escalating. The distinction: if the goal and its acceptance criteria are unchanged but the method changes (different parameter, different data source), that is tactical adaptation and stays with the agent. If the goal itself needs to change (different target, different scope, different acceptance criteria), that is replanning and must go through the allocator.

### Replanning Protocol

```
1. DETECT: Goal transitions to 'failed' (criteria not met) or 'blocked'
   (dependency issue).

2. ANALYZE: Allocator reads:
   - The failed goal's failure_reason and replan_history
   - The failure memory table (past failures for this family/domain)
   - The parent goal's status and remaining child goals
   - Available token budget and wall-clock budget for this cycle

3. DECIDE (exactly one of):

   a. RETRY with modifications
      - Adjust parameters, timeframe, data source, or approach
      - Write new plan to replan_history
      - Increment attempt_count
      - Transition goal back to 'active'

   b. REPLACE with alternative
      - Abandon the current goal
      - Create a new sibling goal under the same parent
      - Different approach to achieve the parent's objective

   c. ESCALATE to parent
      - This sub-goal path is exhausted; the parent goal itself
        needs a new decomposition strategy
      - Mark current goal as 'abandoned'
      - Trigger replanning at the parent level

   d. ABANDON the branch
      - Mark current goal and all descendants as 'abandoned'
      - Write failure record to failure memory
      - Notify goals that depend on this one (they become 'blocked')

4. VALIDATE: Check that the replan does not violate:
   - Stop conditions (max_attempts not exceeded, token budget not blown)
   - Dependency graph acyclicity
   - Previously known failure patterns (the replan must not repeat a
     known-failed approach from failure memory)

5. EXECUTE: Assign the replanned work and resume
```

### Preventing Infinite Replanning Loops

This is the hardest problem in adaptive planning for AI agents. Without safeguards, the system enters a degenerate cycle: plan -> fail -> replan -> fail -> replan -> fail, burning tokens and wall-clock time without progress. Research on stopping conditions for multi-agent loops identifies five defense layers needed:

**Layer 1: Hard attempt limits (per goal)**
```python
if goal.attempt_count >= goal.stop_conditions.max_attempts:
    abandon(goal, reason="Max replan attempts exceeded")
    return
```
Simple, robust, impossible to circumvent. Default: 3 attempts. Configurable per goal.

**Layer 2: Token budget ceiling (per goal and per cycle)**
```python
if goal.tokens_spent >= goal.stop_conditions.max_tokens:
    abandon(goal, reason="Token budget exhausted")
    return
if cycle_tokens_spent >= cycle_token_budget:
    pause_all_non_critical_goals()
    return
```
Prevents runaway cost. Google's research on AI agent compute budgeting shows agents make better decisions when given explicit budgets rather than open-ended resources.

**Layer 3: Diminishing returns detection**
```python
if len(goal.replan_history) >= 2:
    prev_best = max(h['best_metric'] for h in goal.replan_history[:-1])
    curr_best = goal.replan_history[-1]['best_metric']
    improvement = curr_best - prev_best
    min_threshold = goal.stop_conditions.diminishing_returns.min_improvement
    if improvement < min_threshold:
        abandon(goal,
            reason=f"Diminishing returns: improvement {improvement:.3f} "
                   f"< threshold {min_threshold}")
        return
```
Catches the case where replans produce marginally better results but never reach the acceptance threshold.

**Layer 4: Similarity detection (anti-loop)**

The most subtle defense. If the replan is essentially the same as a previous attempt, the system is looping without making meaningful changes.

```python
def is_novel_replan(new_plan: str, history: list[dict]) -> bool:
    """Check that the new plan is meaningfully different from previous."""
    for prev in history:
        similarity = compute_similarity(new_plan, prev['plan'])
        if similarity > 0.85:
            return False
    return True

if not is_novel_replan(proposed_replan, goal.replan_history):
    abandon(goal,
        reason="Replan too similar to previous attempts (looping)")
    return
```

[FRAGILE] **Similarity detection relies on embedding comparison, which is imprecise.** A replan might be textually different but strategically identical (e.g., "try MACD(10,20)" vs. "try MACD(12,22)" -- different numbers, same approach). Mitigation: compare structured plan representations (parameter sets, approach categories, data sources used) not raw text. Require the allocator to categorize each replan's "approach type" and reject if the approach type repeats.

**Layer 5: Wall-clock timeout**

If a goal has been in the failed/blocked/replan cycle for longer than its `max_wall_clock` stop condition, force-abandon it regardless of attempt count. This catches degenerate situations where individual attempts are fast but the cumulative time is excessive.

**How these layers interact:** Layers are evaluated in order. The first one that fires terminates the goal. In practice, `max_attempts` (Layer 1) fires most often because it is the simplest and most common scenario. Diminishing returns (Layer 3) catches the subtle case of slow convergence. Similarity detection (Layer 4) catches true loops. The wall-clock timeout (Layer 5) is the safety net that catches everything else.

**Trading example of all layers working together:**
- Attempt 1: MACD(12,26) on BTC/USDT 1h. Sharpe 0.8. [Layer 1: 1/3]
- Allocator replans: different timeframe. [Layer 4: checks novelty -- new timeframe = novel]
- Attempt 2: MACD(12,26) on BTC/USDT 4h. Sharpe 1.1. [Layer 1: 2/3. Layer 3: improvement 0.3 > 0.1 threshold, OK]
- Allocator replans: intermediate timeframe. [Layer 4: new timeframe = novel]
- Attempt 3: MACD(12,26) on BTC/USDT 2h. Sharpe 1.2. [Layer 1: 3/3 -- FIRES]
- Goal abandoned. Failure record written. Parent replans.

---

## Priority & Resource Allocation

### Priority Scoring

Each goal has a `priority` score from 0.0 to 1.0 computed by the allocator using a weighted formula. The formula is adapted from the Eisenhower Matrix (urgency vs. importance) extended with AI-agent-specific factors (feasibility, cost efficiency, dependency fan-out).

```python
def compute_priority(goal, fund_state, goal_tree) -> float:
    weights = {
        'urgency':            0.25,  # How time-sensitive?
        'importance':         0.30,  # Contribution to strategic objective?
        'feasibility':        0.20,  # Evidence strength, past success rate?
        'cost_efficiency':    0.15,  # Expected value / expected token cost?
        'dependency_fan_out': 0.10,  # How many other goals does this unblock?
    }

    scores = {
        'urgency':            compute_urgency(goal),
        'importance':         compute_importance(goal, fund_state),
        'feasibility':        compute_feasibility(goal),
        'cost_efficiency':    compute_cost_efficiency(goal),
        'dependency_fan_out': compute_fan_out(goal, goal_tree),
    }

    return sum(weights[k] * scores[k] for k in weights)
```

**Component scoring details:**

- **Urgency** (0.25 weight): Based on deadline proximity and time-sensitivity of opportunity. A market-driven signal that decays has higher urgency than infrastructure work with no deadline. Score: `1.0 - (time_remaining / total_time_allowed)`, clamped to [0, 1].

- **Importance** (0.30 weight): Alignment with the strategic goal. Directly traced through the parent chain. A goal whose strategic parent is "achieve 15% return" and whose tactical parent is "deploy alpha strategies" gets high importance. A goal whose parent is "clean up log files" gets low importance.

- **Feasibility** (0.20 weight): Draws from the confidence/uncertainty annotations on upstream evidence (Research 02, Pattern 7). A goal based on a high-confidence hypothesis gets high feasibility. A goal based on a speculative hypothesis with weak evidence gets low feasibility. Also incorporates historical success rate: if 5 previous goals in this family all failed, feasibility is low.

- **Cost efficiency** (0.15 weight): Estimated value divided by estimated token cost. A quick backtest (low cost) with high potential (valuable strategy) scores well. A massive data collection effort (high cost) with uncertain payoff scores poorly. [FRAGILE] Both value and cost estimates are imprecise for novel goals. This component is most useful for comparing well-understood goal types (e.g., backtest A vs. backtest B).

- **Dependency fan-out** (0.10 weight): How many other goals are blocked waiting for this one? A goal that unblocks 5 downstream goals gets higher priority than one that unblocks 0. This prevents bottleneck goals from languishing in the queue.

**Priority scoring examples:**

| Goal | Urgency | Importance | Feasibility | Cost Eff. | Fan-out | Total |
|------|---------|-----------|-------------|-----------|---------|-------|
| (Trading) Monitor open position risk | 0.95 | 0.90 | 0.95 | 0.80 | 0.20 | **0.85** |
| (Trading) Backtest new strategy | 0.40 | 0.70 | 0.60 | 0.70 | 0.50 | **0.58** |
| (Trading) Research new alpha family | 0.30 | 0.80 | 0.40 | 0.50 | 0.30 | **0.49** |
| (Software) Fix production crash | 0.95 | 0.95 | 0.85 | 0.90 | 0.60 | **0.90** |
| (Software) Refactor auth module | 0.20 | 0.50 | 0.80 | 0.40 | 0.20 | **0.42** |
| (Software) Research new framework | 0.10 | 0.30 | 0.30 | 0.20 | 0.00 | **0.21** |

### Agent Assignment

The allocator assigns agents to goals based on:

1. **Role match** (primary filter): Does the agent's role (researcher, quant, coder, tester, risk_monitor) match the goal type?
2. **Availability**: Is there an idle agent of this role? If not, wait or spawn a new one.
3. **Load balancing**: Distribute work evenly to prevent bottlenecks.

[YAGNI_RISK] **Context affinity** (assigning to an agent that previously worked on related goals because it has "warm context"). This optimization matters only if agent context persists across invocations. In our current architecture (spawn-per-task), agents start fresh each time. Context affinity is irrelevant until we implement persistent agent sessions. Defer.

**In practice for our system:** Since we spawn one agent per task and agents do not persist between tasks, assignment reduces to: pick the right role, spawn the agent, give it the scoped goal context from the blackboard. This is dramatically simpler than resource scheduling in traditional PM. It is also one of the key advantages of AI agents over human teams -- spawning a new agent has near-zero marginal cost compared to hiring, onboarding, and managing a human.

---

## Progress Tracking

### How Progress is Measured

Progress measurement depends on goal type. There is no universal "percentage complete" that works for all goals.

| Goal Type | Progress Signal | Measurement Method | Dashboard Display |
|-----------|----------------|-------------------|-------------------|
| `strategic` | Child goal completion ratio | N completed / M total children (weighted) | Progress bar + child list |
| `tactical` | Child goal completion ratio | N completed / M total children (weighted) | Progress bar + child list |
| `operational` | Task completion + acceptance check results | Criteria checklist evaluation | Checklist with pass/fail/pending |
| `task` | Agent activity signals | Heartbeat, artifact writes, token spend rate | Status indicator (working/stalled/done) |

**For parent goals (strategic, tactical):** Progress = `sum(child_weight * child_progress) / sum(child_weight)`. Default child weight is 1.0 but can be overridden (e.g., risk management might weight 2x because it is more important than an individual strategy research task).

**For operational goals:** Display as a checklist of acceptance criteria, each marked pass/fail/pending. Progress = passed_criteria / total_criteria. This is meaningful because operational goals have concrete, enumerable criteria.

**For tasks:** Do NOT display percentage. Display status: `queued`, `agent_working`, `stalled`, `completed`, `failed`. If the agent has been working for longer than 2x the expected duration with no artifact output, flag as `stalled` for allocator attention.

### The Genuinely Hard Problem: Research and Creative Task Progress

This was flagged in the research prompt and remains an honest unsolved problem in both human project management and AI agent systems. METR's research on measuring AI ability to complete long tasks confirms that "task completion time serves as a proxy for difficulty, but does not predict intermediate progress."

Research progress does not correlate with time spent or tokens consumed. A researcher might spend 90% of their budget finding nothing, then produce a breakthrough in the final 10%. Conversely, a researcher might produce copious output early and then discover all of it is wrong.

**What we can measure (imperfect but useful):**
- **Time elapsed vs. time budget** (has the researcher used 40 of their 120 minutes?)
- **Artifacts produced** (0 hypotheses so far, expected 3-5 -- at least we know output is happening)
- **Token spend rate** (burning at 2x expected rate -- may indicate stuck-in-a-loop behavior)
- **Distinct approaches tried** (an agent that has explored 5 different angles is making cognitive progress even if none have panned out)
- **Last meaningful output** (wrote a draft 15 min ago vs. no artifact for 60 min)

**What we cannot measure:**
- Quality of insight
- Proximity to a breakthrough
- Whether the agent is "on the right track"

**Recommended approach:**
1. Do NOT display "percentage complete" for research goals. It is misleading and creates false confidence.
2. Display elapsed time, artifact count, and a stall indicator.
3. Require periodic checkpoint artifacts (every 30 minutes of wall-clock time) to prove the agent is making cognitive progress. These can be rough notes, partial hypotheses, or "approaches tried and rejected" logs.
4. Use time/budget-based stop conditions rather than progress milestones for research.

### Dashboard Representation

The goal tree maps naturally to a hierarchical dashboard:

```
[Strategic] Build profitable crypto fund                  55% ========------
  [Tactical] Research alpha strategies                   100% ============== DONE
    [Oper] Backtest MACD on BTC/USDT                     100% DONE
    [Oper] Backtest RSI mean-reversion on ETH/USDT       100% DONE
    [Oper] Backtest funding rate arb                      100% DONE
  [Tactical] Deploy to paper trading                      40% ======--------
    [Oper] Set up paper trading engine                   100% DONE
    [Oper] Connect to Binance testnet                      0% ACTIVE (agent working)
    [Oper] Run 2-week paper trade                          0% BLOCKED (depends on connect)
  [Tactical] Implement risk management                     0% APPROVED (queued)
```

---

## Plan Templates & Reuse

### Concept

Many goals follow the same structural pattern regardless of specific parameters. A plan template captures this pattern as a reusable decomposition recipe. The allocator can instantiate a template to create a set of concrete goals with a single command, filling in domain-specific parameters.

**This is analogous to:**
- CI/CD pipeline definitions (build -> test -> deploy)
- HTN methods (a "method" defines how a compound task decomposes into sub-tasks)
- CrewAI "Flows" (modular, reusable agent workflows)
- Factory patterns in software (create complex objects from a template)

### Template Data Model

```sql
CREATE TABLE plan_templates (
    template_id     TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    domain          TEXT,  -- 'trading', 'software', 'research', NULL for universal

    -- The template as a goal tree skeleton
    template_spec   JSON NOT NULL,

    -- Usage tracking
    times_used      INTEGER DEFAULT 0,
    success_count   INTEGER DEFAULT 0,
    avg_completion_time_hours REAL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Universal vs. Domain-Specific Templates

Templates fall into two categories:

**Universal templates** (`domain: null`) ship with the Agent OS core and work for any project type. They use only core acceptance criteria types (`artifact_exists`, `test_passes`, `metric`, `human_review`) and contain no domain-specific SQL, role names, or paths. The three universal templates are: Research Investigation, Feature Development, and Bug Fix. These cover the most common workflows across all project types.

**Domain-specific templates** are declared in `project.yaml` and reference domain tables, domain roles, and domain-specific acceptance criteria. They are only available to projects that declare the corresponding domain tables. For example, the Alpha Strategy Lifecycle template below references `research_hypotheses`, `backtest_runs`, and `strategies` tables -- it only works in projects that declare those tables.

When the Agent OS is used for a new project type (ML research, SaaS, data pipeline), the universal templates provide immediate value without configuration. Domain-specific templates are added as the project matures and recurring workflows emerge.

### Built-in Templates

#### Template 1: Alpha Strategy Lifecycle (Trading Domain)

This template encodes the full pipeline from hypothesis to paper trading -- the same 8-phase cycle described in CLAUDE.md, captured as a reusable goal tree.

```json
{
  "template_id": "alpha_strategy_lifecycle",
  "name": "Alpha Strategy Lifecycle",
  "domain": "trading",
  "description": "Full pipeline: research -> design -> implement -> backtest -> validate -> promote",
  "template_spec": {
    "root": {
      "type": "tactical",
      "title_pattern": "Research and deploy {strategy_name} strategy"
    },
    "children": [
      {
        "ref": "research",
        "type": "operational",
        "title_pattern": "Research {hypothesis_family} for {strategy_name}",
        "role": "researcher",
        "acceptance_criteria_template": [
          {"type": "file_exists", "path": "agent_comms/artifacts/research/{artifact_name}.md"},
          {"type": "sql", "query": "SELECT count(*) FROM research_hypotheses WHERE family_id='{family_id}' AND status='approved'", "op": ">=", "value": 1}
        ],
        "stop_conditions": [
          {"type": "max_attempts", "value": 2},
          {"type": "max_tokens", "value": 300000}
        ]
      },
      {
        "ref": "design",
        "type": "operational",
        "title_pattern": "Design strategy spec for {strategy_name}",
        "role": "quant",
        "depends_on": ["research"],
        "acceptance_criteria_template": [
          {"type": "file_exists", "path": "agent_comms/artifacts/strategies/{strategy_id}_spec.json"},
          {"type": "schema_valid", "path": "agent_comms/artifacts/strategies/{strategy_id}_spec.json", "schema": "strategy_spec_v1"}
        ]
      },
      {
        "ref": "implement",
        "type": "operational",
        "title_pattern": "Implement {strategy_name}",
        "role": "coder",
        "depends_on": ["design"],
        "acceptance_criteria_template": [
          {"type": "file_exists", "path": "src/hft/strategy/implementations/{strategy_module}.py"},
          {"type": "lint_clean", "command": "uv run ruff check src/hft/strategy/implementations/{strategy_module}.py"},
          {"type": "test_passes", "command": "uv run pytest tests/unit/test_{strategy_module}.py"}
        ]
      },
      {
        "ref": "backtest",
        "type": "operational",
        "title_pattern": "Backtest {strategy_name} on {symbol} {timeframe}",
        "role": "tester",
        "depends_on": ["implement"],
        "acceptance_criteria_template": [
          {"type": "metric", "source": "backtest_runs", "strategy_id": "{strategy_id}", "metric": "sharpe_ratio", "op": ">=", "value": 1.5},
          {"type": "metric", "source": "backtest_runs", "strategy_id": "{strategy_id}", "metric": "max_drawdown", "op": ">=", "value": -0.15},
          {"type": "metric", "source": "backtest_runs", "strategy_id": "{strategy_id}", "metric": "trade_count", "op": ">=", "value": 100},
          {"type": "metric", "source": "backtest_runs", "strategy_id": "{strategy_id}", "metric": "profit_factor", "op": ">=", "value": 1.3}
        ],
        "stop_conditions": [{"type": "max_attempts", "value": 3}]
      },
      {
        "ref": "walk_forward",
        "type": "operational",
        "title_pattern": "Walk-forward validation of {strategy_name}",
        "role": "tester",
        "depends_on": ["backtest"],
        "acceptance_criteria_template": [
          {"type": "metric", "source": "backtest_runs", "strategy_id": "{strategy_id}", "metric": "oos_sharpe_ratio", "op": ">=", "value": 1.0}
        ]
      },
      {
        "ref": "promote",
        "type": "operational",
        "title_pattern": "Promote {strategy_name} to paper trading",
        "role": "hf_manager",
        "depends_on": ["walk_forward"],
        "acceptance_criteria_template": [
          {"type": "human_approval", "approver": "hf_manager"},
          {"type": "sql", "query": "SELECT status FROM strategies WHERE strategy_id='{strategy_id}'", "op": "=", "value": "paper_trading"}
        ]
      }
    ]
  }
}
```

#### Template 2: Feature Development Lifecycle (Software Domain)

```json
{
  "template_id": "feature_lifecycle",
  "name": "Feature Development Lifecycle",
  "domain": "software",
  "description": "Standard feature pipeline: spec -> implement -> test -> deploy",
  "template_spec": {
    "root": {
      "type": "tactical",
      "title_pattern": "Build and deploy {feature_name}"
    },
    "children": [
      {
        "ref": "spec",
        "type": "operational",
        "title_pattern": "Write specification for {feature_name}",
        "role": "designer",
        "acceptance_criteria_template": [
          {"type": "file_exists", "path": "specs/{feature_slug}.md"},
          {"type": "human_approval", "approver": "tech_lead"}
        ]
      },
      {
        "ref": "implement",
        "type": "operational",
        "title_pattern": "Implement {feature_name}",
        "role": "coder",
        "depends_on": ["spec"],
        "acceptance_criteria_template": [
          {"type": "test_passes", "command": "uv run pytest tests/unit/"},
          {"type": "lint_clean", "command": "uv run ruff check src/"}
        ]
      },
      {
        "ref": "integration_test",
        "type": "operational",
        "title_pattern": "Integration test {feature_name}",
        "role": "tester",
        "depends_on": ["implement"],
        "acceptance_criteria_template": [
          {"type": "test_passes", "command": "uv run pytest tests/integration/"}
        ]
      },
      {
        "ref": "deploy",
        "type": "operational",
        "title_pattern": "Deploy {feature_name} to staging",
        "role": "devops",
        "depends_on": ["integration_test"],
        "acceptance_criteria_template": [
          {"type": "test_passes", "command": "curl -sf https://staging.example.com/health"}
        ]
      }
    ]
  }
}
```

#### Template 3: Research Investigation (Universal)

```json
{
  "template_id": "research_investigation",
  "name": "Research Investigation",
  "domain": null,
  "description": "Universal research template: literature review -> hypothesis generation -> evaluation",
  "template_spec": {
    "root": {
      "type": "tactical",
      "title_pattern": "Investigate {research_question}"
    },
    "children": [
      {
        "ref": "lit_review",
        "type": "operational",
        "title_pattern": "Literature review for {research_question}",
        "role": "researcher",
        "acceptance_criteria_template": [
          {"type": "file_exists", "path": "agent_comms/artifacts/research/{artifact_name}_lit_review.md"}
        ],
        "stop_conditions": [{"type": "max_tokens", "value": 200000}]
      },
      {
        "ref": "hypotheses",
        "type": "operational",
        "title_pattern": "Generate hypotheses for {research_question}",
        "role": "researcher",
        "depends_on": ["lit_review"],
        "acceptance_criteria_template": [
          {"type": "sql", "query": "SELECT count(*) FROM research_hypotheses WHERE family_id='{family_id}' AND status='proposed'", "op": ">=", "value": 3}
        ]
      },
      {
        "ref": "evaluate",
        "type": "operational",
        "title_pattern": "Evaluate hypotheses for {research_question}",
        "role": "hf_manager",
        "depends_on": ["hypotheses"],
        "acceptance_criteria_template": [
          {"type": "sql", "query": "SELECT count(*) FROM research_hypotheses WHERE family_id='{family_id}' AND status IN ('approved','rejected')", "op": ">=", "value": 3}
        ]
      }
    ]
  }
}
```

#### Template 4: Bug Fix (Universal)

```json
{
  "template_id": "bug_fix",
  "name": "Bug Fix",
  "domain": null,
  "description": "Universal bug fix pipeline: reproduce -> diagnose -> fix -> verify",
  "template_spec": {
    "root": {
      "type": "tactical",
      "title_pattern": "Fix: {bug_description}"
    },
    "children": [
      {
        "ref": "reproduce",
        "type": "operational",
        "title_pattern": "Reproduce and isolate {bug_description}",
        "role": "{investigator_role}",
        "acceptance_criteria_template": [
          {"type": "artifact_exists", "path": "{artifacts_dir}/bug_reports/{bug_id}_reproduction.md"}
        ],
        "stop_conditions": [{"type": "max_attempts", "value": 2}]
      },
      {
        "ref": "fix",
        "type": "operational",
        "title_pattern": "Implement fix for {bug_description}",
        "role": "{implementer_role}",
        "depends_on": ["reproduce"],
        "acceptance_criteria_template": [
          {"type": "test_passes", "command": "{test_command}"},
          {"type": "lint_clean", "command": "{lint_command}"}
        ]
      },
      {
        "ref": "verify",
        "type": "operational",
        "title_pattern": "Verify fix for {bug_description}",
        "role": "{tester_role}",
        "depends_on": ["fix"],
        "acceptance_criteria_template": [
          {"type": "test_passes", "command": "{regression_test_command}"}
        ]
      }
    ]
  }
}
```

**Note on universality:** Templates 2 (Feature Development) and 3 (Research Investigation) are structurally universal but their example acceptance criteria reference domain-specific tables (e.g., `research_hypotheses`). To make them truly universal, domain-specific SQL queries in acceptance criteria should be parameterized via `{table_name}` and `{query_template}` placeholders, filled from `project.yaml` at instantiation time. Templates 3 and 4 as written above use only `artifact_exists` and `test_passes` criteria, which are domain-agnostic by nature. Template 2 should be updated to `domain: null` with parameterized paths and commands.

### Template Instantiation

When the allocator decides to use a template:

```python
def instantiate_template(
    template_id: str,
    params: dict,
    parent_goal_id: str,
    db
) -> list[Goal]:
    """
    Create concrete goals from a template by filling in parameters.

    params example: {
        "strategy_name": "MACD Crossover",
        "strategy_id": "macd_v1",
        "strategy_module": "macd_crossover",
        "hypothesis_family": "momentum",
        "family_id": "momentum",
        "artifact_name": "momentum_macd_research",
        "symbol": "BTC/USDT",
        "timeframe": "1h"
    }
    """
    template = db.get_template(template_id)
    goals = []
    ref_to_goal_id = {}  # Map template refs to created goal IDs

    for node in template.template_spec['children']:
        goal_id = generate_goal_id()
        ref_to_goal_id[node['ref']] = goal_id

        # Resolve dependencies from template refs to concrete goal IDs
        depends_on = [
            ref_to_goal_id[ref]
            for ref in node.get('depends_on', [])
        ]

        goal = create_goal(
            goal_id=goal_id,
            parent_goal_id=parent_goal_id,
            title=node['title_pattern'].format(**params),
            goal_type=node['type'],
            acceptance_criteria=fill_criteria(
                node['acceptance_criteria_template'], params
            ),
            stop_conditions=node.get(
                'stop_conditions', default_stop_conditions()
            ),
            depends_on=depends_on,
            decomposition_strategy='template',
            template_id=template_id,
            status='approved'
        )
        goals.append(goal)

    # Update template usage stats
    db.exec(
        "UPDATE plan_templates SET times_used = times_used + 1 "
        f"WHERE template_id = '{template_id}'"
    )

    return goals
```

### Template Evolution

Templates should improve over time based on usage data. After each instantiation, track:
- Did the instantiated goals succeed or fail?
- Which acceptance criteria were too strict (frequently failing good work) or too lenient (letting bad work through)?
- Which stop conditions fired?
- How long did each step take compared to estimates?

Over time, the allocator can adjust templates:
- Increase `max_attempts` for steps that frequently need replanning
- Tighten acceptance criteria that are too permissive
- Add missing steps that the allocator manually inserts every time a template is used
- Remove steps that are consistently skipped or irrelevant

[YAGNI_RISK] **Automated template learning** (the system automatically evolves templates based on outcome data). Microsoft CORPGEN's experiential learning approach -- distilling successful task trajectories into a FAISS-indexed database and retrieving them as few-shot examples -- demonstrates that this works (largest performance gains in their ablation study). However, it requires embedding infrastructure, retrieval pipelines, and careful management of the template corpus. Start with manual template updates by the allocator, informed by usage statistics. Add automated optimization only if manual updates become a bottleneck -- likely after 20+ cycles of template usage.

---

## Integration with Other Agent OS Components

### Blackboard (Research 02)

Goals are stored on the blackboard (`goals` table in fund.db). All coordination happens through goal status transitions, not direct agent messaging. The goal system IS the primary blackboard coordination mechanism. Agents poll for goals in their scope (`SELECT * FROM goals WHERE status = 'approved' AND owner_agent_id IS NULL AND goal_type = 'task'`), execute them, and write results back.

### Failure Memory (Research 02, Pattern 8)

Every abandoned or failed goal generates a structured failure record per Research 08's schema. The replanning protocol MUST consult failure memory before creating a replan. The query: `SELECT * FROM failure_memory WHERE family_id = ? ORDER BY created_at DESC LIMIT 20`. This prevents the system from retrying known-failed approaches. The failure record includes: what was tried, why it failed, what lesson was learned, and what to avoid next time.

### Failure Recovery (Research 08)

When an agent crashes mid-task (F1/F2 in Research 08's failure taxonomy), the goal remains in `active` state with a stale heartbeat. The supervisor (Research 08's heartbeat/liveness monitor) detects this and transitions the goal to `failed` with reason "agent_crash." The replanning protocol then handles recovery -- either reassigning the same task to a new agent (if the crash was transient) or modifying the approach (if the crash was caused by the task itself).

### Confidence Framework (Research 02, Pattern 7)

Goal priority scoring incorporates confidence/uncertainty from upstream goals. A goal derived from a low-confidence research hypothesis should have lower `feasibility` score (and thus lower overall priority) than one derived from a high-confidence hypothesis. The uncertainty propagation rule from Research 02 applies: pipeline confidence is bounded by the weakest link.

---

## Open Questions

### 1. Optimal Decomposition Depth at Approval Time

The lazy decomposition strategy says "decompose one level at a time." But how much should the allocator think ahead when approving a strategic goal? If it approves "Research alpha strategies" without any sense of the operational goals that will follow, it cannot estimate total cost or timeline. If it fully decomposes, it wastes tokens on speculation.

**Current recommendation:** A "sketch" decomposition at approval time -- listing expected children without full specifications or acceptance criteria -- and a "full" decomposition only when activating. The sketch informs priority scoring and resource estimation without committing to implementation details.

**Status:** Implement sketch decomposition. Evaluate after 5 cycles whether more upfront detail is needed.

### 2. Cross-Goal Learning (Success Memory)

If the system successfully completes "Backtest MACD on BTC/USDT," should that inform how it approaches "Backtest RSI on ETH/USDT"? The current architecture supports learning from failures (failure memory) but not from successes.

**Possible approach:** A `success_memory` table parallel to `failure_memory`. Before starting a goal, the agent queries both. Success records include: what approach worked, which parameters were effective, what pitfalls were avoided. This gives agents a head start on related tasks.

[YAGNI_RISK] Start with failure memory only. Add success memory if agents are repeatedly reinventing approaches that worked before. Microsoft CORPGEN's experiential learning (indexing successful trajectories in FAISS for few-shot retrieval) is the most sophisticated version of this idea and showed the largest performance gains in ablation studies -- but it requires embedding infrastructure that we do not yet have.

**Status:** Defer. Monitor for repeated reinvention across goals in the first 10 cycles.

### 3. Multi-Agent Goal Ownership

Can multiple agents collaborate on a single goal? The current model has one `owner_agent_id` per goal. Some goals might benefit from collaboration (e.g., a researcher and a quant jointly designing a strategy).

**Current recommendation:** No. Keep single ownership. If collaboration is needed, decompose into sub-goals with separate owners and well-defined interfaces (output artifacts). Multi-agent ownership creates ambiguity about who is responsible for acceptance criteria and who reports failure.

**Status:** Single ownership. Revisit only if decomposition feels artificial for naturally collaborative tasks.

### 4. Goal Priority Drift

Priorities change as the system learns. A goal that was high-priority yesterday might be irrelevant today because new information arrived. Should the allocator periodically re-score all goals?

**Current recommendation:** Yes. At the start of each cycle, the allocator re-scores all `approved` and `active` goals. This prevents stale priorities from misallocating resources.

[FRAGILE] Re-scoring requires the allocator to hold all active goals in context, which may exceed context window limits as the goal tree grows. Mitigation: re-score only strategic and tactical goals each cycle. Operational and task priorities are derived from their parents.

**Status:** Implement per-cycle re-scoring for strategic and tactical goals.

### 5. Human Steering Mechanism

How does a human adjust the goal tree mid-cycle? Options:
- **Direct DB edits** (powerful but error-prone, no validation)
- **CLI commands** (`uv run hft goal approve G-42`, `uv run hft goal reprioritize G-42 0.9`) -- structured, validated
- **Natural language instruction to allocator** ("focus on risk management this cycle, deprioritize new research") -- highest bandwidth for complex intentions

**Current recommendation:** CLI commands for structured operations (approve, reject, reprioritize, abandon). Natural language for strategic direction (included in the allocator's prompt context at cycle start). Direct DB edits as escape hatch for power users.

**Status:** Build CLI commands first. Natural language steering already exists via the allocator's CLAUDE.md instructions.

### 6. Measuring Progress on Creative/Research Tasks (Genuinely Unsolved)

This was discussed in the Progress Tracking section. It is flagged here as an explicit open question because no satisfactory solution exists. The fundamental challenge: creative work does not decompose into measurable increments. A researcher is not "60% done with having an insight."

**Mitigations (all imperfect):**
- Require periodic checkpoint artifacts (proves activity, not quality)
- Track distinct approaches tried (measures exploration breadth)
- Use time/budget stop conditions instead of progress milestones
- Accept uncertainty and build the pipeline to tolerate false starts

**Status:** Unsolved. Use the mitigations above. Do not attempt to display "percentage complete" for research goals.

### 7. Template Ecosystem: Build vs. Discover

As the system runs, should it automatically discover new templates from successful goal completions? Or should the allocator manually create templates?

**Current recommendation:** Manual template creation by the allocator. After completing a novel workflow successfully, the allocator can abstract it into a template. Automated template discovery risks creating templates from one-off successes that do not generalize.

[YAGNI_RISK] Automated template discovery. Defer until there are 20+ completed tactical goals to pattern-match against.

**Status:** Manual templates only for V1.

### 8. Goal Versioning and Audit Trail

When a goal is replanned, should we keep the old version or overwrite it? The current schema uses `replan_history` JSON to track changes, but this field could grow large over many attempts.

**Current recommendation:** Keep `replan_history` JSON for V1. If it grows unwieldy (10+ replans on a single goal), move historical data to a separate `goal_history` table with `goal_id` as foreign key.

**Status:** JSON field is sufficient for now. Monitor after 20+ cycles.

---

## Summary: What to Build First

The goal and planning system is large. Here is the recommended build order, from essential to optional:

### Phase 1: Core (Must Have for V1)

1. `goals` table with the schema defined above
2. Goal state machine with all transitions and triggers
3. Acceptance criteria evaluator supporting `metric`, `sql`, `file_exists`, `test_passes`, and `human_approval` types
4. Simple dependency resolver (topological sort, block-on-failure)
5. Stop conditions: `max_attempts`, `max_tokens`, `max_wall_clock`
6. Allocator decomposition protocol (lazy, one level at a time)
7. Priority scoring (urgency + importance + feasibility + cost_efficiency + fan_out)

### Phase 2: Robustness (Should Have)

8. Replanning protocol with the five defense layers
9. Diminishing returns detection
10. Chain-stuck detector for blocked dependency chains
11. Progress tracking per goal type
12. Integration with failure memory (consult before replanning)

### Phase 3: Efficiency (Nice to Have)

13. Plan templates with the three built-in templates
14. Template instantiation with parameter filling
15. Per-cycle priority re-scoring
16. CLI commands for human steering (`goal approve`, `goal abandon`, etc.)

### Phase 4: Advanced (Defer) [YAGNI_RISK on all]

17. Template evolution / automated learning from usage data
18. Success memory (complement to failure memory)
19. Cross-goal transfer learning
20. Automated template discovery from completed workflows
21. Cost-benefit stop condition (requires accurate value estimation)
22. Context-affinity-based agent assignment
23. Goal merging

---

## References

- [Microsoft CORPGEN: Multi-Horizon Tasks for Autonomous AI Agents (arxiv:2602.14229)](https://arxiv.org/abs/2602.14229)
- [Microsoft CORPGEN Blog: Advances AI Agents for Real Work](https://www.microsoft.com/en-us/research/blog/corpgen-advances-ai-agents-for-real-work/)
- [DynTaskMAS: Dynamic Task Graph Framework for LLM-based MAS (ICAPS 2025, arxiv:2503.07675)](https://arxiv.org/abs/2503.07675)
- [Hierarchical Task Network Planning - Wikipedia](https://en.wikipedia.org/wiki/Hierarchical_task_network)
- [HTN Planning in AI - GeeksforGeeks](https://www.geeksforgeeks.org/artificial-intelligence/hierarchical-task-network-htn-planning-in-ai/)
- [A Hierarchical Goal-Based Formalism for Single-Agent Planning (AAMAS 2012)](https://www.ifaamas.org/Proceedings/aamas2012/papers/1F_3.pdf)
- [PhD Proposal: Hierarchical Goal Decomposition for Probabilistic Planning (UMD 2025)](https://www.cs.umd.edu/event/2025/02/phd-proposal-hierarchical-goal-decomposition-probabilistic-planning)
- [AI Agents Planning in 2026: Blueprint for Autonomous Enterprise AI](https://gleecus.com/blogs/ai-agents-planning-2026/)
- [Long-Running AI Agents and Task Decomposition 2026 - Zylos Research](https://zylos.ai/research/2026-01-16-long-running-ai-agents)
- [IBM: What is AI Agent Planning?](https://www.ibm.com/think/topics/ai-agent-planning)
- [Enhancing Multi-Agent Coordination with Dynamic DAG (EMNLP 2025)](https://aclanthology.org/2025.findings-emnlp.757.pdf)
- [DAGs: The Backbone of Modern Multi-Agent AI](https://santanub.medium.com/directed-acyclic-graphs-the-backbone-of-modern-multi-agent-ai-d9a0fe842780)
- [A Practical Perspective on Orchestrating AI Agent Systems with DAGs](https://medium.com/@arpitnath42/a-practical-perspective-on-orchestrating-ai-agent-systems-with-dags-c9264bf38884)
- [Stopping Conditions That Actually Stop Multi-Agent Loops](https://dev.to/dowhatmatters/stopping-conditions-that-actually-stop-multi-agent-loops-bnb)
- [Circuit Breaker Pattern for AI Agents](https://dev.to/tumf/ralph-claude-code-the-technology-to-stop-ai-agents-how-the-circuit-breaker-pattern-prevents-3di4)
- [Resilience Circuit Breakers for Agentic AI](https://medium.com/@michael.hannecke/resilience-circuit-breakers-for-agentic-ai-cc7075101486)
- [Scene Graph-Guided Proactive Replanning for Failure-Resilient Agents (arxiv:2508.11286)](https://arxiv.org/abs/2508.11286)
- [Measuring AI Ability to Complete Long Tasks - METR (2025)](https://metr.org/blog/2025-03-19-measuring-ai-ability-to-complete-long-tasks/)
- [Anthropic: Demystifying Evals for AI Agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- [Braintrust: What is Agent Evaluation?](https://www.braintrust.dev/articles/agent-evaluation)
- [The 9 Best Agentic Workflow Patterns in 2026 - Beam AI](https://beam.ai/agentic-insights/the-9-best-agentic-workflow-patterns-to-scale-ai-agents-in-2026)
- [Agentic Workflows for Software Development - QuantumBlack/McKinsey (2026)](https://medium.com/quantumblack/agentic-workflows-for-software-development-dc8e64f4a79d)
- [Google: Framework for AI Agent Compute and Tool Budgeting](https://venturebeat.com/ai/googles-new-framework-helps-ai-agents-spend-their-compute-and-tool-budget/)
- [Atlassian: OKRs - The Ultimate Guide](https://www.atlassian.com/agile/agile-at-scale/okr)
- [GPT-HTN-Planner: LLM-based Hierarchical Task Network Planning](https://github.com/DaemonIB/GPT-HTN-Planner)
- [35th ICAPS HPlan Workshop Proceedings (2025)](https://icaps25.icaps-conference.org/files/HPlan/HPlanProceedings-2025.pdf)
- Research 02: AI-Native Coordination Patterns (internal)
- Research 08: Failure Modes, Resilience & Self-Healing (internal)
