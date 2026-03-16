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
  retry_count?: number;
  last_retry_at?: string | null;
  last_retry_reason?: string | null;
  next_retry_at?: string | null;
  next_retry_reason?: string | null;
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
  retry_count?: number;
  last_retry_reason?: string | null;
  next_retry_at?: string | null;
  next_retry_reason?: string | null;
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
  retry_count?: number;
  last_retry_at?: string | null;
  last_retry_reason?: string | null;
  next_retry_at?: string | null;
  next_retry_reason?: string | null;
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

export interface QuarantineQueueItem {
  queue_id: string;
  session_id: string;
  failure_id?: string | null;
  task_id?: string | null;
  task_title?: string | null;
  agent_name?: string | null;
  failure_type?: string | null;
  summary?: string | null;
  status: "open" | "restored" | "dismissed";
  reason?: string | null;
  artifact_count: number;
  resolution_note?: string | null;
  created_at: string;
  updated_at: string;
  resolved_at?: string | null;
  quarantined_artifacts?: QuarantinedArtifactItem[];
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

export interface RestoreFailureArtifactsResponse {
  failure_id: string;
  session_id: string;
  restored_artifacts: QuarantinedArtifactItem[];
  restored_count: number;
}

export interface QuarantineQueueResponse {
  entries: QuarantineQueueItem[];
  summary: {
    open: number;
    restored: number;
    dismissed: number;
  };
}

export interface RestoreQuarantineEntryResponse {
  queue_id: string;
  session_id: string;
  restored_artifacts: QuarantinedArtifactItem[];
  restored_count: number;
  status: "restored";
}

export interface DismissQuarantineEntryResponse {
  queue_id: string;
  session_id: string;
  status: "dismissed";
  artifact_count: number;
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

export interface ProviderRuntimeControls {
  cli_command?: string;
  timeout_seconds?: number;
  permission_mode?: string;
  sandbox?: string;
  model?: string;
}

export interface ProviderRunSummary {
  total_runs: number;
  active_runs: number;
  completed_runs: number;
  failed_runs: number;
  timed_out_runs: number;
  cancelled_runs: number;
  last_run_at?: string | null;
}

export interface ProviderRunItem {
  session_id: string;
  task_id?: string | null;
  task_title?: string | null;
  agent_id?: string | null;
  agent_name?: string | null;
  status: string;
  progress_pct?: number | null;
  status_message?: string | null;
  started_at: string;
  ended_at?: string | null;
}

export interface ProviderStatusItem {
  id: string;
  name: string;
  kind: string;
  status: string;
  execution_mode: string;
  configured_execution_mode: string;
  effective_execution_mode?: string | null;
  supports_worker_execution: boolean;
  supports_live_api: boolean;
  default_artifact_type: string;
  lifecycle_version: string;
  lifecycle_phases: string[];
  available_execution_modes?: string[];
  runtime_controls?: ProviderRuntimeControls;
  config_warnings?: string[];
  is_runnable?: boolean;
  run_summary?: ProviderRunSummary;
  recent_runs?: ProviderRunItem[];
  notes: string;
}

export interface ProvidersResponse {
  providers: ProviderStatusItem[];
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
