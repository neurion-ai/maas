import type { BoardTask } from "../types";

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
  pendingActionKey?: string | null;
  onReviewAction?: (taskId: string, decision: "approve" | "reject") => void;
  onAgentAction?: (agentId: string, action: "pause" | "resume") => void;
}

export function TaskCard({
  task,
  pendingActionKey,
  onReviewAction,
  onAgentAction
}: TaskCardProps) {
  const reviewApproveKey = `review:${task.task_id}:approve`;
  const reviewRejectKey = `review:${task.task_id}:reject`;
  const agentActionKey = task.agent?.id ? `agent:${task.agent.id}:${task.agent.status === "paused" ? "resume" : "pause"}` : null;
  const isPendingReviewApprove = pendingActionKey === reviewApproveKey;
  const isPendingReviewReject = pendingActionKey === reviewRejectKey;
  const isPendingAgentAction = pendingActionKey === agentActionKey;
  const canReview = task.status === "review" && !!onReviewAction;
  const canToggleAgent = !!task.agent?.id && !!onAgentAction && (task.agent?.status === "running" || task.agent?.status === "paused");

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
      </dl>
      {(canReview || canToggleAgent) && (
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
        </div>
      )}
    </article>
  );
}
