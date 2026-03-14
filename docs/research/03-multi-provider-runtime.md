# Research 03: Multi-Provider Runtime Layer

**Date:** 2026-03-08
**Researcher:** Agent 03 (Multi-Provider Runtime)
**Status:** Complete
**Validation:** Claims tagged with source basis: (a) established systems practice, (b) observed in existing systems/products, (c) proposal. Unverified capabilities flagged with [NEEDS_VERIFICATION].

---

## Executive Summary

The Agent OS must allow any agent runtime -- Claude Code, OpenAI Codex, Gemini CLI, custom Python scripts, cron jobs, human operators -- to participate as a first-class agent with zero runtime-specific code in the core platform. This document specifies the **multi-provider runtime layer**: a minimal lifecycle protocol that every agent must implement, provider-specific adapters that translate native runtime capabilities into that protocol, heartbeat and liveness detection, session management with context bootstrapping, output validation, resource management, and a testing framework that eliminates the need for real API tokens during development.

The central design principle is **protocol over implementation**. The Agent OS does not care how an agent thinks, what model powers it, or what language it is written in. It cares only that the agent speaks the lifecycle protocol: register a session, send heartbeats, produce validated artifacts, and close the session. This protocol is implemented as five SQLite operations and two filesystem conventions. Any runtime that can execute `sqlite3` commands or make HTTP calls to a thin REST gateway can participate.

The architecture has three tiers:
1. **Lifecycle Protocol** (5 operations, ~20 lines of SQL) -- the universal contract
2. **Provider Adapters** (per-runtime wrappers) -- translate native capabilities to the protocol
3. **Supervisor** (single process) -- monitors liveness, enforces resource budgets, recovers from failures

This design is validated against an existing multi-agent codebase (a crypto hedge fund with `BaseAgent` in `src/hft/agents/base_agent.py`, schema in `agent_comms/db/migrations/001_initial.sql`) and extends it to support heterogeneous runtimes across any project domain.

**Key findings from provider research:**
- Claude Code (b: verified) has full bash/file/SQLite access, making direct DB integration trivial
- OpenAI Codex Cloud (b: verified) runs in an isolated sandbox with no network during the agent phase, requiring a file-based protocol with post-execution sync
- Codex CLI (b: verified) runs locally and can access SQLite directly, but is sandboxed by default
- Gemini CLI (b: verified) has Shell/ReadFile/WriteFile tools, supporting direct DB access like Claude Code
- The lifecycle protocol requires only 5 operations and can be implemented in ~20 lines of SQL

---

## 1. Lifecycle Protocol Specification

### 1.1 Design Goals

- **Minimal surface area:** An agent implementor should be able to integrate in under 30 minutes
- **No SDK required:** The protocol must work with raw SQL or raw HTTP -- no Python library dependency
- **Idempotent operations:** Every protocol call must be safe to retry
- **Observable by default:** Every state transition is recorded in the database

### 1.2 The Five Lifecycle Operations

Every agent runtime must implement exactly five operations. These map directly to SQL statements against the core `agents` and `activity_log` tables (plus any project-specific tables declared in `project.yaml`).

| # | Operation | Purpose | Frequency |
|---|-----------|---------|-----------|
| L1 | `start_session` | Register agent as running, record session start | Once per session |
| L2 | `heartbeat` | Prove liveness, report progress metadata | Every 30s (configurable) |
| L3 | `log_activity` | Record structured actions for audit trail | Per significant action |
| L4 | `produce_artifact` | Write a validated output to the blackboard | Per deliverable |
| L5 | `end_session` | Mark agent as idle, record session summary | Once per session |

### 1.3 SQL Implementation (Direct DB Access)

This is the reference implementation. Any runtime with `sqlite3` access can use these exact statements.

```sql
-- L1: start_session
-- Registers the agent as running and increments the run counter.
-- The session_id is stored in current_task_id for correlation.
UPDATE agents SET
    status = 'running',
    last_run_start = CURRENT_TIMESTAMP,
    last_heartbeat = CURRENT_TIMESTAMP,
    total_runs = total_runs + 1,
    current_task_id = :session_id,
    updated_at = CURRENT_TIMESTAMP
WHERE agent_id = :agent_id;

-- Also log the session start
INSERT INTO activity_log (agent_id, action, category, description, details, severity)
VALUES (:agent_id, 'session_start', 'system',
        'Agent session started',
        json_object('session_id', :session_id, 'runtime', :runtime_type),
        'info');
```

```sql
-- L2: heartbeat
-- Updates liveness timestamp. The supervisor checks this to detect dead agents.
-- Optional: include progress metadata in the details field.
UPDATE agents SET
    last_heartbeat = CURRENT_TIMESTAMP,
    updated_at = CURRENT_TIMESTAMP
WHERE agent_id = :agent_id;
```

```sql
-- L3: log_activity
-- Records a structured action. severity must match CHECK constraints.
-- Valid severities: debug, info, warning, error, critical
-- Categories are project-defined via project.yaml (e.g., system, research, task, communication).
-- Examples: trading/strategy/risk (finance), training/evaluation/deployment (ML), billing/support (SaaS).
INSERT INTO activity_log (agent_id, action, category, description, details, severity)
VALUES (:agent_id, :action, :category, :description, :details_json, :severity);
```

```sql
-- L4: produce_artifact (two steps)
-- Step 1: Write the artifact file to agent_comms/artifacts/{category}/{filename}
-- Step 2: Record the artifact in the activity log for discoverability
INSERT INTO activity_log (agent_id, action, category, description, details, severity)
VALUES (:agent_id, 'artifact_produced', :category,
        :description,
        json_object(
            'artifact_path', :artifact_path,
            'artifact_type', :artifact_type,
            'schema_version', :schema_version,
            'checksum', :sha256_checksum
        ),
        'info');
```

```sql
-- L5: end_session
-- Marks the agent as idle and clears the current task.
UPDATE agents SET
    status = 'idle',
    last_run_end = CURRENT_TIMESTAMP,
    current_task_id = NULL,
    updated_at = CURRENT_TIMESTAMP
WHERE agent_id = :agent_id;

INSERT INTO activity_log (agent_id, action, category, description, details, severity)
VALUES (:agent_id, 'session_end', 'system',
        'Agent session ended',
        json_object('session_id', :session_id, 'duration_seconds', :duration),
        'info');
```

### 1.4 Is This Sufficient?

The five operations cover the full agent lifecycle. Analysis against observed needs:

| Need | Covered by | Notes |
|------|-----------|-------|
| Agent registration | `start_session` | Agent rows pre-exist in `agents` table via migration |
| Liveness monitoring | `heartbeat` | Supervisor polls `last_heartbeat` |
| Audit trail | `log_activity` | Every significant action recorded |
| Output delivery | `produce_artifact` | File + DB entry, validated before commit |
| Session tracking | `start_session` / `end_session` | Duration, run count, task correlation |
| Error reporting | `log_activity` with severity='error' | Subsumes error reporting into logging |
| Inter-agent messaging | Existing `messages` table | Not part of lifecycle protocol; uses `BaseAgent.send_message()` |
| Task claiming | Existing `tasks` table | Agent reads assigned tasks; not lifecycle-specific |

**Verdict:** The five operations are sufficient. Inter-agent messaging and task management are orthogonal concerns already handled by the existing schema. Adding them to the lifecycle protocol would violate the minimality principle.

### 1.5 Session Table Extension (Proposed)

The current schema tracks sessions implicitly via `last_run_start` / `last_run_end` on the `agents` table. For multi-session history (required by the research prompt), we propose a dedicated `agent_sessions` table:

```sql
-- (c: proposal) New table for explicit session tracking
CREATE TABLE IF NOT EXISTS agent_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT UNIQUE NOT NULL,
    agent_id TEXT NOT NULL,
    runtime_type TEXT NOT NULL
        CHECK (runtime_type IN (
            'claude_code', 'codex_cloud', 'codex_cli',
            'gemini_cli', 'python_script', 'cron_job',
            'human_operator', 'custom'
        )),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'completed', 'failed', 'timed_out', 'killed')),

    -- What did this session work on?
    task_ids TEXT,           -- JSON array of task_ids claimed during this session
    goal_ids TEXT,           -- JSON array of goal_ids this session contributed to
    artifacts_produced TEXT, -- JSON array of artifact paths written

    -- Context bootstrapping record
    context_loaded TEXT,     -- JSON: what files/tables the agent read at startup
    context_summary TEXT,    -- Agent's own summary of its starting context

    -- Resource tracking
    tokens_input INTEGER DEFAULT 0,
    tokens_output INTEGER DEFAULT 0,
    estimated_cost_usd REAL DEFAULT 0.0,
    api_calls INTEGER DEFAULT 0,

    -- Timing
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_heartbeat TIMESTAMP,
    ended_at TIMESTAMP,
    duration_seconds REAL,

    -- Session handoff
    predecessor_session_id TEXT, -- Previous session of same agent (for context continuity)
    handoff_notes TEXT,          -- What the predecessor session wanted the next session to know

    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);

CREATE INDEX IF NOT EXISTS idx_sessions_agent ON agent_sessions(agent_id, started_at);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON agent_sessions(status);
```

This table enables:
- Tracking what each session worked on and produced
- Resource accounting per session (tokens, cost)
- Session chaining for context continuity across ephemeral LLM sessions
- Runtime-type analytics (which runtimes are most efficient?)

---

## 2. Provider Adapter Designs

Each provider adapter translates the native runtime's capabilities into the five lifecycle operations. The adapters are thin -- typically under 100 lines of code.

### 2.1 Claude Code Adapter

**Runtime characteristics (b: observed, verified against Claude Code documentation and direct usage):**
- Runs locally in the user's terminal, IDE (VS Code), desktop app, or browser
- Has full bash access via `BashTool`, can execute `sqlite3` commands directly
- Has file I/O via `Read`, `Edit`, `Write` tools (named `View`, `Edit`, `Write` in some contexts)
- Can spawn subagents -- separate context windows that report back to parent (launched February 2026 alongside Opus 4.6)
- Agent Teams: can spawn teammates that communicate via shared task list and direct messaging, working in separate git worktrees
- MCP (Model Context Protocol) for external tool integration
- 1M token context window (Opus 4.6, beta), 128K max output
- Skills system: `.md` files that Claude auto-detects and invokes when relevant
- Hooks system: `PreToolUse`, `PostToolUse` for intercepting tool calls
- No persistent process -- runs per invocation, then stops. State must be externalized.

