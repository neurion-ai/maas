const app = document.querySelector("#app");

const projects = [
  { id: "all", name: "All missions", tone: "blue" },
  { id: "quant-alpha", name: "Quant Alpha", tone: "yellow" },
  { id: "growth-loop", name: "Growth Loop", tone: "green" },
  { id: "platform-core", name: "Platform Core", tone: "blue" },
  { id: "governance", name: "Governance", tone: "purple" },
];

const agents = [
  { id: "agent-ceo", name: "CEO", role: "Objective owner", runtime: "Claude", status: "idle" },
  { id: "agent-chief-of-staff", name: "ChiefOfStaff", role: "Decision broker", runtime: "Seraph", status: "live" },
  { id: "agent-research", name: "ResearchLead", role: "Research lane", runtime: "Claude Code", status: "live" },
  { id: "agent-growth", name: "GrowthLead", role: "Growth lane", runtime: "OpenClaw", status: "live" },
  { id: "agent-runtime", name: "RuntimeBroker", role: "Runtime routing", runtime: "Hermes", status: "blocked" },
  { id: "agent-memory", name: "MemoryCurator", role: "Canonical memory", runtime: "Seraph", status: "idle" },
  { id: "agent-review", name: "ReviewDesk", role: "Review lane", runtime: "Claude Code", status: "live" },
  { id: "agent-codex", name: "CodexCoder", role: "Execution lane", runtime: "Codex CLI", status: "live" },
];

const goals = [
  {
    id: "goal-launch",
    title: "Launch the autonomous quant alpha loop safely",
    owner: "CEO",
    progress: 76,
    summary:
      "Move from research and sandbox verification into guarded paper trading with repeatable approvals and runtime safety.",
    linkedIssues: ["QNT-127", "OPS-88", "MEM-14"],
    milestones: [
      "Guardrail approved",
      "Runtime parity closed",
      "Weekly operator brief promoted to memory",
    ],
  },
  {
    id: "goal-growth",
    title: "Run a weekly outbound intelligence cadence",
    owner: "GrowthLead",
    progress: 58,
    summary:
      "Turn research findings into reusable outbound briefs, review queues, and campaign memory without direct human micromanagement.",
    linkedIssues: ["GTH-204", "GTH-211", "MEM-32"],
    milestones: ["Prospect brief queue healthy", "Review SLA under 20m", "Playbook promoted"],
  },
  {
    id: "goal-platform",
    title: "Normalize the runtime contract across capable agents",
    owner: "RuntimeBroker",
    progress: 44,
    summary:
      "Keep Codex, Claude Code, Hermes, OpenClaw, and Seraph interchangeable under one controlled execution contract.",
    linkedIssues: ["OPS-88", "OPS-104", "GOV-19"],
    milestones: ["Interrupt parity", "Fallback routing", "Audit trace completeness"],
  },
];

function buildOpenIssue(data) {
  return {
    kind: "open",
    collaborators: [],
    outputs: [],
    history: [],
    threads: [],
    ...data,
  };
}

function buildResolvedIssue(data) {
  return {
    kind: "resolved",
    outputs: [],
    history: [],
    collaborators: [],
    ...data,
  };
}

