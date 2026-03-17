import type { BoardColumn as BoardColumnType, FilterOption } from "../types";
import { TaskCard } from "./TaskCard";

interface BoardColumnProps {
  column: BoardColumnType;
  agentOptions?: FilterOption[];
  pendingActionKey?: string | null;
  onReviewAction?: (taskId: string, decision: "approve" | "reject") => void;
  onAgentAction?: (agentId: string, action: "pause" | "resume") => void;
  onPriorityChange?: (taskId: string, priority: number) => void;
  onReassign?: (taskId: string, agentId: string) => void;
  onHalt?: (taskId: string) => void;
  onRecover?: (taskId: string) => void;
  onRecoverAndRequeue?: (taskId: string) => void;
  onMarkForReplan?: (taskId: string) => void;
  onFinishReplan?: (taskId: string) => void;
  onRetryLimitChange?: (taskId: string, autoRetryLimit: number | null) => void;
}

export function BoardColumn({
  column,
  agentOptions,
  pendingActionKey,
  onReviewAction,
  onAgentAction,
  onPriorityChange,
  onReassign,
  onHalt,
  onRecover,
  onRecoverAndRequeue,
  onMarkForReplan,
  onFinishReplan,
  onRetryLimitChange
}: BoardColumnProps) {
  return (
    <section className="board-column">
      <header className="board-column__header">
        <div>
          <h2>{column.title}</h2>
          <p>{column.tasks.length} tasks</p>
        </div>
        <span className="board-column__count">{column.tasks.length}</span>
      </header>
      <div className="board-column__stack">
        {column.tasks.map((task) => (
          <TaskCard
            key={task.task_id}
            task={task}
            agentOptions={agentOptions}
            pendingActionKey={pendingActionKey}
            onReviewAction={onReviewAction}
            onAgentAction={onAgentAction}
            onPriorityChange={onPriorityChange}
            onReassign={onReassign}
            onHalt={onHalt}
            onRecover={onRecover}
            onRecoverAndRequeue={onRecoverAndRequeue}
            onMarkForReplan={onMarkForReplan}
            onFinishReplan={onFinishReplan}
            onRetryLimitChange={onRetryLimitChange}
          />
        ))}
      </div>
    </section>
  );
}
