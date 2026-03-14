# Research 09: Project Onboarding System

**Date:** 2026-03-08
**Researcher:** Agent 09 (Project Onboarding)
**Status:** Complete
**Validation:** Claims tagged with source basis: (a) established practice in developer tooling and project scaffolding, (b) observed in existing multi-agent and DevOps systems, (c) novel proposal. Confidence marked [HIGH], [MEDIUM], or [LOW].

---

## 1. Executive Summary

The Agent Operating System is useless if projects cannot get onboarded. This document defines the complete onboarding protocol for two scenarios: **greenfield** (empty directory, new project) and **brownfield** (existing codebase with history, workflows, conventions, and domain knowledge). The brownfield case is harder and more important -- most real-world value comes from augmenting existing projects, not starting from scratch.

The core challenge: the Agent OS must bootstrap its own coordination infrastructure (SQLite database, project config, agent roles, goal tree, plan templates) *without disrupting* the existing project's structure, workflows, or conventions. It must discover what the project is, what tools it uses, what "done" looks like, and what agent roles would be useful -- all from introspection of the codebase and its metadata.

**Key design decisions:**

1. **Project discovery is a structured pipeline, not a single LLM call.** The system runs a deterministic sequence of file-system scans, pattern matchers, and schema extractors, then feeds the structured results to an LLM for interpretation. This avoids the "magic black box" failure where the LLM hallucinates project structure it did not actually observe. [HIGH confidence]

2. **The project configuration file (`project.yaml`) is the single source of truth** for how the Agent OS interacts with this project. It declares domain tables, agent roles, plan templates, acceptance criteria defaults, resource constraints, and integration points. Discovery proposes it; the human approves it; the system enforces it. [HIGH confidence]

3. **Onboarding is incremental and non-destructive.** The Agent OS creates its own directory (`.agent-os/`) inside the project root. It never modifies existing files unless explicitly instructed. Existing CI/CD, scripts, and workflows continue to work unchanged. The Agent OS is an overlay, not a replacement. [HIGH confidence]

4. **Brownfield onboarding produces a "project understanding" artifact** -- a structured document that the human reviews before the system begins operating. This is the single most important trust-building moment. If the system misunderstands the project, the human catches it here, not after agents have been running for hours. [HIGH confidence]

5. **Agent roles are inferred from project structure, not assumed from templates.** A trading project needs researchers and quants. An ML research project needs experiment designers and script builders. A SaaS project needs frontend/backend/devops specialists. The system proposes roles based on what it discovers, not from a fixed menu. [MEDIUM confidence -- role inference quality depends on LLM capability]

---

## 2. Two Modes: Greenfield vs Brownfield

### 2.1 Mode Selection

The onboarding CLI detects which mode to use automatically:

```bash
# User invokes onboarding
aos init /path/to/project
```

**Detection logic:**

```python
def detect_mode(project_dir: Path) -> str:
    """Determine if this is a greenfield or brownfield project."""
    contents = list(project_dir.iterdir())

    # Filter out hidden files, .git, and common noise
    meaningful = [f for f in contents
                  if not f.name.startswith('.')
                  and f.name not in ('LICENSE', 'LICENSE.txt', '.gitignore')]

    if len(meaningful) == 0:
        return 'greenfield'

    # Check for code indicators
    code_extensions = {'.py', '.js', '.ts', '.go', '.rs', '.java', '.rb', '.cpp', '.c'}
    has_code = any(
        f.suffix in code_extensions
        for f in project_dir.rglob('*')
        if f.is_file()
    )
    has_readme = (project_dir / 'README.md').exists() or (project_dir / 'README.rst').exists()
    has_package_manager = any(
        (project_dir / f).exists()
        for f in ['pyproject.toml', 'package.json', 'Cargo.toml', 'go.mod',
                  'Gemfile', 'pom.xml', 'build.gradle']
    )

    if has_code or has_readme or has_package_manager:
        return 'brownfield'

    return 'greenfield'
```

### 2.2 Greenfield Overview

Greenfield is the simpler case. The system needs to:
1. Ask the user what they want to build
2. Propose a project structure, agent roles, and initial goals
3. Scaffold the directory structure and Agent OS infrastructure
4. Create the initial goal tree for the human to approve

The output is a working project directory with Agent OS infrastructure ready to go.

### 2.3 Brownfield Overview

Brownfield is the complex case. The system needs to:
1. Introspect the codebase without modifying it
2. Build a structured understanding of the project
3. Propose agent roles, plan templates, and initial goals based on discoveries
4. Bootstrap the Agent OS database alongside existing infrastructure
5. Import existing knowledge (docs, logs, conventions) into the system's memory
6. Present everything to the human for review and approval

The output is an Agent OS overlay on an existing project, with the human's explicit approval of the system's understanding.

---

## 3. Project Discovery Protocol (Brownfield)

The discovery protocol runs a pipeline of analyzers, each producing structured output that feeds into the next. The pipeline is deterministic and inspectable -- every discovery is traceable to a specific file or pattern match.

### 3.1 Pipeline Architecture

```
Phase 1: Filesystem Scan       -> project_structure.json
Phase 2: Language & Framework   -> tech_stack.json
Phase 3: Workflow Discovery     -> workflows.json
Phase 4: Documentation Ingestion -> knowledge_base.json
Phase 5: Agent Role Inference   -> proposed_roles.json
Phase 6: Tool Integration       -> integrations.json
Phase 7: Synthesis              -> project_understanding.md + project.yaml (draft)
```

Each phase produces a structured artifact. The final synthesis phase combines all artifacts into a human-readable understanding document and a draft `project.yaml`.

### 3.2 Phase 1: Filesystem Scan

**Purpose:** Map the project structure, identify major directories, estimate project size, and detect organizational patterns.

**Implementation:**

```python
def scan_filesystem(project_dir: Path) -> dict:
    """Produce a structural map of the project."""
    result = {
        'root': str(project_dir),
        'total_files': 0,
        'total_dirs': 0,
        'file_types': {},           # extension -> count
        'top_level_dirs': [],       # [{name, file_count, primary_type}]
        'notable_files': [],        # Files that indicate project type
        'estimated_loc': 0,         # Lines of code (approximate)
        'gitignore_patterns': [],   # What's excluded
        'large_files': [],          # Files > 1MB (data, models, binaries)
    }

    # Walk the tree, respecting .gitignore
    for path in walk_respecting_gitignore(project_dir):
        result['total_files'] += 1
        ext = path.suffix.lower()
        result['file_types'][ext] = result['file_types'].get(ext, 0) + 1

    # Identify notable files
    notable_patterns = {
        'pyproject.toml': 'python_project',
        'setup.py': 'python_project',
        'package.json': 'node_project',
        'Cargo.toml': 'rust_project',
        'go.mod': 'go_project',
        'Makefile': 'has_make',
        'Dockerfile': 'has_docker',
        'docker-compose.yml': 'has_docker_compose',
        '.github/workflows': 'has_github_actions',
        '.gitlab-ci.yml': 'has_gitlab_ci',
        'CLAUDE.md': 'has_claude_config',
        'AGENTS.md': 'has_agent_config',
        '.claude/agents': 'has_claude_agents',
        'CLAUDE.md': 'has_claude_md',
    }

    for pattern, indicator in notable_patterns.items():
        if (project_dir / pattern).exists():
            result['notable_files'].append({
                'path': pattern,
                'indicator': indicator
            })

    return result
```

**Key outputs:**
- File type distribution (is this primarily Python? TypeScript? Mixed?)
- Project size (LOC, file count) -- informs how many agents might be needed
- Organizational pattern (monorepo? package per concern? flat?)
- Notable files that immediately indicate project nature

### 3.3 Phase 2: Language & Framework Detection

**Purpose:** Identify the tech stack, including languages, frameworks, package managers, and runtime requirements.

**Detection sources (ordered by reliability):**

