const app = document.querySelector("#app");

const state = {
  theme: "dark",
  view: "board",
  mode: "ops",
  selectedTaskId: "task-validate-hft",
  selectedIncidentId: "incident-import-gate",
  selectedAgentId: "agent-researcher",
  selectedProjectId: "proj-hft",
  boardFilter: "active",
};

const data = {
  project: {
    id: "proj-hft",
    name: "HFT",
    description: "High Frequency Trading overlay",
    sourceRoot: "/Users/bigcube/Desktop/repos/hft",
    health: "Needs review",
    queuedJobs: 2,
    activeRuns: 1,
    blocked: 1,
    waitingReview: 2,
  },
  agents: [
    {
      id: "agent-allocator",
      name: "Allocator",
      role: "orchestration",
      status: "watch",
      current: "Holding queue fairness steady",
      detail: "2 launch-ready tasks are assigned and waiting on runtime capacity.",
    },
    {
      id: "agent-researcher",
      name: "Researcher",
      role: "analysis",
      status: "running",
      current: "Validate imported workflow: hft",
      detail: "Simulation run finished; waiting on operator review.",
    },
    {
      id: "agent-builder",
      name: "Builder",
      role: "execution",
      status: "idle",
      current: "Align runtime and provider settings",
      detail: "Idle, assigned, and launch-ready for the next work loop.",
    },
    {
      id: "agent-reviewer",
      name: "Reviewer",
      role: "approval",
      status: "ready",
      current: "Imported understanding approved",
      detail: "Watching 2 review tasks and 1 incident requiring judgment.",
    },
  ],
  tasks: [
    {
      id: "task-validate-hft",
      title: "Validate imported workflow: hft",
      status: "review",
      priority: "Critical",
      goal: "Adopt MAAS as an overlay for the repository",
      summary: "Confirm that the imported python script entrypoint and validation recipe match the repo reality.",
      assignee: "Researcher",
      evidence: "Simulation run completed with artifact evidence and no runtime failure.",
      nextAction: "Operator should review the evidence and either approve or request changes.",
      repoScope: ["pyproject.toml", "hft.py"],
      verification: "python_script:hft",
      incidentIds: ["incident-import-gate"],
      tags: ["review", "workflow", "verification"],
    },
    {
      id: "task-map-workspace",
      title: "Map imported repo area: workspace",
      status: "assigned",
      priority: "High",
      goal: "Build repo-grounded context for downstream execution",
      summary: "Inspect the workspace area, summarize ownership, and surface likely test and config boundaries.",
      assignee: "Allocator",
      evidence: "No launch yet.",
      nextAction: "The work loop should launch this automatically on the next run.",
      repoScope: ["workspace/"],
      verification: "Summarize repository structure",
      incidentIds: [],
      tags: ["assigned", "repo-map"],
    },
    {
      id: "task-map-agent-comms",
      title: "Map imported repo area: agent_comms",
      status: "ready",
      priority: "High",
      goal: "Build repo-grounded context for downstream execution",
      summary: "Inspect the agent communication package and identify contracts, dependencies, and likely validation edges.",
      assignee: "Allocator",
      evidence: "No run yet.",
      nextAction: "Can be allocated or launched automatically.",
      repoScope: ["agent_comms/"],
      verification: "Summarize interfaces",
      incidentIds: [],
      tags: ["ready", "repo-map"],
    },
    {
      id: "task-import-docs",
      title: "Import discovered documentation and test conventions",
      status: "ready",
      priority: "Medium",
      goal: "Capture repo conventions before broader automation",
      summary: "Extract docs, tests, and quality gates into the shared project context.",
      assignee: "Researcher",
      evidence: "No run yet.",
      nextAction: "Can be launched by the work loop.",
      repoScope: ["README.md", "tests/"],
      verification: "Convention summary",
      incidentIds: [],
      tags: ["ready", "docs"],
    },
    {
      id: "task-align-runtime",
      title: "Align runtime and provider settings with existing tooling",
      status: "assigned",
      priority: "High",
      goal: "Make execution safe and predictable",
      summary: "Match the repo’s current runtime conventions before live provider runs expand.",
      assignee: "Builder",
      evidence: "Preflight is green in simulation, CLI still disabled.",
      nextAction: "Queued launch should verify settings and report back.",
      repoScope: ["pyproject.toml", "README.md"],
      verification: "Runtime config summary",
      incidentIds: ["incident-provider-choice"],
      tags: ["assigned", "runtime"],
    },
    {
      id: "task-plan-src",
      title: "Plan imported area: src",
      status: "planned",
      priority: "Medium",
      goal: "Generate the next set of repo-grounded tasks",
      summary: "Break the src tree into smaller ownership slices after the first repo map completes.",
      assignee: "Unassigned",
      evidence: "Waiting on upstream repo-area mapping.",
      nextAction: "Hidden by default until upstream tasks finish.",
      repoScope: ["src/"],
      verification: "Plan quality review",
      incidentIds: [],
      tags: ["planned"],
    },
    {
      id: "task-old-run",
      title: "Review imported project understanding",
      status: "done",
      priority: "Critical",
      goal: "Adopt MAAS as an overlay for the repository",
      summary: "Imported understanding was approved and released into normal scheduling.",
      assignee: "Reviewer",
      evidence: "Approved yesterday.",
      nextAction: "No action required.",
      repoScope: ["README.md", "pyproject.toml"],
      verification: "Approved",
      incidentIds: [],
      tags: ["done"],
    },
  ],
  incidents: [
    {
      id: "incident-import-gate",
      title: "Review task is waiting on operator approval",
      severity: "warn",
      summary: "The workflow validation run completed and is now in review.",
      cause: "This is the expected next step after the imported workflow run.",
      impact: "Downstream tasks stay slowed until the decision is made.",
      action: "Review evidence and approve or request changes from the Board inspector.",
      evidence: ["Simulation artifact", "Validation recipe trace", "Recent run timeline"],
    },
    {
      id: "incident-provider-choice",
      title: "Live provider mode is still simulation-only",
      severity: "default",
      summary: "Execution is safe, but only in simulation mode for now.",
      cause: "CLI mode has not been enabled and preflighted yet.",
      impact: "The system can demonstrate flow, but not real repo-changing work.",
      action: "Enable live runtime later from Execution advanced settings, not during onboarding.",
      evidence: ["Preflight passed in local_simulation", "No recent live failures"],
    },
  ],
  feed: [
    {
      id: "feed-1",
      title: "Researcher completed simulated workflow validation",
      summary: "Validate imported workflow: hft moved to review with artifact evidence.",
      time: "2m ago",
      tone: "good",
    },
    {
      id: "feed-2",
      title: "Import review gate was cleared",
      summary: "Brownfield onboarding moved from changes requested to approved.",
      time: "11m ago",
      tone: "default",
    },
    {
      id: "feed-3",
      title: "Builder assigned runtime-alignment task",
      summary: "Task is assigned and ready for the next automatic run.",
      time: "14m ago",
      tone: "default",
    },
    {
      id: "feed-4",
      title: "No dead-letter or circuit-breaker incidents",
      summary: "Recovery posture is stable for this project right now.",
      time: "18m ago",
      tone: "good",
    },
  ],
  providers: [
    {
      id: "claude_code",
      name: "Claude Code",
      mode: "local_simulation",
      readiness: "Ready",
      note: "Safe default execution path for assigned work.",
      queue: "2 queued jobs · 0 failed",
      latest: "Preflight passed 3m ago",
    },
    {
      id: "openai_codex",
      name: "OpenAI Codex",
      mode: "local_simulation",
      readiness: "Ready",
      note: "Alternative simulation runtime for side-by-side checks.",
      queue: "0 queued jobs · 0 failed",
      latest: "Preflight passed 4m ago",
    },
    {
      id: "python_script",
      name: "Python Script",
      mode: "local_simulation",
      readiness: "Reference only",
      note: "Used for repo-native validation recipes and local proof runs.",
      queue: "0 queued jobs · 0 failed",
      latest: "No explicit check required",
    },
  ],
  runTimeline: [
    {
      id: "run-1",
      title: "Validate imported workflow: hft",
      state: "Completed",
      provider: "Claude Code",
      detail: "Simulation run produced workflow evidence and routed task to review.",
    },
    {
      id: "run-2",
      title: "Map imported repo area: workspace",
      state: "Queued",
      provider: "Claude Code",
      detail: "Launch-ready and waiting for the next work loop.",
    },
    {
      id: "run-3",
      title: "Align runtime and provider settings",
      state: "Assigned",
      provider: "Claude Code",
      detail: "Ready for automatic launch after queue pressure clears.",
    },
  ],
  projects: [
    {
      id: "proj-hft",
      name: "HFT",
      type: "brownfield",
      status: "selected",
      summary: "Imported repo with live workflow validation and repo-grounded planning.",
      tasks: "11 visible tasks",
      health: "Needs review",
    },
    {
      id: "proj-payments",
      name: "Payments platform",
      type: "greenfield",
      status: "active",
      summary: "Planning-only workspace with no incidents.",
      tasks: "7 planned tasks",
      health: "Stable",
    },
    {
      id: "proj-risk",
      name: "Risk engine",
      type: "brownfield",
      status: "attention",
      summary: "Repeated failures on runtime configuration alignment.",
      tasks: "3 incidents",
      health: "At risk",
    },
  ],
  importFlow: [
    {
      title: "Import repo",
      detail: "Choose a local repo or Git source. MAAS scans structure, workflows, tests, and docs.",
    },
    {
      title: "Review understanding",
      detail: "Operator sees discovered areas, workflows, and the initial plan in one takeover flow.",
    },
    {
      title: "Run work loop",
      detail: "MAAS allocates, launches, verifies, and routes only exceptions back to the operator.",
    },
  ],
};