const scenarios = {
  startup: {
    key: "startup",
    label: "Starting work",
    company: {
      name: "Northstar Research Group",
      subtitle: "Autonomous organization",
      objective: "Boot the first autonomous quant-and-growth loop",
      liveCount: 2,
      stage: "Initialization pass",
      stageCopy:
        "MAAS is decomposing the objective, validating capable runtimes, and preparing the first decision gates without exposing internal scheduler mechanics.",
    },
    stats: [
      { label: "Open issues", value: "112", note: "18 launchable, 7 blocked, 87 staged" },
      { label: "Issues in progress", value: "9", note: "Mostly planning and bootstrap verification" },
      { label: "Resolved", value: "1,024", note: "Historical runs and prior memory retained" },
      { label: "Pending approvals", value: "6", note: "2 critical gates before wider autonomy" },
    ],
    dashboard: {
      operatorQueue: [
        {
          tone: "yellow",
          title: "Approve initial runtime policy",
          summary: "Execution is ready, but MAAS needs a default runtime/fallback posture before launching the first queue.",
          action: "Review policy",
          project: "Governance",
        },
        {
          tone: "blue",
          title: "Approve first wave of decomposed issues",
          summary: "The planning pass proposed 14 runnable issues across Quant Alpha, Platform Core, and Growth Loop.",
          action: "Approve plan",
          project: "Quant Alpha",
        },
        {
          tone: "red",
          title: "Contain Hermes stop-semantics gap",
          summary: "Startup can continue, but one runtime lane still needs a fallback gate before it becomes eligible for broader work.",
          action: "Inspect incident",
          project: "Platform Core",
        },
      ],
      lanePressure: [
        { label: "Ready to launch", value: "18", note: "Waiting on policy and initial approvals" },
        { label: "Review queue", value: "4", note: "Mostly plan and memory promotions" },
        { label: "Blocked", value: "7", note: "3 runtime, 2 policy, 2 handoff" },
        { label: "Resolved today", value: "12", note: "Mostly startup and migration cleanup" },
      ],
      landed: [
        {
          key: "MEM-08",
          title: "Promote baseline risk memo into canonical memory",
          closed: "18m ago",
          outcome: "Merged into governance memory",
          project: "Governance",
        },
        {
          key: "OPS-70",
          title: "Validate Codex CLI preflight across the execution lane",
          closed: "41m ago",
          outcome: "Marked healthy for startup",
          project: "Platform Core",
        },
      ],
      history: [
        {
          lane: "main",
          tone: "blue",
          text: "Planning lane decomposed the primary objective into 14 executable issues",
          time: "8m ago",
          project: "Quant Alpha",
        },
        {
          lane: "runtime/codex-default",
          tone: "green",
          text: "Codex CLI runtime passed preflight and opened the execution lane",
          time: "14m ago",
          project: "Platform Core",
        },
        {
          lane: "review/plan-packet",
          tone: "yellow",
          text: "ChiefOfStaff created the first plan approval packet for operator review",
          time: "21m ago",
          project: "Governance",
        },
        {
          lane: "runtime/hermes-fallback",
          tone: "red",
          text: "Hermes stop semantics were flagged; MAAS isolated the lane and requested a fallback decision",
          time: "25m ago",
          project: "Platform Core",
        },
      ],
    },
    inbox: {
      summary: [
        "2 critical decisions",
        "3 runtime lanes warming",
        "7 blocked items",
        "14 issues prepared",
      ],
      queues: [
        {
          name: "Approvals",
          summary: "The only things preventing the first autonomous pass from starting.",
          items: [
            {
              tone: "yellow",
              title: "Approve initial runtime policy",
              summary: "Codex CLI and Claude Code are healthy. Decide whether Hermes should stay behind a fallback gate.",
              impact: "18 ready issues are waiting.",
              action: "Review policy",
              project: "Governance",
            },
            {
              tone: "blue",
              title: "Approve first-wave execution plan",
              summary: "The planning lane finished decomposition and bundled the first 14 issues for launch.",
              impact: "Quant Alpha and Growth Loop remain in staging.",
              action: "Open plan",
              project: "Quant Alpha",
            },
          ],
        },
        {
          name: "Runtime degradation",
          summary: "Contained startup risks that need explicit operator awareness.",
          items: [
            {
              tone: "red",
              title: "Hermes stop semantics missing",
              summary: "The lane is isolated; execution can still proceed on Codex and Claude if policy allows fallback.",
              impact: "7 platform tasks remain blocked behind the parity fix.",
              action: "Inspect incident",
              project: "Platform Core",
            },
          ],
        },
        {
          name: "Handoffs",
          summary: "New work waiting to cross a decision or review boundary.",
          items: [
            {
              tone: "blue",
              title: "Bootstrap notes waiting for memory promotion",
              summary: "The first operator brief is ready to be promoted once the plan is approved.",
              impact: "Future runs will lack canonical startup context if ignored.",
              action: "Review memory",
              project: "Governance",
            },
          ],
        },
      ],
    },
    issues: {
      counts: { open: 112, inProgress: 9, review: 6, blocked: 7, resolved: 1024 },
      open: [
        buildOpenIssue({
          id: "startup-gov-19",
          key: "GOV-19",
          title: "Approve initial runtime policy",
          project: "Governance",
          group: "decision",
          priority: "Critical",
          lead: "CEO",
          collaborators: ["ChiefOfStaff", "RuntimeBroker"],
          statusLabel: "Awaiting operator decision",
          summary:
            "MAAS has enough runtime evidence to start work, but it still needs a default fallback rule before allowing Hermes into the launch set.",
          nextAction: "Approve the policy or request another runtime pass",
          updated: "5m ago",
          outputs: ["runtime-policy.diff", "startup-preflight.md"],
          threads: [
            {
              branch: "policy/runtime-defaults",
              agent: "ChiefOfStaff",
              runtime: "Seraph",
              state: "awaiting review",
              note: "Prepared the operator packet with default/fallback routing options.",
            },
            {
              branch: "runtime/hermes-parity",
              agent: "RuntimeBroker",
              runtime: "Hermes",
              state: "blocked",
              note: "Lane isolated after stop semantics failed the final startup check.",
            },
          ],
          history: [
            { lane: "main", tone: "blue", text: "Policy issue created from startup decomposition", time: "42m ago" },
            { lane: "runtime/hermes-parity", tone: "red", text: "Hermes startup check flagged missing stop semantics", time: "25m ago" },
            { lane: "policy/runtime-defaults", tone: "yellow", text: "ChiefOfStaff opened the decision packet", time: "8m ago" },
          ],
        }),
        buildOpenIssue({
          id: "startup-qnt-127",
          key: "QNT-127",
          title: "Approve first wave of quant alpha issues",
          project: "Quant Alpha",
          group: "decision",
          priority: "High",
          lead: "CEO",
          collaborators: ["ResearchLead", "ChiefOfStaff"],
          statusLabel: "Ready for approval",
          summary:
            "The first quant research pack is decomposed, scoped, and linked to evidence. MAAS needs sign-off to release it into the execution lane.",
          nextAction: "Approve the execution plan or request one more research pass",
          updated: "11m ago",
          outputs: ["launch-pack.zip", "first-wave-issues.md"],
          threads: [
            {
              branch: "research/first-wave",
              agent: "ResearchLead",
              runtime: "Claude Code",
              state: "complete",
              note: "Prepared the first 9 research issues and linked prior findings.",
            },
            {
              branch: "review/launch-packet",
              agent: "ChiefOfStaff",
              runtime: "Seraph",
              state: "awaiting review",
              note: "Prepared the packet for operator sign-off.",
            },
          ],
          history: [
            { lane: "main", tone: "blue", text: "Planning lane created first-wave issue packet", time: "51m ago" },
            { lane: "research/first-wave", tone: "green", text: "ResearchLead finished scope and linked evidence", time: "16m ago" },
            { lane: "review/launch-packet", tone: "yellow", text: "ChiefOfStaff moved the plan into approval", time: "11m ago" },
          ],
        }),
        buildOpenIssue({
          id: "startup-ops-88",
          key: "OPS-88",
          title: "Fix Hermes interrupt parity before broader rollout",
          project: "Platform Core",
          group: "blocked",
          priority: "High",
          lead: "RuntimeBroker",
          collaborators: ["CodexCoder"],
          statusLabel: "Blocked on parity gap",
          summary:
            "The runtime lane is contained and fallback routing is available, but the parity fix still blocks the wider Platform Core queue.",
          nextAction: "Route one more attempt or keep Hermes behind the fallback gate",
          updated: "7m ago",
          outputs: ["hermes-gap.log"],
          threads: [
            {
              branch: "runtime/hermes-fix",
              agent: "CodexCoder",
              runtime: "Codex CLI",
              state: "in progress",
              note: "Implementing a safer interrupt shim around Hermes stop handling.",
            },
            {
              branch: "ops/fallback-routing",
              agent: "RuntimeBroker",
              runtime: "Hermes",
              state: "contained",
              note: "Overflow tasks already route to Codex and Claude when needed.",
            },
          ],
          history: [
            { lane: "main", tone: "blue", text: "Platform Core flagged Hermes parity gap during startup", time: "33m ago" },
            { lane: "ops/fallback-routing", tone: "yellow", text: "Fallback route activated for the affected queue", time: "22m ago" },
            { lane: "runtime/hermes-fix", tone: "red", text: "CodexCoder opened a parity-fix attempt", time: "7m ago" },
          ],
        }),
        buildOpenIssue({
          id: "startup-mem-14",
          key: "MEM-14",
          title: "Promote startup notes into canonical memory",
          project: "Governance",
          group: "watch",
          priority: "Medium",
          lead: "MemoryCurator",
          collaborators: ["ChiefOfStaff"],
          statusLabel: "Waiting on upstream approval",
          summary:
            "The startup brief is ready but should not become canonical memory until the initial plan and runtime policy are approved.",
          nextAction: "Wait for the runtime policy and plan approvals to land",
          updated: "18m ago",
          outputs: ["startup-brief.md"],
          threads: [
            {
              branch: "memory/startup-notes",
              agent: "MemoryCurator",
              runtime: "Seraph",
              state: "staged",
              note: "Canonical memory packet prepared and linked to the operator brief.",
            },
          ],
          history: [
            { lane: "main", tone: "blue", text: "Memory promotion issue created from startup policy", time: "27m ago" },
            { lane: "memory/startup-notes", tone: "yellow", text: "Promotion packet prepared and waiting on approval chain", time: "18m ago" },
          ],
        }),
      ],
      resolved: [
        buildResolvedIssue({
          id: "startup-res-1",
          key: "OPS-70",
          title: "Validate Codex CLI preflight across the execution lane",
          project: "Platform Core",
          resolution: "Marked healthy and unlocked Codex for the startup pass.",
          resolvedBy: "RuntimeBroker",
          closed: "41m ago",
          merged: "1 lane opened · 0 retries",
          outputs: ["preflight-report.json"],
          history: [
            { lane: "main", tone: "blue", text: "Preflight issue created from startup checklist", time: "1h ago" },
            { lane: "runtime/codex-default", tone: "green", text: "Codex CLI passed readiness and published the report", time: "41m ago" },
          ],
        }),
        buildResolvedIssue({
          id: "startup-res-2",
          key: "MEM-08",
          title: "Promote baseline risk memo into canonical memory",
          project: "Governance",
          resolution: "Merged into canonical memory and linked to the startup briefing.",
          resolvedBy: "MemoryCurator",
          closed: "18m ago",
          merged: "2 notes merged · 1 superseded",
          outputs: ["baseline-risk.md"],
          history: [
            { lane: "main", tone: "blue", text: "Historical memo selected for canonical promotion", time: "58m ago" },
            { lane: "memory/baseline-risk", tone: "green", text: "MemoryCurator promoted the memo and updated references", time: "18m ago" },
          ],
        }),
      ],
    },
    topology: {
      capabilities: [
        { name: "Planning pool", load: "3 active / 7 queued", note: "Decomposing startup objective" },
        { name: "Research pool", load: "2 active / 4 queued", note: "Preparing first-wave quant issues" },
        { name: "Review pool", load: "1 active / 5 waiting", note: "Mostly operator approval packets" },
      ],
      runtimes: [
        { name: "Codex CLI", status: "healthy", load: "2 running", note: "Execution + platform fixes" },
        { name: "Claude Code", status: "healthy", load: "2 running", note: "Research + review support" },
        { name: "Hermes", status: "degraded", load: "contained", note: "Behind fallback gate" },
        { name: "Seraph", status: "healthy", load: "1 running", note: "Decision packets and memory" },
      ],
      outputs: [
        { name: "Ready to launch", count: "18", note: "Waiting on the runtime policy" },
        { name: "Review queue", count: "4", note: "Plan and memory packets" },
        { name: "Blocked queue", count: "7", note: "Mostly Hermes parity follow-ups" },
        { name: "Resolved today", count: "12", note: "Startup cleanup and preflights" },
      ],
      handoffs: [
        { title: "Planning → Review", detail: "First-wave issue packet is ready for operator sign-off.", tone: "yellow" },
        { title: "Runtime → Execution", detail: "Codex lane is clear; Hermes is held behind fallback routing.", tone: "red" },
        { title: "Briefing → Memory", detail: "Startup notes are staged and waiting on upstream approvals.", tone: "blue" },
      ],
      graph: {
        title: "Execution graph for GOV-19",
        summary: "One policy issue, two parallel threads, one operator gate.",
        branches: [
          { tone: "blue", lane: "policy/runtime-defaults", state: "awaiting review", agent: "ChiefOfStaff", note: "Prepared the operator policy packet." },
          { tone: "red", lane: "runtime/hermes-parity", state: "blocked", agent: "RuntimeBroker", note: "Held behind a fallback gate until stop semantics are fixed." },
          { tone: "green", lane: "runtime/codex-default", state: "ready", agent: "CodexCoder", note: "Codex path already validated and ready to launch." },
        ],
      },
    },
  },
  active: {
    key: "active",
    label: "Working at scale",
    company: {
      name: "Northstar Research Group",
      subtitle: "Autonomous organization",
      objective: "Run research, growth, governance, and platform work in parallel",
      liveCount: 7,
      stage: "Autonomy in motion",
      stageCopy:
        "The operator mostly clears decisions, watches runtime pressure, and promotes strong outputs. The organization is already doing real work across multiple missions.",
    },
    stats: [
      { label: "Open issues", value: "100", note: "31 in flight, 18 in review, 9 blocked" },
      { label: "Issues in progress", value: "31", note: "8 with multiple active agent threads" },
      { label: "Resolved", value: "1,084", note: "40 landed this cycle" },
      { label: "Pending approvals", value: "4", note: "1 critical, 3 routine" },
    ],
    dashboard: {
      operatorQueue: [
        {
          tone: "yellow",
          title: "Approve quant paper-trading guardrail",
          summary: "Research, verification, and the operator packet are all ready. This is the only thing stopping promotion.",
          action: "Review approval",
          project: "Quant Alpha",
        },
        {
          tone: "red",
          title: "Hermes parity gap is contained but still unresolved",
          summary: "The fallback route kept the platform queue moving, but one lane is still operating in a degraded state.",
          action: "Inspect incident",
          project: "Platform Core",
        },
        {
          tone: "blue",
          title: "Promote strategy memo into canonical memory",
          summary: "The latest memo has source-backed evidence and can now become reusable guidance for both Growth and Governance.",
          action: "Promote memory",
          project: "Governance",
        },
      ],
      lanePressure: [
        { label: "Ready to launch", value: "13", note: "Mostly assigned to Codex and Claude Code" },
        { label: "Review queue", value: "18", note: "2 above SLA threshold" },
        { label: "Blocked", value: "9", note: "3 runtime, 3 policy, 3 handoff" },
        { label: "Resolved today", value: "40", note: "High throughput with contained risk" },
      ],
      landed: [
        {
          key: "OPS-97",
          title: "Ship runtime fallback routing contract v2",
          closed: "9m ago",
          outcome: "Merged and now active in execution",
          project: "Platform Core",
        },
        {
          key: "GTH-198",
          title: "Generate and review three outbound prospect briefs",
          closed: "26m ago",
          outcome: "Promoted into the weekly outbound pack",
          project: "Growth Loop",
        },
        {
          key: "MEM-29",
          title: "Promote operator scorecard into canonical memory",
          closed: "44m ago",
          outcome: "Now referenced by the daily briefing",
          project: "Governance",
        },
      ],
      history: [
        {
          lane: "research/guardrail-proof",
          tone: "green",
          text: "ResearchLead finished the paper-trading guardrail evidence pack",
          time: "4m ago",
          project: "Quant Alpha",
        },
        {
          lane: "review/operator-brief",
          tone: "yellow",
          text: "ChiefOfStaff turned the guardrail package into an operator approval packet",
          time: "6m ago",
          project: "Quant Alpha",
        },
        {
          lane: "runtime/hermes-fallback",
          tone: "red",
          text: "RuntimeBroker contained a Hermes parity regression and rerouted two jobs to Codex",
          time: "11m ago",
          project: "Platform Core",
        },
        {
          lane: "growth/prospect-pack",
          tone: "blue",
          text: "GrowthLead handed three completed briefs to ReviewDesk",
          time: "16m ago",
          project: "Growth Loop",
        },
        {
          lane: "memory/strategy-memo",
          tone: "blue",
          text: "MemoryCurator staged the latest strategy memo for canonical promotion",
          time: "24m ago",
          project: "Governance",
        },
      ],
    },
    inbox: {
      summary: [
        "1 critical approval",
        "3 routine approvals",
        "6 handoffs in flight",
        "9 blocked issues",
      ],
      queues: [
        {
          name: "Approvals",
          summary: "The smallest possible set of decisions that directly affect throughput.",
          items: [
            {
              tone: "yellow",
              title: "Approve quant paper-trading guardrail",
              summary: "All parallel research and verification branches are complete. The issue is waiting on a final operator decision.",
              impact: "Blocks the launch promotion path.",
              action: "Review now",
              project: "Quant Alpha",
            },
            {
              tone: "blue",
              title: "Promote strategy memo into canonical memory",
              summary: "This memo can now be reused by Growth, Governance, and the daily brief generator.",
              impact: "Improves future planning quality.",
              action: "Promote",
              project: "Governance",
            },
          ],
        },
        {
          name: "Runtime degradation",
          summary: "Contained incidents and pressure points that still deserve operator awareness.",
          items: [
            {
              tone: "red",
              title: "Hermes parity gap remains contained",
              summary: "Fallback routing is holding, but the platform queue is still carrying avoidable pressure.",
              impact: "3 platform issues remain blocked.",
              action: "Open incident",
              project: "Platform Core",
            },
            {
              tone: "yellow",
              title: "Review queue passed SLA in Growth Loop",
              summary: "Two issues have been waiting on Review for more than 20 minutes.",
              impact: "One campaign workstream is drifting.",
              action: "Open queue",
              project: "Growth Loop",
            },
          ],
        },
        {
          name: "Handoffs",
          summary: "Cross-lane transitions where autonomous work can silently stall if nobody is watching.",
          items: [
            {
              tone: "blue",
              title: "Promote strategy memo from active work into memory",
              summary: "The memo already has evidence and citations; only the final promotion remains.",
              impact: "Keeps future Growth plans grounded.",
              action: "Review memory",
              project: "Governance",
            },
            {
              tone: "yellow",
              title: "Quant approval packet waiting in decision lane",
              summary: "The issue is ready; MAAS is holding the promotion until the operator responds.",
              impact: "Launch queue remains paused.",
              action: "Open packet",
              project: "Quant Alpha",
            },
          ],
        },
        {
          name: "Contained / watchlist",
          summary: "Not urgent, but useful context for a fully working autonomous system.",
          items: [
            {
              tone: "green",
              title: "Fallback routing is carrying 2 jobs safely",
              summary: "Overflow moved from Hermes into Codex without dropping evidence or audit trail.",
              impact: "No action required unless load rises again.",
              action: "Open trace",
              project: "Platform Core",
            },
          ],
        },
      ],
    },
    issues: {
      counts: { open: 100, inProgress: 31, review: 18, blocked: 9, resolved: 1084 },
      open: [
        buildOpenIssue({
          id: "active-qnt-127",
          key: "QNT-127",
          title: "Approve quant paper-trading guardrail",
          project: "Quant Alpha",
          group: "decision",
          priority: "Critical",
          lead: "CEO",
          collaborators: ["ResearchLead", "ChiefOfStaff", "ReviewDesk"],
          statusLabel: "Awaiting operator decision",
          summary:
            "This issue already has research, verification, and the operator-facing packet. Nothing else in the launch path needs direct human involvement.",
          nextAction: "Review the guardrail packet and approve or request a narrower risk pass",
          updated: "4m ago",
          outputs: ["guardrail.diff", "backtest-summary.md", "operator-packet.md"],
          threads: [
            {
              branch: "research/guardrail-proof",
              agent: "ResearchLead",
              runtime: "Claude Code",
              state: "complete",
              note: "Prepared the final evidence pack with risk notes, backtests, and open assumptions.",
            },
            {
              branch: "verify/paper-trading-replay",
              agent: "CodexCoder",
              runtime: "Codex CLI",
              state: "complete",
              note: "Replay run finished without new runtime or artifact failures.",
            },
            {
              branch: "review/operator-brief",
              agent: "ChiefOfStaff",
              runtime: "Seraph",
              state: "awaiting review",
              note: "Prepared the approval packet and final diff for the operator.",
            },
          ],
          history: [
            { lane: "main", tone: "blue", text: "Issue promoted from the active research queue", time: "2h ago" },
            { lane: "research/guardrail-proof", tone: "green", text: "ResearchLead landed the final evidence pack", time: "31m ago" },
            { lane: "verify/paper-trading-replay", tone: "green", text: "CodexCoder replayed the paper-trading flow successfully", time: "19m ago" },
            { lane: "review/operator-brief", tone: "yellow", text: "ChiefOfStaff opened the approval packet", time: "4m ago" },
          ],
        }),
        buildOpenIssue({
          id: "active-gth-204",
          key: "GTH-204",
          title: "Create three new institutional prospect briefs",
          project: "Growth Loop",
          group: "inprogress",
          priority: "High",
          lead: "GrowthLead",
          collaborators: ["ReviewDesk", "ChiefOfStaff"],
          statusLabel: "3 parallel threads active",
          summary:
            "The growth workstream is running three briefs in parallel and only needs review capacity once they converge.",
          nextAction: "Monitor the Review SLA; no operator intervention needed yet",
          updated: "7m ago",
          outputs: ["brief-001.md", "brief-002.md"],
          threads: [
            {
              branch: "growth/prospect-apollo",
              agent: "GrowthLead",
              runtime: "OpenClaw",
              state: "writing",
              note: "Drafting the first institutional brief from this week's research findings.",
            },
            {
              branch: "growth/prospect-delta",
              agent: "GrowthLead",
              runtime: "OpenClaw",
              state: "writing",
              note: "Second brief in progress with updated scoring criteria.",
            },
            {
              branch: "review/brief-sla-watch",
              agent: "ReviewDesk",
              runtime: "Claude Code",
              state: "watching",
              note: "Prepared to ingest the three briefs as soon as they land.",
            },
          ],
          history: [
            { lane: "main", tone: "blue", text: "Growth workstream generated three prospect brief slots", time: "1h ago" },
            { lane: "growth/prospect-apollo", tone: "green", text: "First brief moved into drafting", time: "22m ago" },
            { lane: "growth/prospect-delta", tone: "green", text: "Second brief moved into drafting", time: "17m ago" },
            { lane: "review/brief-sla-watch", tone: "yellow", text: "ReviewDesk started watching the downstream queue", time: "7m ago" },
          ],
        }),
        buildOpenIssue({
          id: "active-ops-88",
          key: "OPS-88",
          title: "Fix Hermes interrupt parity before broader rollout",
          project: "Platform Core",
          group: "blocked",
          priority: "High",
          lead: "RuntimeBroker",
          collaborators: ["CodexCoder", "CTO"],
          statusLabel: "Contained incident with live fallback",
          summary:
            "MAAS is routing around the degraded lane safely, but the fix still matters because it keeps one execution pool below desired capacity.",
          nextAction: "Keep fallback active and ship the parity fix before widening Hermes usage",
          updated: "11m ago",
          outputs: ["hermes-trace.log", "fallback-contract.md"],
          threads: [
            {
              branch: "runtime/hermes-fix",
              agent: "CodexCoder",
              runtime: "Codex CLI",
              state: "implementing",
              note: "Working on a safer interrupt contract and replay test.",
            },
            {
              branch: "ops/fallback-routing",
              agent: "RuntimeBroker",
              runtime: "Hermes",
              state: "contained",
              note: "Overflow rerouted to Codex and Claude with audit trail intact.",
            },
          ],
          history: [
            { lane: "main", tone: "blue", text: "Platform Core flagged a Hermes parity regression", time: "3h ago" },
            { lane: "ops/fallback-routing", tone: "yellow", text: "Fallback routing activated for affected jobs", time: "44m ago" },
            { lane: "runtime/hermes-fix", tone: "red", text: "CodexCoder opened a repair branch with replay tests", time: "11m ago" },
          ],
        }),
        buildOpenIssue({
          id: "active-mem-32",
          key: "MEM-32",
          title: "Promote strategy memo into canonical memory",
          project: "Governance",
          group: "decision",
          priority: "Medium",
          lead: "MemoryCurator",
          collaborators: ["ChiefOfStaff"],
          statusLabel: "Decision-ready",
          summary:
            "The memo already has citations, review notes, and downstream references. Promotion would let Growth and Governance reuse it automatically.",
          nextAction: "Promote the memo or request one more evidence pass",
          updated: "9m ago",
          outputs: ["strategy-memo.md", "citations.json"],
          threads: [
            {
              branch: "memory/strategy-memo",
              agent: "MemoryCurator",
              runtime: "Seraph",
              state: "awaiting review",
              note: "Promotion packet is staged and linked to recent outputs.",
            },
            {
              branch: "review/memo-sanity",
              agent: "ChiefOfStaff",
              runtime: "Seraph",
              state: "complete",
              note: "Verified that the memo cites the current operator briefing and active issues.",
            },
          ],
          history: [
            { lane: "main", tone: "blue", text: "Memo promotion issue created from the weekly planning cycle", time: "1h ago" },
            { lane: "review/memo-sanity", tone: "green", text: "ChiefOfStaff completed the sanity review", time: "21m ago" },
            { lane: "memory/strategy-memo", tone: "yellow", text: "MemoryCurator staged the promotion for operator review", time: "9m ago" },
          ],
        }),
        buildOpenIssue({
          id: "active-gov-41",
          key: "GOV-41",
          title: "Review capital-exposure exception for one growth test",
          project: "Governance",
          group: "watch",
          priority: "Medium",
          lead: "CEO",
          collaborators: ["ChiefOfStaff"],
          statusLabel: "Needs a routine decision",
          summary:
            "The issue is low-risk and isolated, but MAAS surfaced it because it crosses the current policy envelope for one experiment.",
          nextAction: "Review the exception packet when the critical approval is done",
          updated: "16m ago",
          outputs: ["exception-packet.md"],
          threads: [
            {
              branch: "policy/capital-exception",
              agent: "ChiefOfStaff",
              runtime: "Seraph",
              state: "waiting",
              note: "Exception packet is ready and low-risk.",
            },
          ],
          history: [
            { lane: "main", tone: "blue", text: "Exception issue opened from governance checks", time: "47m ago" },
            { lane: "policy/capital-exception", tone: "yellow", text: "ChiefOfStaff staged the packet for later review", time: "16m ago" },
          ],
        }),
      ],
      resolved: [
        buildResolvedIssue({
          id: "active-res-1",
          key: "OPS-97",
          title: "Ship runtime fallback routing contract v2",
          project: "Platform Core",
          resolution: "Merged into the live runtime contract and now routes overflow automatically.",
          resolvedBy: "RuntimeBroker",
          closed: "9m ago",
          merged: "3 branches merged · 0 superseded",
          outputs: ["fallback-contract-v2.md", "runtime-routing.diff"],
          history: [
            { lane: "main", tone: "blue", text: "Fallback routing contract issue created from runtime parity work", time: "4h ago" },
            { lane: "runtime/codex-overflow", tone: "green", text: "Overflow route validated under load", time: "18m ago" },
            { lane: "runtime/merge-contract-v2", tone: "green", text: "RuntimeBroker promoted the new contract into production", time: "9m ago" },
          ],
        }),
        buildResolvedIssue({
          id: "active-res-2",
          key: "GTH-198",
          title: "Generate and review three outbound prospect briefs",
          project: "Growth Loop",
          resolution: "Merged into the current outbound packet and linked to the growth scorecard.",
          resolvedBy: "ReviewDesk",
          closed: "26m ago",
          merged: "3 branches merged · 1 rejected",
          outputs: ["prospect-pack.zip"],
          history: [
            { lane: "main", tone: "blue", text: "Brief pack issue created from the weekly growth cadence", time: "2h ago" },
            { lane: "growth/prospect-pack", tone: "green", text: "GrowthLead finished three briefs and handed them to review", time: "41m ago" },
            { lane: "review/pack-merge", tone: "green", text: "ReviewDesk merged the approved briefs into the outbound pack", time: "26m ago" },
          ],
        }),
        buildResolvedIssue({
          id: "active-res-3",
          key: "MEM-29",
          title: "Promote operator scorecard into canonical memory",
          project: "Governance",
          resolution: "Canonicalized and now referenced by the daily operator briefing.",
          resolvedBy: "MemoryCurator",
          closed: "44m ago",
          merged: "2 supporting notes merged",
          outputs: ["operator-scorecard.md"],
          history: [
            { lane: "main", tone: "blue", text: "Scorecard memory issue created from the weekly review cycle", time: "3h ago" },
            { lane: "memory/operator-scorecard", tone: "green", text: "MemoryCurator promoted the scorecard", time: "44m ago" },
          ],
        }),
      ],
    },
    topology: {
      capabilities: [
        { name: "Research pool", load: "4 active / 7 queued", note: "Quant and growth briefs in flight" },
        { name: "Execution pool", load: "5 active / 6 queued", note: "Mostly Codex CLI backed" },
        { name: "Review pool", load: "3 active / 18 waiting", note: "SLA pressure rising" },
        { name: "Memory pool", load: "2 active / 4 queued", note: "Promotions and operator brief reuse" },
      ],
      runtimes: [
        { name: "Codex CLI", status: "healthy", load: "6 running", note: "Primary execution lane" },
        { name: "Claude Code", status: "healthy", load: "4 running", note: "Research + review" },
        { name: "OpenClaw", status: "healthy", load: "2 running", note: "Growth lane" },
        { name: "Hermes", status: "degraded", load: "contained", note: "Fallback route active" },
        { name: "Seraph", status: "healthy", load: "3 running", note: "Decision packets + memory" },
      ],
      outputs: [
        { name: "Launch-ready issues", count: "13", note: "Ready for the next run cycle" },
        { name: "Review queue", count: "18", note: "2 above SLA" },
        { name: "Blocked queue", count: "9", note: "Mostly runtime and governance" },
        { name: "Resolved today", count: "40", note: "Operator intervention stayed low" },
      ],
      handoffs: [
        { title: "Research → Review", detail: "Three growth briefs and one quant guardrail are waiting on decision or review capacity.", tone: "yellow" },
        { title: "Execution → Review", detail: "Two replay runs finished and are waiting on evidence approval.", tone: "blue" },
        { title: "Runtime → Fallback", detail: "Hermes overflow is routing into Codex with audit trace intact.", tone: "red" },
      ],
      graph: {
        title: "Parallel work graph for QNT-127",
        summary: "One issue, three active threads, one operator gate, and one accepted output set.",
        branches: [
          { tone: "green", lane: "research/guardrail-proof", state: "complete", agent: "ResearchLead", note: "Risk note and backtest package landed." },
          { tone: "green", lane: "verify/paper-trading-replay", state: "complete", agent: "CodexCoder", note: "Replay run passed and linked outputs." },
          { tone: "yellow", lane: "review/operator-brief", state: "awaiting review", agent: "ChiefOfStaff", note: "Approval packet is waiting on the operator." },
        ],
      },
    },
  },
  resolving: {
    key: "resolving",
    label: "Resolving pressure",
    company: {
      name: "Northstar Research Group",
      subtitle: "Autonomous organization",
      objective: "Drain queues, land fixes, and promote the right learnings into memory",
      liveCount: 4,
      stage: "Recovery and consolidation",
      stageCopy:
        "The critical approval landed, throughput is recovering, and the organization is now closing the remaining incidents while preserving learnings for the next cycle.",
    },
    stats: [
      { label: "Open issues", value: "86", note: "19 in flight, 11 review, 4 blocked" },
      { label: "Issues in progress", value: "19", note: "Most queues are draining cleanly" },
      { label: "Resolved", value: "1,109", note: "25 landed this cycle" },
      { label: "Pending approvals", value: "1", note: "Only one low-risk exception remains" },
    ],
    dashboard: {
      operatorQueue: [
        {
          tone: "blue",
          title: "Promote recovery memo into canonical memory",
          summary: "The incident package is fully sourced and should become reusable policy for future runtime degradations.",
          action: "Promote memo",
          project: "Governance",
        },
        {
          tone: "yellow",
          title: "Review one remaining capital-exposure exception",
          summary: "The main launch blocker is gone. One lower-risk policy exception still needs a yes/no.",
          action: "Review decision",
          project: "Governance",
        },
      ],
      lanePressure: [
        { label: "Ready to launch", value: "7", note: "Healthy and draining" },
        { label: "Review queue", value: "11", note: "No SLA breach" },
        { label: "Blocked", value: "4", note: "Mostly long-tail incidents" },
        { label: "Resolved today", value: "25", note: "The critical path is now clear" },
      ],
      landed: [
        {
          key: "QNT-127",
          title: "Approve quant paper-trading guardrail",
          closed: "6m ago",
          outcome: "Launch queue unblocked and resumed automatically",
          project: "Quant Alpha",
        },
        {
          key: "OPS-88",
          title: "Route Hermes overflow safely through Codex",
          closed: "19m ago",
          outcome: "Queue pressure dropped immediately",
          project: "Platform Core",
        },
        {
          key: "MEM-32",
          title: "Promote strategy memo into canonical memory",
          closed: "38m ago",
          outcome: "Future cycles now reuse the resolved plan",
          project: "Governance",
        },
      ],
      history: [
        {
          lane: "review/guardrail-approval",
          tone: "green",
          text: "The critical quant guardrail was approved and the launch queue resumed automatically",
          time: "6m ago",
          project: "Quant Alpha",
        },
        {
          lane: "runtime/hermes-fallback",
          tone: "green",
          text: "Overflow routing stayed stable while the Hermes queue drained",
          time: "13m ago",
          project: "Platform Core",
        },
        {
          lane: "memory/recovery-memo",
          tone: "blue",
          text: "Recovery notes were staged for canonical promotion",
          time: "21m ago",
          project: "Governance",
        },
      ],
    },
    inbox: {
      summary: [
        "1 routine approval",
        "4 blocked issues",
        "Queues draining cleanly",
        "25 recently resolved",
      ],
      queues: [
        {
          name: "Approvals",
          summary: "Only low-risk operator decisions remain.",
          items: [
            {
              tone: "yellow",
              title: "Review one remaining capital-exposure exception",
              summary: "This is routine and isolated. The critical path is already clear.",
              impact: "Affects one growth experiment only.",
              action: "Review",
              project: "Governance",
            },
          ],
        },
        {
          name: "Runtime degradation",
          summary: "Incidents are mostly resolved; only long-tail items remain visible.",
          items: [
            {
              tone: "green",
              title: "Hermes overflow no longer blocking work",
              summary: "Fallback routing remains active, but the queue is now draining within target.",
              impact: "No immediate action needed.",
              action: "Open trace",
              project: "Platform Core",
            },
          ],
        },
        {
          name: "Handoffs",
          summary: "Most work is converging into review, memory, or resolved history.",
          items: [
            {
              tone: "blue",
              title: "Promote recovery memo into canonical memory",
              summary: "The memo can now become reusable guidance across future incident cycles.",
              impact: "Improves future recovery quality.",
              action: "Promote",
              project: "Governance",
            },
          ],
        },
      ],
    },
    issues: {
      counts: { open: 86, inProgress: 19, review: 11, blocked: 4, resolved: 1109 },
      open: [
        buildOpenIssue({
          id: "resolving-gov-41",
          key: "GOV-41",
          title: "Review one remaining capital-exposure exception",
          project: "Governance",
          group: "decision",
          priority: "Medium",
          lead: "CEO",
          collaborators: ["ChiefOfStaff"],
          statusLabel: "Routine operator decision",
          summary:
            "The critical launch path is already clear. This exception only affects one low-risk growth experiment and can be reviewed when convenient.",
          nextAction: "Review and either approve or close the exception",
          updated: "9m ago",
          outputs: ["exception-packet.md"],
          threads: [
            {
              branch: "policy/capital-exception",
              agent: "ChiefOfStaff",
              runtime: "Seraph",
              state: "awaiting review",
              note: "Routine packet ready with no remaining unknowns.",
            },
          ],
          history: [
            { lane: "main", tone: "blue", text: "Exception issue survived the recovery pass", time: "37m ago" },
            { lane: "policy/capital-exception", tone: "yellow", text: "ChiefOfStaff refreshed the decision packet", time: "9m ago" },
          ],
        }),
        buildOpenIssue({
          id: "resolving-mem-41",
          key: "MEM-41",
          title: "Promote recovery memo into canonical memory",
          project: "Governance",
          group: "decision",
          priority: "Medium",
          lead: "MemoryCurator",
          collaborators: ["ChiefOfStaff"],
          statusLabel: "Ready for promotion",
          summary:
            "The incident package is fully sourced and should become reusable memory so future degradations resolve faster.",
          nextAction: "Promote the memo into canonical memory",
          updated: "12m ago",
          outputs: ["recovery-memo.md", "incident-summary.json"],
          threads: [
            {
              branch: "memory/recovery-memo",
              agent: "MemoryCurator",
              runtime: "Seraph",
              state: "awaiting review",
              note: "Promotion packet is staged with linked outputs and incident context.",
            },
            {
              branch: "review/memo-sanity",
              agent: "ChiefOfStaff",
              runtime: "Seraph",
              state: "complete",
              note: "Verified that the memo lines up with the final incident resolution trace.",
            },
          ],
          history: [
            { lane: "main", tone: "blue", text: "Recovery memo promotion issue created", time: "54m ago" },
            { lane: "review/memo-sanity", tone: "green", text: "Sanity review complete", time: "18m ago" },
            { lane: "memory/recovery-memo", tone: "yellow", text: "Promotion packet waiting on the operator", time: "12m ago" },
          ],
        }),
        buildOpenIssue({
          id: "resolving-gth-211",
          key: "GTH-211",
          title: "Rerun the paused outbound experiment with the cleared queue",
          project: "Growth Loop",
          group: "inprogress",
          priority: "Medium",
          lead: "GrowthLead",
          collaborators: ["ReviewDesk"],
          statusLabel: "Back online",
          summary:
            "The main bottleneck is gone. Growth is resuming one paused experiment and should recover naturally if the queue stays healthy.",
          nextAction: "No operator action needed unless the review queue slows again",
          updated: "14m ago",
          outputs: ["relaunch-plan.md"],
          threads: [
            {
              branch: "growth/relaunch-pass",
              agent: "GrowthLead",
              runtime: "OpenClaw",
              state: "running",
              note: "Rebuilding the outbound sequence with the cleared approvals.",
            },
            {
              branch: "review/queue-watch",
              agent: "ReviewDesk",
              runtime: "Claude Code",
              state: "watching",
              note: "Monitoring that the review lane stays within SLA.",
            },
          ],
          history: [
            { lane: "main", tone: "blue", text: "Growth experiment was resumed after the critical approval landed", time: "22m ago" },
            { lane: "growth/relaunch-pass", tone: "green", text: "GrowthLead reopened the workstream", time: "14m ago" },
          ],
        }),
        buildOpenIssue({
          id: "resolving-ops-104",
          key: "OPS-104",
          title: "Close the last Hermes parity follow-up",
          project: "Platform Core",
          group: "blocked",
          priority: "Medium",
          lead: "RuntimeBroker",
          collaborators: ["CodexCoder"],
          statusLabel: "Long-tail blocker",
          summary:
            "The system is already routing safely. This is the last platform tail item that still needs cleanup before Hermes can be marked fully healthy again.",
          nextAction: "Finish the cleanup branch and keep overflow on Codex until then",
          updated: "17m ago",
          outputs: ["parity-cleanup.diff"],
          threads: [
            {
              branch: "runtime/cleanup-tail",
              agent: "CodexCoder",
              runtime: "Codex CLI",
              state: "implementing",
              note: "Cleaning the last edge case from the parity fix.",
            },
            {
              branch: "ops/fallback-routing",
              agent: "RuntimeBroker",
              runtime: "Hermes",
              state: "healthy enough",
              note: "Overflow still routes safely and keeps the queue moving.",
            },
          ],
          history: [
            { lane: "main", tone: "blue", text: "The critical incident resolved, leaving one parity follow-up", time: "49m ago" },
            { lane: "runtime/cleanup-tail", tone: "red", text: "CodexCoder opened the final cleanup branch", time: "17m ago" },
          ],
        }),
      ],
      resolved: [
        buildResolvedIssue({
          id: "resolving-res-1",
          key: "QNT-127",
          title: "Approve quant paper-trading guardrail",
          project: "Quant Alpha",
          resolution: "Approved and automatically promoted into the live launch sequence.",
          resolvedBy: "Operator",
          closed: "6m ago",
          merged: "3 evidence branches accepted",
          outputs: ["operator-packet.md", "guardrail.diff", "backtest-summary.md"],
          history: [
            { lane: "research/guardrail-proof", tone: "green", text: "Evidence pack accepted", time: "31m ago" },
            { lane: "verify/paper-trading-replay", tone: "green", text: "Replay run accepted", time: "19m ago" },
            { lane: "review/guardrail-approval", tone: "green", text: "Operator approved the guardrail and launched the queue", time: "6m ago" },
          ],
        }),
        buildResolvedIssue({
          id: "resolving-res-2",
          key: "OPS-88",
          title: "Route Hermes overflow safely through Codex",
          project: "Platform Core",
          resolution: "Queue pressure dropped and the degraded lane stopped blocking work.",
          resolvedBy: "RuntimeBroker",
          closed: "19m ago",
          merged: "2 routing branches merged",
          outputs: ["runtime-routing.diff", "overflow-trace.log"],
          history: [
            { lane: "ops/fallback-routing", tone: "green", text: "Overflow route proved stable under pressure", time: "24m ago" },
            { lane: "runtime/merge-fallback", tone: "green", text: "RuntimeBroker marked the queue healthy enough to continue", time: "19m ago" },
          ],
        }),
        buildResolvedIssue({
          id: "resolving-res-3",
          key: "MEM-32",
          title: "Promote strategy memo into canonical memory",
          project: "Governance",
          resolution: "Promoted and now referenced by future planning and the operator brief.",
          resolvedBy: "MemoryCurator",
          closed: "38m ago",
          merged: "1 memo promoted · 2 citations retained",
          outputs: ["strategy-memo.md", "citations.json"],
          history: [
            { lane: "review/memo-sanity", tone: "green", text: "Review sanity pass accepted", time: "52m ago" },
            { lane: "memory/strategy-memo", tone: "green", text: "MemoryCurator promoted the memo", time: "38m ago" },
          ],
        }),
      ],
    },
    topology: {
      capabilities: [
        { name: "Research pool", load: "2 active / 3 queued", note: "Mostly relaunch and cleanup work" },
        { name: "Execution pool", load: "3 active / 2 queued", note: "Lower pressure after the critical approval" },
        { name: "Review pool", load: "2 active / 11 waiting", note: "Healthy and draining" },
        { name: "Memory pool", load: "2 active / 3 queued", note: "Promotions and recovery notes" },
      ],
      runtimes: [
        { name: "Codex CLI", status: "healthy", load: "4 running", note: "Carrying most execution" },
        { name: "Claude Code", status: "healthy", load: "2 running", note: "Review and research support" },
        { name: "OpenClaw", status: "healthy", load: "1 running", note: "Growth relaunch" },
        { name: "Hermes", status: "recovering", load: "light", note: "Fallback still active for safety" },
        { name: "Seraph", status: "healthy", load: "2 running", note: "Memory and decisions" },
      ],
      outputs: [
        { name: "Ready to launch", count: "7", note: "Mostly routine work" },
        { name: "Review queue", count: "11", note: "No SLA breach" },
        { name: "Blocked queue", count: "4", note: "Long-tail cleanup only" },
        { name: "Resolved today", count: "25", note: "Critical path already cleared" },
      ],
      handoffs: [
        { title: "Approval → Execution", detail: "Quant Alpha resumed automatically after the guardrail was approved.", tone: "green" },
        { title: "Incident → Memory", detail: "Recovery memo is ready to become reusable guidance.", tone: "blue" },
        { title: "Runtime → Healthy", detail: "Hermes is recovering while Codex still carries overflow.", tone: "yellow" },
      ],
      graph: {
        title: "Resolution graph for the launch path",
        summary: "Critical approval landed, one runtime tail remains, memory promotion now follows.",
        branches: [
          { tone: "green", lane: "review/guardrail-approval", state: "merged", agent: "Operator", note: "Approval accepted and launch resumed." },
          { tone: "yellow", lane: "runtime/cleanup-tail", state: "in progress", agent: "CodexCoder", note: "Final parity cleanup is still running." },
          { tone: "blue", lane: "memory/recovery-memo", state: "awaiting review", agent: "MemoryCurator", note: "Recovery learnings ready for promotion." },
        ],
      },
    },
  },
};

