const app = document.querySelector("#app");

const projects = [
  { id: "all", name: "All programs", tone: "blue" },
  { id: "quant", name: "Quant Alpha", tone: "yellow" },
  { id: "growth", name: "Growth Loop", tone: "green" },
  { id: "platform", name: "Platform Core", tone: "blue" },
  { id: "governance", name: "Governance", tone: "purple" },
];

const agents = [
  { id: "orchestrator", name: "Orchestrator", role: "Main control agent", status: "running", project: "All programs", currentIssue: "QNT-127" },
  { id: "research", name: "ResearchLead", role: "Quant research", status: "running", project: "Quant Alpha", currentIssue: "QNT-127" },
  { id: "codex-a", name: "CodexWorker-A", role: "Execution", status: "running", project: "Quant Alpha", currentIssue: "QNT-127" },
  { id: "codex-b", name: "CodexWorker-B", role: "Execution", status: "running", project: "Platform Core", currentIssue: "OPS-88" },
  { id: "review", name: "ReviewDesk", role: "Review", status: "waiting", project: "Growth Loop", currentIssue: "GTH-204" },
  { id: "memory", name: "MemoryCurator", role: "Memory", status: "idle", project: "Governance", currentIssue: "MEM-32" },
  { id: "scheduler", name: "Scheduler", role: "Queue owner", status: "running", project: "All programs", currentIssue: "OPS-104" },
  { id: "recovery", name: "RecoveryAgent", role: "Recovery", status: "blocked", project: "Platform Core", currentIssue: "OPS-88" },
];

function makeIssue(data) {
  return {
    kind: "open",
    assignees: [],
    outputs: [],
    branches: [],
    history: [],
    runs: [],
    dependsOn: [],
    unlocks: [],
    related: [],
    ...data,
  };
}

function makeResolved(data) {
  return {
    kind: "resolved",
    outputs: [],
    history: [],
    dependsOn: [],
    unlocks: [],
    related: [],
    ...data,
  };
}

