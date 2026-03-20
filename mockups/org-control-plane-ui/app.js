const app = document.querySelector("#app");

const state = {
  theme: "dark",
  view: "command",
  selectedWorkstreamId: "ws-launch-quant-alpha",
  selectedAgentId: "agent-chief-of-staff",
  selectedIncidentId: "inc-approval-risk",
  selectedMemoryId: "mem-decision-risk-gate",
};

const data = {
  organization: {
    name: "Northstar Research Group",
    subtitle: "Autonomous research and operating organization",
    status: "Intervention needed",
    statusReason: "2 approval-blocked workstreams and 1 contained runtime incident",
    objective: "Launch a compliant quantitative research initiative with live paper trading, daily reporting, and controlled capital risk.",
    mode: "Supervised autonomy",
    activeTeams: 5,
    activeAgents: 12,
    activeRuns: 7,
    blockedWorkstreams: 2,
  },
  decisions: [
    {
      id: "dec-risk-policy",
      tone: "critical",
      title: "Approve risk guardrail for live paper-trading promotion",
      summary: "Research and execution teams are ready, but the policy gate requires operator approval before the organization can move from sandbox to paper-trading mode.",
      owner: "Risk Council",
      impact: "Blocks 2 workstreams",
      action: "Review guardrail",
    },
    {
      id: "dec-hire-runtime",
      tone: "warn",
      title: "Select preferred coding runtime for execution team",
      summary: "Both Claude Code and Codex are healthy. The execution team needs one default runtime with a fallback policy before broader automation resumes.",
      owner: "Platform Team",
      impact: "Affects 4 agents",
      action: "Choose runtime policy",
    },
    {
      id: "dec-memory-promo",
      tone: "blue",
      title: "Promote strategy memo to canonical operating guidance",
      summary: "The latest market-entry plan has supporting evidence and can be promoted into reusable organizational memory.",
      owner: "Chief of Staff",
      impact: "Improves downstream planning",
      action: "Promote memory",
    },
  ],
  workstreams: [
    {
      id: "ws-launch-quant-alpha",
      title: "Launch quant alpha research track",
      status: "review",
      priority: "Critical",
      owner: "Research Lead",
      team: "Research",
      progress: 78,
      summary: "Paper-trading rollout package is ready for risk approval.",
      nextAction: "Approve the risk guardrail or request changes to the promotion criteria.",
      evidence: "Backtests passed · sandbox runs stable · daily report pipeline green",
      health: "Awaiting decision",
      runtime: "Claude Code with Codex fallback",
      scope: ["strategy memo", "risk guardrail", "reporting runbook"],
      incidentId: "inc-approval-risk",
    },
    {
      id: "ws-client-intel",
      title: "Build client-intelligence operating loop",
      status: "in_progress",
      priority: "High",
      owner: "Growth Operator",
      team: "Growth",
      progress: 54,
      summary: "Research, enrichment, and outreach drafting are running on schedule.",
      nextAction: "No operator action needed unless evidence quality falls.",
      evidence: "3 lead briefs generated · 1 handoff pending to review",
      health: "On track",
      runtime: "Seraph research pods",
      scope: ["prospect briefs", "message drafts", "scorecards"],
      incidentId: null,
    },
    {
      id: "ws-runtime-migration",
      title: "Normalize runtime contract for engineering team",
      status: "blocked",
      priority: "High",
      owner: "Platform Lead",
      team: "Platform",
      progress: 41,
      summary: "Execution adapters exist, but the org-wide runtime contract still lacks interrupt and checkpoint parity.",
      nextAction: "Resolve the contained runtime incident before resuming the migration.",
      evidence: "Claude Code and Codex are green; Hermes adapter still missing stop semantics",
      health: "Blocked by runtime policy",
      runtime: "Mixed runtime fleet",
      scope: ["runtime contract", "checkpoint format", "interrupt semantics"],
      incidentId: "inc-runtime-drift",
    },
    {
      id: "ws-daily-ops-report",
      title: "Daily operator briefing",
      status: "ready",
      priority: "Medium",
      owner: "Chief of Staff",
      team: "Operations",
      progress: 0,
      summary: "Generate the next org-wide briefing from current memory, runs, and incidents.",
      nextAction: "Can launch automatically when the work loop resumes.",
      evidence: "No run started yet",
      health: "Ready",
      runtime: "Hermes summarizer",
      scope: ["daily briefing", "decision queue", "run highlights"],
      incidentId: null,
    },
    {
      id: "ws-governance-audit",
      title: "Quarterly governance and spend audit",
      status: "backlog",
      priority: "Medium",
      owner: "Risk Council",
      team: "Governance",
      progress: 0,
      summary: "Review budget, policy exceptions, and approvals across the organization.",
      nextAction: "Not urgent this cycle.",
      evidence: "Backlog item only",
      health: "Backlog",
      runtime: "N/A",
      scope: ["budgets", "approval trail", "policy overrides"],
      incidentId: null,
    },
  ],
  teams: [
    {
      name: "Research",
      mission: "Generate and validate alpha hypotheses.",
      capacity: "3 agents active",
      pressure: "1 waiting approval",
    },
    {
      name: "Execution",
      mission: "Convert approved plans into durable outputs.",
      capacity: "2 agents active",
      pressure: "Healthy",
    },
    {
      name: "Growth",
      mission: "Turn research into pipeline and operator leverage.",
      capacity: "2 agents active",
      pressure: "1 handoff pending",
    },
    {
      name: "Platform",
      mission: "Keep runtime, policy, and memory stable.",
      capacity: "3 agents active",
      pressure: "1 contained incident",
    },
  ],
  agents: [
    {
      id: "agent-chief-of-staff",
      name: "Chief of Staff",
      team: "Operations",
      role: "org operations",
      status: "needs_review",
      runtime: "Seraph",
      current: "Holding the daily operator briefing until the risk decision is made.",
      waitingOn: "Risk Council approval",
      lastAction: "Published the decision packet for operator review 4m ago.",
      risk: "Review queue pressure",
    },
    {
      id: "agent-research-lead",
      name: "Research Lead",
      team: "Research",
      role: "hypothesis and validation",
      status: "working",
      runtime: "Claude Code",
      current: "Finalizing the quant alpha package and evidence chain.",
      waitingOn: "Operator approval for promotion",
      lastAction: "Attached backtest evidence and guardrail proposal 7m ago.",
      risk: "Healthy",
    },
    {
      id: "agent-runtime-broker",
      name: "Runtime Broker",
      team: "Platform",
      role: "routing and execution policy",
      status: "blocked",
      runtime: "Codex",
      current: "Runtime parity rollout stalled on missing Hermes stop semantics.",
      waitingOn: "Runtime contract change",
      lastAction: "Raised contained incident and paused rollout 12m ago.",
      risk: "Provider drift",
    },
    {
      id: "agent-growth-ops",
      name: "Growth Operator",
      team: "Growth",
      role: "pipeline and messaging",
      status: "working",
      runtime: "OpenClaw",
      current: "Running the client-intelligence loop and preparing 3 briefs.",
      waitingOn: "Review handoff",
      lastAction: "Handed prospect brief to Review team 2m ago.",
      risk: "Healthy",
    },
    {
      id: "agent-risk-reviewer",
      name: "Risk Reviewer",
      team: "Governance",
      role: "policy approval",
      status: "needs_review",
      runtime: "Hermes",
      current: "Reviewing guardrail and approval criteria for paper-trading promotion.",
      waitingOn: "Operator decision",
      lastAction: "Prepared a diff of approved vs proposed risk posture 6m ago.",
      risk: "Operator bottleneck",
    },
    {
      id: "agent-memory-curator",
      name: "Memory Curator",
      team: "Platform",
      role: "canonical memory",
      status: "idle",
      runtime: "Seraph",
      current: "Ready to promote the latest strategy memo into canonical memory.",
      waitingOn: "Promotion approval",
      lastAction: "Flagged one stale decision record 19m ago.",
      risk: "Idle",
    },
  ],
  handoffs: [
    {
      from: "Growth Operator",
      to: "Review Team",
      item: "Prospect brief #28",
      age: "2m",
      state: "Awaiting review",
    },
    {
      from: "Research Lead",
      to: "Risk Reviewer",
      item: "Paper-trading guardrail packet",
      age: "7m",
      state: "Needs operator approval",
    },
    {
      from: "Runtime Broker",
      to: "Platform Lead",
      item: "Hermes stop-semantics gap",
      age: "12m",
      state: "Contained incident",
    },
  ],
  incidents: [
    {
      id: "inc-approval-risk",
      bucket: "Needs approval",
      severity: "critical",
      title: "Paper-trading promotion is waiting on risk approval",
      summary: "Research and execution are ready, but the organization cannot promote the new trading loop until the operator approves the guardrail.",
      cause: "Policy gate intentionally stops launch-ready work.",
      impact: "Blocks 2 workstreams and 3 agents.",
      recommendation: "Review the guardrail packet and approve or request changes.",
      fallback: "Keep the workstream in sandbox mode and re-run tomorrow.",
      evidence: [
        "Backtest package is attached",
        "Paper-trading checklist completed",
        "Budget and policy posture are within limits",
      ],
    },
    {
      id: "inc-runtime-drift",
      bucket: "Contained",
      severity: "warn",
      title: "Hermes adapter lacks normalized interrupt semantics",
      summary: "Runtime contract rollout is paused because one adapter cannot yet guarantee stop behavior.",
      cause: "Adapter implementation gap, not org-wide execution failure.",
      impact: "Blocks runtime normalization workstream only.",
      recommendation: "Contain it and keep the rest of the org on the stable runtime contract.",
      fallback: "Route the affected workstream to Claude Code temporarily.",
      evidence: [
        "Interrupt gap isolated to Hermes",
        "Codex and Claude Code adapters healthy",
        "No active work lost",
      ],
    },
    {
      id: "inc-review-latency",
      bucket: "Act now",
      severity: "warn",
      title: "Review queue is slowing decision throughput",
      summary: "Two agents are healthy but waiting for operator review.",
      cause: "Human bottleneck, not agent failure.",
      impact: "Reduces organizational throughput.",
      recommendation: "Clear the top approval and let autonomy resume.",
      fallback: "Pause low-priority workstreams until the queue clears.",
      evidence: [
        "2 agents in needs-review",
        "1 critical decision outstanding",
      ],
    },
    {
      id: "inc-memory-stale",
      bucket: "Needs diagnosis",
      severity: "blue",
      title: "One canonical memory entry may be stale",
      summary: "The operating assumption for risk limits predates the new strategy memo.",
      cause: "Memory promotion lag.",
      impact: "Could confuse future planning.",
      recommendation: "Compare the decision record with the latest evidence.",
      fallback: "Mark the memory item provisional until reviewed.",
      evidence: [
        "Stale decision marker fired 19m ago",
        "New strategy memo awaiting promotion",
      ],
    },
  ],
  transitions: [
    {
      tone: "good",
      title: "Research Lead attached validated backtest evidence",
      time: "4m ago",
    },
    {
      tone: "warn",
      title: "Risk approval became the top organization bottleneck",
      time: "6m ago",
    },
    {
      tone: "blue",
      title: "Runtime contract rollout contained a Hermes-specific gap",
      time: "12m ago",
    },
    {
      tone: "good",
      title: "Growth loop finished 3 prospect briefs without escalation",
      time: "18m ago",
    },
  ],
  memory: {
    objectives: [
      {
        id: "mem-objective-main",
        title: "Reach stable paper-trading readiness without breaching risk posture",
        copy: "Current success criteria: validated strategy, daily reporting, explicit risk guardrail, and stable runtime posture.",
        tone: "critical",
      },
      {
        id: "mem-plan-main",
        title: "Current operating plan",
        copy: "Research finishes evidence, risk approves the guardrail, execution promotes the loop, and Memory Curator promotes the strategy memo into canonical guidance.",
        tone: "blue",
      },
    ],
    decisions: [
      {
        id: "mem-decision-risk-gate",
        title: "Risk approval is mandatory before moving from sandbox to paper trading",
        copy: "Approved last quarter. Still in force. Being revalidated against the new alpha strategy.",
        tone: "critical",
      },
      {
        id: "mem-decision-runtime",
        title: "Default coding runtime is Claude Code with Codex fallback",
        copy: "Selected for stable stop semantics and evidence formatting parity.",
        tone: "blue",
      },
    ],
    evidence: [
      {
        id: "mem-evidence-backtest",
        title: "Backtest evidence package",
        copy: "Validated by Research Lead. Ready for operator review.",
        tone: "good",
      },
      {
        id: "mem-evidence-reporting",
        title: "Daily reporting pipeline proof",
        copy: "Latest simulated run completed without incident.",
        tone: "good",
      },
    ],
    canonical: [
      {
        id: "mem-canonical-risk",
        title: "Current risk operating guardrail",
        copy: "Canonical. Last verified 3 days ago. May need promotion update after current review.",
        tone: "warn",
      },
      {
        id: "mem-canonical-onboarding",
        title: "Org runtime contract and escalation policy",
        copy: "Canonical. In force across Research, Growth, and Platform teams.",
        tone: "blue",
      },
    ],
  },
};