const agentDetails = {
  startup: {
    "agent-ceo": {
      latestRun: "Watching the first runtime and plan approvals. Nothing should launch until both are cleared.",
      metrics: [
        { label: "Open approvals", value: "2" },
        { label: "Direct blockers", value: "2" },
        { label: "Resolved today", value: "3" },
        { label: "Success rate", value: "100%" },
      ],
      currentAssignments: ["Approve initial runtime policy", "Approve first-wave execution plan"],
      recentLanded: ["Select Codex CLI as initial execution lane", "Canonicalize baseline risk memo"],
      handoffs: ["Planning → Review packet waiting", "Runtime → Execution gate waiting"],
    },
    "agent-chief-of-staff": {
      latestRun: "Packaging the initial plan and runtime choices into one operator-ready packet.",
      metrics: [
        { label: "Active threads", value: "2" },
        { label: "Decision packets", value: "3" },
        { label: "Resolved today", value: "5" },
        { label: "Success rate", value: "100%" },
      ],
      currentAssignments: ["Prepare first-wave approval packet", "Refresh startup operator briefing"],
      recentLanded: ["Link startup notes into the briefing", "Stage memory promotion packet"],
      handoffs: ["Planning → Operator", "Memory → Canonical queue"],
    },
    "agent-research": {
      latestRun: "Decomposed the quant objective and packaged the first research wave.",
      metrics: [
        { label: "Active threads", value: "2" },
        { label: "Open issues", value: "4" },
        { label: "Resolved today", value: "2" },
        { label: "Success rate", value: "100%" },
      ],
      currentAssignments: ["Prepare first-wave quant issues", "Link evidence into the launch pack"],
      recentLanded: ["Assemble quant research backlog", "Validate references for startup brief"],
      handoffs: ["Research → Review", "Research → Memory"],
    },
  },
  active: {
    "agent-ceo": {
      latestRun: "Waiting on one critical approval and two lower-risk decisions. Everything else can keep moving autonomously.",
      metrics: [
        { label: "Open approvals", value: "4" },
        { label: "Direct blockers", value: "1" },
        { label: "Resolved today", value: "9" },
        { label: "Success rate", value: "100%" },
      ],
      currentAssignments: ["Approve quant paper-trading guardrail", "Review capital-exposure exception"],
      recentLanded: ["Approved runtime fallback routing v2", "Released outbound intelligence pack"],
      handoffs: ["Review → Execution", "Memory → Canonical queue"],
    },
    "agent-chief-of-staff": {
      latestRun: "Maintaining the decision queue and converting agent outputs into operator-ready packets.",
      metrics: [
        { label: "Active threads", value: "4" },
        { label: "Decision packets", value: "4" },
        { label: "Resolved today", value: "8" },
        { label: "Success rate", value: "98%" },
      ],
      currentAssignments: ["Finalize quant approval packet", "Sanity-check strategy memo promotion"],
      recentLanded: ["Publish daily operator briefing", "Link runtime incident into watchlist"],
      handoffs: ["Research → Operator", "Execution → Review", "Memory → Promotion"],
    },
    "agent-research": {
      latestRun: "Research lane is healthy. The main quant approval packet is complete and the next briefs are already in motion.",
      metrics: [
        { label: "Active threads", value: "5" },
        { label: "Open issues", value: "11" },
        { label: "Resolved today", value: "6" },
        { label: "Success rate", value: "97%" },
      ],
      currentAssignments: ["Guardrail follow-up evidence", "Growth scoring refresh"],
      recentLanded: ["Quant guardrail proof", "Growth brief citations"],
      handoffs: ["Research → Review", "Research → Memory"],
    },
    "agent-growth": {
      latestRun: "Three outbound briefs are running in parallel and review capacity is the only real pressure point.",
      metrics: [
        { label: "Active threads", value: "3" },
        { label: "Open issues", value: "8" },
        { label: "Resolved today", value: "4" },
        { label: "Success rate", value: "96%" },
      ],
      currentAssignments: ["Create three new prospect briefs", "Refresh outbound scorecard"],
      recentLanded: ["Merge prospect pack into weekly outbound packet", "Refresh prospect targeting notes"],
      handoffs: ["Growth → Review", "Growth → Memory"],
    },
    "agent-runtime": {
      latestRun: "Containment is holding. Hermes is still degraded, but fallback routing kept the platform queue moving safely.",
      metrics: [
        { label: "Active threads", value: "2" },
        { label: "Open incidents", value: "1" },
        { label: "Resolved today", value: "3" },
        { label: "Success rate", value: "93%" },
      ],
      currentAssignments: ["Route around Hermes parity gap", "Review queue pressure on runtime lanes"],
      recentLanded: ["Promote fallback routing contract v2", "Recover one blocked execution lane"],
      handoffs: ["Runtime → Fallback", "Runtime → Review"],
    },
  },
  resolving: {
    "agent-ceo": {
      latestRun: "The critical path is clear. Only one routine governance decision remains in queue.",
      metrics: [
        { label: "Open approvals", value: "1" },
        { label: "Direct blockers", value: "0" },
        { label: "Resolved today", value: "11" },
        { label: "Success rate", value: "100%" },
      ],
      currentAssignments: ["Review one remaining capital-exposure exception"],
      recentLanded: ["Approve quant paper-trading guardrail", "Resume launch queue automatically"],
      handoffs: ["Approval → Execution complete", "Memory → Promotion pending"],
    },
    "agent-chief-of-staff": {
      latestRun: "Most operator-facing work is now in cleanup and memory promotion.",
      metrics: [
        { label: "Active threads", value: "2" },
        { label: "Decision packets", value: "2" },
        { label: "Resolved today", value: "6" },
        { label: "Success rate", value: "99%" },
      ],
      currentAssignments: ["Refresh the last policy exception packet", "Review the recovery memo promotion"],
      recentLanded: ["Close the quant approval queue", "Publish recovery summary"],
      handoffs: ["Incident → Memory", "Governance → Archive"],
    },
    "agent-research": {
      latestRun: "Quant research is healthy again and mostly waiting on downstream relaunch results.",
      metrics: [
        { label: "Active threads", value: "2" },
        { label: "Open issues", value: "4" },
        { label: "Resolved today", value: "5" },
        { label: "Success rate", value: "98%" },
      ],
      currentAssignments: ["Watch relaunch sequence", "Refresh next research backlog"],
      recentLanded: ["Guardrail proof accepted", "Weekly research brief refreshed"],
      handoffs: ["Research → Execution", "Research → Memory"],
    },
    "agent-runtime": {
      latestRun: "Runtime pressure is mostly gone. The last Hermes cleanup branch is still open, but overflow is safe.",
      metrics: [
        { label: "Active threads", value: "1" },
        { label: "Open incidents", value: "1" },
        { label: "Resolved today", value: "5" },
        { label: "Success rate", value: "96%" },
      ],
      currentAssignments: ["Close the last Hermes parity follow-up"],
      recentLanded: ["Overflow rerouted safely through Codex", "Queue pressure normalized"],
      handoffs: ["Runtime → Healthy", "Incident → Memory"],
    },
  },
};