function setTheme(theme) {
  state.theme = theme;
  document.documentElement.dataset.theme = theme;
  render();
}

function selectTask(taskId) {
  state.selectedTaskId = taskId;
  render();
}

function selectIncident(incidentId) {
  state.selectedIncidentId = incidentId;
  render();
}

function selectView(view) {
  state.view = view;
  render();
}

function selectMode(mode) {
  state.mode = mode;
  render();
}

function statusTone(value) {
  const lowered = value.toLowerCase();
  if (["critical", "at risk", "needs review", "blocked"].includes(lowered)) return "critical";
  if (["warn", "watch", "review", "attention"].includes(lowered)) return "warn";
  return "good";
}

function selectedTask() {
  return data.tasks.find((task) => task.id === state.selectedTaskId) ?? data.tasks[0];
}

function selectedIncident() {
  return data.incidents.find((incident) => incident.id === state.selectedIncidentId) ?? data.incidents[0];
}

function laneConfig() {
  return [
    { key: "ready", title: "Ready", subtitle: "Unassigned or launchable next" },
    { key: "assigned", title: "Assigned", subtitle: "Has owner, awaiting automatic launch" },
    { key: "in_progress", title: "In Progress", subtitle: "Live execution" },
    { key: "review", title: "Review", subtitle: "Operator decision needed" },
    { key: "blocked", title: "Blocked", subtitle: "Needs intervention" },
  ];
}

