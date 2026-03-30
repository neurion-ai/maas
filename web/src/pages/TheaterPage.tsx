import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { fetchTheater } from "../lib/controlRoomApi";
import { formatTimestamp, priorityLabel, statusLabel } from "../lib/codexMvp";
import { consumePendingAgentFocus, setPendingAgentFocus } from "../lib/agentFocus";
import { getSelectedProjectId, subscribeProjectScope } from "../lib/projectScope";
import { setPendingRunFocus } from "../lib/runFocus";
import { setPendingTaskFocus } from "../lib/taskFocus";
import { useLivePulse } from "../lib/useLivePulse";
import type { TheaterAgent, TheaterBranch, TheaterIssue, TheaterResponse, TheaterRun } from "../types";

type ViewTarget = "command" | "theater" | "work" | "issues" | "agents" | "runs" | "system" | "projects" | "settings";
type TheaterDockState = "attention" | "working" | "review_wait" | "idle";

const THEATER_DOCK_ORDER: TheaterDockState[] = ["attention", "working", "review_wait", "idle"];
const THEATER_DOCK_LABELS: Record<TheaterDockState, string> = {
  attention: "Needs attention",
  working: "Working off field",
  review_wait: "Waiting on review",
  idle: "Idle reserve",
};

function heartbeatLabel(seconds?: number | null) {
  if (seconds == null) {
    return "No heartbeat";
  }
  if (seconds < 60) {
    return `${seconds}s ago`;
  }
  return `${Math.round(seconds / 60)}m ago`;
}

function branchTone(branch: TheaterBranch) {
  if ((branch.dirty_file_count ?? 0) > 0) {
    return "warn";
  }
  if (!branch.is_active) {
    return "default";
  }
  return "good";
}

function issueTone(issue: TheaterIssue) {
  if (issue.lane_key === "blocked") {
    return "danger";
  }
  if (issue.lane_key === "review" || issue.lane_key === "delivery") {
    return "warn";
  }
  if (issue.lane_key === "in_progress") {
    return "good";
  }
  return "default";
}

function agentTone(agent: TheaterAgent) {
  if (agent.visual_state === "attention" || agent.visual_state === "blocked") {
    return "danger";
  }
  if (agent.visual_state === "review_wait") {
    return "warn";
  }
  if (agent.visual_state === "working") {
    return "good";
  }
  return "default";
}

function dockStateForAgent(agent: TheaterAgent): TheaterDockState {
  if (agent.visual_state === "attention" || agent.visual_state === "blocked") {
    return "attention";
  }
  if (agent.visual_state === "working") {
    return "working";
  }
  if (agent.visual_state === "review_wait") {
    return "review_wait";
  }
  return "idle";
}

function agentStatusLabel(agent: TheaterAgent, run?: TheaterRun | null) {
  if (run?.is_stale) {
    return "stale run";
  }
  if (run?.is_live) {
    return run.status.replaceAll("_", " ");
  }
  return agent.visual_state.replaceAll("_", " ");
}

function issueRunLabel(issue: TheaterIssue) {
  if (issue.current_run_stale) {
    return "Stale run";
  }
  if (issue.current_run_status) {
    return issue.current_run_status.replaceAll("_", " ");
  }
  return "No run";
}

function branchStatusLabel(branch: TheaterBranch, pr?: { state?: string | null; is_draft: boolean } | null) {
  if (pr?.is_draft) {
    return "draft PR";
  }
  if (pr?.state) {
    return pr.state.toLowerCase();
  }
  if (branch.lineage_state === "recent") {
    return "recent history";
  }
  if (branch.lineage_state === "historical") {
    return "history";
  }
  return branch.task_status?.replaceAll("_", " ") ?? "active";
}

function degradedReasonLabel(reason: "branch_lineage_unsupported" | "branch_lineage_empty" | "branch_lineage_capped") {
  if (reason === "branch_lineage_unsupported") {
    return "Git lineage is unavailable for this project.";
  }
  if (reason === "branch_lineage_empty") {
    return "No branch or worktree lineage exists yet.";
  }
  return "Theater is capping lineage rendering to keep the tree responsive.";
}