| Source | What It Reveals | Reliability |
|--------|----------------|-------------|
| `pyproject.toml` / `setup.py` | Python version, dependencies, project metadata | HIGH |
| `package.json` | Node.js version, framework (React, Next.js, Express), dependencies | HIGH |
| `Cargo.toml` | Rust edition, crate dependencies | HIGH |
| `requirements.txt` | Python dependencies (less structured than pyproject.toml) | MEDIUM |
| Import analysis | Frameworks actually used in code (not just declared) | MEDIUM |
| Config files | Framework-specific config (`.eslintrc`, `ruff.toml`, `tsconfig.json`) | HIGH |
| Docker files | Runtime environment, system dependencies | MEDIUM |

**Output structure:**

```json
{
  "primary_language": "python",
  "language_version": "3.12",
  "package_manager": "uv",
  "frameworks": [
    {"name": "lightgbm", "category": "ml", "version": "4.x"},
    {"name": "pandas", "category": "data", "version": "2.x"},
    {"name": "numpy", "category": "data", "version": "1.x"}
  ],
  "dev_tools": {
    "linter": "ruff",
    "formatter": "ruff",
    "test_runner": "pytest",
    "type_checker": null
  },
  "runtime_constraints": [
    {"type": "gpu_exclusivity", "reason": "LightGBM GPU training requires sequential execution"},
    {"type": "conda_env", "name": "lightgbm", "reason": "Specific environment required"}
  ]
}
```

[FRAGILE] **Runtime constraints are critical and easy to miss.** The Numerai project has a GPU exclusivity constraint ("training runs must be executed sequentially, one at a time -- never in parallel") that is documented only in CLAUDE.md, not in any config file. The discovery system must parse documentation for constraints, not just config files. This is where LLM-based analysis adds value over pure pattern matching.

### 3.4 Phase 3: Workflow Discovery

**Purpose:** Identify existing automation, scripts, entry points, and CI/CD pipelines. These represent the project's existing "agent-like" behaviors that the Agent OS should integrate with, not replace.

**What to discover:**

1. **CLI entry points** -- Commands the project exposes
   - Python: `[project.scripts]` in `pyproject.toml`, `console_scripts` in `setup.py`
   - Node: `"scripts"` in `package.json`
   - Makefiles: targets and their descriptions
   - Custom scripts in `scripts/`, `bin/`, `tools/` directories

2. **CI/CD pipelines** -- Automated workflows already in place
   - `.github/workflows/*.yml` -- GitHub Actions
   - `.gitlab-ci.yml` -- GitLab CI
   - `Jenkinsfile`, `Taskfile.yml`, `justfile`
   - What triggers them, what they do, what they produce

3. **Existing agent/skill definitions** -- Claude Code agents, Codex skills, etc.
   - `.claude/agents/*.md` -- Claude Code custom agents
   - `agents/skills/*/SKILL.md` -- Codex-compatible skills
   - `AGENTS.md` -- Agent instructions

4. **Database/state management**
   - SQLite databases (`.db`, `.sqlite`)
   - Configuration databases
   - State files (`*.state`, `*.lock`)

5. **Data pipelines**
   - Data directories (large files, parquet, CSV)
   - ETL scripts
   - Cache directories and strategies

**Example: Numerai project workflow discovery output:**

```json
{
  "cli_entry_points": [
    {
      "command": "python -m agents.code.modeling --config <path>",
      "purpose": "Train a model from a config file",
      "category": "training"
    },
    {
      "command": "python -m agents.code.analysis.show_experiment",
      "purpose": "Generate comparison plots",
      "category": "analysis"
    },
    {
      "command": "python -m agents.code.data.build_full_datasets",
      "purpose": "Build training datasets",
      "category": "data_prep"
    },
    {
      "command": "python -m production.cli train|validate|package",
      "purpose": "Production pipeline CLI",
      "category": "production"
    }
  ],
  "ci_cd": [
    {
      "file": ".github/workflows/build-models.yml",
      "trigger": "push to master, workflow_dispatch",
      "purpose": "Build example model pickles from notebooks",
      "produces": ["cached-pickles/*.pkl"]
    }
  ],
  "existing_agents": [
    {
      "name": "numerai-researcher",
      "file": ".claude/agents/numerai-researcher.md",
      "role": "Research agent scanning arxiv, Kaggle, forums",
      "model": "opus",
      "tools": ["Read", "Grep", "Glob", "WebSearch", "WebFetch"]
    },
    {
      "name": "numerai-script-builder",
      "file": ".claude/agents/numerai-script-builder.md",
      "role": "Generate experiment scripts from hypotheses",
      "model": "opus",
      "skills": ["numerai-experiment-design"]
    },
    {
      "name": "numerai-docs-updater",
      "file": ".claude/agents/numerai-docs-updater.md",
      "role": "Update experiment documentation after results",
      "model": "sonnet"
    },
    {
      "name": "numerai-experiment-runner",
      "file": ".claude/agents/numerai-experiment-runner.md",
      "role": "Execute scripts, monitor GPU, extract results",
      "model": "haiku"
    }
  ],
  "existing_skills": [
    {
      "name": "numerai-experiment-design",
      "file": "numerai/agents/skills/numerai-experiment-design/SKILL.md",
      "purpose": "Design, run, and report experiments"
    },
    {
      "name": "numerai-model-implementation",
      "file": "numerai/agents/skills/numerai-model-implementation/SKILL.md",
      "purpose": "Add new model types to the pipeline"
    },
    {
      "name": "numerai-model-upload",
      "file": "numerai/agents/skills/numerai-model-upload/SKILL.md",
      "purpose": "Create and deploy pickle files for submission"
    }
  ],
  "data_locations": [
    {"path": "numerai/v5.2/", "type": "training_data", "gitignored": true},
    {"path": "numerai/agents/experiments/", "type": "experiment_results", "gitignored": false},
    {"path": "cached-pickles/", "type": "model_artifacts", "gitignored": false}
  ],
  "caching_strategy": {
    "prediction_cache": "per-fold predictions saved after each fold",
    "data_cache": "processed datasets cached as parquet",
    "oof_cache": "{output_dir}/cache/{config_hash}.parquet"
  }
}
```

### 3.5 Phase 4: Documentation Ingestion

**Purpose:** Extract domain knowledge, conventions, lessons learned, and operating rules from existing documentation. This becomes the Agent OS's initial memory -- what a new team member would read on their first day.

**Sources (priority order):**

1. **CLAUDE.md / AGENTS.md** -- If these exist, they are the richest source of project conventions, constraints, and agent instructions. They represent what the project owner considers essential for AI agents to know. Parse these with high attention.

2. **README.md** -- Project overview, setup instructions, usage patterns.

3. **Devlogs / postmortems** (e.g., `DEVLOG.md`) -- Failure memory. These document what went wrong and how to prevent recurrence. Critical for populating the `failure_log` table.

4. **Experiment logs** (e.g., `experiment.md`, `experiments_plan.md`) -- What has been tried, what worked, what did not. Populates the knowledge base and informs initial goals.

5. **Inline documentation** -- Docstrings, comments with "IMPORTANT", "WARNING", "HACK", "TODO". These are embedded conventions.

6. **Configuration files with comments** -- Often contain rationale for specific settings.

**Ingestion strategy:**

```python
class DocumentationIngester:
    """Extract structured knowledge from project documentation."""

    def ingest(self, project_dir: Path) -> dict:
        knowledge = {
            'conventions': [],       # Rules and coding standards
            'constraints': [],       # Hard limits (GPU exclusivity, rate limits, etc.)
            'failure_memory': [],    # Past failures and lessons learned
            'domain_vocabulary': {}, # Key terms and their meanings
            'operating_rules': [],   # Rules agents must follow
            'experiment_history': [],# What has been tried
            'success_patterns': [],  # What works well
            'anti_patterns': [],     # What to avoid
        }

        # Parse CLAUDE.md if it exists
        claude_md = project_dir / 'CLAUDE.md'
        if claude_md.exists():
            knowledge.update(self._parse_claude_md(claude_md))

        # Parse DEVLOG for failure memory
        for devlog in project_dir.rglob('DEVLOG.md'):
            knowledge['failure_memory'].extend(
                self._extract_failures(devlog)
            )

        # Parse experiment docs for history
        for exp_doc in project_dir.rglob('experiment.md'):
            knowledge['experiment_history'].extend(
                self._extract_experiments(exp_doc)
            )

        return knowledge
```