function toneClass(tone) {
  return tone === "critical" ? "critical" : tone === "warn" ? "warn" : tone === "good" ? "good" : "blue";
}

function selectedWorkstream() {
  return data.workstreams.find((item) => item.id === state.selectedWorkstreamId) ?? data.workstreams[0];
}

function selectedAgent() {
  return data.agents.find((item) => item.id === state.selectedAgentId) ?? data.agents[0];
}

function selectedIncident() {
  return data.incidents.find((item) => item.id === state.selectedIncidentId) ?? data.incidents[0];
}

function selectedMemory() {
  const all = [
    ...data.memory.objectives,
    ...data.memory.decisions,
    ...data.memory.evidence,
    ...data.memory.canonical,
  ];
  return all.find((item) => item.id === state.selectedMemoryId) ?? all[0];
}

function renderTopbar() {
  const org = data.organization;
  return `
    <header class="topbar">
      <div class="brand">
        <div class="brand-mark"></div>
        <div class="brand-copy">
          <strong>MAAS</strong>
          <span>autonomous organization control plane</span>
        </div>
        <div>
          <span class="org-name">${org.name}</span>
          <span class="org-subtitle">${org.subtitle}</span>
        </div>
      </div>

      <div class="topbar-middle">
        <div class="select-shell">
          <label>Organization</label>
          <select>
            <option>${org.name}</option>
            <option>Atlas Labs</option>
            <option>Mercury Ops</option>
          </select>
        </div>

        <div class="search-shell">
          <span class="eyebrow">Command</span>
          <input value="" placeholder="Jump to workstream, agent, incident, or memory…" />
        </div>
      </div>

      <div class="topbar-actions">
        <div class="chip chip--critical"><strong>${org.status}</strong><span>${org.statusReason}</span></div>
        <button class="action-button action-button--primary">Resume autonomy</button>
        <button class="action-button action-button--ghost" data-theme-toggle>${state.theme === "dark" ? "Light" : "Dark"} theme</button>
      </div>
    </header>
  `;
}

