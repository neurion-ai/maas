import { useEffect, useMemo, useState } from "react";
import {
  fetchAgentRoster,
  fetchArtifactDetail,
  fetchArtifacts,
  fetchGoalTree,
  fetchIncidentTimeline,
  fetchOverview,
  fetchPortfolio,
  fetchRecoveryPolicy,
  recoverAgent,
  resetTaskCircuitBreaker,
  resetTaskRetryState,
  restoreAndRequeueQuarantineEntry,
  restoreQuarantineEntry,
  runAlertOperatorAction,
  runOrchestratorPass,
  runSupervisorPass
} from "../lib/controlRoomApi";
import {
  fetchBoard,
  finishTaskReplan,
  markTaskForReplan,
  prepareTaskGitWorkspace,
  recoverAndRequeueTask,
  recoverTask,
  refreshTaskGitDiff,
  reviewTask,
  runTaskVerification
} from "../lib/boardApi";
import { assignNextTask } from "../lib/controlRoomApi";
import { useLivePulse } from "../lib/useLivePulse";
import type {
  ActivityItem,
  AgentRosterEntry,
  AgentRosterResponse,
  AlertOperatorAction,
  ArtifactDetail,
  ArtifactsResponse,
  BoardColumn,
  BoardResponse,
  BoardTask,
  GoalTreeNode,
  GoalTreeResponse,
  OverviewResponse,
  PortfolioResponse,
  RecoveryPolicyResponse,
  TimelineResponse
} from "../types";

type HomeViewTarget = "work" | "runs" | "incidents" | "projects";

interface HomePageProps {
  onNavigate: (view: HomeViewTarget) => void;
}

interface AttentionItem {
  id: string;
  tone: "critical" | "warn" | "default";
  label: string;
  summary: string;
  meta?: string;
  actionLabel?: string;
  action?: () => Promise<void>;
}

interface TickerItem {
  id: string;
  title: string;
  summary: string;
  createdAt: string;
  tone: "critical" | "warn" | "default";
  count?: number;
  taskId?: string | null;
  agentId?: string | null;
}

function formatTime(value?: string | null) {
  if (!value) {
    return "Not recorded";
  }
  return new Date(value).toLocaleString();
}

function formatHeartbeat(seconds?: number | null) {
  if (seconds == null) {
    return "No heartbeat";
  }
  if (seconds < 60) {
    return `${seconds}s`;
  }
  return `${Math.round(seconds / 60)}m`;
}

function formatPriority(priority: number) {
  if (priority >= 90) return "P0";
  if (priority >= 75) return "P1";
  if (priority >= 50) return "P2";
  return "P3";
}

function formatList(items?: string[] | null, limit = 4) {
  const values = (items ?? []).filter(Boolean);
  if (!values.length) {
    return "None";
  }
  if (values.length <= limit) {
    return values.join(", ");
  }
  return `${values.slice(0, limit).join(", ")} +${values.length - limit}`;
}

function statusTone(status?: string | null) {
  if (!status) {
    return "default";
  }
  if (["error", "blocked", "critical", "failed"].includes(status)) {
    return "critical";
  }
  if (["review", "paused", "warning", "warn"].includes(status)) {
    return "warn";
  }
  return "default";
}

function columnTone(columnKey: BoardColumn["key"]) {
  if (columnKey === "blocked") return "critical";
  if (columnKey === "review") return "warn";
  if (columnKey === "in_progress") return "default";
  return "default";
}

function flattenTasks(board: BoardResponse | null) {
  return (board?.columns ?? []).flatMap((column) => column.tasks);
}

function findGoalPath(nodes: GoalTreeNode[], goalId?: string | null, trail: GoalTreeNode[] = []): GoalTreeNode[] | null {
  if (!goalId) {
    return null;
  }
  for (const node of nodes) {
    const nextTrail = [...trail, node];
    if (node.goal_id === goalId) {
      return nextTrail;
    }
    const childTrail = findGoalPath(node.children, goalId, nextTrail);
    if (childTrail) {
      return childTrail;
    }
  }
  return null;
}

function buildTickerItems(timeline: TimelineResponse | null, activity: ActivityItem[] | undefined): TickerItem[] {
  const sourceEvents: TickerItem[] = [
    ...(timeline?.events ?? []).map((event) => ({
      id: `${event.source}:${event.event_id}`,
      title: event.title,
      summary: event.description,
      createdAt: event.created_at,
      tone: (
        event.severity === "critical"
          ? "critical"
          : event.severity === "warning"
            ? "warn"
            : "default"
      ) as TickerItem["tone"],
      taskId: event.task_id,
      agentId: event.agent_id
    })),
    ...(activity ?? []).map((item, index) => ({
      id: `activity:${item.activity_id ?? index}:${item.created_at}`,
      title: item.action.replaceAll("_", " "),
      summary: item.description,
      createdAt: item.created_at,
      tone: (
        item.severity === "critical"
          ? "critical"
          : item.severity === "warning"
            ? "warn"
            : "default"
      ) as TickerItem["tone"],
      taskId: item.task_id,
      agentId: item.agent_id
    }))
  ].sort((left, right) => right.createdAt.localeCompare(left.createdAt));

  const grouped: TickerItem[] = [];
  for (const item of sourceEvents) {
    const previous = grouped[grouped.length - 1];
    if (
      previous &&
      previous.title === item.title &&
      previous.taskId === item.taskId &&
      previous.agentId === item.agentId &&
      previous.summary === item.summary
    ) {
      previous.count = (previous.count ?? 1) + 1;
      if (item.createdAt > previous.createdAt) {
        previous.createdAt = item.createdAt;
      }
      continue;
    }
    grouped.push({ ...item, count: 1 });
  }
  return grouped.slice(0, 18);
}

