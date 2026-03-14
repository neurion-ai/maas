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

export function TaskCard({ task }: { task: BoardTask }) {
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
    </article>
  );
}
