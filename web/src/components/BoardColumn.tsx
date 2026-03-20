import type { BoardColumn as BoardColumnType, FilterOption } from "../types";
import { TaskCard } from "./TaskCard";

function laneDescription(column: BoardColumnType) {
  switch (column.key) {
    case "ready":
      return "Queued for allocation";
    case "assigned":
      return "Ready to launch";
    case "in_progress":
      return "Live execution";
    case "review":
      return "Waiting on operator";
    case "blocked":
      return "Stopped or waiting";
    case "planned":
      return "Not ready yet";
    case "done":
      return "Completed work";
    case "cancelled":
      return "Closed out";
    default:
      return "Tasks";
  }
}

function laneSecondary(column: BoardColumnType) {
  const criticalCount = column.tasks.filter((task) => task.priority >= 90).length;
  const blockedSignals = column.tasks.filter((task) => task.failure_count || task.next_retry_at).length;
  const focusedCount = column.tasks.filter((task) => task.status === "review" || task.status === "blocked").length;

  if (column.key === "review") {
    return criticalCount ? `${criticalCount} high priority` : "Decision queue";
  }
  if (column.key === "blocked") {
    if (blockedSignals) {
      return `${blockedSignals} with retry or failure signal`;
    }
    return "Needs intervention";
  }
  if (column.key === "in_progress") {
    return criticalCount ? `${criticalCount} critical in flight` : "Active owners";
  }
  if (column.key === "assigned") {
    return criticalCount ? `${criticalCount} critical launch-ready` : "Has an owner";
  }
  if (column.key === "ready") {
    return criticalCount ? `${criticalCount} critical next` : "Ordered by priority";
  }
  if (column.key === "planned") {
    return focusedCount ? `${focusedCount} carrying review state` : "Backlog";
  }
  return criticalCount ? `${criticalCount} critical` : `${column.tasks.length} total`;
}

interface BoardColumnProps {
  column: BoardColumnType;
  agentOptions?: FilterOption[];
  pendingActionKey?: string | null;
  focusedTaskId?: string | null;
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

export function BoardColumn({
  column,
  agentOptions,
  pendingActionKey,
  focusedTaskId,
  onInspect,
  onReviewAction,
  onAgentAction,
  onPriorityChange,
  onReassign,
  onHalt,
  onRecover,
  onRecoverAndRequeue,
  onMarkForReplan,
  onFinishReplan,
  onRunVerification,
  onPrepareGitWorkspace,
  onRefreshGitDiff,
  onRetryLimitChange
}: BoardColumnProps) {
  return (
    <section className="board-column">
      <header className="board-column__header">
        <div>
          <h2>{column.title}</h2>
          <p>
            {laneDescription(column)}
            {column.tasks.length ? ` · ${laneSecondary(column)}` : ""}
          </p>
        </div>
        <span className="board-column__count">
          {column.tasks.length}
        </span>
      </header>
      <div className="board-column__stack">
        {column.tasks.map((task) => (
          <TaskCard
            key={task.task_id}
            task={task}
            agentOptions={agentOptions}
            pendingActionKey={pendingActionKey}
            isFocused={focusedTaskId === task.task_id}
            onInspect={onInspect}
            onReviewAction={onReviewAction}
            onAgentAction={onAgentAction}
            onPriorityChange={onPriorityChange}
            onReassign={onReassign}
            onHalt={onHalt}
            onRecover={onRecover}
            onRecoverAndRequeue={onRecoverAndRequeue}
            onMarkForReplan={onMarkForReplan}
            onFinishReplan={onFinishReplan}
            onRunVerification={onRunVerification}
            onPrepareGitWorkspace={onPrepareGitWorkspace}
            onRefreshGitDiff={onRefreshGitDiff}
            onRetryLimitChange={onRetryLimitChange}
          />
        ))}
      </div>
    </section>
  );
}
