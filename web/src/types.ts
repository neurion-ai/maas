export type BoardColumnKey =
  | "planned"
  | "ready"
  | "assigned"
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

export interface SchedulerFactor {
  key: string;
  label: string;
  value: number;
}

export interface BoardGoal {
  id: string;
  title: string;
}

export interface BoardTask {
  task_id: string;
  issue_key?: string | null;
  project_id?: string | null;
  project_name?: string | null;
  title: string;
  description?: string;
  status: BoardColumnKey | "assigned";
  priority: number;
  progress_pct?: number | null;
  retry_count?: number;
  auto_retry_limit?: number | null;
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
  scheduler_status?: string | null;
  scheduler_summary?: string | null;
  scheduler_score?: number | null;
  scheduler_rank?: number | null;
  scheduler_agent?: BoardAgent | null;
  scheduler_factors?: SchedulerFactor[];
  replan_strategy?: string | null;
  replan_summary?: string | null;
  scoped_paths?: string[];
  validation_commands?: string[];
  has_verification_recipe?: boolean;
  latest_verification_status?: string | null;
  latest_verification_at?: string | null;
  latest_verification_command?: string | null;
  git_workspace_supported?: boolean;
  git_workspace_prepared?: boolean;
  git_workspace_branch?: string | null;
  git_workspace_dirty_files?: number;
  git_workspace_change_summary?: string | null;
  git_workspace_last_diff_at?: string | null;
  git_workspace_diff_artifact_id?: string | null;
  operator_bucket?: "review" | "blocked_failures" | "blocked_dependencies" | null;
  batch_review_eligible?: boolean;
  batch_review_reason?: string | null;
}

export interface BoardColumn {
  key: BoardColumnKey;
  title: string;
  tasks: BoardTask[];
}