function renderSubnav() {
  const views = [
    ["command", "Command"],
    ["workstreams", "Workstreams"],
    ["agents", "Agents"],
    ["incidents", "Incidents"],
    ["memory", "Memory"],
  ];

  const nav = views
    .map(
      ([value, label]) =>
        `<button class="nav-button ${state.view === value ? "is-active" : ""}" data-view="${value}">${label}</button>`,
    )
    .join("");

  return `
    <div class="subnav">
      <div class="nav-list">${nav}</div>

      <div class="chip-list">
        <div class="chip chip--blue"><strong>${data.organization.activeTeams}</strong><span>active teams</span></div>
        <div class="chip chip--good"><strong>${data.organization.activeAgents}</strong><span>healthy agents</span></div>
        <div class="chip chip--warn"><strong>${data.organization.activeRuns}</strong><span>runs in motion</span></div>
        <div class="chip chip--critical"><strong>${data.organization.blockedWorkstreams}</strong><span>blocked workstreams</span></div>
      </div>

      <div class="mode-list">
        <button class="mode-button is-active">Supervised</button>
        <button class="mode-button">Portfolio</button>
      </div>
    </div>
  `;
}

function renderCommand() {
  return `
    <div class="view-grid view-grid--command">
      <div class="stack">
        <section class="panel panel--scroll">
          <div class="hero-line">
            <div>
              <div class="panel-kicker">Decision queue</div>
              <h2 class="panel-title">What needs human judgment now</h2>
              <p class="panel-subtitle">Clear approvals, policy gates, and strategic choices before you drill into work details.</p>
            </div>
            <div class="hero-status"><span class="status-dot critical"></span>3 items</div>
          </div>
          <div class="decision-list section-block">
            ${data.decisions
              .map(
                (item, index) => `
                <article class="decision-card ${index === 0 ? "is-primary" : ""}">
                  <div class="card-head">
                    <span class="label-chip ${toneClass(item.tone)}">${index === 0 ? "Primary" : item.owner}</span>
                    <button class="action-button">${item.action}</button>
                  </div>
                  <h3 class="card-title">${item.title}</h3>
                  <p class="card-copy">${item.summary}</p>
                  <div class="card-meta">
                    <span class="mini-chip">${item.owner}</span>
                    <span class="mini-chip">${item.impact}</span>
                  </div>
                </article>
              `,
              )
              .join("")}
          </div>
        </section>
      </div>

      <div class="stack">
        <section class="panel panel--scroll">
          <div class="hero-line">
            <div>
              <div class="panel-kicker">Objective</div>
              <h2 class="panel-title">${data.organization.objective}</h2>
              <p class="panel-subtitle">MAAS routes teams and runtimes toward this objective. The operator supervises deviations, approvals, and risk.</p>
            </div>
            <div class="hero-status"><span class="status-dot warn"></span>${data.organization.mode}</div>
          </div>

          <div class="stats-grid">
            <div class="stat-card"><span class="metric-label">Active workstreams</span><strong>4</strong><span class="metric-note">2 on track · 1 review · 1 blocked</span></div>
            <div class="stat-card"><span class="metric-label">Decision pressure</span><strong>3</strong><span class="metric-note">1 critical approval</span></div>
            <div class="stat-card"><span class="metric-label">Runtime posture</span><strong>Stable</strong><span class="metric-note">1 contained adapter issue</span></div>
            <div class="stat-card"><span class="metric-label">Memory freshness</span><strong>1 stale</strong><span class="metric-note">Strategy memo awaiting promotion</span></div>
          </div>

          <div class="workstream-map section-block">
            ${data.workstreams
              .filter((item) => item.status !== "backlog")
              .map(
                (item) => `
                <article class="workstream-card ${state.selectedWorkstreamId === item.id ? "is-selected" : ""}" data-workstream="${item.id}">
                  <div class="card-head">
                    <div>
                      <span class="label-chip ${toneClass(item.priority === "Critical" ? "critical" : item.status === "blocked" ? "warn" : item.status === "review" ? "blue" : "good")}">${item.priority}</span>
                    </div>
                    <span class="mini-chip">${item.team}</span>
                  </div>
                  <h3 class="card-title">${item.title}</h3>
                  <p class="card-copy">${item.summary}</p>
                  <div class="progress-row">
                    <div class="progress-bar"><span style="width:${item.progress}%"></span></div>
                    <span class="muted">${item.progress}%</span>
                  </div>
                  <div class="card-meta">
                    <span class="mini-chip">${item.owner}</span>
                    <span class="mini-chip">${item.health}</span>
                    <span class="mini-chip">${item.runtime}</span>
                  </div>
                </article>
              `,
              )
              .join("")}
          </div>
        </section>
      </div>

      <div class="stack">
        <section class="panel">
          <div class="panel-kicker">Capability health</div>
          <h2 class="panel-title">Teams and runtime posture</h2>
          <div class="stack section-block">
            ${data.teams
              .map(
                (team) => `
                <article class="capability-card">
                  <div class="card-head">
                    <h3 class="card-title">${team.name}</h3>
                    <span class="mini-chip">${team.capacity}</span>
                  </div>
                  <p class="card-copy">${team.mission}</p>
                  <div class="card-meta">
                    <span class="mini-chip">${team.pressure}</span>
                  </div>
                </article>
              `,
              )
              .join("")}
          </div>
        </section>

        <section class="panel panel--scroll">
          <div class="panel-kicker">Meaningful transitions</div>
          <h2 class="panel-title">What changed recently</h2>
          <div class="timeline-list section-block">
            ${data.transitions
              .map(
                (item) => `
                <article class="timeline-item">
                  <div class="card-head">
                    <span class="label-chip ${toneClass(item.tone)}">${item.time}</span>
                  </div>
                  <h3 class="card-title">${item.title}</h3>
                </article>
              `,
              )
              .join("")}
          </div>
        </section>
      </div>
    </div>
  `;
}

