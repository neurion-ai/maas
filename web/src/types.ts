export type BoardColumnKey =
  | "planned"
  | "ready"
  | "in_progress"
  | "review"
  | "blocked"
  | "done"
  | "cancelled";

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
  status: BoardColumnKey | "assigned";
  priority: number;
  progress_pct?: number | null;
  heartbeat_age_seconds?: number | null;
  age_hours?: number | null;
  review_state?: string | null;
  goal?: BoardGoal | null;
  agent?: BoardAgent | null;
  failure_count?: number;
  latest_failure_at?: string | null;
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
  priority_min_values?: number[];
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

export interface OverviewProject {
  project_id: string;
  name: string;
  description: string;
  project_type: string;
}

export interface OverviewSummary {
  tasks_total: number;
  tasks_in_progress: number;
  tasks_review: number;
  tasks_blocked: number;
  goals_total: number;
  goals_active: number;
  alerts_open: number;
  alerts_critical: number;
  escalations_open: number;
  failures_total: number;
  repeated_failure_tasks: number;
  agents_running: number;
}

export interface OverviewWorkItem {
  task_id: string;
  title: string;
  status: string;
  priority: number;
  goal_title?: string | null;
  agent_name?: string | null;
}

export interface ActivityItem {
  activity_id?: string;
  action: string;
  description: string;
  severity: string;
  created_at: string;
  agent_id?: string | null;
  task_id?: string | null;
}

export interface OverviewResponse {
  project: OverviewProject | null;
  summary: OverviewSummary;
  active_work: OverviewWorkItem[];
  recent_activity: ActivityItem[];
  recent_failures: FailureItem[];
  repeated_failures: RepeatedFailureItem[];
}

export interface FailureItem {
  failure_id?: string;
  task_id?: string | null;
  session_id?: string | null;
  agent_id?: string | null;
  task_title?: string | null;
  agent_name?: string | null;
  failure_type: string;
  summary: string;
  detail_json?: string;
  quarantined_artifact_count?: number;
  quarantined_artifacts?: QuarantinedArtifactItem[];
  created_at: string;
}

export interface QuarantinedArtifactItem {
  artifact_id: string;
  path: string;
  quarantine_reason?: string | null;
  quarantined_from_path?: string | null;
}

export interface RepeatedFailureItem {
  task_id: string;
  task_title?: string | null;
  failure_count: number;
  latest_failure_at?: string | null;
}

export interface FailuresResponse {
  recent: FailureItem[];
  repeated_tasks: RepeatedFailureItem[];
  summary: {
    total_failures: number;
    tasks_with_failures: number;
    repeated_tasks: number;
  };
}

export interface GoalTreeNode {
  goal_id: string;
  parent_goal_id?: string | null;
  title: string;
  description: string;
  status: string;
  goal_type: string;
  priority: number;
  task_counts: Record<string, number>;
  children: GoalTreeNode[];
}

export interface GoalTreeResponse {
  roots: GoalTreeNode[];
  total_goals: number;
}

export interface AgentRosterEntry {
  agent_id: string;
  role: string;
  display_name: string;
  status: string;
  current_task_id?: string | null;
  current_task_title?: string | null;
  heartbeat_age_seconds?: number | null;
}

export interface AgentRosterResponse {
  agents: AgentRosterEntry[];
}

export interface AlertItem {
  alert_id: string;
  project_id?: string;
  severity: string;
  title: string;
  description: string;
  status: string;
  created_at: string;
  operator_action?: AlertOperatorAction;
}

export interface AlertOperatorAction {
  action: "recover_task" | "recover_agent" | "resolve_repeated_failures";
  label: string;
  resource_type: "task" | "agent";
  resource_id: string;
  related_task_id?: string;
}

export interface AlertsResponse {
  alerts: AlertItem[];
  grouped: Record<string, AlertItem[]>;
  summary: {
    open: number;
    acknowledged: number;
    resolved: number;
    critical_open: number;
    repeated_failure_open: number;
  };
}

export interface EscalationItem {
  escalation_id: string;
  project_id?: string;
  requested_by: string;
  requester_name?: string | null;
  action_type: string;
  resource_type: string;
  resource_id: string;
  payload_json: string;
  reason: string;
  status: string;
  resolved_by?: string | null;
  resolver_name?: string | null;
  resolution_note?: string | null;
  resolved_at?: string | null;
  created_at: string;
}

export interface EscalationsResponse {
  escalations: EscalationItem[];
  grouped: Record<string, EscalationItem[]>;
  summary: {
    open: number;
    approved: number;
    rejected: number;
  };
}

export interface LiveSnapshot {
  generated_at: string;
  counts: {
    tasks_in_progress: number;
    tasks_review: number;
    alerts_open: number;
    escalations_open: number;
    agents_running: number;
    failures_total: number;
    repeated_failure_tasks: number;
  };
  revision: {
    latest_task?: string | null;
    latest_activity?: string | null;
    latest_alert?: string | null;
    latest_escalation?: string | null;
    latest_failure?: string | null;
  };
}

export interface SupervisorReadyChange {
  task_id: string;
  status: string;
  review_state?: string | null;
}

export interface SupervisorAllocation {
  agent_id: string;
  task_id: string;
  task_title?: string;
  status: string;
  assigned: boolean;
  already_assigned?: boolean;
}

export interface SupervisorRunResponse {
  ready_changes: SupervisorReadyChange[];
  allocations: SupervisorAllocation[];
  assigned_count: number;
  stale_sessions: Array<{
    session_id: string;
    task_id: string;
    repeated_failure_alert?: {
      alert_id: string;
      task_id: string;
      failure_count: number;
    } | null;
  }>;
}