const scenarios = {
  startup: {
    key: "startup",
    label: "Starting work",
    hero: {
      title: "The system is waking up and building the first runnable queue.",
      copy:
        "Codex is passing readiness checks, the backlog is being decomposed into issues, and the operator mostly needs to clear the first two approvals.",
    },
    metrics: [
      { label: "Open issues", value: "112", note: "18 launchable, 7 blocked, 87 staged" },
      { label: "Active runs", value: "9", note: "Mostly planning and bootstrap validation" },
      { label: "Resolved", value: "1,024", note: "Historical work and memory retained" },
      { label: "Critical decisions", value: "2", note: "Both block broader autonomy" },
    ],
    command: {
      queue: [
        { tone: "yellow", issueKey: "GOV-23", title: "Approve initial runtime policy", copy: "Codex is healthy, but MAAS still needs a default write/retry posture before launching the first real run.", action: "Review now", project: "Governance" },
        { tone: "blue", issueKey: "QNT-127", title: "Approve first quant issue packet", copy: "The first 14 issues are scoped and linked to goals; nothing should launch until the packet is accepted.", action: "Open packet", project: "Quant Alpha" },
        { tone: "red", issueKey: "OPS-88", title: "Contain one startup parity gap", copy: "A platform branch failed the final replay. MAAS isolated it and is waiting on a narrower recovery choice.", action: "Inspect failure", project: "Platform Core" },
      ],
      landed: [
        { key: "OPS-70", title: "Validate Codex preflight on startup queue", outcome: "Codex marked ready for launch", time: "32m ago", project: "Platform Core" },
        { key: "MEM-08", title: "Promote baseline risk note", outcome: "Canonical memory updated", time: "17m ago", project: "Governance" },
      ],
      history: [
        { tone: "blue", lane: "plan/bootstrap", text: "Orchestrator decomposed the startup objective into 14 executable issues", time: "7m ago", project: "Quant Alpha" },
        { tone: "green", lane: "run/preflight-codex", text: "CodexWorker-A completed the startup preflight and published readiness artifacts", time: "14m ago", project: "Platform Core" },
        { tone: "yellow", lane: "review/initial-policy", text: "Orchestrator opened the first operator approval packet", time: "18m ago", project: "Governance" },
      ],
    },
    work: {
      issues: [
        makeIssue({
          id: "startup-qnt-127",
          key: "QNT-127",
          title: "Approve the first quant issue packet",
          project: "Quant Alpha",
          goal: "Launch the first autonomous quant loop",
          status: "review",
          priority: "Critical",
          assignees: ["Orchestrator", "ResearchLead"],
          summary: "The first research pack is ready. Approving it will release nine launchable issues into active execution.",
          nextAction: "Review and approve the packet",
          blockedReason: "Operator approval required",
          updated: "5m ago",
          outputs: ["launch-pack.zip", "startup-brief.md"],
          branches: [
            { name: "plan/first-wave", owner: "ResearchLead", state: "complete", note: "Issue packet assembled with evidence and scope." },
            { name: "review/operator-packet", owner: "Orchestrator", state: "awaiting review", note: "Ready for operator acceptance." },
          ],
          runs: [
            { id: "run_501", state: "completed", agent: "ResearchLead", summary: "Decomposition pass produced nine scoped quant issues." },
          ],
          history: [
            { tone: "blue", lane: "plan/first-wave", text: "ResearchLead decomposed the quant objective into a first executable packet", time: "24m ago" },
            { tone: "yellow", lane: "review/operator-packet", text: "Orchestrator opened the packet for operator approval", time: "5m ago" },
          ],
        }),
        makeIssue({
          id: "startup-ops-88",
          key: "OPS-88",
          title: "Fix startup parity gap in one Codex replay branch",
          project: "Platform Core",
          goal: "Keep the startup queue safe and deterministic",
          status: "blocked",
          priority: "High",
          assignees: ["CodexWorker-B", "RecoveryAgent"],
          summary: "One replay branch diverged during final startup checks. MAAS contained it before it could contaminate the launch queue.",
          nextAction: "Choose recover-or-retry strategy",
          blockedReason: "Recovery choice required",
          updated: "9m ago",
          outputs: ["startup-replay.log"],
          branches: [
            { name: "replay/startup-001", owner: "CodexWorker-B", state: "failed", note: "Final replay diverged from expected patch output." },
            { name: "recovery/startup-001", owner: "RecoveryAgent", state: "waiting", note: "Recovery path prepared but not yet approved." },
          ],
          runs: [
            { id: "run_498", state: "failed", agent: "CodexWorker-B", summary: "Replay failed with patch mismatch on final validation." },
          ],
          history: [
            { tone: "red", lane: "replay/startup-001", text: "CodexWorker-B failed the final startup replay with a patch mismatch", time: "9m ago" },
            { tone: "yellow", lane: "recovery/startup-001", text: "RecoveryAgent prepared a recover-or-retry plan", time: "6m ago" },
          ],
        }),
        makeIssue({
          id: "startup-mem-14",
          key: "MEM-14",
          title: "Promote startup notes after the first packet is approved",
          project: "Governance",
          goal: "Ground the first live runs in reusable memory",
          status: "todo",
          priority: "Medium",
          assignees: ["MemoryCurator"],
          summary: "The notes are ready, but they should not become canonical until the initial packet is actually accepted.",
          nextAction: "Wait for upstream approval",
          blockedReason: "Depends on QNT-127",
          updated: "18m ago",
          outputs: ["startup-notes.md"],
          branches: [
            { name: "memory/startup-notes", owner: "MemoryCurator", state: "staged", note: "Promotion packet prepared and linked." },
          ],
          runs: [],
          history: [
            { tone: "blue", lane: "memory/startup-notes", text: "MemoryCurator prepared the startup promotion packet", time: "18m ago" },
          ],
        }),
      ],
      resolved: [
        makeResolved({
          id: "startup-res-ops-70",
          key: "OPS-70",
          title: "Validate Codex preflight on startup queue",
          project: "Platform Core",
          outcome: "Codex marked healthy and launch-safe",
          resolvedBy: "CodexWorker-A",
          closed: "32m ago",
          outputs: ["preflight-report.json"],
          history: [
            { tone: "green", lane: "run/preflight-codex", text: "CodexWorker-A passed the startup preflight and published the report", time: "32m ago" },
          ],
        }),
      ],
      selectedIssueId: "startup-qnt-127",
    },
    issues: {
      queue: [
        { tone: "yellow", issueKey: "QNT-127", title: "Approval needed: first quant packet", copy: "Blocks nine launchable issues.", action: "Review packet", project: "Quant Alpha", age: "5m" },
        { tone: "red", issueKey: "OPS-88", title: "Blocked replay branch", copy: "Startup replay diverged and needs recovery guidance.", action: "Inspect run", project: "Platform Core", age: "9m" },
        { tone: "blue", issueKey: "MEM-14", title: "Promote startup notes later", copy: "Not urgent yet, but queued for when the packet lands.", action: "Open issue", project: "Governance", age: "18m" },
      ],
      resolved: [
        { key: "OPS-70", title: "Codex preflight validated", copy: "Launch-safe readiness established.", closed: "32m ago", project: "Platform Core" },
      ],
    },
    system: {
      metrics: [
        { label: "Run success rate", value: "94%", note: "Startup noise still expected" },
        { label: "Queued runs", value: "18", note: "Held behind approvals" },
        { label: "Stale agents", value: "0", note: "All heartbeats healthy" },
        { label: "Logged events", value: "8,412", note: "Every state transition persisted" },
      ],
      logs: [
        "[17:01:18] orchestrator issued startup decomposition for quant objective",
        "[17:01:24] codex_worker_a passed startup preflight and uploaded preflight-report.json",
        "[17:01:41] codex_worker_b replay branch failed with patch mismatch on startup-replay.log",
        "[17:01:47] recovery_agent prepared recovery/startup-001 plan and marked issue OPS-88 blocked",
      ],
      trace: {
        title: "run_498 · startup replay",
        body:
          "codex exec --task OPS-88 --mode replay\n-> checkout startup workspace\n-> apply patch candidate\n-> replay validation failed: expected patch drift exceeded threshold\n-> artifacts: startup-replay.log",
      },
    },
  },
  active: {
    key: "active",
    label: "Working at scale",
    hero: {
      title: "The system is doing real work, spawning subagents, and only surfacing true exceptions.",
      copy:
        "Codex is carrying the execution load, ReviewDesk is absorbing completions, and the operator mostly clears decisions and watches for blocked branches or stale runs.",
    },
    metrics: [
      { label: "Open issues", value: "100", note: "31 in progress, 18 review, 9 blocked" },
      { label: "Active runs", value: "27", note: "8 with multiple subagents working in parallel" },
      { label: "Resolved", value: "1,084", note: "40 landed this cycle" },
      { label: "Critical decisions", value: "1", note: "Only one actually blocks the launch path" },
    ],
    command: {
      queue: [
        { tone: "yellow", issueKey: "QNT-127", title: "Approve quant paper-trading guardrail", copy: "Research, validation, and the operator packet are all ready. This is the only thing blocking promotion.", action: "Review now", project: "Quant Alpha" },
        { tone: "red", issueKey: "OPS-88", title: "One platform branch is stuck in repeated recovery", copy: "Fallback kept the queue moving, but one branch still needs a narrower fix path.", action: "Inspect failure", project: "Platform Core" },
        { tone: "blue", issueKey: "MEM-32", title: "Promote the strategy memo into canonical memory", copy: "The latest strategy memo has citations and can now ground future planning runs.", action: "Promote", project: "Governance" },
      ],
      landed: [
        { key: "GTH-198", title: "Generate three outbound prospect briefs", outcome: "Merged into the weekly outbound pack", time: "11m ago", project: "Growth Loop" },
        { key: "OPS-97", title: "Ship runtime fallback contract v2", outcome: "Execution queue stabilized", time: "17m ago", project: "Platform Core" },
        { key: "MEM-29", title: "Promote operator scorecard", outcome: "Now referenced by the daily brief", time: "36m ago", project: "Governance" },
      ],
      history: [
        { tone: "green", lane: "run/qnt-127/verify-replay", text: "CodexWorker-A completed the final guardrail replay and attached verification outputs", time: "3m ago", project: "Quant Alpha" },
        { tone: "yellow", lane: "review/qnt-127/operator-packet", text: "Orchestrator turned the guardrail evidence into one approval packet", time: "6m ago", project: "Quant Alpha" },
        { tone: "red", lane: "run/ops-88/recovery-4", text: "RecoveryAgent opened a fourth recovery attempt after a stale patch branch was rejected", time: "10m ago", project: "Platform Core" },
        { tone: "blue", lane: "run/gth-204/subagent-2", text: "GrowthLead spawned two subagents to draft prospect briefs in parallel", time: "14m ago", project: "Growth Loop" },
      ],
    },
    work: {
      issues: [
        makeIssue({
          id: "active-qnt-127",
          key: "QNT-127",
          title: "Approve quant paper-trading guardrail",
          project: "Quant Alpha",
          goal: "Launch the guarded paper-trading loop",
          status: "review",
          priority: "Critical",
          assignees: ["Orchestrator", "ResearchLead", "CodexWorker-A"],
          summary: "All parallel work for the guardrail is complete. This issue is waiting on operator judgment, not more agent labor.",
          nextAction: "Approve the guardrail or request a narrower risk pass",
          blockedReason: "Operator approval required",
          updated: "3m ago",
          outputs: ["guardrail.diff", "backtest-summary.md", "operator-packet.md"],
          branches: [
            { name: "research/guardrail-proof", owner: "ResearchLead", state: "complete", note: "Evidence pack and risk note assembled." },
            { name: "run/qnt-127/verify-replay", owner: "CodexWorker-A", state: "complete", note: "Final replay and artifact validation succeeded." },
            { name: "review/qnt-127/operator-packet", owner: "Orchestrator", state: "awaiting review", note: "Packet ready for operator decision." },
          ],
          runs: [
            { id: "run_982", state: "completed", agent: "CodexWorker-A", summary: "Verification replay passed and produced guardrail.diff." },
            { id: "run_961", state: "completed", agent: "ResearchLead", summary: "Compiled evidence and linked prior findings." },
          ],
          history: [
            { tone: "blue", lane: "research/guardrail-proof", text: "ResearchLead completed the evidence pack", time: "26m ago" },
            { tone: "green", lane: "run/qnt-127/verify-replay", text: "CodexWorker-A passed the final replay and uploaded outputs", time: "3m ago" },
            { tone: "yellow", lane: "review/qnt-127/operator-packet", text: "Orchestrator opened the operator approval packet", time: "2m ago" },
          ],
        }),
        makeIssue({
          id: "active-gth-204",
          key: "GTH-204",
          title: "Create three new institutional prospect briefs",
          project: "Growth Loop",
          goal: "Maintain weekly outbound intelligence cadence",
          status: "inprogress",
          priority: "High",
          assignees: ["GrowthLead", "ReviewDesk"],
          summary: "Three briefs are being drafted in parallel by spawned subagents and will converge into one review queue.",
          nextAction: "No operator action needed unless review SLA breaches",
          blockedReason: "None",
          updated: "7m ago",
          outputs: ["brief-apollo.md", "brief-delta.md"],
          branches: [
            { name: "run/gth-204/subagent-1", owner: "GrowthLead", state: "writing", note: "Drafting brief for Apollo account cluster." },
            { name: "run/gth-204/subagent-2", owner: "GrowthLead", state: "writing", note: "Drafting brief for Delta account cluster." },
            { name: "run/gth-204/review-queue", owner: "ReviewDesk", state: "watching", note: "Ready to ingest all three briefs once they land." },
          ],
          runs: [
            { id: "run_995", state: "running", agent: "GrowthLead", summary: "Two subagents are drafting prospect briefs in parallel." },
          ],
          history: [
            { tone: "blue", lane: "run/gth-204/main", text: "GrowthLead opened the outbound brief issue", time: "44m ago" },
            { tone: "green", lane: "run/gth-204/subagent-1", text: "Subagent 1 started drafting the Apollo brief", time: "18m ago" },
            { tone: "green", lane: "run/gth-204/subagent-2", text: "Subagent 2 started drafting the Delta brief", time: "14m ago" },
            { tone: "yellow", lane: "run/gth-204/review-queue", text: "ReviewDesk reserved capacity for the completed briefs", time: "7m ago" },
          ],
        }),
        makeIssue({
          id: "active-ops-88",
          key: "OPS-88",
          title: "Fix repeated recovery failure on one platform branch",
          project: "Platform Core",
          goal: "Keep platform runs deterministic under Codex-only execution",
          status: "blocked",
          priority: "High",
          assignees: ["RecoveryAgent", "CodexWorker-B"],
          summary: "One platform branch is failing repeatedly. MAAS has contained it, but the operator still needs to decide whether to replan or keep retrying.",
          nextAction: "Inspect the failed branch history and choose recover-or-replan",
          blockedReason: "Recovery branch failed three times",
          updated: "10m ago",
          outputs: ["recovery-4.log", "patch-drift.diff"],
          branches: [
            { name: "run/ops-88/recovery-4", owner: "RecoveryAgent", state: "failed", note: "The fourth recovery attempt still diverged from accepted patch history." },
            { name: "run/ops-88/hotfix", owner: "CodexWorker-B", state: "waiting", note: "A narrower hotfix branch is ready if the operator chooses replan." },
          ],
          runs: [
            { id: "run_994", state: "failed", agent: "RecoveryAgent", summary: "Fourth recovery attempt failed on patch drift." },
            { id: "run_992", state: "failed", agent: "RecoveryAgent", summary: "Third recovery attempt failed on stale workspace state." },
          ],
          history: [
            { tone: "red", lane: "run/ops-88/recovery-3", text: "RecoveryAgent failed the third recovery attempt due to stale workspace state", time: "18m ago" },
            { tone: "red", lane: "run/ops-88/recovery-4", text: "RecoveryAgent failed again with patch drift", time: "10m ago" },
            { tone: "yellow", lane: "run/ops-88/hotfix", text: "CodexWorker-B prepared a narrower hotfix branch for replan", time: "4m ago" },
          ],
        }),
        makeIssue({
          id: "active-mem-32",
          key: "MEM-32",
          title: "Promote strategy memo into canonical memory",
          project: "Governance",
          goal: "Reuse proven planning outputs automatically",
          status: "todo",
          priority: "Medium",
          assignees: ["MemoryCurator"],
          summary: "The strategy memo is accepted and cited. Promoting it would improve the next planning loop across Growth and Governance.",
          nextAction: "Promote when the critical approval is cleared",
          blockedReason: "Waiting behind QNT-127 in operator queue",
          updated: "16m ago",
          outputs: ["strategy-memo.md", "citations.json"],
          branches: [
            { name: "memory/strategy-memo", owner: "MemoryCurator", state: "staged", note: "Promotion package ready and linked." },
          ],
          runs: [],
          history: [
            { tone: "blue", lane: "memory/strategy-memo", text: "MemoryCurator staged the strategy memo for promotion", time: "16m ago" },
          ],
        }),
      ],
      resolved: [
        makeResolved({
          id: "active-res-gth-198",
          key: "GTH-198",
          title: "Generate three outbound prospect briefs",
          project: "Growth Loop",
          outcome: "Merged into the weekly outbound pack",
          resolvedBy: "ReviewDesk",
          closed: "11m ago",
          outputs: ["prospect-pack.zip"],
          history: [
            { tone: "green", lane: "run/gth-198/review-merge", text: "ReviewDesk merged three accepted briefs into the outbound pack", time: "11m ago" },
          ],
        }),
        makeResolved({
          id: "active-res-ops-97",
          key: "OPS-97",
          title: "Ship runtime fallback contract v2",
          project: "Platform Core",
          outcome: "Queue stabilized and overflow routing is now default",
          resolvedBy: "Orchestrator",
          closed: "17m ago",
          outputs: ["runtime-routing.diff"],
          history: [
            { tone: "green", lane: "run/ops-97/merge", text: "Fallback routing v2 was merged into the active queue controller", time: "17m ago" },
          ],
        }),
      ],
      selectedIssueId: "active-qnt-127",
    },
    issues: {
      queue: [
        { tone: "yellow", issueKey: "QNT-127", title: "Approval needed: quant paper-trading guardrail", copy: "All parallel branches completed. The launch path is now waiting on judgment, not more work.", action: "Review now", project: "Quant Alpha", age: "3m" },
        { tone: "red", issueKey: "OPS-88", title: "Repeated recovery failure on OPS-88", copy: "Four attempts failed. MAAS recommends replan, not another blind retry.", action: "Inspect history", project: "Platform Core", age: "10m" },
        { tone: "yellow", issueKey: "GTH-209", title: "Growth review queue drifting toward SLA breach", copy: "Two completed brief issues are waiting longer than target in review.", action: "Open queue", project: "Growth Loop", age: "12m" },
        { tone: "blue", issueKey: "MEM-32", title: "Strategy memo ready for canonical promotion", copy: "Safe to promote once the critical approval is done.", action: "Promote later", project: "Governance", age: "16m" },
      ],
      resolved: [
        { key: "GTH-198", title: "Outbound brief pack merged", copy: "Three briefs accepted and merged.", closed: "11m ago", project: "Growth Loop" },
        { key: "OPS-97", title: "Fallback contract v2 shipped", copy: "Platform queue stabilized.", closed: "17m ago", project: "Platform Core" },
      ],
    },
    system: {
      metrics: [
        { label: "Run success rate", value: "97%", note: "Strong despite contained platform noise" },
        { label: "Queued runs", value: "23", note: "Mostly review and routine execution" },
        { label: "Stale agents", value: "1", note: "ReviewDesk waiting on older queue item" },
        { label: "Logged events", value: "18,942", note: "Full state transition and run audit" },
      ],
      logs: [
        "[17:14:02] codex_worker_a finished run_982 for QNT-127 and uploaded guardrail.diff",
        "[17:14:07] orchestrator opened review packet for QNT-127 and moved issue to review",
        "[17:14:11] recovery_agent failed run_994 for OPS-88 with patch drift against accepted branch",
        "[17:14:15] growthlead spawned subagent-2 for GTH-204 to draft Delta brief in parallel",
        "[17:14:21] reviewdesk reserved capacity for three inbound GTH-204 brief outputs",
      ],
      trace: {
        title: "run_994 · OPS-88 recovery",
        body:
          "codex exec --task OPS-88 --branch recovery-4\n-> restore last accepted workspace snapshot\n-> replay candidate patch from run_992\n-> verify artifact lineage\n-> fail: patch drift exceeds accepted branch delta\n-> recommendation: stop retry loop and open hotfix replan branch",
      },
    },
  },
  resolving: {
    key: "resolving",
    label: "Resolving pressure",
    hero: {
      title: "The critical blocker is gone and the system is converging back to a healthy rhythm.",
      copy:
        "The operator has already cleared the main approval. MAAS is now draining long-tail incidents, landing the last fixes, and promoting the right learnings into memory.",
    },
    metrics: [
      { label: "Open issues", value: "86", note: "19 in progress, 11 review, 4 blocked" },
      { label: "Active runs", value: "14", note: "Mostly cleanup, review, and relaunch runs" },
      { label: "Resolved", value: "1,109", note: "25 landed this cycle" },
      { label: "Critical decisions", value: "0", note: "Only one routine exception remains" },
    ],
    command: {
      queue: [
        { tone: "blue", issueKey: "MEM-41", title: "Promote recovery memo into canonical memory", copy: "The incident package is now good enough to become reusable policy for future runs.", action: "Promote memo", project: "Governance" },
        { tone: "yellow", issueKey: "GOV-41", title: "Review one remaining capital-exposure exception", copy: "Low-risk routine decision. The main launch path is already clear.", action: "Review", project: "Governance" },
      ],
      landed: [
        { key: "QNT-127", title: "Approve quant paper-trading guardrail", outcome: "Launch queue resumed automatically", time: "6m ago", project: "Quant Alpha" },
        { key: "OPS-88", title: "Reroute stuck branch through hotfix path", outcome: "Queue pressure fell immediately", time: "15m ago", project: "Platform Core" },
        { key: "MEM-32", title: "Promote strategy memo", outcome: "Future planning now reuses it", time: "28m ago", project: "Governance" },
      ],
      history: [
        { tone: "green", lane: "review/qnt-127/approval", text: "The operator approved the quant guardrail and the launch queue resumed automatically", time: "6m ago", project: "Quant Alpha" },
        { tone: "green", lane: "run/ops-88/hotfix", text: "CodexWorker-B landed the hotfix branch and cleared the repeated recovery loop", time: "15m ago", project: "Platform Core" },
        { tone: "blue", lane: "memory/recovery-memo", text: "RecoveryAgent assembled a reusable recovery memo from the resolved incident", time: "21m ago", project: "Governance" },
      ],
    },
    work: {
      issues: [
        makeIssue({
          id: "resolving-gov-41",
          key: "GOV-41",
          title: "Review one remaining capital-exposure exception",
          project: "Governance",
          goal: "Close the cycle with only low-risk operator work remaining",
          status: "review",
          priority: "Medium",
          assignees: ["Orchestrator"],
          summary: "The critical path is already clear. This is a routine decision affecting one growth experiment only.",
          nextAction: "Review and either approve or close the exception",
          blockedReason: "Operator judgment required",
          updated: "8m ago",
          outputs: ["exception-packet.md"],
          branches: [
            { name: "review/capital-exception", owner: "Orchestrator", state: "awaiting review", note: "Routine exception packet ready." },
          ],
          runs: [],
          history: [
            { tone: "yellow", lane: "review/capital-exception", text: "Orchestrator refreshed the last exception packet for review", time: "8m ago" },
          ],
        }),
        makeIssue({
          id: "resolving-mem-41",
          key: "MEM-41",
          title: "Promote recovery memo into canonical memory",
          project: "Governance",
          goal: "Make the latest recovery path reusable",
          status: "todo",
          priority: "Medium",
          assignees: ["RecoveryAgent", "MemoryCurator"],
          summary: "The incident package is fully sourced and should become reusable guidance for future failures of this type.",
          nextAction: "Promote the memo after reviewing the routine exception",
          blockedReason: "Waiting behind GOV-41",
          updated: "14m ago",
          outputs: ["recovery-memo.md"],
          branches: [
            { name: "memory/recovery-memo", owner: "MemoryCurator", state: "staged", note: "Promotion packet prepared and linked." },
          ],
          runs: [],
          history: [
            { tone: "blue", lane: "memory/recovery-memo", text: "Recovery memo packet staged for promotion", time: "14m ago" },
          ],
        }),
        makeIssue({
          id: "resolving-gth-211",
          key: "GTH-211",
          title: "Relaunch the paused outbound experiment",
          project: "Growth Loop",
          goal: "Resume normal work after the critical path was cleared",
          status: "inprogress",
          priority: "Medium",
          assignees: ["GrowthLead", "ReviewDesk"],
          summary: "The main bottleneck is gone. This experiment is restarting and should flow normally if the review queue stays healthy.",
          nextAction: "No operator action needed unless review slows again",
          blockedReason: "None",
          updated: "11m ago",
          outputs: ["relaunch-plan.md"],
          branches: [
            { name: "run/gth-211/relaunch", owner: "GrowthLead", state: "running", note: "Rebuilding the outbound sequence with cleared approvals." },
            { name: "run/gth-211/review-watch", owner: "ReviewDesk", state: "watching", note: "Monitoring SLA while the experiment restarts." },
          ],
          runs: [
            { id: "run_1011", state: "running", agent: "GrowthLead", summary: "Experiment relaunch is healthy." },
          ],
          history: [
            { tone: "green", lane: "run/gth-211/relaunch", text: "GrowthLead reopened the paused experiment", time: "11m ago" },
          ],
        }),
      ],
      resolved: [
        makeResolved({
          id: "resolving-res-qnt-127",
          key: "QNT-127",
          title: "Approve quant paper-trading guardrail",
          project: "Quant Alpha",
          outcome: "Approved and automatically promoted into the live launch sequence",
          resolvedBy: "Operator",
          closed: "6m ago",
          outputs: ["guardrail.diff", "operator-packet.md"],
          history: [
            { tone: "green", lane: "review/qnt-127/approval", text: "Operator approved the guardrail and resumed the launch queue", time: "6m ago" },
          ],
        }),
        makeResolved({
          id: "resolving-res-ops-88",
          key: "OPS-88",
          title: "Fix repeated recovery failure on one platform branch",
          project: "Platform Core",
          outcome: "Hotfix path landed and the stuck queue drained",
          resolvedBy: "CodexWorker-B",
          closed: "15m ago",
          outputs: ["hotfix.diff", "recovery-summary.md"],
          history: [
            { tone: "green", lane: "run/ops-88/hotfix", text: "CodexWorker-B landed the hotfix path and cleared the recovery loop", time: "15m ago" },
          ],
        }),
      ],
      selectedIssueId: "resolving-gov-41",
    },
    issues: {
      queue: [
        { tone: "yellow", issueKey: "GOV-41", title: "Routine review: capital-exposure exception", copy: "Low-risk and isolated. It no longer blocks anything critical.", action: "Review", project: "Governance", age: "8m" },
        { tone: "blue", issueKey: "MEM-41", title: "Promote recovery memo", copy: "The recovery path is solid and ready to be made reusable.", action: "Promote", project: "Governance", age: "14m" },
      ],
      resolved: [
        { key: "QNT-127", title: "Quant guardrail approved", copy: "Launch queue resumed automatically.", closed: "6m ago", project: "Quant Alpha" },
        { key: "OPS-88", title: "Repeated recovery failure cleared", copy: "Hotfix path landed successfully.", closed: "15m ago", project: "Platform Core" },
      ],
    },
    system: {
      metrics: [
        { label: "Run success rate", value: "99%", note: "Pressure is draining cleanly" },
        { label: "Queued runs", value: "9", note: "Mostly review and follow-up" },
        { label: "Stale agents", value: "0", note: "All active runs healthy" },
        { label: "Logged events", value: "19,304", note: "All resolutions and promotions persisted" },
      ],
      logs: [
        "[17:23:01] operator approved QNT-127 and resumed the launch queue automatically",
        "[17:23:08] codex_worker_b finished hotfix branch for OPS-88 and closed repeated recovery loop",
        "[17:23:16] orchestrator downgraded GOV-41 from critical to routine decision",
        "[17:23:24] memory_curator staged recovery-memo.md for promotion",
      ],
      trace: {
        title: "run_1004 · OPS-88 hotfix",
        body:
          "codex exec --task OPS-88 --branch hotfix\n-> restore accepted snapshot\n-> apply narrowed patch set\n-> replay validation passed\n-> artifact lineage verified\n-> close blocked issue and mark hotfix path canonical",
      },
    },
  },
};