function workstreamLanes() {
  return [
    ["ready", "Ready"],
    ["in_progress", "In progress"],
    ["review", "Review / Decision"],
    ["blocked", "Blocked"],
  ];
}

function renderWorkstreams() {
  const selected = selectedWorkstream();
  return `
    <div class="view-grid view-grid--workstreams">
      <section class="panel panel--scroll">
        <div class="hero-line">
          <div>
            <div class="panel-kicker">Workstreams</div>
            <h2 class="panel-title">Execution flow</h2>
            <p class="panel-subtitle">Cards summarize; the inspector explains and offers the safe next action.</p>
          </div>
          <div class="control-row">
            <button class="filter-button is-active">Needs attention</button>
            <button class="filter-button">By team</button>
            <button class="filter-button">By objective</button>
          </div>
        </div>

        <div class="lane-shell section-block">
          ${workstreamLanes()
            .map(([status, label]) => {
              const items = data.workstreams.filter((item) => item.status === status);
              return `
                <section class="lane">
                  <div class="lane-head">
                    <div>
                      <h3>${label}</h3>
                      <span class="muted">${items.length} items</span>
                    </div>
                    <span class="mini-chip">${items.length}</span>
                  </div>
                  <div class="lane-list">
                    ${items
                      .map(
                        (item) => `
                        <article class="task-card ${item.id === state.selectedWorkstreamId ? "is-selected" : ""}" data-workstream="${item.id}">
                          <div class="card-head">
                            <span class="label-chip ${toneClass(item.priority === "Critical" ? "critical" : item.status === "blocked" ? "warn" : item.status === "review" ? "blue" : "good")}">${item.priority}</span>
                            <span class="mini-chip">${item.owner}</span>
                          </div>
                          <h3 class="task-title">${item.title}</h3>
                          <p class="task-copy">${item.summary}</p>
                          <div class="card-meta">
                            <span class="mini-chip">${item.team}</span>
                            <span class="mini-chip">${item.health}</span>
                            <span class="mini-chip">${item.scope[0]}</span>
                          </div>
                        </article>
                      `,
                      )
                      .join("") || `<div class="detail-box"><p>No items here.</p></div>`}
                  </div>
                </section>
              `;
            })
            .join("")}
        </div>
      </section>

      <aside class="panel panel--sticky panel--scroll">
        <div class="hero-line">
          <div>
            <div class="panel-kicker">Inspector</div>
            <h2 class="panel-title">${selected.title}</h2>
            <p class="panel-subtitle">${selected.summary}</p>
          </div>
          <span class="label-chip ${toneClass(selected.status === "blocked" ? "warn" : selected.status === "review" ? "critical" : "good")}">${selected.health}</span>
        </div>

        <div class="inspector-grid section-block">
          <div class="detail-box">
            <h4>Next safe action</h4>
            <p><strong>${selected.nextAction}</strong></p>
          </div>
          <div class="detail-box">
            <h4>Evidence</h4>
            <p>${selected.evidence}</p>
          </div>
          <div class="detail-box">
            <h4>Scope</h4>
            <ul>${selected.scope.map((item) => `<li>${item}</li>`).join("")}</ul>
          </div>
          <div class="detail-box">
            <h4>Execution posture</h4>
            <p><strong>${selected.runtime}</strong></p>
            <p>${selected.verification}</p>
          </div>
          ${
            selected.incidentId
              ? `<div class="detail-box">
                   <h4>Linked incident</h4>
                   <p>${data.incidents.find((item) => item.id === selected.incidentId)?.title ?? "None"}</p>
                 </div>`
              : ""
          }
          <div class="detail-box">
            <h4>Operator actions</h4>
            <div class="card-meta">
              <button class="action-button action-button--primary">Review or intervene</button>
              <button class="action-button">Open evidence</button>
            </div>
          </div>
        </div>
      </aside>
    </div>
  `;
}

