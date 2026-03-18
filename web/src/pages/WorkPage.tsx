import { startTransition, useDeferredValue, useEffect, useMemo, useState } from "react";
import { BoardColumn } from "../components/BoardColumn";
import { StatCard } from "../components/StatCard";
import {
  fetchBoard,
  finishTaskReplan,
  haltTask,
  markTaskForReplan,
  prepareTaskGitWorkspace,
  reassignTask,
  recoverAndRequeueTask,
  recoverTask,
  refreshTaskGitDiff,
  reprioritizeTask,
  reviewTask,
  runTaskVerification,
  setAgentState,
  setTaskRetryLimit
} from "../lib/boardApi";
import { fetchGoalTree, fetchOverview } from "../lib/controlRoomApi";
import { useLivePulse } from "../lib/useLivePulse";
import type { BoardFiltersInput, BoardResponse, FilterOption, GoalTreeNode, GoalTreeResponse, OverviewResponse } from "../types";
import { BoardPage } from "./BoardPage";
import { GoalTreePage } from "./GoalTreePage";

type WorkFocus = "all" | "execution" | "attention";

function formatTime(value?: string | null) {
  if (!value) {
    return "Not recorded";
  }
  return new Date(value).toLocaleString();
}

function formatPriority(priority: number) {
  if (priority >= 90) {
    return "Critical";
  }
  if (priority >= 75) {
    return "High";
  }
  if (priority >= 50) {
    return "Medium";
  }
  return "Low";
}

function formatStatusLabel(value?: string | null) {
  if (!value) {
    return "Unknown";
  }
  return value.replaceAll("_", " ");
}

function formatList(items?: string[] | null) {
  return (items ?? []).filter(Boolean).join(", ") || "None";
}