**Example: What the Numerai ingestion would extract:**

```yaml
conventions:
  - "Run from repo root with PYTHONPATH=numerai"
  - "Always use the lightgbm conda environment"
  - "One variable at a time per config variant (4-5 configs per round)"
  - "Simple mean ensemble -- no complex weight optimization"
  - "Medium features (780) optimal -- 'all' converges to benchmark"

constraints:
  - type: gpu_exclusivity
    description: "Training runs must be sequential, never parallel"
    reason: "Concurrent runs cause GPU access contention and hang indefinitely"
  - type: mandatory_caching
    description: "Never recompute what can be cached"
    levels: ["per-fold predictions", "expensive data loading", "intermediate transforms"]
  - type: mandatory_progress
    description: "Every experiment script MUST use tqdm for progress bars"
  - type: scoring_rules
    description: "NEVER write custom scoring functions -- use production.validation.metrics"

failure_memory:
  - id: s6_catboost_cv
    what: "CatBoost expanding CV produced look-ahead bias"
    impact: "Result retraction"
    prevention: "assert_no_lookahead() in every trainer before .fit()"
  - id: r36d_cdst_loo
    what: "CDST per-era LOO on validation data caused look-ahead"
    impact: "Result retraction"
    prevention: "Never use per-era leave-one-out on validation data"
  - id: prediction_source_bug
    what: "Using raw cache instead of production OOF for scoring"
    impact: "Metrics diverged from Numerai diagnostics"
    prevention: "Ensemble analysis MUST use production OOF files"

anti_patterns:
  - "Loss function diversity in LightGBM (huber=MSE, MAE/quantile collapse)"
  - "DART boosting (-7.4% quality at 10x cost)"
  - "Kitchen-sink features (converge to benchmark)"
  - "Complex stacking (overfits)"
  - "Self-supervised pretraining in data-rich regimes"

success_patterns:
  - "Target diversity > algorithm diversity"
  - "Ridge residual stacking: +15% sharpe"
  - "XGBoost individually beats LGBM: +6.2% bmc.sharpe"
  - "Post-prediction neutralization (0.75): free consistency win"
  - "Two diverse models > many similar models"
```

[FRAGILE] **Documentation quality varies wildly.** Some projects have detailed CLAUDE.md files with explicit conventions. Others have a bare README with "TODO: write docs." The ingestion system must degrade gracefully -- missing documentation is not an error, it is information ("this project has poor documentation, which is itself a risk factor").

### 3.6 Phase 5: Agent Role Inference

**Purpose:** Propose agent roles based on what the project actually needs, not from a fixed template. Different projects need fundamentally different agent teams.

**Inference rules:**

| Project Signal | Inferred Role | Confidence |
|---------------|---------------|------------|
| ML training pipelines, experiment configs, model files | `experiment_designer` -- designs and runs ML experiments | HIGH |
| Research docs, arxiv references, hypothesis tracking | `researcher` -- scans literature, proposes hypotheses | HIGH |
| Test suites (`tests/`, `pytest`, `jest`) | `tester` -- writes and maintains tests | MEDIUM |
| CI/CD pipelines | `devops` -- manages deployment and CI | MEDIUM |
| API endpoints, web framework | `backend_developer` -- implements API/backend | HIGH |
| React/Vue/Angular, CSS, components | `frontend_developer` -- implements UI | HIGH |
| Risk management code, monitoring | `risk_monitor` -- monitors operational health | HIGH |
| Trading/execution logic | `trader` -- manages execution and positions | HIGH |
| Data pipelines, ETL scripts | `data_engineer` -- manages data infrastructure | MEDIUM |
| Documentation files, changelogs | `docs_updater` -- maintains documentation | LOW |
| Strategy/quant code | `quant` -- designs quantitative strategies | HIGH |
| Existing `.claude/agents/` definitions | Import directly with role mapping | HIGH |

**Role inference algorithm:**

```python
def infer_roles(
    tech_stack: dict,
    workflows: dict,
    knowledge: dict,
    filesystem: dict
) -> list[dict]:
    """Propose agent roles based on project discovery."""
    roles = []

    # Always include an allocator/manager
    roles.append({
        'role': 'allocator',
        'name': 'Project Manager',
        'description': 'Coordinates all agents, decomposes goals, reviews output',
        'model': 'opus',
        'required': True,
        'source': 'default -- every project needs coordination'
    })

    # Import existing agent definitions
    for agent in workflows.get('existing_agents', []):
        roles.append({
            'role': _map_to_standard_role(agent['role']),
            'name': agent['name'],
            'description': agent.get('role', ''),
            'model': agent.get('model', 'opus'),
            'imported_from': agent['file'],
            'source': 'imported from existing agent definition'
        })

    # Infer from project structure
    if _has_ml_pipeline(tech_stack, filesystem):
        if not _role_exists(roles, 'experiment_designer'):
            roles.append({
                'role': 'experiment_designer',
                'name': 'Experiment Designer',
                'description': 'Designs ML experiments, writes configs, analyzes results',
                'model': 'opus',
                'source': f'inferred from ML pipeline: {_ml_evidence(tech_stack)}'
            })

    if _has_test_suite(filesystem):
        roles.append({
            'role': 'tester',
            'name': 'Test Engineer',
            'description': 'Writes and maintains test suites, validates implementations',
            'model': 'sonnet',
            'source': f'inferred from test suite at {_test_locations(filesystem)}'
        })

    # ... additional rules per signal type

    return roles
```

**Critical rule: existing agent definitions take priority over inference.** If the project already has `.claude/agents/numerai-researcher.md`, the system imports that definition verbatim rather than inferring a generic "researcher" role. The project owner has already done the work of defining what the agent should know and do.

### 3.7 Phase 6: Tool Integration Discovery

**Purpose:** Identify existing tools, scripts, databases, and external services that agents will need to interact with. These become the agent's "toolbox" for this specific project.

**Categories:**

1. **CLI tools** -- Project-specific commands that agents can invoke
2. **Databases** -- Existing SQLite/Postgres/etc. that contain project state
3. **External services** -- APIs, MCP servers, webhooks
4. **Scripts** -- Utility scripts in `scripts/`, `tools/`, etc.
5. **Config files** -- Settings that agents need to read/modify

**Output structure:**

```json
{
  "cli_tools": [
    {
      "command": "python -m agents.code.modeling",
      "args": "--config <path> [--output-dir <dir>]",
      "purpose": "Train model from config",
      "safe_to_automate": true,
      "resource_impact": "high_gpu",
      "typical_duration": "30-120 minutes"
    }
  ],
  "databases": [
    {
      "path": "agent_comms/db/fund.db",
      "type": "sqlite",
      "tables": ["fund_state", "strategies", "agents", "..."],
      "access_pattern": "read_write",
      "has_schema_tool": true,
      "schema_tool": "scripts/db_tool.py"
    }
  ],
  "external_services": [
    {
      "name": "Numerai MCP Server",
      "type": "mcp",
      "tools": ["check_api_credentials", "upload_model", "get_leaderboard"],
      "auth": "NUMERAI_MCP_AUTH env var",
      "required": false
    }
  ]
}
```

### 3.8 Phase 7: Synthesis

**Purpose:** Combine all discovery outputs into two deliverables:
1. `project_understanding.md` -- Human-readable summary for review
2. `project.yaml` (draft) -- Machine-readable configuration for the Agent OS

The synthesis phase uses an LLM to interpret the structured discovery data and produce coherent, contextualized output. This is the one phase where the LLM does interpretive work rather than pattern matching.

**The project understanding document** is structured as:

```markdown
# Project Understanding: [Project Name]
## Generated by Agent OS Onboarding — [date]
## Status: DRAFT — requires human review and approval

### What This Project Is
[1-paragraph summary based on README, CLAUDE.md, and code analysis]

### Tech Stack
[Table of languages, frameworks, tools]

### Project Structure
[Directory tree with annotations]

### Existing Workflows
[List of CLI commands, CI/CD pipelines, scripts]

### Existing Agent Definitions
[Imported from .claude/agents/ or AGENTS.md]

### Discovered Conventions
[Rules, constraints, and patterns extracted from docs]

### Known Failure Patterns
[Extracted from DEVLOG, postmortems]

### Proposed Agent Roles
[Table of roles with justification for each]

### Proposed Initial Goals
[What the system thinks should happen first]

### Items Requiring Human Input
[Ambiguities, unclear conventions, missing information]
```

---

## 4. Project Bootstrap Protocol (Greenfield)

### 4.1 Interactive Goal Elicitation

When the system detects an empty directory, it enters an interactive dialogue to understand what the user wants to build. This is a structured conversation, not freeform chat.

**Question sequence:**

```
Step 1: Project Type
  "What kind of project is this?"
  Options: [Software application, ML/AI research, Data pipeline,
            Trading system, Other (describe)]

Step 2: Outcome
  "What is the primary outcome you want to achieve?"
  [Free text -- becomes the strategic goal]
  Example: "Build a Numerai tournament model that achieves top-100 ranking"

Step 3: Timeline
  "What is your rough timeline?"
  Options: [Days, Weeks, Months, Ongoing/indefinite]

Step 4: Tech Stack (if known)
  "Do you have preferences for languages/frameworks?"
  [Free text or 'no preference']

Step 5: Team Size
  "How many AI agents should work on this simultaneously?"
  Options: [1-2 (solo/pair), 3-5 (small team), 6-10 (large team)]
  Default: 3-5

Step 6: Autonomy Level
  "How much autonomy should agents have?"
  Options:
    - Conservative: agents propose, human approves everything
    - Balanced: agents execute routine tasks, escalate novel ones
    - Aggressive: agents execute freely, human reviews periodically
  Default: Balanced

Step 7: Constraints
  "Any constraints I should know about?"
  [Free text -- GPU limits, API keys, budget, etc.]
```

### 4.2 Default Agent Roles by Project Type

| Project Type | Default Roles | Rationale |
|-------------|--------------|-----------|
| Software Application | `allocator`, `backend_dev`, `frontend_dev`, `tester`, `devops` | Standard software team |
| ML/AI Research | `allocator`, `researcher`, `experiment_designer`, `coder`, `docs_updater` | Research-driven iteration |
| Data Pipeline | `allocator`, `data_engineer`, `coder`, `tester`, `monitor` | ETL/pipeline focus |
| Trading System | `allocator`, `researcher`, `quant`, `coder`, `tester`, `risk_monitor` | Full alpha pipeline |

### 4.3 Scaffolding

For greenfield projects, the system creates the initial directory structure:

```
project_root/
  .agent-os/
    db/
      project.db              # Agent OS SQLite database
    config/
      project.yaml            # Project configuration
    artifacts/
      research/
      strategies/
      reports/
    logs/
  src/                        # Source code (structure depends on project type)
  tests/                      # Test directory
  docs/                       # Documentation
  scripts/                    # Utility scripts
  CLAUDE.md                   # Generated with project conventions
  .gitignore                  # With .agent-os/db/ excluded
```

**Critical principle:** The scaffolding is minimal. The system creates only the Agent OS infrastructure and a skeleton project structure. It does not generate boilerplate code -- that is the job of the first agent session, guided by the initial goals.

### 4.4 Initial Goal Tree Generation

Based on the elicitation answers, the system generates a starter goal tree:

**Example for ML Research project:**

```
Strategic: "Build high-performing Numerai tournament model" (human-set)
  |-- Tactical: "Set up ML pipeline and baseline models"
  |     |-- Operational: "Configure data loading and preprocessing"
  |     |-- Operational: "Train baseline model and establish metrics"
  |     +-- Operational: "Set up experiment tracking infrastructure"
  +-- Tactical: "Research and iterate on model improvements"
        |-- Operational: "Survey literature for applicable techniques"
        +-- Operational: "Design first experiment round"
```

The goal tree is always shallow at creation time -- consistent with the lazy decomposition principle from Research 04. Deeper levels are created by the allocator as work progresses.

---

## 5. Project Configuration Schema

### 5.1 `project.yaml` Specification

The project configuration file is the contract between the project and the Agent OS. It declares everything the OS needs to know about this specific project.