function agentStatusLabel(status) {
  if (status === "working") return "Working";
  if (status === "blocked") return "Blocked";
  if (status === "needs_review") return "Needs review";
  return "Idle";
}

function renderAgents() {
  const selected = selectedAgent();
  const grouped = {
    working: data.agents.filter((item) => item.status === "working"),
    needs_review: data.agents.filter((item) => item.status === "needs_review"),
    blocked: data.agents.filter((item) => item.status === "blocked"),
    idle: data.agents.filter((item) => item.status === "idle"),
  };

  return `
    <div class="view-grid view-grid--agents">
      <div class="stack">
        <section class="panel">
          <div class="panel-kicker">Teams</div>
          <h2 class="panel-title">Capability clusters</h2>
          <div class="stack section-block">
            ${data.teams
              .map(
                (team) => `
                <article class="capability-card">
                  <h3 class="card-title">${team.name}</h3>
                  <p class="card-copy">${team.mission}</p>
                  <div class="card-meta">
                    <span class="mini-chip">${team.capacity}</span>
                    <span class="mini-chip">${team.pressure}</span>
                  </div>
                </article>
              `,
              )
              .join("")}
          </div>
        </section>
      </div>

      <section class="panel panel--scroll">
        <div class="hero-line">
          <div>
            <div class="panel-kicker">Agents</div>
            <h2 class="panel-title">Ownership and coordination</h2>
            <p class="panel-subtitle">Grouped by status so you can see who is working, who is waiting, and where handoffs are stalling.</p>
          </div>
        </div>

        <div class="stack section-block">
          ${Object.entries(grouped)
            .map(
              ([status, items]) => `
              <section class="section-block">
                <div class="agent-group-header">
                  <div>
                    <span class="label-chip ${toneClass(status === "blocked" ? "warn" : status === "needs_review" ? "critical" : status === "working" ? "good" : "blue")}">${agentStatusLabel(status)}</span>
                  </div>
                  <span class="mini-chip">${items.length}</span>
                </div>
                <div class="agent-list">
                  ${items
                    .map(
                      (item) => `
                      <article class="agent-card ${item.id === state.selectedAgentId ? "is-selected" : ""}" data-agent="${item.id}">
                        <div class="card-head">
                          <span class="mini-chip">${item.team}</span>
                          <span class="label-chip ${toneClass(status === "blocked" ? "warn" : status === "needs_review" ? "critical" : status === "working" ? "good" : "blue")}">${agentStatusLabel(status)}</span>
                        </div>
                        <h4>${item.name}</h4>
                        <p>${item.current}</p>
                        <div class="card-meta">
                          <span class="mini-chip">${item.runtime}</span>
                          <span class="mini-chip">${item.waitingOn}</span>
                        </div>
                      </article>
                    `,
                    )
                    .join("")}
                </div>
              </section>
            `,
            )
            .join("")}
        </div>
      </section>

      <div class="stack">
        <section class="panel">
          <div class="panel-kicker">Handoffs</div>
          <h2 class="panel-title">Where work is waiting to transfer</h2>
          <div class="stack section-block">
            ${data.handoffs
              .map(
                (item) => `
                <article class="handoff-card">
                  <div class="card-head">
                    <h3 class="card-title">${item.item}</h3>
                    <span class="mini-chip">${item.age}</span>
                  </div>
                  <p class="card-copy">${item.from} → ${item.to}</p>
                  <div class="card-meta">
                    <span class="mini-chip">${item.state}</span>
                  </div>
                </article>
              `,
              )
              .join("")}
          </div>
        </section>

        <section class="panel">
          <div class="panel-kicker">Selected agent</div>
          <h2 class="panel-title">${selected.name}</h2>
          <div class="inspector-grid section-block">
            <div class="detail-box">
              <h4>Current responsibility</h4>
              <p>${selected.current}</p>
            </div>
            <div class="detail-box">
              <h4>Waiting on</h4>
              <p>${selected.waitingOn}</p>
            </div>
            <div class="detail-box">
              <h4>Last meaningful action</h4>
              <p>${selected.lastAction}</p>
            </div>
            <div class="detail-box">
              <h4>Risk state</h4>
              <p>${selected.risk}</p>
            </div>
          </div>
        </section>
      </div>
    </div>
  `;
}