const state = {
  scenario: "active",
  view: "dashboard",
  selectedProjectId: "all",
  selectedIssueId: "active-qnt-127",
  selectedResolvedIssueId: "active-res-1",
  selectedAgentId: "agent-research",
  selectedGoalId: "goal-launch",
  issueTab: "open",
};

const groupLabels = [
  ["decision", "Needs decision"],
  ["inprogress", "In flight"],
  ["blocked", "Blocked"],
  ["watch", "Watchlist"],
];

function currentScenario() {
  return scenarios[state.scenario];
}

function projectName(projectId) {
  return projects.find((project) => project.id === projectId)?.name ?? "All missions";
}

function projectMatches(project) {
  if (state.selectedProjectId === "all") return true;
  return project === projectName(state.selectedProjectId);
}

function filteredOpenIssues() {
  return currentScenario().issues.open.filter((issue) => projectMatches(issue.project));
}

function filteredResolvedIssues() {
  return currentScenario().issues.resolved.filter((issue) => projectMatches(issue.project));
}

function issueCounts() {
  const open = filteredOpenIssues();
  return {
    open: open.length,
    decision: open.filter((issue) => issue.group === "decision").length,
    inprogress: open.filter((issue) => issue.group === "inprogress").length,
    blocked: open.filter((issue) => issue.group === "blocked").length,
    resolved: filteredResolvedIssues().length,
  };
}