const syntheticPlans = {
  startup: {
    todo: [
      ["QNT-131", "Prepare the first model-risk backlog", "Quant Alpha", "Launch the first autonomous quant loop"],
      ["QNT-132", "Define the initial replay acceptance checklist", "Quant Alpha", "Launch the first autonomous quant loop"],
      ["GOV-27", "Document the first launch approval boundaries", "Governance", "Ground the first live runs in reusable memory"],
      ["MEM-18", "Package bootstrap notes for later promotion", "Governance", "Ground the first live runs in reusable memory"],
      ["PLT-55", "Verify the startup workspace cleanup path", "Platform Core", "Keep the startup queue safe and deterministic"],
      ["GTH-101", "Seed the first outbound intelligence backlog", "Growth Loop", "Start the growth intelligence loop"],
    ],
    inprogress: [
      ["QNT-129", "Map the first quant feature branches", "Quant Alpha", "Launch the first autonomous quant loop"],
      ["PLT-52", "Generate the startup operator brief", "Governance", "Ground the first live runs in reusable memory"],
      ["PLT-53", "Backfill accepted startup artifacts", "Platform Core", "Keep the startup queue safe and deterministic"],
      ["GTH-103", "Compile the first prospect scoring notes", "Growth Loop", "Start the growth intelligence loop"],
    ],
    review: [
      ["GOV-23", "Approve the initial write-permission posture", "Governance", "Ground the first live runs in reusable memory"],
      ["QNT-130", "Review the startup research citations", "Quant Alpha", "Launch the first autonomous quant loop"],
      ["PLT-54", "Accept the startup trace retention policy", "Platform Core", "Keep the startup queue safe and deterministic"],
    ],
    blocked: [
      ["PLT-56", "Resolve one startup patch drift branch", "Platform Core", "Keep the startup queue safe and deterministic"],
      ["GTH-105", "Wait on the first growth policy packet", "Growth Loop", "Start the growth intelligence loop"],
    ],
    resolved: [
      ["OPS-68", "Validate base Codex workspace creation", "Platform Core", "Codex startup workspace marked healthy"],
      ["MEM-07", "Promote a baseline startup memo", "Governance", "Startup memory now available to the first brief"],
      ["QNT-120", "Assemble initial quant source bundle", "Quant Alpha", "The first source bundle is archived and ready"],
      ["GTH-098", "Import the first outbound reference pack", "Growth Loop", "Growth reference pack is now searchable"],
      ["PLT-49", "Verify startup artifact retention policy", "Platform Core", "Artifact retention defaults accepted"],
      ["GOV-18", "Seed the first operator decision log", "Governance", "Decision log initialized and linked"],
    ],
  },
  active: {
    todo: [
      ["QNT-133", "Package the second quant feature sweep", "Quant Alpha", "Launch the guarded paper-trading loop"],
      ["QNT-134", "Prepare a shadow-risk review packet", "Quant Alpha", "Launch the guarded paper-trading loop"],
      ["GTH-205", "Queue the next outbound brief cohort", "Growth Loop", "Maintain weekly outbound intelligence cadence"],
      ["GTH-206", "Refresh institutional scoring prompts", "Growth Loop", "Maintain weekly outbound intelligence cadence"],
      ["MEM-33", "Stage memory promotion for the scorecard", "Governance", "Reuse proven planning outputs automatically"],
      ["MEM-34", "Link growth findings into the daily brief", "Governance", "Reuse proven planning outputs automatically"],
      ["OPS-99", "Prepare deterministic replay for fallback lane", "Platform Core", "Keep platform runs deterministic under Codex-only execution"],
      ["OPS-100", "Package a narrower patch set for stale branches", "Platform Core", "Keep platform runs deterministic under Codex-only execution"],
    ],
    inprogress: [
      ["QNT-128", "Assemble the follow-up quant validation pack", "Quant Alpha", "Launch the guarded paper-trading loop"],
      ["QNT-135", "Generate alternative risk scenarios", "Quant Alpha", "Launch the guarded paper-trading loop"],
      ["GTH-207", "Draft three follow-on prospect briefs", "Growth Loop", "Maintain weekly outbound intelligence cadence"],
      ["GTH-208", "Draft a summary note for the outbound scorecard", "Growth Loop", "Maintain weekly outbound intelligence cadence"],
      ["OPS-101", "Replay the fallback lane under load", "Platform Core", "Keep platform runs deterministic under Codex-only execution"],
      ["OPS-102", "Validate artifact lineage on hotfix branches", "Platform Core", "Keep platform runs deterministic under Codex-only execution"],
      ["MEM-35", "Compile the operator brief appendix", "Governance", "Reuse proven planning outputs automatically"],
      ["MEM-36", "Refresh the canonical plan summary", "Governance", "Reuse proven planning outputs automatically"],
    ],
    review: [
      ["QNT-136", "Review the updated risk packet", "Quant Alpha", "Launch the guarded paper-trading loop"],
      ["QNT-137", "Approve the replay summary for launch notes", "Quant Alpha", "Launch the guarded paper-trading loop"],
      ["GTH-209", "Review the first outbound batch", "Growth Loop", "Maintain weekly outbound intelligence cadence"],
      ["GTH-210", "Approve the revised outbound scorecard", "Growth Loop", "Maintain weekly outbound intelligence cadence"],
      ["MEM-37", "Approve promotion of the strategy memo appendix", "Governance", "Reuse proven planning outputs automatically"],
      ["OPS-103", "Review a narrower recovery branch before merge", "Platform Core", "Keep platform runs deterministic under Codex-only execution"],
    ],
    blocked: [
      ["OPS-104", "Replan one stale hotfix branch", "Platform Core", "Keep platform runs deterministic under Codex-only execution"],
      ["OPS-105", "Wait on artifact restore before rerun", "Platform Core", "Keep platform runs deterministic under Codex-only execution"],
      ["QNT-138", "Hold one launch branch behind policy review", "Quant Alpha", "Launch the guarded paper-trading loop"],
      ["GTH-212", "Wait on review capacity for a campaign branch", "Growth Loop", "Maintain weekly outbound intelligence cadence"],
    ],
    resolved: [
      ["GTH-199", "Publish an outbound scorecard update", "Growth Loop", "Weekly scorecard accepted and published"],
      ["QNT-121", "Backfill prior guardrail findings", "Quant Alpha", "Prior findings are linked to the active loop"],
      ["OPS-96", "Recover one blocked execution lane", "Platform Core", "Lane restored and queue pressure reduced"],
      ["MEM-28", "Promote launch notes into canonical memory", "Governance", "Launch notes now ground later planning"],
      ["GTH-197", "Archive one accepted prospect bundle", "Growth Loop", "Brief bundle archived with lineage"],
      ["QNT-122", "Merge quant replay fixes from last cycle", "Quant Alpha", "Replay fixes are now canonical"],
      ["OPS-95", "Ship queue controller instrumentation", "Platform Core", "Queue metrics now appear in system view"],
      ["MEM-27", "Attach citations to the weekly strategy note", "Governance", "Memo citations are now complete"],
      ["GTH-196", "Close a stale outreach branch", "Growth Loop", "Branch closed and superseded"],
      ["QNT-123", "Promote the quant risk addendum", "Quant Alpha", "Risk addendum is now accepted"],
    ],
  },
  resolving: {
    todo: [
      ["MEM-42", "Archive the recovery decision packet", "Governance", "Make the latest recovery path reusable"],
      ["GTH-213", "Queue one post-recovery outbound experiment", "Growth Loop", "Resume normal work after the critical path was cleared"],
      ["OPS-106", "Clean the last stale branch reference", "Platform Core", "Close the cycle with only long-tail cleanup remaining"],
      ["QNT-139", "Package the next post-approval validation sweep", "Quant Alpha", "Resume the launch sequence cleanly"],
    ],
    inprogress: [
      ["GTH-214", "Relaunch one paused growth sequence", "Growth Loop", "Resume normal work after the critical path was cleared"],
      ["OPS-107", "Drain the last platform cleanup queue", "Platform Core", "Close the cycle with only long-tail cleanup remaining"],
      ["MEM-43", "Compile the recovery appendix for the operator brief", "Governance", "Make the latest recovery path reusable"],
      ["QNT-140", "Rebalance the launch backlog after approval", "Quant Alpha", "Resume the launch sequence cleanly"],
    ],
    review: [
      ["GOV-42", "Review the final routine exception packet", "Governance", "Close the cycle with only low-risk operator work remaining"],
      ["MEM-44", "Approve promotion of the recovery appendix", "Governance", "Make the latest recovery path reusable"],
      ["GTH-215", "Review one relaunch summary", "Growth Loop", "Resume normal work after the critical path was cleared"],
    ],
    blocked: [
      ["OPS-108", "Wait on the final cleanup artifact", "Platform Core", "Close the cycle with only long-tail cleanup remaining"],
    ],
    resolved: [
      ["GTH-200", "Resume the main outbound sequence", "Growth Loop", "Growth queue is back within SLA"],
      ["OPS-98", "Clear the stuck recovery loop", "Platform Core", "Repeated recovery failure is gone"],
      ["MEM-30", "Promote the strategy memo", "Governance", "Strategy memo is now canonical"],
      ["QNT-124", "Resume the quant launch queue", "Quant Alpha", "Launch queue is flowing again"],
      ["GTH-201", "Accept the last campaign review packet", "Growth Loop", "Campaign queue is healthy again"],
      ["OPS-94", "Close the fallback routing review", "Platform Core", "Fallback path accepted"],
      ["MEM-31", "Archive the resolved incident packet", "Governance", "Incident archive updated"],
    ],
  },
};