function visibleTasksForLane(key) {
  const byAgent = state.selectedAgentId
    ? data.tasks.filter((task) => task.assignee.toLowerCase() === data.agents.find((a) => a.id === state.selectedAgentId)?.name.toLowerCase())
    : data.tasks;
  if (state.boardFilter === "critical") {
    return byAgent.filter((task) => task.status === key && task.priority === "Critical");
  }
  if (state.boardFilter === "attention") {
    return byAgent.filter((task) => task.status === key && ["review", "blocked"].includes(task.status));
  }
  return byAgent.filter((task) => task.status === key);
}

function hiddenColumns() {
  return ["planned", "done", "cancelled"]
    .map((status) => ({
      status,
      count: data.tasks.filter((task) => task.status === status).length,
      label: status.charAt(0).toUpperCase() + status.slice(1),
    }))
    .filter((item) => item.count > 0);
}

function renderTopbar() {
  return `
    <header class="topbar">
      <div class="brand-block">
        <div class="brand-mark"></div>
        <div class="brand-copy">
          <strong>MAAS</strong>
          <span>ideal operator mockup · board-first autonomous software delivery</span>
        </div>
      </div>
      <div class="project-strip">
        <div class="select-shell">
          <label>Project</label>
          <select>
            ${data.projects.map((project) => `<option ${project.id === state.selectedProjectId ? "selected" : ""}>${project.name}</option>`).join("")}
          </select>
        </div>
        <div class="project-health">
          <strong>${data.project.name}</strong>
          <span>${data.project.description}</span>
        </div>
      </div>
      <div class="topbar-actions">
        <div class="command-shell">
          <span>⌘K</span>
          <input value="Search task, agent, incident, file, or command" readonly />
        </div>
        <button class="action-button ${state.theme === "dark" ? "action-button--ghost" : ""}" data-theme-toggle>
          ${state.theme === "dark" ? "Light" : "Dark"}
        </button>
      </div>
    </header>
  `;
}