function selectedIssue() {
  const pool = state.issueTab === "resolved" ? filteredResolvedIssues() : filteredOpenIssues();
  const selectedKey = state.issueTab === "resolved" ? state.selectedResolvedIssueId : state.selectedIssueId;
  return pool.find((issue) => issue.id === selectedKey) ?? pool[0] ?? null;
}

function selectedAgent() {
  return agents.find((agent) => agent.id === state.selectedAgentId) ?? agents[0];
}

function selectedGoal() {
  return goals.find((goal) => goal.id === state.selectedGoalId) ?? goals[0];
}

function selectedAgentDetail() {
  const scenarioDetails = agentDetails[state.scenario] ?? {};
  return (
    scenarioDetails[state.selectedAgentId] ?? {
      latestRun: "This agent is healthy but does not have a custom scenario card yet.",
      metrics: [
        { label: "Active threads", value: "1" },
        { label: "Open issues", value: "2" },
        { label: "Resolved today", value: "1" },
        { label: "Success rate", value: "100%" },
      ],
      currentAssignments: ["Keep the lane healthy"],
      recentLanded: ["No notable landed work yet"],
      handoffs: ["No major handoffs in queue"],
    }
  );
}

function ensureSelections() {
  const open = filteredOpenIssues();
  const resolved = filteredResolvedIssues();
  if (!open.some((issue) => issue.id === state.selectedIssueId)) {
    state.selectedIssueId = open[0]?.id ?? "";
  }
  if (!resolved.some((issue) => issue.id === state.selectedResolvedIssueId)) {
    state.selectedResolvedIssueId = resolved[0]?.id ?? "";
  }
}

