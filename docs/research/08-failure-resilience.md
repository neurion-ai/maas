# Research Output 08: Failure Modes, Resilience & Self-Healing

## Executive Summary

Any AI Agent Operating System running long-lived autonomous agents will experience failures -- crashes, hangs, hallucinations, drift, conflicts, resource exhaustion, and cascading breakdowns. This research defines a comprehensive failure taxonomy, detection mechanisms with realistic latency and false-positive assessments, step-by-step recovery protocols, and a self-healing architecture. The design draws heavily from battle-tested distributed systems patterns (Erlang/OTP supervisors, circuit breakers, bulkheads, saga compensation, dead letter queues) while honestly confronting the unique challenges of LLM-based agents -- particularly hallucination detection, which remains genuinely hard and for which no silver bullet exists. Every failure mode includes concrete examples across multiple domains (trading, ML research, SaaS) to validate that the design is project-agnostic. Self-healing mechanisms that risk oscillation or infinite loops are explicitly flagged.

---

## Failure Taxonomy

| # | Failure Type | Detection Method | Impact | Recovery | Seen In Real Systems? |
|---|-------------|-----------------|--------|----------|----------------------|
| F1 | **Agent Crash** (process dies) | Heartbeat timeout, process exit code | Task abandoned mid-execution, partial writes | Restart agent, resume or reassign task | Yes -- any process can die from OOM, segfault, or provider error |
| F2 | **Agent Hang** (infinite loop, deadlock) | Heartbeat stall, progress timeout | Agent consumes resources, blocks dependent tasks | Kill + restart, reassign task | Yes -- common with LLM API timeouts, infinite tool loops |
| F3 | **Agent Hallucination** (confidently wrong output) | Cross-validation, schema checks, range checks | Bad data propagates to downstream agents/decisions | Quarantine output, flag for review, re-run with different prompt | Yes -- LLMs routinely confabulate statistics, citations, tool outputs |
| F4 | **Agent Drift** (slowly goes off-task) | Goal-progress scoring, semantic similarity to objective | Wasted tokens/cost, delayed goal completion | Checkpoint and redirect, inject goal reminder, escalate | Yes -- documented in multi-agent research; occurs in ~50% of workflows by 600 interactions |
| F5 | **Agent Conflict** (contradictory work) | Conflicting artifact writes, mutex violations, semantic contradiction detection | Inconsistent system state, wasted effort | Conflict resolution protocol, lock arbitration, allocator decides | Partially -- more common in multi-agent than traditional systems |
| F6 | **Resource Exhaustion** (context window, API rate limit, cost ceiling) | Token counter, rate limit headers, cost tracker | Agent cannot complete task, degraded output quality | Summarize context, wait for rate limit reset, budget escalation | Yes -- context window limits are a daily reality |
| F7 | **Network/API Failure** (provider outage) | HTTP error codes, connection timeouts, health checks | Agent cannot call tools or LLM | Retry with backoff, failover to alternate provider, queue for later | Yes -- provider outages happen regularly |
| F8 | **State Corruption** (bad data written to blackboard) | Schema validation, constraint checks, anomaly detection | Downstream agents make decisions on wrong data | Rollback write, quarantine record, revalidate | Yes -- any database-backed system can have this |
| F9 | **Cascading Failure** (one agent's failure breaks others) | Dependency graph monitoring, health propagation | System-wide degradation or halt | Circuit breaker, bulkhead isolation, dependency timeout | Yes -- the defining problem of distributed systems |
| F10 | **Zombie Agent** (agent appears alive but produces no useful work) | Output volume tracking, quality scoring | Silent resource waste | Terminate + restart with fresh context | Yes -- common when LLM gets into apologetic loops or meta-discussion |

---

## Detection Mechanisms

### DM1: Heartbeat + Liveness Monitoring

**How it works:** Every running agent must update a `last_heartbeat` timestamp in the `agents` table at a configurable interval (default: 30 seconds). A supervisor process checks all agents every 15 seconds. If `now() - last_heartbeat > timeout_threshold`, the agent is declared dead or hung.

**Concrete examples:**
- *Trading:* The researcher agent is fetching data from CoinGecko. The API hangs for 5 minutes with no response. The agent process is alive but blocked on I/O. The heartbeat stops updating because the agent's main loop is stuck on the HTTP call. After 90 seconds (3x heartbeat interval), the supervisor declares the agent hung.
- *ML Research:* A training agent is downloading a 50GB dataset from HuggingFace. The connection stalls mid-transfer. The agent's main loop is blocked on the HTTP stream. After 90 seconds without a heartbeat, the supervisor declares it hung.
- *SaaS:* A deployment agent is waiting on a CI/CD pipeline callback. The webhook never fires due to a misconfigured URL. The agent polls indefinitely. After 90 seconds of heartbeat stall, the supervisor intervenes.

**False positive rate:** LOW (~2%). A healthy agent under heavy computation might miss a heartbeat cycle. Mitigation: use 3x interval as threshold, not 1x.

**Detection latency:** 45-90 seconds depending on check interval and threshold multiplier.

**What it detects:** F1 (crash), F2 (hang).

**What it misses:** F3 (hallucination), F4 (drift), F10 (zombie) -- the agent is alive and sending heartbeats, just doing the wrong thing.

### DM2: Progress Tracking + Stall Detection

**How it works:** Each task has measurable progress indicators. The system tracks: (a) time since last artifact write, (b) time since last task status update, (c) token spend rate vs. output production rate. A stall is declared when no meaningful progress is recorded for a configurable duration (default: 10 minutes for research tasks, 5 minutes for implementation tasks).

**Concrete examples:**
- *Trading:* The quant agent is assigned to design a momentum strategy. It has been running for 25 minutes and has consumed 150K tokens but has not written any artifact. The progress tracker flags a stall. Upon inspection, the agent has been debating internally about the optimal lookback period, generating increasingly circular reasoning without committing to a decision.
- *ML Research:* An experiment agent is assigned to run a hyperparameter sweep. It has consumed 200K tokens discussing whether to use Bayesian optimization or grid search, without launching any experiment runs or writing results.
- *SaaS:* A coder agent is assigned to implement a REST endpoint. It has spent 20 minutes refactoring unrelated utility code, producing no output related to the endpoint specification.

**False positive rate:** MEDIUM (~10-15%). Some legitimate tasks (deep research, complex debugging) genuinely take time without visible output. Mitigation: task-type-specific thresholds and an "I'm still working" signal the agent can explicitly send.

**Detection latency:** 5-25 minutes depending on task type configuration.

**What it detects:** F2 (hang), F4 (drift), F10 (zombie).

### DM3: Output Validation (Schema + Range + Semantic)

**How it works:** Three layers of validation run on every artifact before it is accepted into the blackboard:

1. **Schema validation:** Does the output match the expected structure? A research brief must have `hypothesis`, `evidence`, `confidence` fields. A design spec must have the required sections defined by the project's artifact schemas.
2. **Range validation:** Are numeric values within plausible bounds? Configurable per project -- e.g., a Sharpe ratio of 47.3 is flagged in a trading project; a model accuracy of 150% is flagged in an ML project; a response time of -3ms is flagged in a SaaS project.
3. **Semantic consistency:** Does the output contradict itself? Does the conclusion match the evidence? This layer is the weakest -- see Hallucination Detection section for honest assessment.

**Concrete examples:**
- *Trading:* The researcher agent produces a brief claiming "BTC/USDT funding rates have been consistently negative for 30 days." The semantic check cross-references actual funding rate data and finds rates were positive for 22 of 30 days. The brief is quarantined.
- *ML Research:* An experiment agent reports "model F1 score improved from 0.72 to 0.91 after adding dropout." The validation layer re-runs the evaluation script and finds F1 is actually 0.74. The report is quarantined.
- *SaaS:* A monitoring agent claims "API latency p99 dropped 40% after the caching change." The validator queries the actual metrics store and finds p99 increased by 5%. The report is quarantined.

**False positive rate:** Layer 1 (schema): LOW (~1%). Layer 2 (range): LOW-MEDIUM (~5%). Layer 3 (semantic): HIGH (~20-30%) -- legitimate novel findings can look anomalous.

**Detection latency:** < 5 seconds for schema/range, 30-120 seconds for semantic cross-validation.

**What it detects:** F3 (hallucination), F8 (state corruption).

### DM4: Conflict Detection

**How it works:** The system monitors for:

1. **Write conflicts:** Two agents attempting to update the same record or write to the same artifact path within a short window.
2. **Semantic conflicts:** Two agents producing contradictory conclusions about the same topic (e.g., two researchers reaching opposite conclusions about the same hypothesis, or two agents recommending incompatible architectural decisions).
3. **Resource conflicts:** Two agents trying to use the same limited resource (e.g., both trying to use a single GPU, or both writing to the same output path).

**Concrete examples:**
- *Trading:* The coder agent implements a momentum strategy with a 20-period SMA crossover. Simultaneously, the quant agent updates the strategy spec to use a 50-period EMA. The artifact version system detects the spec was modified after the coder started implementation, flagging a conflict.
- *ML Research:* Agent A sets up an experiment with learning rate 0.001 and Agent B overwrites the config to use 0.01. The version conflict is detected on the shared experiment config file.
- *SaaS:* A frontend agent and a backend agent both modify the API contract schema simultaneously with incompatible changes. The write conflict on the shared spec file triggers resolution.

**False positive rate:** Write conflicts: VERY LOW (~0.5%). Semantic conflicts: HIGH (~25%) -- agents can legitimately disagree, and "contradiction" is hard to define programmatically.

**Detection latency:** Write conflicts: immediate (database constraint). Semantic conflicts: minutes (requires analysis).

**What it detects:** F5 (conflict).

### DM5: Cost + Resource Monitoring

**How it works:** Every agent session tracks:
- Total tokens consumed (input + output)
- API calls made (count and cost)
- Wall-clock time elapsed
- Context window utilization percentage

Thresholds are configured per task type. Alerts fire at 80% of budget, hard stop at 100%.

**Concrete examples:**
- *Trading:* The researcher agent is doing a deep-dive into DeFi yield farming strategies. It has consumed $14.50 against a $15.00 budget. The cost monitor fires a warning at $12.00 (80%) and will hard-stop at $15.00. The agent is instructed to summarize findings before the budget runs out.
- *ML Research:* An experiment agent running a hyperparameter sweep has consumed 500K tokens against a 600K budget. The warning fires at 480K, giving the agent time to write partial results and recommend which configurations to prioritize in a follow-up task.
- *SaaS:* A code review agent analyzing a large PR has consumed $9.00 against a $10.00 budget. It summarizes remaining unreviewed files and flags them for a follow-up pass.

**False positive rate:** VERY LOW (~1%). Cost tracking is deterministic.

**Detection latency:** Near-real-time (checked after each API call).

**What it detects:** F6 (resource exhaustion).

### DM6: Dependency Health Propagation

**How it works:** The system maintains a dependency graph of agents and tasks. When an agent fails or a task is blocked, the system propagates health status to all dependent nodes. A dependent task that has been waiting for a prerequisite beyond a timeout is escalated.

**Concrete example:** Agent B needs the output from task T-42 (assigned to Agent A) before it can start. Agent A crashed 10 minutes ago. The dependency health system propagates the failure: T-42 is marked `blocked`, and Agent B is notified not to wait. The allocator can reassign Agent A's task or adjust priorities.

**False positive rate:** LOW (~3%). Occasional false positives when a dependency is slow but not actually failed.

**Detection latency:** Propagation within 30 seconds of source failure detection.

**What it detects:** F9 (cascading failure).

---

## Recovery Protocols

### RP1: Agent Crash Recovery

**Trigger:** Heartbeat timeout, process exit code != 0, unhandled exception.

**Step-by-step procedure:**

1. **Detect:** Supervisor detects missing heartbeat or process exit.
2. **Classify:** Check exit code and last log entries. Was it OOM? API error? Bug?
3. **Assess state:** Query `tasks` table for the agent's in-progress task. Check for partial artifact writes.
4. **Clean up partial state:**
   - If partial artifact exists, move it to `agent_comms/artifacts/_quarantine/` with metadata about why it was quarantined.
   - If partial DB writes occurred, check integrity constraints. Roll back if transaction was incomplete.
5. **Decide restart strategy:**
   - If crash count < 3 in last hour: restart immediately with same task.
   - If crash count >= 3 in last hour: escalate to allocator for reassignment or human review.
   - If crash was OOM: restart with reduced context/scope.
6. **Restart:** Spawn new agent process. Load task context from DB. Resume from last checkpoint if available, otherwise restart task from beginning.
7. **Log:** Write to `activity_log` with full crash details, recovery action taken.

**What could go wrong with recovery:**
- The crash was caused by corrupted task data in the DB. Restarting will just crash again. Mitigation: after 2 crashes on the same task, try the task with a fresh context (no prior agent output loaded).
- Partial writes corrupted the DB. Mitigation: all writes must be in transactions; WAL mode ensures atomicity.
- The new agent process also crashes immediately (same bug). Mitigation: exponential backoff on restart attempts; max 5 restarts per task.

[OSCILLATION_RISK] If the crash is caused by the task itself (e.g., a prompt that always triggers a tool error), the restart-crash-restart cycle will oscillate. Mitigation: crash counter with exponential backoff. After 3 rapid crashes, the task is moved to a dead letter queue for human inspection, not retried automatically.

### RP2: Agent Hang Recovery

**Trigger:** Heartbeat stall (agent alive but not progressing), progress timeout.

**Step-by-step procedure:**

1. **Detect:** Heartbeat stall detected, or progress tracker shows no output for > threshold.
2. **Attempt soft interrupt:** Send a signal to the agent process (if supported by the runtime). For LLM-based agents, this may mean cancelling the current API call.
3. **Grace period:** Wait 30 seconds for the agent to respond to the interrupt.
4. **Hard kill:** If no response, terminate the process.
5. **Follow RP1 steps 3-7** for state cleanup and restart.

**Concrete example:** The coder agent calls `uv run ruff check` on a malformed Python file. Ruff enters an unexpectedly long analysis. The agent's main loop is blocked waiting for the subprocess. After 90 seconds of heartbeat stall, the supervisor sends SIGTERM. After 30 seconds grace period, SIGKILL. The task is restarted with a note in context: "Previous attempt hung during linting -- check for syntax errors before running ruff."

**What could go wrong with recovery:**
- The hang was caused by a legitimate long-running operation (e.g., downloading 2GB of market data). The timeout kills a valid operation. Mitigation: agents can declare "long operation in progress" to extend their timeout.
- Killing the process leaves zombie child processes. Mitigation: process group kill (kill the entire process tree).

### RP3: Hallucination Recovery

**Trigger:** Output validation failure (schema, range, or cross-validation check).

**Step-by-step procedure:**

1. **Quarantine:** Move the suspicious output to `_quarantine/` directory. Do NOT let it propagate to other agents.
2. **Classify severity:**
   - **Hard hallucination:** Output contains fabricated data, impossible values, or contradicts ground truth. Examples: "The backtest shows 847 trades" when the log shows 12; "Model accuracy reached 97%" when the evaluation script shows 61%; "All 200 tests pass" when 14 are failing.
   - **Soft hallucination:** Output makes claims that are plausible but unverified. Examples: "BTC historically drops 15% in March"; "Transformer models consistently outperform LSTMs for this task type"; "This endpoint handles 10K rps based on similar architectures."
   - **Structural hallucination:** Output has correct data but wrong structure/relationships. Examples: entry and exit signals are swapped in a spec; train and test datasets are swapped in an experiment config; request and response schemas are transposed in an API definition.
3. **For hard hallucinations:**
   - Log the failure with the specific hallucination identified.
   - Re-run the task with a modified prompt that includes: "Previous attempt produced incorrect output. Specifically: [description of error]. Double-check all claims against source data."
   - If second attempt also fails, escalate to human review.
4. **For soft hallucinations:**
   - Flag the output as "unverified" rather than quarantining it.
   - Schedule a cross-validation task: assign another agent to verify the specific claims.
5. **For structural hallucinations:**
   - Re-run with explicit schema examples in the prompt.
   - Consider using structured output (JSON mode) if available.

**What could go wrong with recovery:**
- The cross-validation agent also hallucinates, confirming the wrong answer. This is a real risk -- LLMs can converge on the same wrong answer. Mitigation: use a different model or provider for cross-validation. Use ground-truth data checks wherever possible instead of LLM-based verification.
- The re-run prompt mentioning the previous error biases the agent in a different wrong direction. Mitigation: provide the specific error, not a general warning.
- Over-aggressive quarantine blocks legitimate novel findings. Mitigation: always have an appeal path (human can override quarantine).

### RP4: Agent Drift Recovery

**Trigger:** Progress tracking shows agent is active but not advancing toward the goal. Semantic similarity between agent's recent output and goal description drops below threshold.

**Step-by-step procedure:**

1. **Detect:** Progress tracker flags that the agent has been active for 20 minutes but goal completion score has not improved.
2. **Diagnose:** Compare agent's recent actions/outputs against the original task description. Calculate semantic similarity score.
3. **Soft redirect (drift score 0.5-0.7):** Inject a goal reminder into the agent's context: "Reminder: your current task is [original task description]. You seem to have drifted into [detected topic]. Please refocus."
4. **Hard redirect (drift score < 0.5):** Checkpoint current state, terminate the agent, restart with fresh context and the original task. Include a note: "Stay focused on [task]. Do not explore tangential topics."
5. **Escalate (drift persists after redirect):** Flag to allocator. The task may be poorly defined or genuinely require the tangential exploration.

**Concrete examples:**
- *Trading:* The researcher agent was tasked with analyzing BTC/ETH correlation patterns. After 15 minutes, its output has drifted into Ethereum's merge history and L2 scaling. The drift detector measures semantic similarity at 0.35. The agent is checkpointed and restarted with a focused prompt.
- *ML Research:* An agent tasked with evaluating data augmentation techniques for image classification has drifted into a survey of self-supervised learning methods. Interesting but off-task. Semantic similarity to the original objective drops to 0.40. The agent is redirected.
- *SaaS:* An agent tasked with optimizing a database query has drifted into redesigning the entire schema layer. The drift detector flags that the agent is modifying files outside the task scope and producing output unrelated to query optimization.

**What could go wrong with recovery:**
- The "drift" was actually productive exploration that would have led to a genuine insight. Aggressive drift correction destroys serendipitous discovery. Mitigation: log the drifted content as a "tangential finding" that can be explored in a future task.
- The drift detection uses semantic similarity, which can be fooled by surface-level keyword matching. An agent discussing "BTC/ETH" but in a completely irrelevant context would pass the check. Mitigation: combine semantic similarity with goal-progress scoring.

[OSCILLATION_RISK] If the drift threshold is too tight, the agent gets redirected every few minutes and can never make progress. If too loose, drift is never caught. The threshold must be calibrated per task type, and there should be a cooldown period after each redirect (minimum 10 minutes before next drift check).

### RP5: Conflict Resolution

**Trigger:** Two agents produce contradictory outputs or attempt conflicting writes.

**Step-by-step procedure:**

1. **Detect:** Write conflict detected by DB constraint, or semantic conflict detected by validation layer.
2. **Pause:** Both agents are paused (if still running).
3. **Classify:**
   - **Write conflict:** Simple -- use last-writer-wins with version tracking, or first-writer-wins with retry.
   - **Semantic conflict:** Complex -- requires judgment about which output is correct.
4. **For write conflicts:** Apply optimistic concurrency control. The second writer gets a "conflict" error and must re-read the current state before retrying.
5. **For semantic conflicts:** Escalate to the allocator agent. Provide both outputs with evidence. The allocator decides which to accept, or assigns a tiebreaker task.
6. **If allocator cannot resolve:** Escalate to human.

**Concrete examples:**
- *Trading:* Researcher A concludes "funding rate arbitrage has a Sharpe of 2.1." Researcher B concludes "effective Sharpe < 0.5 due to execution slippage." The allocator reviews both briefs, determines Researcher B used more realistic assumptions, and marks A's brief as "superseded."
- *ML Research:* Agent A recommends "use ResNet-50 as backbone, best accuracy/speed tradeoff." Agent B recommends "use EfficientNet-B3, 2x faster at similar accuracy." The allocator reviews both benchmark results and selects the recommendation backed by stronger evidence.
- *SaaS:* Agent A proposes a microservice split for the billing module. Agent B proposes keeping it monolithic with better caching. The allocator evaluates both against the project's scalability requirements and decides.

**What could go wrong with recovery:**
- The allocator itself makes the wrong call. Mitigation: log the decision and reasoning so it can be audited.
- Pausing both agents causes downstream stalls. Mitigation: set a timeout on conflict resolution (15 minutes), after which the system picks the more conservative option and logs the decision.

### RP6: Resource Exhaustion Recovery

**Trigger:** Context window > 90% full, API rate limit hit, cost budget exceeded.

**Step-by-step procedure:**

1. **Context window exhaustion:**
   - Checkpoint current progress (write intermediate results to artifact).
   - Summarize the conversation so far into a compressed context.
   - Spawn a new agent session with the compressed context + original task.
   - This is effectively a "context window handoff."

2. **API rate limit:**
   - Check rate limit reset time from response headers.
   - If reset < 5 minutes: wait and retry.
   - If reset > 5 minutes: switch to alternate provider if available, or queue task for later.
   - Never busy-wait. Use the supervisor's scheduling system.

3. **Cost budget exceeded:**
   - Hard stop the agent.
   - Save whatever partial output exists.
   - Escalate to allocator: "Task X consumed $Y but is only Z% complete. Options: increase budget, simplify task, or abandon."

**Concrete examples:**
- *Trading:* The tester agent is running a walk-forward analysis with 12 windows. It has completed 8 windows and consumed 95% of its context window. The system checkpoints the 8 completed results to an artifact file, summarizes the analysis parameters, and spawns a continuation agent that picks up at window 9.
- *ML Research:* An experiment agent is running a 50-configuration hyperparameter sweep. After 30 configurations, it hits 90% context window. Partial results are checkpointed and a continuation agent resumes from configuration 31.
- *SaaS:* A code review agent is analyzing a 200-file PR. After reviewing 120 files, it hits the context limit. Review comments for the first 120 files are saved as an artifact, and a continuation agent handles the remaining 80 files.

**What could go wrong with recovery:**
- Context summarization loses critical details. The continuation agent misses something important from the first 8 windows. Mitigation: store full intermediate results in artifacts, not just in context. The continuation agent reads artifacts, not the summarized conversation.
- Cost estimation is inaccurate (e.g., streaming responses where cost is unknown until complete). Mitigation: estimate cost conservatively; use per-token pricing with a 20% safety margin.

[OSCILLATION_RISK] Context window handoff can itself consume significant tokens (summarization + re-contextualization). If the task requires more context than the window allows, repeated handoffs will oscillate: summarize -> work briefly -> exhaust -> summarize -> work briefly -> exhaust. Mitigation: if a task requires more than 2 handoffs, flag it as "too complex for single agent" and decompose into subtasks.

### RP7: Network/API Failure Recovery

**Trigger:** HTTP 5xx, connection timeout, DNS failure, provider outage.

**Step-by-step procedure:**

1. **Classify:** Transient (500, 502, 503, timeout) vs. permanent (provider deprecation, auth revoked).
2. **For transient failures:**
   - Retry with exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s.
   - Add jitter (random 0-1s) to prevent thundering herd.
   - Max 5 retries.
3. **For persistent failures (all retries exhausted):**
   - If alternate provider configured: failover (e.g., Claude -> GPT-4 -> Gemini).
   - If no alternate: pause agent, queue task, alert human.
4. **For extended outages (> 30 minutes):**
   - Activate degraded mode (see Graceful Degradation section).
   - Redistribute work to agents that can use available providers.

**What could go wrong with recovery:**
- Failover to a different LLM provider produces different quality output. A task designed for Claude may not work well with GPT-4. Mitigation: test critical prompts across providers; maintain provider-specific prompt variants.
- Thundering herd on provider recovery: all queued tasks hit the provider simultaneously when it comes back. Mitigation: staggered retry with random jitter.

---

## State Corruption Prevention & Recovery

### Prevention: Defense in Depth

**Layer 1: Schema Constraints (Database Level)**

Every table in the Agent OS database uses strict CHECK constraints, NOT NULL where appropriate, and foreign keys. The `db_tool.py` validates enum values before writes.

```sql
-- Example: core task table constraints
CHECK (status IN ('pending', 'assigned', 'in_progress', 'done', 'blocked', 'cancelled'))
-- Domain tables define their own CHECK constraints in project.yaml
```

**Concrete example of prevention:** An agent attempts to set a task status to `'completed'` (not a valid enum value -- the correct value is `'done'`). The CHECK constraint rejects the write. The `db_tool.py` catches this before it even hits SQLite and returns an error with the valid values.

**Layer 2: Application-Level Validation (Pre-Write)**

Before any agent writes to the database or artifacts, a validation function checks:
- Type correctness (numbers are numbers, dates are dates)
- Range plausibility (configurable per project -- e.g., accuracy between 0 and 1, latency > 0, counts non-negative)
- Referential integrity (parent record exists before creating a child record)
- Temporal consistency (end_date > start_date for any time-bounded entity)

**Layer 3: Write-Ahead Log + Transactions**

SQLite's WAL mode (already configured in the system) ensures that:
- Partial writes from crashed agents are automatically rolled back.
- Readers are never blocked by writers (important for multi-agent concurrent access).
- The database file is never in a corrupted state, even after power failure.

All agent writes must be wrapped in explicit transactions. A write that spans multiple tables (e.g., creating a parent record + its child records) is atomic.

**Layer 4: Artifact Versioning**

Every artifact write creates a new version rather than overwriting. Artifacts use timestamped filenames:
```
agent_comms/artifacts/strategies/momentum_v1_20260308T140000.json
agent_comms/artifacts/strategies/momentum_v2_20260308T153000.json
```

This allows rollback to any previous version if a corrupt artifact is detected.

### Recovery: When Corruption Gets Through

**Scenario 1: Detected at write time (constraint violation)**
- Write is rejected. Agent receives error. Agent can retry with corrected data.
- No corruption occurs.

**Scenario 2: Detected after write (validation catches it later)**
- Mark the record as `quarantined` (add a `quarantined_at` timestamp column).
- Trace all downstream reads of this record (using the activity log).
- For each downstream consumer: check if they used the corrupted data. If yes, quarantine their outputs too.
- Re-run affected tasks with corrected data.

**Concrete examples:**
- *Trading:* The researcher writes a hypothesis claiming "BTC dominance is at 78%." Range check passes (0-100% is valid). But 3 hours later, a monitoring sweep finds actual BTC dominance is 54%. The hypothesis is quarantined. Downstream work based on it is flagged for re-evaluation.
- *ML Research:* An experiment agent records "dataset has 50K samples" in the experiment log. A later validation check finds the actual dataset has 12K samples after deduplication. The experiment results based on the wrong sample count are quarantined.
- *SaaS:* A monitoring agent writes "service uptime was 99.99% this week." A ground-truth audit against the actual incident log finds two 15-minute outages, putting real uptime at 99.7%. The report is corrected.

**Scenario 3: Retroactive corruption (data looked OK but was wrong)**

This is the hardest case. The data was plausible at write time but turns out to be incorrect.

- Periodic "ground truth audits" compare key claims against external data sources.
- Projects configure which claims to spot-check via `project.yaml` under `validation_rules` -- e.g., a trading project checks statistics against market data, an ML project re-runs evaluation scripts, a SaaS project queries metrics stores.
- Findings that fail the spot-check trigger a cascade review (Scenario 2 above).

**Honest assessment:** Retroactive corruption detection is inherently incomplete. You cannot fact-check every claim an LLM makes. The strategy is to check the high-impact claims (the ones that drive downstream decisions) and accept that low-impact claims may be wrong. This is a cost-benefit tradeoff, not a guarantee.

---

## Hallucination Detection Strategies

### Honest Assessment

Hallucination detection in LLM outputs is genuinely hard. Current research (2025-2026) identifies several families of techniques, but none achieves reliability above ~85% on arbitrary text. The fundamental problem: an LLM can produce fluent, confident text that is completely wrong, and detecting this requires either ground truth data or another (potentially also hallucinating) system.

What follows are practical strategies ordered by reliability, with honest assessments of their limitations.

### Strategy 1: Ground Truth Comparison (Most Reliable)

**How it works:** Compare agent claims against known data. The specific ground truth sources are project-dependent -- market data for trading, evaluation metrics for ML, observability data for SaaS -- but the pattern is universal: if verifiable data exists, check the claim against it.

**Concrete examples:**
- *Trading:* The researcher claims "ETH/BTC correlation over the last 90 days is 0.92." The system loads actual price data, computes the correlation, and gets 0.67. Hard hallucination detected.
- *ML Research:* An agent claims "the fine-tuned model achieves BLEU score 42.3 on the test set." The system re-runs the evaluation script and gets BLEU 28.1. Hard hallucination detected.
- *SaaS:* An agent claims "the new index reduced query time from 800ms to 50ms." The system runs the benchmark query and measures 720ms. Hard hallucination detected.

**Reliability:** HIGH (~95%) when ground truth data is available.

**Limitation:** Only works when ground truth exists and is accessible. Cannot verify subjective claims ("this is a good approach"), forward-looking claims ("this will improve performance"), or claims about external events not in our data stores.

### Strategy 2: Schema + Range Validation (Reliable but Shallow)

**How it works:** Enforce structured output with strict schemas. Validate that numeric outputs fall within plausible ranges defined in the project's validation config.

**Concrete examples:**
- *Trading:* A strategy spec must include `max_position_size` as a float between 0.0 and 1.0. The agent outputs `max_position_size: 15.0`. Caught immediately.
- *ML Research:* An experiment report must include `accuracy` as a float between 0.0 and 1.0. The agent outputs `accuracy: 1.47`. Caught immediately.
- *SaaS:* A performance report must include `error_rate` as a float between 0.0 and 1.0. The agent outputs `error_rate: -0.03`. Caught immediately.

**Reliability:** HIGH (~98%) for what it covers.

**Limitation:** Only catches structural and extreme-value hallucinations. Cannot detect a `max_position_size: 0.5` that should actually be `0.05` -- both are in range.

### Strategy 3: Self-Consistency Checks (Moderate)

**How it works:** Ask the agent the same question multiple times (with slight rephrasing) and check if answers are consistent. Inconsistent answers suggest at least one is hallucinated.

**Concrete example:** Ask an agent the same quantitative question three times with different framings (e.g., "What is the optimal value for parameter X?"). If it answers 20, 50, and 14, the inconsistency suggests it is guessing rather than reasoning from data.

**Reliability:** MODERATE (~60-70%). Consistent wrong answers are not caught. The technique only detects uncertainty, not wrongness.

**Limitation:** Expensive (3x the API cost). Consistent hallucinations (the LLM confidently gives the same wrong answer every time) are not detected. Some legitimate questions have context-dependent answers that look inconsistent.

### Strategy 4: Cross-Agent Verification (Moderate, with Caveats)

**How it works:** Have a different agent (ideally using a different model) verify the output. The verifier gets the original task description and the output, and checks for correctness.

**Concrete example:** An agent produces a brief with a specific quantitative claim. A verifier agent (using a different model) is given this claim and asked to check it against available data. The verifier either confirms, refutes, or flags the claim as unverifiable. The result is treated as evidence, not proof.

**Reliability:** MODERATE (~55-65%). The verifier can also hallucinate. Using a different model helps but does not eliminate the risk.

**Limitation:** Two LLMs can converge on the same wrong answer, especially for plausible-sounding but incorrect claims. This is NOT the same as having two humans independently verify -- LLMs share training data biases. Cross-model verification (Claude checking GPT-4's work, or vice versa) is better than same-model verification but still imperfect.

### Strategy 5: Execution-Based Verification (High for Code, N/A for Text)

**How it works:** For code and quantitative claims, actually execute them and check the results.

**Concrete examples:**
- *Trading:* The coder claims "this strategy generates 150 trades on the test dataset." Run the backtest. If it generates 12 trades, the claim was hallucinated.
- *ML Research:* The agent claims "this training script converges in 10 epochs." Run the script. If it hasn't converged after 50 epochs, the claim was hallucinated.
- *SaaS:* The agent claims "all integration tests pass after the refactor." Run the test suite. If 8 tests fail, the claim was hallucinated.

This is the strongest form of verification for executable claims.

**Reliability:** HIGH (~95%) for executable claims.

**Limitation:** Only works for code and quantitative claims. Cannot verify qualitative research, subjective analysis, or strategic reasoning.

### Strategy 6: Confidence Calibration (Low, Research Stage)

**How it works:** Ask the LLM to rate its confidence in each claim. Filter out low-confidence claims.

**Reliability:** LOW (~40-50%). LLMs are notoriously poorly calibrated -- they express high confidence in wrong answers and sometimes low confidence in correct ones. Current research shows improvement with chain-of-thought prompting but calibration remains unreliable.

**Honest assessment:** Do not rely on this as a primary detection mechanism. Use it as a weak signal to prioritize which claims to verify with stronger methods.

### Recommended Hallucination Detection Stack

For the Agent OS, layer the strategies by cost-effectiveness:

1. **Always:** Schema + range validation on all structured outputs (cheap, fast, reliable for what it covers).
2. **Always:** Ground truth comparison where ground truth data exists (check statistics against actual data).
3. **For high-stakes outputs:** Execution-based verification (run the code, check the numbers).
4. **For research outputs:** Cross-agent verification using a different model provider, but treat the result as "additional evidence" not "proof."
5. **Never rely solely on:** Self-consistency or confidence calibration as primary filters.

---

## Self-Healing Architecture

### Design Principles

The self-healing architecture draws from Erlang/OTP's "let it crash" philosophy: rather than trying to prevent every possible failure (impossible), design the system to detect failures quickly and recover automatically. The system should be more reliable than any individual agent.

**Reference:** Erlang/OTP's supervisor trees have been battle-tested for 30+ years in telecom systems achieving 99.9999999% uptime (the "nine nines"). The key insight: individual processes (agents) are expected to crash. The supervisor tree ensures the system as a whole stays healthy.

### Component 1: Supervisor Tree

```
                    [System Supervisor]
                    /        |        \
           [Agent Pool]  [DB Health]  [API Health]
           /    |    \
      [Agent1] [Agent2] [Agent3]
```

**System Supervisor:** Top-level process that monitors all subsystems. If any subsystem fails entirely, it can restart the entire subsystem.

**Agent Pool Supervisor:** Manages all agent processes. Handles restart logic (RP1-RP2). Implements restart intensity limiting: if more than 5 agents crash within 60 seconds, something systemic is wrong -- halt all agents and alert human rather than restarting in a loop.

[OSCILLATION_RISK] The restart intensity limit is critical. Without it, a systemic issue (e.g., database locked, API down) causes all agents to crash and restart continuously. The limit acts as a circuit breaker on the supervisor itself.

**DB Health Monitor:** Checks database integrity periodically. Runs `PRAGMA integrity_check` every 30 minutes. Monitors WAL file size (large WAL = checkpointing is failing). Alerts if DB is locked for > 30 seconds.

**API Health Monitor:** Pings each configured LLM provider every 60 seconds. Maintains a health status per provider. Routes new agent sessions to healthy providers only.

### Component 2: Circuit Breakers

Adapted from the distributed systems pattern (Hystrix, Resilience4j), applied to agent-level operations.

**Circuit breaker per external dependency:**

- **LLM API circuit breaker:** Tracks failure rate of API calls. If > 50% of calls fail in a 60-second window, the circuit opens. No new API calls are attempted for 30 seconds (open state). After 30 seconds, one test call is allowed (half-open state). If it succeeds, circuit closes. If it fails, circuit stays open for another 60 seconds.

- **Data source circuit breaker:** Same pattern for any external data API configured in `project.yaml` (e.g., market data feeds, dataset registries, metrics endpoints).

- **Tool execution circuit breaker:** If a specific tool (e.g., `ruff check`) fails 3 times in a row across any agent, stop calling it system-wide and alert. It may be a broken installation, not an agent problem.

**Concrete example:** Anthropic's API starts returning 503 errors. After 5 failed calls in 30 seconds, the Claude circuit breaker opens. New agent tasks are routed to the GPT-4 fallback provider. Every 30 seconds, one test call is made to Claude. When Claude recovers, the circuit closes and new tasks resume using Claude.

### Component 3: Bulkhead Isolation

Agents are isolated from each other so that one failing agent cannot take down the system:

- **Process isolation:** Each agent runs in its own process with its own memory space. An agent OOM does not affect other agents.
- **Resource budgets:** Each agent has a maximum token budget, maximum runtime, and maximum number of tool calls. Exceeding any limit triggers graceful shutdown of that agent only.
- **Database connection pooling:** Each agent gets a limited number of database connections. A runaway agent doing excessive queries cannot exhaust the connection pool.
- **Filesystem isolation:** Agents can only write to their designated artifact directories. A buggy agent cannot overwrite another agent's output.

### Component 4: Dead Letter Queue

Tasks that fail repeatedly are not retried forever. They are moved to a dead letter queue:

```sql
CREATE TABLE dead_letter_tasks (
    id TEXT PRIMARY KEY,
    original_task_id TEXT NOT NULL,
    failure_count INTEGER NOT NULL,
    last_failure_reason TEXT,
    last_failure_at TEXT NOT NULL,
    task_snapshot TEXT NOT NULL,  -- JSON of the full task state at time of failure
    created_at TEXT DEFAULT (datetime('now')),
    resolved_at TEXT,            -- NULL until human resolves it
    resolution TEXT              -- 'retry', 'abandon', 'redesign'
);
```

**Rules:**
- After 3 failures on the same task: move to dead letter queue.
- After 5 failures on the same task type (across different tasks): flag the task type as potentially broken.
- Dead letter tasks require human resolution: retry (with modified parameters), abandon (accept the loss), or redesign (the task itself is flawed).

**Concrete example:** The coder agent fails 3 times trying to implement a task that uses a library not installed in the environment. Each time it crashes with `ModuleNotFoundError: No module named 'some_package'`. The task is moved to the dead letter queue with the error context. A human reviews it and either installs the missing dependency or redesigns the task to use an available library.

### Component 5: Saga-Style Compensation

For multi-step workflows, failures in later steps should trigger compensation in earlier steps. The specific pipeline stages are defined by the project's plan templates (see `project.yaml`), but the compensation pattern is universal.

**Example pipelines as sagas:**

```
# Trading: Research -> Review -> Design -> Implement -> Backtest -> Evaluate -> Deploy
# ML Research: Hypothesis -> Experiment Design -> Training -> Evaluation -> Publication
# SaaS: Spec -> Implement -> Test -> Review -> Deploy -> Monitor
```

**Compensation chain (if a late-stage validation fails):**
1. Validation step fails against acceptance criteria (configurable per project).
2. The implementation artifact is marked as failed.
3. The design/spec task is reopened for revision (compensation: re-examine the approach).
4. The originating hypothesis or requirement is downgraded from `approved` to `needs_revision`.
5. The upstream agent is notified to check their assumptions.

This prevents a flawed starting assumption from consuming resources repeatedly across the full pipeline.

**Concrete examples:**
- *Trading:* A mean-reversion strategy is implemented, backtested, and achieves Sharpe 0.3 against a threshold of 1.5. Saga compensation triggers: strategy marked failed, quant asked to revise parameters, hypothesis flagged for re-evaluation.
- *ML Research:* A model architecture is designed, trained, and achieves F1 0.42 against a threshold of 0.75. Compensation triggers: model config marked failed, experiment design reopened, original hypothesis about feature relevance flagged.
- *SaaS:* A new API endpoint is implemented, tested, and fails load testing at 200 rps against a 1000 rps target. Compensation triggers: implementation marked failed, design spec reopened for architectural revision.

[OSCILLATION_RISK] If the compensation logic automatically resubmits the upstream work and it gets re-approved with slightly different framing, the system enters a loop: design -> implement -> validate fail -> compensate -> redesign -> implement -> ... Mitigation: track the number of compensation cycles per goal. After 2 full cycles without passing validation, the goal is marked `exhausted` and requires human override to reopen.

---

## Learning from Failure (Feedback Loop Design)

### Storage Format

Failure records are stored in a dedicated table with structured, queryable fields:

```sql
CREATE TABLE failure_log (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),

    -- What failed
    agent_id TEXT NOT NULL,
    agent_role TEXT NOT NULL,          -- project-defined roles (e.g., 'researcher', 'coder', 'tester')
    task_id TEXT,
    task_type TEXT,                    -- project-defined types (e.g., 'research', 'implementation', 'review')

    -- Failure classification
    failure_type TEXT NOT NULL,        -- 'crash', 'hang', 'hallucination', 'drift', 'conflict',
                                      -- 'resource_exhaustion', 'api_failure', 'corruption'
    failure_subtype TEXT,              -- More specific: 'oom', 'context_window', 'rate_limit', etc.
    severity TEXT NOT NULL,            -- 'low', 'medium', 'high', 'critical'

    -- Context
    error_message TEXT,
    stack_trace TEXT,
    input_summary TEXT,               -- What was the agent working on (truncated)
    output_summary TEXT,              -- What did it produce before failing (truncated)

    -- Recovery
    recovery_action TEXT,             -- 'restart', 'reassign', 'escalate', 'abandon', 'compensate'
    recovery_successful INTEGER,      -- 0 or 1
    recovery_notes TEXT,

    -- Learning
    root_cause TEXT,                  -- Diagnosed after the fact (may be NULL initially)
    prevention_hint TEXT,             -- "Next time, try X" (may be NULL initially)
    similar_failure_ids TEXT          -- JSON array of related failure IDs
);

CREATE INDEX idx_failure_type ON failure_log(failure_type);
CREATE INDEX idx_task_type ON failure_log(task_type);
CREATE INDEX idx_agent_role ON failure_log(agent_role);
CREATE INDEX idx_timestamp ON failure_log(timestamp);
```

### Retrieval Mechanism

When an agent starts a new task, the system queries the failure log for relevant past failures:

```sql
-- Before assigning a research task to the researcher:
SELECT failure_type, error_message, prevention_hint, recovery_action
FROM failure_log
WHERE task_type = 'research'
  AND recovery_successful = 1
  AND prevention_hint IS NOT NULL
ORDER BY timestamp DESC
LIMIT 5;
```

The results are injected into the agent's system prompt as a "lessons learned" section:

```
## Lessons from Past Failures (auto-generated)
- Previous research tasks have failed due to hallucinated statistics. Always
  cross-reference numeric claims against available ground-truth data before
  including them in your output.
- A previous agent drifted into tangential analysis when tasked with a focused
  investigation. Stay focused on the assigned topic.
- Rate limiting on an external API caused a hang. Use a 1-second delay between
  API calls to external data sources.
```

### Pattern Detection

A periodic analysis job (run at a configurable interval, e.g., daily or at the start of each project cycle) identifies recurring failure patterns:

```sql
-- Find the most common failure types in the last 7 days
SELECT failure_type, failure_subtype, task_type, COUNT(*) as count,
       GROUP_CONCAT(DISTINCT prevention_hint) as hints
FROM failure_log
WHERE timestamp > datetime('now', '-7 days')
GROUP BY failure_type, failure_subtype, task_type
HAVING count >= 3
ORDER BY count DESC;
```

If a pattern is detected (same failure type >= 3 times in 7 days), the system:
1. Escalates to the allocator with a summary.
2. Suggests a systemic fix (e.g., "coder agents keep failing on TA-Lib imports -- consider adding it to the environment").
3. Updates the relevant agent prompt with a permanent warning.

### Concrete Example of the Full Feedback Loop

1. **Failure occurs:** The coder agent crashes while implementing a task because it tries to import a package not installed in the environment. Error: `ModuleNotFoundError`.
2. **Logged:** `failure_type='crash', failure_subtype='import_error', error_message='ModuleNotFoundError: some_package', task_type='implementation'`.
3. **Recovery:** Task restarted. Coder tries again, same error. After 3 attempts, task goes to dead letter queue.
4. **Root cause diagnosed:** Human reviews and installs the missing package. Sets `root_cause='missing_dependency'`, `prevention_hint='Check that all imports are available in the environment before writing code that depends on them. Available packages: [list]'`.
5. **Next time:** When the next implementation task is assigned to a coder agent, the prompt includes: "Check that all imports are available in the environment before writing code that depends on them. If you need a package that is not installed, flag it in your implementation plan for approval."
6. **Pattern detection:** After 3 `import_error` failures across different tasks, the system alerts the allocator: "Recurring import errors suggest the development environment is missing common packages. Consider a dependency audit."

---

## Graceful Degradation Model

### Degradation Levels

| Level | Condition | Available Capabilities | Response |
|-------|-----------|----------------------|----------|
| **L0: Nominal** | All systems healthy | Full autonomy, all agents active | Normal operation |
| **L1: Degraded** | One provider down, or one agent type failing | Reduced parallelism, failover to alternate providers | Reroute work, extend timelines |
| **L2: Limited** | Multiple providers down, DB degraded | Single-agent operation, read-only DB access | Critical tasks only, queue non-critical |
| **L3: Emergency** | Primary DB unavailable or corrupted | No agent operations | Human intervention required, system halt |
| **L4: Recovery** | Recovering from L2/L3 | Gradual restart, validation of state | Verify integrity before resuming |

### Minimum Viable System

The absolute minimum: **1 agent process + SQLite database + 1 LLM provider = functional system.**

In this configuration:
- The single agent acts as allocator and worker (reduced quality but functional).
- The database provides persistence and state management.
- The system can execute one task at a time, sequentially.
- No parallelism, no cross-validation, no conflict detection (only one agent).
- Safety-critical autonomous operations are paused (too risky without full monitoring -- e.g., live trading, production deployments, unattended training runs).

### Priority-Based Resource Allocation During Degradation

When resources are constrained, tasks are prioritized. Priority tiers are configurable per project in `project.yaml` under `degradation_priorities`. Default tiers:

1. **Critical:** Safety-critical monitoring tasks (must continue -- e.g., risk monitoring in trading, production health checks in SaaS, active experiment safeguards in ML).
2. **High:** Completing in-progress work with significant sunk cost (e.g., long-running evaluations, multi-step pipelines past the halfway point).
3. **Medium:** New work that can be deferred without loss (e.g., new research, design tasks, non-urgent feature work).
4. **Low:** Dashboard updates, report generation, documentation (cosmetic).

During L1 degradation, low-priority tasks are paused. During L2, only critical tasks run.

### Provider Failover Matrix

The failover matrix is configured per project in `project.yaml` under `provider_failover`. LLM provider failover is universal; data source failover is project-specific.

| Dependency Type | Primary (example) | Failover 1 (example) | Failover 2 (example) | Notes |
|----------------|-------------------|---------------------|---------------------|-------|
| LLM Provider | Claude (Anthropic) | GPT-4 (OpenAI) | Gemini (Google) | Prompt adaptation may be needed |
| Data Source | Project-specific API | Alternate source | Local cached data | Reduced freshness |
| Tool/Service | Primary instance | Backup instance | Degraded fallback | Feature parity may vary |

### Concrete Degradation Scenario

**Situation:** The primary LLM provider experiences a 2-hour outage during active work.

**System response:**
1. Circuit breaker on the primary provider opens after 5 failed calls.
2. System transitions to L1 degradation.
3. Running agents on the primary provider are paused. Their current task state is checkpointed.
4. New tasks are assigned to agents using the configured failover provider.
5. Critical-priority tasks (per project config) switch to failover immediately.
6. Medium-priority tasks are queued for when the primary provider returns.
7. API health monitor pings the primary provider every 60 seconds.
8. After 2 hours, the provider responds. Circuit breaker enters half-open. Test call succeeds.
9. Circuit closes. Queued tasks resume on the primary provider. Paused agents are restarted.
10. System transitions back to L0 nominal.

---

## Open Questions

1. **Hallucination detection ceiling:** What is the realistic upper bound on hallucination detection accuracy for arbitrary LLM outputs? Current research suggests ~85% for structured outputs and much lower for free-text. Is this good enough for autonomous operation, or does it require human-in-the-loop for high-stakes outputs indefinitely?

2. **Supervisor cost:** Running heartbeat checks, progress monitors, circuit breakers, and validation layers adds overhead. How much system resource (tokens, compute, latency) does the self-healing infrastructure itself consume? Is there a point where the monitoring cost exceeds the cost of occasional failures?

3. **Cross-model hallucination correlation:** When using cross-agent verification with different models (Claude checking GPT-4's work), how correlated are their hallucinations? If both models were trained on similar data, they may converge on the same wrong answers. Empirical measurement is needed.

4. **Drift detection calibration:** Semantic similarity thresholds for drift detection need to be calibrated per task type. Research tasks have legitimate tangential exploration; implementation tasks should stay very focused. How do we set these thresholds without extensive trial-and-error? [OSCILLATION_RISK] if thresholds are auto-adjusted based on outcomes.

5. **Failure log scaling:** Over months of operation, the `failure_log` table will grow large. How do we summarize old failures without losing the lessons? A periodic "failure knowledge consolidation" that converts individual failure records into general rules?

6. **Compensation depth:** In the saga pattern for multi-step pipelines, how deep should compensation go? If a late-stage failure traces back to a hallucinated upstream output, should the system re-evaluate the full chain? This could be unbounded.

7. **Byzantine agents:** What if an agent is not just wrong but adversarial (due to prompt injection through artifacts)? The current design assumes honest-but-fallible agents. Defending against actively adversarial agents is a different (harder) problem covered in the security research (Agent 06).

8. **Recovery testing:** How do we test the self-healing mechanisms themselves? Chaos engineering (intentionally crashing agents, corrupting data, simulating outages) is the standard approach, but it is expensive and risky in a system that manages real workloads with external effects (deployments, trades, published outputs). A staging environment for failure testing is needed.

---

## Sources

- [Building Resilient Systems: Circuit Breakers and Retry Patterns](https://dasroot.net/posts/2026/01/building-resilient-systems-circuit-breakers-retry-patterns/)
- [Resilient Microservices: A Systematic Review of Recovery Patterns](https://arxiv.org/html/2512.16959v1)
- [Microservices.io: Circuit Breaker Pattern](https://microservices.io/patterns/reliability/circuit-breaker.html)
- [Microsoft Azure: Bulkhead Pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/bulkhead)
- [Bulkhead Pattern in Microservices](https://www.systemdesignacademy.com/blog/bulkhead-pattern)
- [Erlang/OTP Supervisor Behaviour](https://www.erlang.org/doc/system/sup_princ.html)
- [Riak and Erlang/OTP - Architecture of Open Source Applications](https://aosabook.org/en/v1/riak.html)
- [Temporal: Mastering Saga Patterns for Distributed Transactions](https://temporal.io/blog/mastering-saga-patterns-for-distributed-transactions-in-microservices)
- [Microsoft Azure: Saga Design Pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/saga)
- [SQLite Write-Ahead Logging](https://sqlite.org/wal.html)
- [How To Corrupt An SQLite Database File](https://sqlite.org/howtocorrupt.html)
- [Dead Letter Queue - Design for Failure](https://ctaverna.github.io/dead-letters/)
- [AI Hallucinations in Agentic Systems (2026)](https://medium.com/@yash.mishra0501/ai-hallucinations-are-getting-smarter-heres-how-to-catch-them-in-real-time-even-in-agentic-3d75a9fc1ab3)
- [LLM-based Agents Suffer from Hallucinations: A Survey](https://arxiv.org/html/2509.18970v1)
- [Agent Drift: Quantifying Behavioral Degradation in Multi-Agent LLM Systems](https://arxiv.org/html/2601.04170v1)
- [The Silent Failures: When AI Agents Break Without Alerts](https://medium.com/@milesk_33/the-silent-failures-when-ai-agents-break-without-alerts-23a050488b16)
- [Workshop on Reliable Agentic AI: From Hallucination to Trustworthy Autonomy](https://hallucination-reliable-agentic-ai.github.io/)