function buildAgentContext(
  agent: AgentRosterEntry,
  tasks: BoardTask[],
  tickerItems: TickerItem[]
): { subtitle: string; detail: string; tone: "critical" | "warn" | "default" } {
  const currentTask = tasks.find((task) => task.task_id === agent.current_task_id);
  const lastEvent = tickerItems.find((item) => item.agentId === agent.agent_id);

  if (currentTask) {
    if (currentTask.status === "blocked") {
      return {
        subtitle: currentTask.title,
        detail: currentTask.review_state ? `Blocked · ${currentTask.review_state}` : "Blocked",
        tone: "critical"
      };
    }
    if (currentTask.status === "review") {
      return {
        subtitle: currentTask.title,
        detail: "Waiting on review",
        tone: "warn"
      };
    }
    return {
      subtitle: currentTask.title,
      detail: currentTask.goal?.title ?? "Active execution",
      tone: "default"
    };
  }

  if (agent.status === "error") {
    return {
      subtitle: "Needs recovery",
      detail: lastEvent?.summary ?? "Agent reported an error state.",
      tone: "critical"
    };
  }

  if (agent.status === "idle") {
    return {
      subtitle: "Idle",
      detail: lastEvent?.summary ?? "Waiting for the next assignment.",
      tone: "default"
    };
  }

  return {
    subtitle: agent.current_task_title ?? "No current task",
    detail: lastEvent?.summary ?? "No recent activity recorded.",
    tone: statusTone(agent.status)
  };
}

function matchRepoPlanItems(task: BoardTask, overview: OverviewResponse | null) {
  const items = overview?.onboarding?.repo_plan_state?.items ?? overview?.onboarding?.repo_plan_preview?.items ?? [];
  const scopedPaths = task.scoped_paths ?? [];
  if (!items.length) {
    return [];
  }
  return items.filter((item) => {
    if (scopedPaths.length) {
      return item.paths.some((path) => scopedPaths.some((scope) => path.startsWith(scope) || scope.startsWith(path)));
    }
    return Boolean(task.goal?.title && item.title.toLowerCase().includes(task.goal.title.toLowerCase()));
  });
}

function CompactBoardCard({
  task,
  selected,
  onSelect
}: {
  task: BoardTask;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button type="button" className={`compact-board-card ${selected ? "is-selected" : ""}`} onClick={onSelect}>
      <div className="compact-board-card__top">
        <span className={`compact-board-card__priority compact-board-card__priority--${statusTone(task.review_state ?? task.status)}`}>
          {formatPriority(task.priority)}
        </span>
        <span className="compact-board-card__id">{task.task_id}</span>
      </div>
      <strong className="compact-board-card__title">{task.title}</strong>
      <div className="compact-board-card__meta">
        <span>{task.agent?.name ?? "Unassigned"}</span>
        <span>{task.goal?.title ?? "Unlinked"}</span>
      </div>
      <div className="compact-board-card__signals">
        {task.review_state ? <span>{task.review_state.replaceAll("_", " ")}</span> : null}
        {task.failure_count ? <span>{task.failure_count} failures</span> : null}
        {task.latest_verification_status ? <span>{task.latest_verification_status}</span> : null}
        {task.next_retry_at ? <span>retry pending</span> : null}
      </div>
    </button>
  );
}

