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

function formatHeartbeat(seconds?: number | null) {
  if (seconds == null) {
    return "No heartbeat";
  }
  if (seconds < 60) {
    return `${seconds}s ago`;
  }
  return `${Math.round(seconds / 60)}m ago`;
}

function formatAge(hours?: number | null) {
  if (hours == null) {
    return "New";
  }
  if (hours < 1) {
    return `${Math.round(hours * 60)}m old`;
  }
  if (hours < 24) {
    return `${hours.toFixed(1)}h old`;
  }
  return `${(hours / 24).toFixed(1)}d old`;
}

interface TaskCardProps {
  task: BoardTask;
  agentOptions?: FilterOption[];
  pendingActionKey?: string | null;
  onReviewAction?: (taskId: string, decision: "approve" | "reject") => void;
  onAgentAction?: (agentId: string, action: "pause" | "resume") => void;
  onPriorityChange?: (taskId: string, priority: number) => void;
  onReassign?: (taskId: string, agentId: string) => void;
  onHalt?: (taskId: string) => void;
  onRecover?: (taskId: string) => void;
  onRecoverAndRequeue?: (taskId: string) => void;
  onRetryLimitChange?: (taskId: string, autoRetryLimit: number | null) => void;
}

export function TaskCard({
  task,
  agentOptions = [],
  pendingActionKey,
  onReviewAction,
  onAgentAction,
  onPriorityChange,
  onReassign,
  onHalt,
  onRecover,
  onRecoverAndRequeue,
  onRetryLimitChange
}: TaskCardProps) {
  const reviewApproveKey = `review:${task.task_id}:approve`;
  const reviewRejectKey = `review:${task.task_id}:reject`;
  const agentActionKey = task.agent?.id ? `agent:${task.agent.id}:${task.agent.status === "paused" ? "resume" : "pause"}` : null;
  const reprioritizeKey = `reprioritize:${task.task_id}`;
  const reassignKey = `reassign:${task.task_id}`;
  const haltKey = `halt:${task.task_id}`;
  const recoverKey = `recover:${task.task_id}`;
  const recoverAndRequeueKey = `recover-and-requeue:${task.task_id}`;
  const retryLimitKey = `retry-limit:${task.task_id}`;
  const isPendingReviewApprove = pendingActionKey === reviewApproveKey;
  const isPendingReviewReject = pendingActionKey === reviewRejectKey;
  const isPendingAgentAction = pendingActionKey === agentActionKey;
  const isPendingReprioritize = pendingActionKey === reprioritizeKey;
  const isPendingReassign = pendingActionKey === reassignKey;
  const isPendingHalt = pendingActionKey === haltKey;
  const isPendingRecover = pendingActionKey === recoverKey;
  const isPendingRecoverAndRequeue = pendingActionKey === recoverAndRequeueKey;
  const isPendingRetryLimit = pendingActionKey === retryLimitKey;
  const canReview = task.status === "review" && !!onReviewAction;
  const canToggleAgent = !!task.agent?.id && !!onAgentAction && (task.agent?.status === "running" || task.agent?.status === "paused");
  const canSteerTask = task.status !== "done" && task.status !== "cancelled";
  const canReassign = canSteerTask && task.status !== "in_progress" && !!onReassign && agentOptions.length > 0;
  const canReprioritize = canSteerTask && !!onPriorityChange;
  const canHalt = canSteerTask && !!onHalt;
  const canRecover =
    task.status === "blocked" && !!onRecover && RECOVERABLE_REVIEW_STATES.has(task.review_state ?? "");
  const canRecoverAndRequeue =
    task.status === "blocked" && !!onRecoverAndRequeue && RECOVERABLE_REVIEW_STATES.has(task.review_state ?? "");
  const canSetRetryLimit = canSteerTask && !!onRetryLimitChange;
  const retryLimitOptions = Array.from(
    new Set(
      [null, 0, 1, 2, 3, 5, 10, task.auto_retry_limit ?? null].filter((value) => value === null || value >= 0)
    )
  ) as Array<number | null>;

  return (
    <article className={`task-card task-card--${task.status}`}>
      <div className="task-card__meta">
        <span className="task-card__badge">{formatPriority(task.priority)}</span>
        <span className="task-card__id">{task.task_id}</span>
      </div>
      <h3>{task.title}</h3>
      <dl className="task-card__details">
        <div>
          <dt>Goal</dt>
          <dd>{task.goal?.title ?? "Unlinked"}</dd>
        </div>
        <div>
          <dt>Agent</dt>
          <dd>{task.agent?.name ?? "Unassigned"}</dd>
        </div>
        <div>
          <dt>Progress</dt>
          <dd>{task.progress_pct != null ? `${task.progress_pct}%` : "Not started"}</dd>
        </div>
        <div>
          <dt>Heartbeat</dt>
          <dd>{formatHeartbeat(task.heartbeat_age_seconds)}</dd>
        </div>
        <div>
          <dt>Age</dt>
          <dd>{formatAge(task.age_hours)}</dd>
        </div>
        <div>
          <dt>Review</dt>
          <dd>{task.review_state ?? "Not in review"}</dd>
        </div>
        <div>
          <dt>Failures</dt>
          <dd>{task.failure_count ? `${task.failure_count} logged` : "None"}</dd>
        </div>
        <div>
          <dt>Retries</dt>
          <dd>
            {task.retry_count
              ? `${task.retry_count} auto retr${task.retry_count === 1 ? "y" : "ies"}${task.last_retry_reason ? ` (${task.last_retry_reason})` : ""}`
              : "None"}
          </dd>
        </div>
        <div>
          <dt>Retry budget</dt>
          <dd>{task.auto_retry_limit == null ? "Project default" : `${task.auto_retry_limit} max auto retries`}</dd>
        </div>
        <div>
          <dt>Next retry</dt>
          <dd>
            {task.next_retry_at
              ? `${new Date(task.next_retry_at).toLocaleString()}${task.next_retry_reason ? ` (${task.next_retry_reason})` : ""}`
              : "Ready now"}
          </dd>
        </div>
      </dl>
      {(canReview || canToggleAgent || canReassign || canReprioritize || canHalt || canRecover || canRecoverAndRequeue || canSetRetryLimit) && (
        <div className="task-card__actions">
          {canReview && (
            <>
              <button
                type="button"
                className="task-action task-action--approve"
                disabled={isPendingReviewApprove || isPendingReviewReject}
                onClick={() => onReviewAction?.(task.task_id, "approve")}
              >
                {isPendingReviewApprove ? "Approving..." : "Approve"}
              </button>
              <button
                type="button"
                className="task-action task-action--reject"
                disabled={isPendingReviewApprove || isPendingReviewReject}
                onClick={() => onReviewAction?.(task.task_id, "reject")}
              >
                {isPendingReviewReject ? "Rejecting..." : "Reject"}
              </button>
            </>
          )}
          {canReprioritize && (
            <label className="task-inline-control">
              <span>Priority</span>
              <select
                value={String(task.priority)}
                disabled={isPendingReprioritize}
                onChange={(event) => onPriorityChange?.(task.task_id, Number(event.target.value))}
              >
                {[50, 75, 90, 100].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
          )}
          {canReassign && (
            <label className="task-inline-control">
              <span>Assign</span>
              <select
                value={task.agent?.id ?? ""}
                disabled={isPendingReassign}
                onChange={(event) => onReassign?.(task.task_id, event.target.value)}
              >
                <option value="" disabled>
                  Select agent
                </option>
                {agentOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          {canSetRetryLimit && (
            <label className="task-inline-control">
              <span>Retry limit</span>
              <select
                value={task.auto_retry_limit == null ? "" : String(task.auto_retry_limit)}
                disabled={isPendingRetryLimit}
                onChange={(event) =>
                  onRetryLimitChange?.(
                    task.task_id,
                    event.target.value === "" ? null : Number(event.target.value)
                  )
                }
              >
                {retryLimitOptions.map((value) => (
                  <option key={value == null ? "default" : value} value={value == null ? "" : String(value)}>
                    {value == null ? "Project default" : value}
                  </option>
                ))}
              </select>
            </label>
          )}
          {canToggleAgent && task.agent?.id && (
            <button
              type="button"
              className="task-action task-action--secondary"
              disabled={isPendingAgentAction}
              onClick={() =>
                onAgentAction?.(task.agent!.id, task.agent?.status === "paused" ? "resume" : "pause")
              }
            >
              {isPendingAgentAction
                ? task.agent?.status === "paused"
                  ? "Resuming..."
                  : "Pausing..."
                : task.agent?.status === "paused"
                  ? "Resume Agent"
                  : "Pause Agent"}
            </button>
          )}
          {canHalt && (
            <button
              type="button"
              className="task-action task-action--reject"
              disabled={isPendingHalt}
              onClick={() => onHalt?.(task.task_id)}
            >
              {isPendingHalt ? "Halting..." : "Halt task"}
            </button>
          )}
          {canRecover && (
            <button
              type="button"
              className="task-action task-action--approve"
              disabled={isPendingRecover || isPendingRecoverAndRequeue}
              onClick={() => onRecover?.(task.task_id)}
            >
              {isPendingRecover ? "Recovering..." : "Recover task"}
            </button>
          )}
          {canRecoverAndRequeue && (
            <button
              type="button"
              className="task-action task-action--secondary"
              disabled={isPendingRecover || isPendingRecoverAndRequeue}
              onClick={() => onRecoverAndRequeue?.(task.task_id)}
            >
              {isPendingRecoverAndRequeue ? "Requeueing..." : "Recover + requeue"}
            </button>
          )}
        </div>
      )}
    </article>
  );
}