function makeSyntheticIssue(scenarioKey, status, [key, title, project, goal], index) {
  const owners = {
    "Quant Alpha": ["ResearchLead", "CodexWorker-A"],
    "Growth Loop": ["GrowthLead", "ReviewDesk"],
    "Platform Core": ["CodexWorker-B", "RecoveryAgent"],
    Governance: ["Orchestrator", "MemoryCurator"],
  };
  const assignees = owners[project] ?? ["Orchestrator"];
  const branchLabel = status === "review" ? "review" : status === "blocked" ? "recovery" : "run";
  const stateLabel =
    status === "todo"
      ? "queued"
      : status === "inprogress"
        ? "running"
        : status === "review"
          ? "awaiting review"
          : "blocked";
  return makeIssue({
    id: `${scenarioKey}-${key.toLowerCase()}`,
    key,
    title,
    project,
    goal,
    status,
    priority: status === "blocked" ? "High" : status === "review" ? "High" : "Medium",
    assignees,
    summary: `${title}. This is representative pipeline work to make the mockup feel like a busy, fully operating MAAS system.`,
    nextAction:
      status === "review"
        ? "Inspect and decide whether to accept it"
        : status === "blocked"
          ? "Inspect the blocker and choose recovery"
          : status === "inprogress"
            ? "Monitor progress unless it stalls"
            : "Let the scheduler release it when capacity opens",
    blockedReason:
      status === "blocked"
        ? "Needs recovery or unblocking"
        : status === "review"
          ? "Waiting on review queue"
          : "None",
    updated: `${(index % 27) + 3}m ago`,
    outputs: status === "todo" ? [] : [`${key.toLowerCase()}.md`],
    branches: [
      {
        name: `${branchLabel}/${key.toLowerCase()}/main`,
        owner: assignees[0],
        state: stateLabel,
        note: `${title} is currently ${stateLabel} on the main branch.`,
      },
      ...(status === "inprogress"
        ? [
            {
              name: `${branchLabel}/${key.toLowerCase()}/subagent-1`,
              owner: assignees[0],
              state: "parallel",
              note: "A spawned subagent is working a narrower slice in parallel.",
            },
          ]
        : []),
    ],
    runs:
      status === "todo"
        ? []
        : [
            {
              id: `run_${scenarioKey.slice(0, 3)}_${index + 1100}`,
              state: status === "blocked" ? "failed" : status === "review" ? "completed" : "running",
              agent: assignees[0],
              summary: `${title} produced a representative run record for the mockup.`,
            },
          ],
    history: [
      {
        tone: status === "blocked" ? "red" : status === "review" ? "yellow" : status === "inprogress" ? "green" : "blue",
        lane: `${branchLabel}/${key.toLowerCase()}`,
        text: `${title} entered ${status} state for the current cycle`,
        time: `${(index % 31) + 4}m ago`,
      },
    ],
  });
}

