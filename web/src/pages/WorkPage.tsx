import { startTransition, useDeferredValue, useEffect, useMemo, useState } from "react";
import { BoardColumn } from "../components/BoardColumn";
import { TaskInspector } from "../components/TaskInspector";
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
import { consumePendingTaskFocus } from "../lib/taskFocus";
import { brownfieldRepoPlanItems, brownfieldRepoPlanTrust } from "../lib/brownfield";
import { fetchGoalTree, fetchOverview } from "../lib/controlRoomApi";
import { useLivePulse } from "../lib/useLivePulse";
import type { BoardFiltersInput, BoardResponse, FilterOption, GoalTreeNode, GoalTreeResponse, OverviewResponse } from "../types";

type WorkFocus = "all" | "execution" | "attention";
type WorkViewTarget = "home" | "runs" | "incidents" | "projects";

interface WorkPageProps {
  onNavigate: (view: WorkViewTarget) => void;
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

function matchRepoPlanItems(task: NonNullable<BoardResponse>["columns"][number]["tasks"][number], overview: OverviewResponse | null) {
  const items = brownfieldRepoPlanItems(overview?.onboarding);
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

export function WorkPage({ onNavigate }: WorkPageProps) {
  const [board, setBoard] = useState<BoardResponse | null>(null);
  const [goalTree, setGoalTree] = useState<GoalTreeResponse | null>(null);
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [query, setQuery] = useState("");
  const [focus, setFocus] = useState<WorkFocus>("all");
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingActionKey, setPendingActionKey] = useState<string | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [externalTaskFocusId, setExternalTaskFocusId] = useState<string | null>(() => consumePendingTaskFocus());
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
  const pendingImportReview =
    overview?.onboarding?.mode === "brownfield" &&
    !!overview?.onboarding?.review_status &&
    !["approved", "reviewed", "not_applicable"].includes(overview.onboarding.review_status);
  const brownfieldTrust = brownfieldRepoPlanTrust(overview?.onboarding);
  const reviewTaskId = overview?.onboarding?.review_task_id ?? null;
  const gatedBlockedTaskCount = useMemo(
    () =>
      (board?.columns ?? [])
        .find((column) => column.key === "blocked")
        ?.tasks.filter((task) => task.review_state === "awaiting_onboarding_approval").length ?? 0,
    [board]
  );
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

  useEffect(() => {
    if (!externalTaskFocusId || !allTasks.length) {
      return;
    }
    const externallyFocusedTask = allTasks.find((task) => task.task_id === externalTaskFocusId);
    if (externallyFocusedTask) {
      setSelectedTaskId(externallyFocusedTask.task_id);
      setExternalTaskFocusId(null);
      return;
    }
    setSelectedTaskId(externalTaskFocusId);
    setExternalTaskFocusId(null);
  }, [allTasks, externalTaskFocusId]);

  const agentOptions = useMemo<FilterOption[]>(() => board?.filter_options?.agents ?? [], [board]);
  const visibleColumns = useMemo(() => {
    const normalizedColumns = (board?.columns ?? []).map((column) =>
      pendingImportReview && column.key === "blocked"
        ? {
            ...column,
            tasks: column.tasks.filter((task) => task.review_state !== "awaiting_onboarding_approval")
          }
        : column
    );
    const orderedKeys = ["ready", "assigned", "in_progress", "review", "blocked", "planned"] as const;
    const byKey = new Map(normalizedColumns.map((column) => [column.key, column] as const));
    const prioritized = orderedKeys
      .map((key) => byKey.get(key))
      .filter((column): column is NonNullable<typeof board>["columns"][number] => Boolean(column));
    const visible = prioritized.filter((column) => column.tasks.length > 0);
    return visible.length ? visible : prioritized.slice(0, 3);
  }, [board, pendingImportReview]);
  const collapsedColumns = useMemo(
    () =>
      (board?.columns ?? [])
        .filter((column) => !visibleColumns.some((visible) => visible.key === column.key))
        .filter((column) => column.tasks.length > 0)
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

  return (
    <section className="dashboard-page workbench-page">
      <header className="workbench-header surface-card surface-card--dense">
        <div className="workbench-header__copy">
          <span className="eyebrow">Board</span>
          <h1>Execution workspace</h1>
          <p>The board is the only place for task flow, task detail, and operator steering.</p>
          <div className="hero-meta">
            <span className="hero-meta__pill">{allTasks.length} visible tasks</span>
            <span className="hero-meta__pill">{board?.summary.active_tasks ?? board?.summary.total_tasks ?? 0} active flow</span>
            <span className="hero-meta__pill">{board?.summary.review_tasks ?? 0} in review</span>
          </div>
        </div>
        <div className="workbench-header__controls">
          <label className="field-control field-control--search">
            <span>Search</span>
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

      {pendingImportReview ? (
        <article className="surface-card surface-card--dense workbench-callout">
          <div className="surface-card__header surface-card__header--tight">
            <div>
              <span className="eyebrow">Import review</span>
              <h2>This board is partially gated by import review</h2>
              <p>
                {gatedBlockedTaskCount} blocked task{gatedBlockedTaskCount === 1 ? "" : "s"} are gated by brownfield onboarding.
                Handle the release decision from Cockpit, not from individual blocked cards.
              </p>
            </div>
            <span className="status-pill status-pill--warn">
              {overview?.onboarding?.review_task_status
                ? overview.onboarding.review_task_status.replaceAll("_", " ")
                : "review pending"}
            </span>
          </div>
          <div className="workbench-callout__actions">
            <button
              type="button"
              className="hero-button hero-button--primary hero-button--compact"
              onClick={() => onNavigate("home")}
            >
              Open cockpit
            </button>
            {reviewTaskId ? (
              <button
                type="button"
                className="hero-button hero-button--ghost hero-button--compact"
                onClick={() => setSelectedTaskId(reviewTaskId)}
              >
                Select review task
              </button>
            ) : null}
          </div>
        </article>
      ) : null}

      {overview?.onboarding?.mode === "brownfield" && brownfieldTrust && brownfieldTrust.state !== "fresh" ? (
        <article className="surface-card surface-card--dense workbench-callout">
          <div className="surface-card__header surface-card__header--tight">
            <div>
              <span className="eyebrow">Brownfield trust</span>
              <h2>{brownfieldTrust.summary}</h2>
              <p>{brownfieldTrust.detail}</p>
              <p>Recommended action: {brownfieldTrust.recommended_action}</p>
            </div>
            <span className={`status-pill ${brownfieldTrust.safe_to_execute ? "" : "status-pill--warn"}`.trim()}>
              {brownfieldTrust.state.replaceAll("_", " ")} · drift {brownfieldTrust.drift_severity}
            </span>
          </div>
          <div className="workbench-callout__actions">
            <button
              type="button"
              className="hero-button hero-button--primary hero-button--compact"
              onClick={() => onNavigate("home")}
            >
              Open cockpit
            </button>
            <button
              type="button"
              className="hero-button hero-button--ghost hero-button--compact"
              onClick={() => onNavigate("projects")}
            >
              Open projects
            </button>
          </div>
        </article>
      ) : null}

      <section className="workbench-layout">
        <div className="workbench-layout__board">
          <article className="surface-card surface-card--flush">
            <div className="surface-card__header surface-card__header--tight">
              <div>
                <span className="eyebrow">Board</span>
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
                />
              ))}
            </div>
          </article>
        </div>

        <aside className="workbench-layout__inspector">
          <article className="surface-card surface-card--dense">
            <div className="surface-card__header surface-card__header--tight">
              <div>
                <span className="eyebrow">Inspector</span>
                <h2>{selectedTask ? "Task detail" : "Select a card"}</h2>
              </div>
            </div>
            <TaskInspector
              task={selectedTask}
              agentOptions={agentOptions}
              pendingActionKey={pendingActionKey}
              goalPath={selectedTask ? findGoalPath(goalTree?.roots ?? [], selectedTask.goal?.id ?? null) ?? [] : []}
              siblingTasks={
                selectedTask?.goal?.id
                  ? allTasks.filter((task) => task.goal?.id === selectedTask.goal?.id && task.task_id !== selectedTask.task_id)
                  : []
              }
              repoPlanItems={
                selectedTask
                  ? matchRepoPlanItems(selectedTask, overview).slice(0, 6)
                  : []
              }
              onSelectSibling={setSelectedTaskId}
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
          </article>
        </aside>
      </section>
    </section>
  );
}
