# Agent Operating System -- Unified Design Synthesis

**Date:** 2026-03-08
**Status:** Final synthesis of research documents 01-08
**Purpose:** The build specification. Everything we decided, reconciled, and prioritized.

---

## 1. Executive Summary

The Agent Operating System (Agent OS) is a general-purpose runtime for orchestrating teams of AI agents that collaborate on long-lived, multi-phase projects. It is domain-agnostic (hedge funds, SaaS, research labs) but opinionated about architecture: a **SQLite blackboard** serves as the universal coordination substrate, **typed work packets** with machine-checkable acceptance criteria replace natural language coordination, a **hierarchical goal system** decomposes objectives into executable tasks with DAG dependencies, and a **multi-provider runtime** lets any agent backend (Claude Code, OpenAI Codex, Python scripts, cron jobs, humans) participate through five canonical lifecycle operations.

**What makes it different from CrewAI, LangGraph, AutoGen, and others:**

No existing framework combines all six of our requirements (Ref: 07, Gap Analysis):
1. **Typed packet coordination** with executable acceptance gates -- not conversation, not shared state graphs, but structured work units with machine-verifiable completion criteria.
2. **Continuous parallel execution** with dependency-aware scheduling -- not sequential pipelines or LLM-mediated routing, but pre-declared DAGs that maximize parallelism automatically.
3. **Persistent cross-session meta-learning** -- structured failure memory that future agents query before starting work. No framework has this as a first-class feature.
4. **Provider-agnostic runtime** where the model is a parameter, not the identity -- different agents use different models based on task requirements and cost.
5. **Real-time observability dashboard** purpose-built for agent oversight -- not a log viewer or conversation debugger, but a mission-control surface with human steering.
6. **Layered security with infrastructure-enforced guardrails** -- capability tokens, append-only audit trails with hash chains, sandboxed execution, and escalation protocols that the agent cannot bypass.

---

## 2. Core Architecture Decisions

### 2.1 Entity Model (Reconciled from 01, 04)

Seven core entities. This is the minimum set; adding more requires justification.

| Entity | Purpose | Identity Format |
|--------|---------|----------------|
| **Project** | Top-level container. Defines domain, config, gates. | `proj_` + ULID |
| **Goal** | Hierarchical objective with acceptance criteria. Forms a **tree**. | `goal_` + ULID |
| **Task** | Leaf-level executable unit assigned to an agent session. Forms a **DAG** via `task_dependencies`. | `task_` + ULID |
| **Agent** | Registered agent identity with role, capabilities, status. | `agent_` + slug (e.g., `agent_researcher`) |
| **Session** | A single agent execution run, bounded by start/end. | `sess_` + random hex |
| **Artifact** | Versioned output produced by a session. | `art_` + random hex |
| **Event** | Append-only audit trail entry with hash chain. | `aud_` + ULID |

**Identity system (Ref: 01, Section 2):** Prefixed ULIDs for time-sortability, uniqueness without coordination, and human readability. Agents use stable slugs (not ULIDs) because they are long-lived identities referenced in prompts and config.

**Goals are a tree, tasks are a DAG (Ref: 04, "Why a Tree for Goals, DAG for Tasks"):** Each goal has exactly one parent context (tree). Tasks have cross-cutting dependencies across goal boundaries (DAG). This keeps goal decomposition simple while allowing execution-level flexibility. Goal-level DAG dependencies are deferred -- tree + task DAG is sufficient for our scale.

### 2.2 Unified Database Schema

Single SQLite database in WAL mode. Key tables (consolidated from 01, 03, 04, 06, 08):

**Core tables:** `projects`, `goals`, `tasks`, `task_dependencies`, `agents`, `sessions`, `artifacts`, `plan_templates`

**Operational tables:** `activity_log` (lightweight ops log), `audit_trail` (security-grade hash-chained log), `failure_log` (structured failure memory), `dead_letter_tasks` (tasks that failed repeatedly), `confidence_calibration` (tracks agent confidence accuracy over time)

**Domain tables (project-specific, not part of core OS):** Declared in `project.yaml` under `domain_tables` and created at `agent-os init` time. The core schema never references domain tables directly. Each project defines its own set -- for example, an HFT fund project might declare `fund_state`, `strategies`, `research_hypotheses`, `backtest_runs`, `paper_trades`, `paper_positions`, `portfolio_snapshots`, `risk_events`. A SaaS project might declare `deployments`, `feature_flags`, `incidents`. An ML research project might declare `experiments`, `model_runs`, `dataset_versions`. Domain table DDL lives in `project.yaml` or in SQL files referenced by it; the init process executes them after creating core tables.

**Concurrency model:** WAL mode + optimistic locking via `version` columns on mutable rows. Sufficient for tens of concurrent agents. If contention becomes measurable, the first upgrade path is moving the dashboard to read from a 5-second-refresh replica, not migrating to Postgres.

### 2.3 State Machines

**Goal states (Ref: 04):** `proposed -> approved -> active -> {completed | failed | blocked | paused | abandoned}`. Failed goals can be reopened with mandatory justification. Completed goals cannot be reopened -- create a new goal referencing the old one.

**Task states (Ref: 01, existing schema):** `pending -> assigned -> in_progress -> {done | blocked | cancelled}`. Review state for outputs requiring gating.