function incidentBuckets() {
  return ["Act now", "Needs approval", "Needs diagnosis", "Contained"];
}

function renderIncidents() {
  const selected = selectedIncident();
  return `
    <div class="view-grid view-grid--incidents">
      <section class="panel panel--scroll">
        <div class="hero-line">
          <div>
            <div class="panel-kicker">Incidents</div>
            <h2 class="panel-title">Operator inbox</h2>
            <p class="panel-subtitle">Grouped by actionability, not by subsystem. This is where approvals, failures, and blocked work converge.</p>
          </div>
          <div class="chip-list">
            <div class="chip chip--critical"><strong>1</strong><span>critical</span></div>
            <div class="chip chip--warn"><strong>2</strong><span>awaiting action</span></div>
          </div>
        </div>

        <div class="stack section-block">
          ${incidentBuckets()
            .map((bucket) => {
              const items = data.incidents.filter((item) => item.bucket === bucket);
              return `
                <section class="incident-group">
                  <div class="incident-group-header">
                    <div>
                      <span class="label-chip ${toneClass(bucket === "Act now" ? "critical" : bucket === "Needs approval" ? "warn" : bucket === "Contained" ? "blue" : "good")}">${bucket}</span>
                    </div>
                    <span class="mini-chip">${items.length}</span>
                  </div>
                  <div class="incident-group">
                    ${items
                      .map(
                        (item) => `
                        <article class="incident-card ${item.id === state.selectedIncidentId ? "is-primary" : ""}" data-incident="${item.id}">
                          <div class="incident-head">
                            <span class="label-chip ${toneClass(item.severity)}">${item.severity}</span>
                            <span class="mini-chip">${item.bucket}</span>
                          </div>
                          <h3 class="incident-title">${item.title}</h3>
                          <p class="incident-copy">${item.summary}</p>
                          <div class="card-meta">
                            <span class="mini-chip">${item.impact}</span>
                          </div>
                        </article>
                      `,
                      )
                      .join("") || `<div class="detail-box"><p>No incidents here.</p></div>`}
                  </div>
                </section>
              `;
            })
            .join("")}
        </div>
      </section>

      <aside class="panel panel--sticky panel--scroll">
        <div class="hero-line">
          <div>
            <div class="panel-kicker">Selected incident</div>
            <h2 class="panel-title">${selected.title}</h2>
            <p class="panel-subtitle">${selected.summary}</p>
          </div>
          <span class="label-chip ${toneClass(selected.severity)}">${selected.severity}</span>
        </div>
        <div class="inspector-grid section-block">
          <div class="detail-box">
            <h4>What MAAS recommends</h4>
            <p><strong>${selected.recommendation}</strong></p>
          </div>
          <div class="detail-box">
            <h4>Why this surfaced</h4>
            <p>${selected.cause}</p>
          </div>
          <div class="detail-box">
            <h4>Impact</h4>
            <p>${selected.impact}</p>
          </div>
          <div class="detail-box">
            <h4>Safe fallback</h4>
            <p>${selected.fallback}</p>
          </div>
          <div class="detail-box">
            <h4>Evidence summary</h4>
            <ul>${selected.evidence.map((item) => `<li>${item}</li>`).join("")}</ul>
          </div>
          <div class="detail-box">
            <h4>Actions</h4>
            <div class="card-meta">
              <button class="action-button action-button--primary">Take recommended action</button>
              <button class="action-button">Escalate</button>
            </div>
          </div>
        </div>
      </aside>
    </div>
  `;
}