function renderSubnav() {
  const summaryChips = [
    { label: "Health", value: data.project.health, tone: statusTone(data.project.health) },
    { label: "Active runs", value: String(data.project.activeRuns), tone: "default" },
    { label: "Waiting review", value: String(data.project.waitingReview), tone: "warn" },
    { label: "Queued jobs", value: String(data.project.queuedJobs), tone: "default" },
    { label: "Blocked", value: String(data.project.blocked), tone: data.project.blocked ? "critical" : "good" },
  ];

  return `
    <nav class="subnav">
      <div class="nav-list">
        ${["board", "execution", "incidents", "projects"]
          .map(
            (view) => `
              <button class="nav-button ${state.view === view ? "is-active" : ""}" data-view="${view}">
                ${view}
              </button>
            `
          )
          .join("")}
      </div>
      <div class="chip-list">
        ${summaryChips
          .map(
            (chip) => `
              <span class="chip chip--${chip.tone}">
                ${chip.label}
                <strong>${chip.value}</strong>
              </span>
            `
          )
          .join("")}
      </div>
      <div class="mode-list">
        ${["ops", "focus", "review"]
          .map(
            (mode) => `
              <button class="mode-button ${state.mode === mode ? "is-active" : ""}" data-mode="${mode}">
                ${mode}
              </button>
            `
          )
          .join("")}
        <button class="action-button action-button--primary">Run work loop</button>
      </div>
    </nav>
  `;
}

function renderAgentsRail() {
  return `
    <section class="panel scroll-panel">
      <div class="panel-header">
        <div class="panel-copy">
          <span class="eyebrow">Agents</span>
          <h2 class="panel-title">Who is doing what</h2>
          <p class="panel-subtitle">The left rail is for people supervising capacity, assignment pressure, and who is stuck.</p>
        </div>
        <span class="status-pill">4 live roles</span>
      </div>
      <div class="agent-list">
        ${data.agents
          .map(
            (agent) => `
              <article class="agent-card ${state.selectedAgentId === agent.id ? "is-active" : ""}" data-agent="${agent.id}">
                <div class="agent-top">
                  <div>
                    <div class="agent-name">${agent.name}</div>
                    <div class="agent-role">${agent.role}</div>
                  </div>
                  <span class="status-pill status-pill--${statusTone(agent.status)}">${agent.status}</span>
                </div>
                <p>${agent.current}</p>
                <p class="agent-role">${agent.detail}</p>
                <div class="agent-actions">
                  <button class="rail-button rail-button--primary">Open work</button>
                  <button class="rail-button">History</button>
                </div>
              </article>
            `
          )
          .join("")}
      </div>
    </section>
  `;
}