function makeSyntheticResolved(scenarioKey, [key, title, project, outcome], index) {
  return makeResolved({
    id: `${scenarioKey}-${key.toLowerCase()}`,
    key,
    title,
    project,
    outcome,
    resolvedBy: project === "Governance" ? "Orchestrator" : project === "Platform Core" ? "CodexWorker-B" : project === "Growth Loop" ? "ReviewDesk" : "ResearchLead",
    closed: `${(index % 37) + 5}m ago`,
    outputs: [`${key.toLowerCase()}.artifact`],
    history: [
      {
        tone: "green",
        lane: `merge/${key.toLowerCase()}`,
        text: `${title} landed and updated system state`,
        time: `${(index % 37) + 5}m ago`,
      },
    ],
  });
}

Object.entries(syntheticPlans).forEach(([scenarioKey, plan]) => {
  const scenario = scenarios[scenarioKey];
  ["todo", "inprogress", "review", "blocked"].forEach((status) => {
    plan[status].forEach((seed, index) => {
      scenario.work.issues.push(makeSyntheticIssue(scenarioKey, status, seed, index));
    });
  });
  plan.resolved.forEach((seed, index) => {
    scenario.work.resolved.push(makeSyntheticResolved(scenarioKey, seed, index));
  });
});

function dedupePush(list, value) {
  if (!value || list.includes(value)) return;
  list.push(value);
}

function wireScenarioRelationships(scenarioKey, explicit = {}) {
  const scenario = scenarios[scenarioKey];
  const allItems = [...scenario.work.issues, ...scenario.work.resolved];
  const itemByKey = new Map(allItems.map((item) => [item.key, item]));

  allItems.forEach((item) => {
    item.dependsOn = [];
    item.unlocks = [];
    item.related = [];
  });

  function addDependency(issueKey, dependencyKey) {
    const issue = itemByKey.get(issueKey);
    const dependency = itemByKey.get(dependencyKey);
    if (!issue || !dependency || issueKey === dependencyKey) return;
    dedupePush(issue.dependsOn, dependencyKey);
    dedupePush(dependency.unlocks, issueKey);
  }

  function addRelated(aKey, bKey) {
    const a = itemByKey.get(aKey);
    const b = itemByKey.get(bKey);
    if (!a || !b || aKey === bKey) return;
    dedupePush(a.related, bKey);
    dedupePush(b.related, aKey);
  }

  const projectGroups = scenario.work.issues.reduce((acc, issue) => {
    (acc[issue.project] ??= []).push(issue);
    return acc;
  }, {});

  Object.values(projectGroups).forEach((group) => {
    group.forEach((issue, index) => {
      const previous = group[index - 1];
      if (previous) addDependency(issue.key, previous.key);
    });

    const goalGroups = group.reduce((acc, issue) => {
      (acc[issue.goal] ??= []).push(issue);
      return acc;
    }, {});

    Object.values(goalGroups).forEach((goalGroup) => {
      goalGroup.forEach((issue, index) => {
        goalGroup
          .filter((candidate) => candidate.key !== issue.key)
          .slice(0, 3)
          .forEach((candidate) => addRelated(issue.key, candidate.key));
        if (index > 0) addDependency(issue.key, goalGroup[index - 1].key);
      });
    });
  });

  Object.entries(explicit).forEach(([issueKey, relations]) => {
    relations.dependsOn?.forEach((dependencyKey) => addDependency(issueKey, dependencyKey));
    relations.unlocks?.forEach((unlockedKey) => addDependency(unlockedKey, issueKey));
    relations.related?.forEach((relatedKey) => addRelated(issueKey, relatedKey));
  });
}

wireScenarioRelationships("startup", {
  "QNT-127": {
    dependsOn: ["OPS-70"],
    unlocks: ["QNT-129", "QNT-131", "MEM-14"],
    related: ["GOV-23"],
  },
  "OPS-88": {
    dependsOn: ["OPS-70"],
    unlocks: ["PLT-55", "PLT-56"],
    related: ["QNT-127"],
  },
  "MEM-14": {
    dependsOn: ["QNT-127"],
    related: ["GOV-27", "MEM-18"],
  },
});

wireScenarioRelationships("active", {
  "QNT-127": {
    dependsOn: ["QNT-121"],
    unlocks: ["QNT-128", "QNT-133", "QNT-134", "MEM-32"],
    related: ["OPS-88", "GTH-204"],
  },
  "GTH-204": {
    dependsOn: ["GTH-197"],
    unlocks: ["GTH-205", "GTH-206", "GTH-209", "GTH-210"],
    related: ["QNT-127"],
  },
  "OPS-88": {
    dependsOn: ["OPS-97"],
    unlocks: ["OPS-99", "OPS-100", "OPS-101", "OPS-103"],
    related: ["QNT-127"],
  },
  "MEM-32": {
    dependsOn: ["QNT-127"],
    unlocks: ["MEM-33", "MEM-34", "MEM-35", "MEM-36"],
    related: ["MEM-28"],
  },
});

wireScenarioRelationships("resolving", {
  "GOV-41": {
    dependsOn: ["QNT-127", "OPS-88"],
    unlocks: ["MEM-41", "MEM-42"],
    related: ["GTH-211"],
  },
  "MEM-41": {
    dependsOn: ["OPS-88", "GOV-41"],
    unlocks: ["MEM-42", "MEM-43", "MEM-44"],
    related: ["MEM-30"],
  },
  "GTH-211": {
    dependsOn: ["QNT-127"],
    unlocks: ["GTH-213", "GTH-214", "GTH-215"],
    related: ["OPS-88"],
  },
});

const state = {
  scenario: "active",
  view: "command",
  project: "all",
  workMode: "board",
  selectedWorkIssue: "active-qnt-127",
  selectedIssuesIssue: "active-qnt-127",
  issuesTab: "queue",
  selectedAgent: "research",
};

function currentScenario() {
  return scenarios[state.scenario];
}

function toneClass(tone) {
  return `tone-${tone}`;
}

function projectName(projectId) {
  return projects.find((project) => project.id === projectId)?.name ?? "All programs";
}

function projectIdByName(name) {
  return projects.find((project) => project.name === name)?.id ?? "all";
}

function projectMatches(name) {
  return state.project === "all" || name === projectName(state.project);
}

function workIssues() {
  return currentScenario().work.issues.filter((issue) => projectMatches(issue.project));
}