function toneClass(tone) {
  return `tone-${tone ?? "blue"}`;
}

function liveAgents() {
  return agents.filter((agent) => agent.status === "live").slice(0, 6);
}

function renderHeader(title, subtitle, actions = "") {
  return `
    <header class="page-header">
      <div>
        <div class="page-eyebrow">${title.toUpperCase()}</div>
        <h1>${title}</h1>
        <div class="page-subtitle">${subtitle}</div>
      </div>
      ${actions ? `<div class="header-actions">${actions}</div>` : ""}
    </header>
  `;
}

function renderScenarioSwitcher() {
  return `
    <div class="scenario-switcher">
      ${Object.values(scenarios)
        .map(
          (scenario) => `
            <button class="scenario-button ${state.scenario === scenario.key ? "is-active" : ""}" data-scenario="${scenario.key}">
              ${scenario.label}
            </button>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderSidebar() {
  const scenario = currentScenario();
  const counts = issueCounts();
  return `
    <aside class="sidebar">
      <div class="brand-row">
        <div class="paperclip-mark">◜</div>
        <strong>MAAS</strong>
      </div>

      <div class="avatar">${scenario.company.name[0]}</div>

      <div class="sidebar-section">
        <button class="primary-action">New Mission</button>
        <nav class="main-nav">
          <button class="nav-item ${state.view === "dashboard" ? "is-active" : ""}" data-view="dashboard">
            <span>Dashboard</span>
            <span>${scenario.company.liveCount} live</span>
          </button>
          <button class="nav-item ${state.view === "inbox" ? "is-active" : ""}" data-view="inbox">
            <span>Inbox</span>
            <span>${currentScenario().inbox.queues.reduce((sum, queue) => sum + queue.items.filter((item) => projectMatches(item.project)).length, 0)}</span>
          </button>
          <button class="nav-item ${state.view === "issues" ? "is-active" : ""}" data-view="issues">
            <span>Issues</span>
            <span>${state.selectedProjectId === "all" ? currentScenario().issues.counts.open : counts.open}</span>
          </button>
          <button class="nav-item ${state.view === "goals" ? "is-active" : ""}" data-view="goals">
            <span>Goals</span>
          </button>
          <button class="nav-item ${state.view === "agents" ? "is-active" : ""}" data-view="agents">
            <span>Agents</span>
            <span>${liveAgents().length} live</span>
          </button>
          <button class="nav-item ${state.view === "topology" ? "is-active" : ""}" data-view="topology">
            <span>Topology</span>
          </button>
        </nav>
      </div>

      <div class="sidebar-section">
        <div class="section-label">Projects</div>
        <div class="project-list">
          ${projects
            .map((project) => {
              const projectCount =
                project.id === "all"
                  ? currentScenario().issues.counts.open
                  : currentScenario().issues.open.filter((issue) => issue.project === project.name).length;
              return `
                <button class="project-item ${state.selectedProjectId === project.id ? "is-active" : ""}" data-project="${project.id}">
                  <span class="project-meta">
                    <span class="project-dot ${toneClass(project.tone)}"></span>
                    <span>${project.name}</span>
                  </span>
                  <span class="project-count">${projectCount}</span>
                </button>
              `;
            })
            .join("")}
        </div>
      </div>

      <div class="sidebar-section">
        <div class="section-label">Live agents</div>
        <div class="agent-list-nav">
          ${liveAgents()
            .map(
              (agent) => `
                <button class="agent-nav-item ${state.view === "agents" && state.selectedAgentId === agent.id ? "is-active" : ""}" data-view="agents" data-agent="${agent.id}">
                  <span>${agent.name}</span>
                  <span class="live-badge">${agent.runtime}</span>
                </button>
              `,
            )
            .join("")}
        </div>
      </div>
    </aside>
  `;
}

function renderStatGrid() {
  return `
    <section class="stat-grid">
      ${currentScenario().stats
        .map(
          (stat) => `
            <article class="stat-card">
              <div class="stat-value">${stat.value}</div>
              <div class="stat-label">${stat.label}</div>
              <div class="stat-note">${stat.note}</div>
            </article>
          `,
        )
        .join("")}
    </section>
  `;
}

function filterDashboardItems(items) {
  return items.filter((item) => !item.project || projectMatches(item.project));
}

function renderDashboard() {
  const scenario = currentScenario();
  const operatorQueue = filterDashboardItems(scenario.dashboard.operatorQueue);
  const lanePressure = scenario.dashboard.lanePressure;
  const landed = filterDashboardItems(scenario.dashboard.landed);
  const history = filterDashboardItems(scenario.dashboard.history);

  return `
    <section class="page-shell">
      ${renderHeader("Dashboard", `${scenario.company.objective} · ${projectName(state.selectedProjectId)}`)}
      ${renderScenarioSwitcher()}

      <article class="stage-banner">
        <div>
          <div class="stage-label">${scenario.company.stage}</div>
          <div class="stage-copy">${scenario.company.stageCopy}</div>
        </div>
        <span class="scenario-pill">${scenario.label}</span>
      </article>

      ${renderStatGrid()}

      <section class="dashboard-grid">
        <article class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">Operator queue</div>
              <div class="panel-copy">The smallest set of human decisions that actually change throughput.</div>
            </div>
          </div>
          <div class="stack-list">
            ${operatorQueue
              .map(
                (item) => `
                  <div class="action-card">
                    <div class="action-main">
                      <div class="row-title"><span class="issue-key-dot ${toneClass(item.tone)}"></span>${item.title}</div>
                      <div class="row-copy">${item.summary}</div>
                    </div>
                    <button class="row-action">${item.action}</button>
                  </div>
                `,
              )
              .join("")}
          </div>
        </article>

        <article class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">Pipeline pressure</div>
              <div class="panel-copy">Representative queue health for the current scenario.</div>
            </div>
          </div>
          <div class="mini-stack">
            ${lanePressure
              .map(
                (item) => `
                  <div class="mini-row">
                    <div>
                      <div class="row-title">${item.label}</div>
                      <div class="row-copy">${item.note}</div>
                    </div>
                    <div class="metric-number">${item.value}</div>
                  </div>
                `,
              )
              .join("")}
          </div>
        </article>

        <article class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">Recently landed</div>
              <div class="panel-copy">Resolved work that actually changed the system.</div>
            </div>
          </div>
          <div class="stack-list">
            ${landed
              .map(
                (item) => `
                  <div class="landed-row">
                    <div class="row-title">${item.key} · ${item.title}</div>
                    <div class="row-copy">${item.outcome}</div>
                    <div class="meta-inline">
                      <span>${item.project}</span>
                      <span>${item.closed}</span>
                    </div>
                  </div>
                `,
              )
              .join("")}
          </div>
        </article>
      </section>

      <article class="panel timeline-panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">Execution history</div>
            <div class="panel-copy">Git-like branch and merge events, not a flat log dump.</div>
          </div>
        </div>
        <div class="history-list">
          ${history
            .map(
              (event) => `
                <div class="history-row">
                  <div class="history-track">
                    <span class="history-dot ${toneClass(event.tone)}"></span>
                  </div>
                  <div class="history-main">
                    <div class="meta-inline">
                      <span class="branch-chip">${event.lane}</span>
                      <span>${event.project}</span>
                    </div>
                    <div class="row-title">${event.text}</div>
                  </div>
                  <div class="issue-date">${event.time}</div>
                </div>
              `,
            )
            .join("")}
        </div>
      </article>
    </section>
  `;
}

function renderInbox() {
  const inbox = currentScenario().inbox;
  return `
    <section class="page-shell">
      ${renderHeader("Inbox", `Decisions, incidents, handoffs, and watchlist items · ${projectName(state.selectedProjectId)}`)}
      ${renderScenarioSwitcher()}
      <div class="summary-row">
        ${inbox.summary.map((item) => `<span class="summary-chip">${item}</span>`).join("")}
      </div>
      <section class="queue-grid">
        ${inbox.queues
          .map((queue) => {
            const rows = queue.items.filter((item) => projectMatches(item.project));
            return `
              <article class="panel">
                <div class="panel-head">
                  <div>
                    <div class="panel-title">${queue.name}</div>
                    <div class="panel-copy">${queue.summary}</div>
                  </div>
                  <span class="queue-count">${rows.length}</span>
                </div>
                <div class="stack-list">
                  ${rows
                    .map(
                      (item) => `
                        <div class="queue-item">
                          <div class="row-title"><span class="issue-key-dot ${toneClass(item.tone)}"></span>${item.title}</div>
                          <div class="row-copy">${item.summary}</div>
                          <div class="meta-inline">
                            <span>${item.project}</span>
                            <span>${item.impact}</span>
                          </div>
                          <button class="row-action">${item.action}</button>
                        </div>
                      `,
                    )
                    .join("")}
                </div>
              </article>
            `;
          })
          .join("")}
      </section>
    </section>
  `;
}

function renderIssueTabs() {
  const counts = issueCounts();
  const tabs = [
    { id: "open", label: `Open ${state.selectedProjectId === "all" ? currentScenario().issues.counts.open : counts.open}` },
    { id: "resolved", label: `Resolved ${state.selectedProjectId === "all" ? currentScenario().issues.counts.resolved : counts.resolved}` },
  ];
  return `
    <div class="tab-switcher">
      ${tabs
        .map(
          (tab) => `
            <button class="tab-button ${state.issueTab === tab.id ? "is-active" : ""}" data-issue-tab="${tab.id}">
              ${tab.label}
            </button>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderIssueListRows(rows, resolved = false) {
  if (!rows.length) {
    return `<div class="empty-state">No representative rows for this project in the current scenario.</div>`;
  }
  return rows
    .map((issue) => {
      const selected = selectedIssue()?.id === issue.id;
      const selectAttr = resolved ? `data-resolved-issue="${issue.id}"` : `data-issue="${issue.id}"`;
      const rightLabel = resolved ? issue.closed : issue.updated;
      const nextLine = resolved ? issue.resolution : `Next: ${issue.nextAction}`;
      return `
        <button class="issue-list-row ${selected ? "is-active" : ""}" ${selectAttr}>
          <div class="issue-row-main">
            <div class="row-title"><span class="issue-key-dot ${toneClass(resolved ? "green" : issue.priority === "Critical" ? "yellow" : issue.group === "blocked" ? "red" : "blue")}"></span>${issue.key} · ${issue.title}</div>
            <div class="meta-inline">
              <span>${issue.project}</span>
              <span>${issue.lead ?? issue.resolvedBy}</span>
              ${
                issue.collaborators?.length
                  ? `<span>+${issue.collaborators.length} agents</span>`
                  : ""
              }
              ${issue.statusLabel ? `<span>${issue.statusLabel}</span>` : ""}
            </div>
            <div class="row-copy">${nextLine}</div>
          </div>
          <div class="issue-date">${rightLabel}</div>
        </button>
      `;
    })
    .join("");
}

function renderIssueDetailPanel(issue) {
  if (!issue) {
    return `<article class="panel issue-detail-panel"><div class="empty-state">No issue selected.</div></article>`;
  }
  const isResolved = issue.kind === "resolved";
  return `
    <article class="panel issue-detail-panel">
      <div class="detail-header">
        <div>
          <div class="meta-inline">
            <span class="branch-chip">${issue.key}</span>
            <span>${issue.project}</span>
            <span>${isResolved ? "Resolved" : issue.priority}</span>
          </div>
          <h2>${issue.title}</h2>
          <p>${isResolved ? issue.resolution : issue.summary}</p>
        </div>
        <div class="detail-status ${isResolved ? "resolved" : ""}">
          ${isResolved ? issue.closed : issue.statusLabel}
        </div>
      </div>

      <div class="detail-grid">
        <section class="detail-card recommendation-card">
          <div class="panel-title">${isResolved ? "Resolution" : "Recommended next action"}</div>
          <div class="detail-copy">${isResolved ? issue.resolution : issue.nextAction}</div>
          <div class="meta-inline">
            <span>${isResolved ? `Resolved by ${issue.resolvedBy}` : `Lead ${issue.lead}`}</span>
            ${issue.collaborators?.length ? `<span>${issue.collaborators.length + 1} agents involved</span>` : ""}
            ${issue.merged ? `<span>${issue.merged}</span>` : ""}
          </div>
        </section>

        <section class="detail-card">
          <div class="panel-title">${isResolved ? "Accepted outputs" : "Linked outputs"}</div>
          <div class="chip-cloud">
            ${issue.outputs.map((output) => `<span class="output-chip">${output}</span>`).join("")}
          </div>
        </section>
      </div>

      ${
        !isResolved
          ? `
            <section class="detail-card">
              <div class="panel-title">Active threads</div>
              <div class="thread-list">
                ${issue.threads
                  .map(
                    (thread) => `
                      <div class="thread-card">
                        <div class="meta-inline">
                          <span class="branch-chip">${thread.branch}</span>
                          <span>${thread.agent}</span>
                          <span>${thread.runtime}</span>
                        </div>
                        <div class="row-title">${thread.state}</div>
                        <div class="row-copy">${thread.note}</div>
                      </div>
                    `,
                  )
                  .join("")}
              </div>
            </section>
          `
          : ""
      }

      <section class="detail-card">
        <div class="panel-title">Execution history</div>
        <div class="history-list dense">
          ${issue.history
            .map(
              (event) => `
                <div class="history-row">
                  <div class="history-track">
                    <span class="history-dot ${toneClass(event.tone)}"></span>
                  </div>
                  <div class="history-main">
                    <div class="meta-inline">
                      <span class="branch-chip">${event.lane}</span>
                    </div>
                    <div class="row-title">${event.text}</div>
                  </div>
                  <div class="issue-date">${event.time}</div>
                </div>
              `,
            )
            .join("")}
        </div>
      </section>
    </article>
  `;
}

function renderIssues() {
  const open = filteredOpenIssues();
  const resolved = filteredResolvedIssues();
  const selected = selectedIssue();
  return `
    <section class="page-shell">
      ${renderHeader(
        "Issues",
        `${projectName(state.selectedProjectId)} · ${state.selectedProjectId === "all" ? "100 active issues in the pipeline · 1,000+ resolved" : "Representative issue list for the selected mission"}`,
        `<button class="header-button">New issue</button><button class="header-button">Filters</button><button class="header-button">Sort</button>`,
      )}
      ${renderScenarioSwitcher()}
      ${renderIssueTabs()}
      <section class="issues-layout">
        <article class="panel issue-list-panel">
          ${
            state.issueTab === "open"
              ? groupLabels
                  .map(([group, label]) => {
                    const rows = open.filter((issue) => issue.group === group);
                    if (!rows.length) return "";
                    return `
                      <section class="issue-group">
                        <div class="group-heading">${label}<span class="group-count">${rows.length}</span></div>
                        ${renderIssueListRows(rows)}
                      </section>
                    `;
                  })
                  .join("")
              : `
                <section class="issue-group">
                  <div class="group-heading">Resolved and landed<span class="group-count">${resolved.length}</span></div>
                  ${renderIssueListRows(resolved, true)}
                </section>
              `
          }
        </article>
        ${renderIssueDetailPanel(selected)}
      </section>
    </section>
  `;
}

function renderGoals() {
  const goal = selectedGoal();
  const linkedIssues = [...filteredOpenIssues(), ...filteredResolvedIssues()].filter((issue) =>
    goal.linkedIssues.includes(issue.key),
  );
  return `
    <section class="page-shell">
      ${renderHeader("Goals", `Strategic objectives and their linked issue flow · ${projectName(state.selectedProjectId)}`)}
      ${renderScenarioSwitcher()}
      <section class="two-column-layout">
        <article class="panel list-panel">
          ${goals
            .map(
              (item) => `
                <button class="goal-row ${item.id === state.selectedGoalId ? "is-active" : ""}" data-goal="${item.id}">
                  <div class="row-title">${item.title}</div>
                  <div class="row-copy">${item.summary}</div>
                  <div class="goal-progress"><span style="width:${item.progress}%"></span></div>
                </button>
              `,
            )
            .join("")}
        </article>
        <article class="panel detail-panel">
          <div class="detail-header compact">
            <div>
              <div class="meta-inline">
                <span class="branch-chip">${goal.owner}</span>
                <span>${goal.progress}% complete</span>
              </div>
              <h2>${goal.title}</h2>
              <p>${goal.summary}</p>
            </div>
          </div>
          <section class="detail-card">
            <div class="panel-title">Milestones</div>
            <div class="stack-list">
              ${goal.milestones.map((item) => `<div class="row-copy">${item}</div>`).join("")}
            </div>
          </section>
          <section class="detail-card">
            <div class="panel-title">Linked issues</div>
            <div class="stack-list">
              ${linkedIssues
                .map(
                  (issue) => `
                    <button class="issue-snippet static" data-view="issues" data-issue="${issue.id}">
                      <span class="issue-key-dot ${toneClass(issue.kind === "resolved" ? "green" : issue.group === "blocked" ? "red" : "blue")}"></span>
                      <span class="issue-snippet-title">${issue.key} · ${issue.title}</span>
                      <span class="issue-time">${issue.kind === "resolved" ? issue.closed : issue.updated}</span>
                    </button>
                  `,
                )
                .join("")}
            </div>
          </section>
        </article>
      </section>
    </section>
  `;
}

function renderAgents() {
  const agent = selectedAgent();
  const detail = selectedAgentDetail();
  return `
    <section class="page-shell">
      ${renderHeader(
        "Agents",
        `${agent.name} · ${agent.role} · ${projectName(state.selectedProjectId)}`,
        `<button class="header-button">Assign issue</button><button class="header-button">Invoke</button><button class="header-button">Pause</button>`,
      )}
      ${renderScenarioSwitcher()}
      <div class="summary-row">
        <span class="summary-chip">Runtime ${agent.runtime}</span>
        <span class="summary-chip">Status ${agent.status}</span>
        <span class="summary-chip">${currentScenario().stats[1].value} issues in progress org-wide</span>
      </div>
      <article class="panel latest-run-panel">
        <div class="status-line">
          <span class="status-pill ${agent.status === "live" ? "ok" : agent.status === "blocked" ? "blocked" : "idle"}">${agent.status}</span>
          <span>${detail.latestRun}</span>
        </div>
      </article>
      <section class="agent-stats-grid">
        ${detail.metrics
          .map(
            (metric, index) => `
              <article class="mini-stat-panel">
                <div class="mini-stat-title">${metric.label}</div>
                <div class="mini-chart"><span style="width:${55 + index * 10}%"></span></div>
                <div class="mini-stat-value">${metric.value}</div>
              </article>
            `,
          )
          .join("")}
      </section>
      <section class="two-column-layout">
        <article class="panel list-panel">
          <div class="panel-title">Current assignments</div>
          <div class="stack-list">
            ${detail.currentAssignments.map((item) => `<div class="row-copy">${item}</div>`).join("")}
          </div>
          <div class="panel-title spaced">Active handoffs</div>
          <div class="stack-list">
            ${detail.handoffs.map((item) => `<div class="row-copy">${item}</div>`).join("")}
          </div>
        </article>
        <article class="panel detail-panel">
          <div class="panel-title">Recently landed</div>
          <div class="stack-list">
            ${detail.recentLanded.map((item) => `<div class="landed-row">${item}</div>`).join("")}
          </div>
        </article>
      </section>
    </section>
  `;
}

function renderTopology() {
  const topology = currentScenario().topology;
  return `
    <section class="page-shell">
      ${renderHeader("Topology", `AI-native execution routing, runtime pressure, and parallel work graph · ${projectName(state.selectedProjectId)}`)}
      ${renderScenarioSwitcher()}
      <section class="topology-grid">
        <article class="panel">
          <div class="panel-title">Capability pools</div>
          <div class="stack-list">
            ${topology.capabilities
              .map(
                (item) => `
                  <div class="topology-node">
                    <div class="row-title">${item.name}</div>
                    <div class="meta-inline"><span>${item.load}</span></div>
                    <div class="row-copy">${item.note}</div>
                  </div>
                `,
              )
              .join("")}
          </div>
        </article>
        <article class="panel">
          <div class="panel-title">Runtime lanes</div>
          <div class="stack-list">
            ${topology.runtimes
              .map(
                (item) => `
                  <div class="topology-node">
                    <div class="meta-inline">
                      <span class="row-title">${item.name}</span>
                      <span class="status-pill ${item.status === "healthy" ? "ok" : item.status === "degraded" ? "blocked" : "idle"}">${item.status}</span>
                    </div>
                    <div class="meta-inline"><span>${item.load}</span></div>
                    <div class="row-copy">${item.note}</div>
                  </div>
                `,
              )
              .join("")}
          </div>
        </article>
        <article class="panel">
          <div class="panel-title">Output queues</div>
          <div class="stack-list">
            ${topology.outputs
              .map(
                (item) => `
                  <div class="topology-node">
                    <div class="meta-inline">
                      <span class="row-title">${item.name}</span>
                      <span class="queue-count">${item.count}</span>
                    </div>
                    <div class="row-copy">${item.note}</div>
                  </div>
                `,
              )
              .join("")}
          </div>
        </article>
      </section>

      <section class="two-column-layout">
        <article class="panel list-panel">
          <div class="panel-title">Critical handoffs</div>
          <div class="stack-list">
            ${topology.handoffs
              .map(
                (item) => `
                  <div class="queue-item compact">
                    <div class="row-title"><span class="issue-key-dot ${toneClass(item.tone)}"></span>${item.title}</div>
                    <div class="row-copy">${item.detail}</div>
                  </div>
                `,
              )
              .join("")}
          </div>
        </article>
        <article class="panel detail-panel">
          <div class="panel-title">${topology.graph.title}</div>
          <div class="panel-copy">${topology.graph.summary}</div>
          <div class="graph-stack">
            ${topology.graph.branches
              .map(
                (branch) => `
                  <div class="graph-branch">
                    <div class="graph-rail ${toneClass(branch.tone)}"></div>
                    <div class="graph-card">
                      <div class="meta-inline">
                        <span class="branch-chip">${branch.lane}</span>
                        <span>${branch.agent}</span>
                      </div>
                      <div class="row-title">${branch.state}</div>
                      <div class="row-copy">${branch.note}</div>
                    </div>
                  </div>
                `,
              )
              .join("")}
          </div>
        </article>
      </section>
    </section>
  `;
}

function renderView() {
  if (state.view === "dashboard") return renderDashboard();
  if (state.view === "inbox") return renderInbox();
  if (state.view === "issues") return renderIssues();
  if (state.view === "goals") return renderGoals();
  if (state.view === "agents") return renderAgents();
  return renderTopology();
}

function render() {
  ensureSelections();
  app.innerHTML = `
    <div class="paperclip-shell">
      ${renderSidebar()}
      <main class="main-area">
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
      if (button.dataset.agent) {
        state.selectedAgentId = button.dataset.agent;
      }
      if (button.dataset.issue) {
        state.issueTab = "open";
        state.selectedIssueId = button.dataset.issue;
      }
      render();
    });
  });

  app.querySelectorAll("[data-project]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedProjectId = button.dataset.project;
      render();
    });
  });

  app.querySelectorAll("[data-scenario]").forEach((button) => {
    button.addEventListener("click", () => {
      state.scenario = button.dataset.scenario;
      render();
    });
  });

  app.querySelectorAll("[data-goal]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedGoalId = button.dataset.goal;
      render();
    });
  });

  app.querySelectorAll("[data-issue-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      state.issueTab = button.dataset.issueTab;
      render();
    });
  });

  app.querySelectorAll("[data-issue]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedIssueId = button.dataset.issue;
      render();
    });
  });

  app.querySelectorAll("[data-resolved-issue]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedResolvedIssueId = button.dataset.resolvedIssue;
      render();
    });
  });
}

render();