```yaml
# project.yaml — Agent OS Project Configuration
# This file is the single source of truth for how the Agent OS
# operates on this project. Human-reviewed and approved.

# ============================================================
# PROJECT IDENTITY
# ============================================================
project:
  name: "Numerai AI Experiments"
  description: "ML research for Numerai tournament — high Sharpe + high MMC"
  domain: "ml_research"           # trading | software | ml_research | data_pipeline | custom
  version: "1.0"
  created_at: "2026-03-08"

# ============================================================
# TECH STACK (discovered or declared)
# ============================================================
tech_stack:
  primary_language: "python"
  language_version: "3.12"
  package_manager: "conda"        # uv | pip | conda | npm | cargo
  environment:
    type: "conda"
    name: "lightgbm"
    activation: "conda activate lightgbm"
  command_prefix: "PYTHONPATH=numerai"

# ============================================================
# AGENT ROLES
# ============================================================
agents:
  - role: allocator
    name: "Project Manager"
    model: opus
    provider: claude
    description: "Coordinates research agenda, reviews results, decomposes goals"
    capabilities: ["goal_management", "agent_coordination", "review"]

  - role: researcher
    name: "ML Researcher"
    model: opus
    provider: claude
    description: "Scans arxiv, Kaggle, forums for applicable techniques"
    capabilities: ["web_search", "literature_review", "hypothesis_generation"]
    imported_from: ".claude/agents/numerai-researcher.md"

  - role: experiment_designer
    name: "Script Builder"
    model: opus
    provider: claude
    description: "Generates experiment scripts from hypotheses"
    capabilities: ["code_generation", "config_creation"]
    imported_from: ".claude/agents/numerai-script-builder.md"

  - role: executor
    name: "Experiment Runner"
    model: haiku
    provider: claude
    description: "Executes experiment scripts, monitors GPU, extracts results"
    capabilities: ["script_execution", "monitoring"]
    imported_from: ".claude/agents/numerai-experiment-runner.md"

  - role: docs_updater
    name: "Documentation Updater"
    model: sonnet
    provider: claude
    description: "Updates experiment documentation after results"
    capabilities: ["documentation", "cross_file_updates"]
    imported_from: ".claude/agents/numerai-docs-updater.md"

# ============================================================
# DOMAIN-SPECIFIC TABLES
# ============================================================
# These tables are created alongside core Agent OS tables.
# They hold project-specific state that agents read and write.
domain_tables:
  - name: experiments
    description: "Experiment tracking — configs, results, status"
    schema: |
      CREATE TABLE IF NOT EXISTS experiments (
          experiment_id TEXT PRIMARY KEY,
          round_number INTEGER NOT NULL,
          name TEXT NOT NULL,
          hypothesis TEXT,
          config_path TEXT,
          status TEXT NOT NULL DEFAULT 'planned'
              CHECK (status IN ('planned', 'running', 'completed', 'failed', 'retracted')),
          metrics JSON,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          completed_at TIMESTAMP
      );

  - name: models
    description: "Model registry — trained model metadata and performance"
    schema: |
      CREATE TABLE IF NOT EXISTS models (
          model_id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          model_type TEXT NOT NULL,
          config JSON,
          bmc_mean REAL,
          bmc_sharpe REAL,
          corr_mean REAL,
          benchmark_corr REAL,
          status TEXT DEFAULT 'experimental'
              CHECK (status IN ('experimental', 'candidate', 'production', 'retired')),
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      );

  - name: research_ideas
    description: "Research backlog — ideas with priority and status"
    schema: |
      CREATE TABLE IF NOT EXISTS research_ideas (
          idea_id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          source TEXT,
          priority TEXT DEFAULT 'P2'
              CHECK (priority IN ('P0', 'P1', 'P2', 'P3')),
          status TEXT DEFAULT 'proposed'
              CHECK (status IN ('proposed', 'in_progress', 'done', 'rejected')),
          hypothesis TEXT,
          expected_impact TEXT,
          kill_signal TEXT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      );

# ============================================================
# PLAN TEMPLATES
# ============================================================
plan_templates:
  - template_id: experiment_cycle
    name: "Experiment Cycle"
    description: "Full experiment round: hypothesis -> script -> run -> analyze -> document"
    domain: "ml_research"
    template_spec:
      root:
        type: tactical
        title_pattern: "Experiment Round {round_number}: {hypothesis_name}"
      children:
        - ref: hypothesis
          type: operational
          title_pattern: "Formulate hypothesis for {technique_name}"
          role: researcher
          acceptance_criteria:
            - {type: artifact_exists, path: ".agent-os/artifacts/research/{hypothesis_id}.md"}
        - ref: script
          type: operational
          title_pattern: "Generate experiment script for {technique_name}"
          role: experiment_designer
          depends_on: [hypothesis]
          acceptance_criteria:
            - {type: file_exists, path: "numerai/agents/experiments/{experiment_name}/scripts/{script_name}.py"}
            - {type: lint_clean, command: "ruff check {script_path}"}
        - ref: execute
          type: operational
          title_pattern: "Run experiment {experiment_name}"
          role: executor
          depends_on: [script]
          acceptance_criteria:
            - {type: artifact_exists, path: ".agent-os/artifacts/results/{experiment_id}_results.json"}
        - ref: document
          type: operational
          title_pattern: "Document results for {experiment_name}"
          role: docs_updater
          depends_on: [execute]
          acceptance_criteria:
            - {type: file_exists, path: "numerai/agents/experiments/{experiment_name}/experiment.md"}

  - template_id: model_deployment
    name: "Model Deployment"
    description: "Validate, package, test, and deploy a model to Numerai"
    domain: "ml_research"
    template_spec:
      root:
        type: tactical
        title_pattern: "Deploy {model_name} to Numerai tournament"
      children:
        - ref: validate
          type: operational
          title_pattern: "Validate {model_name} OOF predictions"
          role: executor
          acceptance_criteria:
            - {type: metric, source: models, model_id: "{model_id}", metric: bmc_sharpe, op: ">=", value: 0.5}
        - ref: package
          type: operational
          title_pattern: "Package {model_name} as pickle"
          role: experiment_designer
          depends_on: [validate]
          acceptance_criteria:
            - {type: file_exists, path: "{pickle_path}"}
            - {type: test_passes, command: "docker run -i --rm -v ... --debug --model {pickle_path}"}
        - ref: deploy
          type: operational
          title_pattern: "Upload {model_name} to Numerai"
          role: executor
          depends_on: [package]

# ============================================================
# ACCEPTANCE CRITERIA DEFAULTS
# ============================================================
acceptance_defaults:
  code_quality:
    - {type: lint_clean, command: "ruff check {file_path}"}
  ml_experiment:
    - {type: artifact_exists, path: ".agent-os/artifacts/results/{experiment_id}.json"}
    - {type: metric, metric: bmc_mean, op: ">", value: 0}
  documentation:
    - {type: file_exists, path: "{doc_path}"}

# ============================================================
# RESOURCE CONSTRAINTS
# ============================================================
resources:
  gpu:
    exclusive: true
    max_concurrent_training: 1
    reason: "LightGBM GPU training hangs with concurrent access"
  rate_limits:
    numerai_api: 60          # calls per minute
  budgets:
    max_session_cost_usd: 20.0
    max_cycle_cost_usd: 50.0
  data_locations:
    training_data: "numerai/v5.2/"
    experiment_results: "numerai/agents/experiments/"
    production_models: "/media/pawel/data/numerai_data/project2501/"

# ============================================================
# INTEGRATION POINTS
# ============================================================
integrations:
  mcp_servers:
    - name: numerai
      description: "Numerai Tournament API"
      auth_env: NUMERAI_MCP_AUTH
      required: false

  existing_cli:
    - command: "PYTHONPATH=numerai python3 -m agents.code.modeling"
      alias: "train_model"
      description: "Train a model from config file"
    - command: "PYTHONPATH=numerai python3 -m production.cli"
      alias: "production"
      description: "Production pipeline (train, validate, package)"

  documentation_sources:
    - path: "CLAUDE.md"
      type: "conventions"
      auto_refresh: true
    - path: "numerai/agents/experiments/high_sharpe_mmc/DEVLOG.md"
      type: "failure_memory"
      auto_refresh: true
    - path: "numerai/agents/experiments/high_sharpe_mmc/experiments_plan.md"
      type: "current_state"
      auto_refresh: true

# ============================================================
# OPERATING RULES (from documentation discovery)
# ============================================================
operating_rules:
  - id: no_custom_scoring
    severity: critical
    rule: "NEVER write custom scoring functions. Use production.validation.metrics."
    source: "CLAUDE.md"
  - id: use_production_oof
    severity: critical
    rule: "Ensemble analysis MUST use production OOF files from train_models/oof_predictions/"
    source: "CLAUDE.md"
  - id: no_lookahead
    severity: critical
    rule: "assert_no_lookahead() must be called in every trainer before .fit()"
    source: "CLAUDE.md"
  - id: sequential_gpu
    severity: high
    rule: "Training runs must be sequential, never parallel (GPU exclusivity)"
    source: "CLAUDE.md"
  - id: mandatory_caching
    severity: high
    rule: "Per-fold predictions must be saved immediately after each fold"
    source: "CLAUDE.md"
  - id: mandatory_progress
    severity: medium
    rule: "Every long-running script must use tqdm for progress reporting"
    source: "CLAUDE.md"
```

### 5.2 Schema Versioning

The `project.yaml` carries a `version` field. When the schema evolves (new sections, renamed fields), the onboarding system handles migration:

```python
CURRENT_SCHEMA_VERSION = "1.0"

def migrate_config(config: dict) -> dict:
    """Migrate project.yaml from older versions to current."""
    version = config.get('project', {}).get('version', '0.1')

    if version == '0.1':
        # v0.1 -> v1.0: moved 'tables' to 'domain_tables', added 'resources'
        config['domain_tables'] = config.pop('tables', [])
        config.setdefault('resources', {})
        config['project']['version'] = '1.0'

    return config
```

---

## 6. Database Initialization

### 6.1 Core Tables (Always Created)

Every Agent OS project gets the same core tables from Research 01:

```sql
-- Core Agent OS tables (project-independent)
-- These are created by `aos init` regardless of project type.

-- Projects (meta-table for multi-project support)
CREATE TABLE projects (...);

-- Goal hierarchy
CREATE TABLE goals (...);

-- Task management (leaf-level executable units)
CREATE TABLE tasks (...);
CREATE TABLE task_dependencies (...);

-- Agent registry
CREATE TABLE agents (...);

-- Session tracking
CREATE TABLE agent_sessions (...);

-- Artifact registry
CREATE TABLE artifacts (...);

-- Plan templates
CREATE TABLE plan_templates (...);

-- Operational logging
CREATE TABLE activity_log (...);

-- Security audit trail (hash-chained)
CREATE TABLE audit_trail (...);

-- Failure memory
CREATE TABLE failure_log (...);

-- Dead letter queue
CREATE TABLE dead_letter_tasks (...);

-- Confidence calibration
CREATE TABLE confidence_calibration (...);

-- Fund state (key-value for simple state tracking)
CREATE TABLE project_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 6.2 Domain Tables (Project-Specific)

Domain tables are declared in `project.yaml` under `domain_tables` and created during initialization. They hold project-specific state that agents need but that does not fit the generic Agent OS schema.

**Creation process:**

```python
def create_domain_tables(db: sqlite3.Connection, config: dict):
    """Create project-specific domain tables from config."""
    for table_def in config.get('domain_tables', []):
        # Validate the schema SQL (prevent injection, check syntax)
        schema_sql = table_def['schema']
        validate_create_table_sql(schema_sql)

        # Create the table
        db.executescript(schema_sql)

        # Log the creation
        db.execute(
            "INSERT INTO activity_log (agent_id, action, category, description, severity) "
            "VALUES ('system', 'table_created', 'system', ?, 'info')",
            (f"Domain table '{table_def['name']}' created: {table_def['description']}",)
        )

    db.commit()