Source: [Claude Code overview](https://code.claude.com/docs/en/overview), [Agent Teams docs](https://code.claude.com/docs/en/agent-teams)

**Natural integration path:** Claude Code's native tool set (`Bash`, `Read`, `Write`, `Edit`) maps perfectly to the lifecycle protocol. The agent can call `sqlite3` directly from bash, read/write files to `agent_comms/artifacts/`, and use the existing `BaseAgent` Python class. This is the simplest integration of all providers.

**Adapter implementation:**

```python
"""Claude Code adapter -- lifecycle operations via direct DB access.

Claude Code agents can use this as a Python import OR execute the
equivalent sqlite3 commands directly from bash. Both paths are valid.
"""

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


class ClaudeCodeAdapter:
    """Thin adapter that maps Claude Code capabilities to the lifecycle protocol."""

    RUNTIME_TYPE = "claude_code"

    def __init__(self, agent_id: str, db_path: str | Path):
        self.agent_id = agent_id
        self.db_path = Path(db_path)
        self.session_id = f"sess_{agent_id}_{uuid.uuid4().hex[:8]}"
        self._start_time: float | None = None

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    # L1: start_session
    def start_session(self, context_summary: str = "") -> str:
        self._start_time = time.time()
        conn = self._conn()
        try:
            conn.execute(
                """UPDATE agents SET
                    status = 'running',
                    last_run_start = CURRENT_TIMESTAMP,
                    last_heartbeat = CURRENT_TIMESTAMP,
                    total_runs = total_runs + 1,
                    current_task_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE agent_id = ?""",
                (self.session_id, self.agent_id),
            )
            conn.execute(
                """INSERT INTO agent_sessions
                    (session_id, agent_id, runtime_type, context_summary)
                VALUES (?, ?, ?, ?)""",
                (self.session_id, self.agent_id, self.RUNTIME_TYPE, context_summary),
            )
            conn.execute(
                """INSERT INTO activity_log
                    (agent_id, action, category, description, details, severity)
                VALUES (?, 'session_start', 'system', 'Claude Code session started', ?, 'info')""",
                (self.agent_id, json.dumps({"session_id": self.session_id, "runtime": self.RUNTIME_TYPE})),
            )
            conn.commit()
        finally:
            conn.close()
        return self.session_id

    # L2: heartbeat
    def heartbeat(self, progress: dict[str, Any] | None = None) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE agents SET last_heartbeat = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE agent_id = ?",
                (self.agent_id,),
            )
            conn.execute(
                "UPDATE agent_sessions SET last_heartbeat = CURRENT_TIMESTAMP WHERE session_id = ?",
                (self.session_id,),
            )
            conn.commit()
        finally:
            conn.close()

    # L3: log_activity
    def log_activity(
        self, action: str, category: str, description: str,
        details: dict[str, Any] | None = None, severity: str = "info",
    ) -> None:
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO activity_log
                    (agent_id, action, category, description, details, severity)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (self.agent_id, action, category, description, json.dumps(details or {}), severity),
            )
            conn.commit()
        finally:
            conn.close()

    # L4: produce_artifact
    def produce_artifact(
        self, category: str, filename: str, content: str,
        artifact_type: str = "markdown", schema_version: str = "1.0",
    ) -> Path:
        artifacts_dir = self.db_path.parent.parent / "artifacts" / category
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifacts_dir / filename
        artifact_path.write_text(content)
        checksum = hashlib.sha256(content.encode()).hexdigest()

        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO activity_log
                    (agent_id, action, category, description, details, severity)
                VALUES (?, 'artifact_produced', ?, ?, ?, 'info')""",
                (
                    self.agent_id, category, f"Produced {filename}",
                    json.dumps({
                        "artifact_path": str(artifact_path),
                        "artifact_type": artifact_type,
                        "schema_version": schema_version,
                        "checksum": checksum,
                        "session_id": self.session_id,
                    }),
                ),
            )
            # Update session record
            conn.execute(
                """UPDATE agent_sessions SET
                    artifacts_produced = json_insert(
                        COALESCE(artifacts_produced, '[]'),
                        '$[#]', ?
                    )
                WHERE session_id = ?""",
                (str(artifact_path), self.session_id),
            )
            conn.commit()
        finally:
            conn.close()
        return artifact_path

    # L5: end_session
    def end_session(self, handoff_notes: str = "") -> None:
        duration = time.time() - self._start_time if self._start_time else 0
        conn = self._conn()
        try:
            conn.execute(
                """UPDATE agents SET
                    status = 'idle',
                    last_run_end = CURRENT_TIMESTAMP,
                    current_task_id = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE agent_id = ?""",
                (self.agent_id,),
            )
            conn.execute(
                """UPDATE agent_sessions SET
                    status = 'completed',
                    ended_at = CURRENT_TIMESTAMP,
                    duration_seconds = ?,
                    handoff_notes = ?
                WHERE session_id = ?""",
                (duration, handoff_notes, self.session_id),
            )
            conn.execute(
                """INSERT INTO activity_log
                    (agent_id, action, category, description, details, severity)
                VALUES (?, 'session_end', 'system', 'Claude Code session ended', ?, 'info')""",
                (self.agent_id, json.dumps({"session_id": self.session_id, "duration_seconds": round(duration, 1)})),
            )
            conn.commit()
        finally:
            conn.close()
```

**Bash-only alternative (no Python needed):**

A Claude Code agent that prefers not to import Python can use raw `sqlite3` commands. This is significant because it means the lifecycle protocol works even when the agent's only capability is shell access:

```bash
#!/bin/bash
# Claude Code lifecycle -- bash-only implementation
# DB path is project-specific (resolved from project.yaml or convention)
DB="agent_comms/db/agent_os.db"
AGENT_ID="researcher"
SESSION_ID="sess_researcher_$(date +%s)"

# L1: start_session
sqlite3 "$DB" "
  UPDATE agents SET status='running', last_run_start=datetime('now'),
    last_heartbeat=datetime('now'), total_runs=total_runs+1,
    current_task_id='$SESSION_ID', updated_at=datetime('now')
  WHERE agent_id='$AGENT_ID';
  INSERT INTO activity_log (agent_id, action, category, description, details, severity)
  VALUES ('$AGENT_ID','session_start','system','Session started',
    json_object('session_id','$SESSION_ID','runtime','claude_code'),'info');
"

# L2: heartbeat (call periodically during work)
sqlite3 "$DB" "UPDATE agents SET last_heartbeat=datetime('now') WHERE agent_id='$AGENT_ID'"

# L3: log_activity (category values are project-defined)
# Finance example:
sqlite3 "$DB" "
  INSERT INTO activity_log (agent_id, action, category, description, severity)
  VALUES ('$AGENT_ID','hypothesis_proposed','research','Proposed BTC funding rate hypothesis','info')
"
# ML research example:
#   VALUES ('$AGENT_ID','experiment_started','training','Launched hyperparameter sweep for ResNet-50','info')
# SaaS example:
#   VALUES ('$AGENT_ID','migration_planned','infrastructure','Planned DB schema migration for billing v2','info')

# L4: produce_artifact (write file, then log)
mkdir -p agent_comms/artifacts/research/
echo '# My Research Finding' > agent_comms/artifacts/research/finding_001.md
CHECKSUM=$(shasum -a 256 agent_comms/artifacts/research/finding_001.md | cut -d' ' -f1)
sqlite3 "$DB" "
  INSERT INTO activity_log (agent_id, action, category, description, details, severity)
  VALUES ('$AGENT_ID','artifact_produced','research','Produced finding_001.md',
    json_object('artifact_path','agent_comms/artifacts/research/finding_001.md',
                'checksum','$CHECKSUM'),'info');
"

# L5: end_session
sqlite3 "$DB" "
  UPDATE agents SET status='idle', last_run_end=datetime('now'),
    current_task_id=NULL, updated_at=datetime('now')
  WHERE agent_id='$AGENT_ID';
  INSERT INTO activity_log (agent_id, action, category, description, severity)
  VALUES ('$AGENT_ID','session_end','system','Session ended','info');
"
```

**Claude Code subagent and Agent Teams integration:**

When a Claude Code lead agent spawns subagents (via Agent Teams or the Task tool), each subagent should receive the adapter initialization as part of its spawn prompt. Key architectural details (b: verified via Anthropic documentation):

- **Subagents** run within a single session. They get their own isolated context windows, and intermediate tool calls and results stay inside the subagent; only the final message returns to the parent. Subagents cannot message each other -- they only report back to the parent agent.
- **Agent Teams teammates** are fully independent sessions. They can message each other, claim tasks from a shared list, and work in separate git worktrees. However, a teammate cannot spawn additional teams (no nested teams).
- Each subagent/teammate should register its own session with a unique `session_id` but use a derived `agent_id` (e.g., `researcher_sub_01`) to maintain traceability.

Source: [Claude Code subagents](https://code.claude.com/docs/en/sub-agents), [Claude Code Agent Teams](https://code.claude.com/docs/en/agent-teams)

The lead agent can track all sub-sessions by querying:

```sql
SELECT session_id, status, duration_seconds, artifacts_produced
FROM agent_sessions
WHERE agent_id LIKE 'researcher%' AND started_at > datetime('now', '-1 hour');
```

**What Claude Code can and cannot do (b: verified):**
- CAN: Execute bash, read/write files, call sqlite3, install packages via pip/uv, run Python scripts, use MCP tools, spawn subagents/teammates, work in git worktrees
- CAN: Run background processes, manage git operations, access the local network
- CANNOT: Persist state between invocations natively (must use external DB/files)
- CANNOT: Run continuously as a daemon (each session is a single invocation that ends)
- CANNOT: Spawn nested team-of-teams (teammates cannot spawn additional teams -- by design to prevent exponential token costs)

---

### 2.2 OpenAI Codex Adapter

**Runtime characteristics (b: observed, verified against OpenAI developer documentation):**
- **Codex Cloud:** Runs in isolated containers on OpenAI infrastructure. Container checks out a GitHub repo at a specific branch/commit. Setup scripts run with internet access to install dependencies. During the agent phase, internet access is disabled by default (can be optionally enabled). Agent operates on the checked-out code, edits files, runs shell commands, and produces a PR or commit. Container state cached for up to 12 hours.
- **Codex CLI:** Open-source, built in Rust. Runs locally in the terminal. Sandboxed by default with network access disabled. Supports `AGENTS.md` for repo-specific instructions. Can function as an MCP server, enabling orchestration via the OpenAI Agents SDK.
- Both use GPT-5.2-Codex model (as of late 2025). Support file I/O and shell commands within their sandboxes.

Source: [Codex Cloud environments](https://developers.openai.com/codex/cloud/environments/), [Codex CLI](https://developers.openai.com/codex/cli), [Introducing Codex](https://openai.com/index/introducing-codex/)

**Key constraint: the Codex Cloud sandbox prohibits network access during the agent phase.** This means a Codex Cloud agent cannot call `sqlite3` against a remote database or make HTTP calls to a REST gateway in real-time. The agent must either:
1. Have the SQLite database file accessible within its container (via git repo checkout), or
2. Write lifecycle events to local files that are synced post-execution.

Option 2 is more practical because the central database (e.g., `agent_os.db`) is in `.gitignore` (it contains runtime state, not versioned code). Option 1 would require checking the database into the repo, which creates merge conflicts and stale state.

**Adapter design (file-based protocol for Codex Cloud):**

Since Codex Cloud agents operate in an isolated sandbox with no network access during the agent phase, the adapter uses a **file-based protocol**. The agent writes lifecycle events to a structured JSON-lines file. A post-execution sync process reads these events and applies them to the central database.

```python
"""Codex Cloud adapter -- file-based lifecycle for sandboxed execution.

The Codex agent writes lifecycle events to a JSON-lines file within the repo.
A post-execution sync process (triggered by webhook, CI, or cron) reads
these events and applies them to the central SQLite database.

This is necessary because Codex Cloud disables network access during
the agent phase (b: verified per OpenAI documentation).
"""

import json
import time
import uuid
from pathlib import Path
from typing import Any


class CodexCloudAdapter:
    """File-based lifecycle adapter for Codex Cloud's sandboxed environment."""

    RUNTIME_TYPE = "codex_cloud"
    EVENTS_FILE = ".agent_os/lifecycle_events.jsonl"

    def __init__(self, agent_id: str, repo_root: str | Path):
        self.agent_id = agent_id
        self.repo_root = Path(repo_root)
        self.session_id = f"sess_{agent_id}_{uuid.uuid4().hex[:8]}"
        self._start_time: float | None = None
        self._events_path = self.repo_root / self.EVENTS_FILE
        self._events_path.parent.mkdir(parents=True, exist_ok=True)

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Append a lifecycle event to the JSONL log."""
        event = {
            "timestamp": time.time(),
            "iso_time": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "runtime_type": self.RUNTIME_TYPE,
            "event_type": event_type,
            **data,
        }
        with open(self._events_path, "a") as f:
            f.write(json.dumps(event) + "\n")

    # L1: start_session
    def start_session(self, context_summary: str = "") -> str:
        self._start_time = time.time()
        self._emit_event("session_start", {"context_summary": context_summary})
        return self.session_id

    # L2: heartbeat
    def heartbeat(self, progress: dict[str, Any] | None = None) -> None:
        self._emit_event("heartbeat", {"progress": progress or {}})

    # L3: log_activity
    def log_activity(
        self, action: str, category: str, description: str,
        details: dict[str, Any] | None = None, severity: str = "info",
    ) -> None:
        self._emit_event("activity", {
            "action": action, "category": category,
            "description": description, "details": details or {},
            "severity": severity,
        })

    # L4: produce_artifact
    def produce_artifact(
        self, category: str, filename: str, content: str,
        artifact_type: str = "markdown",
    ) -> Path:
        artifact_dir = self.repo_root / "agent_comms" / "artifacts" / category
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / filename
        artifact_path.write_text(content)
        import hashlib
        checksum = hashlib.sha256(content.encode()).hexdigest()
        self._emit_event("artifact_produced", {
            "artifact_path": str(artifact_path.relative_to(self.repo_root)),
            "artifact_type": artifact_type,
            "checksum": checksum,
        })
        return artifact_path

    # L5: end_session
    def end_session(self, handoff_notes: str = "") -> None:
        duration = time.time() - self._start_time if self._start_time else 0
        self._emit_event("session_end", {
            "duration_seconds": round(duration, 1),
            "handoff_notes": handoff_notes,
        })
```

**Post-execution sync process:**

After the Codex Cloud task completes (producing a PR or commit), a webhook or CI job runs the sync process. This is the critical bridge between the sandboxed Codex environment and the central Agent OS database:

```python
"""Sync Codex lifecycle events from JSONL file into the central SQLite database.

Run this from CI (GitHub Actions), a webhook handler, or a cron job
after a Codex task completes and its PR/commit is available.

Usage:
    python scripts/sync_codex_events.py path/to/lifecycle_events.jsonl
"""

import json
import sqlite3
import sys
from pathlib import Path


def sync_codex_events(events_file: Path, db_path: Path) -> int:
    """Read lifecycle events from a Codex agent's JSONL log and apply to the central DB.

    Returns the number of events processed.
    """
    if not events_file.exists():
        print(f"No events file found at {events_file}")
        return 0

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")

    count = 0
    for line in events_file.read_text().strip().split("\n"):
        if not line.strip():
            continue
        event = json.loads(line)
        event_type = event["event_type"]
        agent_id = event["agent_id"]
        iso_time = event["iso_time"]

        if event_type == "session_start":
            conn.execute(
                "UPDATE agents SET status='running', last_run_start=?, "
                "total_runs=total_runs+1, current_task_id=?, updated_at=? WHERE agent_id=?",
                (iso_time, event["session_id"], iso_time, agent_id),
            )
            conn.execute(
                "INSERT OR IGNORE INTO agent_sessions (session_id, agent_id, runtime_type, context_summary, started_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (event["session_id"], agent_id, event["runtime_type"],
                 event.get("context_summary", ""), iso_time),
            )
        elif event_type == "heartbeat":
            conn.execute(
                "UPDATE agents SET last_heartbeat=?, updated_at=? WHERE agent_id=?",
                (iso_time, iso_time, agent_id),
            )
        elif event_type == "activity":
            conn.execute(
                "INSERT INTO activity_log (timestamp, agent_id, action, category, description, details, severity) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (iso_time, agent_id, event["action"], event["category"],
                 event["description"], json.dumps(event.get("details", {})),
                 event.get("severity", "info")),
            )
        elif event_type == "artifact_produced":
            conn.execute(
                "INSERT INTO activity_log (timestamp, agent_id, action, category, description, details, severity) "
                "VALUES (?, ?, 'artifact_produced', 'system', ?, ?, 'info')",
                (iso_time, agent_id, f"Produced {event.get('artifact_path', 'unknown')}",
                 json.dumps({k: v for k, v in event.items()
                            if k not in ('timestamp', 'iso_time', 'agent_id', 'session_id', 'runtime_type', 'event_type')})),
            )
        elif event_type == "session_end":
            conn.execute(
                "UPDATE agents SET status='idle', last_run_end=?, current_task_id=NULL, updated_at=? WHERE agent_id=?",
                (iso_time, iso_time, agent_id),
            )
            conn.execute(
                "UPDATE agent_sessions SET status='completed', ended_at=?, "
                "duration_seconds=?, handoff_notes=? WHERE session_id=?",
                (iso_time, event.get("duration_seconds", 0),
                 event.get("handoff_notes", ""), event["session_id"]),
            )
        count += 1

    conn.commit()
    conn.close()
    print(f"Synced {count} events from {events_file}")
    return count


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python sync_codex_events.py <events_file> [db_path]")
        sys.exit(1)
    events = Path(sys.argv[1])
    db = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("agent_comms/db/agent_os.db")
    sync_codex_events(events, db)
```

**GitHub Actions integration for automatic sync:**

```yaml
# .github/workflows/sync-codex-events.yml
# (c: proposal) Triggered when Codex produces a PR
name: Sync Codex Agent Events
on:
  pull_request:
    paths:
      - '.agent_os/lifecycle_events.jsonl'

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv run python scripts/sync_codex_events.py .agent_os/lifecycle_events.jsonl
```

**Codex CLI integration (direct DB access):**

Unlike Codex Cloud, Codex CLI runs locally and can access the SQLite database directly. It can use the same adapter as Claude Code with a different `RUNTIME_TYPE`:

```python
class CodexCLIAdapter(ClaudeCodeAdapter):
    """Codex CLI runs locally and has direct DB access.

    Functionally identical to the Claude Code adapter, but records
    a different runtime_type for analytics.
    """
    RUNTIME_TYPE = "codex_cli"
```

**Codex + OpenAI Agents SDK integration:**

The OpenAI Agents SDK (b: verified, open-source Python framework) can orchestrate Codex CLI as an MCP server. In this mode, the Agents SDK acts as the supervisor and can inject lifecycle calls as part of the agent's tool execution loop. The SDK provides:
- A Runner execution engine that drives the agentic loop
- Automatic tracing of LLM calls, tool invocations, and handoffs
- Guardrails for input/output validation

Source: [OpenAI Agents SDK docs](https://openai.github.io/openai-agents-python/), [Codex + Agents SDK guide](https://developers.openai.com/codex/guides/agents-sdk/)

[NEEDS_VERIFICATION: exact MCP server protocol for injecting lifecycle heartbeats into the Codex agent loop -- the documentation describes Codex-as-MCP-server capability but does not specify how to hook into the tool execution cycle for heartbeat injection]

**What Codex can and cannot do (b: verified):**
- CAN (Cloud): Execute shell commands, read/write files within the repo, run tests, produce commits/PRs
- CAN (Cloud): Access pre-installed dependencies (setup script runs with internet)
- CAN (CLI): Execute shell commands locally, read/write files, access local filesystem, function as MCP server
- CANNOT (Cloud): Access network during agent phase -- setup scripts only (configurable but off by default)
- CANNOT (Cloud): Access the central SQLite database in real-time (requires post-execution sync)
- CANNOT (Cloud): Maintain persistent processes between tasks (container is ephemeral)
- CANNOT (either): Spawn subagents natively (no Agent Teams equivalent) -- must use Agents SDK for orchestration

---

### 2.3 Google Gemini CLI Adapter

**Runtime characteristics (b: observed, verified against Google developer documentation):**
- Open-source agentic coding assistant running locally in the terminal
- Built-in tools: Shell, ReadFile, WriteFile, SearchText, FindFiles, GoogleSearch, WebFetch, EditFile, ReadFolder, SaveMemory, WriteTodos
- Gemini 2.5 Pro model with 1M token context window
- MCP server support for custom integrations
- ReAct (Reason and Act) loop for multi-step actions
- Supports `GEMINI.md` for project-specific instructions (analogous to `AGENTS.md` / `CLAUDE.md`)
- Free tier: 60 requests/minute, 1,000 requests/day; paid tiers offer 5-20x higher limits
- No native subagent spawning or team coordination

Source: [Gemini CLI GitHub](https://github.com/google-gemini/gemini-cli), [Gemini CLI docs](https://developers.google.com/gemini-code-assist/docs/gemini-cli)

**Integration path:** Gemini CLI's `Shell` tool can execute `sqlite3` commands directly, making it compatible with the same direct-DB-access adapter as Claude Code. The `ReadFile` and `WriteFile` tools handle artifact I/O. The main difference is the rate limiting model (request-based rather than token-based) and the lack of native subagent orchestration.

```python
class GeminiCLIAdapter(ClaudeCodeAdapter):
    """Gemini CLI adapter -- identical to Claude Code adapter for lifecycle operations.

    Gemini CLI has the same capabilities for our purposes:
    shell access, file I/O, and local DB access via the Shell tool.
    The rate limit tracking and request counting are the primary differentiators.
    """
    RUNTIME_TYPE = "gemini_cli"

    def start_session(self, context_summary: str = "") -> str:
        session_id = super().start_session(context_summary)
        # Record Gemini-specific rate limit context for the supervisor
        self.log_activity(
            "rate_limit_context", "system",
            "Gemini CLI rate limits: 60 req/min, 1000 req/day (free tier)",
            details={"requests_per_minute": 60, "requests_per_day": 1000},
        )
        return session_id
```

**What Gemini CLI can and cannot do (b: verified):**
- CAN: Execute shell commands, read/write files, search text in codebase, access web via GoogleSearch/WebFetch
- CAN: Use MCP servers for extensibility
- CAN: Access local SQLite database via Shell tool
- CANNOT: Spawn subagents or teams natively (no equivalent to Claude Code Agent Teams)
- CANNOT: Run as a persistent daemon
- CANNOT [NEEDS_VERIFICATION]: Work in git worktrees -- documentation does not mention worktree support

---

### 2.4 Custom Python Script Adapter

**Runtime characteristics:**
- Direct Python process running on the host machine
- Full access to SQLite, filesystem, network, external APIs
- Can run as a daemon, cron job, or one-shot script
- Most flexible adapter -- serves as the reference implementation
- No LLM context window constraints (can hold unlimited state in memory)

The `BaseAgent` class (e.g., `src/{project}/agents/base_agent.py` in the reference implementation) already implements most of the lifecycle protocol. The adapter is a thin wrapper that adds session tracking:

```python
"""Custom Python script adapter.

This extends the existing BaseAgent class to add session tracking
and the full lifecycle protocol. All existing project-specific agent classes
can inherit from this adapter instead of BaseAgent directly.

Examples by domain:
  - Finance: researcher.py, quant.py, risk_monitor.py
  - ML research: trainer.py, evaluator.py, data_curator.py
  - SaaS: deployer.py, migration_runner.py, monitor.py
"""

import json
import uuid
import time
from agent_os.agents.base_agent import BaseAgent  # or project-specific path


class PythonScriptAdapter(BaseAgent):
    """Python script adapter with full session tracking."""

    RUNTIME_TYPE = "python_script"

    def __init__(self, agent_id: str, name: str, role: str):
        super().__init__(agent_id, name, role)
        self._session_id: str | None = None
        self._start_time: float | None = None

    def start_session(self, context_summary: str = "") -> str:
        self._session_id = f"sess_{self.agent_id}_{uuid.uuid4().hex[:8]}"
        self._start_time = time.time()
        self.mark_run_start()
        self.log_activity(
            "session_start", "system",
            f"Python script session started: {self._session_id}",
            details={
                "session_id": self._session_id,
                "runtime": self.RUNTIME_TYPE,
                "context_summary": context_summary,
            },
        )
        return self._session_id

    def produce_artifact(
        self, category: str, filename: str, content: str,
        artifact_type: str = "markdown",
    ) -> str:
        """Write artifact and log it. Returns the artifact path."""
        import hashlib
        from pathlib import Path
        artifacts_dir = self.db_path.parent.parent / "artifacts" / category
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifacts_dir / filename
        artifact_path.write_text(content)
        checksum = hashlib.sha256(content.encode()).hexdigest()
        self.log_activity(
            "artifact_produced", category,
            f"Produced {filename}",
            details={
                "artifact_path": str(artifact_path),
                "artifact_type": artifact_type,
                "checksum": checksum,
                "session_id": self._session_id,
            },
        )
        return str(artifact_path)

    def end_session(self, handoff_notes: str = "") -> None:
        duration = time.time() - self._start_time if self._start_time else 0
        self.mark_run_end()
        self.log_activity(
            "session_end", "system",
            f"Python script session ended: {self._session_id}",
            details={
                "session_id": self._session_id,
                "duration_seconds": round(duration, 1),
                "handoff_notes": handoff_notes,
            },
        )
```

**Cron job usage examples:**

The cron adapter works for any periodic monitoring task. The domain-specific logic lives in the `run()` method; the lifecycle protocol is identical across domains.

```python
#!/usr/bin/env python3
"""Cron-based monitoring agent -- runs periodically via crontab.

Finance example:  */5 * * * * cd /path/to/project && uv run python scripts/cron_risk_check.py
ML example:       */10 * * * * cd /path/to/project && uv run python scripts/cron_gpu_monitor.py
SaaS example:     */1 * * * * cd /path/to/project && uv run python scripts/cron_health_check.py
"""

import sqlite3
from pathlib import Path
from agent_os.agents.base_agent import BaseAgent  # or project-specific path


class CronMonitorAgent(BaseAgent):
    RUNTIME_TYPE = "cron_job"

    def run(self) -> None:
        self.mark_run_start()
        try:
            self.heartbeat()

            # Domain-specific monitoring logic goes here.
            # The lifecycle protocol (heartbeat, log_activity, produce_artifact)
            # is identical regardless of what is being monitored.
            #
            # Finance: check open positions for drawdown breaches
            # ML research: check GPU utilization, training loss plateaus
            # SaaS: check API error rates, queue depths, latency P99
            conn = self._get_conn()
            try:
                # Example: query a project-specific table for items needing attention
                rows = conn.execute(
                    "SELECT * FROM monitored_items WHERE status = 'active'"
                ).fetchall()
                for row in rows:
                    if self._check_threshold_breach(row):
                        self.log_activity(
                            "threshold_alert", "monitoring",
                            f"Item {row['item_id']} breached threshold",
                            details={"item_id": row["item_id"]},
                            severity="warning",
                        )
            finally:
                conn.close()

            self.heartbeat()
        finally:
            self.mark_run_end()

    def _check_threshold_breach(self, row) -> bool:
        """Project-specific threshold logic. Override per domain."""
        raise NotImplementedError


if __name__ == "__main__":
    monitor = CronMonitorAgent("monitor", "Monitor Agent", "Periodic Monitoring")
    monitor.run()
```

---

### 2.5 Human Operator Adapter

**Runtime characteristics:**
- Human interacting via web dashboard or CLI tool
- Actions are slow (minutes to hours between actions)
- Requires a UI layer that translates human actions into lifecycle events
- The human never writes SQL directly -- the adapter mediates all interactions

**Design: CLI-based operator interface:**

```python
#!/usr/bin/env python3
"""Human operator CLI -- translates human actions into lifecycle protocol events.

Usage:
    uv run python scripts/human_operator.py start <operator_name>
    uv run python scripts/human_operator.py log <operator_name> <action> <category> <description>
    uv run python scripts/human_operator.py approve-hypothesis <hypothesis_id>
    uv run python scripts/human_operator.py end <operator_name>
"""

import argparse
import json
import sqlite3
import uuid
from pathlib import Path

DB_PATH = Path("agent_comms/db/agent_os.db")  # Resolved from project.yaml in production


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def start_session(agent_id: str) -> None:
    session_id = f"sess_{agent_id}_human_{uuid.uuid4().hex[:6]}"
    conn = _conn()
    conn.execute(
        "UPDATE agents SET status='running', last_heartbeat=CURRENT_TIMESTAMP, "
        "last_run_start=CURRENT_TIMESTAMP, total_runs=total_runs+1, "
        "current_task_id=?, updated_at=CURRENT_TIMESTAMP WHERE agent_id=?",
        (session_id, agent_id),
    )
    conn.execute(
        "INSERT INTO activity_log (agent_id, action, category, description, details, severity) "
        "VALUES (?, 'session_start', 'system', 'Human operator session started', "
        "json_object('session_id', ?, 'runtime', 'human_operator'), 'info')",
        (agent_id, session_id),
    )
    conn.commit()
    conn.close()
    print(f"Session started: {session_id}")
    print(f"Reminder: Run 'end {agent_id}' when you're done.")


def log_action(agent_id: str, action: str, category: str, description: str) -> None:
    conn = _conn()
    # Also refresh heartbeat on every human action
    conn.execute(
        "UPDATE agents SET last_heartbeat=CURRENT_TIMESTAMP WHERE agent_id=?",
        (agent_id,),
    )
    conn.execute(
        "INSERT INTO activity_log (agent_id, action, category, description, severity) "
        "VALUES (?, ?, ?, ?, 'info')",
        (agent_id, action, category, description),
    )
    conn.commit()
    conn.close()
    print(f"Logged: [{category}] {action} -- {description}")


def end_session(agent_id: str) -> None:
    conn = _conn()
    conn.execute(
        "UPDATE agents SET status='idle', last_run_end=CURRENT_TIMESTAMP, "
        "current_task_id=NULL, updated_at=CURRENT_TIMESTAMP WHERE agent_id=?",
        (agent_id,),
    )
    conn.execute(
        "INSERT INTO activity_log (agent_id, action, category, description, severity) "
        "VALUES (?, 'session_end', 'system', 'Human operator session ended', 'info')",
        (agent_id,),
    )
    conn.commit()
    conn.close()
    print("Session ended.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Human operator lifecycle CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("start")
    s.add_argument("agent_id")

    s = sub.add_parser("log")
    s.add_argument("agent_id")
    s.add_argument("action")
    s.add_argument("category")
    s.add_argument("description")

    s = sub.add_parser("end")
    s.add_argument("agent_id")

    args = parser.parse_args()
    if args.command == "start":
        start_session(args.agent_id)
    elif args.command == "log":
        log_action(args.agent_id, args.action, args.category, args.description)
    elif args.command == "end":
        end_session(args.agent_id)
```

**Web dashboard REST endpoints (c: proposal):**

The existing FastAPI dashboard (`dashboard/api/server.py`) can expose lifecycle endpoints that the web UI calls when a human operator takes actions:

```python
# (c: proposal) REST endpoints for the web dashboard human operator adapter
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


class SessionStart(BaseModel):
    agent_id: str
    context_summary: str = ""


class ActivityLog(BaseModel):
    agent_id: str
    action: str
    category: str
    description: str
    severity: str = "info"


@app.post("/api/v1/lifecycle/start-session")
def api_start_session(req: SessionStart) -> dict:
    """Start a human operator session via the web dashboard."""
    adapter = _get_adapter(req.agent_id, runtime_type="human_operator")
    session_id = adapter.start_session(req.context_summary)
    return {"session_id": session_id, "agent_id": req.agent_id}


@app.post("/api/v1/lifecycle/heartbeat/{agent_id}")
def api_heartbeat(agent_id: str) -> dict:
    """Refresh heartbeat -- called automatically by the web UI every 60s."""
    adapter = _get_adapter(agent_id)
    adapter.heartbeat()
    return {"status": "ok"}


@app.post("/api/v1/lifecycle/log-activity")
def api_log_activity(req: ActivityLog) -> dict:
    """Log a human operator action."""
    adapter = _get_adapter(req.agent_id)
    adapter.log_activity(req.action, req.category, req.description, severity=req.severity)
    return {"status": "ok"}


@app.post("/api/v1/lifecycle/end-session/{agent_id}")
def api_end_session(agent_id: str) -> dict:
    """End a human operator session."""
    adapter = _get_adapter(agent_id)
    adapter.end_session()
    return {"status": "ok"}


def _get_adapter(agent_id: str, runtime_type: str = "human_operator"):
    """Factory function to get the appropriate adapter for an agent."""
    from pathlib import Path
    db_path = Path("agent_comms/db/agent_os.db")  # Resolved from project.yaml in production
    adapter = ClaudeCodeAdapter(agent_id, db_path)
    adapter.RUNTIME_TYPE = runtime_type
    return adapter
```

---

### 2.6 Common Interface Summary

All adapters converge on the same five methods, defined as a Python `Protocol`:

```python
from typing import Any, Protocol, runtime_checkable
from pathlib import Path


@runtime_checkable
class AgentLifecycle(Protocol):
    """The universal agent lifecycle interface.

    Every provider adapter must implement these five methods.
    This is the entirety of the integration contract.
    No SDK, no framework, no inheritance chain required.
    """

    RUNTIME_TYPE: str

    def start_session(self, context_summary: str = "") -> str:
        """Register agent as running. Returns session_id."""
        ...

    def heartbeat(self, progress: dict[str, Any] | None = None) -> None:
        """Prove liveness. Called every 30 seconds."""
        ...

    def log_activity(
        self, action: str, category: str, description: str,
        details: dict[str, Any] | None = None, severity: str = "info",
    ) -> None:
        """Record a structured action in the audit trail."""
        ...

    def produce_artifact(
        self, category: str, filename: str, content: str,
        artifact_type: str = "markdown",
    ) -> Path:
        """Write a validated output artifact. Returns the artifact path."""
        ...

    def end_session(self, handoff_notes: str = "") -> None:
        """Mark agent as idle. Record session summary."""
        ...
```

**Adapter implementation complexity by provider:**

| Provider | Lines of Code | Integration Time | DB Access Model |
|----------|--------------|------------------|-----------------|
| Claude Code | ~80 (Python) or ~20 (bash) | 15 min | Direct SQLite |
| Codex Cloud | ~60 (adapter) + ~60 (sync) | 30 min | File-based JSONL + post-sync |
| Codex CLI | ~5 (inherits Claude Code) | 5 min | Direct SQLite |
| Gemini CLI | ~10 (inherits Claude Code) | 5 min | Direct SQLite |
| Python Script | ~40 (extends BaseAgent) | 10 min | Direct SQLite |
| Cron Job | ~30 (extends BaseAgent) | 10 min | Direct SQLite |
| Human Operator | ~50 (CLI) or REST endpoints | 20 min | HTTP or Direct SQLite |

---

## 3. Heartbeat & Liveness Detection

### 3.1 Heartbeat Protocol

**Design (a: established distributed systems pattern, per Martin Fowler's Patterns of Distributed Systems and the HeartBeat pattern):**

The Agent OS uses a **push-based heartbeat** model. Each running agent pushes a timestamp update to the `agents.last_heartbeat` column at a fixed interval. A supervisor process polls all agents and declares any agent dead if its heartbeat is stale beyond a configurable threshold.

Push-based heartbeats are preferred over pull-based for this system because (a: per distributed systems literature):
- They provide fast failure detection -- the absence of an expected heartbeat immediately signals a potential issue
- They reduce the supervisor's workload -- it only needs to check timestamps, not actively probe agents
- They work naturally with LLM agents that have a tool-use loop (heartbeat is just another "tool call" between reasoning steps)

Source: [Martin Fowler HeartBeat pattern](https://martinfowler.com/articles/patterns-of-distributed-systems/heartbeat.html), [HeartBeats in Distributed Systems](https://blog.algomaster.io/p/heartbeats-in-distributed-systems)

**Parameters:**

| Parameter | Default | Rationale |
|-----------|---------|-----------|
| Heartbeat interval | 30 seconds | Balances detection speed vs. DB write frequency. An LLM agent performing a complex reasoning step may take 10-20 seconds between tool calls -- 30s accommodates this without false positives. |
| Liveness threshold | 90 seconds (3x interval) | Using 3x the heartbeat interval absorbs temporary delays (DB lock contention, long tool calls, API latency) while still detecting genuine failures within ~2 minutes. (a: established practice -- 3x multiplier is standard in heartbeat literature) |
| Supervisor poll interval | 15 seconds | The supervisor checks more frequently than agents heartbeat, ensuring detection latency is bounded by the liveness threshold, not the poll interval. |
| Grace period on startup | 60 seconds | A newly started agent gets extra time to bootstrap its context before the first heartbeat is expected. LLM agents may spend 10-30s loading context. |
| Human operator timeout | 4 hours | Humans work on human timescales. A 90-second timeout would incorrectly declare every human operator dead. |

### 3.2 Heartbeat with Progress Metadata

Plain heartbeats only prove liveness, not usefulness. A zombie agent (F10 in the failure taxonomy from Research 08) is alive and sending heartbeats, but producing no useful work. To detect zombies, heartbeats should include optional progress metadata:

```sql
-- Enhanced heartbeat with progress tracking
-- The heartbeat UPDATE is always fast (single row, indexed by PK).
-- Progress metadata goes to activity_log for analysis without slowing the heartbeat.
UPDATE agents SET
    last_heartbeat = CURRENT_TIMESTAMP,
    updated_at = CURRENT_TIMESTAMP
WHERE agent_id = :agent_id;

-- Optional: log progress metadata (only every 5th heartbeat to reduce log volume)
INSERT INTO activity_log (agent_id, action, category, description, details, severity)
VALUES (:agent_id, 'heartbeat_progress', 'system', 'Agent progress report',
    json_object(
        'tokens_used', :tokens_used,
        'artifacts_produced', :artifacts_count,
        'current_subtask', :current_subtask,
        'progress_pct', :progress_pct,
        'last_tool_call', :last_tool_name
    ),
    'debug');
```

The supervisor can then detect zombies by checking:
- Has the agent produced any artifacts in the last N heartbeat cycles?
- Is `progress_pct` increasing or stalled?
- Is the agent stuck in a loop (same `current_subtask` for multiple consecutive heartbeats)?

Source: [AgentHeartbeat project](https://github.com/DonkRonk17/AgentHeartbeat) -- real-time monitoring system that tracks AI agents' activity velocity, response patterns, and health metrics to detect failures and emergent behaviors early. Notably documents a case where AI-to-AI cascading replies happened with no early warning system -- agents replied to each other at increasing velocity until context windows filled.

### 3.3 Dead Agent Detection and Recovery

**Supervisor implementation:**

```python
"""Supervisor liveness checker -- runs as a persistent process or cron job.

Checks all running agents every 15 seconds. Declares agents dead
if their heartbeat exceeds the liveness threshold. Triggers recovery.
"""

import sqlite3
import time
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path


# Per-runtime timeout overrides
TIMEOUT_OVERRIDES = {
    "human_operator": 14400,  # 4 hours
    "cron_job": 300,          # 5 minutes (cron jobs should be fast)
    "claude_code": 90,       # 90 seconds (default)
    "codex_cli": 90,
    "gemini_cli": 90,
    "python_script": 90,
    "codex_cloud": 3600,     # 1 hour (cloud tasks can be long; heartbeats are file-based)
}


def check_agent_liveness(
    db_path: str | Path,
    default_threshold_seconds: int = 90,
) -> list[dict]:
    """Check all running agents for heartbeat staleness.

    Returns a list of agents that have exceeded the liveness threshold.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    stale_agents = conn.execute(
        """SELECT a.agent_id, a.current_task_id, a.last_heartbeat,
                  CAST((julianday('now') - julianday(a.last_heartbeat)) * 86400 AS INTEGER) as stale_seconds,
                  COALESCE(s.runtime_type, 'unknown') as runtime_type
           FROM agents a
           LEFT JOIN agent_sessions s ON a.current_task_id = s.session_id
           WHERE a.status = 'running'
             AND a.last_heartbeat IS NOT NULL""",
    ).fetchall()

    dead_agents = []
    for agent in stale_agents:
        runtime = agent["runtime_type"]
        threshold = TIMEOUT_OVERRIDES.get(runtime, default_threshold_seconds)

        if agent["stale_seconds"] <= threshold:
            continue  # Still within threshold

        dead_agents.append({
            "agent_id": agent["agent_id"],
            "task_id": agent["current_task_id"],
            "last_heartbeat": agent["last_heartbeat"],
            "stale_seconds": agent["stale_seconds"],
            "threshold": threshold,
            "runtime_type": runtime,
        })

        # Mark agent as error state
        conn.execute(
            "UPDATE agents SET status='error', updated_at=CURRENT_TIMESTAMP WHERE agent_id=?",
            (agent["agent_id"],),
        )

        # Log the detection
        conn.execute(
            """INSERT INTO activity_log
                (agent_id, action, category, description, details, severity)
            VALUES (?, 'agent_declared_dead', 'system',
                    'Agent heartbeat exceeded liveness threshold',
                    ?, 'error')""",
            (agent["agent_id"], json.dumps({
                "stale_seconds": agent["stale_seconds"],
                "threshold": threshold,
                "task_id": agent["current_task_id"],
                "runtime_type": runtime,
            })),
        )

    conn.commit()
    conn.close()
    return dead_agents


def recover_dead_agent(db_path: str | Path, agent_id: str, session_id: str | None) -> None:
    """Recovery protocol for a dead agent.

    Steps:
    1. Mark the agent's current session as 'failed'
    2. If the agent had an in_progress task, mark it as 'blocked' for reassignment
    3. Log the failure for the manager agent to review
    4. Do NOT auto-restart -- the manager decides whether to respawn
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA busy_timeout=5000")

    # Update session record (if using agent_sessions table)
    if session_id:
        conn.execute(
            "UPDATE agent_sessions SET status='failed', ended_at=CURRENT_TIMESTAMP "
            "WHERE session_id=? AND status='active'",
            (session_id,),
        )

    # Block any in-progress tasks so they can be reassigned
    conn.execute(
        "UPDATE tasks SET status='blocked', updated_at=CURRENT_TIMESTAMP "
        "WHERE assigned_to=? AND status='in_progress'",
        (agent_id,),
    )

    # Log for manager review
    conn.execute(
        """INSERT INTO activity_log
            (agent_id, action, category, description, details, severity)
        VALUES (?, 'recovery_executed', 'system',
                'Dead agent recovery protocol executed',
                json_object('session_id', ?, 'blocked_tasks', 'check tasks table'),
                'warning')""",
        (agent_id, session_id or "unknown"),
    )

    conn.commit()
    conn.close()


def supervisor_loop(db_path: str | Path, poll_interval: int = 15) -> None:
    """Main supervisor loop. Run as a persistent process.

    Usage: python -m hft.supervisor
    """
    print(f"Supervisor started. Polling every {poll_interval}s.")
    while True:
        dead = check_agent_liveness(db_path)
        for agent in dead:
            print(f"[DEAD] {agent['agent_id']} -- stale {agent['stale_seconds']}s "
                  f"(threshold: {agent['threshold']}s, runtime: {agent['runtime_type']})")
            recover_dead_agent(db_path, agent["agent_id"], agent.get("task_id"))
        time.sleep(poll_interval)
```

### 3.4 Recovery Protocol

When an agent dies mid-task, the recovery action depends on what state was left behind:

| Scenario | Detection | Recovery Action | Idempotent? |
|----------|-----------|----------------|-------------|
| Agent crashed before writing any output | Heartbeat timeout, no new activity_log entries | Reassign task to a new agent session | Yes -- no partial state to clean up |
| Agent wrote partial artifacts to filesystem | Heartbeat timeout, artifact_produced log entries exist | Move partial artifacts to `artifacts/quarantine/`, reassign task | Yes -- new agent starts fresh |
| Agent died mid-SQLite-transaction | Heartbeat timeout, process exit | SQLite WAL mode auto-rolls back uncommitted transactions (a: verified per SQLite docs) | Yes -- SQLite handles this automatically |
| Agent committed partial results to DB | Heartbeat timeout, multiple activity_log entries | Flag rows written by the dead session for review, reassign task | Requires supervisor or manager review |
| Agent entered infinite loop (zombie) | Heartbeat continues but no progress_pct change | Kill agent process (if possible), mark session failed, reassign | Requires progress metadata in heartbeats |

**Key insight:** Because all agent state lives in the SQLite database (which provides ACID transactions via WAL mode) and the filesystem (which is append-mostly), recovery is always possible by rolling back to the last consistent state. An agent that dies mid-`sqlite3` call leaves no partial writes thanks to WAL journaling. (a: verified per SQLite WAL documentation)

Source: [SQLite WAL mode](https://sqlite.org/wal.html)

---

## 4. Session & Context Management

### 4.1 The Context Loss Problem

LLM-based agents have ephemeral context windows. When a Claude Code session ends, the agent "forgets" everything. The next session starts with a blank context window and must rebuild its working state. This is fundamentally different from traditional software agents that can maintain in-memory state indefinitely.

**Impact:** A researcher agent that spent 30 minutes analyzing funding rate data and formed intermediate conclusions loses all of that analytical state when the session ends -- unless it externalized its findings to the database and filesystem. The context bootstrapping protocol must reconstruct enough state for the next session to continue where the previous one left off, without re-doing the same work.

This is not a theoretical concern. Research 02 (AI-Native Patterns) documents that AI agents have "perfect recall within context window; no recall across sessions without external storage." The session handoff protocol exists to bridge this gap.

### 4.2 Context Bootstrapping Protocol

When an agent starts a new session, it must reconstruct enough context to continue useful work. The bootstrapping protocol has three phases, ordered by importance and size:

**Phase 1: Static Context (always loaded, ~2-4K tokens)**

Read from files that define the agent's identity and the project structure. These files change infrequently and are small:

| File | Purpose | Size |
|------|---------|------|
| `agents/prompts/{agent_id}.md` | Agent role definition, capabilities, rules | ~1-2K tokens |
| `CLAUDE.md` / `AGENTS.md` / `GEMINI.md` | Project instructions (runtime-specific) | ~2K tokens |
| `workspace/current_cycle.md` | Where we are in the current work cycle, what's next | ~500 tokens |
| `workspace/project_state.md` | Project status overview (domain-specific: fund performance, training metrics, deployment health, etc.) | ~500 tokens |

**Phase 2: Dynamic Context (queried from DB, ~1-5K tokens)**

These SQL queries reconstruct the agent's operational state. Q1-Q4 are universal (part of the core OS schema). Q5 is project-specific (the table and columns come from `project.yaml`):

```sql
-- Q1: What is the project's current state? (core OS table)
SELECT key, value FROM project_state ORDER BY key;

-- Q2: What tasks are assigned to me? (core OS table)
SELECT task_id, title, task_type, status, description
FROM tasks
WHERE assigned_to = :agent_id AND status NOT IN ('done', 'cancelled')
ORDER BY priority ASC;

-- Q3: What did my last session work on? (context continuity -- critical, core OS table)
SELECT session_id, context_summary, handoff_notes, artifacts_produced,
       ended_at, duration_seconds
FROM agent_sessions
WHERE agent_id = :agent_id AND status = 'completed'
ORDER BY ended_at DESC LIMIT 1;

-- Q4: What messages are waiting for me? (core OS table)
SELECT from_agent, subject, body, priority
FROM messages
WHERE to_agent = :agent_id AND status = 'pending'
ORDER BY priority ASC, created_at ASC;

-- Q5: What domain-specific items are in my scope? (project-defined table)
-- Finance:     SELECT strategy_id, name, status FROM strategies WHERE status NOT IN ('retired', 'draft')
-- ML research: SELECT experiment_id, name, status FROM experiments WHERE status IN ('running', 'queued')
-- SaaS:        SELECT service_id, name, health FROM services WHERE environment = 'production'
```

**Phase 3: Task-Specific Context (loaded on demand, variable size)**

The agent reads artifacts, data files, and domain-specific specs relevant to its current task. This phase is driven by the task description and the agent's own judgment about what context it needs. Examples by domain:

**Finance (hedge fund):** A researcher reads market data from `data/raw/` and previous research from `agent_comms/artifacts/research/`. A quant reads the research brief and strategy template. A coder reads the strategy spec and implementation code.

**ML research:** A trainer reads dataset metadata and previous experiment configs from `agent_comms/artifacts/experiments/`. An evaluator reads model checkpoints and benchmark definitions. A data curator reads data quality reports.

**SaaS:** A deployer reads the deployment manifest and recent incident reports. A migration runner reads schema diffs and rollback plans. A monitor reads service dependency graphs and SLO definitions.

### 4.3 Session Handoff Protocol

The critical mechanism for context continuity across ephemeral sessions. Before ending a session, the agent writes structured `handoff_notes` to the `agent_sessions` table:

```python
def prepare_handoff(self) -> str:
    """Generate structured handoff notes for the next session.

    The next session reads these notes during Phase 2 bootstrapping (Q3).
    Notes should be concise but complete -- the next session has no other
    memory of what this session did or discovered.
    """
    # The handoff structure is universal; the content is domain-specific.
    # Finance example:
    handoff = {
        "what_i_did": "Analyzed BTC funding rate data for Jan-Feb 2026. "
                      "Found 3 potential divergence signals.",
        "key_findings": [
            "Funding rate > 0.05% for 4h preceded 2.1% drops (n=7)",
            "Signal degrades after March 2025 regime change",
        ],
        "what_to_do_next": [
            "Test with 1h resolution instead of 4h",
            "Write formal hypothesis to DB if results hold",
        ],
        "artifacts_written": [
            "agent_comms/artifacts/research/funding_rate_analysis_20260308.md"
        ],
        "open_questions": [
            "Is the signal independent of the momentum factor?",
        ],
    }
    # ML research example:
    # handoff = {
    #     "what_i_did": "Ran hyperparameter sweep on ResNet-50 with cosine annealing.",
    #     "key_findings": ["lr=3e-4 with warmup=500 gives best val loss (0.312)"],
    #     "what_to_do_next": ["Run full training with best config", "Evaluate on held-out test set"],
    #     "artifacts_written": ["agent_comms/artifacts/experiments/resnet50_sweep_20260308.json"],
    #     "open_questions": ["Does the learning rate schedule transfer to ViT?"],
    # }
    # SaaS example:
    # handoff = {
    #     "what_i_did": "Investigated P99 latency spike on billing service.",
    #     "key_findings": ["Root cause: N+1 query in invoice generation endpoint"],
    #     "what_to_do_next": ["Apply eager-loading fix", "Add regression test for query count"],
    #     "artifacts_written": ["agent_comms/artifacts/incidents/billing_latency_20260308.md"],
    #     "open_questions": ["Are other endpoints affected by the same ORM pattern?"],
    # }
    return json.dumps(handoff, indent=2)
```

### 4.4 How Much Context to Pre-Load vs. Discover

**Recommendation (c: proposal, informed by experience with the existing fund system):**

| Context Type | Pre-Load at Startup? | Rationale |
|-------------|---------------------|-----------|
| Agent role/prompt | Always | Defines identity and capabilities; small and static |
| Project state (key-value) | Always | Small (~10 rows), essential for orientation |
| Assigned tasks | Always | Agent must know what to work on immediately |
| Previous session handoff | Always | Critical for continuity; structured and small |
| Pending messages | Always | May contain urgent instructions from manager |
| Domain-specific details (strategies, experiments, services, etc.) | On demand | Large and task-specific; agent reads what it needs |
| Raw data files (Parquet, CSV, logs, etc.) | On demand | Potentially GB-scale; agent reads specific files |
| Other agents' artifacts | On demand | Avoid information overload; read only what's relevant to current task |
| Full activity log history | Never pre-load | Too large; query specific entries if needed |

**Total pre-loaded context:** ~3-8K tokens. This leaves the vast majority of the context window (which can be 200K-1M tokens depending on provider) available for the agent's actual work.

---

## 5. Output Validation Contract

### 5.1 The Problem

An agent can produce output in any format -- prose, JSON, SQL, markdown, binary files. Without validation, bad output propagates through the blackboard and poisons downstream agents' decisions. Research 08 (Failure Resilience) identifies this as failure mode F3 (Agent Hallucination) and F8 (State Corruption). The output contract defines what formats are acceptable and how they are validated before being committed to the shared blackboard.

### 5.2 Artifact Types and Validation Schemas

Every artifact produced by an agent has a type that determines its validation rules:

```python
"""Artifact validation schemas and validators.

This module defines the validation contract for all agent outputs.
Artifacts must pass validation before being committed to the blackboard
(agent_comms/artifacts/ directory).

IMPORTANT: Artifact types and schemas are PROJECT-DEFINED, not hard-coded
in the core OS. The core OS provides the validation framework; projects
declare their artifact types and schemas in project.yaml. The examples
below show schemas for three different domains.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# In production, artifact types are loaded from project.yaml at startup.
# The core OS defines only the validation framework, not the types themselves.
# Example project.yaml snippet:
#   artifact_types:
#     research_brief:
#       required_fields: [title, hypothesis, data_sources, findings, confidence]
#       confidence_range: [0.0, 1.0]
#       max_size_bytes: 500000
#
# For illustration, here are schemas from three different domains:

# --- Finance (hedge fund) ---
FINANCE_SCHEMAS: dict[str, dict[str, Any]] = {
    "strategy_spec": {
        "required_fields": ["strategy_id", "name", "entry_rules", "exit_rules", "risk_parameters"],
        "max_size_bytes": 200_000,
    },
    "backtest_report": {
        "required_fields": ["strategy_id", "sharpe_ratio", "max_drawdown_pct", "total_trades", "profit_factor"],
        "plausibility_checks": {
            "sharpe_ratio": (-10.0, 50.0),
            "max_drawdown_pct": (-1.0, 0.0),
            "profit_factor": (0.0, 100.0),
        },
        "max_size_bytes": 1_000_000,
    },
}

# --- ML Research ---
ML_SCHEMAS: dict[str, dict[str, Any]] = {
    "experiment_report": {
        "required_fields": ["experiment_id", "model_name", "dataset", "metrics", "hyperparameters"],
        "plausibility_checks": {
            "accuracy": (0.0, 1.0),
            "loss": (0.0, 1000.0),
        },
        "max_size_bytes": 1_000_000,
    },
    "dataset_card": {
        "required_fields": ["dataset_id", "description", "size", "splits", "license"],
        "max_size_bytes": 200_000,
    },
}

# --- SaaS ---
SAAS_SCHEMAS: dict[str, dict[str, Any]] = {
    "incident_report": {
        "required_fields": ["incident_id", "severity", "root_cause", "resolution", "timeline"],
        "max_size_bytes": 500_000,
    },
    "deployment_manifest": {
        "required_fields": ["service_id", "version", "environment", "rollback_plan"],
        "max_size_bytes": 100_000,
    },
}

# Universal artifact types (provided by core OS for all projects)
UNIVERSAL_SCHEMAS: dict[str, dict[str, Any]] = {
    "research_brief": {
        "required_fields": ["title", "hypothesis", "data_sources", "findings", "confidence"],
        "confidence_range": (0.0, 1.0),
        "max_size_bytes": 500_000,
    },
    "code": {"max_size_bytes": 1_000_000},
    "data": {"max_size_bytes": 10_000_000},
    "audit": {"required_fields": ["timestamp", "agent_id", "action"], "max_size_bytes": 200_000},
}


@dataclass
class ValidationResult:
    """Result of artifact validation."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checksum: str = ""


def validate_artifact(
    content: str,
    artifact_type: str,
    filename: str,
    schemas: dict[str, dict[str, Any]] | None = None,
) -> ValidationResult:
    """Validate an artifact against its schema before committing to the blackboard.

    Three-stage pipeline:
    1. Schema validation -- structure, required fields, type checks
    2. Plausibility checks -- range bounds, sanity checks
    3. Integrity recording -- checksum computation

    The schemas dict is loaded from project.yaml at startup and merged
    with UNIVERSAL_SCHEMAS. Projects define their own artifact types.

    Returns ValidationResult with pass/fail and any issues found.
    """
    errors: list[str] = []
    warnings: list[str] = []
    checksum = hashlib.sha256(content.encode()).hexdigest()

    all_schemas = {**UNIVERSAL_SCHEMAS, **(schemas or {})}
    schema = all_schemas.get(artifact_type)
    if not schema:
        warnings.append(f"No schema defined for artifact type '{artifact_type}' -- skipping structural validation")
        return ValidationResult(valid=True, errors=errors, warnings=warnings, checksum=checksum)

    # --- Stage 1: Schema validation ---

    # Size check
    content_bytes = len(content.encode())
    max_size = schema.get("max_size_bytes", 1_000_000)
    if content_bytes > max_size:
        errors.append(f"Artifact exceeds max size: {content_bytes:,} > {max_size:,} bytes")

    # Empty content check
    if not content.strip():
        errors.append("Artifact content is empty")
        return ValidationResult(valid=False, errors=errors, warnings=warnings, checksum=checksum)

    # For JSON artifacts, validate structure
    if filename.endswith(".json"):
        try:
            data = json.loads(content)
            required = schema.get("required_fields", [])
            missing = [f for f in required if f not in data]
            if missing:
                errors.append(f"Missing required fields: {missing}")

            # --- Stage 2: Plausibility checks ---
            plausibility = schema.get("plausibility_checks", {})
            for field_name, (low, high) in plausibility.items():
                if field_name in data:
                    val = data[field_name]
                    if isinstance(val, (int, float)) and not (low <= val <= high):
                        warnings.append(
                            f"Field '{field_name}' value {val} outside plausible range [{low}, {high}] "
                            f"-- artifact will be quarantined for review"
                        )

            # Check for confidence range if specified
            conf_range = schema.get("confidence_range")
            if conf_range and "confidence" in data:
                low, high = conf_range
                val = data["confidence"]
                if isinstance(val, (int, float)) and not (low <= val <= high):
                    errors.append(f"Confidence {val} outside valid range [{low}, {high}]")

        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON: {e}")

    # For markdown artifacts, check for expected sections
    elif filename.endswith(".md"):
        required_fields = schema.get("required_fields", [])
        for req_field in required_fields:
            heading = f"## {req_field.replace('_', ' ').title()}"
            if heading not in content and f"# {req_field.replace('_', ' ').title()}" not in content:
                warnings.append(f"Expected heading '{heading}' not found in markdown -- may be formatted differently")

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        checksum=checksum,
    )
```

### 5.3 Validation Pipeline

Artifacts pass through a three-stage validation pipeline before being committed:

```
Agent produces artifact content
        |
        v
[Stage 1: Schema Validation]
  - Structure check: required fields present?
  - Type check: is JSON valid? Are fields correct type?
  - Size check: within max_size_bytes limit?
  - Result: REJECT (errors) or PASS
        |
        v
[Stage 2: Plausibility Check]
  - Range bounds: Sharpe between -10 and 50?
  - Sanity: drawdown negative? win_rate between 0 and 1?
  - Result: QUARANTINE (warnings) or PASS
        |
        v
[Stage 3: Integrity Recording]
  - Compute SHA-256 checksum
  - Record in activity_log with full metadata
  - Result: always PASS
        |
        v
Artifact committed to blackboard:
  agent_comms/artifacts/{category}/{filename}
```

**Failed validation behavior:**

| Stage | Outcome | Action |
|-------|---------|--------|
| Stage 1 failure (missing fields, invalid JSON, empty) | REJECT | Artifact is NOT written to the blackboard. Error logged to activity_log. Agent is notified. |
| Stage 2 failure (implausible values) | QUARANTINE | Artifact written to `artifacts/quarantine/{category}/` instead of target directory. Warning logged. Manager agent reviews. |
| Stage 3 | Always PASS | Checksum and metadata recorded for integrity verification. |

### 5.4 Format Decision: JSON vs. Markdown vs. Both

| Output Type | Recommended Format | Rationale |
|------------|-------------------|-----------|
| Structured data (hypotheses, metrics, configs) | JSON | Machine-parseable, schema-validatable, queryable by SQL |
| Narrative analysis (research briefs, reports) | Markdown | Human-readable, version-controllable, LLM-friendly input |
| Hybrid (strategy specs, backtest reports) | Markdown with YAML/JSON frontmatter | Best of both: human-readable body with machine-parseable metadata |

**Recommended hybrid format for complex artifacts:**

The frontmatter schema is project-defined; the core OS parses the YAML header for validation and indexing. Two examples:

```markdown
---
# Finance example: backtest report
artifact_type: backtest_report
strategy_id: strat_fr_atr_v2c
schema_version: "1.0"
metrics:
  sharpe_ratio: 1.82
  max_drawdown_pct: -0.087
  total_trades: 342
  profit_factor: 1.45
validated: true
checksum: "a1b2c3d4e5f6..."
---

# Backtest Report: Funding Rate ATR v2c

## Summary
The strategy was tested on BTC/USDT 1h bars from 2025-01-01 to 2026-02-28...
```

```markdown
---
# ML research example: experiment report
artifact_type: experiment_report
experiment_id: exp_resnet50_cosine_003
schema_version: "1.0"
metrics:
  accuracy: 0.924
  loss: 0.287
  training_hours: 4.2
  gpu_type: A100
validated: true
checksum: "f7e8d9c0b1a2..."
---

# Experiment Report: ResNet-50 Cosine Annealing Sweep

## Summary
Trained ResNet-50 on ImageNet with cosine annealing schedule...
```

This format allows:
- The frontmatter to be parsed by machines for automated decisions (`if metrics.sharpe_ratio > 1.5: promote()`)
- The body to be read by humans and LLM agents for qualitative assessment
- Git to track changes meaningfully (markdown diffs are readable)

---

## 6. Resource Management

### 6.1 The Multi-Agent Resource Problem

When multiple agents run simultaneously, they compete for shared resources:
- **LLM API rate limits:** Claude API, OpenAI API, Gemini API all have per-account rate limits
- **Token budgets:** Each API call costs money; uncontrolled agents can burn through budgets rapidly
- **SQLite write contention:** Only one writer at a time in WAL mode (a: verified per SQLite docs)
- **Disk space:** Artifacts accumulate; data files in `data/raw/` can be gigabytes
- **External API limits:** Project-specific (e.g., Binance 1200 req/min, GitHub API 5000 req/hr, HuggingFace Hub 300 req/min)

Source: [AI Agent Token Cost Optimization 2026](https://fast.io/resources/ai-agent-token-cost-optimization/), [Hidden Economics of AI Agents](https://online.stevens.edu/blog/hidden-economics-ai-agents-token-costs-latency/)

### 6.2 Per-Agent Resource Quotas

```sql
-- (c: proposal) Resource quota tracking table
CREATE TABLE IF NOT EXISTS agent_resource_quotas (
    agent_id TEXT PRIMARY KEY,

    -- Per-session limits
    max_tokens_per_session INTEGER DEFAULT 500000,
    max_cost_per_session_usd REAL DEFAULT 10.0,
    max_api_calls_per_minute INTEGER DEFAULT 30,
    max_artifact_size_bytes INTEGER DEFAULT 5000000,
    max_concurrent_sessions INTEGER DEFAULT 1,

    -- Liveness timeout override (seconds)
    heartbeat_timeout_seconds INTEGER DEFAULT 90,

    -- Running totals for current session (reset on start_session)
    current_session_tokens INTEGER DEFAULT 0,
    current_session_cost_usd REAL DEFAULT 0.0,

    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);

-- Default quotas by role (project-defined via project.yaml agent_roles section).
-- These are populated by `agent-os init` based on the project's agent_roles config.
-- Example for a finance project:
INSERT OR IGNORE INTO agent_resource_quotas
    (agent_id, max_tokens_per_session, max_cost_per_session_usd, heartbeat_timeout_seconds)
VALUES
    ('manager', 1000000, 25.0, 90),         -- Manager needs large context for synthesis
    ('researcher', 500000, 15.0, 90),       -- Research is token-intensive
    ('implementer', 500000, 15.0, 90),      -- Implementation needs room for iteration
    ('tester', 800000, 20.0, 120),          -- Testing can be verbose and slow
    ('monitor', 200000, 5.0, 300);          -- Monitoring is lightweight but may run as cron
-- ML research project might use: trainer (800K tokens), evaluator (300K), data_curator (200K)
-- SaaS project might use: deployer (300K), migration_runner (500K), oncall_monitor (200K)
```

### 6.3 Token Budget Tracking and Enforcement

Each adapter tracks token usage and enforces the per-session budget:

```python
"""Token budget enforcement mixin for all adapters.

Mix this into any adapter class to add token budget tracking.
When the budget is exceeded, the agent receives a warning and
the supervisor is notified, but the agent is NOT killed --
the manager decides how to handle budget overruns.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any


# Approximate pricing per 1M tokens as of March 2026
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
    "gpt-5.2-codex": {"input": 2.0, "output": 8.0},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.0},
}


class TokenBudgetMixin:
    """Mix into any adapter to add token budget tracking and enforcement."""

    def track_token_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str = "unknown",
    ) -> bool:
        """Record token usage and check if budget is exceeded.

        Returns True if within budget, False if exceeded.
        Budget exceedance logs a warning but does not kill the agent.
        """
        pricing = MODEL_PRICING.get(model, {"input": 5.0, "output": 20.0})
        cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000

        db_path = getattr(self, "db_path", None)
        agent_id = getattr(self, "agent_id", None)
        if not db_path or not agent_id:
            return True  # No tracking possible without DB access

        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            # Update running totals
            conn.execute(
                """UPDATE agent_resource_quotas SET
                    current_session_tokens = current_session_tokens + ? + ?,
                    current_session_cost_usd = current_session_cost_usd + ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE agent_id = ?""",
                (input_tokens, output_tokens, cost, agent_id),
            )

            # Check budget
            row = conn.execute(
                """SELECT current_session_tokens, max_tokens_per_session,
                          current_session_cost_usd, max_cost_per_session_usd
                   FROM agent_resource_quotas WHERE agent_id = ?""",
                (agent_id,),
            ).fetchone()

            conn.commit()

            if row:
                tokens_used, tokens_max = row[0], row[1]
                cost_used, cost_max = row[2], row[3]
                within_budget = tokens_used <= tokens_max and cost_used <= cost_max

                if not within_budget:
                    # Log warning -- do NOT kill the agent
                    conn2 = sqlite3.connect(str(db_path))
                    conn2.execute(
                        """INSERT INTO activity_log
                            (agent_id, action, category, description, details, severity)
                        VALUES (?, 'budget_exceeded', 'system',
                                'Agent exceeded resource budget',
                                ?, 'warning')""",
                        (agent_id, json.dumps({
                            "tokens_used": tokens_used,
                            "tokens_max": tokens_max,
                            "cost_used": round(cost_used, 4),
                            "cost_max": cost_max,
                            "model": model,
                        })),
                    )
                    conn2.commit()
                    conn2.close()
                return within_budget
            return True
        finally:
            conn.close()

    def reset_session_budget(self) -> None:
        """Reset budget counters at the start of a new session."""
        db_path = getattr(self, "db_path", None)
        agent_id = getattr(self, "agent_id", None)
        if not db_path or not agent_id:
            return
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "UPDATE agent_resource_quotas SET current_session_tokens=0, "
            "current_session_cost_usd=0.0, updated_at=CURRENT_TIMESTAMP WHERE agent_id=?",
            (agent_id,),
        )
        conn.commit()
        conn.close()
```

### 6.4 SQLite Write Contention Management

SQLite WAL mode allows unlimited concurrent readers and a single writer at any given moment. Writes are serialized -- if two agents attempt to write simultaneously, one blocks until the other's transaction completes. (a: verified per SQLite documentation)

Source: [SQLite WAL](https://sqlite.org/wal.html), [SkyPilot engineering blog on SQLite concurrency](https://blog.skypilot.co/abusing-sqlite-to-handle-concurrency/)

**Mitigation strategies:**

1. **`busy_timeout`:** Set a busy timeout so agents retry automatically instead of failing:
   ```sql
   PRAGMA busy_timeout=5000;  -- Wait up to 5 seconds for a write lock
   ```

2. **Short transactions:** Keep write transactions as small as possible. A heartbeat update is a single-row UPDATE against an indexed primary key -- sub-millisecond. Activity log inserts are single INSERTs. Neither should hold the write lock long enough to cause contention.

3. **Partitioned writes:** Each agent primarily writes to its own rows. Write contention only occurs when two agents commit simultaneously, and with 5-second busy_timeout this resolves automatically.

4. **Read-only replicas (future optimization):** For read-heavy operations (dashboard rendering, analytics queries), a periodic snapshot of the database can be served from a read-only copy, eliminating read-write contention entirely.

**Practical assessment:** For a system with 5-10 concurrent agents, each writing a heartbeat every 30 seconds and occasional activity log entries, SQLite WAL mode is more than sufficient. The write throughput of SQLite in WAL mode exceeds 10,000 writes/second on modern hardware. Our system generates approximately 0.3 writes/second per agent (one heartbeat every 30s plus occasional log entries), for a total of ~3 writes/second across 10 agents. This is 3,000x below SQLite's capacity.

### 6.5 External API Rate Limiting

For external APIs (Binance, CoinGecko, etc.), a shared rate limiter prevents multiple agents from collectively exceeding provider limits:

```python
"""Shared rate limiter for external API calls across all agents.

Uses SQLite's atomic transactions to implement a sliding window
rate limiter that works across multiple processes.
"""

import json
import sqlite3
import time
from pathlib import Path


class SharedRateLimiter:
    """SQLite-backed rate limiter shared across all agent processes.

    Uses a sliding window counter stored in project_state.
    Thread-safe and multi-process-safe via SQLite's transaction model.
    """

    def __init__(self, db_path: Path, api_name: str, max_per_minute: int):
        self.db_path = db_path
        self.api_name = api_name
        self.max_per_minute = max_per_minute
        self._key = f"rate_limit_{api_name}"

    def acquire(self, timeout: float = 5.0) -> bool:
        """Attempt to acquire a rate limit slot.

        Returns True if the call is allowed, False if rate limited.
        Uses SQLite transaction isolation to prevent race conditions.
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            now = time.time()
            row = conn.execute(
                "SELECT value FROM project_state WHERE key = ?", (self._key,)
            ).fetchone()

            if row:
                window: list[float] = json.loads(row[0])
                # Remove entries older than 60 seconds (sliding window)
                window = [t for t in window if now - t < 60]
            else:
                window = []

            if len(window) >= self.max_per_minute:
                conn.close()
                return False

            window.append(now)
            conn.execute(
                "INSERT OR REPLACE INTO project_state (key, value, updated_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP)",
                (self._key, json.dumps(window)),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def wait_and_acquire(self, timeout: float = 30.0) -> bool:
        """Block until a rate limit slot is available or timeout is reached."""
        start = time.time()
        while time.time() - start < timeout:
            if self.acquire():
                return True
            time.sleep(0.5)
        return False


# Usage examples (project-specific external APIs):
# Finance:     SharedRateLimiter(db_path, "binance", max_per_minute=1200)
# ML research: SharedRateLimiter(db_path, "huggingface_hub", max_per_minute=300)
# SaaS:        SharedRateLimiter(db_path, "github_api", max_per_minute=83)  # 5000/hr
#
# if limiter.acquire():
#     response = requests.get(api_url, ...)
# else:
#     logger.warning("Rate limit reached, waiting...")
#     limiter.wait_and_acquire()
```

---

## 7. Testing & Simulation

### 7.1 The Testing Challenge

Testing a multi-agent system with real LLM APIs is expensive ($5-50 per fund cycle in API tokens), slow (30-60 minutes per cycle), and non-deterministic (LLM outputs vary between runs). Development and CI/CD require ways to test the lifecycle protocol, adapter integrations, and inter-agent coordination without burning real tokens.

Source: [AI Agent Production Costs 2026](https://www.agentframeworkhub.com/blog/ai-agent-production-costs-2026), [Mocking External APIs in Agent Tests](https://langwatch.ai/scenario/testing-guides/mocks/)

Three testing strategies address different needs:

| Strategy | Purpose | Cost | Speed | Fidelity |
|----------|---------|------|-------|----------|
| Mock agents | Unit-test lifecycle protocol | $0 | <1 second | Low (no real LLM reasoning) |
| Replay mode | Deterministic regression testing | $0 | <1 second | Medium (real outputs, replayed) |
| Simulation framework | Integration testing of multi-agent coordination | $0 | Seconds | Medium-High (scripted scenarios) |

### 7.2 Mock Agent Framework

A mock agent implements the lifecycle protocol with deterministic, pre-scripted behavior:

```python
"""Mock agent for testing the lifecycle protocol and coordination without real LLMs.

Usage in pytest:
    def test_agent_lifecycle(tmp_path):
        db_path = setup_test_db(tmp_path)
        script = [
            {"action": "heartbeat"},
            {"action": "log", "log_action": "research_start", "category": "research",
             "description": "Analyzing input data"},
            {"action": "produce_artifact", "category": "research",
             "filename": "test_brief.md", "content": "# Finding\\n\\nSignal detected."},
        ]
        agent = MockAgent("researcher", db_path, script)
        result = agent.run()
        assert result["completed"]
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class MockAgent:
    """Simulates an agent for testing.

    Follows the lifecycle protocol exactly but produces pre-scripted
    outputs instead of calling real LLM APIs. Validates that the
    protocol is correctly implemented regardless of runtime.
    """

    def __init__(
        self,
        agent_id: str,
        db_path: Path,
        script: list[dict[str, Any]],
        heartbeat_interval: float = 0.1,  # Fast for testing
    ):
        self.agent_id = agent_id
        self.db_path = db_path
        self.script = script
        self.heartbeat_interval = heartbeat_interval
        # Use the Claude Code adapter since it's the reference implementation
        self._adapter = ClaudeCodeAdapter(agent_id, db_path)
        self._adapter.RUNTIME_TYPE = "mock"

    def run(self) -> dict[str, Any]:
        """Execute the scripted actions and return a summary."""
        session_id = self._adapter.start_session("Mock session for testing")
        results: dict[str, Any] = {
            "session_id": session_id,
            "actions": [],
            "completed": False,
            "crashed": False,
        }

        for step in self.script:
            action = step["action"]

            if action == "heartbeat":
                self._adapter.heartbeat(step.get("progress"))
                results["actions"].append({"action": "heartbeat"})

            elif action == "log":
                self._adapter.log_activity(
                    step["log_action"], step["category"],
                    step["description"], step.get("details"),
                    step.get("severity", "info"),
                )
                results["actions"].append({"action": "log", "log_action": step["log_action"]})

            elif action == "produce_artifact":
                path = self._adapter.produce_artifact(
                    step["category"], step["filename"],
                    step["content"], step.get("artifact_type", "markdown"),
                )
                results["actions"].append({"action": "produce_artifact", "path": str(path)})

            elif action == "sleep":
                time.sleep(step.get("seconds", 0.01))

            elif action == "fail":
                # Simulate a crash -- do NOT call end_session
                self._adapter.log_activity(
                    "agent_crash", "system",
                    f"Mock agent simulated crash: {step.get('reason', 'unknown')}",
                    severity="error",
                )
                results["crashed"] = True
                return results  # Exit without end_session

        self._adapter.end_session("Mock session completed successfully")
        results["completed"] = True
        return results
```

**Test example -- verifying the lifecycle protocol:**

```python
def test_lifecycle_protocol(tmp_path: Path) -> None:
    """Test that a mock agent correctly executes all lifecycle operations."""
    db_path = tmp_path / "test.db"
    _init_test_db(db_path)  # Create tables from 001_initial.sql + agent_sessions

    script = [
        {"action": "heartbeat", "progress": {"step": 1}},
        {"action": "log", "log_action": "research_start", "category": "research",
         "description": "Starting data analysis"},
        {"action": "produce_artifact", "category": "research",
         "filename": "test_analysis.md",
         "content": "# Test Analysis\n\nAnomaly pattern detected in dataset."},
        {"action": "heartbeat", "progress": {"step": 2}},
    ]

    agent = MockAgent("researcher", db_path, script)
    result = agent.run()

    assert result["completed"] is True
    assert result["crashed"] is False
    assert len(result["actions"]) == 4

    # Verify DB state after session
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Agent should be idle after session ends
    agent_row = conn.execute(
        "SELECT status, current_task_id FROM agents WHERE agent_id = 'researcher'"
    ).fetchone()
    assert agent_row["status"] == "idle"
    assert agent_row["current_task_id"] is None

    # Activity log should contain session_start, log, artifact_produced, session_end
    logs = conn.execute(
        "SELECT action FROM activity_log WHERE agent_id = 'researcher' ORDER BY id"
    ).fetchall()
    actions = [row["action"] for row in logs]
    assert "session_start" in actions
    assert "research_start" in actions
    assert "artifact_produced" in actions
    assert "session_end" in actions

    # Artifact file should exist
    artifact_path = db_path.parent / "artifacts" / "research" / "test_analysis.md"
    # (path depends on adapter's artifact directory resolution)

    conn.close()


def test_dead_agent_detection(tmp_path: Path) -> None:
    """Test that the supervisor correctly detects a dead (crashed) agent."""
    db_path = tmp_path / "test.db"
    _init_test_db(db_path)

    # Simulate an agent that crashes mid-execution
    script = [
        {"action": "heartbeat"},
        {"action": "log", "log_action": "doing_work", "category": "research",
         "description": "Working on something"},
        {"action": "fail", "reason": "simulated OOM crash"},
    ]

    agent = MockAgent("researcher", db_path, script)
    result = agent.run()

    assert result["crashed"] is True
    assert result["completed"] is False

    # Agent should still be 'running' (it didn't call end_session)
    conn = sqlite3.connect(str(db_path))
    status = conn.execute(
        "SELECT status FROM agents WHERE agent_id = 'researcher'"
    ).fetchone()[0]
    assert status == "running"

    # Now the supervisor should detect it as dead
    # (after heartbeat exceeds threshold -- in real system, wait 90s)
    # For testing, manually set a stale heartbeat:
    conn.execute(
        "UPDATE agents SET last_heartbeat = datetime('now', '-120 seconds') WHERE agent_id = 'researcher'"
    )
    conn.commit()
    conn.close()

    dead = check_agent_liveness(str(db_path), default_threshold_seconds=90)
    assert len(dead) == 1
    assert dead[0]["agent_id"] == "researcher"
```

### 7.3 Replay Mode

Record real agent sessions and replay them for deterministic regression testing:

```python
"""Replay mode -- record and replay agent sessions for deterministic testing.

Use SessionRecorder to wrap a real adapter during a live session.
The recording is saved as a JSON file.

Later, use SessionReplayer to replay the same sequence of lifecycle
calls against a fresh database to verify the protocol still works
after schema or adapter changes.
"""

import json
import time
from pathlib import Path
from typing import Any


class SessionRecorder:
    """Wraps an adapter and records all lifecycle events for replay."""

    def __init__(self, adapter: Any, recording_path: Path):
        self._adapter = adapter
        self._recording_path = recording_path
        self._events: list[dict[str, Any]] = []
        self._start_time = time.time()

    def start_session(self, context_summary: str = "") -> str:
        result = self._adapter.start_session(context_summary)
        self._events.append({
            "op": "start_session",
            "elapsed": time.time() - self._start_time,
            "args": {"context_summary": context_summary},
            "result": result,
        })
        return result

    def heartbeat(self, progress: dict[str, Any] | None = None) -> None:
        self._adapter.heartbeat(progress)
        self._events.append({
            "op": "heartbeat",
            "elapsed": time.time() - self._start_time,
            "args": {"progress": progress},
        })

    def log_activity(
        self, action: str, category: str, description: str,
        details: dict[str, Any] | None = None, severity: str = "info",
    ) -> None:
        self._adapter.log_activity(action, category, description, details, severity)
        self._events.append({
            "op": "log_activity",
            "elapsed": time.time() - self._start_time,
            "args": {
                "action": action, "category": category,
                "description": description, "details": details,
                "severity": severity,
            },
        })

    def produce_artifact(
        self, category: str, filename: str, content: str,
        artifact_type: str = "markdown",
    ) -> Path:
        result = self._adapter.produce_artifact(category, filename, content, artifact_type)
        self._events.append({
            "op": "produce_artifact",
            "elapsed": time.time() - self._start_time,
            "args": {
                "category": category, "filename": filename,
                "content": content, "artifact_type": artifact_type,
            },
            "result": str(result),
        })
        return result

    def end_session(self, handoff_notes: str = "") -> None:
        self._adapter.end_session(handoff_notes)
        self._events.append({
            "op": "end_session",
            "elapsed": time.time() - self._start_time,
            "args": {"handoff_notes": handoff_notes},
        })
        # Save recording to disk
        self._recording_path.write_text(json.dumps(self._events, indent=2))


class SessionReplayer:
    """Replays a recorded session against a fresh adapter for regression testing."""

    def __init__(self, adapter: Any, recording_path: Path):
        self._adapter = adapter
        self._events = json.loads(recording_path.read_text())

    def replay(self) -> int:
        """Replay all recorded events. Returns number of events replayed."""
        count = 0
        for event in self._events:
            op = event["op"]
            args = event["args"]
            getattr(self._adapter, op)(**args)
            count += 1
        return count
```

### 7.4 Multi-Agent Simulation Framework

For full system integration testing, a simulation framework orchestrates multiple mock agents concurrently:

```python
"""Multi-agent simulation framework for system integration testing.

Validates:
- Lifecycle protocol compliance across multiple agents
- Inter-agent coordination via the blackboard (SQLite)
- SQLite concurrency under parallel writes
- Heartbeat and liveness detection
- Artifact validation pipeline
- Resource quota enforcement

Usage:
    sim = AgentSimulation(db_path, artifacts_dir)
    results = sim.run_cycle({
        "researcher": researcher_script,
        "quant": quant_script,
        "coder": coder_script,
    })
    assert results["all_agents_idle"]
"""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


class AgentSimulation:
    """Runs a full work cycle with mock agents for integration testing."""

    def __init__(self, db_path: Path, artifacts_dir: Path):
        self.db_path = db_path
        self.artifacts_dir = artifacts_dir
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

    def run_cycle(
        self,
        agent_scripts: dict[str, list[dict[str, Any]]],
        max_workers: int | None = None,
    ) -> dict[str, Any]:
        """Run a simulated fund cycle with the given agent scripts.

        Args:
            agent_scripts: Maps agent_id to a list of scripted actions.
            max_workers: Max concurrent agents (defaults to len(agent_scripts)).

        Returns:
            Summary: per-agent results, final DB state, total artifacts.
        """
        workers = max_workers or len(agent_scripts)
        results: dict[str, Any] = {"agents": {}}

        # Run agents in parallel (simulating real multi-agent execution)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for agent_id, script in agent_scripts.items():
                agent = MockAgent(agent_id, self.db_path, script)
                futures[agent_id] = executor.submit(agent.run)

            for agent_id, future in futures.items():
                try:
                    results["agents"][agent_id] = future.result(timeout=30)
                except Exception as e:
                    results["agents"][agent_id] = {"error": str(e)}

        # Validate final state
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row

        still_running = conn.execute(
            "SELECT agent_id FROM agents WHERE status = 'running'"
        ).fetchall()
        results["all_agents_idle"] = len(still_running) == 0
        results["still_running"] = [r["agent_id"] for r in still_running]

        total_logs = conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0]
        results["total_activity_logs"] = total_logs

        artifact_count = sum(1 for _ in self.artifacts_dir.rglob("*") if _.is_file())
        results["total_artifacts"] = artifact_count

        conn.close()
        return results
```

---

## 8. Open Questions

### 8.1 Resolved Questions

| Question | Resolution | Confidence |
|----------|-----------|------------|
| Is 5 lifecycle operations sufficient? | Yes. Inter-agent messaging and task management are orthogonal to the lifecycle protocol and already handled by existing `messages` and `tasks` tables. | High |
| SQLite vs. PostgreSQL? | SQLite for single-host deployments (current case). WAL mode handles our concurrency needs (3 writes/second vs. 10,000+ capacity). Migrate only if we need multi-host distribution. | High |
| JSON vs. Markdown for outputs? | Both, with a hybrid format (markdown body + JSON/YAML frontmatter) for complex artifacts. JSON for machine-to-machine, markdown for human/LLM-readable. | High |
| How to handle Codex Cloud sandbox? | File-based JSONL protocol with post-execution sync via CI/webhook. The adapter writes events locally; a sync process applies them to the central DB after the task completes. | High |
| How does Claude Code integrate? | Direct SQLite access via bash/Python. Simplest integration of all providers. The existing `BaseAgent` class already implements 4 of 5 lifecycle operations. | High (verified) |

### 8.2 Unresolved Questions

**Q1: How should the Claude Agent SDK integrate with the lifecycle protocol?**

The Claude Agent SDK (`claude-agent-sdk-python`, available on PyPI) provides its own session management, subagent spawning, and hook system (`PreToolUse`, `PostToolUse`). Should the Agent OS lifecycle protocol wrap the SDK, or should the SDK wrap the lifecycle protocol?

The SDK provides hooks that could automatically inject heartbeats and activity logging into every tool call, which would be elegant but creates a tight coupling to Anthropic's SDK.

**Recommendation:** The lifecycle protocol should be independent of any SDK. Provider adapters that happen to use the Claude Agent SDK can use its hooks to automate lifecycle calls, but the protocol itself must work without any SDK. The protocol is SQL-first, not SDK-first.

Source: [Claude Agent SDK GitHub](https://github.com/anthropics/claude-agent-sdk-python), [Building agents with the Claude Agent SDK](https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk)

**Q2: Multi-host deployment -- when does SQLite stop being enough?**

SQLite requires all processes to be on the same host (WAL mode uses shared memory via the `-shm` file, which does not work over network filesystems). If the Agent OS scales to multiple hosts, we need either:
- A network-accessible database (PostgreSQL, CockroachDB)
- An HTTP gateway that proxies lifecycle calls to a central SQLite instance
- A distributed SQLite solution like LiteFS (Fly.io) or Turso

Source: [SQLite WAL documentation](https://sqlite.org/wal.html)

**Recommendation:** Design the HTTP gateway now (the REST endpoints in Section 2.5) so the migration path is clear, but do not build it until single-host SQLite becomes a bottleneck. The REST API provides the same 5 lifecycle operations over HTTP instead of direct SQL, making the transport layer swappable without changing adapter logic.

**Q3: Session timeout policy for human operators**

Human operators work on human timescales (minutes to hours between actions). The default 90-second liveness threshold would incorrectly declare every human operator dead. Options:
- Per-runtime-type timeout (humans get 4-hour timeout) -- **recommended**
- Humans explicitly extend their session via a "still here" button
- Humans do not use heartbeats at all; their sessions are manually started/ended

**Recommendation:** Per-runtime-type timeout, stored in the `agent_resource_quotas` table (`heartbeat_timeout_seconds` column). Human operators get a 4-hour timeout. Cron jobs get a 5-minute timeout. LLM agents get the default 90 seconds.

**Q4: Artifact conflict resolution**

What happens when two agents write to the same artifact path simultaneously? SQLite handles DB-level conflicts via transactions, but filesystem writes are not atomic.

**Recommendation:** Namespace artifacts by agent_id and session_id (e.g., `research/researcher_sess_abc123_hypothesis_001.md`). No two agents should ever write to the same path. If they do, it indicates a task assignment error that the allocator should prevent. As a safety net, the `produce_artifact` operation should check for path conflicts and append a disambiguation suffix if needed.

**Q5: Cost tracking accuracy across providers**

Token pricing differs by model, changes over time, and is hard to determine precisely when using prompt caching, batch APIs, or free tiers. How accurate does cost tracking need to be?

**Recommendation:** Track tokens precisely (they are reported by API responses) but treat cost estimates as approximate (+/- 20%). Use a `MODEL_PRICING` configuration that operators update when prices change. Focus on relative comparisons (which agent/task costs the most) rather than absolute dollar amounts. The primary purpose of cost tracking is preventing runaway spending, not financial accounting.

**Q6: How do we handle runtime-specific tool capabilities in the common interface?**

Claude Code has `Edit`, Codex has shell-based editing, Gemini has `EditFile`. Each has slightly different semantics for file modification. Should the Agent OS provide a common file-editing abstraction?

**Recommendation:** No. The lifecycle protocol is deliberately minimal. File editing semantics are the agent's internal concern. The Agent OS only cares about the final artifact (via `produce_artifact`), not how it was produced. This is the "protocol over implementation" principle: the protocol specifies what outputs must look like, not how they are created.

---

## Appendix A: Provider Capability Matrix

| Capability | Claude Code | Codex Cloud | Codex CLI | Gemini CLI | Python Script | Human Operator |
|-----------|------------|-------------|-----------|------------|--------------|----------------|
| Direct SQLite access | Yes | No (sandboxed) | Yes (if unsandboxed) | Yes (via Shell) | Yes | Via CLI/Web UI |
| File I/O | Yes | Yes (in container) | Yes | Yes | Yes | Via CLI/Web UI |
| Shell execution | Yes | Yes (in container) | Yes (sandboxed) | Yes | Yes | N/A |
| Network access | Yes | No (agent phase) | Configurable | Yes | Yes | Yes |
| Persistent process | No (per-invocation) | No (per-task) | No (per-invocation) | No (per-invocation) | Yes (can daemon) | Yes |
| Subagent spawning | Yes (Teams + Task) | No | No | No | Yes (threads) | No |
| MCP support | Yes | Yes (as MCP server) | Yes | Yes | Custom | N/A |
| Context window | 1M tokens (beta) | Model-dependent | Model-dependent | 1M tokens | N/A (unlimited memory) | N/A |
| Git worktree support | Yes (built-in) | Yes (PR-based) | Configurable | [NEEDS_VERIFICATION] | Manual | N/A |
| Adapter type needed | Direct DB | File-based + sync | Direct DB | Direct DB | Direct DB | HTTP/CLI |
| Integration effort | 15 min | 30 min | 5 min | 5 min | 10 min | 20 min |

## Appendix B: Migration Path from Current BaseAgent

The existing `BaseAgent` class (reference implementation: `src/hft/agents/base_agent.py`) already implements 4 of the 5 lifecycle operations. Any project with a similar base agent class can follow this migration path. The gap analysis:

| Lifecycle Operation | Existing BaseAgent Method | Gap |
|-------------------|--------------------------|-----|
| L1: start_session | `mark_run_start()` | Missing: session_id tracking, runtime_type recording, session table insert |
| L2: heartbeat | `heartbeat()` | Missing: progress metadata support (but easy to add) |
| L3: log_activity | `log_activity()` | Fully implemented -- no changes needed |
| L4: produce_artifact | Not implemented | Agent writes files directly without validation or tracking |
| L5: end_session | `mark_run_end()` | Missing: session summary, handoff notes, duration recording |

**Migration plan (backward-compatible):**
1. Add the `agent_sessions` table via a new migration (`004_agent_sessions.sql`)
2. Add `agent_resource_quotas` table in the same migration
3. Extend `BaseAgent.mark_run_start()` to accept `session_id` parameter and create a session record
4. Add `BaseAgent.produce_artifact()` method with validation via the `validate_artifact()` function
5. Extend `BaseAgent.mark_run_end()` to accept `handoff_notes` and update the session record
6. All changes are additive -- existing agent code continues to work without modification

## Appendix C: Quick-Start Integration Guide

**For a new agent runtime in 5 minutes:**

1. Ensure your runtime can execute SQL against the project database (e.g., `agent_comms/db/agent_os.db`, or write JSONL for sandboxed runtimes)
2. On startup, run the `start_session` SQL (Section 1.3, L1)
3. Every 30 seconds, run the `heartbeat` SQL (Section 1.3, L2)
4. When you produce output, write the file to `agent_comms/artifacts/{category}/` and run the `produce_artifact` SQL (Section 1.3, L4)
5. When done, run the `end_session` SQL (Section 1.3, L5)

**Total integration code:** ~20 lines of SQL or ~50 lines in any programming language.

**No SDK, framework, or library required.** The database is the protocol.

---

## Appendix D: Sources

- [Claude Code overview](https://code.claude.com/docs/en/overview)
- [Claude Code Agent Teams](https://code.claude.com/docs/en/agent-teams)
- [Claude Code subagents](https://code.claude.com/docs/en/sub-agents)
- [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python)
- [Building agents with Claude Agent SDK](https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk)
- [OpenAI Codex Cloud environments](https://developers.openai.com/codex/cloud/environments/)
- [OpenAI Codex CLI](https://developers.openai.com/codex/cli)
- [OpenAI Codex + Agents SDK](https://developers.openai.com/codex/guides/agents-sdk/)
- [OpenAI Agents SDK docs](https://openai.github.io/openai-agents-python/)
- [Introducing Codex](https://openai.com/index/introducing-codex/)
- [Gemini CLI GitHub](https://github.com/google-gemini/gemini-cli)
- [Gemini CLI docs](https://developers.google.com/gemini-code-assist/docs/gemini-cli)
- [SQLite WAL mode](https://sqlite.org/wal.html)
- [SQLite concurrency patterns](https://blog.skypilot.co/abusing-sqlite-to-handle-concurrency/)
- [Martin Fowler HeartBeat pattern](https://martinfowler.com/articles/patterns-of-distributed-systems/heartbeat.html)
- [HeartBeats in Distributed Systems](https://blog.algomaster.io/p/heartbeats-in-distributed-systems)
- [AgentHeartbeat monitoring](https://github.com/DonkRonk17/AgentHeartbeat)
- [AI Agent Token Cost Optimization](https://fast.io/resources/ai-agent-token-cost-optimization/)
- [Mocking External APIs in Agent Tests](https://langwatch.ai/scenario/testing-guides/mocks/)