function resolvedIssues() {
  return currentScenario().work.resolved.filter((issue) => projectMatches(issue.project));
}

function selectedWorkIssue() {
  const allVisible = [...workIssues(), ...resolvedIssues()];
  return allVisible.find((issue) => issue.id === state.selectedWorkIssue) ?? allVisible[0];
}

function selectedIssuesIssue() {
  const list = state.issuesTab === "queue" ? workIssues() : resolvedIssues();
  return list.find((issue) => issue.id === state.selectedIssuesIssue) ?? list[0];
}

function selectedAgent() {
  return agents.find((agent) => agent.id === state.selectedAgent) ?? agents[0];
}

function countsByStatus() {
  const items = workIssues();
  return {
    todo: items.filter((issue) => issue.status === "todo").length,
    inprogress: items.filter((issue) => issue.status === "inprogress").length,
    review: items.filter((issue) => issue.status === "review").length,
    blocked: items.filter((issue) => issue.status === "blocked").length,
    done: resolvedIssues().length,
  };
}

function groupIssues() {
  const items = workIssues();
  return {
    todo: items.filter((issue) => issue.status === "todo"),
    inprogress: items.filter((issue) => issue.status === "inprogress"),
    review: items.filter((issue) => issue.status === "review"),
    blocked: items.filter((issue) => issue.status === "blocked"),
    done: resolvedIssues(),
  };
}