export function HomePage({ onNavigate }: HomePageProps) {
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioResponse | null>(null);
  const [board, setBoard] = useState<BoardResponse | null>(null);
  const [goalTree, setGoalTree] = useState<GoalTreeResponse | null>(null);
  const [roster, setRoster] = useState<AgentRosterResponse | null>(null);
  const [recovery, setRecovery] = useState<RecoveryPolicyResponse | null>(null);
  const [timeline, setTimeline] = useState<TimelineResponse | null>(null);
  const [taskArtifacts, setTaskArtifacts] = useState<ArtifactsResponse | null>(null);
  const [taskTimeline, setTaskTimeline] = useState<TimelineResponse | null>(null);
  const [taskDiffArtifact, setTaskDiffArtifact] = useState<ArtifactDetail | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingActionKey, setPendingActionKey] = useState<string | null>(null);
  const livePulse = useLivePulse();

  async function loadControlRoom() {
    const [overviewPayload, portfolioPayload, boardPayload, goalTreePayload, rosterPayload, recoveryPayload, timelinePayload] =
      await Promise.all([
        fetchOverview(),
        fetchPortfolio(),
        fetchBoard(),
        fetchGoalTree(),
        fetchAgentRoster(),
        fetchRecoveryPolicy(),
        fetchIncidentTimeline({ limit: 24 })
      ]);

    setOverview(overviewPayload);
    setPortfolio(portfolioPayload);
    setBoard(boardPayload);
    setGoalTree(goalTreePayload);
    setRoster(rosterPayload);
    setRecovery(recoveryPayload);
    setTimeline(timelinePayload);
  }

  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        const [overviewPayload, portfolioPayload, boardPayload, goalTreePayload, rosterPayload, recoveryPayload, timelinePayload] =
          await Promise.all([
            fetchOverview(),
            fetchPortfolio(),
            fetchBoard(),
            fetchGoalTree(),
            fetchAgentRoster(),
            fetchRecoveryPolicy(),
            fetchIncidentTimeline({ limit: 24 })
          ]);
        if (!mounted) {
          return;
        }
        setOverview(overviewPayload);
        setPortfolio(portfolioPayload);
        setBoard(boardPayload);
        setGoalTree(goalTreePayload);
        setRoster(rosterPayload);
        setRecovery(recoveryPayload);
        setTimeline(timelinePayload);
      } catch {
        if (mounted) {
          setNotice("Control room refresh failed; showing the latest available operator state.");
        }
      }
    }

    void load();
    return () => {
      mounted = false;
    };
  }, [livePulse]);

  const allTasks = useMemo(() => flattenTasks(board), [board]);
  const boardColumns = useMemo(
    () =>
      (board?.columns ?? []).filter((column) =>
        ["planned", "ready", "in_progress", "review", "blocked"].includes(column.key)
      ),
    [board]
  );
  const tickerItems = useMemo(() => buildTickerItems(timeline, overview?.recent_activity), [overview, timeline]);

  const selectedTask =
    allTasks.find((task) => task.task_id === selectedTaskId) ??
    allTasks.find((task) => task.status === "in_progress") ??
    allTasks.find((task) => task.status === "review") ??
    allTasks.find((task) => task.status === "blocked") ??
    allTasks[0] ??
    null;

  useEffect(() => {
    if (selectedTask && selectedTask.task_id !== selectedTaskId) {
      setSelectedTaskId(selectedTask.task_id);
    }
  }, [selectedTask, selectedTaskId]);

  useEffect(() => {
    let mounted = true;
    async function loadTaskContext() {
      if (!selectedTask) {
        if (mounted) {
          setTaskArtifacts(null);
          setTaskTimeline(null);
          setTaskDiffArtifact(null);
        }
        return;
      }
      const [artifactsPayload, timelinePayload, diffPayload] = await Promise.all([
        fetchArtifacts({ taskId: selectedTask.task_id, limit: 6, offset: 0 }),
        fetchIncidentTimeline({ taskId: selectedTask.task_id, limit: 8 }),
        selectedTask.git_workspace_diff_artifact_id
          ? fetchArtifactDetail(selectedTask.git_workspace_diff_artifact_id)
          : Promise.resolve(null)
      ]);
      if (!mounted) {
        return;
      }
      setTaskArtifacts(artifactsPayload);
      setTaskTimeline(timelinePayload);
      setTaskDiffArtifact(diffPayload);
    }

    void loadTaskContext();
    return () => {
      mounted = false;
    };
  }, [selectedTask?.git_workspace_diff_artifact_id, selectedTask?.task_id]);

  async function runAction(actionKey: string, successMessage: string, action: () => Promise<unknown>, fallback: string) {
    setPendingActionKey(actionKey);
    setNotice(null);
    try {
      await action();
      await loadControlRoom();
      setNotice(successMessage);
    } catch {
      setNotice(fallback);
    } finally {
      setPendingActionKey(null);
    }
  }

  const attentionItems = useMemo<AttentionItem[]>(() => {
    const items: AttentionItem[] = [];

    for (const alert of recovery?.open_failure_alerts ?? []) {
      items.push({
        id: `failure-alert:${alert.alert_id}`,
        tone: "critical",
        label: alert.title,
        summary: alert.description,
        meta: formatTime(alert.created_at),
        actionLabel: alert.operator_action?.label,
        action: alert.operator_action
          ? () =>
              runAction(
                `alert:${alert.alert_id}`,
                `Resolved ${alert.title}.`,
                () => runAlertOperatorAction(alert.operator_action as AlertOperatorAction),
                `Alert action failed for ${alert.title}.`
              )
          : undefined
      });
    }

    for (const task of recovery?.recoverable_blocked_tasks ?? []) {
      items.push({
        id: `blocked:${task.task_id}`,
        tone: "warn",
        label: task.title,
        summary: task.review_state ? `Blocked · ${task.review_state}` : "Recoverable blocked task",
        meta: task.agent_name ?? task.goal_title ?? undefined,
        actionLabel: "Recover + requeue",
        action: () =>
          runAction(
            `recover-and-requeue:${task.task_id}`,
            `Recovered and requeued ${task.title}.`,
            () => recoverAndRequeueTask(task.task_id),
            `Recover-and-requeue failed for ${task.title}.`
          )
      });
    }

    for (const deadLetter of recovery?.dead_letter_entries ?? []) {
      items.push({
        id: `dlq:${deadLetter.dlq_id}`,
        tone: "critical",
        label: deadLetter.title,
        summary: `Dead letter · ${deadLetter.reason}`,
        meta: deadLetter.detail?.failure_type ?? undefined,
        actionLabel: "Reset retry",
        action: () =>
          runAction(
            `reset-retry:${deadLetter.task_id}`,
            `Reset retry state for ${deadLetter.title}.`,
            () => resetTaskRetryState(deadLetter.task_id),
            `Retry reset failed for ${deadLetter.title}.`
          )
      });
    }

    for (const task of recovery?.circuit_breaker_tasks ?? []) {
      items.push({
        id: `circuit:${task.task_id}`,
        tone: "critical",
        label: task.title,
        summary: task.circuit_breaker_detail?.trigger?.replaceAll("_", " ") ?? "Circuit breaker opened",
        meta: task.goal_title ?? undefined,
        actionLabel: "Reset breaker",
        action: () =>
          runAction(
            `reset-breaker:${task.task_id}`,
            `Reset circuit breaker for ${task.title}.`,
            () => resetTaskCircuitBreaker(task.task_id),
            `Circuit-breaker reset failed for ${task.title}.`
          )
      });
    }

    for (const quarantine of recovery?.open_quarantine_entries ?? []) {
      const recoverable =
        quarantine.task_status === "blocked" &&
        ["session_failed", "stale_session"].includes(quarantine.task_review_state ?? "");
      items.push({
        id: `quarantine:${quarantine.queue_id}`,
        tone: "warn",
        label: quarantine.task_title ?? quarantine.queue_id,
        summary: quarantine.summary ?? quarantine.reason ?? "Quarantined artifacts need review.",
        meta: `${quarantine.artifact_count} artifacts`,
        actionLabel: recoverable ? "Restore + requeue" : "Restore artifacts",
        action: () =>
          runAction(
            `${recoverable ? "restore-requeue" : "restore"}:${quarantine.queue_id}`,
            recoverable
              ? `Restored artifacts and requeued ${quarantine.task_title ?? quarantine.queue_id}.`
              : `Restored artifacts for ${quarantine.task_title ?? quarantine.queue_id}.`,
            () =>
              recoverable
                ? restoreAndRequeueQuarantineEntry(quarantine.queue_id)
                : restoreQuarantineEntry(quarantine.queue_id),
            `Quarantine action failed for ${quarantine.task_title ?? quarantine.queue_id}.`
          )
      });
    }

    for (const staleAgent of recovery?.open_stale_agent_alerts ?? []) {
      items.push({
        id: `stale-agent:${staleAgent.alert_id}`,
        tone: "warn",
        label: staleAgent.title,
        summary: staleAgent.description,
        meta: staleAgent.project_name ?? undefined,
        actionLabel: staleAgent.operator_action?.label,
        action: staleAgent.operator_action
          ? () =>
              runAction(
                `stale-agent:${staleAgent.alert_id}`,
                `Ran ${staleAgent.operator_action?.label?.toLowerCase() ?? "recovery"} for ${staleAgent.title}.`,
                () => runAlertOperatorAction(staleAgent.operator_action as AlertOperatorAction),
                `Stale-agent action failed for ${staleAgent.title}.`
              )
          : undefined
      });
    }

    for (const repeated of recovery?.repeated_failure_incidents ?? []) {
      if (!repeated.operator_action) {
        continue;
      }
      items.push({
        id: `repeated:${repeated.task_id}`,
        tone: "warn",
        label: repeated.task_title ?? repeated.task_id,
        summary: `${repeated.failure_count} repeated failures`,
        meta: repeated.latest_failure_at ? formatTime(repeated.latest_failure_at) : undefined,
        actionLabel: repeated.operator_action.label,
        action: () =>
          runAction(
            `repeated:${repeated.task_id}`,
            `Resolved repeated-failure incident for ${repeated.task_title ?? repeated.task_id}.`,
            () => runAlertOperatorAction(repeated.operator_action!),
            `Repeated-failure resolution failed for ${repeated.task_title ?? repeated.task_id}.`
          )
      });
    }

    return items.slice(0, 10);
  }, [recovery]);

  const goalPath = useMemo(
    () => findGoalPath(goalTree?.roots ?? [], selectedTask?.goal?.id ?? null) ?? [],
    [goalTree, selectedTask?.goal?.id]
  );
  const sameGoalTasks = useMemo(
    () =>
      selectedTask?.goal?.id
        ? allTasks.filter((task) => task.goal?.id === selectedTask.goal?.id && task.task_id !== selectedTask.task_id)
        : [],
    [allTasks, selectedTask]
  );
  const repoPlanItems = useMemo(
    () => (selectedTask ? matchRepoPlanItems(selectedTask, overview).slice(0, 6) : []),
    [overview, selectedTask]
  );

  const projectHealth = overview?.summary.tasks_blocked
    ? "Degraded"
    : (recovery?.summary.open_failure_alerts ?? 0) > 0 || (recovery?.summary.open_dead_letter_entries ?? 0) > 0
      ? "At risk"
      : "Stable";

  return (
    <section className="control-room">
      <header className="control-room__header surface-card surface-card--dense">
        <div>
          <div className="control-room__eyebrow">Control room</div>
          <h1>{overview?.project?.name ?? "No active project"}</h1>
          <p>{overview?.project?.description ?? "Create or restore a project to start supervising agents."}</p>
        </div>
        <div className="control-room__header-actions">
          <button
            type="button"
            className="hero-button hero-button--primary hero-button--compact"
            disabled={pendingActionKey === "supervisor"}
            onClick={() =>
              void runAction(
                "supervisor",
                "Supervisor pass completed.",
                () => runSupervisorPass(3),
                "Supervisor pass failed."
              )
            }
          >
            {pendingActionKey === "supervisor" ? "Running..." : "Supervisor"}
          </button>
          <button
            type="button"
            className="hero-button hero-button--ghost hero-button--compact"
            disabled={pendingActionKey === "orchestrator"}
            onClick={() =>
              void runAction(
                "orchestrator",
                "Orchestrator pass completed.",
                () => runOrchestratorPass(4, 2),
                "Orchestrator pass failed."
              )
            }
          >
            {pendingActionKey === "orchestrator" ? "Running..." : "Orchestrator"}
          </button>
          <button type="button" className="hero-button hero-button--ghost hero-button--compact" onClick={() => onNavigate("projects")}>
            Projects
          </button>
        </div>
      </header>

      {notice ? <div className="banner banner--info">{notice}</div> : null}

      <section className="control-room__status-strip">
        <div className="status-panel">
          <span className={`status-dot status-dot--${projectHealth === "Stable" ? "good" : projectHealth === "Degraded" ? "warn" : "critical"}`} />
          <div>
            <strong>{projectHealth}</strong>
            <span>project health</span>
          </div>
        </div>
        <div className="status-panel">
          <strong>{overview?.summary.tasks_in_progress ?? 0}</strong>
          <span>active runs</span>
        </div>
        <div className="status-panel">
          <strong>{overview?.summary.tasks_review ?? 0}</strong>
          <span>waiting review</span>
        </div>
        <div className="status-panel">
          <strong>{recovery?.summary.open_failure_alerts ?? 0}</strong>
          <span>failure alerts</span>
        </div>
        <div className="status-panel">
          <strong>{portfolio?.summary.queued_provider_jobs ?? 0}</strong>
          <span>queued jobs</span>
        </div>
        <div className="status-panel">
          <strong>{portfolio?.summary.projects_with_issues ?? 0}</strong>
          <span>projects with issues</span>
        </div>
      </section>

      <section className="control-room__grid">
        <aside className="control-room__agents surface-card surface-card--dense">
          <div className="surface-card__header surface-card__header--tight">
            <div>
              <span className="eyebrow">Agents</span>
              <h2>Who is doing what</h2>
            </div>
            <button type="button" className="text-link" onClick={() => onNavigate("runs")}>
              Open runtime
            </button>
          </div>
          <div className="agent-rail">
            {(roster?.agents ?? []).map((agent) => {
              const context = buildAgentContext(agent, allTasks, tickerItems);
              const actionKey = `agent:${agent.agent_id}`;
              return (
                <div key={agent.agent_id} className={`agent-rail__item agent-rail__item--${context.tone}`}>
                  <div className="agent-rail__top">
                    <div>
                      <strong>{agent.display_name}</strong>
                      <span>{agent.role}</span>
                    </div>
                    <span className={`status-pill status-pill--${statusTone(agent.status)}`}>{agent.status}</span>
                  </div>
                  <div className="agent-rail__body">
                    <p>{context.subtitle}</p>
                    <span>{context.detail}</span>
                    <span>heartbeat {formatHeartbeat(agent.heartbeat_age_seconds)}</span>
                  </div>
                  <div className="agent-rail__actions">
                    {agent.current_task_id ? (
                      <button
                        type="button"
                        className="task-action task-action--ghost"
                        onClick={() => setSelectedTaskId(agent.current_task_id ?? null)}
                      >
                        Focus task
                      </button>
                    ) : null}
                    {agent.status === "idle" ? (
                      <button
                        type="button"
                        className="task-action task-action--secondary"
                        disabled={pendingActionKey === actionKey}
                        onClick={() =>
                          void runAction(
                            actionKey,
                            `Requested next task for ${agent.display_name}.`,
                            () => assignNextTask(agent.agent_id),
                            `Could not assign the next task to ${agent.display_name}.`
                          )
                        }
                      >
                        {pendingActionKey === actionKey ? "Working..." : "Assign next"}
                      </button>
                    ) : null}
                    {agent.status === "error" ? (
                      <button
                        type="button"
                        className="task-action task-action--approve"
                        disabled={pendingActionKey === actionKey}
                        onClick={() =>
                          void runAction(
                            actionKey,
                            `Recovered ${agent.display_name}.`,
                            () => recoverAgent(agent.agent_id),
                            `Recovery failed for ${agent.display_name}.`
                          )
                        }
                      >
                        {pendingActionKey === actionKey ? "Working..." : "Recover"}
                      </button>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </aside>

        <div className="control-room__center">
          <article className="surface-card surface-card--dense">
            <div className="surface-card__header surface-card__header--tight">
              <div>
                <span className="eyebrow">Kanban</span>
                <h2>Execution flow</h2>
              </div>
              <button type="button" className="text-link" onClick={() => onNavigate("work")}>
                Open workbench
              </button>
            </div>
            <div className="compact-board">
              {boardColumns.map((column) => (
                <section key={column.key} className={`compact-board__column compact-board__column--${columnTone(column.key)}`}>
                  <header className="compact-board__column-header">
                    <strong>{column.title}</strong>
                    <span>{column.tasks.length}</span>
                  </header>
                  <div className="compact-board__cards">
                    {column.tasks.slice(0, column.key === "planned" ? 6 : 10).map((task) => (
                      <CompactBoardCard
                        key={task.task_id}
                        task={task}
                        selected={selectedTask?.task_id === task.task_id}
                        onSelect={() => setSelectedTaskId(task.task_id)}
                      />
                    ))}
                  </div>
                </section>
              ))}
            </div>
          </article>

          <article className="surface-card surface-card--dense">
            <div className="surface-card__header surface-card__header--tight">
              <div>
                <span className="eyebrow">Inspector</span>
                <h2>{selectedTask?.title ?? "No task selected"}</h2>
              </div>
              {selectedTask ? <span className={`status-pill status-pill--${statusTone(selectedTask.review_state ?? selectedTask.status)}`}>{selectedTask.status}</span> : null}
            </div>
            {selectedTask ? (
              <div className="task-inspector">
                <div className="task-inspector__primary">
                  <div className="task-inspector__summary">
                    <div>
                      <span>Agent</span>
                      <strong>{selectedTask.agent?.name ?? "Unassigned"}</strong>
                    </div>
                    <div>
                      <span>Goal</span>
                      <strong>{selectedTask.goal?.title ?? "Unlinked"}</strong>
                    </div>
                    <div>
                      <span>Verification</span>
                      <strong>{selectedTask.latest_verification_status ?? "none"}</strong>
                    </div>
                    <div>
                      <span>Failures</span>
                      <strong>{selectedTask.failure_count ?? 0}</strong>
                    </div>
                  </div>
                  <p className="task-inspector__description">{selectedTask.description ?? "No task description captured yet."}</p>
                  <div className="task-inspector__actions">
                    {selectedTask.status === "review" ? (
                      <>
                        <button
                          type="button"
                          className="task-action task-action--approve"
                          disabled={pendingActionKey === `review:${selectedTask.task_id}:approve`}
                          onClick={() =>
                            void runAction(
                              `review:${selectedTask.task_id}:approve`,
                              `Approved ${selectedTask.title}.`,
                              () => reviewTask(selectedTask.task_id, "approve"),
                              `Approve failed for ${selectedTask.title}.`
                            )
                          }
                        >
                          {pendingActionKey === `review:${selectedTask.task_id}:approve` ? "Working..." : "Approve"}
                        </button>
                        <button
                          type="button"
                          className="task-action task-action--reject"
                          disabled={pendingActionKey === `review:${selectedTask.task_id}:reject`}
                          onClick={() =>
                            void runAction(
                              `review:${selectedTask.task_id}:reject`,
                              `Requested changes for ${selectedTask.title}.`,
                              () => reviewTask(selectedTask.task_id, "reject"),
                              `Reject failed for ${selectedTask.title}.`
                            )
                          }
                        >
                          {pendingActionKey === `review:${selectedTask.task_id}:reject` ? "Working..." : "Request changes"}
                        </button>
                      </>
                    ) : null}
                    {selectedTask.status === "blocked" &&
                    ["session_failed", "stale_session"].includes(selectedTask.review_state ?? "") ? (
                      <>
                        <button
                          type="button"
                          className="task-action task-action--secondary"
                          disabled={pendingActionKey === `recover:${selectedTask.task_id}`}
                          onClick={() =>
                            void runAction(
                              `recover:${selectedTask.task_id}`,
                              `Recovered ${selectedTask.title}.`,
                              () => recoverTask(selectedTask.task_id),
                              `Recover failed for ${selectedTask.title}.`
                            )
                          }
                        >
                          {pendingActionKey === `recover:${selectedTask.task_id}` ? "Working..." : "Recover"}
                        </button>
                        <button
                          type="button"
                          className="task-action task-action--approve"
                          disabled={pendingActionKey === `recover-and-requeue:${selectedTask.task_id}`}
                          onClick={() =>
                            void runAction(
                              `recover-and-requeue:${selectedTask.task_id}`,
                              `Recovered and requeued ${selectedTask.title}.`,
                              () => recoverAndRequeueTask(selectedTask.task_id),
                              `Recover-and-requeue failed for ${selectedTask.title}.`
                            )
                          }
                        >
                          {pendingActionKey === `recover-and-requeue:${selectedTask.task_id}` ? "Working..." : "Recover + requeue"}
                        </button>
                      </>
                    ) : null}
                    {selectedTask.review_state === "needs_replan" ? (
                      <button
                        type="button"
                        className="task-action task-action--approve"
                        disabled={pendingActionKey === `finish-replan:${selectedTask.task_id}`}
                        onClick={() =>
                          void runAction(
                            `finish-replan:${selectedTask.task_id}`,
                            `Returned ${selectedTask.title} to readiness evaluation.`,
                            () => finishTaskReplan(selectedTask.task_id),
                            `Finish-replan failed for ${selectedTask.title}.`
                          )
                        }
                      >
                        {pendingActionKey === `finish-replan:${selectedTask.task_id}` ? "Working..." : "Finish replan"}
                      </button>
                    ) : null}
                    {selectedTask.review_state !== "needs_replan" &&
                    selectedTask.status !== "in_progress" &&
                    selectedTask.status !== "review" &&
                    selectedTask.status !== "done" &&
                    selectedTask.status !== "cancelled" ? (
                      <button
                        type="button"
                        className="task-action task-action--ghost"
                        disabled={pendingActionKey === `mark-for-replan:${selectedTask.task_id}`}
                        onClick={() =>
                          void runAction(
                            `mark-for-replan:${selectedTask.task_id}`,
                            `Marked ${selectedTask.title} for replanning.`,
                            () => markTaskForReplan(selectedTask.task_id),
                            `Mark-for-replan failed for ${selectedTask.title}.`
                          )
                        }
                      >
                        {pendingActionKey === `mark-for-replan:${selectedTask.task_id}` ? "Working..." : "Mark for replan"}
                      </button>
                    ) : null}
                    {selectedTask.has_verification_recipe ? (
                      <button
                        type="button"
                        className="task-action task-action--ghost"
                        disabled={pendingActionKey === `verify:${selectedTask.task_id}`}
                        onClick={() =>
                          void runAction(
                            `verify:${selectedTask.task_id}`,
                            `Verification finished for ${selectedTask.title}.`,
                            () => runTaskVerification(selectedTask.task_id),
                            `Verification failed for ${selectedTask.title}.`
                          )
                        }
                      >
                        {pendingActionKey === `verify:${selectedTask.task_id}` ? "Working..." : "Run verification"}
                      </button>
                    ) : null}
                    {selectedTask.git_workspace_supported && !selectedTask.git_workspace_prepared ? (
                      <button
                        type="button"
                        className="task-action task-action--ghost"
                        disabled={pendingActionKey === `prepare:${selectedTask.task_id}`}
                        onClick={() =>
                          void runAction(
                            `prepare:${selectedTask.task_id}`,
                            `Prepared git workspace for ${selectedTask.title}.`,
                            () => prepareTaskGitWorkspace(selectedTask.task_id),
                            `Git workspace preparation failed for ${selectedTask.title}.`
                          )
                        }
                      >
                        {pendingActionKey === `prepare:${selectedTask.task_id}` ? "Working..." : "Prepare git"}
                      </button>
                    ) : null}
                    {selectedTask.git_workspace_prepared ? (
                      <button
                        type="button"
                        className="task-action task-action--ghost"
                        disabled={pendingActionKey === `diff:${selectedTask.task_id}`}
                        onClick={() =>
                          void runAction(
                            `diff:${selectedTask.task_id}`,
                            `Refreshed git diff for ${selectedTask.title}.`,
                            () => refreshTaskGitDiff(selectedTask.task_id),
                            `Git diff refresh failed for ${selectedTask.title}.`
                          )
                        }
                      >
                        {pendingActionKey === `diff:${selectedTask.task_id}` ? "Working..." : "Refresh diff"}
                      </button>
                    ) : null}
                  </div>
                </div>

                <div className="task-inspector__grid">
                  <section className="inspector-panel">
                    <div className="inspector-panel__header">
                      <strong>Goal relationship</strong>
                    </div>
                    {goalPath.length ? (
                      <div className="inspector-flow">
                        <div className="inspector-flow__path">
                          {goalPath.map((node) => (
                            <span key={node.goal_id}>{node.title}</span>
                          ))}
                        </div>
                        <div className="inspector-flow__list">
                          {sameGoalTasks.slice(0, 6).map((task) => (
                            <button key={task.task_id} type="button" className="inspector-chip" onClick={() => setSelectedTaskId(task.task_id)}>
                              <strong>{task.title}</strong>
                              <span>{task.status}</span>
                            </button>
                          ))}
                          {!sameGoalTasks.length ? <span className="muted-copy">No sibling tasks in the visible board.</span> : null}
                        </div>
                      </div>
                    ) : (
                      <span className="muted-copy">No goal relationship is available for this task.</span>
                    )}
                  </section>

                  <section className="inspector-panel">
                    <div className="inspector-panel__header">
                      <strong>Repo scope</strong>
                    </div>
                    <div className="inspector-copy-stack">
                      <p>{formatList(selectedTask.scoped_paths)}</p>
                      <p>{formatList(selectedTask.validation_commands)}</p>
                      {repoPlanItems.length ? (
                        <div className="inspector-flow__list">
                          {repoPlanItems.map((item) => (
                            <div key={item.synthesis_key} className="inspector-chip inspector-chip--static">
                              <strong>{item.title}</strong>
                              <span>{formatList(item.paths, 2)}</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <span className="muted-copy">No repo-plan items matched this task scope.</span>
                      )}
                    </div>
                  </section>

                  <section className="inspector-panel">
                    <div className="inspector-panel__header">
                      <strong>Evidence</strong>
                    </div>
                    <div className="inspector-copy-stack">
                      <p>
                        Verification: {selectedTask.latest_verification_status ?? "none"}
                        {selectedTask.latest_verification_at ? ` · ${formatTime(selectedTask.latest_verification_at)}` : ""}
                      </p>
                      <p>
                        Git workspace:{" "}
                        {selectedTask.git_workspace_prepared
                          ? `${selectedTask.git_workspace_branch ?? "prepared"} · ${selectedTask.git_workspace_change_summary ?? "diff ready"}`
                          : selectedTask.git_workspace_supported
                            ? "supported, not prepared"
                            : "not supported"}
                      </p>
                      {taskDiffArtifact?.preview?.content ? (
                        <pre className="inspector-pre">{taskDiffArtifact.preview.content}</pre>
                      ) : null}
                      <div className="inspector-flow__list">
                        {(taskArtifacts?.items ?? []).slice(0, 5).map((artifact) => (
                          <div key={artifact.artifact_id} className="inspector-chip inspector-chip--static">
                            <strong>{artifact.file_name}</strong>
                            <span>{artifact.artifact_type} · {artifact.artifact_state}</span>
                          </div>
                        ))}
                        {!taskArtifacts?.items.length ? <span className="muted-copy">No artifacts recorded for this task yet.</span> : null}
                      </div>
                    </div>
                  </section>

                  <section className="inspector-panel">
                    <div className="inspector-panel__header">
                      <strong>Recent history</strong>
                    </div>
                    <div className="ticker-list ticker-list--compact">
                      {(taskTimeline?.events ?? []).slice(0, 6).map((event) => (
                        <div key={event.event_id} className={`ticker-item ticker-item--${statusTone(event.severity)}`}>
                          <div>
                            <strong>{event.title}</strong>
                            <p>{event.description}</p>
                          </div>
                          <span>{formatTime(event.created_at)}</span>
                        </div>
                      ))}
                      {!taskTimeline?.events.length ? <span className="muted-copy">No task-specific history has been recorded yet.</span> : null}
                    </div>
                  </section>
                </div>
              </div>
            ) : (
              <div className="empty-state empty-state--compact">
                <strong>No task is currently visible.</strong>
                <p>Wait for the scheduler to surface work or open the workbench for the full board.</p>
              </div>
            )}
          </article>
        </div>

        <aside className="control-room__ops">
          <article className="surface-card surface-card--dense">
            <div className="surface-card__header surface-card__header--tight">
              <div>
                <span className="eyebrow">Attention</span>
                <h2>What needs you now</h2>
              </div>
              <button type="button" className="text-link" onClick={() => onNavigate("incidents")}>
                Open incidents
              </button>
            </div>
            <div className="attention-list">
              {attentionItems.length ? (
                attentionItems.map((item) => (
                  <div key={item.id} className={`attention-item attention-item--${item.tone}`}>
                    <div>
                      <strong>{item.label}</strong>
                      <p>{item.summary}</p>
                      {item.meta ? <span>{item.meta}</span> : null}
                    </div>
                    {item.action && item.actionLabel ? (
                      <button
                        type="button"
                        className="task-action task-action--approve"
                        disabled={pendingActionKey === item.id}
                        onClick={() => void item.action?.()}
                      >
                        {pendingActionKey === item.id ? "Working..." : item.actionLabel}
                      </button>
                    ) : (
                      <button type="button" className="task-action task-action--ghost" onClick={() => onNavigate("incidents")}>
                        Inspect
                      </button>
                    )}
                  </div>
                ))
              ) : (
                <div className="empty-state empty-state--compact">
                  <strong>No urgent operator actions.</strong>
                  <p>Keep an eye on the live feed and the board; nothing is escalated right now.</p>
                </div>
              )}
            </div>
          </article>

          <article className="surface-card surface-card--dense">
            <div className="surface-card__header surface-card__header--tight">
              <div>
                <span className="eyebrow">Live feed</span>
                <h2>Meaningful system events</h2>
              </div>
              <button type="button" className="text-link" onClick={() => onNavigate("runs")}>
                Open runs
              </button>
            </div>
            <div className="ticker-list">
              {tickerItems.length ? (
                tickerItems.map((item) => (
                  <div key={item.id} className={`ticker-item ticker-item--${item.tone}`}>
                    <div>
                      <strong>{item.title}</strong>
                      <p>{item.summary}</p>
                    </div>
                    <div className="ticker-item__meta">
                      {item.count && item.count > 1 ? <span>×{item.count}</span> : null}
                      <span>{formatTime(item.createdAt)}</span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="empty-state empty-state--compact">
                  <strong>No recent events.</strong>
                  <p>The feed will populate as agents, providers, and recovery actions change system state.</p>
                </div>
              )}
            </div>
          </article>
        </aside>
      </section>
    </section>
  );
}