export interface BoardSummary {
  total_tasks: number;
  active_agents: number;
  assigned_tasks?: number;
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

export interface ProjectSummary {
  project_id: string;
  name: string;
  description: string;
  project_type: string;
  created_at: string;
  updated_at?: string;
  state: "active" | "archived";
  archived_at?: string | null;
  source_root?: string;
  onboarding_mode?: string;
  task_count: number;
  agent_count: number;
  open_alert_count: number;
}

export interface ProjectsResponse {
  projects: ProjectSummary[];
}

export interface PortfolioProject {
  project_id: string;
  name: string;
  description: string;
  project_type: string;
  created_at: string;
  updated_at?: string;
  state: "active" | "archived";
  archived_at?: string | null;
  source_root?: string;
  onboarding_mode?: string;
  task_count: number;
  agent_count: number;
  open_alert_count: number;
  blocked_tasks: number;
  in_progress_tasks: number;
  open_alerts: number;
  critical_alerts: number;
  active_sessions: number;
  running_agents: number;
  open_quarantine_entries: number;
  dead_letter_entries: number;
  review_queue_count: number;
  blocked_failure_count: number;
  suspect_run_count: number;
  stale_agent_count: number;
  repeated_failure_tasks: number;
  health: "healthy" | "warn" | "critical" | "archived";
  provider_readiness: {
    total: number;
    ready: number;
    issues: number;
    unknown: number;
  };
  scheduler_policy: {
    fair_share_weight: number;
    max_active_sessions: number;
  };
  provider_capacity: {
    queue_mode: "running" | "draining" | "paused";
    max_running_jobs: number;
    preferred_provider_id?: string | null;
    queued_jobs: number;
    running_jobs: number;
    at_capacity: boolean;
    can_start_jobs: boolean;
    can_launch_jobs?: boolean;
  };
  review_policy: {
    auto_approve_low_risk: boolean;
    max_priority_for_auto_approve: number;
    require_verification_pass: boolean;
  };
  risk_policy: {
    priority_threshold: number;
    sensitive_path_prefixes: string[];
  };
  runtime_quotas: {
    daily_run_limit: number;
    daily_live_run_limit: number;
    daily_runtime_seconds_limit: number;
    max_task_session_attempts: number;
    runs_today: number;
    live_runs_today: number;
    runtime_seconds_today: number;
  };
  notification_policy?: {
    webhook_urls?: string[];
    minimum_severity?: string;
    enabled_events?: string[];
  };
  at_scheduler_capacity: boolean;
}

export interface PortfolioResponse {
  summary: {
    active_projects: number;
    archived_projects: number;
    open_alerts: number;
    blocked_tasks: number;
    active_sessions: number;
    recovery_pressure: number;
    projects_with_issues: number;
    open_escalations: number;
    queued_provider_jobs: number;
    queued_notifications: number;
    failed_notifications: number;
    review_queue: number;
    blocked_failures: number;
    suspect_runs: number;
    stale_agents: number;
  };
  projects: PortfolioProject[];
  command_center: {
    open_escalations: EscalationItem[];
    urgent_alerts: AlertItem[];
    open_dead_letter_entries: DeadLetterQueueItem[];
    queued_provider_jobs: ProviderJobItem[];
    review_queue: Array<{
      project_id: string;
      project_name: string;
      task_id: string;
      title: string;
      priority: number;
      review_state?: string | null;
      goal_title?: string | null;
      agent_name?: string | null;
      updated_at?: string | null;
    }>;
    blocked_failures: Array<{
      project_id: string;
      project_name: string;
      task_id: string;
      title: string;
      priority: number;
      review_state?: string | null;
      goal_title?: string | null;
      agent_name?: string | null;
      failure_count?: number;
      latest_failure_at?: string | null;
    }>;
    suspect_runs: Array<{
      project_id: string;
      project_name: string;
      session_id: string;
      task_id?: string | null;
      task_title?: string | null;
      agent_id?: string | null;
      agent_name?: string | null;
      status: string;
      provider_type: string;
      status_message?: string | null;
      started_at?: string | null;
      last_heartbeat_at?: string | null;
    }>;
    notification_deliveries: NotificationItem[];
  };
}

export interface ProjectCreateRequest {
  actor_id: string;
  name: string;
  description: string;
  project_type: string;
  mode: "auto" | "greenfield" | "brownfield";
  source_root?: string;
  create_source_root?: boolean;
  template_id?: string;
}

export interface ProjectCreateResponse {
  project: ProjectSummary;
  mode: string;
  metadata: {
    understanding_path: string;
    discovery_path?: string | null;
    source_root: string;
    generated_source_root?: boolean;
    cloned_from_project_id?: string;
    template_id?: string | null;
  };
}

export interface ProjectTemplate {
  id: string;
  name: string;
  description: string;
  mode: "auto" | "greenfield" | "brownfield";
  project_type: string;
  create_source_root: boolean;
}

export interface ProjectTemplatesResponse {
  templates: ProjectTemplate[];
}

export interface AutopilotStatusResponse {
  project_id: string;
  policy: {
    enabled: boolean;
    interval_seconds: number;
    allocate_limit: number;
    provider_job_limit: number;
    auto_launch_assigned_work: boolean;
    process_notifications: boolean;
    notification_batch_limit: number;
  };
  runtime: {
    project_id: string;
    enabled: boolean;
    running: boolean;
    policy: AutopilotStatusResponse["policy"];
    last_heartbeat_at?: string | null;
    last_summary?: {
      assigned_count: number;
      provider_jobs_queued: number;
      provider_jobs_processed: number;
      provider_jobs_dispatched: number;
      notifications_processed: number;
      why_idle?: string | null;
    } | null;
    last_error?: string | null;
    loop_count: number;
  };
  why_idle: string;
}

export interface ProjectActionResponse {
  project_id: string;
  state: "active" | "archived" | "deleted";
}

export interface DirectoryPickerResponse {
  cancelled: boolean;
  path: string | null;
}

export interface RepoTreeEntry {
  name: string;
  path: string;
  kind: "directory" | "file";
  size?: number | null;
  extension?: string | null;
  previewable: boolean;
}

export interface RepoTreeResponse {
  path: string;
  parent_path?: string | null;
  source_root: string;
  entries: RepoTreeEntry[];
}

export interface RepoFileResponse {
  path: string;
  name: string;
  parent_path?: string | null;
  size: number;
  extension?: string | null;
  previewable: boolean;
  content_kind: "text" | "json" | "binary";
  content?: string | null;
  truncated: boolean;
}

export interface OverviewOnboarding {
  mode: string;
  review_status: string;
  review_required: boolean;
  review_overrides?: {
    ignored_paths: string[];
    accepted_workflow_labels: string[];
    accepted_runbook_labels: string[];
  };
  discovery_summary: {
    primary_language?: string;
    total_files?: number;
    package_managers?: string[];
    workflow_labels?: string[];
    workflow_details?: Array<{
      label: string;
      path?: string;
      detail?: string;
    }>;
    runbook_commands?: Array<{
      label: string;
      kind: string;
      name?: string;
      path?: string;
      command?: string | null;
      detail?: string;
      review_note?: string;
    }>;
    repo_areas?: string[];
    codebase_map?: Array<{
      name: string;
      path?: string;
      kind: string;
      primary_language: string;
      file_count: number;
      summary?: string;
      sample_files?: string[];
    }>;
  };
  repo_plan_preview?: {
    generated_task_count: number;
    verification_task_count: number;
    repo_area_task_count: number;
    sample_paths: string[];
    items: Array<{
      synthesis_key: string;
      task_kind: string;
      title: string;
      source_label: string;
      paths: string[];
      command?: string | null;
    }>;
  } | null;
  repo_plan_state?: {
    generated_task_count: number;
    verification_task_count: number;
    repo_area_task_count: number;
    sample_paths: string[];
    items: Array<{
      synthesis_key: string;
      task_kind: string;
      title: string;
      source_label: string;
      paths: string[];
      command?: string | null;
    }>;
    active_task_count: number;
    created_count: number;
    updated_count: number;
    cancelled_count: number;
    stale: boolean;
    last_refreshed_at?: string | null;
    last_refreshed_by?: string | null;
  } | null;
  review_task_id?: string | null;
  review_task_status?: string | null;
  review_task_review_state?: string | null;
  pending_gated_tasks: number;
  last_scanned_at?: string | null;
  last_scanned_by?: string | null;
  drift_summary?: {
    detected?: boolean;
    scanned_at?: string;
    summary?: string;
    changes?: string[];
    file_count_delta?: number;
    primary_language_before?: string | null;
    primary_language_after?: string | null;
    workflow_labels_added?: string[];
    workflow_labels_removed?: string[];
    repo_areas_added?: string[];
    repo_areas_removed?: string[];
    package_managers_added?: string[];
    package_managers_removed?: string[];
    codebase_map_added?: string[];
    codebase_map_removed?: string[];
  } | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
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

export interface TimelineEvent {
  event_id: string;
  source: string;
  event_type: string;
  title: string;
  description: string;
  severity: string;
  created_at: string;
  task_id?: string | null;
  session_id?: string | null;
  agent_id?: string | null;
  resource_type?: string | null;
  resource_id?: string | null;
  details?: Record<string, unknown>;
}

export interface TimelineResponse {
  filters: {
    task_id?: string | null;
    session_id?: string | null;
    agent_id?: string | null;
    resource_type?: string | null;
    resource_id?: string | null;
    limit: number;
    order: "asc" | "desc";
  };
  summary: {
    total_events: number;
    sources: Record<string, number>;
  };
  events: TimelineEvent[];
}

export interface ArtifactFacetCount {
  artifact_type?: string;
  provider_type?: string;
  count: number;
}

export interface ArtifactItem {
  artifact_id: string;
  project_id: string;
  task_id?: string | null;
  task_title?: string | null;
  task_status?: string | null;
  task_review_state?: string | null;
  session_id?: string | null;
  session_status?: string | null;
  provider_type?: string | null;
  agent_id?: string | null;
  agent_name?: string | null;
  artifact_type: string;
  path: string;
  display_path: string;
  file_name: string;
  artifact_state: "active" | "quarantined" | "restored" | "external";
  exists: boolean;
  size_bytes?: number | null;
  quarantine_reason?: string | null;
  quarantined_from_path?: string | null;
  restored_from_quarantine?: boolean;
  quarantine_queue_id?: string | null;
  quarantine_queue_status?: "open" | "restored" | "dismissed" | null;
  operator_action?: FailureOperatorAction;
  secondary_operator_action?: FailureOperatorAction;
  created_at: string;
}

export interface ArtifactsResponse {
  summary: {
    total_artifacts: number;
    active_artifacts: number;
    quarantined_artifacts: number;
    restored_artifacts: number;
    external_artifacts: number;
    missing_files: number;
  };
  artifact_types: ArtifactFacetCount[];
  provider_types: ArtifactFacetCount[];
  filtered_count: number;
  offset: number;
  limit: number;
  selected_filters: {
    search: string;
    state: string;
    provider_type: string;
    artifact_type: string;
    task_id: string;
    session_id: string;
    missing_only: boolean;
  };
  items: ArtifactItem[];
}

export interface ArtifactPreview {
  kind: "text" | "json" | "unavailable";
  reason?: string | null;
  encoding?: string | null;
  truncated?: boolean;
  content?: string | null;
}

export interface ArtifactRelatedItem {
  artifact_id: string;
  artifact_type: string;
  file_name: string;
  display_path: string;
  artifact_state: "active" | "quarantined" | "restored" | "external";
  provider_type?: string | null;
  session_id?: string | null;
  created_at: string;
}

export interface ArtifactTaskLink {
  task_id: string;
  task_title?: string | null;
  dependency_type: "blocks" | "informs" | "conflicts";
  artifact_count: number;
  recent_artifacts: ArtifactRelatedItem[];
}

export interface ArtifactDetail extends ArtifactItem {
  absolute_path?: string | null;
  metadata: Record<string, unknown>;
  download_url?: string | null;
  task_export_url?: string | null;
  session_export_url?: string | null;
  download_content_type?: string | null;
  preview: ArtifactPreview;
  lineage_summary?: {
    task_artifact_count: number;
    session_artifact_count: number;
  };
  quarantine_entry?: {
    queue_id: string;
    status: "open" | "restored" | "dismissed";
    reason?: string | null;
    resolution_note?: string | null;
    created_at?: string | null;
    updated_at?: string | null;
    resolved_at?: string | null;
  } | null;
  session_artifacts?: ArtifactRelatedItem[];
  upstream_task_artifacts?: ArtifactTaskLink[];
  downstream_task_artifacts?: ArtifactTaskLink[];
  related_artifacts?: ArtifactRelatedItem[];
}

export interface ArtifactComparisonResponse {
  left: ArtifactDetail;
  right: ArtifactDetail;
  comparable: boolean;
  reason?: string | null;
  unified_diff?: string | null;
  truncated?: boolean;
}

export interface ArtifactPurgeResponse {
  scope_type: "task" | "session";
  scope_id: string;
  deleted_artifact_count: number;
  deleted_file_count: number;
  missing_file_count: number;
  preserved_path_count: number;
}

export interface OverviewResponse {
  project: OverviewProject | null;
  onboarding?: OverviewOnboarding | null;
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
  auto_retry_limit?: number | null;
  last_retry_at?: string | null;
  last_retry_reason?: string | null;
  next_retry_at?: string | null;
  next_retry_reason?: string | null;
  failure_type: string;
  summary: string;
  detail_json?: string;
  quarantined_artifact_count?: number;
  quarantined_artifacts?: QuarantinedArtifactItem[];
  operator_action?: FailureOperatorAction;
  secondary_operator_action?: FailureOperatorAction;
  created_at: string;
}

export interface FailureOperatorAction {
  action:
    | "recover_and_requeue_task"
    | "restore_quarantine_entry"
    | "restore_failure_artifacts"
    | "restore_and_requeue_quarantine_entry"
    | "dismiss_quarantine_entry"
    | "reopen_quarantine_entry";
  label: string;
  resource_type: "task" | "failure" | "quarantine";
  resource_id: string;
  related_task_id?: string | null;
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
  task_status?: string | null;
  task_review_state?: string | null;
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
  operator_action?: AlertOperatorAction;
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

export interface RestoreAndRequeueQuarantineEntryResponse {
  queue_id: string;
  task_id: string;
  session_id: string;
  restored_artifacts: QuarantinedArtifactItem[];
  restored_count: number;
  status: "restored";
  task_status: string;
  task_review_state?: string | null;
  next_retry_at?: string | null;
  next_retry_reason?: string | null;
}

export interface DismissQuarantineEntryResponse {
  queue_id: string;
  session_id: string;
  status: "dismissed";
  artifact_count: number;
}

export interface ReopenQuarantineEntryResponse {
  queue_id: string;
  session_id: string;
  status: "open";
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
  project_name?: string;
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
  project_name?: string;
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

export interface NotificationItem {
  notification_id: string;
  project_id: string;
  project_name?: string | null;
  target_url: string;
  event_type: string;
  severity: string;
  title: string;
  body: string;
  payload: Record<string, unknown>;
  resource_type?: string | null;
  resource_id?: string | null;
  status: string;
  attempts: number;
  last_error?: string | null;
  last_response_code?: number | null;
  created_at: string;
  updated_at?: string | null;
  sent_at?: string | null;
}

export interface ProviderRuntimeControls {
  cli_command?: string;
  timeout_seconds?: number;
  permission_mode?: string;
  sandbox?: string;
  model?: string;
  job_limit_per_pass?: number;
  queue_paused?: boolean;
}

export interface ProviderEditableRuntimeControls {
  cli_command?: string;
  timeout_seconds?: number | string;
  permission_mode?: string;
  sandbox?: string;
  model?: string;
  job_limit_per_pass?: number | string;
  queue_paused?: boolean | string;
}

export interface ProviderRunSummary {
  total_runs: number;
  active_runs: number;
  completed_runs: number;
  failed_runs: number;
  timed_out_runs: number;
  cancelled_runs: number;
  last_run_at?: string | null;
  timeout_failures: number;
  nonzero_exit_failures: number;
  runtime_failures: number;
  latest_failure_kind?: string | null;
  latest_failure_at?: string | null;
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
  execution_mode?: string | null;
  external_runtime?: string | null;
  failure_kind?: string | null;
  failure_detail?: string | null;
}

export interface ProviderPreflightItem {
  checked_at: string;
  status: string;
  summary: string;
  issues?: string[];
  execution_mode?: string | null;
  external_runtime?: string | null;
}

export interface ProviderJobSummary {
  queued_jobs: number;
  running_jobs: number;
  completed_jobs: number;
  failed_jobs: number;
  cancelled_jobs: number;
  last_job_at?: string | null;
}

export interface ProviderJobItem {
  job_id: string;
  project_id: string;
  project_name?: string | null;
  provider_id: string;
  task_id: string;
  title?: string | null;
  goal_title?: string | null;
  agent_id: string;
  agent_name?: string | null;
  status: string;
  queued_by: string;
  worker_id?: string | null;
  artifact_path?: string | null;
  session_id?: string | null;
  artifact_id?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  updated_at?: string | null;
  execution_mode?: string | null;
  failure_kind?: string | null;
  failure_detail?: string | null;
}

export interface ProviderWorkerSummary {
  total_workers: number;
  idle_workers: number;
  busy_workers: number;
  offline_workers: number;
}

export interface ProviderWorkerItem {
  worker_id: string;
  project_id?: string | null;
  project_name?: string | null;
  provider_id?: string | null;
  status: "idle" | "busy" | "offline";
  current_job_id?: string | null;
  current_job_title?: string | null;
  last_job_id?: string | null;
  last_job_status?: string | null;
  heartbeat_at?: string | null;
  heartbeat_age_seconds?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface ProviderRunTarget {
  project_id: string;
  task_id: string;
  title: string;
  status: "planned" | "ready" | "assigned";
  priority: number;
  review_state?: string | null;
  agent_id: string;
  agent_name?: string | null;
  goal_title?: string | null;
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
  configurable_runtime_controls?: ProviderEditableRuntimeControls;
  config_warnings?: string[];
  guardrails?: string[];
  is_runnable?: boolean;
  run_summary?: ProviderRunSummary;
  job_summary?: ProviderJobSummary;
  recent_runs?: ProviderRunItem[];
  latest_preflight?: ProviderPreflightItem | null;
  notes: string;
}

export interface ProvidersResponse {
  providers: ProviderStatusItem[];
  run_targets: ProviderRunTarget[];
  job_queue: ProviderJobItem[];
  worker_summary?: ProviderWorkerSummary;
  worker_pool?: ProviderWorkerItem[];
}

export interface RecoveryDelayPreviewItem {
  attempt: number;
  delay_seconds: number;
}

export interface RecoveryPolicySettings {
  auto_retry_timeout_sessions: boolean;
  auto_retry_failed_sessions: boolean;
  auto_recover_blocked_tasks: boolean;
  auto_dlq_retry_exhausted_tasks: boolean;
  auto_open_task_circuit_breakers: boolean;
  auto_route_circuit_breakers_to_replan: boolean;
  circuit_breaker_failure_threshold: number;
  circuit_breaker_replan_after_seconds: number;
  max_timed_out_retries: number;
  max_failed_session_retries: number;
  timed_out_retry_cooldown_seconds: number;
  failed_session_retry_cooldown_seconds: number;
  recover_and_requeue_cooldown_seconds: number;
  retry_backoff_multiplier: number;
  retry_backoff_max_seconds: number;
}

export interface RecoveryTaskItem {
  task_id: string;
  title: string;
  status: string;
  review_state?: string | null;
  replan_reason?: string | null;
  priority: number;
  retry_count?: number | null;
  auto_retry_limit?: number | null;
  last_retry_at?: string | null;
  last_retry_reason?: string | null;
  next_retry_at?: string | null;
  next_retry_reason?: string | null;
  updated_at?: string | null;
  goal_title?: string | null;
  agent_name?: string | null;
  failure_count?: number | null;
  latest_failure_at?: string | null;
  replan_strategy?: string | null;
  replan_summary?: string | null;
  circuit_breaker_detail?: {
    trigger?: string;
    failure_count?: number;
    threshold?: number;
    retry_limit?: number;
    retry_count?: number;
  };
  circuit_breaker_opened_at?: string | null;
  auto_replan_reason?: string | null;
}

export interface DeadLetterQueueItem {
  dlq_id: string;
  project_id: string;
  project_name?: string | null;
  task_id: string;
  failure_id?: string | null;
  reason: string;
  status: string;
  resolution_note?: string | null;
  created_at: string;
  updated_at?: string | null;
  resolved_at?: string | null;
  title: string;
  task_status: string;
  review_state?: string | null;
  priority: number;
  retry_count?: number | null;
  auto_retry_limit?: number | null;
  last_retry_reason?: string | null;
  next_retry_at?: string | null;
  next_retry_reason?: string | null;
  goal_title?: string | null;
  agent_name?: string | null;
  detail?: {
    failure_type?: string;
    retry_count?: number;
    retry_limit?: number;
    source?: string;
  };
}

export interface RecoveryPolicyResponse {
  project_id: string;
  policy: RecoveryPolicySettings;
  defaults: RecoveryPolicySettings;
  summary: {
    retry_backoff_tasks: number;
    needs_replan_tasks: number;
    circuit_breaker_tasks: number;
    replanning_candidates: number;
    tasks_with_retry_history: number;
    recoverable_blocked_tasks: number;
    auto_recovery_candidates: number;
    auto_replan_candidates: number;
    open_dead_letter_entries: number;
    open_circuit_breakers: number;
    tasks_with_retry_overrides: number;
    open_quarantine_entries: number;
    open_failure_alerts: number;
    open_repeated_failure_alerts: number;
    open_stale_agent_alerts: number;
  };
  backoff_preview: {
    timed_out_retry_delays: RecoveryDelayPreviewItem[];
    failed_session_retry_delays: RecoveryDelayPreviewItem[];
    recover_and_requeue_delays: RecoveryDelayPreviewItem[];
  };
  task_retry_overrides: RecoveryTaskItem[];
  auto_recovery_candidates: RecoveryTaskItem[];
  auto_replan_candidates: RecoveryTaskItem[];
  recoverable_blocked_tasks: RecoveryTaskItem[];
  task_retry_history: RecoveryTaskItem[];
  replanning_candidates: RecoveryTaskItem[];
  needs_replan_tasks: RecoveryTaskItem[];
  circuit_breaker_tasks: RecoveryTaskItem[];
  active_retry_backoff: RecoveryTaskItem[];
  dead_letter_entries: DeadLetterQueueItem[];
  open_quarantine_entries: QuarantineQueueItem[];
  open_failure_alerts: AlertItem[];
  open_stale_agent_alerts: AlertItem[];
  repeated_failure_incidents: RepeatedFailureItem[];
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

export interface SupervisorProjectRun {
  project_id: string;
  ready_changes: SupervisorReadyChange[];
  allocations: SupervisorAllocation[];
  assigned_count: number;
  auto_recovered_tasks: Array<{
    task_id: string;
    status: string;
    review_state?: string | null;
    next_retry_at?: string | null;
    next_retry_reason?: string | null;
  }>;
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

export interface SupervisorRunResponse {
  ready_changes: SupervisorReadyChange[];
  allocations: SupervisorAllocation[];
  assigned_count: number;
  auto_recovered_tasks: Array<{
    task_id: string;
    status: string;
    review_state?: string | null;
    next_retry_at?: string | null;
    next_retry_reason?: string | null;
  }>;
  stale_sessions: Array<{
    session_id: string;
    task_id: string;
    repeated_failure_alert?: {
      alert_id: string;
      task_id: string;
      failure_count: number;
    } | null;
  }>;
  project_runs: SupervisorProjectRun[];
}

export interface OrchestratorProjectRun extends SupervisorProjectRun {
  provider_jobs_queued: number;
  launch_provider_id?: string | null;
  queued_jobs: Array<{
    job_id: string;
    provider_id: string;
    status: string;
    task_id: string;
    project_id: string;
  }>;
  provider_jobs_processed: number;
  provider_jobs_dispatched?: number;
  dispatched_worker_ids?: string[];
  processed_jobs: Array<{
    job_id: string;
    provider_id: string;
    status: string;
    task_id: string;
    project_id: string;
  }>;
}

export interface OrchestratorRunResponse extends SupervisorRunResponse {
  provider_jobs_queued: number;
  provider_jobs_processed: number;
  provider_jobs_dispatched?: number;
  project_runs: OrchestratorProjectRun[];
}

export interface CodexIssueRelationshipItem {
  task_id: string;
  issue_key?: string | null;
  title: string;
  status: string;
  priority: number;
  review_state?: string | null;
  goal_id?: string | null;
  goal_title?: string | null;
  agent_id?: string | null;
  agent_name?: string | null;
  dependency_type?: "blocks" | "informs" | "conflicts" | null;
}

export interface CodexIssueRunItem {
  session_id: string;
  agent_id?: string | null;
  agent_name?: string | null;
  provider_type: string;
  execution_mode?: string | null;
  external_runtime?: string | null;
  status: string;
  progress_pct?: number | null;
  status_message?: string | null;
  last_heartbeat_at?: string | null;
  started_at: string;
  ended_at?: string | null;
}

export interface CodexRunConsolePreview {
  path: string;
  content: string;
  truncated: boolean;
}

export interface CodexRunDetailResponse {
  session_id: string;
  task_id?: string | null;
  task_title?: string | null;
  task_status?: string | null;
  task_review_state?: string | null;
  issue_key?: string | null;
  agent_id?: string | null;
  agent_name?: string | null;
  provider_type: string;
  execution_mode?: string | null;
  external_runtime?: string | null;
  status: string;
  progress_pct?: number | null;
  status_message?: string | null;
  last_heartbeat_at?: string | null;
  heartbeat_age_seconds?: number | null;
  started_at: string;
  ended_at?: string | null;
  run_age_seconds?: number | null;
  is_live: boolean;
  is_stale?: boolean;
  diagnostic_summary?: string | null;
  recommended_action?: string | null;
  current_step?: string | null;
  timeout_seconds?: number | null;
  command?: string[] | null;
  runtime_root?: string | null;
  phases?: Array<{
    key: string;
    label: string;
    timestamp?: string | null;
    description?: string | null;
    status: string;
  }>;
  memory_context?: Array<{
    artifact_id: string;
    task_id?: string | null;
    title?: string | null;
    summary?: string | null;
    tags?: string[];
    score?: number;
  }>;
  output_preview?: CodexRunConsolePreview | null;
  stdout_preview?: CodexRunConsolePreview | null;
  stderr_preview?: CodexRunConsolePreview | null;
  activity: CodexRunConsoleActivityItem[];
  artifacts: ArtifactItem[];
  artifact_summary?: {
    total_artifacts: number;
    active_artifacts: number;
    quarantined_artifacts: number;
    restored_artifacts: number;
    external_artifacts: number;
    missing_files: number;
  };
}

export interface CodexRunListItem {
  session_id: string;
  project_id?: string | null;
  project_name?: string | null;
  task_id?: string | null;
  task_title?: string | null;
  task_status?: string | null;
  task_review_state?: string | null;
  issue_key?: string | null;
  goal_id?: string | null;
  goal_title?: string | null;
  agent_id?: string | null;
  agent_name?: string | null;
  provider_type: string;
  execution_mode?: string | null;
  external_runtime?: string | null;
  status: string;
  progress_pct?: number | null;
  status_message?: string | null;
  last_heartbeat_at?: string | null;
  heartbeat_age_seconds?: number | null;
  started_at: string;
  ended_at?: string | null;
  run_age_seconds?: number | null;
  is_live: boolean;
  is_stale: boolean;
  diagnostic_summary?: string | null;
  recommended_action?: string | null;
  artifact_count: number;
  failure_count: number;
}

export interface CodexRunIndexResponse {
  summary: {
    total_runs: number;
    active_runs: number;
    failed_runs: number;
    timed_out_runs: number;
    cancelled_runs: number;
    completed_runs: number;
    stale_runs: number;
  };
  items: CodexRunListItem[];
}

export interface CodexSystemDiagnosticsResponse {
  summary: {
    suspect_runs: number;
    stale_agents: number;
    queued_jobs: number;
    running_jobs: number;
    oldest_queued_at?: string | null;
    oldest_running_at?: string | null;
  };
  execution_state?: {
    state: string;
    summary: string;
    detail: string;
  };
  suspect_runs: CodexRunListItem[];
  stale_agents: Array<{
    agent_id: string;
    display_name: string;
    status: string;
    heartbeat_age_seconds?: number | null;
    current_task_id?: string | null;
    current_issue_key?: string | null;
    current_task_title?: string | null;
    focus_run_session_id?: string | null;
    diagnostic_summary?: string | null;
    recommended_action?: string | null;
  }>;
  queue_pressure: {
    queued_jobs: number;
    running_jobs: number;
    oldest_queued_at?: string | null;
    oldest_running_at?: string | null;
  };
}

export interface CodexRunConsoleActivityItem {
  activity_id?: string | null;
  action: string;
  description: string;
  severity: string;
  created_at: string;
  details?: Record<string, unknown>;
}

export interface CodexRunConsole {
  session_id: string;
  agent_id?: string | null;
  agent_name?: string | null;
  provider_type: string;
  execution_mode?: string | null;
  external_runtime?: string | null;
  status: string;
  progress_pct?: number | null;
  status_message?: string | null;
  last_heartbeat_at?: string | null;
  started_at: string;
  ended_at?: string | null;
  is_live: boolean;
  timeout_seconds?: number | null;
  command?: string[] | null;
  runtime_root?: string | null;
  output_preview?: CodexRunConsolePreview | null;
  stdout_preview?: CodexRunConsolePreview | null;
  stderr_preview?: CodexRunConsolePreview | null;
  activity: CodexRunConsoleActivityItem[];
}

export interface VerificationRun {
  verification_run_id: string;
  task_id: string;
  command: string;
  status: string;
  started_at: string;
  finished_at?: string | null;
  exit_code?: number | null;
  output_excerpt?: string | null;
  artifact_id?: string | null;
}

export interface CodexAgentOwnedIssueItem {
  task_id: string;
  issue_key?: string | null;
  title: string;
  status: string;
  priority: number;
  review_state?: string | null;
  progress_pct?: number | null;
  created_at: string;
  goal_id?: string | null;
  goal_title?: string | null;
}

export interface CodexAgentRunItem {
  session_id: string;
  task_id?: string | null;
  task_title?: string | null;
  provider_type: string;
  execution_mode?: string | null;
  external_runtime?: string | null;
  status: string;
  progress_pct?: number | null;
  status_message?: string | null;
  last_heartbeat_at?: string | null;
  heartbeat_age_seconds?: number | null;
  started_at: string;
  ended_at?: string | null;
  run_age_seconds?: number | null;
  is_live?: boolean;
  is_stale?: boolean;
  diagnostic_summary?: string | null;
  recommended_action?: string | null;
}

export interface CodexAgentDetailResponse {
  agent: {
    agent_id: string;
    role: string;
    display_name: string;
    status: string;
    current_task_id?: string | null;
    current_task_title?: string | null;
    current_issue_key?: string | null;
    last_heartbeat_at?: string | null;
  };
  owned_issues: CodexAgentOwnedIssueItem[];
  runs: CodexAgentRunItem[];
  history: TimelineEvent[];
}

export interface CodexIssueDetailResponse {
  task: {
    task_id: string;
    issue_key?: string | null;
    title: string;
    description?: string | null;
    status: string;
    priority: number;
    review_state?: string | null;
    progress_pct?: number | null;
    retry_count?: number | null;
    auto_retry_limit?: number | null;
    last_retry_at?: string | null;
    last_retry_reason?: string | null;
    next_retry_at?: string | null;
    next_retry_reason?: string | null;
    last_heartbeat_at?: string | null;
    created_at: string;
    updated_at: string;
    goal_id?: string | null;
    goal_title?: string | null;
    agent_id?: string | null;
    agent_name?: string | null;
    agent_status?: string | null;
  };
  relationships: {
    depends_on: CodexIssueRelationshipItem[];
    unlocks: CodexIssueRelationshipItem[];
    related: CodexIssueRelationshipItem[];
  };
  runs: CodexIssueRunItem[];
  run_console?: CodexRunConsole | null;
  history: TimelineEvent[];
  artifacts: ArtifactItem[];
  artifact_summary: ArtifactsResponse["summary"];
  verification_runs: VerificationRun[];
  review_decision?: {
    status: string;
    batch_review_eligible: boolean;
    auto_approve_eligible: boolean;
    summary: string;
    detail: string;
  };
  recovery_playbook?: {
    kind: string;
    title: string;
    summary: string;
    detail: string;
    recommended_action: string;
    actions: string[];
    confidence: string;
  };
  memory_context?: Array<{
    artifact_id: string;
    task_id?: string | null;
    session_id?: string | null;
    artifact_type?: string | null;
    path?: string | null;
    created_at?: string | null;
    title?: string | null;
    summary?: string | null;
    tags?: string[];
    promoted_at?: string | null;
    promoted_by?: string | null;
    preview?: {
      content?: string;
      truncated?: boolean;
    } | null;
    score?: number;
  }>;
  git_workspace?: {
    workspace_id: string;
    task_id: string;
    branch_name: string;
    worktree_path: string;
    repo_root: string;
    base_ref?: string | null;
    head_commit?: string | null;
    dirty_file_count?: number | null;
    change_summary?: string | null;
    last_diff_artifact_id?: string | null;
    updated_at?: string | null;
  } | null;
}

export interface CodexIssueQueueBucket {
  title: string;
  description: string;
  items: BoardTask[];
  batch_review?: {
    eligible_count: number;
    eligible_task_ids: string[];
    summary: string;
  };
}

export interface CodexIssueIndexResponse {
  generated_at: string;
  summary: {
    review: number;
    blocked_failures: number;
    blocked_dependencies: number;
    resolved: number;
    recent_failures: number;
    batch_review_eligible: number;
  };
  queue: {
    review: CodexIssueQueueBucket;
    blocked_failures: CodexIssueQueueBucket;
    blocked_dependencies: CodexIssueQueueBucket;
  };
  resolved: BoardTask[];
  board_summary: BoardSummary;
  filter_options?: BoardFilterOptions;
}

export interface CodexRetrievalIssueHit {
  task_id: string;
  issue_key?: string | null;
  project_id?: string | null;
  project_name?: string | null;
  title: string;
  status: string;
  priority: number;
  goal_id?: string | null;
  goal_title?: string | null;
  agent_id?: string | null;
  agent_name?: string | null;
  match_context: string;
  updated_at?: string | null;
}

export interface CodexRetrievalRunHit {
  session_id: string;
  task_id?: string | null;
  issue_key?: string | null;
  project_id?: string | null;
  project_name?: string | null;
  task_title?: string | null;
  status: string;
  provider_type: string;
  execution_mode?: string | null;
  external_runtime?: string | null;
  match_context: string;
  started_at: string;
}

export interface CodexRetrievalArtifactHit {
  artifact_id: string;
  task_id?: string | null;
  issue_key?: string | null;
  session_id?: string | null;
  project_id?: string | null;
  project_name?: string | null;
  artifact_path: string;
  artifact_type: string;
  artifact_state: string;
  title: string;
  created_at: string;
}

export interface CodexRetrievalEventHit {
  source: string;
  event_id: string;
  project_id?: string | null;
  project_name?: string | null;
  task_id?: string | null;
  issue_key?: string | null;
  session_id?: string | null;
  agent_id?: string | null;
  title: string;
  description: string;
  created_at: string;
}

export interface CodexRetrievalSearchResponse {
  query: {
    search: string;
    goal_id?: string | null;
    agent_id?: string | null;
    priority_min?: number | null;
  };
  summary: {
    total_hits: number;
    issue_hits: number;
    run_hits: number;
    artifact_hits: number;
    event_hits: number;
    memory_hits: number;
  };
  issues: CodexRetrievalIssueHit[];
  runs: CodexRetrievalRunHit[];
  artifacts: CodexRetrievalArtifactHit[];
  events: CodexRetrievalEventHit[];
  memory: Array<{
    artifact_id: string;
    task_id?: string | null;
    session_id?: string | null;
    artifact_type?: string | null;
    path?: string | null;
    created_at?: string | null;
    title?: string | null;
    summary?: string | null;
    tags?: string[];
    promoted_at?: string | null;
    promoted_by?: string | null;
    preview?: {
      content?: string;
      truncated?: boolean;
    } | null;
    score?: number;
  }>;
}