function renderMemoryColumn(title, kicker, items) {
  return `
    <section class="panel panel--scroll memory-column">
      <div>
        <div class="panel-kicker">${kicker}</div>
        <h2 class="panel-title">${title}</h2>
      </div>
      <div class="memory-list">
        ${items
          .map(
            (item) => `
            <article class="memory-card ${item.id === state.selectedMemoryId ? "is-primary" : ""}" data-memory="${item.id}">
              <div class="memory-head">
                <span class="label-chip ${toneClass(item.tone)}">${item.tone}</span>
              </div>
              <h3 class="memory-title">${item.title}</h3>
              <p class="memory-copy">${item.copy}</p>
            </article>
          `,
          )
          .join("")}
      </div>
    </section>
  `;
}

function renderMemory() {
  const selected = selectedMemory();
  return `
    <div class="view-grid view-grid--memory">
      <div class="memory-column">
        ${renderMemoryColumn("Objective and plan", "Memory", data.memory.objectives)}
      </div>
      <div class="memory-column">
        ${renderMemoryColumn("Decisions and evidence", "Memory", [...data.memory.decisions, ...data.memory.evidence])}
      </div>
      <div class="memory-column">
        <section class="panel panel--scroll">
          <div class="panel-kicker">Canonical memory</div>
          <h2 class="panel-title">Trusted knowledge in force</h2>
          <div class="memory-list section-block">
            ${data.memory.canonical
              .map(
                (item) => `
                <article class="memory-card ${item.id === state.selectedMemoryId ? "is-primary" : ""}" data-memory="${item.id}">
                  <div class="memory-head">
                    <span class="label-chip ${toneClass(item.tone)}">${item.tone}</span>
                  </div>
                  <h3 class="memory-title">${item.title}</h3>
                  <p class="memory-copy">${item.copy}</p>
                </article>
              `,
              )
              .join("")}
          </div>
        </section>

        <section class="panel">
          <div class="panel-kicker">Selected record</div>
          <h2 class="panel-title">${selected.title}</h2>
          <div class="inspector-grid section-block">
            <div class="detail-box">
              <h4>Current truth</h4>
              <p>${selected.copy}</p>
            </div>
            <div class="detail-box">
              <h4>Why it matters</h4>
              <p>Memory should steer objectives and workstreams. This item exists to keep future execution aligned and auditable.</p>
            </div>
            <div class="detail-box">
              <h4>Promotion model</h4>
              <p>Draft outputs and evidence stay provisional. Only reviewed records become canonical memory.</p>
            </div>
          </div>
        </section>
      </div>
    </div>
  `;
}