function renderSidebar() {
  return `
    <aside class="sidebar">
      <div class="brand-row">
        <div class="brand-mark">◜</div>
        <strong>MAAS</strong>
      </div>

      <div class="avatar">M</div>

      <div class="sidebar-section">
        <button class="primary-action">Create issue</button>
        <div class="nav-list">
          ${[
            ["command", "Command"],
            ["work", "Work"],
            ["issues", "Issues"],
            ["agents", "Agents"],
            ["system", "System"],
          ]
            .map(
              ([id, label]) => `
                <button class="nav-item ${state.view === id ? "is-active" : ""}" data-view="${id}">
                  <span>${label}</span>
                  ${id === "work" ? `<span class="nav-meta">${countsByStatus().todo + countsByStatus().inprogress + countsByStatus().review + countsByStatus().blocked}</span>` : ""}
                </button>
              `,
            )
            .join("")}
        </div>
      </div>

      <div class="sidebar-section">
        <div class="section-label">Programs</div>
        <div class="project-list">
          ${projects
            .map((project) => {
              const count =
                project.id === "all"
                  ? currentScenario().metrics[0].value
                  : workIssues().filter((issue) => issue.project === project.name).length || currentScenario().issues.queue.filter((item) => item.project === project.name).length;
              return `
                <button class="project-item ${state.project === project.id ? "is-active" : ""}" data-project="${project.id}">
                  <span class="project-meta">
                    <span class="project-dot ${toneClass(project.tone)}"></span>
                    <span>${project.name}</span>
                  </span>
                  <span class="project-count">${count}</span>
                </button>
              `;
            })
            .join("")}
        </div>
      </div>

      <div class="sidebar-section">
        <div class="section-label">Live agents</div>
        <div class="agent-mini-list">
          ${agents
            .slice(0, 6)
            .map(
              (agent) => `
                <button class="agent-mini ${state.view === "agents" && state.selectedAgent === agent.id ? "is-active" : ""}" data-view="agents" data-agent="${agent.id}">
                  <span class="agent-mini-main">
                    <span>${agent.name}</span>
                  </span>
                  <span class="agent-mini-meta">${agent.status}</span>
                </button>
              `,
            )
            .join("")}
        </div>
      </div>
    </aside>
  `;
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

function renderHero() {
  const hero = currentScenario().hero;
  return `
    <article class="hero-panel">
      <div>
        <div class="hero-title">${hero.title}</div>
        <div class="hero-copy">${hero.copy}</div>
      </div>
      <span class="chip">${currentScenario().label}</span>
    </article>
  `;
}

function renderMetrics() {
  return `
    <section class="metrics-grid">
      ${currentScenario().metrics
        .map(
          (metric) => `
            <article class="metric-card">
              <div class="stat-value">${metric.value}</div>
              <div class="metric-title">${metric.label}</div>
              <div class="metric-note">${metric.note}</div>
            </article>
          `,
        )
        .join("")}
    </section>
  `;
}

function renderCommand() {
  const command = currentScenario().command;
  return `
    <section class="page">
      ${renderHeader("Command", `${projectName(state.project)} · approvals, pressure, and landed work`, `<button class="button">Run next cycle</button><button class="button">Pause autonomy</button>`)}
      ${renderScenarioSwitcher()}
      ${renderHero()}
      ${renderMetrics()}

      <section class="dashboard-grid">
        <article class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">Operator queue</div>
              <div class="panel-copy">Only the decisions that actually change throughput or risk.</div>
            </div>
          </div>
          <div class="queue-list">
            ${command.queue
              .filter((item) => projectMatches(item.project))
              .map(
                (item) => `
                  <div class="action-row">
                    <div class="row-title"><span class="issue-dot ${toneClass(item.tone)}"></span> ${item.title}</div>
                    <div class="row-copy">${item.copy}</div>
                    <div class="meta-line"><span>${item.project}</span></div>
                    <button class="button">${item.action}</button>
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
              <div class="panel-copy">Completed work that materially changed the state of the system.</div>
            </div>
          </div>
          <div class="stack">
            ${command.landed
              .filter((item) => projectMatches(item.project))
              .map(
                (item) => `
                  <div class="landed-row">
                    <div class="row-title">${item.key} · ${item.title}</div>
                    <div class="row-copy">${item.outcome}</div>
                    <div class="meta-line"><span>${item.project}</span><span>${item.time}</span></div>
                  </div>
                `,
              )
              .join("")}
          </div>
        </article>
      </section>

      <article class="panel history-panel">
        <div class="panel-head">
          <div>
            <div class="panel-title">Execution history</div>
            <div class="panel-copy">Git-like event flow: branches, approvals, failures, recoveries, and landed changes.</div>
          </div>
        </div>
        <div class="event-list">
          ${command.history
            .filter((item) => projectMatches(item.project))
            .map(
              (event) => `
                <div class="event-row">
                  <div class="event-track"><span class="event-dot ${toneClass(event.tone)}"></span></div>
                  <div class="event-main">
                    <div class="meta-line"><span class="branch-chip">${event.lane}</span><span>${event.project}</span></div>
                    <div class="row-title">${event.text}</div>
                  </div>
                  <div class="event-time">${event.time}</div>
                </div>
              `,
            )
            .join("")}
        </div>
      </article>
    </section>
  `;
}

function renderWorkList(items) {
  return `
    <div class="work-list">
      ${items
        .map(
          (issue) => `
            <button class="work-row ${selectedWorkIssue()?.id === issue.id ? "is-active" : ""}" data-work-issue="${issue.id}">
              <div class="work-main">
                <div class="row-title"><span class="issue-dot ${toneClass(issue.priority === "Critical" ? "yellow" : issue.status === "blocked" ? "red" : issue.status === "review" ? "yellow" : "blue")}"></span> ${issue.key} · ${issue.title}</div>
                <div class="meta-line">
                  <span>${issue.project}</span>
                  <span>${issue.goal}</span>
                  <span>${issue.assignees.join(", ")}</span>
                </div>
                <div class="row-copy">${issue.summary}</div>
                <div class="meta-line">
                  <span>${issue.dependsOn.length} deps</span>
                  <span>${issue.unlocks.length} unlocks</span>
                  <span>${issue.branches.length} branches</span>
                </div>
              </div>
              <div class="event-time">${issue.updated}</div>
            </button>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderBoardLane(title, key, items) {
  return `
    <section class="lane">
      <div class="lane-head">
        <div class="row-title">${title}</div>
        <div class="lane-count">${items.length}</div>
      </div>
      <div class="card-list">
        ${items
          .map(
            (issue) => `
              <button class="board-card ${selectedWorkIssue()?.id === issue.id ? "selected" : ""}" data-work-issue="${issue.id}">
                <div class="meta-line"><span class="branch-chip">${issue.key}</span><span>${issue.kind === "resolved" ? "Resolved" : issue.priority}</span></div>
                <div class="row-title">${issue.title}</div>
                <div class="row-copy">${issue.kind === "resolved" ? issue.resolvedBy : issue.assignees.join(", ")}</div>
                <div class="board-chip-row">
                  <span class="status-chip">${issue.branches.length} branches</span>
                  <span class="status-chip">${issue.dependsOn.length} deps</span>
                  <span class="status-chip">${issue.unlocks.length} unlocks</span>
                </div>
              </button>
            `,
          )
          .join("")}
      </div>
    </section>
  `;
}

function issueByKey(key) {
  return [...currentScenario().work.issues, ...currentScenario().work.resolved].find((issue) => issue.key === key);
}

function resolveIssueLinks(keys) {
  return keys.map((key) => issueByKey(key)).filter(Boolean);
}

function renderRelationshipItems(keys, emptyCopy) {
  const items = resolveIssueLinks(keys);
  if (!items.length) return `<div class="empty-copy">${emptyCopy}</div>`;
  return items
    .map(
      (item) => `
        <button class="relation-item" data-work-issue="${item.id}">
          <div class="meta-line"><span class="branch-chip">${item.key}</span><span>${item.kind === "resolved" ? "resolved" : item.status}</span></div>
          <div class="row-title">${item.title}</div>
          <div class="row-copy">${item.project}</div>
        </button>
      `,
    )
    .join("");
}

function renderResolvedBoardSummary(items) {
  const recent = items.slice(0, 6);
  return `
    <article class="resolved-board-summary">
      <div class="panel-head">
        <div>
          <div class="panel-title">Resolved work</div>
          <div class="panel-copy">The board only shows active flow. Completed work is summarized here and fully browsable in Issues → Resolved.</div>
        </div>
        <div class="summary-count">${items.length}</div>
      </div>
      <div class="resolved-preview-list">
        ${recent
          .map(
            (issue) => `
              <button class="resolved-preview ${selectedWorkIssue()?.id === issue.id ? "is-active" : ""}" data-work-issue="${issue.id}">
                <div class="row-title">${issue.key} · ${issue.title}</div>
                <div class="meta-line"><span>${issue.project}</span><span>${issue.closed}</span></div>
              </button>
            `,
          )
          .join("")}
      </div>
      <div class="resolved-summary-footer">
        <span class="chip">${items.length} total resolved in this view</span>
        <button class="button" data-open-resolved>Open resolved list</button>
      </div>
    </article>
  `;
}

function renderWorkDetail(issue) {
  if (!issue) return `<article class="panel"><div class="empty-copy">No issue selected.</div></article>`;
  if (issue.kind === "resolved") {
    return `
      <article class="work-detail">
        <section class="detail-card full">
          <div class="detail-head">
            <div>
              <div class="meta-line"><span class="branch-chip">${issue.key}</span><span>${issue.project}</span><span>Resolved</span></div>
              <h2>${issue.title}</h2>
              <p>${issue.outcome}</p>
            </div>
            <div class="detail-status">done</div>
          </div>
        </section>

        <section class="detail-grid">
          <article class="detail-card">
            <div class="panel-title">Resolved by</div>
            <div class="detail-copy">${issue.resolvedBy}</div>
            <div class="meta-line"><span>Closed ${issue.closed}</span></div>
          </article>
          <article class="detail-card">
            <div class="panel-title">Outputs</div>
            <div class="pill-row">
              ${issue.outputs.map((output) => `<span class="output-chip">${output}</span>`).join("")}
            </div>
          </article>
          <article class="detail-card full">
            <div class="panel-title">What this landing changed</div>
            <div class="relationship-stack">
              <section class="relationship-section">
                <div class="relationship-label">Built on</div>
                <div class="relationship-list scrollable">
                  ${renderRelationshipItems(issue.dependsOn, "No upstream issue is linked in this scenario view.")}
                </div>
              </section>
              <section class="relationship-section">
                <div class="relationship-label">Unlocked</div>
                <div class="relationship-list scrollable">
                  ${renderRelationshipItems(issue.unlocks, "No follow-up issue is linked in this scenario view.")}
                </div>
              </section>
            </div>
          </article>
          <article class="detail-card full">
            <div class="panel-title">Resolution history</div>
            <div class="event-list">
              ${issue.history
                .map(
                  (event) => `
                    <div class="event-row">
                      <div class="event-track"><span class="event-dot ${toneClass(event.tone)}"></span></div>
                      <div class="event-main">
                        <div class="meta-line"><span class="branch-chip">${event.lane}</span></div>
                        <div class="row-title">${event.text}</div>
                      </div>
                      <div class="event-time">${event.time}</div>
                    </div>
                  `,
                )
                .join("")}
            </div>
          </article>
        </section>
      </article>
    `;
  }
  return `
    <article class="work-detail">
      <section class="detail-card full">
        <div class="detail-head">
          <div>
            <div class="meta-line"><span class="branch-chip">${issue.key}</span><span>${issue.project}</span><span>${issue.goal}</span></div>
            <h2>${issue.title}</h2>
            <p>${issue.summary}</p>
          </div>
          <div class="detail-status">${issue.status}</div>
        </div>
      </section>

      <section class="detail-grid">
        <article class="detail-card">
          <div class="panel-title">Recommended next action</div>
          <div class="detail-copy">${issue.nextAction}</div>
          <div class="meta-line"><span>Blocked reason:</span><span>${issue.blockedReason}</span></div>
        </article>
        <article class="detail-card">
          <div class="panel-title">Outputs</div>
          <div class="pill-row">
            ${issue.outputs.map((output) => `<span class="output-chip">${output}</span>`).join("")}
          </div>
        </article>
        <article class="detail-card full">
          <div class="panel-title">Relationship map</div>
          <div class="relationship-stack">
            <section class="relationship-section">
              <div class="relationship-label">Depends on</div>
              <div class="relationship-list scrollable">
                ${renderRelationshipItems(issue.dependsOn, "No upstream dependencies are linked in this scenario view.")}
              </div>
            </section>
            <section class="relationship-section">
              <div class="relationship-label">Unlocks</div>
              <div class="relationship-list scrollable">
                ${renderRelationshipItems(issue.unlocks, "No downstream work is linked yet.")}
              </div>
            </section>
          </div>
          <div class="relationship-secondary">
            <div class="relationship-label">Related on the same goal</div>
            <div class="relationship-list scrollable compact">
              ${renderRelationshipItems(issue.related, "No closely related issues are linked yet.")}
            </div>
          </div>
        </article>
        <article class="detail-card full">
          <div class="panel-title">Active branches and subagents</div>
          <div class="branch-list">
            ${issue.branches
              .map(
                (branch) => `
                  <div class="branch-item">
                    <div class="meta-line"><span class="branch-chip">${branch.name}</span><span>${branch.owner}</span><span>${branch.state}</span></div>
                    <div class="row-copy">${branch.note}</div>
                  </div>
                `,
              )
              .join("")}
          </div>
        </article>
        <article class="detail-card full">
          <div class="panel-title">Run history</div>
          <div class="stack">
            ${issue.runs.length
              ? issue.runs
                  .map(
                    (run) => `
                      <div class="landed-row">
                        <div class="row-title">${run.id} · ${run.state}</div>
                        <div class="row-copy">${run.summary}</div>
                        <div class="meta-line"><span>${run.agent}</span></div>
                      </div>
                    `,
                  )
                  .join("")
              : `<div class="empty-copy">No direct runs recorded on this issue yet.</div>`}
          </div>
        </article>
        <article class="detail-card full">
          <div class="panel-title">Execution history</div>
          <div class="event-list">
            ${issue.history
              .map(
                (event) => `
                  <div class="event-row">
                    <div class="event-track"><span class="event-dot ${toneClass(event.tone)}"></span></div>
                    <div class="event-main">
                      <div class="meta-line"><span class="branch-chip">${event.lane}</span></div>
                      <div class="row-title">${event.text}</div>
                    </div>
                    <div class="event-time">${event.time}</div>
                  </div>
                `,
              )
              .join("")}
          </div>
        </article>
      </section>
    </article>
  `;
}

function renderWork() {
  const issue = selectedWorkIssue();
  const grouped = groupIssues();
  return `
    <section class="page">
      ${renderHeader("Work", `${projectName(state.project)} · same issues in list or kanban form`, `<button class="button">Run next issue</button><button class="button">Pause queue</button>`)}
      ${renderScenarioSwitcher()}
      ${renderHero()}
      <div class="toolbar work-controls">
        <button class="toolbar-button ${state.workMode === "list" ? "is-active" : ""}" data-work-mode="list">List</button>
        <button class="toolbar-button ${state.workMode === "board" ? "is-active" : ""}" data-work-mode="board">Board</button>
        <span class="chip">${countsByStatus().todo} todo</span>
        <span class="chip">${countsByStatus().inprogress} in progress</span>
        <span class="chip">${countsByStatus().review} review</span>
        <span class="chip">${countsByStatus().blocked} blocked</span>
        <span class="chip">${countsByStatus().done} done</span>
      </div>
      <section class="work-surface ${state.workMode === "board" ? "is-board" : ""}">
        <div class="work-surface-main">
          ${
            state.workMode === "list"
              ? renderWorkList(workIssues())
              : `<div class="kanban">
                  ${renderBoardLane("Todo", "todo", grouped.todo)}
                  ${renderBoardLane("In progress", "inprogress", grouped.inprogress)}
                  ${renderBoardLane("Review", "review", grouped.review)}
                  ${renderBoardLane("Blocked", "blocked", grouped.blocked)}
                </div>
                ${renderResolvedBoardSummary(grouped.done)}`
          }
        </div>
        ${renderWorkDetail(issue)}
      </section>
    </section>
  `;
}

function renderIssues() {
  const queue = currentScenario().issues.queue.filter((item) => projectMatches(item.project));
  const resolved = currentScenario().issues.resolved.filter((item) => projectMatches(item.project));
  const issue = selectedIssuesIssue();
  const source = state.issuesTab === "queue" ? workIssues() : resolvedIssues();
  const sourceByKey = new Map(source.map((item) => [item.key, item]));
  return `
    <section class="page">
      ${renderHeader("Issues", `${projectName(state.project)} · operator-facing decisions, failures, and resolutions`, `<button class="button">Search issues</button>`)}
      ${renderScenarioSwitcher()}
      <div class="tab-row">
        <button class="tab-button ${state.issuesTab === "queue" ? "is-active" : ""}" data-issues-tab="queue">Needs action</button>
        <button class="tab-button ${state.issuesTab === "resolved" ? "is-active" : ""}" data-issues-tab="resolved">Resolved</button>
      </div>
      <section class="issues-surface">
        <section class="issues-layout">
          <article class="panel issue-list">
            <div class="panel-head">
              <div>
                <div class="panel-title">${state.issuesTab === "queue" ? "Issue queue" : "Resolved issues"}</div>
                <div class="panel-copy">${state.issuesTab === "queue" ? "The operator-facing slice of work that needs judgment or recovery." : "Completed issues that landed and changed system state."}</div>
              </div>
            </div>
            <div class="stack">
              ${(state.issuesTab === "queue" ? queue : resolved)
                .map((row) => {
                  const issueSource = sourceByKey.get(row.issueKey ?? row.key);
                  const id = issueSource?.id ?? "";
                  return `
                    <button class="issue-row ${issue && issue.id === id ? "is-active" : ""}" ${id ? `data-issues-issue="${id}"` : "disabled"}>
                      <div class="issue-main">
                        <div class="row-title"><span class="issue-dot ${toneClass(row.tone ?? "green")}"></span> ${row.key ? `${row.key} · ` : ""}${row.title}</div>
                        <div class="row-copy">${row.copy ?? row.outcome}</div>
                        <div class="meta-line"><span>${row.project}</span><span>${row.age ?? row.closed}</span></div>
                      </div>
                    </button>
                  `;
                })
                .join("")}
            </div>
          </article>
          ${issue ? renderWorkDetail(issue) : `<article class="panel"><div class="empty-copy">Select an issue to inspect it.</div></article>`}
        </section>
      </section>
    </section>
  `;
}

function renderAgents() {
  const agent = selectedAgent();
  const owned = workIssues().filter((issue) => issue.assignees.includes(agent.name));
  const activeIssue = currentScenario().work.issues.find((issue) => issue.key === agent.currentIssue) ?? owned[0];
  const subagents =
    activeIssue?.branches
      .filter((branch) => branch.owner === agent.name || branch.owner.includes(agent.name) || branch.owner === "ReviewDesk")
      .slice(1)
      .map((branch, index) => ({
        name: `${agent.name}/subagent-${index + 1}`,
        role: branch.name,
        state: branch.state,
        note: branch.note,
      })) ??
    [];
  const recentEvents = currentScenario().command.history.slice(0, 4);
  return `
    <section class="page">
      ${renderHeader("Agents", `${agent.name} · ${agent.role} · ${projectName(state.project)}`, `<button class="button">Assign issue</button><button class="button">Pause agent</button>`)}
      ${renderScenarioSwitcher()}
      <section class="agents-columns">
        <article class="panel agent-list">
          <div class="panel-head">
            <div>
              <div class="panel-title">All agents</div>
              <div class="panel-copy">Who owns what, which subagents are spawned, and where work is actually moving.</div>
            </div>
          </div>
          <div class="stack">
            ${agents
              .map(
                (item) => `
                  <button class="agent-row ${state.selectedAgent === item.id ? "is-active" : ""}" data-agent="${item.id}">
                    <div class="agent-main">
                      <div class="row-title">${item.name}</div>
                      <div class="meta-line"><span>${item.role}</span><span>${item.project}</span><span>${item.currentIssue}</span></div>
                      <div class="row-copy">Status: ${item.status}</div>
                    </div>
                  </button>
                `,
              )
              .join("")}
          </div>
        </article>

        <article class="panel">
          <div class="detail-head">
            <div>
              <div class="meta-line"><span class="branch-chip">${agent.status}</span><span>${agent.project}</span></div>
              <h2>${agent.name}</h2>
              <p>${agent.role} working on ${agent.currentIssue}. This page shows ownership, spawned subagents, current outputs, and recent execution events.</p>
            </div>
          </div>
          <section class="agent-detail-grid">
            <article class="detail-card">
              <div class="panel-title">Current ownership</div>
              <div class="stack">
                ${owned.length
                  ? owned.map((issue) => `<div class="row-copy">${issue.key} · ${issue.title}</div>`).join("")
                  : `<div class="empty-copy">No active issue ownership in this project filter.</div>`}
              </div>
            </article>
            <article class="detail-card">
              <div class="panel-title">Agent health</div>
              <div class="stack">
                <div class="row-copy">Status: ${agent.status}</div>
                <div class="row-copy">Runtime: Codex CLI</div>
                <div class="row-copy">Last heartbeat: 18s ago</div>
                <div class="row-copy">Current issue: ${agent.currentIssue}</div>
              </div>
            </article>
            <article class="detail-card full">
              <div class="panel-title">Spawned subagents</div>
              <div class="agent-tree">
                <div class="tree-node">
                  <div class="row-title">${agent.name}</div>
                  <div class="row-copy">Main execution agent on ${agent.currentIssue}</div>
                </div>
                ${subagents
                  .length
                  ? subagents
                      .map(
                        (subagent) => `
                          <div class="tree-node child">
                            <div class="meta-line"><span class="branch-chip">${subagent.state}</span><span>${subagent.role}</span></div>
                            <div class="row-title">${subagent.name}</div>
                            <div class="row-copy">${subagent.note}</div>
                          </div>
                        `,
                      )
                      .join("")
                  : `<div class="empty-copy">No spawned subagent branches are visible for this agent in the current scenario.</div>`}
              </div>
            </article>
            <article class="detail-card full">
              <div class="panel-title">Recent agent events</div>
              <div class="event-list">
                ${recentEvents
                  .map(
                    (event) => `
                      <div class="event-row">
                        <div class="event-track"><span class="event-dot ${toneClass(event.tone)}"></span></div>
                        <div class="event-main">
                          <div class="meta-line"><span class="branch-chip">${event.lane}</span></div>
                          <div class="row-title">${event.text}</div>
                        </div>
                        <div class="event-time">${event.time}</div>
                      </div>
                    `,
                  )
                  .join("")}
              </div>
            </article>
          </section>
        </article>
      </section>
    </section>
  `;
}

function renderSystem() {
  const system = currentScenario().system;
  return `
    <section class="page">
      ${renderHeader("System", `${projectName(state.project)} · logs, metrics, traces, and machine health`, `<button class="button">Tail logs</button><button class="button">Open trace search</button>`)}
      ${renderScenarioSwitcher()}
      <section class="system-columns">
        <article class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">System metrics</div>
              <div class="panel-copy">Everything is logged, but only the machine-level state lives here.</div>
            </div>
          </div>
          <section class="stats-grid">
            ${system.metrics
              .map(
                (metric) => `
                  <article class="stat-card">
                    <div class="stat-value">${metric.value}</div>
                    <div class="stat-label">${metric.label}</div>
                    <div class="stat-note">${metric.note}</div>
                  </article>
                `,
              )
              .join("")}
          </section>

          <article class="panel history-panel">
            <div class="panel-head">
              <div>
                <div class="panel-title">Recent logs</div>
                <div class="panel-copy">Representative slice of the event and run log.</div>
              </div>
            </div>
            <div class="log-list">
              ${system.logs
                .map(
                  (line) => `
                    <div class="log-row">
                      <div class="row-copy">${line}</div>
                    </div>
                  `,
                )
                .join("")}
            </div>
          </article>
        </article>

        <article class="panel">
          <div class="trace-head">
            <div>
              <div class="panel-title">Selected trace</div>
              <div class="panel-copy">${system.trace.title}</div>
            </div>
            <span class="status-chip">Codex CLI</span>
          </div>
          <div class="trace-box">${system.trace.body}</div>

          <article class="panel history-panel">
            <div class="panel-head">
              <div>
                <div class="panel-title">Run and queue state</div>
                <div class="panel-copy">Machine-level queues and run health, separate from issue flow.</div>
              </div>
            </div>
            <div class="run-list">
              <div class="trace-row">
                <div class="row-title">codex/execution queue</div>
                <div class="row-copy">13 queued · 6 running · oldest wait 4m</div>
              </div>
              <div class="trace-row">
                <div class="row-title">review queue</div>
                <div class="row-copy">18 waiting · 2 above SLA</div>
              </div>
              <div class="trace-row">
                <div class="row-title">recovery queue</div>
                <div class="row-copy">1 repeated failure · 1 replan suggested</div>
              </div>
              <div class="trace-row">
                <div class="row-title">artifact pipeline</div>
                <div class="row-copy">All issue outputs linked and auditable</div>
              </div>
            </div>
          </article>
        </article>
      </section>
    </section>
  `;
}

function renderView() {
  if (state.view === "command") return renderCommand();
  if (state.view === "work") return renderWork();
  if (state.view === "issues") return renderIssues();
  if (state.view === "agents") return renderAgents();
  return renderSystem();
}

function render() {
  app.innerHTML = `
    <div class="shell">
      ${renderSidebar()}
      <main class="main">
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
      if (button.dataset.agent) state.selectedAgent = button.dataset.agent;
      render();
    });
  });

  app.querySelectorAll("[data-project]").forEach((button) => {
    button.addEventListener("click", () => {
      state.project = button.dataset.project;
      render();
    });
  });

  app.querySelectorAll("[data-scenario]").forEach((button) => {
    button.addEventListener("click", () => {
      state.scenario = button.dataset.scenario;
      state.selectedWorkIssue = scenarios[state.scenario].work.selectedIssueId;
      state.selectedIssuesIssue = scenarios[state.scenario].work.selectedIssueId;
      render();
    });
  });

  app.querySelectorAll("[data-work-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      state.workMode = button.dataset.workMode;
      render();
    });
  });

  app.querySelectorAll("[data-work-issue]").forEach((button) => {
    button.addEventListener("click", () => {
      const selectedId = button.dataset.workIssue;
      const targetIssue = [...currentScenario().work.issues, ...currentScenario().work.resolved].find((issue) => issue.id === selectedId);
      state.selectedWorkIssue = selectedId;
      state.selectedIssuesIssue = selectedId;
      if (targetIssue && state.project !== "all" && !projectMatches(targetIssue.project)) {
        state.project = projectIdByName(targetIssue.project);
      }
      render();
    });
  });

  app.querySelectorAll("[data-issues-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      state.issuesTab = button.dataset.issuesTab;
      render();
    });
  });

  app.querySelectorAll("[data-open-resolved]").forEach((button) => {
    button.addEventListener("click", () => {
      state.view = "issues";
      state.issuesTab = "resolved";
      const firstResolved = resolvedIssues()[0];
      if (firstResolved) state.selectedIssuesIssue = firstResolved.id;
      render();
    });
  });

  app.querySelectorAll("[data-issues-issue]").forEach((button) => {
    button.addEventListener("click", () => {
      const selectedId = button.dataset.issuesIssue;
      const targetIssue = [...currentScenario().work.issues, ...currentScenario().work.resolved].find((issue) => issue.id === selectedId);
      state.selectedIssuesIssue = selectedId;
      state.selectedWorkIssue = selectedId;
      if (targetIssue && state.project !== "all" && !projectMatches(targetIssue.project)) {
        state.project = projectIdByName(targetIssue.project);
      }
      render();
    });
  });

  app.querySelectorAll("[data-agent]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedAgent = button.dataset.agent;
      state.view = "agents";
      render();
    });
  });
}

render();