function GoalTreePreview({ node }: { node: GoalTreeNode }) {
  return (
    <li className="goal-preview__item">
      <div className="goal-preview__card">
        <div className="goal-preview__header">
          <strong>{node.title}</strong>
          <span className="status-pill">{node.status}</span>
        </div>
        <p>{node.description}</p>
        <div className="goal-preview__meta">
          <span>{node.goal_type}</span>
          <span>P{node.priority}</span>
          <span>{Object.values(node.task_counts).reduce((sum, value) => sum + value, 0)} tasks</span>
        </div>
      </div>
      {node.children.length ? (
        <ul className="goal-preview">
          {node.children.map((child) => (
            <GoalTreePreview key={child.goal_id} node={child} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function WorkPage() {
  const [board, setBoard] = useState<BoardResponse | null>(null);
  const [goalTree, setGoalTree] = useState<GoalTreeResponse | null>(null);
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [query, setQuery] = useState("");
  const [focus, setFocus] = useState<WorkFocus>("all");
  const [advancedViewsOpen, setAdvancedViewsOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingActionKey, setPendingActionKey] = useState<string | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const deferredQuery = useDeferredValue(query);
  const livePulse = useLivePulse();

  const boardFilters: BoardFiltersInput = useMemo(() => {
    const filters: BoardFiltersInput = {
      search: deferredQuery.trim() || undefined
    };
    if (focus === "execution") {
      filters.priorityMin = 75;
    }
    return filters;
  }, [deferredQuery, focus]);

  async function loadWork(signal?: AbortSignal) {
    const [boardPayload, goalTreePayload, overviewPayload] = await Promise.all([
      fetchBoard(boardFilters, signal),
      fetchGoalTree(),
      fetchOverview()
    ]);
    const visibleBoard =
      focus === "attention"
        ? {
            ...boardPayload,
            columns: boardPayload.columns.filter((column) => column.key === "blocked" || column.key === "review")
          }
        : boardPayload;
    startTransition(() => {
      setBoard(visibleBoard);
      setGoalTree(goalTreePayload);
      setOverview(overviewPayload);
    });
  }

  useEffect(() => {
    const controller = new AbortController();
    void loadWork(controller.signal).catch((error) => {
      if (!(error instanceof Error && error.name === "AbortError")) {
        setNotice("Work surface refresh failed; keeping the latest available planning snapshot.");
      }
    });
    return () => {
      controller.abort();
    };
  }, [boardFilters]);

  useEffect(() => {
    if (livePulse === 0) {
      return;
    }
    void loadWork().catch(() => {
      setNotice("Work surface refresh failed; keeping the latest available planning snapshot.");
    });
  }, [livePulse]);

  const allTasks = useMemo(() => (board?.columns ?? []).flatMap((column) => column.tasks), [board]);
  const selectedTask =
    allTasks.find((task) => task.task_id === selectedTaskId) ??
    allTasks.find((task) => task.status === "in_progress") ??
    allTasks[0] ??
    null;

  useEffect(() => {
    if (selectedTask && selectedTask.task_id !== selectedTaskId) {
      setSelectedTaskId(selectedTask.task_id);
    }
  }, [selectedTask, selectedTaskId]);

  const agentOptions = useMemo<FilterOption[]>(() => board?.filter_options?.agents ?? [], [board]);
  const visibleColumns = useMemo(() => {
    const orderedKeys = ["ready", "in_progress", "review", "blocked", "planned"] as const;
    const byKey = new Map((board?.columns ?? []).map((column) => [column.key, column] as const));
    const prioritized = orderedKeys
      .map((key) => byKey.get(key))
      .filter((column): column is NonNullable<typeof board>["columns"][number] => Boolean(column));
    const visible = prioritized.filter(
      (column) => column.tasks.length > 0 || ["in_progress", "review", "blocked"].includes(column.key)
    );
    return visible.length ? visible : prioritized.slice(0, 3);
  }, [board]);
  const collapsedColumns = useMemo(
    () =>
      (board?.columns ?? [])
        .filter((column) => !visibleColumns.some((visible) => visible.key === column.key))
        .map((column) => ({ key: column.key, title: column.title, count: column.tasks.length })),
    [board, visibleColumns]
  );
  const boardIsFitted = visibleColumns.length > 0 && visibleColumns.length <= 3;

  async function reloadWithNotice(message: string) {
    await loadWork();
    setNotice(message);
  }

  async function runAction(actionKey: string, message: string, action: () => Promise<unknown>, fallback: string) {
    setPendingActionKey(actionKey);
    setNotice(null);
    try {
      await action();
      await reloadWithNotice(message);
    } catch {
      setNotice(fallback);
    } finally {
      setPendingActionKey(null);
    }
  }

  const repoPlanState = overview?.onboarding?.repo_plan_state ?? null;
  const repoPlanPreview = overview?.onboarding?.repo_plan_preview ?? null;
  const repoPlan = repoPlanState ?? repoPlanPreview;

  return (
    <section className="dashboard-page">
      <header className="dashboard-hero">
        <div className="dashboard-hero__content">
          <span className="eyebrow">Work</span>
          <h1>Execution cockpit</h1>
          <p>Plan, prioritize, inspect, and steer software-delivery work without bouncing between board, goals, and repo detail views.</p>
          <div className="hero-meta">
            <span className="hero-meta__pill">{allTasks.length} visible tasks</span>
            <span className="hero-meta__pill">{goalTree?.total_goals ?? 0} goals</span>
            <span className="hero-meta__pill">
              {overview?.onboarding?.repo_plan_state?.generated_task_count ?? overview?.onboarding?.repo_plan_preview?.generated_task_count ?? 0} repo-derived plan items
            </span>
          </div>
        </div>
        <div className="work-toolbar">
          <label className="field-control field-control--search">
            <span>Search work</span>
            <input
              type="search"
              value={query}
              placeholder="task, goal, repo path"
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <div className="segmented-control" role="tablist" aria-label="Work focus">
            {[
              { id: "all", label: "All work" },
              { id: "execution", label: "Execution" },
              { id: "attention", label: "Needs attention" }
            ].map((item) => (
              <button
                key={item.id}
                type="button"
                className={focus === item.id ? "is-active" : ""}
                onClick={() => setFocus(item.id as WorkFocus)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      {notice ? <div className="banner banner--info">{notice}</div> : null}

      <section className="stats-grid stats-grid--dense">
        <StatCard label="Ready to assign" value={board?.columns.find((column) => column.key === "ready")?.tasks.length ?? 0} />
        <StatCard label="In progress" value={board?.summary.active_tasks ?? board?.summary.total_tasks ?? 0} />
        <StatCard label="Blocked" value={board?.summary.blocked_tasks ?? 0} tone="warn" />
        <StatCard label="In review" value={board?.summary.review_tasks ?? 0} tone="warn" />
        <StatCard label="Active agents" value={board?.summary.active_agents ?? 0} tone="good" />
        <StatCard label="Repo plan items" value={repoPlan?.generated_task_count ?? 0} />
      </section>

      <section className="work-surface">
        <div className="work-surface__board">
          <div className="surface-card surface-card--flush">
            <div className="surface-card__header">
              <div>
                <span className="eyebrow">Execution board</span>
                <h2>Current task flow</h2>
                {collapsedColumns.length ? (
                  <div className="board-queue-strip board-queue-strip--work">
                    {collapsedColumns.map((column) => (
                      <span key={column.key} className="board-queue-pill">
                        <strong>{column.count}</strong>
                        <span>{column.title}</span>
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
              <span className="status-chip">{allTasks.length} visible cards</span>
            </div>
            <div
              className={`board-strip ${boardIsFitted ? "board-strip--fitted" : ""}`}
              style={
                boardIsFitted
                  ? { gridTemplateColumns: `repeat(${Math.max(visibleColumns.length, 1)}, minmax(0, 1fr))` }
                  : undefined
              }
            >
              {visibleColumns.map((column) => (
                <BoardColumn
                  key={column.key}
                  column={column}
                  agentOptions={agentOptions}
                  pendingActionKey={pendingActionKey}
                  focusedTaskId={selectedTask?.task_id ?? null}
                  onInspect={setSelectedTaskId}
                  onReviewAction={(taskId, decision) =>
                    void runAction(
                      `review:${taskId}:${decision}`,
                      `Review ${decision}ed for ${taskId}.`,
                      () => reviewTask(taskId, decision),
                      "Review action failed; keep the current board state under review."
                    )
                  }
                  onAgentAction={(agentId, action) =>
                    void runAction(
                      `agent:${agentId}:${action}`,
                      `Agent ${action} requested for ${agentId}.`,
                      () => setAgentState(agentId, action),
                      "Agent action failed; keep the current board state under review."
                    )
                  }
                  onPriorityChange={(taskId, priority) =>
                    void runAction(
                      `reprioritize:${taskId}`,
                      `Priority updated for ${taskId}.`,
                      () => reprioritizeTask(taskId, priority),
                      "Priority update failed; keeping the current board ordering."
                    )
                  }
                  onReassign={(taskId, agentId) =>
                    void runAction(
                      `reassign:${taskId}`,
                      `Task ${taskId} reassigned to ${agentId}.`,
                      () => reassignTask(taskId, agentId),
                      "Task reassignment failed; keeping the current ownership."
                    )
                  }
                  onHalt={(taskId) =>
                    void runAction(
                      `halt:${taskId}`,
                      `Task ${taskId} halted.`,
                      () => haltTask(taskId),
                      "Task halt failed; keep the task visible until the backend accepts the action."
                    )
                  }
                  onRecover={(taskId) =>
                    void runAction(
                      `recover:${taskId}`,
                      `Task ${taskId} returned to planning.`,
                      () => recoverTask(taskId),
                      "Task recovery failed; keep the task in the incident queue."
                    )
                  }
                  onRecoverAndRequeue={(taskId) =>
                    void runAction(
                      `recover-and-requeue:${taskId}`,
                      `Task ${taskId} recovered and requeued.`,
                      () => recoverAndRequeueTask(taskId),
                      "Recover-and-requeue failed; keep the incident under operator review."
                    )
                  }
                  onMarkForReplan={(taskId) =>
                    void runAction(
                      `mark-for-replan:${taskId}`,
                      `Task ${taskId} moved into replanning.`,
                      () => markTaskForReplan(taskId),
                      "Mark-for-replan failed; keep the current task state."
                    )
                  }
                  onFinishReplan={(taskId) =>
                    void runAction(
                      `finish-replan:${taskId}`,
                      `Task ${taskId} returned to readiness evaluation.`,
                      () => finishTaskReplan(taskId),
                      "Finish-replan failed; keep the task in replanning."
                    )
                  }
                  onRunVerification={(taskId) =>
                    void runAction(
                      `run-verification:${taskId}`,
                      `Verification finished for ${taskId}.`,
                      () => runTaskVerification(taskId),
                      "Verification failed to start; inspect the task and try again."
                    )
                  }
                  onPrepareGitWorkspace={(taskId) =>
                    void runAction(
                      `prepare-git-workspace:${taskId}`,
                      `Prepared git workspace for ${taskId}.`,
                      () => prepareTaskGitWorkspace(taskId),
                      "Git workspace preparation failed; keep using the current runtime context."
                    )
                  }
                  onRefreshGitDiff={(taskId) =>
                    void runAction(
                      `refresh-git-diff:${taskId}`,
                      `Refreshed git diff for ${taskId}.`,
                      () => refreshTaskGitDiff(taskId),
                      "Git diff refresh failed; keep the current change summary."
                    )
                  }
                  onRetryLimitChange={(taskId, autoRetryLimit) =>
                    void runAction(
                      `retry-limit:${taskId}`,
                      `Updated retry budget for ${taskId}.`,
                      () => setTaskRetryLimit(taskId, autoRetryLimit),
                      "Retry limit update failed; keep the current budget."
                    )
                  }
                />
              ))}
            </div>
          </div>
        </div>

        <aside className="work-surface__detail">
          <div className="surface-card">
            <div className="surface-card__header">
              <div>
                <span className="eyebrow">Focused task</span>
                <h2>{selectedTask?.title ?? "No task selected"}</h2>
              </div>
              {selectedTask ? <span className="status-chip">{formatStatusLabel(selectedTask.status)}</span> : null}
            </div>
            {selectedTask ? (
              <div className="detail-stack">
                <p>{selectedTask.description ?? "No task description captured yet."}</p>
                <div className="detail-grid">
                  <div>
                    <span>Priority</span>
                    <strong>{formatPriority(selectedTask.priority)}</strong>
                  </div>
                  <div>
                    <span>Goal</span>
                    <strong>{selectedTask.goal?.title ?? "Unlinked"}</strong>
                  </div>
                  <div>
                    <span>Agent</span>
                    <strong>{selectedTask.agent?.name ?? "Unassigned"}</strong>
                  </div>
                  <div>
                    <span>Review state</span>
                    <strong>{selectedTask.review_state ?? "Normal flow"}</strong>
                  </div>
                  <div>
                    <span>Scheduler rationale</span>
                    <strong>{selectedTask.scheduler_summary ?? "No explicit rationale yet."}</strong>
                  </div>
                  <div>
                    <span>Next retry</span>
                    <strong>{selectedTask.next_retry_at ? formatTime(selectedTask.next_retry_at) : "Ready now"}</strong>
                  </div>
                </div>
                <div className="detail-section">
                  <span>Scoped repo paths</span>
                  <p>{formatList(selectedTask.scoped_paths)}</p>
                </div>
                <div className="detail-section">
                  <span>Validation commands</span>
                  <p>{formatList(selectedTask.validation_commands)}</p>
                </div>
                <div className="detail-section">
                  <span>Git workspace</span>
                  <p>
                    {selectedTask.git_workspace_prepared
                      ? `${selectedTask.git_workspace_branch ?? "prepared"} · ${selectedTask.git_workspace_change_summary ?? "No change summary"}`
                      : selectedTask.git_workspace_supported
                        ? "Supported but not prepared yet."
                        : "Not supported for this task."}
                  </p>
                </div>
                {selectedTask.replan_summary ? (
                  <div className="detail-section">
                    <span>Replanning guidance</span>
                    <p>{selectedTask.replan_summary}</p>
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="empty-state empty-state--compact">
                <strong>No task is currently visible.</strong>
                <p>Adjust the filters or wait for work to enter the board.</p>
              </div>
            )}
          </div>
        </aside>
      </section>

      <section className="two-column-grid">
        <article className="surface-card">
          <div className="surface-card__header">
            <div>
              <span className="eyebrow">Goal hierarchy</span>
              <h2>Why the work exists</h2>
            </div>
            <span className="status-chip">{goalTree?.total_goals ?? 0} goals</span>
          </div>
          {(goalTree?.roots ?? []).length ? (
            <ul className="goal-preview">
              {goalTree?.roots.map((root) => <GoalTreePreview key={root.goal_id} node={root} />)}
            </ul>
          ) : (
            <div className="empty-state empty-state--compact">
              <strong>No goals are visible yet.</strong>
              <p>The board can still run, but goals make prioritization easier to understand.</p>
            </div>
          )}
        </article>

        <article className="surface-card">
          <div className="surface-card__header">
            <div>
              <span className="eyebrow">Repo-grounded plan</span>
              <h2>Imported codebase coverage</h2>
            </div>
            <span className="status-chip">
              {repoPlan?.generated_task_count ?? 0} synthesized items
            </span>
          </div>
          {repoPlan ? (
            <div className="list-stack">
              <div className="detail-grid detail-grid--compact">
                <div>
                  <span>Verification tasks</span>
                  <strong>{repoPlan.verification_task_count}</strong>
                </div>
                <div>
                  <span>Repo-area tasks</span>
                  <strong>{repoPlan.repo_area_task_count}</strong>
                </div>
                {repoPlanState ? (
                  <div>
                    <span>Active tasks</span>
                    <strong>{repoPlanState.active_task_count}</strong>
                  </div>
                ) : null}
                {repoPlanState ? (
                  <div>
                    <span>Last refreshed</span>
                    <strong>{formatTime(repoPlanState.last_refreshed_at)}</strong>
                  </div>
                ) : null}
              </div>
              {(repoPlan.items ?? []).slice(0, 8).map((item) => (
                <div key={item.synthesis_key} className="list-row">
                  <div>
                    <strong>{item.title}</strong>
                    <p>{item.source_label}</p>
                    <p>{formatList(item.paths)}</p>
                  </div>
                  <div className="list-row__meta">
                    <span className="status-pill">{item.task_kind}</span>
                    {item.command ? <span>{item.command}</span> : null}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="empty-state empty-state--compact">
              <strong>No repo-grounded plan data yet.</strong>
              <p>Brownfield projects will show synthesized task coverage here after planning refreshes.</p>
            </div>
          )}
        </article>
      </section>

      <details
        className="advanced-pane"
        onToggle={(event) => setAdvancedViewsOpen((event.currentTarget as HTMLDetailsElement).open)}
      >
        <summary>Advanced work views</summary>
        {advancedViewsOpen ? (
          <div className="advanced-pane__content">
            <div className="embedded-page">
              <BoardPage />
            </div>
            <div className="embedded-page">
              <GoalTreePage />
            </div>
          </div>
        ) : null}
      </details>
    </section>
  );
}