**Strategy states (domain-specific, HFT only -- NOT part of core OS):** `draft -> spec_complete -> implementing -> implemented -> backtesting -> {backtest_passed | backtest_failed} -> paper_trading -> {paused | retired}`. This state machine is defined by the HFT fund project, not the Agent OS core. Other project types define their own domain-specific state machines (e.g., a SaaS project might have deployment states, an ML project might have experiment states). Domain state machines are declared in `project.yaml` and enforced by CHECK constraints on the corresponding domain tables. Only goal, task, and session state machines above are part of the core OS.

**Session states (Ref: 03):** `active -> {completed | failed | timed_out | cancelled}`.

**Key decision:** State transitions are almost entirely automated. The system monitors acceptance criteria continuously and transitions without human intervention. The only human-gated transitions are `abandon` (irreversible value judgment) and `reopen` (requires justification that the new approach differs from the failed one).

### 2.4 Project Configuration

Each project declares its full domain configuration in a `project.yaml` file at the project root. This file is the single source of truth for everything project-specific that the core OS needs to know.

**Required sections:**

| Section | Purpose | Example |
|---------|---------|---------|
| `project.name` | Human-readable project name | `"HFT Crypto Fund"` |
| `project.type` | Project archetype (informs defaults) | `trading`, `saas`, `ml_research`, `data_pipeline`, `custom` |
| `domain_tables` | SQL DDL or paths to `.sql` files for project-specific tables | `strategies`, `backtest_runs`, `paper_trades` |
| `agent_roles` | Agent role definitions with capabilities, permissions, and prompt paths | `researcher`, `quant`, `coder`, `risk_monitor` |
| `plan_templates` | Domain-specific plan templates (supplement the 3 universal ones) | `alpha_strategy_lifecycle`, `incident_response` |
| `acceptance_defaults` | Default acceptance criteria and stop conditions per goal type | Max attempts, token budgets, metric thresholds |
| `state_machines` | Domain-specific state machines for domain tables | Strategy states, deployment states, experiment states |

**Optional sections:** `data_sources` (external APIs, file paths), `risk_limits` (domain-specific guardrails), `dashboard_panels` (custom domain views for the dashboard).

**Generation:** The `agent-os init` CLI generates `project.yaml` automatically -- from user prompts in greenfield mode, or from codebase analysis in brownfield mode. The file is human-editable and version-controlled. The OS reads it at startup and at `agent-os init` time.

**Design principle:** The core OS imports zero domain knowledge. It reads `project.yaml` to learn what domain tables exist, what roles are valid, and what templates are available. This makes the OS genuinely reusable across domains without code changes.

---

## 3. Coordination Model

### 3.1 Blackboard Architecture

The SQLite database is the single coordination substrate. All agent coordination happens through reading and writing shared state. No direct agent-to-agent messaging is required for standard operations (Ref: 01 Section 3, 02 Pattern 1, 07 "Blackboard Architecture: Deep Dive").

