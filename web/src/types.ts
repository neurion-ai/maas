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
  description?: string;
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
  active_tasks?: number;
  blocked_tasks: number;
  review_tasks: number;
}

export interface FilterOption {
  id: string;
  label: string;
}

export interface BoardFilterOptions {
  agents?: FilterOption[];
  goals?: FilterOption[];
}

export interface BoardFiltersInput {
  search?: string;
  blockedOnly?: boolean;
  reviewOnly?: boolean;
  priorityMin?: number;
  agentId?: string;
  goalId?: string;
}

export interface BoardResponse {
  generated_at: string;
  summary: BoardSummary;
  columns: BoardColumn[];
  filters?: string[];
  filter_options?: BoardFilterOptions;
  selected_filters?: {
    search?: string;
    blocked_only?: boolean;
    review_only?: boolean;
    priority_min?: number | null;
    agent_id?: string | null;
    goal_id?: string | null;
  };
}
