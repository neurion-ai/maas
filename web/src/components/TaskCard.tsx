import type { BoardTask, FilterOption } from "../types";

const RECOVERABLE_REVIEW_STATES = new Set(["session_failed", "stale_session"]);

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

function formatSignalLabel(task: BoardTask) {
  if (task.review_state) {
    return task.review_state.replaceAll("_", " ");
  }
  if (task.next_retry_at) {
    return "retry pending";
  }
  if (task.latest_verification_status) {
    return task.latest_verification_status;
  }
  return task.scheduler_summary ?? "normal flow";
}

interface TaskCardProps {
  task: BoardTask;
  agentOptions?: FilterOption[];
  pendingActionKey?: string | null;
  isFocused?: boolean;
  onInspect?: (taskId: string) => void;
  onReviewAction?: (taskId: string, decision: "approve" | "reject") => void;
  onAgentAction?: (agentId: string, action: "pause" | "resume") => void;
  onPriorityChange?: (taskId: string, priority: number) => void;
  onReassign?: (taskId: string, agentId: string) => void;
  onHalt?: (taskId: string) => void;
  onRecover?: (taskId: string) => void;
  onRecoverAndRequeue?: (taskId: string) => void;
  onMarkForReplan?: (taskId: string) => void;
  onFinishReplan?: (taskId: string) => void;
  onRunVerification?: (taskId: string) => void;
  onPrepareGitWorkspace?: (taskId: string) => void;
  onRefreshGitDiff?: (taskId: string) => void;
  onRetryLimitChange?: (taskId: string, autoRetryLimit: number | null) => void;
}

export function TaskCard({
  task,
  pendingActionKey,
  isFocused = false,
  onInspect,
  onReviewAction,
  onRecover,
  onRecoverAndRequeue,
  onMarkForReplan,
  onFinishReplan,
  onPrepareGitWorkspace
}: TaskCardProps) {
  const canReview = task.status === "review" && !!onReviewAction;
  const canRecover =
    task.status === "blocked" && !!onRecover && RECOVERABLE_REVIEW_STATES.has(task.review_state ?? "");
  const canRecoverAndRequeue =
    task.status === "blocked" && !!onRecoverAndRequeue && RECOVERABLE_REVIEW_STATES.has(task.review_state ?? "");
  const canMarkForReplan =
    task.status !== "in_progress" &&
    task.status !== "done" &&
    task.status !== "cancelled" &&
    task.status !== "review" &&
    task.review_state !== "needs_replan" &&
    !!onMarkForReplan &&
    ((task.retry_count ?? 0) > 0 ||
      !!task.next_retry_at ||
      task.review_state === "retry_backoff" ||
      RECOVERABLE_REVIEW_STATES.has(task.review_state ?? ""));
  const canFinishReplan = task.status === "blocked" && task.review_state === "needs_replan" && !!onFinishReplan;
  const canPrepareGitWorkspace = !!task.git_workspace_supported && !task.git_workspace_prepared && !!onPrepareGitWorkspace;

  return (
    <article className={`task-card task-card--compact ${isFocused ? "is-focused" : ""}`}>
      <div className="task-card__meta">
        <span className="task-card__badge">{formatPriority(task.priority)}</span>
        <span className="task-card__state">{task.status.replaceAll("_", " ")}</span>
      </div>

      <div className="task-card__header">
        <div>
          <h3>{task.title}</h3>
          <p className="task-card__lead">{task.goal?.title ?? "Unlinked goal"}</p>
        </div>
        {onInspect ? (
          isFocused ? (
            <span className="task-card__selection" aria-label="Selected task">
              Selected
            </span>
          ) : (
            <button
              type="button"
              className="task-action task-action--ghost"
              onClick={() => onInspect(task.task_id)}
            >
              Inspect
            </button>
          )
        ) : null}
      </div>

      <div className="task-card__summary">
        <span>{task.agent?.name ?? "Unassigned"}</span>
        <span>{task.failure_count ? `${task.failure_count} failures` : "No failures"}</span>
        <span>{task.progress_pct != null ? `${task.progress_pct}% progress` : "Not started"}</span>
      </div>

      <p className="task-card__context">{formatSignalLabel(task)}</p>

      {(task.scoped_paths?.length || task.validation_commands?.length) ? (
        <div className="task-card__signals">
          {task.scoped_paths?.length ? <span>scope {task.scoped_paths.slice(0, 2).join(", ")}</span> : null}
          {task.validation_commands?.length ? <span>verify {task.validation_commands[0]}</span> : null}
        </div>
      ) : null}

      {(canReview || canRecover || canRecoverAndRequeue || canMarkForReplan || canFinishReplan || canPrepareGitWorkspace) ? (
        <div className="task-card__actions">
          {canReview ? (
            <>
              <button
                type="button"
                className="task-action task-action--approve"
                disabled={pendingActionKey === `review:${task.task_id}:approve`}
                onClick={() => onReviewAction?.(task.task_id, "approve")}
              >
                {pendingActionKey === `review:${task.task_id}:approve` ? "Working..." : "Approve"}
              </button>
              <button
                type="button"
                className="task-action task-action--reject"
                disabled={pendingActionKey === `review:${task.task_id}:reject`}
                onClick={() => onReviewAction?.(task.task_id, "reject")}
              >
                {pendingActionKey === `review:${task.task_id}:reject` ? "Working..." : "Changes"}
              </button>
            </>
          ) : null}
          {!canReview && canRecoverAndRequeue ? (
            <button
              type="button"
              className="task-action task-action--approve"
              disabled={pendingActionKey === `recover-and-requeue:${task.task_id}`}
              onClick={() => onRecoverAndRequeue?.(task.task_id)}
            >
              {pendingActionKey === `recover-and-requeue:${task.task_id}` ? "Working..." : "Recover + requeue"}
            </button>
          ) : null}
          {!canReview && !canRecoverAndRequeue && canRecover ? (
            <button
              type="button"
              className="task-action task-action--secondary"
              disabled={pendingActionKey === `recover:${task.task_id}`}
              onClick={() => onRecover?.(task.task_id)}
            >
              {pendingActionKey === `recover:${task.task_id}` ? "Working..." : "Recover"}
            </button>
          ) : null}
          {!canReview && !canRecover && !canRecoverAndRequeue && canFinishReplan ? (
            <button
              type="button"
              className="task-action task-action--approve"
              disabled={pendingActionKey === `finish-replan:${task.task_id}`}
              onClick={() => onFinishReplan?.(task.task_id)}
            >
              {pendingActionKey === `finish-replan:${task.task_id}` ? "Working..." : "Finish replan"}
            </button>
          ) : null}
          {!canReview && !canRecover && !canRecoverAndRequeue && !canFinishReplan && canMarkForReplan ? (
            <button
              type="button"
              className="task-action task-action--ghost"
              disabled={pendingActionKey === `mark-for-replan:${task.task_id}`}
              onClick={() => onMarkForReplan?.(task.task_id)}
            >
              {pendingActionKey === `mark-for-replan:${task.task_id}` ? "Working..." : "Mark for replan"}
            </button>
          ) : null}
          {!canReview && !canRecover && !canRecoverAndRequeue && !canFinishReplan && !canMarkForReplan && canPrepareGitWorkspace ? (
            <button
              type="button"
              className="task-action task-action--ghost"
              disabled={pendingActionKey === `prepare-git-workspace:${task.task_id}`}
              onClick={() => onPrepareGitWorkspace?.(task.task_id)}
            >
              {pendingActionKey === `prepare-git-workspace:${task.task_id}` ? "Working..." : "Prepare git"}
            </button>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}