export function TheaterPage({ onNavigate }: { onNavigate: (view: ViewTarget) => void }) {
  const [payload, setPayload] = useState<TheaterResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(() => getSelectedProjectId());
  const [selectedIssueId, setSelectedIssueId] = useState<string | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(() => consumePendingAgentFocus());
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedBranchId, setSelectedBranchId] = useState<string | null>(null);
  const [expandedHistoryGroups, setExpandedHistoryGroups] = useState<Record<string, boolean>>({});
  const [fieldLayoutVersion, setFieldLayoutVersion] = useState(0);
  const [agentPositions, setAgentPositions] = useState<Record<string, { left: number; top: number }>>({});
  const livePulse = useLivePulse();
  const fieldRef = useRef<HTMLDivElement | null>(null);
  const lanesRef = useRef<HTMLDivElement | null>(null);
  const anchorRefs = useRef(new Map<string, HTMLDivElement>());

  useEffect(() => subscribeProjectScope(setSelectedProjectId), []);

  useEffect(() => {
    const controller = new AbortController();
    void fetchTheater(selectedProjectId, controller.signal, () => {
      setNotice("Theater is showing the latest cached topology because the live refresh failed.");
    })
      .then((snapshot) => {
        setPayload(snapshot);
        setNotice(null);
      })
      .catch((error) => {
        if (!(error instanceof Error && error.name === "AbortError")) {
          setNotice("Theater refresh failed.");
        }
      });
    return () => controller.abort();
  }, [livePulse, selectedProjectId]);

  useEffect(() => {
    if (!payload) {
      return;
    }
    setSelectedIssueId((current) =>
      current && payload.issues.some((issue) => issue.task_id === current) ? current : payload.issues[0]?.task_id ?? null
    );
    setSelectedAgentId((current) =>
      current && payload.agents.some((agent) => agent.agent_id === current) ? current : null
    );
    setSelectedRunId((current) =>
      current && payload.runs.some((run) => run.run_id === current) ? current : null
    );
    setSelectedBranchId((current) =>
      current && payload.branches.some((branch) => branch.branch_id === current) ? current : null
    );
  }, [payload]);

  const branchesById = useMemo(
    () => new Map((payload?.branches ?? []).map((branch) => [branch.branch_id, branch])),
    [payload?.branches]
  );
  const prsById = useMemo(
    () => new Map((payload?.pull_requests ?? []).map((pr) => [pr.pr_id, pr])),
    [payload?.pull_requests]
  );
  const runsById = useMemo(() => new Map((payload?.runs ?? []).map((run) => [run.run_id, run])), [payload?.runs]);
  const issueToBranch = useMemo(() => {
    const mapping = new Map<string, string>();
    for (const link of payload?.links.issue_to_branch ?? []) {
      mapping.set(link.issue_id, link.branch_id);
    }
    return mapping;
  }, [payload?.links.issue_to_branch]);
  const issueIds = useMemo(() => new Set((payload?.issues ?? []).map((issue) => issue.task_id)), [payload?.issues]);
  const selectedIssue = payload?.issues.find((issue) => issue.task_id === selectedIssueId) ?? null;
  const selectedBranch =
    (selectedBranchId ? branchesById.get(selectedBranchId) : null) ??
    (selectedIssue ? branchesById.get(issueToBranch.get(selectedIssue.task_id) ?? "") ?? null : null);
  const selectedRun =
    (selectedRunId ? payload?.runs.find((run) => run.run_id === selectedRunId) : null) ??
    (selectedIssue?.current_run_session_id
      ? payload?.runs.find((run) => run.run_id === selectedIssue.current_run_session_id) ?? null
      : null);
  const selectedAgent =
    (selectedAgentId ? payload?.agents.find((agent) => agent.agent_id === selectedAgentId) : null) ??
    (selectedIssue?.agent_id ? payload?.agents.find((agent) => agent.agent_id === selectedIssue.agent_id) ?? null : null);
  const selectedPr =
    (selectedBranch?.pr_id ? prsById.get(selectedBranch.pr_id) : null) ??
    (selectedIssue?.github_pr_url
      ? payload?.pull_requests.find((pr) => pr.url === selectedIssue.github_pr_url) ?? null
      : null);

  const issuesByLane = useMemo(() => {
    const grouped = new Map<string, TheaterIssue[]>();
    for (const lane of payload?.layout.issue_lanes ?? []) {
      grouped.set(lane.key, []);
    }
    for (const issue of payload?.issues ?? []) {
      grouped.set(issue.lane_key, [...(grouped.get(issue.lane_key) ?? []), issue]);
    }
    for (const [key, issues] of grouped.entries()) {
      issues.sort((left, right) => {
        if (left.priority !== right.priority) {
          return right.priority - left.priority;
        }
        return left.title.localeCompare(right.title);
      });
      grouped.set(key, issues);
    }
    return grouped;
  }, [payload?.issues, payload?.layout.issue_lanes]);

  const branchChildrenByParent = useMemo(() => {
    const grouped = new Map<string, TheaterBranch[]>();
    const branches = [...(payload?.branches ?? [])];
    branches.sort((left, right) => {
      if (left.lineage_state !== right.lineage_state) {
        return left.lineage_state === "active" ? -1 : 1;
      }
      if ((left.recency_rank ?? 0) !== (right.recency_rank ?? 0)) {
        return (left.recency_rank ?? 0) - (right.recency_rank ?? 0);
      }
      return left.branch_name.localeCompare(right.branch_name);
    });
    for (const branch of branches) {
      const key = branch.parent_branch_id ?? "__root__";
      grouped.set(key, [...(grouped.get(key) ?? []), branch]);
    }
    return grouped;
  }, [payload?.branches]);

  const branchSectionRootsByBase = useMemo(() => {
    const byBase = new Map<string, { active: string[]; history: string[] }>();
    for (const group of payload?.layout.branch_groups ?? []) {
      const visibleActiveIds = new Set(group.visible_active_branch_ids);
      const visibleHistoryIds = new Set(group.visible_history_branch_ids);
      const active = group.visible_active_branch_ids.filter((branchId) => {
        const branch = branchesById.get(branchId);
        if (!branch) {
          return false;
        }
        return !branch.parent_branch_id || !visibleActiveIds.has(branch.parent_branch_id);
      });
      const history = group.visible_history_branch_ids.filter((branchId) => {
        const branch = branchesById.get(branchId);
        if (!branch) {
          return false;
        }
        return !branch.parent_branch_id || !visibleHistoryIds.has(branch.parent_branch_id);
      });
      byBase.set(group.base_branch, { active, history });
    }
    return byBase;
  }, [branchesById, payload?.layout.branch_groups]);

  const visibleLineageBranchIds = useMemo(() => {
    const active = new Set<string>();
    const history = new Set<string>();
    for (const group of payload?.layout.branch_groups ?? []) {
      for (const branchId of group.visible_active_branch_ids) {
        active.add(branchId);
      }
      for (const branchId of group.visible_history_branch_ids) {
        history.add(branchId);
      }
    }
    return { active, history };
  }, [payload?.layout.branch_groups]);

  const highlightedBranchIds = useMemo(() => {
    if (!selectedBranch) {
      return new Set<string>();
    }
    const highlighted = new Set<string>();
    const visited = new Set<string>();
    let current: TheaterBranch | null = selectedBranch;
    while (current) {
      if (visited.has(current.branch_id)) {
        break;
      }
      visited.add(current.branch_id);
      highlighted.add(current.branch_id);
      current = current.parent_branch_id ? branchesById.get(current.parent_branch_id) ?? null : null;
    }
    const stack = [selectedBranch.branch_id];
    while (stack.length) {
      const branchId = stack.pop();
      if (!branchId) {
        continue;
      }
      for (const child of branchChildrenByParent.get(branchId) ?? []) {
        if (highlighted.has(child.branch_id)) {
          continue;
        }
        highlighted.add(child.branch_id);
        stack.push(child.branch_id);
      }
    }
    return highlighted;
  }, [branchChildrenByParent, branchesById, selectedBranch]);

  useEffect(() => {
    if (!selectedBranch || selectedBranch.lineage_state === "active") {
      return;
    }
    const base = selectedBranch.lineage_root_base ?? selectedBranch.base_branch ?? "unbased";
    setExpandedHistoryGroups((current) => (current[base] ? current : { ...current, [base]: true }));
  }, [selectedBranch]);

  const fieldAgents = useMemo(() => {
    const attached = new Map<string, TheaterAgent[]>();
    const docked: Record<TheaterDockState, TheaterAgent[]> = {
      attention: [],
      working: [],
      review_wait: [],
      idle: [],
    };

    for (const agent of payload?.agents ?? []) {
      if (agent.current_task_id && issueIds.has(agent.current_task_id)) {
        attached.set(agent.current_task_id, [...(attached.get(agent.current_task_id) ?? []), agent]);
        continue;
      }
      docked[dockStateForAgent(agent)].push(agent);
    }

    for (const [taskId, agents] of attached.entries()) {
      agents.sort((left, right) => left.name.localeCompare(right.name));
      attached.set(taskId, agents);
    }
    for (const key of THEATER_DOCK_ORDER) {
      docked[key].sort((left, right) => left.name.localeCompare(right.name));
    }

    return { attached, docked };
  }, [payload?.agents, issueIds]);

  const anchorKeyForAgent = useMemo(
    () => (agent: TheaterAgent) => {
      if (agent.current_task_id && issueIds.has(agent.current_task_id)) {
        return `issue:${agent.current_task_id}:${agent.agent_id}`;
      }
      return `dock:${dockStateForAgent(agent)}:${agent.agent_id}`;
    },
    [issueIds]
  );

  useEffect(() => {
    const field = fieldRef.current;
    if (!field || typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver(() => {
      setFieldLayoutVersion((current) => current + 1);
    });
    observer.observe(field);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const lanes = lanesRef.current;
    if (!lanes) {
      return;
    }
    let frame = 0;
    function handleScroll() {
      if (frame) {
        return;
      }
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        setFieldLayoutVersion((current) => current + 1);
      });
    }
    lanes.addEventListener("scroll", handleScroll, { passive: true });
    return () => {
      lanes.removeEventListener("scroll", handleScroll);
      if (frame) {
        window.cancelAnimationFrame(frame);
      }
    };
  }, []);

  useEffect(() => {
    function handleResize() {
      setFieldLayoutVersion((current) => current + 1);
    }
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  useLayoutEffect(() => {
    const field = fieldRef.current;
    if (!field || !payload) {
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      const fieldRect = field.getBoundingClientRect();
      const next: Record<string, { left: number; top: number }> = {};
      for (const agent of payload.agents) {
        const anchor = anchorRefs.current.get(anchorKeyForAgent(agent));
        if (!anchor) {
          continue;
        }
        const rect = anchor.getBoundingClientRect();
        next[agent.agent_id] = {
          left: rect.left - fieldRect.left + rect.width / 2,
          top: rect.top - fieldRect.top + rect.height / 2,
        };
      }
      setAgentPositions((current) => {
        let changed = Object.keys(current).length !== Object.keys(next).length;
        if (!changed) {
          for (const [agentId, nextPosition] of Object.entries(next)) {
            const currentPosition = current[agentId];
            if (
              !currentPosition ||
              Math.abs(currentPosition.left - nextPosition.left) > 0.5 ||
              Math.abs(currentPosition.top - nextPosition.top) > 0.5
            ) {
              changed = true;
              break;
            }
          }
        }
        return changed ? next : current;
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [anchorKeyForAgent, fieldLayoutVersion, payload]);

  function anchorRef(key: string) {
    return (node: HTMLDivElement | null) => {
      if (node) {
        anchorRefs.current.set(key, node);
      } else {
        anchorRefs.current.delete(key);
      }
    };
  }

  function focusIssue(issue: TheaterIssue) {
    setSelectedIssueId(issue.task_id);
    setSelectedAgentId(issue.agent_id ?? null);
    setSelectedRunId(issue.current_run_session_id ?? null);
    setSelectedBranchId(issueToBranch.get(issue.task_id) ?? null);
  }

  function focusBranch(branch: TheaterBranch) {
    setSelectedBranchId(branch.branch_id);
    setSelectedIssueId(branch.linked_task_count === 1 ? branch.task_id ?? null : null);
    setSelectedAgentId(branch.linked_task_count === 1 ? branch.agent_id ?? null : null);
    setSelectedRunId(branch.linked_task_count === 1 ? branch.run_id ?? null : null);
  }

  function focusAgent(agent: TheaterAgent) {
    setSelectedAgentId(agent.agent_id);
    setSelectedIssueId(agent.current_task_id ?? null);
    setSelectedRunId(agent.current_run_id ?? null);
    setSelectedBranchId(agent.current_task_id ? issueToBranch.get(agent.current_task_id) ?? null : null);
  }

  function focusRun(run: TheaterRun) {
    setSelectedRunId(run.run_id);
    setSelectedIssueId(run.task_id ?? null);
    setSelectedAgentId(run.agent_id ?? null);
    setSelectedBranchId(run.task_id ? issueToBranch.get(run.task_id) ?? null : null);
  }

  function toggleHistoryGroup(baseBranch: string) {
    setExpandedHistoryGroups((current) => ({ ...current, [baseBranch]: !current[baseBranch] }));
  }

  function renderLineageBranch(branchId: string, mode: "active" | "historical") {
    const branch = branchesById.get(branchId);
    if (!branch) {
      return null;
    }
    const linkedPr = branch.pr_id ? prsById.get(branch.pr_id) ?? null : null;
    const isSelected = selectedBranch?.branch_id === branch.branch_id;
    const isContext = highlightedBranchIds.has(branch.branch_id);
    const childMode = mode === "active" ? "active" : "historical";
    const visibleChildIds = childMode === "active" ? visibleLineageBranchIds.active : visibleLineageBranchIds.history;
    const children = (branchChildrenByParent.get(branch.branch_id) ?? []).filter((child) =>
      (childMode === "active" ? child.lineage_state === "active" : child.lineage_state !== "active") &&
      visibleChildIds.has(child.branch_id)
    );

    return (
      <div key={branch.branch_id} className="codex-theater-tree__node">
        <button
          type="button"
          className={`codex-theater-branch codex-theater-branch--${branchTone(branch)} ${isSelected ? "is-selected" : ""} ${isContext && !isSelected ? "is-context" : ""}`}
          onClick={() => focusBranch(branch)}
        >
          <div className="codex-theater-branch__top">
            <strong>{branch.branch_name}</strong>
            <span>{branchStatusLabel(branch, linkedPr)}</span>
          </div>
          <div className="codex-theater-branch__meta">
            <span>
              {branch.linked_task_count && branch.linked_task_count > 1
                ? `${branch.linked_task_count} linked issues`
                : branch.issue_key ?? branch.task_id ?? "No issue"}
            </span>
            <span>{branch.agent_name ?? "No owner"}</span>
            <span>{(branch.dirty_file_count ?? 0) > 0 ? `${branch.dirty_file_count} dirty` : "clean"}</span>
          </div>
          <p>{branch.change_summary ?? branch.worktree_path ?? "No worktree summary recorded yet."}</p>
          <div className="codex-theater-branch__chips">
            {branch.base_branch ? <span className="codex-chip">Base: {branch.base_branch}</span> : null}
            {branch.pr_base_branch && branch.pr_base_branch !== branch.base_branch ? (
              <span className="codex-chip">Merge target: {branch.pr_base_branch}</span>
            ) : null}
            {branch.has_tracked_base ? <span className="codex-chip">Stacked branch</span> : null}
            {branch.linked_task_count && branch.linked_task_count > 1 ? <span className="codex-chip">Shared branch</span> : null}
            {branch.run_status ? <span className="codex-chip">Run: {branch.run_status.replaceAll("_", " ")}</span> : null}
            {linkedPr ? (
              <span className="codex-chip">
                PR #{linkedPr.number ?? "draft"} {linkedPr.state?.toLowerCase() ?? "open"}
              </span>
            ) : null}
            {branch.latest_activity_at ? (
              <span className="codex-chip">Updated {formatTimestamp(branch.latest_activity_at)}</span>
            ) : null}
          </div>
        </button>
        {children.length ? <div className="codex-theater-tree__children">{children.map((child) => renderLineageBranch(child.branch_id, childMode))}</div> : null}
      </div>
    );
  }

  return (
    <section className="codex-page codex-theater-page">
      <header className="codex-page__header">
        <div>
          <span className="codex-kicker">Theater</span>
          <h1>Watch live issue ownership, run posture, and branch lineage in one operational field</h1>
          <p>
            Theater is the cross-surface execution map. It keeps issue lanes, current agent ownership, live runs, and
            branch or PR lineage in one project-scoped view without replacing the existing task, run, or agent detail
            surfaces.
          </p>
        </div>
        <div className="codex-page__actions">
          {payload?.summary.branch_data_state !== "available" ? (
            <span className="codex-chip">
              {payload?.summary.branch_data_state === "unsupported" ? "Git lineage unavailable" : "No branch lineage yet"}
            </span>
          ) : null}
          {payload?.summary.brownfield_trust ? (
            <span className="codex-chip">Brownfield trust: {payload.summary.brownfield_trust.replaceAll("_", " ")}</span>
          ) : null}
        </div>
      </header>

      {notice ? <div className="codex-banner">{notice}</div> : null}

      <div className="codex-theater-summary">
        <article className="codex-metric-card">
          <span className="codex-kicker">Active field</span>
          <strong>{payload?.summary.active_issue_count ?? 0}</strong>
          <span>{payload?.summary.issue_count ?? 0} total issues in topology</span>
        </article>
        <article className="codex-metric-card">
          <span className="codex-kicker">Agents</span>
          <strong>{payload?.summary.agent_count ?? 0}</strong>
          <span>{payload?.summary.active_run_count ?? 0} live runs linked</span>
        </article>
        <article className="codex-metric-card">
          <span className="codex-kicker">Branches</span>
          <strong>{payload?.summary.branch_count ?? 0}</strong>
          <span>{payload?.summary.pull_request_count ?? 0} linked pull requests</span>
        </article>
        <article className="codex-metric-card">
          <span className="codex-kicker">Project</span>
          <strong>{payload?.project?.name ?? "No active project"}</strong>
          <span>{payload?.project?.description ?? "Select a project to render Theater."}</span>
        </article>
      </div>

      <div className="codex-theater-panel codex-panel">
        <div className="codex-panel__header">
          <div>
            <span className="codex-kicker">Execution Field</span>
            <h2>Issue lanes stay stable while agents and runs move through them</h2>
          </div>
          <span className="codex-empty-copy">
            Click a card, agent, or run to focus the linked topology and open the underlying surface only when you need
            to act.
          </span>
        </div>
        <div className="codex-theater-field" ref={fieldRef}>
          <div className="codex-theater-agent-dock">
            <header className="codex-theater-agent-dock__header">
              <strong>Agent motion</strong>
              <span>{payload?.agents.length ?? 0} live tokens attach to issue ownership and runtime changes</span>
            </header>
            <div className="codex-theater-agent-dock__grid">
              {THEATER_DOCK_ORDER.map((dockState) => {
                const agents = fieldAgents.docked[dockState];
                return (
                  <section key={dockState} className="codex-theater-agent-dock__group">
                    <header className="codex-theater-agent-dock__group-header">
                      <strong>{THEATER_DOCK_LABELS[dockState]}</strong>
                      <span>{agents.length}</span>
                    </header>
                    <div className="codex-theater-agent-dock__slots">
                      {agents.length ? (
                        agents.map((agent) => (
                          <div
                            key={agent.agent_id}
                            ref={anchorRef(`dock:${dockState}:${agent.agent_id}`)}
                            className={`codex-theater-agent-anchor codex-theater-agent-anchor--${agentTone(agent)}`}
                          />
                        ))
                      ) : (
                        <div className="codex-empty-copy">No agents in this posture.</div>
                      )}
                    </div>
                  </section>
                );
              })}
            </div>
          </div>

          <div className="codex-theater-lanes" role="list" aria-label="Execution lanes" ref={lanesRef}>
            {(payload?.layout.issue_lanes ?? []).map((lane) => {
              const laneIssues = issuesByLane.get(lane.key) ?? [];
              return (
                <section key={lane.key} className="codex-theater-lane" role="listitem">
                  <header className="codex-theater-lane__header">
                    <strong>{lane.label}</strong>
                    <span>{laneIssues.length}</span>
                  </header>
                  <div className="codex-theater-lane__body">
                    {laneIssues.length ? (
                      laneIssues.map((issue) => {
                        const isSelected =
                          selectedIssue?.task_id === issue.task_id ||
                          selectedBranch?.task_id === issue.task_id ||
                          selectedRun?.task_id === issue.task_id ||
                          selectedAgent?.current_task_id === issue.task_id;
                        const assignedAgents = fieldAgents.attached.get(issue.task_id) ?? [];
                        return (
                          <button
                            key={issue.task_id}
                            type="button"
                            className={`codex-theater-card codex-theater-card--${issueTone(issue)} ${isSelected ? "is-selected" : ""}`}
                            onClick={() => focusIssue(issue)}
                          >
                            <div className="codex-theater-card__top">
                              <span className="codex-theater-card__issue-key">{issue.issue_key ?? issue.task_id}</span>
                              <span className={`codex-status-chip codex-status-chip--${issue.status}`}>
                                {statusLabel(issue.status, issue.review_state)}
                              </span>
                            </div>
                            <strong>{issue.title}</strong>
                            <p>
                              {issue.blocked_reason
                                ? issue.blocked_reason.replaceAll("_", " ")
                                : issue.delivery_summary ?? issue.goal_title ?? "No additional execution summary."}
                            </p>
                            <div className="codex-theater-card__meta">
                              <span>{priorityLabel(issue.priority)}</span>
                              <span>{issue.agent_name ?? "Unassigned"}</span>
                              <span>{issueRunLabel(issue)}</span>
                            </div>
                            <div className="codex-theater-card__chips">
                              {issue.git_workspace_branch ? <span className="codex-chip">{issue.git_workspace_branch}</span> : null}
                              {issue.latest_verification_status ? (
                                <span className="codex-chip">Verify: {issue.latest_verification_status}</span>
                              ) : null}
                              {issue.delivery_state ? <span className="codex-chip">Delivery: {issue.delivery_state}</span> : null}
                            </div>
                            <div className="codex-theater-card__agent-row">
                              <div className="codex-theater-card__agent-copy">
                                <strong>Agent slots</strong>
                                <span>
                                  {assignedAgents.length
                                    ? `${assignedAgents.length} attached ${assignedAgents.length === 1 ? "token" : "tokens"}`
                                    : "Awaiting ownership"}
                                </span>
                              </div>
                              <div className="codex-theater-card__agent-slots" aria-hidden="true">
                                {assignedAgents.length ? (
                                  assignedAgents.map((agent) => (
                                    <div
                                      key={agent.agent_id}
                                      ref={anchorRef(`issue:${issue.task_id}:${agent.agent_id}`)}
                                      className={`codex-theater-agent-anchor codex-theater-agent-anchor--${agentTone(agent)}`}
                                    />
                                  ))
                                ) : (
                                  <div className="codex-theater-agent-anchor codex-theater-agent-anchor--empty" />
                                )}
                              </div>
                            </div>
                          </button>
                        );
                      })
                    ) : (
                      <div className="codex-empty-copy">No issues in this lane.</div>
                    )}
                  </div>
                </section>
              );
            })}
          </div>

          <div className="codex-theater-agent-overlay">
            {(payload?.agents ?? []).map((agent) => {
              const position = agentPositions[agent.agent_id];
              const linkedRun = agent.current_run_id ? runsById.get(agent.current_run_id) ?? null : null;
              const isSelected =
                selectedAgent?.agent_id === agent.agent_id ||
                selectedIssue?.task_id === agent.current_task_id ||
                selectedRun?.agent_id === agent.agent_id;
              if (!position) {
                return null;
              }
              return (
                <button
                  key={agent.agent_id}
                  type="button"
                  className={`codex-theater-agent-token codex-theater-agent-token--${agentTone(agent)} ${isSelected ? "is-selected" : ""}`}
                  style={{ left: position.left, top: position.top }}
                  onClick={() => focusAgent(agent)}
                  aria-label={`Focus agent ${agent.name}`}
                >
                  <strong>{agent.name}</strong>
                  <span>{agentStatusLabel(agent, linkedRun)}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <div className="codex-theater-bottom">
        <div className="codex-theater-panel codex-panel">
          <div className="codex-panel__header">
          <div>
            <span className="codex-kicker">Lineage</span>
            <h2>Branch, worktree, and PR lineage keeps active work on top</h2>
          </div>
          {payload?.summary.lineage_render_limits ? (
            <span className="codex-empty-copy">
              {payload.summary.lineage_render_limits.visible_active_count} active / {payload.summary.lineage_render_limits.visible_history_count} history visible
            </span>
          ) : null}
        </div>
          {payload?.summary.degraded_reasons?.length ? (
            <div className="codex-theater-degraded-list">
              {payload.summary.degraded_reasons.map((reason) => (
                <div key={reason} className="codex-banner codex-theater-degraded-list__item">
                  {degradedReasonLabel(reason)}
                </div>
              ))}
            </div>
          ) : null}
          <div className="codex-theater-tree">
            {(payload?.layout.branch_groups ?? []).map((group) => (
              <section key={group.base_branch} className="codex-theater-tree__group">
                <header className="codex-theater-tree__header">
                        <strong>{group.base_branch === "unbased" ? "No base branch recorded" : group.base_branch}</strong>
                  <span>
                    {group.active_count} active / {group.history_count} history
                  </span>
                </header>
                <div className="codex-theater-tree__items">
                  {(branchSectionRootsByBase.get(group.base_branch)?.active ?? []).length ? (
                    <div className="codex-theater-tree__section">
                      <div className="codex-theater-tree__section-header">
                        <strong>Active line</strong>
                        <span>
                          {group.visible_active_branch_ids.length}
                          {group.hidden_active_count ? ` of ${group.active_count}` : ""}
                        </span>
                      </div>
                      <div className="codex-theater-tree__stack">
                        {(branchSectionRootsByBase.get(group.base_branch)?.active ?? []).map((branchId) =>
                          renderLineageBranch(branchId, "active")
                        )}
                      </div>
                      {group.hidden_active_count ? (
                        <div className="codex-empty-copy">
                          {group.hidden_active_count} active branches are currently hidden by the render cap.
                        </div>
                      ) : null}
                    </div>
                  ) : group.active_count ? (
                    <div className="codex-empty-copy">
                      Active branches exist for this line, but they are currently hidden by the render cap.
                    </div>
                  ) : (
                    <div className="codex-empty-copy">No active branches in this line.</div>
                  )}
                  {group.history_count ? (
                    <div className="codex-theater-tree__section codex-theater-tree__section--history">
                      <div className="codex-theater-tree__section-header">
                        <strong>Recent history</strong>
                        <button
                          type="button"
                          className="codex-button codex-button--ghost"
                          onClick={() => toggleHistoryGroup(group.base_branch)}
                        >
                          {expandedHistoryGroups[group.base_branch]
                            ? "Hide history"
                            : `Show ${group.visible_history_branch_ids.length}${group.hidden_history_count ? ` of ${group.history_count}` : ""} branches`}
                        </button>
                      </div>
                      {expandedHistoryGroups[group.base_branch] ? (
                        <div className="codex-theater-tree__stack codex-theater-tree__stack--history">
                          {(branchSectionRootsByBase.get(group.base_branch)?.history ?? []).map((branchId) =>
                            renderLineageBranch(branchId, "historical")
                          )}
                        </div>
                      ) : (
                        <div className="codex-empty-copy">
                          Historical branches stay collapsed until you need their lineage or merge context.
                        </div>
                      )}
                      {group.hidden_history_count ? (
                        <div className="codex-empty-copy">
                          {group.hidden_history_count} older history branches are hidden to keep Theater responsive.
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              </section>
            ))}
            {!payload?.branches.length &&
            payload?.summary.branch_data_state !== "unsupported" &&
            !payload?.summary.degraded_reasons?.includes("branch_lineage_empty") ? (
              <div className="codex-empty-copy">No branch or worktree lineage exists yet.</div>
            ) : null}
          </div>
        </div>

        <aside className="codex-theater-panel codex-panel codex-theater-focus">
          <div className="codex-panel__header">
            <div>
              <span className="codex-kicker">Focus</span>
              <h2>{selectedIssue?.title ?? selectedBranch?.branch_name ?? selectedAgent?.name ?? selectedRun?.task_title ?? "No focus selected"}</h2>
            </div>
          </div>

          <section className="codex-detail-section">
            <div className="codex-section-heading">
              <strong>Issue</strong>
              <span>{selectedIssue?.issue_key ?? "None"}</span>
            </div>
            {selectedIssue ? (
              <>
                <div className="codex-detail-card">
                  <strong>{selectedIssue.title}</strong>
                  <p>{selectedIssue.delivery_summary ?? selectedIssue.goal_title ?? "No extra issue summary recorded."}</p>
                  <div className="codex-detail-card__meta">
                    <span>{statusLabel(selectedIssue.status, selectedIssue.review_state)}</span>
                    <span>{priorityLabel(selectedIssue.priority)}</span>
                    <span>{selectedIssue.agent_name ?? "Unassigned"}</span>
                  </div>
                </div>
                <div className="codex-detail-actions">
                  <button
                    type="button"
                    className="codex-button codex-button--primary"
                    onClick={() => {
                      setPendingTaskFocus(selectedIssue.task_id);
                      onNavigate("work");
                    }}
                  >
                    Open issue
                  </button>
                  {selectedIssue.current_run_session_id ? (
                    <button
                      type="button"
                      className="codex-button"
                      onClick={() => {
                        setPendingRunFocus(selectedIssue.current_run_session_id ?? null);
                        onNavigate("runs");
                      }}
                    >
                      Open run
                    </button>
                  ) : null}
                </div>
              </>
            ) : (
              <div className="codex-empty-copy">Select an issue from the execution field.</div>
            )}
          </section>

          <section className="codex-detail-section">
            <div className="codex-section-heading">
              <strong>Agent</strong>
              <span>{selectedAgent?.visual_state?.replaceAll("_", " ") ?? "None"}</span>
            </div>
            {selectedAgent ? (
              <>
                <button
                  type="button"
                  className={`codex-theater-focus-chip codex-theater-focus-chip--${agentTone(selectedAgent)}`}
                  onClick={() => focusAgent(selectedAgent)}
                >
                  <strong>{selectedAgent.name}</strong>
                  <span>{selectedAgent.role}</span>
                  <span>{heartbeatLabel(selectedAgent.last_heartbeat_age_seconds)}</span>
                </button>
                <div className="codex-detail-actions">
                  <button
                    type="button"
                    className="codex-button"
                    onClick={() => {
                      setPendingAgentFocus(selectedAgent.agent_id);
                      onNavigate("agents");
                    }}
                  >
                    Open agent
                  </button>
                </div>
              </>
            ) : (
              <div className="codex-empty-copy">Select an agent token or issue owner.</div>
            )}
          </section>

          <section className="codex-detail-section">
            <div className="codex-section-heading">
              <strong>Run</strong>
              <span>{selectedRun?.status?.replaceAll("_", " ") ?? "None"}</span>
            </div>
            {selectedRun ? (
              <>
                <button
                  type="button"
                  className={`codex-theater-focus-chip codex-theater-focus-chip--${selectedRun.is_stale ? "danger" : selectedRun.is_live ? "good" : "default"}`}
                  onClick={() => focusRun(selectedRun)}
                >
                  <strong>{selectedRun.task_title ?? selectedRun.issue_key ?? selectedRun.run_id}</strong>
                  <span>{selectedRun.execution_mode ?? "runtime"}</span>
                  <span>{selectedRun.status_message ?? heartbeatLabel(selectedRun.heartbeat_age_seconds)}</span>
                </button>
                <div className="codex-detail-actions">
                  <button
                    type="button"
                    className="codex-button"
                    onClick={() => {
                      setPendingRunFocus(selectedRun.run_id);
                      onNavigate("runs");
                    }}
                  >
                    Open run
                  </button>
                </div>
              </>
            ) : (
              <div className="codex-empty-copy">Select a linked run from the issue field or lineage tree.</div>
            )}
          </section>

          <section className="codex-detail-section">
            <div className="codex-section-heading">
              <strong>Branch / PR</strong>
              <span>{selectedBranch?.branch_name ?? "None"}</span>
            </div>
            {selectedBranch ? (
              <>
                <div className="codex-detail-card">
                  <strong>{selectedBranch.branch_name}</strong>
                  <p>{selectedBranch.worktree_path ?? selectedBranch.change_summary ?? "No worktree path recorded."}</p>
                  <div className="codex-detail-card__meta">
                    <span>{selectedBranch.base_branch ?? "No base"}</span>
                    <span>{(selectedBranch.dirty_file_count ?? 0) > 0 ? `${selectedBranch.dirty_file_count} dirty` : "clean"}</span>
                    <span>{selectedBranch.issue_key ?? selectedBranch.task_id ?? "No issue"}</span>
                  </div>
                </div>
                <div className="codex-detail-actions">
                  {selectedPr?.url ? (
                    <a className="codex-button" href={selectedPr.url} target="_blank" rel="noreferrer">
                      Open PR
                    </a>
                  ) : null}
                  {selectedIssue ? (
                    <button
                      type="button"
                      className="codex-button"
                      onClick={() => {
                        setPendingTaskFocus(selectedIssue.task_id);
                        onNavigate("issues");
                      }}
                    >
                      Open issue detail
                    </button>
                  ) : null}
                </div>
              </>
            ) : (
              <div className="codex-empty-copy">Select a branch from the lineage tree.</div>
            )}
          </section>
        </aside>
      </div>
    </section>
  );
}