```

**Why domain tables, not a generic key-value store?** Because agents need structured, queryable state. A key-value store works for simple flags (`current_cycle = 18`) but fails for complex queries (`SELECT * FROM experiments WHERE status = 'completed' AND bmc_sharpe > 1.0 ORDER BY bmc_mean DESC`). Domain tables with CHECK constraints, indexes, and foreign keys provide the structure that agents and acceptance criteria need.

### 6.3 Migration System for Schema Evolution

Projects evolve. Tables need new columns, new tables get added, constraints change. The migration system handles this without data loss.

**Migration file format:**

```
.agent-os/
  db/
    project.db
    migrations/
      001_initial.sql           # Created by `aos init`
      002_add_experiment_tags.sql
      003_add_model_ensemble.sql
```

**Migration tracking table:**

```sql
CREATE TABLE IF NOT EXISTS _migrations (
    migration_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    checksum TEXT NOT NULL         -- SHA-256 of migration file content
);
```

**Migration runner:**

```python
def run_migrations(db_path: Path, migrations_dir: Path):
    """Apply pending migrations in order."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    # Ensure migration tracking table exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            migration_id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            checksum TEXT NOT NULL
        )
    """)

    # Get applied migrations
    applied = {
        row[0]
        for row in conn.execute("SELECT migration_id FROM _migrations")
    }

    # Get pending migrations (sorted by filename)
    pending = sorted(
        f for f in migrations_dir.glob('*.sql')
        if f.stem not in applied
    )

    for migration_file in pending:
        sql = migration_file.read_text()
        checksum = hashlib.sha256(sql.encode()).hexdigest()

        try:
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO _migrations (migration_id, filename, checksum) VALUES (?, ?, ?)",
                (migration_file.stem, migration_file.name, checksum)
            )
            conn.commit()
            print(f"  Applied migration: {migration_file.name}")
        except Exception as e:
            conn.rollback()
            raise MigrationError(f"Migration {migration_file.name} failed: {e}")

    conn.close()
