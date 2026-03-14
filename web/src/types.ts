export type BoardColumnKey =
  | "planned"
  | "ready"
  | "in_progress"
  | "review"
  | "blocked"
  | "done";

export interface BoardAgent {
  id: string;
  name: string;
  status?: string;
}

export interface BoardGoal {
  id: string;
  title: string;
}

export interface BoardTask {
  task_id: string;
  title: string;
  status: BoardColumnKey | "assigned" | "cancelled";
  priority: number;
  progress_pct?: number | null;
  heartbeat_age_seconds?: number | null;
  age_hours?: number | null;
  review_state?: string | null;
  goal?: BoardGoal | null;
  agent?: BoardAgent | null;
}

export interface BoardColumn {
  key: BoardColumnKey;
  title: string;
  tasks: BoardTask[];
}

export interface BoardSummary {
  total_tasks: number;
  active_agents: number;
  blocked_tasks: number;
  review_tasks: number;
}

export interface BoardResponse {
  generated_at: string;
  summary: BoardSummary;
  columns: BoardColumn[];
}