function renderBoardCenter() {
  return `
    <section class="panel">
      <div class="panel-header">
        <div class="panel-copy">
          <span class="eyebrow">Board</span>
          <h2 class="panel-title">Current task flow</h2>
          <p class="panel-subtitle">Cards only summarize. All real steering, evidence, and decisions live in the inspector.</p>
        </div>
        <span class="status-pill">${data.tasks.filter((task) => ["ready", "assigned", "in_progress", "review", "blocked"].includes(task.status)).length} visible cards</span>
      </div>
      <div class="board-toolbar">
        <div class="board-filters">
          ${[
            ["active", "All work"],
            ["critical", "Critical only"],
            ["attention", "Needs attention"],
          ]
            .map(
              ([value, label]) => `
                <button class="filter-pill ${state.boardFilter === value ? "is-active" : ""}" data-filter="${value}">
                  ${label}
                </button>
              `
            )
            .join("")}
        </div>
        <div class="hidden-columns">
          ${hiddenColumns()
            .map((item) => `<span class="hidden-chip">${item.count} ${item.label}</span>`)
            .join("")}
        </div>
      </div>
      <div class="board-scroll">
        <div class="board-grid">
          ${laneConfig()
            .map((lane) => {
              const tasks = visibleTasksForLane(lane.key);
              return `
                <section class="lane">
                  <header class="lane-header">
                    <div class="lane-title-row">
                      <h3 class="lane-title">${lane.title}</h3>
                      <span class="lane-count">${tasks.length}</span>
                    </div>
                    <p class="lane-subtitle">${lane.subtitle}</p>
                  </header>
                  <div class="task-stack">
                    ${tasks.length ? tasks.map(renderTaskCard).join("") : `<div class="task-card"><div class="task-summary">Nothing in ${lane.title.toLowerCase()} right now.</div></div>`}
                  </div>
                </section>
              `;
            })
            .join("")}
        </div>
      </div>
    </section>
  `;
}

function renderTaskCard(task) {
  return `
    <article class="task-card ${state.selectedTaskId === task.id ? "is-selected" : ""}" data-task="${task.id}">
      <div class="task-top">
        <span class="status-pill status-pill--${statusTone(task.priority)}">${task.priority}</span>
        <span class="status-pill">${task.assignee}</span>
      </div>
      <div class="task-title">${task.title}</div>
      <p class="task-summary">${task.summary}</p>
      <div class="tag-row">
        ${task.tags.map((tag) => `<span class="tag">${tag}</span>`).join("")}
      </div>
    </article>
  `;
}

