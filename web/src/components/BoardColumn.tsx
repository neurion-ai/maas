import type { BoardColumn as BoardColumnType } from "../types";
import { TaskCard } from "./TaskCard";

interface BoardColumnProps {
  column: BoardColumnType;
  pendingActionKey?: string | null;
  onReviewAction?: (taskId: string, decision: "approve" | "reject") => void;
  onAgentAction?: (agentId: string, action: "pause" | "resume") => void;
}

export function BoardColumn({ column, pendingActionKey, onReviewAction, onAgentAction }: BoardColumnProps) {
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
            pendingActionKey={pendingActionKey}
            onReviewAction={onReviewAction}
            onAgentAction={onAgentAction}
          />
        ))}
      </div>
    </section>
  );
}