```

### 6.4 Data Import During Onboarding

For brownfield projects, the initialization phase also populates certain tables with discovered data:

1. **`agents` table** -- Populated from `project.yaml` agent definitions
2. **`plan_templates` table** -- Populated from `project.yaml` plan templates
3. **`failure_log` table** -- Populated from DEVLOG/postmortem discoveries
4. **`project_state` table** -- Populated with initial state (cycle=0, phase=init)
5. **`activity_log` table** -- Initial entry recording the onboarding event

```python
def import_discovered_data(db: sqlite3.Connection, config: dict, knowledge: dict):
    """Populate Agent OS tables with discovered project data."""

    # Import agent definitions
    for agent_def in config.get('agents', []):
        db.execute(
            """INSERT INTO agents (agent_id, project_id, name, role, provider, model,
                capabilities, config)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"agent_{agent_def['role']}",
                config['project']['name'],
                agent_def['name'],
                agent_def['role'],
                agent_def.get('provider', 'claude'),
                agent_def.get('model', 'opus'),
                json.dumps(agent_def.get('capabilities', [])),
                json.dumps({'imported_from': agent_def.get('imported_from', '')})
            )
        )

    # Import failure memory
    for failure in knowledge.get('failure_memory', []):
        db.execute(
            """INSERT INTO failure_log
                (failure_id, category, what_failed, failure_type, context,
                 root_cause, prevention_hint, severity)
            VALUES (?, 'imported', ?, 'historical', ?, ?, ?, 'warning')""",
            (
                failure['id'],
                failure['what'],
                json.dumps({'source': 'onboarding_discovery'}),
                failure.get('impact', ''),
                failure.get('prevention', '')
            )
        )

    # Import plan templates
    for template in config.get('plan_templates', []):
        db.execute(
            """INSERT INTO plan_templates
                (template_id, name, description, domain, template_spec)
            VALUES (?, ?, ?, ?, ?)""",
            (
                template['template_id'],
                template['name'],
                template['description'],
                template.get('domain'),
                json.dumps(template['template_spec'])
            )
        )

    db.commit()
```

---

## 7. Concrete Example: Onboarding the Numerai Project

This section walks through the full brownfield onboarding of the Numerai AI Experiments repository at `/Users/bigcube/Desktop/repos/numerai-ai-experiments/`.

### 7.1 Step 1: Detection

```bash
$ aos init /Users/bigcube/Desktop/repos/numerai-ai-experiments/
[*] Scanning project directory...
[*] Found 85+ source files, README.md, CLAUDE.md, AGENTS.md
[*] Mode: BROWNFIELD (existing codebase detected)
```

### 7.2 Step 2: Filesystem Scan

The scanner produces:

```
Total files: 95 (excluding .git)
Primary types: .py (52), .md (18), .yaml (12), .ipynb (5), .pkl (4)
Top-level dirs: numerai/, signals/, crypto/, cached-pickles/
Notable files:
  - CLAUDE.md (has_claude_config) -- RICH, 230 lines of conventions
  - AGENTS.md (has_agent_config) -- Tournament guide and skills
  - .claude/agents/ (has_claude_agents) -- 4 custom agent definitions
  - .github/workflows/build-models.yml (has_github_actions)
  - numerai/production/ -- Production pipeline code
  - numerai/agents/ -- Agent framework with skills, experiments, baselines
```

### 7.3 Step 3: Tech Stack Detection

```
Primary language: Python 3.12 (inferred from conda env)
Package manager: conda (lightgbm environment)
ML frameworks: LightGBM, XGBoost, CatBoost, scikit-learn, Ridge
Data tools: pandas, numpy, parquet
Plotting: matplotlib
External APIs: Numerai (via MCP server)
Dev tools: ruff (inferred from lint commands in CLAUDE.md)
Runtime constraints:
  - GPU exclusivity (sequential training only)
  - Conda environment requirement (lightgbm)
  - PYTHONPATH=numerai required for imports
```

### 7.4 Step 4: Workflow Discovery

The system discovers 4 existing Claude Code agents, 4 skills, a GitHub Actions pipeline, 4 CLI entry points, and an MCP server integration. (Full output shown in Section 3.4 above.)

Key insight: **This project already has a partially-built agent system.** The `.claude/agents/` definitions describe a 4-agent team (researcher, script-builder, runner, docs-updater) that maps closely to the Agent OS agent model. Onboarding should import these definitions, not replace them.

### 7.5 Step 5: Documentation Ingestion

CLAUDE.md is 230 lines of dense conventions -- a goldmine for onboarding. The system extracts:
- 6 operating rules (no custom scoring, use production OOF, no lookahead, sequential GPU, mandatory caching, mandatory progress)
- 3 failure memories from devlogs (CatBoost CV lookahead, CDST LOO lookahead, prediction source divergence)
- 9 anti-patterns (what does not work)
- 8 success patterns (what works)
- Complete experiment documentation structure (4 files: plan, notebook, ideas, devlog)

### 7.6 Step 6: Proposed Agent Roles

| Role | Name | Source | Model |
|------|------|--------|-------|
| `allocator` | Project Manager | Default (required) | opus |
| `researcher` | ML Researcher | Imported from `.claude/agents/numerai-researcher.md` | opus |
| `experiment_designer` | Script Builder | Imported from `.claude/agents/numerai-script-builder.md` | opus |
| `executor` | Experiment Runner | Imported from `.claude/agents/numerai-experiment-runner.md` | haiku |
| `docs_updater` | Documentation Updater | Imported from `.claude/agents/numerai-docs-updater.md` | sonnet |

No new roles are proposed because the existing agent definitions already cover the project's needs comprehensively. The system adds only the `allocator` role, which is required for Agent OS coordination.

### 7.7 Step 7: Proposed Initial Goals

```
Strategic: "Achieve top-100 Numerai tournament ranking with high Sharpe + high MMC"
  |-- Tactical: "Continue high_sharpe_mmc experiment series"
  |     |-- Operational: "Review experiments_plan.md for next priorities"
  |     +-- Operational: "Execute highest-priority P0 experiment from research_ideas.md"
  +-- Tactical: "Maintain and improve production model pipeline"
        |-- Operational: "Validate current production ensemble performance"
        +-- Operational: "Identify candidate models for production rotation"
```

### 7.8 Step 8: Human Review

The system generates `project_understanding.md` and `project.yaml` (draft), then presents them:

```
[*] Project understanding document written to:
    .agent-os/project_understanding.md

[*] Draft project configuration written to:
    .agent-os/config/project.yaml

[!] HUMAN REVIEW REQUIRED
    Please review both files and approve/modify before the Agent OS
    begins operating. Key items requiring your input:

    1. Is the strategic goal correct?
    2. Are the imported agent roles correct?
    3. Are the operating rules complete? (6 discovered, may be more)
    4. GPU exclusivity constraint — is this still accurate?
    5. Production data location (/media/pawel/data/...) — confirm or update

    Run `aos approve` when ready, or `aos edit-config` to modify.
```

### 7.9 Step 9: Database Initialization

After human approval:

```bash
$ aos approve
[*] Creating Agent OS database at .agent-os/db/project.db
[*] Applied migration: 001_initial.sql (core tables)
[*] Creating domain tables...
    - experiments (experiment tracking)
    - models (model registry)
    - research_ideas (research backlog)
[*] Importing agent definitions (5 agents)
[*] Importing failure memory (3 entries from DEVLOG)
[*] Importing plan templates (2 templates)
[*] Setting initial project state:
    - cycle = 0
    - phase = initialized
    - status = active
[*] Agent OS ready. Run `aos start` to begin first cycle.
```

---

## 8. Concrete Example: Onboarding a New Empty SaaS Project

### 8.1 Invocation

```bash
$ mkdir ~/projects/my-saas && cd ~/projects/my-saas
$ aos init .
[*] Scanning project directory...
[*] Empty directory detected.
[*] Mode: GREENFIELD (new project)
```

### 8.2 Interactive Elicitation

```
Agent OS: What kind of project is this?
  [1] Software application
  [2] ML/AI research
  [3] Data pipeline
  [4] Trading system
  [5] Other
> 1

Agent OS: What is the primary outcome you want to achieve?
> Build a task management SaaS app with team collaboration features

Agent OS: What is your rough timeline?
  [1] Days
  [2] Weeks
  [3] Months
  [4] Ongoing/indefinite
> 3

Agent OS: Do you have preferences for languages/frameworks?
> Python backend with FastAPI, React frontend with TypeScript

Agent OS: How many AI agents should work on this simultaneously?
  [1] 1-2 (solo/pair)
  [2] 3-5 (small team)  [recommended]
  [3] 6-10 (large team)
> 2

Agent OS: How much autonomy should agents have?
  [1] Conservative (agents propose, human approves everything)
  [2] Balanced (routine tasks autonomous, novel ones escalated)  [recommended]
  [3] Aggressive (agents execute freely, human reviews periodically)
> 2

Agent OS: Any constraints I should know about?
> No GPU needed. Using PostgreSQL for the database. Deploy to Railway.
```

### 8.3 Generated Configuration

The system generates `project.yaml`:

```yaml
project:
  name: "Task Management SaaS"
  description: "Team collaboration task management app with FastAPI + React"
  domain: "software"
  version: "1.0"

tech_stack:
  primary_language: "python"
  language_version: "3.12"
  secondary_language: "typescript"
  package_manager: "uv"
  frameworks:
    backend: "fastapi"
    frontend: "react"
    database: "postgresql"
  deployment: "railway"

agents:
  - role: allocator
    name: "Project Lead"
    model: opus
    description: "Decomposes goals, reviews PRs, coordinates sprints"
  - role: backend_dev
    name: "Backend Developer"
    model: opus
    description: "Implements FastAPI endpoints, database models, business logic"
    capabilities: ["python", "fastapi", "postgresql", "api_design"]
  - role: frontend_dev
    name: "Frontend Developer"
    model: sonnet
    description: "Implements React components, pages, and client-side logic"
    capabilities: ["typescript", "react", "css", "ui_design"]
  - role: tester
    name: "QA Engineer"
    model: sonnet
    description: "Writes unit tests, integration tests, E2E tests"
    capabilities: ["pytest", "jest", "testing"]
  - role: devops
    name: "DevOps Engineer"
    model: sonnet
    description: "CI/CD, Docker, deployment to Railway"
    capabilities: ["docker", "ci_cd", "railway", "monitoring"]

plan_templates:
  - template_id: feature_development
    name: "Feature Development"
    description: "Design -> Implement Backend -> Implement Frontend -> Test -> Deploy"
    domain: "software"
    template_spec:
      root:
        type: tactical
        title_pattern: "Build {feature_name} feature"
      children:
        - ref: design
          type: operational
          title_pattern: "Design API spec for {feature_name}"
          role: backend_dev
          acceptance_criteria:
            - {type: file_exists, path: "docs/api/{feature_slug}.md"}
        - ref: backend
          type: operational
          title_pattern: "Implement {feature_name} backend"
          role: backend_dev
          depends_on: [design]
          acceptance_criteria:
            - {type: test_passes, command: "uv run pytest tests/api/test_{feature_slug}.py"}
            - {type: lint_clean, command: "uv run ruff check src/api/"}
        - ref: frontend
          type: operational
          title_pattern: "Implement {feature_name} UI"
          role: frontend_dev
          depends_on: [design]
          acceptance_criteria:
            - {type: test_passes, command: "npm test -- --testPathPattern={feature_slug}"}
        - ref: integrate
          type: operational
          title_pattern: "Integration test {feature_name}"
          role: tester
          depends_on: [backend, frontend]
          acceptance_criteria:
            - {type: test_passes, command: "uv run pytest tests/integration/test_{feature_slug}.py"}
        - ref: deploy
          type: operational
          title_pattern: "Deploy {feature_name} to staging"
          role: devops
          depends_on: [integrate]

acceptance_defaults:
  code_quality:
    - {type: lint_clean, command: "uv run ruff check {file_path}"}
    - {type: test_passes, command: "uv run pytest {test_path}"}
  frontend:
    - {type: test_passes, command: "npm test -- --testPathPattern={component}"}
```

### 8.4 Generated Directory Structure

```
my-saas/
  .agent-os/
    db/project.db
    config/project.yaml
    artifacts/
      research/
      designs/
      reports/
    db/migrations/
      001_initial.sql
    logs/
  src/
    api/                # FastAPI backend
      __init__.py
    models/             # Database models
      __init__.py
    services/           # Business logic
      __init__.py
  frontend/
    src/
      components/
      pages/
  tests/
    api/
    integration/
  docs/
    api/
  scripts/
  pyproject.toml        # Generated with FastAPI, SQLAlchemy, pytest deps
  CLAUDE.md             # Generated with project conventions
  .gitignore
```

### 8.5 Generated Initial Goal Tree

```
Strategic: "Launch task management SaaS with team collaboration"
  |-- Tactical: "Set up project infrastructure"
  |     |-- Operational: "Initialize FastAPI project with auth boilerplate"
  |     |-- Operational: "Initialize React project with routing"
  |     |-- Operational: "Set up PostgreSQL schema and migrations"
  |     +-- Operational: "Configure CI/CD pipeline for Railway"
  +-- Tactical: "Build core task management features"
        |-- Operational: "Design data model for tasks, projects, and users"
        +-- Operational: "Implement task CRUD API"
```

### 8.6 Confirmation

```
[*] Project scaffolded successfully.
[*] Database initialized with core + 0 domain tables.
[*] 5 agent roles configured.
[*] 1 plan template registered.
[*] Initial goal tree created (2 tactical, 6 operational goals).

[*] Review the generated files:
    - .agent-os/config/project.yaml
    - CLAUDE.md
    - pyproject.toml

    Run `aos approve` when ready.
```

---

## 9. Integration with Existing Agent OS Components

### 9.1 Goal System Integration (Ref: 04)

Onboarding is the entry point to the goal system. The initial goal tree created during onboarding becomes the root of all subsequent goal decomposition.

**Connection points:**
- `project.yaml` plan templates are registered in the `plan_templates` table, making them available to the allocator for lazy decomposition
- Acceptance criteria defaults from `project.yaml` are inherited by new goals unless overridden
- Stop conditions from `project.yaml` (`resources.budgets`) become defaults for new goals
- The allocator reads `project.yaml` agent definitions to know which roles are available for task assignment

### 9.2 Runtime Layer Integration (Ref: 03)

Agent definitions in `project.yaml` include `provider` and `model` fields that the runtime dispatcher uses for routing.

**Connection points:**
- Each agent in `project.yaml` maps to a row in the `agents` table
- The `imported_from` field on agent definitions tells the runtime where to find the full prompt (e.g., `.claude/agents/numerai-researcher.md`)
- Resource constraints (`resources.gpu.exclusive`) are enforced by the session supervisor -- if GPU exclusivity is declared, the supervisor will not start two GPU-tagged sessions concurrently
- Rate limits (`resources.rate_limits`) are passed to provider adapters for enforcement

### 9.3 Dashboard Integration (Ref: 05)

The dashboard reads from the same SQLite database that onboarding creates.

**Connection points:**
- The project name and description from `project.yaml` appear in the dashboard header
- Domain tables declared in `project.yaml` can be surfaced as domain-specific dashboard panels (e.g., an "Experiments" panel for ML research projects, a "Strategies" panel for trading projects)
- Operating rules from `project.yaml` can be displayed in a "Project Rules" panel for human reference
- The project understanding document (`project_understanding.md`) is browsable in the artifact browser

### 9.4 Security Integration (Ref: 06)

Agent role definitions in `project.yaml` feed into the permission model.

**Connection points:**
- Each agent role's `capabilities` array defines what the agent is allowed to do
- Operating rules with `severity: critical` become hard guardrails that trigger escalation if violated
- Resource budgets (`max_session_cost_usd`, `max_cycle_cost_usd`) are enforced by the cost tracking system
- Domain table access is scoped by role -- a `researcher` can write to `research_ideas` but not to `models`

### 9.5 Failure Memory Integration (Ref: 08)

Documentation ingestion during brownfield onboarding directly populates the `failure_log` table.

**Connection points:**
- Devlog entries are parsed into structured failure records with `category`, `what_failed`, `root_cause`, and `prevention_hint`
- These records are queryable by agents before starting work ("What has failed before in this domain?")
- Anti-patterns from CLAUDE.md are stored as failure records with `failure_type = 'anti_pattern'`
- Success patterns are stored in a complementary `success_patterns` table (or as `failure_type = 'success_pattern'` in the same table for simplicity)

---

## 10. Open Questions

### 10.1 Must Answer Before Building

| # | Question | Recommendation |
|---|----------|---------------|
| 1 | **How deep should automatic introspection go?** Should the system read and analyze individual source files, or only top-level metadata (package files, config, docs)? | Start with metadata + docs only. Source file analysis is expensive (tokens) and error-prone (LLM misinterprets code). Add targeted source analysis in v2 for specific patterns (test coverage, API endpoint discovery). |
| 2 | **Should onboarding modify existing files?** E.g., should it add Agent OS entries to `.gitignore`, or create a CLAUDE.md if none exists? | Never modify existing files without explicit permission. Instead, output a list of "recommended changes" the human can apply. Exception: creating `.agent-os/` directory is always safe since it is new. |
| 3 | **How to handle projects with existing databases?** If the project already has a SQLite database (like the HFT fund's `fund.db`), should the Agent OS use the same database or create a separate one? | Separate database (`.agent-os/db/project.db`). The Agent OS database contains coordination state; the project database contains domain state. Domain tables in `project.yaml` can reference the external database via ATTACH for read queries, but the Agent OS should not write to an existing database it did not create. |
| 4 | **What is the minimum `project.yaml` for a useful Agent OS?** If a user just wants basic task tracking with one agent, how small can the config be? | Minimal config: `project.name` + `project.domain` + one agent definition (allocator). Everything else has defaults. The system should work with a 5-line config. |
| 5 | **How to handle multi-language monorepos?** A project might have Python backend, TypeScript frontend, and Rust microservices. | Support multiple `tech_stack` entries. Agent roles should be language-aware (backend_dev knows Python+FastAPI, frontend_dev knows TypeScript+React). The discovery system should detect all languages and frameworks, not just the primary one. |

### 10.2 Can Defer

| # | Question | Notes |
|---|----------|-------|
| 6 | **Project-to-project migration.** Can you "export" an Agent OS project and re-import it on another machine? | Useful for team handoffs. Database + config + artifacts = portable project. Defer to v2. |
| 7 | **Incremental re-onboarding.** If the project changes significantly (new framework added, new team members), can you re-run discovery without losing existing goals and history? | Important for long-lived projects. The `aos refresh` command should re-run discovery phases and produce a diff against current config. Defer to v2. |
| 8 | **Multi-project dashboard.** How do multiple projects appear in a single dashboard instance? | Research 05 mentions this as a v3 feature. Each project has its own database; the dashboard meta-view reads from all of them. |
| 9 | **Template marketplace.** Can plan templates be shared across projects and teams? | Would be valuable (e.g., a "SaaS Feature Development" template usable by any SaaS project). Requires a template registry service. Defer to v3. |
| 10 | **Discovery plugin system.** Can third parties add custom discovery analyzers? | E.g., a Terraform analyzer for infrastructure projects, a Kubernetes analyzer for container orchestration. Plugin architecture for Phase 2+ analyzers. Defer to v2. |
| 11 | **Onboarding for non-code projects.** Can the Agent OS onboard a writing project, a research paper, or an investment portfolio? | The core model (goals, tasks, agents, artifacts) is domain-agnostic. The discovery pipeline is code-centric. Extending to non-code projects requires new analyzers and different agent role inference. Defer to v3. |
| 12 | **Conflict resolution when existing agent definitions contradict project.yaml.** If `.claude/agents/numerai-researcher.md` says `model: sonnet` but `project.yaml` says `model: opus`, which wins? | `project.yaml` is the source of truth for the Agent OS. Agent prompt files define behavior; `project.yaml` defines operational parameters. Document this clearly. |

### 10.3 Risks

1. **Over-introspection cost.** If the discovery pipeline reads too many files and sends them to an LLM for analysis, onboarding a large project could cost $5-20 in API calls. Mitigation: limit LLM-assisted analysis to docs and config files; use deterministic pattern matching for everything else. Budget target: onboarding should cost < $2 for a project with 10K files.

2. **Misunderstood project.** The system builds a wrong model of the project (e.g., mistakes a test helper for a production module, or misidentifies the primary language). Mitigation: the mandatory human review step catches this. The system must never begin operating without human approval of the project understanding.

3. **Agent role mismatch.** Inferred roles do not match what the project actually needs. A project might look like ML research but actually be a data engineering project. Mitigation: role inference is a proposal, not a decision. The human reviews and modifies before approval.

4. **Stale documentation.** CLAUDE.md or DEVLOG may be outdated, leading to incorrect operating rules or failure memories. Mitigation: tag imported knowledge with its source file's last-modified timestamp. Flag entries from files older than 30 days for human review.

5. **Schema migration failures.** A domain table migration could fail if it conflicts with existing data, leaving the database in an inconsistent state. Mitigation: all migrations run inside transactions. Failed migrations roll back completely. The `_migrations` table tracks what has been applied.

---

*This document fills the critical gap between "we have an Agent OS design" and "we can actually use it on a real project." The onboarding system is the front door -- if it is confusing, destructive, or wrong, users will never reach the sophisticated coordination, planning, and resilience systems described in Research 01-08. Build it first, build it carefully, and require human approval at every trust-critical step.*