function renderInspector() {
  const task = selectedTask();
  const relatedIncidents = data.incidents.filter((incident) => task.incidentIds.includes(incident.id));
  return `
    <section class="inspector-stack">
      <section class="panel">
        <div class="panel-header">
          <div class="panel-copy">
            <span class="eyebrow">Inspector</span>
            <h2 class="panel-title">Selected task</h2>
            <p class="panel-subtitle">This is the only place where task steering and judgment live.</p>
          </div>
          <span class="status-pill status-pill--${statusTone(task.status === "review" ? "warn" : task.status === "blocked" ? "critical" : "good")}">${task.status}</span>
        </div>
        <div class="inspector-body">
          <div class="inspector-hero">
            <div class="breadcrumb">
              <span>${data.project.name}</span>
              <span>${task.goal}</span>
              <span>${task.title}</span>
            </div>
            <div class="inspector-heading">
              <div>
                <h3 class="inspector-title">${task.title}</h3>
                <p class="inspector-subtitle">${task.summary}</p>
              </div>
            </div>
          </div>
          <div class="recommendation-box">
            <strong>Recommended operator move</strong>
            <p>${task.nextAction}</p>
            <div class="inspector-actions">
              <button class="action-button action-button--primary">${task.status === "review" ? "Approve" : "Run automatically"}</button>
              <button class="action-button">${task.status === "review" ? "Request changes" : "Inspect evidence"}</button>
            </div>
          </div>
          <div class="meta-grid">
            <div class="meta-card">
              <span>Assignee</span>
              <strong>${task.assignee}</strong>
            </div>
            <div class="meta-card">
              <span>Verification</span>
              <strong>${task.verification}</strong>
            </div>
            <div class="meta-card">
              <span>Repo scope</span>
              <strong>${task.repoScope.join(", ")}</strong>
            </div>
            <div class="meta-card">
              <span>Evidence</span>
              <strong>${task.evidence}</strong>
            </div>
          </div>
          ${relatedIncidents.length ? `
            <div class="playbook-box">
              <strong>Linked incidents</strong>
              <p>${relatedIncidents.map((incident) => incident.title).join(" · ")}</p>
            </div>
          ` : ""}
        </div>
      </section>
      <section class="panel scroll-panel">
        <div class="panel-header">
          <div class="panel-copy">
            <span class="eyebrow">Live feed</span>
            <h2 class="panel-title">Meaningful system events</h2>
            <p class="panel-subtitle">Curated movement, not every heartbeat.</p>
          </div>
        </div>
        <div class="feed-list">
          ${data.feed
            .map(
              (item) => `
                <article class="feed-card">
                  <div class="feed-top">
                    <div class="run-name">${item.title}</div>
                    <span class="status-pill status-pill--${item.tone === "good" ? "good" : item.tone === "critical" ? "critical" : "warn"}">${item.time}</span>
                  </div>
                  <p>${item.summary}</p>
                </article>
              `
            )
            .join("")}
        </div>
      </section>
    </section>
  `;
}

function renderBoardView() {
  return `
    <div class="board-layout">
      <div class="rail">${renderAgentsRail()}</div>
      <div class="center-stack">${renderBoardCenter()}</div>
      <div class="inspector-stack">${renderInspector()}</div>
    </div>
  `;
}

function renderExecutionView() {
  return `
    <div class="execution-layout">
      <div class="section-stack">
        <section class="panel">
          <div class="panel-header">
            <div class="panel-copy">
              <span class="eyebrow">Execution</span>
              <h2 class="panel-title">Runtime posture</h2>
              <p class="panel-subtitle">The default system should auto-pick providers and launch assigned work. Manual buttons live here as advanced control, not on the board.</p>
            </div>
            <button class="action-button action-button--primary">Run work loop</button>
          </div>
          <div class="provider-grid">
            ${data.providers
              .map(
                (provider) => `
                  <article class="provider-card">
                    <div class="provider-top">
                      <div>
                        <div class="provider-name">${provider.name}</div>
                        <div class="provider-meta">${provider.mode}</div>
                      </div>
                      <span class="status-pill status-pill--${statusTone(provider.readiness)}">${provider.readiness}</span>
                    </div>
                    <p>${provider.note}</p>
                    <div class="inline-stats">
                      <span class="inline-stat">${provider.queue}</span>
                      <span class="inline-stat">${provider.latest}</span>
                    </div>
                    <div class="project-actions">
                      <button class="rail-button rail-button--primary">Auto-launch assigned work</button>
                      <button class="rail-button">Advanced runtime</button>
                    </div>
                  </article>
                `
              )
              .join("")}
          </div>
        </section>
        <section class="panel scroll-panel">
          <div class="panel-header">
            <div class="panel-copy">
              <span class="eyebrow">Recent runs</span>
              <h2 class="panel-title">Queue and session movement</h2>
              <p class="panel-subtitle">Runs should explain what moved, not just flash and disappear.</p>
            </div>
          </div>
          <div class="run-list">
            ${data.runTimeline
              .map(
                (run) => `
                  <article class="run-card">
                    <div class="run-top">
                      <div>
                        <div class="run-name">${run.title}</div>
                        <div class="run-meta">${run.provider}</div>
                      </div>
                      <span class="status-pill status-pill--${statusTone(run.state)}">${run.state}</span>
                    </div>
                    <p>${run.detail}</p>
                  </article>
                `
              )
              .join("")}
          </div>
        </section>
      </div>
      <div class="section-stack">
        <section class="panel">
          <div class="panel-header">
            <div class="panel-copy">
              <span class="eyebrow">Defaults</span>
              <h2 class="panel-title">How the ideal product behaves</h2>
            </div>
          </div>
          <div class="project-detail-body">
            <div class="execution-box">
              <strong>1. Run launches work</strong>
              <p>No manual per-task provider clicking in the normal flow.</p>
            </div>
            <div class="execution-box">
              <strong>2. Manual launch is advanced</strong>
              <p>Direct queue/run controls exist only for power users or debugging.</p>
            </div>
            <div class="execution-box">
              <strong>3. Every action leaves a trace</strong>
              <p>Completed, failed, queued, and waiting states stay visible in-place.</p>
            </div>
          </div>
        </section>
      </div>
    </div>
  `;
}

