import type { BoardColumn, BoardTask, PortfolioProject } from "../types";

export type CodexWorkStatus = "todo" | "in_progress" | "review" | "blocked" | "done";

export function mapBoardStatus(status: BoardTask["status"]): CodexWorkStatus {
  if (status === "in_progress") {
    return "in_progress";
  }
  if (status === "review") {
    return "review";
  }
  if (status === "blocked") {
    return "blocked";
  }
  if (status === "done") {
    return "done";
  }
  return "todo";
}

export function flattenBoard(columns: BoardColumn[]): BoardTask[] {
  return columns.flatMap((column) => column.tasks);
}

export function openBoardTasks(columns: BoardColumn[]) {
  return flattenBoard(columns).filter((task) => task.status !== "done" && task.status !== "cancelled");
}

export function resolvedBoardTasks(columns: BoardColumn[]) {
  return flattenBoard(columns).filter((task) => task.status === "done" || task.status === "cancelled");
}

export function operatorQueueTasks(tasks: BoardTask[]) {
  return tasks
    .filter((task) => task.status === "review" || task.status === "blocked")
    .sort((left, right) => right.priority - left.priority);
}

export function issueKeyMap(columns: BoardColumn[]) {
  const ordered = [...flattenBoard(columns)].sort((left, right) => {
    return left.priority === right.priority ? left.title.localeCompare(right.title) : right.priority - left.priority;
  });
  return new Map(
    ordered.map((task, index) => [
      task.task_id,
      `ISS-${String(index + 1).padStart(3, "0")}`,
    ])
  );
}

export function boardCounts(columns: BoardColumn[]) {
  const open = openBoardTasks(columns);
  const resolved = resolvedBoardTasks(columns);
  return {
    todo: open.filter((task) => mapBoardStatus(task.status) === "todo").length,
    in_progress: open.filter((task) => mapBoardStatus(task.status) === "in_progress").length,
    review: open.filter((task) => mapBoardStatus(task.status) === "review").length,
    blocked: open.filter((task) => mapBoardStatus(task.status) === "blocked").length,
    done: resolved.length,
  };
}

export function priorityLabel(priority: number) {
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

export function statusLabel(status: string, reviewState?: string | null) {
  if (status === "review" && reviewState) {
    return reviewState.replaceAll("_", " ");
  }
  return status.replaceAll("_", " ");
}

export function nextActionLabel(task: BoardTask) {
  if (task.status === "review") {
    return "Review and decide";
  }
  if (task.status === "blocked") {
    if (task.review_state === "needs_replan") {
      return "Replan or recover";
    }
    if (task.review_state === "circuit_breaker_open") {
      return "Clear circuit breaker";
    }
    return "Unblock dependency or recover";
  }
  if (task.status === "in_progress") {
    return "Watch current run";
  }
  if (task.status === "assigned") {
    return "Let the next cycle launch it";
  }
  if (task.status === "ready" || task.status === "planned") {
    return "Ready for the next cycle";
  }
  if (task.status === "done") {
    return "Review landed output";
  }
  return "Inspect issue";
}

export function formatTimestamp(value?: string | null) {
  if (!value) {
    return "Not recorded";
  }
  return new Date(value).toLocaleString();
}

export type CodexRunControlState =
  | { mode: "run"; label: "Run" }
  | { mode: "pause"; label: "Pause" }
  | { mode: "resume"; label: "Resume" };

export function resolveRunControlState(project: PortfolioProject | null, tasks: BoardTask[]): CodexRunControlState {
  if (!project) {
    return { mode: "run", label: "Run" };
  }
  if (project.provider_capacity.queue_mode === "paused" || project.provider_capacity.queue_mode === "draining") {
    return { mode: "resume", label: "Resume" };
  }
  if (
    project.active_sessions > 0 ||
    project.provider_capacity.running_jobs > 0 ||
    project.provider_capacity.queued_jobs > 0 ||
    tasks.some((task) => task.status === "in_progress")
  ) {
    return { mode: "pause", label: "Pause" };
  }
  return { mode: "run", label: "Run" };
}