**Why blackboard wins:** Decouples agents temporally (don't need to be online simultaneously), provides full auditability (every state change is a DB write), and eliminates message routing complexity. Recent research (arxiv:2510.01285) shows blackboard with volunteer-based activation outperforms assigned-task models by 13-57%.

**Merge semantics (Ref: 07, LangGraph lesson):** Define per-field merge rules: append for logs, last-writer-wins for status fields with version checks, conflict detection for critical state (strategy parameters, capital allocation).

### 3.2 Task Dependency Graphs (Ref: 04)

Three dependency types are necessary and sufficient:

| Type | Semantics | Example |
|------|-----------|---------|
| `blocks` | Hard precedence. B cannot start until A completes. | Backtest cannot start until implementation is done. |
| `informs` | Soft. B benefits from A's output but can proceed without it. | Research brief informs strategy design, but quant can start with hypothesis alone. |
| `conflicts` | Mutual exclusion. Cannot run simultaneously. | Two agents editing the same strategy file. |

**Scheduling:** `resolve_ready_tasks()` returns all tasks whose `blocks` dependencies are satisfied and whose `conflicts` dependencies are not in-progress. Sort by `scheduling_score = priority * 0.6 + urgency * 0.4`, with bonus for critical-path tasks.

**Failure propagation:** When a task fails, mark transitive downstream `blocks` dependencies as `blocked`. Distinguish retryable failures (auto-retry with exponential backoff) from fundamental failures (propagate immediately). After 3 retries, move to dead letter queue (Ref: 08, RP1).

### 3.3 Fan-Out / Fan-In (Ref: 02 Pattern 2)

The defining AI-native coordination pattern. Exploration is embarrassingly parallel; decision-making must be centralized.

- **Fan-out:** Manager decomposes problem into N independent sub-problems, spawns N agents (optimal: 3-5 per Anthropic's research), each writes structured output to the blackboard.
- **Fan-in:** Manager reads all outputs, scores them against rubric, makes portfolio-level decisions. No agent knows about any other agent's work.
- **Partition the search space explicitly** in task descriptions to prevent redundant exploration.

### 3.4 When to Use Direct Messaging vs. Blackboard (Ref: 02, 07)

| Situation | Use |
|-----------|-----|
| Standard task coordination | Blackboard (DB state) |
| Research output, strategy specs, backtest results | Blackboard (artifacts + DB rows) |
| Adversarial review (red team / blue team) | Structured artifacts on blackboard, not conversation |
| Human directives | Inbox files -> allocator reads at next cycle |
| Emergency halt | Halt flag file (`workspace/risk/FUND_HALT.json`) checked by all agents |
| Nuanced reasoning that requires back-and-forth | Rare. Use structured debate format with max 3 rounds, written to artifacts. |

**Anti-patterns to avoid (Ref: 02):** Simulated meetings, consensus-based decisions, natural language as primary communication, sequential pipelines for independent work. Decision, not deliberation.

---

## 4. Runtime & Provider Layer

### 4.1 Lifecycle Protocol (Ref: 03)

Every agent runtime implements exactly five operations. This is the complete contract:

| Operation | Purpose | Frequency |
|-----------|---------|-----------|
| `start_session(agent_id, session_id, task_context)` | Register a new work session | Once at start |
| `heartbeat(session_id, progress_pct, status_msg)` | Signal liveness, report progress | Every 30s |
| `log_activity(session_id, action, category, desc)` | Record what the agent is doing | As needed |
| `produce_artifact(session_id, type, path, metadata)` | Register an output artifact | When output ready |
| `end_session(session_id, outcome, summary)` | Close the session | Once at end |

**Why five is enough:** They cover birth, liveness, work, output, death. Resource management and coordination happen through blackboard tables, not lifecycle calls. Adding more operations creates provider coupling.

Both Python and shell reference implementations exist (Ref: 03 Section 1.3-1.4).

### 4.2 Provider Adapters (Ref: 03 Section 2)

Each adapter translates a provider's native interface into the lifecycle protocol:

| Provider | Mechanism | Key Implementation Detail |
|----------|-----------|--------------------------|
| **Claude Code** | Subprocess with `claude -p` CLI, `--output-format stream-json` for heartbeats | Parse `result` events for artifacts, `content_block_delta` for progress |
| **OpenAI Codex** | REST API (`POST /v1/responses`), poll for completion | Map Codex's PENDING/RUNNING/COMPLETED to session states |
| **Python Script** | Direct `AgentLifecycle` calls in Python code | Simplest path; scripts import the lifecycle module |
| **Cron Job** | Shell lifecycle wrappers (`aos_start_session`, etc.) | For scheduled tasks like risk monitoring, data refresh |
| **Human** | Dashboard UI writes session records | Human "sessions" bridge dashboard actions to the DB |

**Cost estimation and model routing (Ref: 03 Section 4, 07 Cost section):** Each adapter estimates cost. The dispatcher routes tasks to the cheapest provider that meets capability requirements. Research/judgment tasks use Opus; classification/filtering uses Flash/DeepSeek. The 33x price spread between models makes per-task model selection critical.

### 4.3 Heartbeat & Liveness (Ref: 03, 08)

- Agents heartbeat every 30 seconds.
- Supervisor checks every 15 seconds.
- Dead threshold: 3x heartbeat interval (90s).
- False positive rate: ~2% (agent under heavy computation may miss one cycle).
- What heartbeat detects: crash (F1), hang (F2).
- What heartbeat misses: hallucination (F3), drift (F4), zombie (F10). These require progress tracking, output validation, and semantic analysis.

---

## 5. Goal & Planning System

### 5.1 Goal Hierarchy (Ref: 04)

Three-level decomposition is the sweet spot:

| Level | Type | Granularity | Duration |
|-------|------|-------------|----------|
| 1 | Strategic | Outcome-level | Weeks-months |
| 2 | Tactical | Workstream-level | Days-weeks |
| 3 | Operational | Task-level | Hours-session |

Going deeper than 3 adds overhead exceeding planning benefit. If an operational goal is too big for one session, the agent decomposes further at runtime (creating child operational goals), but this should be exceptional.

**Who decomposes (Ref: 04, "Decomposition Strategy"):** Strategic goals set by humans. Tactical goals proposed by allocator from strategic decomposition. Operational goals proposed by the assigned agent when picking up a tactical goal. The allocator approves all non-trivial decompositions.

### 5.2 Acceptance Criteria (Ref: 04)

Every goal requires at least one criterion. Six types:

| Type | Machine-Checkable? | Use For |
|------|--------------------|---------|
| `metric` | Yes | Sharpe >= 1.5, coverage >= 80% |
| `artifact_exists` | Yes | Strategy spec written, docs generated |
| `test_passes` | Yes | `pytest` passes, `ruff check` clean |
| `db_query` | Yes | SELECT COUNT(*) > threshold |
| `human_review` | No | Portfolio fit, UX review (use sparingly -- <20% of goals) |
| `agent_review` | Partially | Red-team validation |

**Stop conditions (Ref: 04):** First-class objects, not afterthoughts. `time_exceeded`, `cost_exceeded`, `retries_exceeded`, `progress_stall`, `metric_ceiling`. Each has an action: `pause_and_escalate`, `abandon`, `abandon_with_postmortem`, `escalate_to_allocator`.

### 5.3 Adaptive Replanning (Ref: 04)

Replanning is event-driven, not polled. Triggers: task failure, goal blocked >T hours, stop condition hit, new information, human override.

**The allocator owns replanning.** No dedicated planner agent (YAGNI at our scale of 5-15 concurrent goals).

**Loop-breaker mechanisms (Ref: 04, 08):**
1. Replan counter: max 3 replans per goal before requiring human approval.
2. Similarity check: new plan must differ >20% from previous plan.
3. Cooling period: minimum 1 hour of execution between replans.
4. Cost cap: if `actual_cost > 2x estimated_cost`, auto-pause and escalate.

### 5.4 Plan Templates (Ref: 04)

Reusable decomposition patterns stored in `plan_templates` table. Templates track `times_used`, `avg_completion_hours`, `avg_success_rate` for calibration over time.

Template learning (automatic modification suggestions) is deferred until 20+ instantiations provide statistical significance. Start with manual templates.

**Universal vs. domain-specific templates.** The Agent OS ships with three universal templates that work for any project type:

| Template | Domain | Purpose |
|----------|--------|---------|
| **Research Investigation** | `null` (universal) | Literature review -> hypothesis generation -> evaluation. Works for any domain where the first step is understanding the problem space. |
| **Feature Development** | `null` (universal) | Spec -> implement -> test -> deploy. The standard software development cycle applicable to any codebase. |
| **Bug Fix** | `null` (universal) | Reproduce -> diagnose -> fix -> verify. Triggered by issue reports or failing tests. |

Universal templates use only core OS acceptance criteria types (`artifact_exists`, `test_passes`, `metric`, `human_review`). They contain no domain-specific SQL queries, role names, or file paths -- those are filled in by parameter substitution at instantiation time.

Projects register domain-specific templates in `project.yaml` under `plan_templates`. For example, the HFT fund project registers `alpha_strategy_lifecycle` (research -> design -> implement -> backtest -> walk-forward -> promote). A SaaS project might register `incident_response` or `onboarding_flow_build`. Domain templates can reference domain tables in their acceptance criteria because those tables are guaranteed to exist for that project type.

The allocator selects templates by matching the goal's intent against available templates (universal + project-specific). If no template matches, the allocator decomposes manually.

---

## 6. Security & Autonomy

### 6.1 Permission Model (Ref: 06)

Three layers, from static to ephemeral:

**Layer 1: Role-Based Baseline (Static).** Each role gets maximum-possible permissions. Researcher can write to `research_hypotheses` but not `strategies`. Coder can write code but not trade. Risk monitor can halt strategies autonomously.

**Layer 2: Attribute-Based Context Checks (Dynamic).** Before any action, verify: agent has active task, task status is `in_progress`, task type matches role, session is not stale, rate limit not exceeded, cost budget not exceeded.

**Layer 3: Task-Scoped Capabilities (Ephemeral).** Allocator issues signed, time-limited capability tokens granting specific resource access for a specific task. Forbidden lists are explicit.

**Critical constraint (Ref: 06, BYPASS_RISK):** SQLite has no built-in access control. Enforcement must happen at the application layer (db_tool.py wrapper) or through sandboxing (restricting raw sqlite3 access). Phase 1 relies on the wrapper; Phase 2 adds an API gateway; Phase 3 adds container/microVM isolation.

### 6.2 Escalation Protocol (Ref: 06)

Seven trigger types: cost threshold ($100/action), low confidence (<0.70), novelty (no precedent), irreversibility, conflict, rate anomaly (>3x normal), scope creep (semantic similarity <0.6).

**Escalation flow:** Forbidden -> DENY (no override). Outside role baseline -> DENY. No capability token -> ESCALATE to allocator. Triggers threshold -> ESCALATE with specific reason. None triggered -> EXECUTE. Always LOG.

**Timeout behavior:** Critical escalations fail closed (halt). High escalations fail closed (skip task). Medium escalations fail open (proceed with best judgment, logged for review).

### 6.3 Hard Guardrails (Ref: 06)

Infrastructure-enforced, cannot be overridden by any agent or configuration:

- Max single trade size: 5% of equity
- Max total exposure: 80% of equity
- Max drawdown halt: 10% from peak (dual-enforced by risk monitor AND execution engine)
- No real money in paper mode (testnet hardcoded)
- No DELETE on critical tables (SQLite triggers)
- Rate limit: max 100 DB writes/min per agent
- Max session cost: $50 per agent session
- Network allowlist: only allowlisted endpoints reachable

Append-only enforcement via SQLite triggers on `activity_log`, `audit_trail`, and `risk_events`.

### 6.4 Audit Trail (Ref: 06)

`audit_trail` table with hash-chained entries. Each entry records: who (agent_id, session_id), what (action_type, action_detail, resource), why (reasoning, confidence), how authorized (capability_token_id), and proof (input_hash, output_hash, chain_hash).

**Tamper evidence:** `chain_hash = SHA-256(previous_hash + entry_content)`. Not a blockchain -- no distributed consensus. Detects post-hoc insertion, deletion, or modification. Periodic export of chain head to external anchor (git commit, remote log) for stronger guarantees.

The `ops_auditor` agent verifies chain integrity periodically.

---

## 7. Observability & Dashboard

### 7.1 Information Hierarchy (Ref: 05)

Six levels, top-down from "is everything OK?" to "what specifically happened?"

| Level | Name | Question Answered |
|-------|------|-------------------|
| 0 | System Pulse | Are things running? Any emergencies? (Always-visible header bar) |
| 1 | Command Center | Is the system healthy and making progress? (Landing page) |
| 2 | Goal Tree | What is the plan, where are we in it? |
| 3 | Agent Roster + Task Board | Who is doing what right now? |
| 4 | Activity Stream | What happened, in what order? |
| 5 | Artifact Browser | What did the system produce? |

### 7.2 Key Pages (Ref: 05)

**Command Center (Page 1):** Goal progress %, agent summary, alert count, recent completions, active work cards, top blockers. Human should assess system health in <5 seconds. If everything is green, close the tab.

**Goal Tree (Page 2):** Indented tree with expand/collapse (not graph view -- scales better past 20 nodes). Status color coding, progress bars, detail sidebar on click. Filter by status.

**Agent Roster (Page 3):** Agent cards with: status badge, duration since start, current task, heartbeat age, last output line, provider icon, session count. Detects stuck agents (duration too long), dead agents (heartbeat stale), and misbehaving agents (view activity).

**Task Board (Page 4):** List view (dense, sortable, filterable) and Board view (Kanban for bottleneck detection). Cross-agent task visibility.

**Activity Stream (Page 5):** Chronological event log. Filterable by agent, category, severity. Virtual scrolling for performance. Delta-based loading (only new events since last fetch).

### 7.3 Real-Time Strategy (Ref: 05)

**Hybrid push/pull:**
- **WebSocket push** for: agent heartbeats (5s), task state changes, alerts, goal status changes, activity log entries.
- **REST polling** for: goal tree structure (10s), full task/agent lists (10s), performance metrics (30s), token/cost usage (60s).

**SQLite constraint:** No pub/sub. Server polls SQLite and pushes to clients. Single poll loop shared across all connected clients, broadcast via `ConnectionManager`. 2-second poll interval is sufficient.

### 7.4 Human Steering Interface (Ref: 05, 06)

**Steering philosophy:** Read-write command center, not read-only monitor. Steer the system (goals, priorities, constraints), don't micromanage agents. The system should ask for help, not the human.

**Action taxonomy:**
- One-click (low risk): pause/resume agent, acknowledge alert.
- Confirmation-required (medium risk): approve blocked goal, reprioritize, send message to agent, create new goal.
- Dangerous (typed confirmation): halt all agents, delete goal, force-restart agent.

**Needs-Human-Input Queue:** Persistent queue of items requiring human decision. Appears as badge, banner, and keyboard-accessible panel (Cmd+Shift+A). This is the most important steering feature -- escalations surface here.

**Keyboard-first navigation (Linear-inspired):** Cmd+1-5 for pages, Cmd+K command palette, J/K list navigation, Cmd+Shift+P project switch.

---

## 8. Resilience & Self-Healing

### 8.1 Failure Taxonomy (Ref: 08)

Ten failure types, ordered by detection difficulty:

| # | Type | Detection | Recovery |
|---|------|-----------|----------|
| F1 | Agent crash | Heartbeat timeout | Restart + resume/reassign |
| F2 | Agent hang | Heartbeat stall, progress timeout | Kill + restart |
| F3 | Hallucination | Cross-validation, schema/range checks, ground truth | Quarantine output, re-run |
| F4 | Agent drift | Goal-progress scoring, semantic similarity | Checkpoint + redirect |
| F5 | Agent conflict | Write conflicts, semantic contradiction | Allocator arbitration |
| F6 | Resource exhaustion | Token counter, rate limit, cost tracker | Context handoff, budget escalation |
| F7 | Network/API failure | HTTP errors, connection timeouts | Retry with backoff, provider failover |
| F8 | State corruption | Schema validation, constraint checks | Rollback, quarantine, revalidate |
| F9 | Cascading failure | Dependency graph monitoring | Circuit breaker, bulkhead isolation |
| F10 | Zombie agent | Output volume tracking, quality scoring | Terminate + restart with fresh context |

### 8.2 Detection & Recovery (Ref: 08)

Six detection mechanisms with honest false-positive assessments:

- **DM1: Heartbeat** -- LOW false positive (~2%), detects F1/F2. Detection latency 45-90s.
- **DM2: Progress tracking** -- MEDIUM false positive (~10-15%), detects F2/F4/F10. Detection latency 5-25 min.
- **DM3: Output validation** -- Schema/range LOW (~1-5%), semantic HIGH (~20-30%). Detects F3/F8.
- **DM4: Conflict detection** -- Write conflicts VERY LOW (~0.5%), semantic conflicts HIGH (~25%). Detects F5.
- **DM5: Cost/resource monitoring** -- VERY LOW false positive (~1%). Near-real-time. Detects F6.
- **DM6: Dependency health propagation** -- LOW (~3%). Propagation within 30s. Detects F9.

**Hallucination detection stack (Ref: 08, ordered by reliability):**
1. Always: schema + range validation (cheap, reliable for what it covers).
2. Always: ground truth comparison where data exists.
3. For high-stakes: execution-based verification (run the code, check the numbers).
4. For research: cross-agent verification using a different model (treat as evidence, not proof).
5. Never rely solely on: self-consistency or confidence calibration.

### 8.3 Self-Healing Architecture (Ref: 08)

**Supervisor tree (Erlang/OTP inspired):** System Supervisor -> {Agent Pool, DB Health, API Health}. Agent Pool manages restart logic with intensity limiting (>5 crashes in 60s = systemic issue, halt and alert).

**Circuit breakers:** Per external dependency (LLM API, data sources, tools). Open at >50% failure rate in 60s window. Half-open after 30s with one test call. Prevents thundering herd on recovery.

**Bulkhead isolation:** Process isolation (each agent own process), resource budgets (token, runtime, tool calls), DB connection limits, filesystem isolation (agents write only to designated directories).

**Dead letter queue:** Tasks that fail 3 times go to DLQ. 5 failures of the same task type flags the type as potentially broken. DLQ requires human resolution: retry, abandon, or redesign.

**Saga-style compensation (Ref: 08):** Multi-step workflows trigger compensation on late-stage failure. Backtest fails -> strategy marked `backtest_failed` -> design reopened for revision -> hypothesis downgraded. Track compensation cycles per hypothesis; permanent rejection after 2 full cycles without passing.

### 8.4 Graceful Degradation (Ref: 08)

| Level | Condition | Response |
|-------|-----------|----------|
| L0 Nominal | All healthy | Full autonomy |
| L1 Degraded | One provider down or one agent type failing | Failover, extend timelines |
| L2 Limited | Multiple providers down, DB degraded | Single-agent, critical tasks only |
| L3 Emergency | Primary DB unavailable | System halt, human required |
| L4 Recovery | Recovering from L2/L3 | Gradual restart, integrity verification |

**Minimum viable system:** 1 agent + SQLite + 1 LLM provider = functional (sequential, no cross-validation, paper trading paused).

### 8.5 Learning From Failure (Ref: 02 Pattern 8, 08)

`failure_log` table with structured, queryable fields: what failed, failure classification, context (truncated input/output), recovery action and outcome, root cause (populated after the fact), prevention hint.

**Retrieval:** Before assigning a task, query failure_log for relevant past failures. Inject results into agent prompt as "Lessons from Past Failures."

**Pattern detection:** Periodic analysis identifies recurring failures (same type >= 3 times in 7 days). Escalate to allocator with systemic fix suggestion.

**Failure memory decay (Ref: 02 Open Questions):** Start with time-based decay (archive after 10 cycles). Add relevance-based decay later.

---

## 9. Competitive Differentiation

### 9.1 What Existing Systems Get Right (Ref: 07)

| Framework | Strength to Steal |
|-----------|-------------------|
| **CrewAI** | Crews + Flows separation (intelligence vs. structure). Multi-tier memory architecture. |
| **LangGraph** | Checkpointing and persistence. State merge schema. Human-in-the-loop as interrupt + persist + resume. |
| **MetaGPT** | SOP-encoded workflows. Assembly-line with structured artifacts. |
| **Claude Code Teams** | Independent context windows per agent. Lead + specialist topology validation. |
| **OpenAI Agents SDK** | Minimal abstraction philosophy. Parallel guardrails. Built-in tracing. |
| **AutoGen** | Distributed runtime concept. Cross-language potential. |

### 9.2 What They Get Wrong (Ref: 07)

- **Role-play trap:** Defining agents by narrative backstories instead of capabilities and data contracts (CrewAI, MetaGPT).
- **Conversation-as-coordination:** Using natural language for inter-agent communication, which is ambiguous, expensive, and error-prone (AutoGen, Claude Code Teams).
- **Ephemeral sessions:** No cross-session memory or persistence (Claude Code Teams, OpenAI Swarm).
- **No failure memory:** No framework systematically learns from past failures across cycles.
- **Binary human control:** Either full autonomy or approve-everything. No granular autonomy tiers.
- **No cost awareness:** No framework has built-in token budgeting per agent per task.
- **Cascading hallucinations:** Pipeline architectures where each stage trusts the previous stage's output without independent validation (MetaGPT).

### 9.3 Our Unique Advantages

1. **Blackboard + typed packets + acceptance gates** = coordination that is inspectable, debuggable, and auditable by default. The DB is both the communication channel and the audit log.
2. **Structured failure memory** = the system learns. Each rejection writes a queryable record that future agents must consult. No other framework has this.
3. **Confidence-weighted pipeline** = uncertainty is first-class data, not optional metadata. Downstream agents and gates use it for decisions.
4. **Infrastructure-enforced guardrails** = security that the agent cannot bypass, not just prompt-level instructions.
5. **Domain-agnostic core + domain-specific plugins** = same OS for trading, SaaS, research. Domain views (positions, deployments) are project-type plugins, not hardcoded pages.
6. **Adversarial validation pattern** = zero-ego red teaming is a structural advantage of AI agents over human teams.
7. **Cost as architecture** = token budgets per task, model routing per capability requirement, DB-mediated coordination to minimize token waste.
8. **Zero-friction onboarding** = works on empty directories and existing codebases alike via automated project discovery. `agent-os init` detects language, framework, test runner, build system, and existing structure -- then generates a `project.yaml` with sensible defaults. No manual configuration required to start. Competing frameworks assume greenfield projects with specific scaffolding; Agent OS meets projects where they are.

---

## 10. Open Questions & Risks

### 10.1 All Open Questions (Collected from 01-08)

**Must answer before building:**

| # | Question | Source | Decision Needed |
|---|----------|--------|-----------------|
| 1 | SQLite permission enforcement: wrapper vs. API gateway vs. Postgres? | 06 | Architecture decision for Phase 1 vs Phase 2 |
| 2 | Capability token implementation: DB-stored vs. signed JWTs? | 06 | Minimum viable security implementation |
| 3 | Hallucination detection ceiling (~85% for structured, lower for free-text) -- is this sufficient for autonomous operation? | 08 | Determines where human-in-the-loop gates are required |
| 4 | Volunteer-based vs. assigned-task activation for agents? | 07 | Likely hybrid: manager sets agenda, agents claim packets |
| 5 | Optimal agent granularity (too broad vs. too narrow)? | 02 | Empirical testing required; start with 3-5 per Anthropic data |

**Can defer:**

| # | Question | Source | Notes |
|---|----------|--------|-------|
| 6 | Cross-model adversarial validation (different providers for red/blue team) | 02 | Enhancement for high-stakes decisions |
| 7 | Failure memory decay policy (time vs. relevance vs. frequency) | 02 | Start time-based (10 cycles), iterate |
| 8 | A2A protocol maturity -- build on v0.3 or wait? | 07 | Low cost to add Agent Cards; defer full integration |
| 9 | Cross-project goal dependencies | 04 | Defer until multi-project is needed |
| 10 | Goal versioning (explicit table vs. activity_log records) | 04 | Use activity_log for now |
| 11 | Decomposition quality evaluation (adversarial, template, post-hoc) | 04 | Start with template anchoring + post-hoc |
| 12 | Multi-user dashboard access control | 05 | v2 feature; single-user for now |
| 13 | Historical dashboard playback | 05 | Requires event sourcing; not v1 |
| 14 | Audit trail performance (hash chain overhead at 100+ writes/min) | 06 | Benchmark; async hashing if needed |
| 15 | Compensation depth in saga pattern | 08 | Limit to 2 full cycles per hypothesis |
| 16 | Recovery/chaos testing infrastructure | 08 | Staging environment needed before production |
| 17 | Cost tracking accuracy (provider API vs. proxy metering) | 06 | Start with estimates; proxy for precision later |
| 18 | When to use conversation-based coordination (structured debates) | 07 | Rare; artifact-based with max 3 rounds |
| 19 | Token budget exhaustion behavior (fail, request more, partial result) | 07 | Partial result + escalation |
| 20 | Auto-pilot mode for human-unavailable periods | 06 | More permissive soft limits, critical-only alerts |

### 10.2 Top 5 Risks

1. **Cascading hallucinations (Ref: 07, 08).** The #1 failure mode in multi-agent systems. Agent A fabricates a statistic, Agent B treats it as ground truth, bad strategy gets promoted. Mitigation: independent validation at every stage, ground-truth checking where possible, cross-model verification for high-stakes outputs. Residual risk: ~15% of structured hallucinations may pass all checks.

2. **Token cost spiral (Ref: 02, 07).** Multi-agent systems consume 2-10x single-agent tokens. Research + adversarial validation + cross-checking compounds cost. A single fund cycle could cost $20-50 in API calls. Monthly: $3,200-$13,000. Mitigation: per-task token budgets, model routing (cheap models for simple tasks), DB-mediated coordination instead of conversation.

3. **Security: SQLite has no access control (Ref: 06).** Any agent with shell access can bypass db_tool.py and run raw SQL. All permission enforcement is application-layer, which is inherently bypassable. Mitigation: Phase 1 wrapper is good-enough for paper trading. Phase 2 API gateway is required before any real capital exposure. Phase 3 container isolation for production.

4. **Replanning oscillation (Ref: 04, 08).** Goal fails, gets replanned, fails similarly, replanned again -- infinite loop consuming resources. Mitigation: replan counter (max 3), similarity check (>20% different), cooling period (1 hour minimum), cost cap (2x estimate). But these are heuristics that may be too strict or too loose.

5. **Coordination bottleneck at scale (Ref: 07).** Central allocator's context window fills with coordination overhead beyond 5 agents. Mitigation: make coordination mechanical (DB state machines, acceptance checks) rather than LLM-mediated. The allocator should evaluate structured data, not "think" about every decision. If this bottleneck materializes, partition by project or workstream.

---

## 11. Implementation Roadmap

### Phase 1: MVP (Weeks 1-4)

**Goal:** Replace current ad-hoc fund cycle with goal-driven, persistent Agent OS. Single project (HFT Fund), single provider (Claude Code), basic dashboard.

**Build:**
1. **Database schema migration.** Add `goals`, `task_dependencies`, `sessions`, `artifacts`, `plan_templates`, `failure_log`, `audit_trail` tables alongside existing tables. Add `goal_id` FK to existing `tasks` table. Existing data stays intact.
2. **Lifecycle protocol.** Implement `AgentLifecycle` class (Python) and shell wrappers. All agent sessions register via lifecycle calls.
3. **Goal/task management.** Implement goal state machine, task dependency resolution (`resolve_ready_tasks`), acceptance criteria evaluation (metric, artifact_exists, test_passes, db_query types).
4. **Failure memory.** Implement `failure_log` writes on every rejection/failure, retrieval injection into agent prompts.
5. **db_tool.py upgrade.** Add `--agent-id` parameter with permission validation. Add SQLite triggers for append-only audit tables.
6. **Dashboard generalization.** Generalize existing React dashboard: Command Center (from Overview), Goal Tree (new), Agent Roster (from Agent Activity), Task Board (from Tasks), Activity Stream (from Agent Activity). Keep trading-specific views as domain panel.
7. **Basic supervisor.** Heartbeat monitoring + crash detection + auto-restart with exponential backoff.
8. **Project onboarding CLI (`agent-os init`).** Handles both greenfield (empty directory) and brownfield (existing codebase) modes. Greenfield: prompts for project type, creates `project.yaml` with universal defaults, creates DB with core tables only. Brownfield: scans directory for language markers, build files, test runners, existing DB schemas, and git history; infers project type and generates `project.yaml` with detected settings. In both modes, domain tables declared in `project.yaml` are created at init time alongside core tables.

**Not in Phase 1:** Multi-provider, container isolation, capability tokens, adversarial validation, A2A/MCP integration, multi-project support.

### Phase 2: Multi-Provider + Security Hardening (Weeks 5-8)

**Build:**
1. **Provider adapters.** Claude Code adapter (primary), Python script adapter, cron job adapter. OpenAI Codex adapter (if needed).
2. **Model routing.** Dispatcher selects provider per task based on capability requirements and cost. Research tasks -> Opus. Data processing -> Flash.
3. **API gateway.** Thin FastAPI layer between agents and SQLite. Validates permissions, enforces rate limits, logs to audit trail. Agents lose direct sqlite3 access.
4. **Audit trail with hash chains.** Full `audit_trail` table implementation with `compute_chain_hash`, periodic verification by ops_auditor.
5. **Escalation protocol.** Implement in allocator prompt and infrastructure (cost checks, novelty detection, irreversibility detection).
6. **Circuit breakers.** Per-provider circuit breakers with half-open test calls. Provider failover matrix.
7. **WebSocket push.** Shared poll loop broadcasting heartbeats, state changes, and alerts to all dashboard clients.
8. **Adversarial validation.** Red team pattern for hypothesis validation and strategy promotion.

### Phase 3: Full Vision (Weeks 9-16)

**Build:**
1. **Container isolation.** Docker + gVisor per agent. Filesystem isolation, network allowlists, resource budgets.
2. **Capability token system.** Signed, time-limited permission grants per task. Validated by API gateway.
3. **Multi-project support.** Project selector, per-project SQLite databases, global meta-dashboard.
4. **Plan template learning.** Track completion rates, duration calibration, bottleneck detection across template instantiations.
5. **Confidence calibration.** Track agent confidence accuracy over time. Apply calibration corrections.
6. **Saga compensation.** Automatic compensation chain on late-stage failures in multi-step workflows.
7. **A2A / MCP compatibility.** Agent Cards for external discovery. MCP tool adapters for standardized tool access.
8. **Advanced dashboard.** Artifact browser, command palette (Cmd+K), keyboard-first navigation, webhook notifications.

### Migration Path from Existing HFT Fund System

The existing system becomes the first project on the Agent OS:

| Existing Component | Agent OS Equivalent | Migration Action |
|-------------------|--------------------|-----------------|
| `fund_state` table | `fund_state` (domain table declared in `project.yaml`) | Move DDL to `project.yaml`; created at `agent-os init`, not hardcoded in core schema |
| `strategies` table | `strategies` (domain table in `project.yaml`) + goals for each strategy lifecycle | Move DDL to `project.yaml`; add goal_id FK; wrap strategy lifecycle in goal state machine |
| `research_hypotheses` table | `research_hypotheses` (domain table in `project.yaml`) + goals for research | Move DDL to `project.yaml`; add goal_id FK |
| `tasks` table | `tasks` with `goal_id`, `task_dependencies` | Add goal_id FK, normalize `depends_on` JSON to `task_dependencies` table |
| `activity_log` table | `activity_log` (keep as lightweight log) + `audit_trail` (new security log) | Add `audit_trail` table; `activity_log` continues as-is |
| `agents/prompts/*.md` | Agent role definitions + project config | Keep prompts; add capability/permission metadata |
| `agent_comms/inbox/` | Inbox for human -> allocator directives | Keep; formalize as human steering channel |
| `agent_comms/artifacts/` | Artifacts registered in `artifacts` table | Keep file structure; add DB registration via `produce_artifact` |
| `workspace/` files | Goal tree + project config replaces manual state files | Gradually; workspace files remain as human-readable redundancy |
| 8-phase fund cycle | Plan template `tmpl_alpha_pipeline` | Encode as template; allocator instantiates per cycle |
| `scripts/db_tool.py` | `db_tool.py` + API gateway (Phase 2) | Upgrade with `--agent-id`; later replace with API |

**Key principle:** The migration is additive, not destructive. New tables are added alongside existing ones. Existing agents continue working. New goal/task management wraps existing workflows. Nothing breaks during transition.

---

*This document synthesizes research outputs 01-08. Each section references its source document for traceability. The design is dense and opinionated -- disagreements should reference specific research findings, not general preferences. Build from Phase 1.*