function renderIncidentsView() {
  const incident = selectedIncident();
  return `
    <div class="incidents-layout">
      <section class="panel scroll-panel">
        <div class="panel-header">
          <div class="panel-copy">
            <span class="eyebrow">Incidents</span>
            <h2 class="panel-title">Exceptions that need judgment</h2>
            <p class="panel-subtitle">Not alerts, failures, recovery, timeline as separate products. One queue, one playbook.</p>
          </div>
        </div>
        <div class="incident-list">
          ${data.incidents
            .map(
              (item) => `
                <article class="incident-card ${state.selectedIncidentId === item.id ? "is-selected" : ""}" data-incident="${item.id}">
                  <div class="incident-top">
                    <div>
                      <div class="incident-title">${item.title}</div>
                      <div class="incident-meta">${item.summary}</div>
                    </div>
                    <span class="status-pill status-pill--${statusTone(item.severity)}">${item.severity}</span>
                  </div>
                  <div class="incident-actions">
                    <button class="rail-button rail-button--primary">Open playbook</button>
                  </div>
                </article>
              `
            )
            .join("")}
        </div>
      </section>
      <section class="panel">
        <div class="panel-header">
          <div class="panel-copy">
            <span class="eyebrow">Playbook</span>
            <h2 class="panel-title">${incident.title}</h2>
            <p class="panel-subtitle">${incident.summary}</p>
          </div>
        </div>
        <div class="playbook-body">
          <div class="playbook-box">
            <strong>What happened</strong>
            <p>${incident.summary}</p>
          </div>
          <div class="playbook-box">
            <strong>Likely cause</strong>
            <p>${incident.cause}</p>
          </div>
          <div class="playbook-box">
            <strong>Impact</strong>
            <p>${incident.impact}</p>
          </div>
          <div class="playbook-box">
            <strong>Recommended next action</strong>
            <p>${incident.action}</p>
            <div class="project-actions">
              <button class="action-button action-button--primary">Take recommended action</button>
              <button class="action-button">Inspect evidence</button>
            </div>
          </div>
          <div class="playbook-box">
            <strong>Evidence</strong>
            <p>${incident.evidence.join(" · ")}</p>
          </div>
        </div>
      </section>
    </div>
  `;
}