function renderView() {
  if (state.view === "command") return renderCommand();
  if (state.view === "workstreams") return renderWorkstreams();
  if (state.view === "agents") return renderAgents();
  if (state.view === "incidents") return renderIncidents();
  return renderMemory();
}

function render() {
  document.documentElement.dataset.theme = state.theme;

  app.innerHTML = `
    <div class="app-shell">
      ${renderTopbar()}
      ${renderSubnav()}
      <main class="view-shell">
        ${renderView()}
      </main>
    </div>
  `;

  bindEvents();
}

function bindEvents() {
  app.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => {
      state.view = button.dataset.view;
      render();
    });
  });

  app.querySelector("[data-theme-toggle]")?.addEventListener("click", () => {
    state.theme = state.theme === "dark" ? "light" : "dark";
    render();
  });

  app.querySelectorAll("[data-workstream]").forEach((element) => {
    element.addEventListener("click", () => {
      state.selectedWorkstreamId = element.dataset.workstream;
      if (state.view === "command") {
        state.view = "workstreams";
      }
      render();
    });
  });

  app.querySelectorAll("[data-agent]").forEach((element) => {
    element.addEventListener("click", () => {
      state.selectedAgentId = element.dataset.agent;
      render();
    });
  });

  app.querySelectorAll("[data-incident]").forEach((element) => {
    element.addEventListener("click", () => {
      state.selectedIncidentId = element.dataset.incident;
      render();
    });
  });

  app.querySelectorAll("[data-memory]").forEach((element) => {
    element.addEventListener("click", () => {
      state.selectedMemoryId = element.dataset.memory;
      render();
    });
  });
}

render();