function renderProjectsView() {
  return `
    <div class="projects-layout">
      <section class="panel">
        <div class="panel-header">
          <div class="panel-copy">
            <span class="eyebrow">Projects</span>
            <h2 class="panel-title">Portfolio and import flow</h2>
            <p class="panel-subtitle">Project setup should feel like a guided intake flow, not a policy admin wall.</p>
          </div>
          <button class="action-button action-button--primary">Import repo</button>
        </div>
        <div class="project-list">
          ${data.projects
            .map(
              (project) => `
                <article class="project-card ${project.id === state.selectedProjectId ? "is-selected" : ""}" data-project="${project.id}">
                  <div class="project-top">
                    <div>
                      <div class="project-name">${project.name}</div>
                      <div class="project-meta">${project.type} · ${project.tasks}</div>
                    </div>
                    <span class="status-pill status-pill--${statusTone(project.health)}">${project.health}</span>
                  </div>
                  <p>${project.summary}</p>
                  <div class="project-actions">
                    <button class="rail-button rail-button--primary">${project.id === state.selectedProjectId ? "Selected" : "Open"}</button>
                    <button class="rail-button">Review flow</button>
                  </div>
                </article>
              `
            )
            .join("")}
        </div>
      </section>
      <section class="section-stack">
        <section class="panel">
          <div class="panel-header">
            <div class="panel-copy">
              <span class="eyebrow">Import flow</span>
              <h2 class="panel-title">What first-run should feel like</h2>
            </div>
          </div>
          <div class="import-flow">
            ${data.importFlow
              .map(
                (step, index) => `
                  <div class="flow-step">
                    <span class="flow-index">${index + 1}</span>
                    <div class="flow-copy">
                      <strong>${step.title}</strong>
                      <p>${step.detail}</p>
                    </div>
                  </div>
                `
              )
              .join("")}
          </div>
        </section>
        <section class="panel">
          <div class="panel-header">
            <div class="panel-copy">
              <span class="eyebrow">Selected project</span>
              <h2 class="panel-title">${data.project.name}</h2>
              <p class="panel-subtitle">${data.project.description}</p>
            </div>
          </div>
          <div class="project-detail-body">
            <div class="project-box">
              <strong>Source root</strong>
              <p>${data.project.sourceRoot}</p>
            </div>
            <div class="project-box">
              <strong>Current project health</strong>
              <p>${data.project.health}. The next real operator step belongs on Board, not scattered across multiple tabs.</p>
            </div>
          </div>
        </section>
      </section>
    </div>
  `;
}

function renderView() {
  if (state.view === "execution") return renderExecutionView();
  if (state.view === "incidents") return renderIncidentsView();
  if (state.view === "projects") return renderProjectsView();
  return renderBoardView();
}

function render() {
  document.documentElement.dataset.theme = state.theme;
  app.innerHTML = `
    <main class="app-shell">
      ${renderTopbar()}
      ${renderSubnav()}
      <section class="workspace">
        <div class="view-frame">
          ${renderView()}
        </div>
      </section>
      <div class="footer-note">Mockup only. No backend calls, no real scheduling, no provider execution. This is the product shape we should be aiming for.</div>
    </main>
  `;

  app.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => selectView(button.dataset.view));
  });

  app.querySelectorAll("[data-mode]").forEach((button) => {
    button.addEventListener("click", () => selectMode(button.dataset.mode));
  });

  app.querySelectorAll("[data-task]").forEach((card) => {
    card.addEventListener("click", () => selectTask(card.dataset.task));
  });

  app.querySelectorAll("[data-incident]").forEach((card) => {
    card.addEventListener("click", () => selectIncident(card.dataset.incident));
  });

  app.querySelectorAll("[data-agent]").forEach((card) => {
    card.addEventListener("click", () => {
      state.selectedAgentId = state.selectedAgentId === card.dataset.agent ? null : card.dataset.agent;
      render();
    });
  });

  app.querySelectorAll("[data-project]").forEach((card) => {
    card.addEventListener("click", () => {
      state.selectedProjectId = card.dataset.project;
      render();
    });
  });

  app.querySelectorAll("[data-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.boardFilter = button.dataset.filter;
      render();
    });
  });

  const toggle = app.querySelector("[data-theme-toggle]");
  toggle?.addEventListener("click", () => setTheme(state.theme === "dark" ? "light" : "dark"));
}

render();
