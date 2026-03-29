import type {
  ActivityItem,
  AgentRosterResponse,
  AlertOperatorAction,
  AlertsResponse,
  ArtifactComparisonResponse,
  ArtifactDetail,
  ArtifactPurgeResponse,
  ArtifactsResponse,
  CodexAgentDetailResponse,
  CodexIssueIndexResponse,
  CodexRetrievalSearchResponse,
  CodexIssueDetailResponse,
  CodexRunIndexResponse,
  CodexSystemDiagnosticsResponse,
  CodexRunDetailResponse,
  ControlOperatorAction,
  DirectoryPickerResponse,
  DismissQuarantineEntryResponse,
  EscalationsResponse,
  FailureOperatorAction,
  FailuresResponse,
  GoalTreeResponse,
  GoalPlanningResponse,
  GoalCreateResponse,
  GoalSynthesisResponse,
  LiveSnapshot,
  NotificationItem,
  OverviewResponse,
  OperatorInboxResponse,
  OrchestratorRunResponse,
  PortfolioResponse,
  ProjectActionResponse,
  ProjectCreateRequest,
  ProjectCreateResponse,
  ProjectTemplatesResponse,
  AutopilotStatusResponse,
  ProjectsResponse,
  ProvidersResponse,
  RecoveryPolicyResponse,
  RepoFileResponse,
  RepoTreeResponse,
  QuarantineQueueResponse,
  ReopenQuarantineEntryResponse,
  RestoreAndRequeueQuarantineEntryResponse,
  RestoreFailureArtifactsResponse,
  RestoreQuarantineEntryResponse,
  DeliveryDraftResponse,
  DeliveryOverviewResponse,
  DeliverySyncResponse,
  EnvironmentDoctorResponse,
  SupervisorRunResponse,
  TaskDeliveryStatusResponse,
  TimelineResponse
} from "../types";
import { appendProjectScope, getSelectedProjectId } from "./projectScope";

const lastSuccessfulResponses = new Map<string, unknown>();
const DEFAULT_ACTOR_ID = "agent_allocator";

const OVERVIEW_FALLBACK: OverviewResponse = {
  project: {
    project_id: "proj_fallback",
    name: "MAAS Demo Workspace",
    description: "Fallback overview while the API is unavailable.",
    project_type: "custom"
  },
  onboarding: {
    mode: "greenfield",
    review_status: "not_applicable",
    review_required: false,
    review_overrides: {
      ignored_paths: [],
      accepted_workflow_labels: [],
      accepted_runbook_labels: []
    },
    discovery_summary: {
      workflow_labels: [],
      workflow_details: [],
      repo_areas: [],
      codebase_map: []
    },
    review_task_id: null,
    review_task_status: null,
    review_task_review_state: null,
    pending_gated_tasks: 0,
    last_scanned_at: null,
    last_scanned_by: null,
    drift_summary: null,
    reviewed_by: null,
    reviewed_at: null
  },
  summary: {
    tasks_total: 8,
    tasks_in_progress: 2,
    tasks_review: 1,
    tasks_blocked: 1,
    goals_total: 2,
    goals_active: 2,
    alerts_open: 1,
    alerts_critical: 0,
    escalations_open: 0,
    failures_total: 0,
    repeated_failure_tasks: 0,
    agents_running: 2
  },
  active_work: [
    {
      task_id: "task_live_board_api",
      title: "Expose a task-first Kanban payload",
      status: "in_progress",
      priority: 89,
      goal_title: "Operational board",
      agent_name: "API Steward"
    }
  ],
  recent_activity: [
    {
      action: "task_started",
      description: "Builder picked up board endpoint work.",
      severity: "info",
      created_at: new Date().toISOString()
    }
  ],
  recent_failures: [],
  repeated_failures: []
};

const GOAL_TREE_FALLBACK: GoalTreeResponse = {
  total_goals: 2,
  roots: [
    {
      goal_id: "goal_root",
      title: "Launch the first usable MAAS workspace",
      description: "Fallback goal tree data",
      status: "active",
      goal_type: "strategic",
      priority: 95,
      task_counts: { in_progress: 1, review: 1 },
      children: [
        {
          goal_id: "goal_child",
          parent_goal_id: "goal_root",
          title: "Stand up board-first orchestration services",
          description: "Fallback tactical goal",
          status: "active",
          goal_type: "tactical",
          priority: 90,
          task_counts: { planned: 1, blocked: 1, done: 1 },
          children: []
        }
      ]
    }
  ]
};

const REPO_TREE_FALLBACK: RepoTreeResponse = {
  path: "",
  parent_path: null,
  source_root: "",
  entries: []
};

const REPO_FILE_FALLBACK: RepoFileResponse = {
  path: "",
  name: "",
  parent_path: null,
  size: 0,
  extension: null,
  previewable: false,
  content_kind: "binary",
  content: null,
  truncated: false
};

const PORTFOLIO_FALLBACK: PortfolioResponse = {
  summary: {
    active_projects: 0,
    archived_projects: 0,
    open_alerts: 0,
    blocked_tasks: 0,
    active_sessions: 0,
    recovery_pressure: 0,
    projects_with_issues: 0,
    open_escalations: 0,
    queued_provider_jobs: 0,
    queued_notifications: 0,
    failed_notifications: 0,
    review_queue: 0,
    blocked_failures: 0,
    suspect_runs: 0,
    stale_agents: 0,
  },
  projects: [],
  command_center: {
    open_escalations: [],
    urgent_alerts: [],
    open_dead_letter_entries: [],
    queued_provider_jobs: [],
    review_queue: [],
    blocked_failures: [],
    suspect_runs: [],
    notification_deliveries: []
  }
};

const ROSTER_FALLBACK: AgentRosterResponse = {
  agents: [
    {
      agent_id: "agent_allocator",
      display_name: "Allocator",
      role: "allocator",
      status: "running",
      current_task_title: "Wire the scheduler and board read model",
      heartbeat_age_seconds: 12
    },
    {
      agent_id: "agent_reviewer",
      display_name: "Reviewer",
      role: "reviewer",
      status: "idle",
      current_task_title: null,
      heartbeat_age_seconds: null
    }
  ]
};

const ACTIVITY_FALLBACK: ActivityItem[] = [
  {
    action: "artifact_produced",
    description: "Runtime worker registered a board artifact.",
    severity: "info",
    created_at: new Date().toISOString()
  }
];

const TIMELINE_FALLBACK: TimelineResponse = {
  filters: {
    limit: 100,
    order: "desc"
  },
  summary: {
    total_events: 0,
    sources: {}
  },
  events: []
};

const ARTIFACTS_FALLBACK: ArtifactsResponse = {
  summary: {
    total_artifacts: 0,
    active_artifacts: 0,
    quarantined_artifacts: 0,
    restored_artifacts: 0,
    external_artifacts: 0,
    missing_files: 0
  },
  artifact_types: [],
  provider_types: [],
  filtered_count: 0,
  offset: 0,
  limit: 100,
  selected_filters: {
    search: "",
    state: "all",
    provider_type: "all",
    artifact_type: "all",
    task_id: "",
    session_id: "",
    missing_only: false
  },
  items: []
};

const ALERTS_FALLBACK: AlertsResponse = {
  alerts: [
    {
      alert_id: "alert_provider_pending",
      severity: "warning",
      title: "Broader provider integrations pending",
      description: "Simulated adapters and explicit local CLI modes are available, but broader provider coverage is still pending.",
      status: "open",
      created_at: new Date().toISOString()
    }
  ],
  grouped: { open: [], acknowledged: [], resolved: [] },
  summary: {
    open: 1,
    acknowledged: 0,
    resolved: 0,
    critical_open: 0,
    repeated_failure_open: 0
  }
};

const ESCALATIONS_FALLBACK: EscalationsResponse = {
  escalations: [],
  grouped: { open: [], approved: [], rejected: [] },
  summary: {
    open: 0,
    approved: 0,
    rejected: 0
  }
};

const FAILURES_FALLBACK: FailuresResponse = {
  recent: [],
  repeated_tasks: [],
  summary: {
    total_failures: 0,
    tasks_with_failures: 0,
    repeated_tasks: 0
  }
};

const QUARANTINE_FALLBACK: QuarantineQueueResponse = {
  entries: [],
  summary: {
    open: 0,
    restored: 0,
    dismissed: 0
  }
};

const LIVE_FALLBACK: LiveSnapshot = {
  generated_at: new Date().toISOString(),
  counts: {
    tasks_in_progress: 2,
    tasks_review: 1,
    alerts_open: 1,
    escalations_open: 0,
    agents_running: 2,
    failures_total: 0,
    repeated_failure_tasks: 0
  },
  revision: {}
};

const PROVIDERS_FALLBACK: ProvidersResponse = {
  providers: [
    {
      id: "python_script",
      name: "Python Script",
      kind: "local_worker",
      status: "available",
      execution_mode: "local_simulation",
      configured_execution_mode: "local_simulation",
      effective_execution_mode: "local_simulation",
      supports_worker_execution: true,
      supports_live_api: false,
      default_artifact_type: "provider_report",
      lifecycle_version: "provider_runtime_v1",
      lifecycle_phases: [
        "session_started",
        "workspace_prepared",
        "execution_running",
        "artifact_recorded",
        "session_completed"
      ],
      available_execution_modes: ["local_simulation"],
      runtime_controls: {},
      configurable_runtime_controls: {},
      config_warnings: [],
      is_runnable: true,
      run_summary: {
        total_runs: 0,
        active_runs: 0,
        completed_runs: 0,
        failed_runs: 0,
        timed_out_runs: 0,
        cancelled_runs: 0,
        last_run_at: null,
        timeout_failures: 0,
        nonzero_exit_failures: 0,
        runtime_failures: 0,
        latest_failure_kind: null,
        latest_failure_at: null
      },
      job_summary: {
        queued_jobs: 0,
        running_jobs: 0,
        completed_jobs: 0,
        failed_jobs: 0,
        cancelled_jobs: 0,
        last_job_at: null
      },
      recent_runs: [],
      latest_preflight: null,
      notes: "Reference local runtime with normalized runtime phase reporting."
    },
    {
      id: "claude_code",
      name: "Claude Code",
      kind: "interactive_cli",
      status: "simulated",
      execution_mode: "local_simulation",
      configured_execution_mode: "local_simulation",
      effective_execution_mode: "local_simulation",
      supports_worker_execution: true,
      supports_live_api: false,
      default_artifact_type: "provider_report",
      lifecycle_version: "provider_runtime_v1",
      lifecycle_phases: [
        "session_started",
        "workspace_prepared",
        "execution_running",
        "artifact_recorded",
        "session_completed"
      ],
      available_execution_modes: ["local_simulation", "claude_cli"],
      runtime_controls: {},
      configurable_runtime_controls: {
        cli_command: "claude",
        timeout_seconds: 300,
        permission_mode: "acceptEdits",
        model: ""
      },
      config_warnings: [],
      is_runnable: true,
      run_summary: {
        total_runs: 0,
        active_runs: 0,
        completed_runs: 0,
        failed_runs: 0,
        timed_out_runs: 0,
        cancelled_runs: 0,
        last_run_at: null,
        timeout_failures: 0,
        nonzero_exit_failures: 0,
        runtime_failures: 0,
        latest_failure_kind: null,
        latest_failure_at: null
      },
      job_summary: {
        queued_jobs: 0,
        running_jobs: 0,
        completed_jobs: 0,
        failed_jobs: 0,
        cancelled_jobs: 0,
        last_job_at: null
      },
      recent_runs: [],
      latest_preflight: null,
      notes: "Simulated local adapter with normalized runtime phase reporting."
    },
    {
      id: "openai_codex",
      name: "OpenAI Codex",
      kind: "api_runtime",
      status: "simulated",
      execution_mode: "local_simulation",
      configured_execution_mode: "local_simulation",
      effective_execution_mode: "local_simulation",
      supports_worker_execution: true,
      supports_live_api: false,
      default_artifact_type: "provider_report",
      lifecycle_version: "provider_runtime_v1",
      lifecycle_phases: [
        "session_started",
        "workspace_prepared",
        "execution_running",
        "artifact_recorded",
        "session_completed"
      ],
      available_execution_modes: ["local_simulation", "codex_cli"],
      runtime_controls: {},
      configurable_runtime_controls: {
        cli_command: "codex",
        timeout_seconds: 300,
        sandbox: "workspace-write",
        model: ""
      },
      config_warnings: [],
      is_runnable: true,
      run_summary: {
        total_runs: 0,
        active_runs: 0,
        completed_runs: 0,
        failed_runs: 0,
        timed_out_runs: 0,
        cancelled_runs: 0,
        last_run_at: null,
        timeout_failures: 0,
        nonzero_exit_failures: 0,
        runtime_failures: 0,
        latest_failure_kind: null,
        latest_failure_at: null
      },
      job_summary: {
        queued_jobs: 0,
        running_jobs: 0,
        completed_jobs: 0,
        failed_jobs: 0,
        cancelled_jobs: 0,
        last_job_at: null
      },
      recent_runs: [],
      latest_preflight: null,
      notes: "Simulated API-style adapter with normalized runtime phase reporting."
    }
  ],
  run_targets: [],
  job_queue: [],
  worker_summary: {
    total_workers: 0,
    idle_workers: 0,
    busy_workers: 0,
    offline_workers: 0
  },
  worker_pool: []
};

const RECOVERY_POLICY_FALLBACK: RecoveryPolicyResponse = {
  project_id: "proj_fallback",
  policy: {
    auto_retry_timeout_sessions: false,
    auto_retry_failed_sessions: false,
    auto_recover_blocked_tasks: false,
    auto_dlq_retry_exhausted_tasks: false,
    auto_open_task_circuit_breakers: false,
    auto_route_circuit_breakers_to_replan: false,
    circuit_breaker_failure_threshold: 3,
    circuit_breaker_replan_after_seconds: 300,
    max_timed_out_retries: 1,
    max_failed_session_retries: 1,
    timed_out_retry_cooldown_seconds: 60,
    failed_session_retry_cooldown_seconds: 120,
    recover_and_requeue_cooldown_seconds: 30,
    retry_backoff_multiplier: 2,
    retry_backoff_max_seconds: 900
  },
  defaults: {
    auto_retry_timeout_sessions: false,
    auto_retry_failed_sessions: false,
    auto_recover_blocked_tasks: false,
    auto_dlq_retry_exhausted_tasks: false,
    auto_open_task_circuit_breakers: false,
    auto_route_circuit_breakers_to_replan: false,
    circuit_breaker_failure_threshold: 3,
    circuit_breaker_replan_after_seconds: 300,
    max_timed_out_retries: 1,
    max_failed_session_retries: 1,
    timed_out_retry_cooldown_seconds: 60,
    failed_session_retry_cooldown_seconds: 120,
    recover_and_requeue_cooldown_seconds: 30,
    retry_backoff_multiplier: 2,
    retry_backoff_max_seconds: 900
  },
  summary: {
    retry_backoff_tasks: 0,
    needs_replan_tasks: 0,
    circuit_breaker_tasks: 0,
    replanning_candidates: 0,
    tasks_with_retry_history: 0,
    recoverable_blocked_tasks: 0,
    auto_recovery_candidates: 0,
    auto_replan_candidates: 0,
    open_dead_letter_entries: 0,
    open_circuit_breakers: 0,
    tasks_with_retry_overrides: 0,
    open_quarantine_entries: 0,
    open_failure_alerts: 0,
    open_repeated_failure_alerts: 0,
    open_stale_agent_alerts: 0
  },
  backoff_preview: {
    timed_out_retry_delays: [{ attempt: 1, delay_seconds: 60 }],
    failed_session_retry_delays: [{ attempt: 1, delay_seconds: 120 }],
    recover_and_requeue_delays: [
      { attempt: 1, delay_seconds: 30 },
      { attempt: 2, delay_seconds: 60 },
      { attempt: 3, delay_seconds: 120 }
    ]
  },
  task_retry_overrides: [],
  auto_recovery_candidates: [],
  auto_replan_candidates: [],
  recoverable_blocked_tasks: [],
  task_retry_history: [],
  replanning_candidates: [],
  needs_replan_tasks: [],
  circuit_breaker_tasks: [],
  active_retry_backoff: [],
  dead_letter_entries: [],
  open_quarantine_entries: [],
  open_failure_alerts: [],
  open_stale_agent_alerts: [],
  repeated_failure_incidents: []
};

async function fetchJson<T>(
  path: string,
  fallback: T,
  signal?: AbortSignal,
  onFallback?: () => void,
  projectId?: string | null
): Promise<T> {
  const scopedPath = appendProjectScope(path, projectId);
  try {
    const response = await fetch(scopedPath, { signal });
    if (!response.ok) {
      throw new Error(`Unexpected status: ${response.status}`);
    }
    const payload = (await response.json()) as T;
    lastSuccessfulResponses.set(scopedPath, payload);
    return payload;
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw error;
    }
    onFallback?.();
    if (lastSuccessfulResponses.has(scopedPath)) {
      return lastSuccessfulResponses.get(scopedPath) as T;
    }
    return fallback;
  }
}

async function fetchGlobalJson<T>(
  path: string,
  fallback: T,
  signal?: AbortSignal,
  onFallback?: () => void
): Promise<T> {
  try {
    const response = await fetch(path, { signal });
    if (!response.ok) {
      throw new Error(`Unexpected status: ${response.status}`);
    }
    const payload = (await response.json()) as T;
    lastSuccessfulResponses.set(path, payload);
    return payload;
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw error;
    }
    onFallback?.();
    if (lastSuccessfulResponses.has(path)) {
      return lastSuccessfulResponses.get(path) as T;
    }
    return fallback;
  }
}

export function fetchProjects() {
  return fetchJson<ProjectsResponse>("/api/projects", { projects: [] });
}

export function fetchProjectTemplates(signal?: AbortSignal, onFallback?: () => void) {
  return fetchJson<ProjectTemplatesResponse>("/api/projects/templates", { templates: [] }, signal, onFallback);
}

export function fetchPortfolio(signal?: AbortSignal, onFallback?: () => void) {
  return fetchGlobalJson<PortfolioResponse>("/api/portfolio", PORTFOLIO_FALLBACK, signal, onFallback);
}

export async function createProject(payload: ProjectCreateRequest) {
  const response = await postJson<ProjectCreateResponse>("/api/projects", payload);
  return response as ProjectCreateResponse;
}

export function fetchAutopilotStatus(
  signal?: AbortSignal,
  onFallback?: () => void,
  projectId?: string | null
) {
  return fetchJson<AutopilotStatusResponse>(
    "/api/autopilot/status",
    {
      project_id: "",
      policy: {
        enabled: false,
        interval_seconds: 20,
        allocate_limit: 6,
        provider_job_limit: 4,
        auto_launch_assigned_work: true,
        process_notifications: true,
        notification_batch_limit: 5,
        schedule_window_start_hour_utc: null,
        schedule_window_end_hour_utc: null,
        stop_when_doctor_blocked: true,
        max_review_queue: 0,
        max_blocked_queue: 0,
        max_idle_cycles_before_alert: 6,
        max_stale_runs: 0,
        max_repeated_failure_incidents: 0,
        max_notification_failures: 0,
      },
      runtime: {
        project_id: "",
        enabled: false,
        running: false,
        policy: {
          enabled: false,
          interval_seconds: 20,
          allocate_limit: 6,
          provider_job_limit: 4,
          auto_launch_assigned_work: true,
          process_notifications: true,
          notification_batch_limit: 5,
          schedule_window_start_hour_utc: null,
          schedule_window_end_hour_utc: null,
          stop_when_doctor_blocked: true,
          max_review_queue: 0,
          max_blocked_queue: 0,
          max_idle_cycles_before_alert: 6,
          max_stale_runs: 0,
          max_repeated_failure_incidents: 0,
          max_notification_failures: 0,
        },
        last_heartbeat_at: null,
        last_summary: null,
        last_error: null,
        loop_count: 0,
      },
      why_idle: "Autopilot status unavailable.",
      governance_gate: {
        blocked: false,
        summary: "Autopilot governance thresholds are clear.",
        reason: null,
        detail: null,
        review_queue: 0,
        blocked_queue: 0,
        stale_runs: 0,
        repeated_failure_incidents: 0,
        notification_failures: 0,
        schedule_window_open: true,
        doctor_summary: null,
        doctor_state: null,
        thresholds: {
          max_review_queue: 0,
          max_blocked_queue: 0,
          max_stale_runs: 0,
          max_repeated_failure_incidents: 0,
          max_notification_failures: 0,
        },
        signals: [],
      },
    },
    signal,
    onFallback,
    projectId
  );
}

export function fetchOperatorInbox(signal?: AbortSignal, onFallback?: () => void) {
  return fetchJson<OperatorInboxResponse>(
    appendProjectScope("/api/operator-inbox"),
    {
      project_id: "",
      generated_at: new Date().toISOString(),
      summary: {
        total_items: 0,
        review: 0,
        stale_runs: 0,
        blocked_recovery: 0,
        policy_conflicts: 0,
        notification_failures: 0,
        critical_items: 0,
      },
      buckets: {},
      items: [],
      workflow: {
        inbox: {
          headline: "Operator inbox is clear",
          detail: "No review, recovery, stale-run, or notification pressure currently requires manual intervention.",
          totalCount: 0,
          reviewCount: 0,
          recoveryCount: 0,
          suspectRunCount: 0,
          failedNotificationCount: 0,
          policyConflictCount: 0,
          recommendedView: "command",
          recommendedLabel: "Open Command",
          operatorActions: [],
          items: [],
        },
        autopilot: {
          tone: "default",
          label: "Loading posture...",
          summary: "Refreshing project execution posture.",
          detail: "The operator loop will appear here once project state loads.",
          facts: [],
          operatorActions: [],
        },
      },
      project: {
        project_id: "",
        name: "",
        queue_mode: "running",
        max_running_jobs: 0,
        autopilot_enabled: false,
      },
    },
    signal,
    onFallback
  );
}

export async function updateProjectAutopilot(
  projectId: string,
  payload: {
    enabled: boolean;
    interval_seconds: number;
    allocate_limit: number;
    provider_job_limit: number;
    auto_launch_assigned_work: boolean;
    process_notifications: boolean;
    notification_batch_limit: number;
    schedule_window_start_hour_utc?: number | null;
    schedule_window_end_hour_utc?: number | null;
    stop_when_doctor_blocked?: boolean;
    max_review_queue?: number;
    max_blocked_queue?: number;
    max_idle_cycles_before_alert?: number;
    max_stale_runs?: number;
    max_repeated_failure_incidents?: number;
    max_notification_failures?: number;
  }
) {
  return postJson(`/api/projects/${projectId}/actions/update-autopilot`, {
    actor_id: DEFAULT_ACTOR_ID,
    ...payload,
  });
}

export function fetchEnvironmentDoctor(
  signal?: AbortSignal,
  onFallback?: () => void,
  projectId?: string | null
) {
  return fetchJson<EnvironmentDoctorResponse>(
    "/api/environment/doctor",
    {
      generated_at: new Date().toISOString(),
      project_id: "",
      project_name: "",
      source_root: "",
      preferred_provider_id: null,
      summary: {
        status: "attention",
        label: "Attention needed",
        summary: "Environment doctor unavailable.",
        detail: "The doctor panel is using fallback data until the API responds again.",
      },
      checks: [],
      progress: {
        status: "idle",
        summary: "Progress diagnosis unavailable.",
        detail: "The current no-progress diagnosis could not be loaded.",
        recommended_action: "Refresh the page or inspect System for more detail.",
        reasons: [],
        operator_actions: [],
        facts: {},
      },
      recommended_actions: [],
    },
    signal,
    onFallback,
    projectId
  );
}

export function fetchGoalPlanning(
  signal?: AbortSignal,
  onFallback?: () => void,
  projectId?: string | null
) {
  return fetchJson<GoalPlanningResponse>(
    "/api/goals/planning",
    {
      summary: {
        total_goals: 0,
        active_goals: 0,
        open_issue_count: 0,
        synthesized_tasks: 0,
      },
      items: [],
    },
    signal,
    onFallback,
    projectId
  );
}

export async function createGoal(payload: {
  title: string;
  description?: string;
  goal_type?: string;
  priority?: number;
  parent_goal_id?: string | null;
}) {
  return postJson<GoalCreateResponse>(appendProjectScope("/api/goals"), {
    actor_id: DEFAULT_ACTOR_ID,
    ...payload,
  });
}

export async function synthesizeGoal(goalId: string, refresh = true) {
  return postJson<GoalSynthesisResponse>(appendProjectScope(`/api/goals/${goalId}/actions/synthesize`), {
    actor_id: DEFAULT_ACTOR_ID,
    refresh,
  });
}

export function fetchDeliveryOverview(
  signal?: AbortSignal,
  onFallback?: () => void,
  projectId?: string | null
) {
  return fetchJson<DeliveryOverviewResponse>(
    "/api/delivery",
    {
      project_id: "",
      project_name: "",
      summary: {
        candidate_count: 0,
        bundle_ready_count: 0,
        github_ready_count: 0,
        diff_count: 0,
        report_count: 0,
        bundle_count: 0,
        ready_count: 0,
        attention_count: 0,
        blocked_count: 0,
        synced_count: 0,
      },
      git: {
        is_git_repo: false,
        branch: null,
        default_branch: null,
        dirty: false,
      },
      items: [],
    },
    signal,
    onFallback,
    projectId
  );
}

export function fetchTaskDeliveryStatus(taskId: string, signal?: AbortSignal) {
  return fetchJson<TaskDeliveryStatusResponse>(
    appendProjectScope(`/api/tasks/${taskId}/delivery`),
    {
      task_id: taskId,
      issue_key: null,
      title: "",
      task_status: "planned",
      review_state: null,
      goal_title: null,
      latest_artifact_type: null,
      artifact_count: 0,
      created_at: null,
      bundle_ready: false,
      github_ready: false,
      delivery_kind: "artifact",
      delivery_gate: {
        status: "blocked",
        summary: "Delivery state is unavailable.",
        detail: "The current delivery state could not be loaded.",
        checks: []
      },
      latest_draft: null,
      github_pr: null,
      latest_artifacts: [],
      git: {
        is_git_repo: false,
        branch: null,
        default_branch: null,
        dirty: false
      }
    },
    signal
  );
}

export async function prepareTaskPrDraft(taskId: string) {
  return postJson<DeliveryDraftResponse>(appendProjectScope(`/api/tasks/${taskId}/actions/prepare-pr-draft`), {
    actor_id: DEFAULT_ACTOR_ID,
  });
}

export async function syncTaskGithubPr(taskId: string) {
  return postJson<DeliverySyncResponse>(appendProjectScope(`/api/tasks/${taskId}/actions/sync-github-pr`), {
    actor_id: DEFAULT_ACTOR_ID,
  });
}

export async function cloneProject(projectId: string, name?: string) {
  const response = await postJson<ProjectCreateResponse>(`/api/projects/${projectId}/actions/clone`, {
    actor_id: DEFAULT_ACTOR_ID,
    name: name?.trim() || undefined,
  });
  return response as ProjectCreateResponse;
}

export async function pickLocalDirectory() {
  const response = await postJson<DirectoryPickerResponse>("/api/system/actions/pick-directory", {});
  return response as DirectoryPickerResponse;
}

export async function archiveProject(projectId: string) {
  const response = await postJson<ProjectActionResponse>(`/api/projects/${projectId}/actions/archive`, {
    actor_id: "agent_allocator"
  });
  return response as ProjectActionResponse;
}

export async function restoreProject(projectId: string) {
  const response = await postJson<ProjectActionResponse>(`/api/projects/${projectId}/actions/restore`, {
    actor_id: "agent_allocator"
  });
  return response as ProjectActionResponse;
}

export async function deleteProject(projectId: string) {
  const response = await postJson<ProjectActionResponse>(`/api/projects/${projectId}/actions/delete`, {
    actor_id: "agent_allocator"
  });
  return response as ProjectActionResponse;
}

export async function updateBrownfieldOnboardingReview(
  projectId: string,
  payload: {
    ignored_paths: string[];
    accepted_workflow_labels?: string[] | null;
    accepted_runbook_labels?: string[] | null;
  }
) {
  return postJson(`/api/projects/${projectId}/actions/update-onboarding-review`, {
    actor_id: "agent_allocator",
    ignored_paths: payload.ignored_paths,
    accepted_workflow_labels: payload.accepted_workflow_labels ?? null,
    accepted_runbook_labels: payload.accepted_runbook_labels ?? null
  });
}

export async function updateProjectProviderCapacity(
  projectId: string,
  payload: {
    queue_mode: "running" | "draining" | "paused";
    max_running_jobs: number;
    preferred_provider_id?: string | null;
  }
) {
  return postJson(`/api/projects/${projectId}/actions/update-provider-capacity`, {
    actor_id: "agent_allocator",
    queue_mode: payload.queue_mode,
    max_running_jobs: payload.max_running_jobs,
    preferred_provider_id: payload.preferred_provider_id ?? null
  });
}

export async function updateProjectReviewPolicy(
  projectId: string,
  payload: {
    auto_approve_low_risk: boolean;
    max_priority_for_auto_approve: number;
    require_verification_pass: boolean;
  }
) {
  return postJson(`/api/projects/${projectId}/actions/update-review-policy`, {
    actor_id: "agent_allocator",
    auto_approve_low_risk: payload.auto_approve_low_risk,
    max_priority_for_auto_approve: payload.max_priority_for_auto_approve,
    require_verification_pass: payload.require_verification_pass,
  });
}

export async function updateProjectRiskPolicy(
  projectId: string,
  payload: { priority_threshold: number; sensitive_path_prefixes: string[] }
) {
  return postJson(`/api/projects/${projectId}/actions/update-risk-policy`, {
    actor_id: "agent_allocator",
    priority_threshold: payload.priority_threshold,
    sensitive_path_prefixes: payload.sensitive_path_prefixes
  });
}

export async function updateProjectRuntimeQuotas(
  projectId: string,
  payload: {
    daily_run_limit: number;
    daily_live_run_limit: number;
    daily_runtime_seconds_limit: number;
    max_task_session_attempts: number;
  }
) {
  return postJson(`/api/projects/${projectId}/actions/update-runtime-quotas`, {
    actor_id: "agent_allocator",
    daily_run_limit: payload.daily_run_limit,
    daily_live_run_limit: payload.daily_live_run_limit,
    daily_runtime_seconds_limit: payload.daily_runtime_seconds_limit,
    max_task_session_attempts: payload.max_task_session_attempts
  });
}

export async function updateProjectNotificationPolicy(
  projectId: string,
  payload: {
    webhook_urls: string[];
    minimum_severity: "info" | "warning" | "critical";
    enabled_events: string[];
  }
) {
  return postJson(`/api/projects/${projectId}/actions/update-notification-policy`, {
    actor_id: "agent_allocator",
    webhook_urls: payload.webhook_urls,
    minimum_severity: payload.minimum_severity,
    enabled_events: payload.enabled_events
  });
}

export async function processNotification(notificationId: string) {
  return postJson(`/api/notifications/${notificationId}/actions/process`, {
    actor_id: "agent_allocator"
  });
}

export async function processNextNotification(projectId?: string) {
  return postJson("/api/notifications/actions/process-next", {
    actor_id: "agent_allocator",
    project_id: projectId ?? null
  });
}

export function fetchNotifications(
  filters: { status?: string; limit?: number } = {},
  signal?: AbortSignal,
  onFallback?: () => void
) {
  const params = new URLSearchParams();
  if (filters.status) {
    params.set("status", filters.status);
  }
  if (filters.limit != null) {
    params.set("limit", String(filters.limit));
  }
  const path = appendProjectScope(params.toString() ? `/api/notifications?${params.toString()}` : "/api/notifications");
  return fetchJson<{ notifications: NotificationItem[] }>(path, { notifications: [] }, signal, onFallback);
}

export async function refreshRepoPlan(projectId: string) {
  return postJson(`/api/projects/${projectId}/actions/refresh-repo-plan`, {
    actor_id: "agent_allocator"
  });
}

export function fetchOverview(projectId?: string | null, signal?: AbortSignal, onFallback?: () => void) {
  return fetchJson<OverviewResponse>("/api/overview", OVERVIEW_FALLBACK, signal, onFallback, projectId);
}

export function fetchRepoTree(path = "", signal?: AbortSignal, onFallback?: () => void) {
  const query = new URLSearchParams();
  if (path) query.set("path", path);
  return fetchJson<RepoTreeResponse>(query.size > 0 ? `/api/repo/tree?${query.toString()}` : "/api/repo/tree", REPO_TREE_FALLBACK, signal, onFallback);
}

export function fetchRepoFile(path: string, signal?: AbortSignal, onFallback?: () => void) {
  const query = new URLSearchParams({ path });
  return fetchJson<RepoFileResponse>(`/api/repo/file?${query.toString()}`, REPO_FILE_FALLBACK, signal, onFallback);
}

export function fetchGoalTree() {
  return fetchJson<GoalTreeResponse>("/api/goals/tree", GOAL_TREE_FALLBACK);
}

export function fetchAgentRoster(
  signal?: AbortSignal,
  onFallback?: () => void,
  projectId?: string | null
) {
  return fetchJson<AgentRosterResponse>("/api/agents", ROSTER_FALLBACK, signal, onFallback, projectId);
}

export function fetchActivity(
  signal?: AbortSignal,
  onFallback?: () => void,
  projectId?: string | null
) {
  return fetchJson<ActivityItem[]>(
    appendProjectScope("/api/activity", projectId),
    ACTIVITY_FALLBACK,
    signal,
    onFallback,
    projectId
  );
}

export function fetchIncidentTimeline(
  params?: {
    taskId?: string;
    sessionId?: string;
    agentId?: string;
    resourceType?: string;
    resourceId?: string;
    order?: "asc" | "desc";
    limit?: number;
  },
  signal?: AbortSignal,
  onFallback?: () => void,
  projectId?: string | null
) {
  const query = new URLSearchParams();
  if (params?.taskId) query.set("task_id", params.taskId);
  if (params?.sessionId) query.set("session_id", params.sessionId);
  if (params?.agentId) query.set("agent_id", params.agentId);
  if (params?.resourceType) query.set("resource_type", params.resourceType);
  if (params?.resourceId) query.set("resource_id", params.resourceId);
  if (params?.order) query.set("order", params.order);
  if (params?.limit) query.set("limit", String(params.limit));
  const path = query.size ? `/api/timeline?${query.toString()}` : "/api/timeline";
  return fetchJson<TimelineResponse>(path, TIMELINE_FALLBACK, signal, onFallback, projectId);
}

export function fetchArtifacts(
  params?: {
    search?: string;
    state?: string;
    providerType?: string;
    artifactType?: string;
    taskId?: string;
    sessionId?: string;
    missingOnly?: boolean;
    limit?: number;
    offset?: number;
  },
  signal?: AbortSignal,
  onFallback?: () => void
) {
  const query = new URLSearchParams();
  if (params?.search) query.set("search", params.search);
  if (params?.state) query.set("state", params.state);
  if (params?.providerType) query.set("provider_type", params.providerType);
  if (params?.artifactType) query.set("artifact_type", params.artifactType);
  if (params?.taskId) query.set("task_id", params.taskId);
  if (params?.sessionId) query.set("session_id", params.sessionId);
  if (params?.missingOnly) query.set("missing_only", "true");
  if (params?.limit != null) query.set("limit", String(params.limit));
  if (params?.offset != null) query.set("offset", String(params.offset));
  const path = appendProjectScope(query.size > 0 ? `/api/artifacts?${query.toString()}` : "/api/artifacts");
  return fetchJson<ArtifactsResponse>(path, ARTIFACTS_FALLBACK, signal, onFallback);
}

export async function fetchArtifactDetail(artifactId: string, signal?: AbortSignal) {
  const response = await fetch(appendProjectScope(`/api/artifacts/${artifactId}`), { signal });
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Unexpected status: ${response.status}`);
  }
  return (await response.json()) as ArtifactDetail;
}

export function fetchCodexIssueDetail(taskId: string, signal?: AbortSignal, onFallback?: () => void) {
  return fetchJson<CodexIssueDetailResponse>(
    appendProjectScope(`/api/issues/${taskId}`),
    {
      task: {
        task_id: taskId,
        title: "Issue detail unavailable",
        description: "",
        status: "ready",
        priority: 50,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      relationships: {
        depends_on: [],
        unlocks: [],
        related: [],
      },
      runs: [],
      run_console: null,
      history: [],
      artifacts: [],
      artifact_summary: ARTIFACTS_FALLBACK.summary,
      verification_runs: [],
      review_decision: {
        status: "unavailable",
        batch_review_eligible: false,
        auto_approve_eligible: false,
        decision_mode: "manual_review",
        summary: "Issue review policy is unavailable.",
        detail: "Review guidance could not be loaded from the backend.",
        why_not_batch_reviewed: "Review guidance could not be loaded from the backend.",
        why_not_auto_approved: "Review guidance could not be loaded from the backend.",
        grouped_review_packet: null,
      },
      recovery_playbook: {
        kind: "idle",
        title: "Issue detail unavailable",
        summary: "Recovery guidance could not be loaded.",
        detail: "Refresh the page and load the issue again.",
        recommended_action: "Refresh the issue detail and retry the action.",
        actions: [],
        confidence: "low",
      },
      goal_explainability: null,
      memory_context: [],
      git_workspace: null,
    },
    signal,
    onFallback
  );
}

export function fetchCodexIssueIndex(signal?: AbortSignal, onFallback?: () => void) {
  return fetchJson<CodexIssueIndexResponse>(
    appendProjectScope("/api/issues/index"),
    {
      generated_at: new Date().toISOString(),
      summary: {
        review: 0,
        blocked_failures: 0,
        blocked_dependencies: 0,
        resolved: 0,
        recent_failures: 0,
        batch_review_eligible: 0,
      },
      queue: {
        review: {
          title: "Review queue",
          description: "",
          items: [],
          batch_review: {
            eligible_count: 0,
            eligible_task_ids: [],
            packets: [],
            summary: "",
          },
        },
        blocked_failures: {
          title: "Blocked by failures",
          description: "",
          items: [],
        },
        blocked_dependencies: {
          title: "Blocked by dependencies or operator state",
          description: "",
          items: [],
        },
      },
      resolved: [],
      board_summary: {
        total_tasks: 0,
        active_agents: 0,
        assigned_tasks: 0,
        active_tasks: 0,
        blocked_tasks: 0,
        review_tasks: 0,
      },
      filter_options: {
        agents: [],
        goals: [],
        priority_min_values: [0, 50, 75, 90],
      },
    },
    signal,
    onFallback
  );
}

export function fetchCodexRunDetail(sessionId: string, signal?: AbortSignal, onFallback?: () => void) {
  return fetchJson<CodexRunDetailResponse>(
    appendProjectScope(`/api/runs/${sessionId}`),
    {
      session_id: sessionId,
      provider_type: "openai_codex",
      status: "unknown",
      started_at: new Date().toISOString(),
      is_live: false,
      activity: [],
      artifacts: [],
      artifact_summary: ARTIFACTS_FALLBACK.summary,
      output_preview: null,
      stdout_preview: null,
      stderr_preview: null,
    },
    signal,
    onFallback
  );
}

export function fetchCodexRuns(
  filters: { limit?: number; status?: string; search?: string } = {},
  signal?: AbortSignal,
  onFallback?: () => void
) {
  const params = new URLSearchParams();
  if (filters.limit != null) {
    params.set("limit", String(filters.limit));
  }
  if (filters.status) {
    params.set("status", filters.status);
  }
  if (filters.search) {
    params.set("search", filters.search);
  }
  const path = appendProjectScope(params.toString() ? `/api/runs?${params.toString()}` : "/api/runs");
  return fetchJson<CodexRunIndexResponse>(
    path,
    {
      summary: {
        total_runs: 0,
        active_runs: 0,
        failed_runs: 0,
        timed_out_runs: 0,
        cancelled_runs: 0,
        completed_runs: 0,
        stale_runs: 0,
      },
      items: [],
    },
    signal,
    onFallback
  );
}

export function fetchCodexSystemDiagnostics(signal?: AbortSignal, onFallback?: () => void) {
  return fetchJson<CodexSystemDiagnosticsResponse>(
    appendProjectScope("/api/system/diagnostics"),
    {
      summary: {
        active_runs: 0,
        suspect_runs: 0,
        stale_agents: 0,
        queued_jobs: 0,
        running_jobs: 0,
        suppressed_items: 0,
        oldest_queued_at: null,
        oldest_running_at: null,
      },
      live_runs: {
        active_runs: 0,
        stale_runs: 0,
        failed_runs: 0,
        completed_runs: 0,
      },
      suspect_runs: [],
      stale_agents: [],
      attention_items: [],
      suppression: {
        summary: {
          total: 0,
          retry_backoff: 0,
          circuit_breaker: 0,
          quarantine: 0,
          repeated_failure: 0,
        },
        items: [],
      },
      queue_pressure: {
        queued_jobs: 0,
        running_jobs: 0,
        oldest_queued_at: null,
        oldest_running_at: null,
      },
    },
    signal,
    onFallback
  );
}

export function fetchCodexRetrievalSearch(
  filters: { search: string; goalId?: string | null; agentId?: string | null; priorityMin?: number | null },
  signal?: AbortSignal,
  onFallback?: () => void,
  projectId?: string | null
) {
  const params = new URLSearchParams();
  params.set("search", filters.search);
  if (filters.goalId) {
    params.set("goal_id", filters.goalId);
  }
  if (filters.agentId) {
    params.set("agent_id", filters.agentId);
  }
  if (filters.priorityMin != null) {
    params.set("priority_min", String(filters.priorityMin));
  }
  return fetchJson<CodexRetrievalSearchResponse>(
    `/api/retrieval/search?${params.toString()}`,
    {
      query: {
        search: filters.search,
        goal_id: filters.goalId ?? null,
        agent_id: filters.agentId ?? null,
        priority_min: filters.priorityMin ?? null,
      },
      summary: {
        total_hits: 0,
        issue_hits: 0,
        run_hits: 0,
        artifact_hits: 0,
        event_hits: 0,
        memory_hits: 0,
      },
      issues: [],
      runs: [],
      artifacts: [],
      events: [],
      memory: [],
    },
    signal,
    onFallback,
    projectId
  );
}

export async function cancelCodexRun(sessionId: string) {
  return postJson(`/api/runs/${sessionId}/actions/cancel`, {
    actor_id: DEFAULT_ACTOR_ID,
  });
}

export async function batchReviewIssues(taskIds: string[], decision: "approve" | "reject") {
  return postJson("/api/issues/actions/batch-review", {
    actor_id: DEFAULT_ACTOR_ID,
    decision,
    task_ids: taskIds,
  });
}

export async function promoteArtifactToMemory(
  artifactId: string,
  payload: { title?: string; summary?: string; tags?: string[] } = {}
) {
  return postJson(`/api/artifacts/${artifactId}/actions/promote-memory`, {
    actor_id: DEFAULT_ACTOR_ID,
    title: payload.title ?? null,
    summary: payload.summary ?? null,
    tags: payload.tags ?? [],
  });
}

export function fetchCodexAgentDetail(agentId: string, signal?: AbortSignal, onFallback?: () => void) {
  return fetchJson<CodexAgentDetailResponse>(
    `/api/agents/${agentId}`,
    {
      agent: {
        agent_id: agentId,
        role: "agent",
        display_name: "Agent detail unavailable",
        status: "idle",
      },
      owned_issues: [],
      runs: [],
      history: [],
    },
    signal,
    onFallback
  );
}

export async function fetchArtifactComparison(leftArtifactId: string, rightArtifactId: string, signal?: AbortSignal) {
  const response = await fetch(`/api/artifacts/${leftArtifactId}/compare/${rightArtifactId}`, { signal });
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Unexpected status: ${response.status}`);
  }
  return (await response.json()) as ArtifactComparisonResponse;
}

export function artifactDownloadUrl(artifactId: string) {
  return `/api/artifacts/${artifactId}/download`;
}

export async function purgeTaskArtifacts(taskId: string) {
  const payload = await postJson<ArtifactPurgeResponse>(`/api/tasks/${taskId}/artifacts/actions/purge`, {
    actor_id: "agent_allocator"
  });
  return payload as ArtifactPurgeResponse;
}

export async function purgeSessionArtifacts(sessionId: string) {
  const payload = await postJson<ArtifactPurgeResponse>(`/api/sessions/${sessionId}/artifacts/actions/purge`, {
    actor_id: "agent_allocator"
  });
  return payload as ArtifactPurgeResponse;
}

export function fetchAlerts(
  signal?: AbortSignal,
  onFallback?: () => void,
  projectId?: string | null
) {
  return fetchJson<AlertsResponse>("/api/alerts", ALERTS_FALLBACK, signal, onFallback, projectId);
}

export function fetchEscalations() {
  return fetchJson<EscalationsResponse>("/api/escalations", ESCALATIONS_FALLBACK);
}

export function fetchFailures() {
  return fetchJson<FailuresResponse>("/api/failures", FAILURES_FALLBACK);
}

export function fetchQuarantineQueue() {
  return fetchJson<QuarantineQueueResponse>("/api/quarantine", QUARANTINE_FALLBACK);
}

export async function restoreFailureArtifacts(failureId: string) {
  const payload = await postJson<RestoreFailureArtifactsResponse>(`/api/failures/${failureId}/actions/restore-artifacts`, {
    actor_id: "agent_allocator"
  });
  return payload as RestoreFailureArtifactsResponse;
}

export async function restoreQuarantineEntry(queueId: string) {
  const payload = await postJson<RestoreQuarantineEntryResponse>(`/api/quarantine/${queueId}/actions/restore`, {
    actor_id: "agent_allocator"
  });
  return payload as RestoreQuarantineEntryResponse;
}

export async function restoreAndRequeueQuarantineEntry(queueId: string) {
  const payload = await postJson<RestoreAndRequeueQuarantineEntryResponse>(
    `/api/quarantine/${queueId}/actions/restore-and-requeue`,
    {
      actor_id: "agent_allocator"
    }
  );
  return payload as RestoreAndRequeueQuarantineEntryResponse;
}

export async function dismissQuarantineEntry(queueId: string) {
  const payload = await postJson<DismissQuarantineEntryResponse>(`/api/quarantine/${queueId}/actions/dismiss`, {
    actor_id: "agent_allocator"
  });
  return payload as DismissQuarantineEntryResponse;
}

export async function reopenQuarantineEntry(queueId: string) {
  const payload = await postJson<ReopenQuarantineEntryResponse>(`/api/quarantine/${queueId}/actions/reopen`, {
    actor_id: "agent_allocator"
  });
  return payload as ReopenQuarantineEntryResponse;
}

export async function recoverTask(taskId: string) {
  const payload = await postJson(`/api/tasks/${taskId}/actions/recover`, {
    actor_id: "agent_allocator"
  });
  return payload;
}

export async function recoverAndRequeueTask(taskId: string) {
  const payload = await postJson(`/api/tasks/${taskId}/actions/recover-and-requeue`, {
    actor_id: "agent_allocator"
  });
  return payload;
}

export async function markTaskForReplan(taskId: string) {
  const payload = await postJson(`/api/tasks/${taskId}/actions/mark-for-replan`, {
    actor_id: "agent_allocator"
  });
  return payload;
}

export async function finishTaskReplan(taskId: string) {
  const payload = await postJson(`/api/tasks/${taskId}/actions/finish-replan`, {
    actor_id: "agent_allocator"
  });
  return payload;
}

export function fetchLiveSnapshot() {
  return fetchJson<LiveSnapshot>("/api/live", LIVE_FALLBACK);
}

export function fetchProviders(
  signal?: AbortSignal,
  onFallback?: () => void,
  projectId?: string | null
) {
  return fetchJson<ProvidersResponse>(
    appendProjectScope("/api/providers", projectId),
    PROVIDERS_FALLBACK,
    signal,
    onFallback,
    projectId
  );
}

export function fetchRecoveryPolicy(
  signal?: AbortSignal,
  onFallback?: () => void,
  projectId?: string | null
) {
  return fetchJson<RecoveryPolicyResponse>(
    appendProjectScope("/api/recovery-policy", projectId),
    RECOVERY_POLICY_FALLBACK,
    signal,
    onFallback,
    projectId
  );
}

export async function runProviderTask(providerId: string, projectId: string, agentId: string, taskId: string) {
  const payload = await postJson<{
    session_id: string;
    artifact_id?: string | null;
    artifact_path: string;
  }>(`/api/providers/${providerId}/actions/run-task`, {
    project_id: projectId,
    agent_id: agentId,
    task_id: taskId
  });
  return payload as {
    session_id: string;
    artifact_id?: string | null;
    artifact_path: string;
  };
}

export async function queueProviderTask(providerId: string, projectId: string, agentId: string, taskId: string) {
  const payload = await postJson<{
    job_id: string;
    status: string;
  }>(`/api/providers/${providerId}/actions/queue-task`, {
    actor_id: "agent_allocator",
    project_id: projectId,
    agent_id: agentId,
    task_id: taskId
  });
  return payload as {
    job_id: string;
    status: string;
  };
}

export async function processProviderJob(jobId: string) {
  const payload = await postJson<{
    job_id: string;
    status: string;
    session_id?: string | null;
    artifact_id?: string | null;
    failure_kind?: string | null;
    failure_detail?: string | null;
  }>(`/api/provider-jobs/${jobId}/actions/process`, {
    actor_id: "agent_allocator"
  });
  return payload as {
    job_id: string;
    status: string;
    session_id?: string | null;
    artifact_id?: string | null;
    failure_kind?: string | null;
    failure_detail?: string | null;
  };
}

export async function runProviderWorkerOnce(workerId: string, providerId?: string) {
  return postJson<{
    processed: boolean;
    worker_id: string;
    job?: {
      job_id: string;
      status: string;
      provider_id: string;
      title?: string | null;
    } | null;
  }>("/api/provider-workers/actions/run-once", {
    worker_id: workerId,
    provider_id: providerId ?? null,
    project_id: getSelectedProjectId()
  });
}

export async function setProviderMode(providerId: string, mode: string) {
  const payload = await postJson(`/api/providers/${providerId}/actions/set-mode`, {
    actor_id: "agent_allocator",
    mode,
    project_id: getSelectedProjectId()
  });
  return payload;
}

export async function setProviderSettings(providerId: string, settings: Record<string, string | number | boolean>) {
  const payload = await postJson(`/api/providers/${providerId}/actions/set-settings`, {
    actor_id: "agent_allocator",
    settings,
    project_id: getSelectedProjectId()
  });
  return payload;
}

export async function runProviderPreflight(providerId: string) {
  const payload = await postJson(`/api/providers/${providerId}/actions/run-preflight`, {
    actor_id: "agent_allocator",
    project_id: getSelectedProjectId()
  });
  return payload as {
    provider_id: string;
    status: string;
    summary: string;
    issues?: string[];
  };
}

export async function setRecoveryPolicy(
  policy: Record<string, string | number | boolean>
) {
  const payload = await postJson("/api/recovery-policy/actions/set", {
    actor_id: "agent_allocator",
    policy,
    project_id: getSelectedProjectId()
  });
  return payload;
}

export async function setTaskRetryLimit(taskId: string, autoRetryLimit: number | null) {
  const payload = await postJson(`/api/tasks/${taskId}/actions/set-retry-limit`, {
    actor_id: "agent_allocator",
    auto_retry_limit: autoRetryLimit
  });
  return payload;
}

export async function releaseTaskRetryBackoff(taskId: string) {
  const payload = await postJson(`/api/tasks/${taskId}/actions/release-retry-backoff`, {
    actor_id: "agent_allocator"
  });
  return payload;
}

export async function resetTaskRetryState(taskId: string) {
  const payload = await postJson(`/api/tasks/${taskId}/actions/reset-retry-state`, {
    actor_id: "agent_allocator"
  });
  return payload;
}

export async function resetTaskCircuitBreaker(taskId: string) {
  const payload = await postJson(`/api/tasks/${taskId}/actions/reset-circuit-breaker`, {
    actor_id: "agent_allocator"
  });
  return payload;
}

async function postJson<T = any>(path: string, body: object): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    let detail = `Unexpected status: ${response.status}`;
    try {
      const payload = await response.json();
      if (typeof payload?.detail === "string" && payload.detail.trim()) {
        detail = payload.detail;
      }
    } catch {
      // Ignore non-JSON error bodies and fall back to status text.
    }
    throw new Error(detail);
  }

  if (response.status === 204) {
    return null as T;
  }

  return (await response.json()) as T;
}

export async function updateAlertStatus(alertId: string, action: "acknowledge" | "resolve") {
  await postJson(`/api/alerts/${alertId}/actions/${action}`, { actor_id: "agent_allocator" });
}

export async function runAlertOperatorAction(operatorAction: AlertOperatorAction) {
  if (operatorAction.action === "recover_task") {
    await postJson(`/api/tasks/${operatorAction.resource_id}/actions/recover`, { actor_id: "agent_allocator" });
    return;
  }
  if (operatorAction.action === "resolve_repeated_failures") {
    await postJson(`/api/tasks/${operatorAction.resource_id}/actions/resolve-repeated-failures`, {
      actor_id: "agent_allocator"
    });
    return;
  }
  await postJson(`/api/agents/${operatorAction.resource_id}/actions/recover`, { actor_id: "agent_allocator" });
}

export async function runControlOperatorAction(operatorAction: ControlOperatorAction) {
  if (operatorAction.action === "run_orchestrator") {
    const payload = operatorAction.payload ?? {};
    return runOrchestratorPass(
      Number(payload.allocate_limit ?? 6),
      Number(payload.provider_job_limit ?? 4),
      Boolean(payload.auto_launch_assigned_work ?? true)
    );
  }
  if (operatorAction.action === "cancel_run") {
    await cancelCodexRun(operatorAction.resource_id);
    return;
  }
  if (operatorAction.action === "update_launch_posture") {
    await updateProjectProviderCapacity(operatorAction.resource_id, {
      queue_mode: String(operatorAction.payload?.queue_mode ?? "running") as "running" | "draining" | "paused",
      max_running_jobs: Number(operatorAction.payload?.max_running_jobs ?? 1),
      preferred_provider_id:
        typeof operatorAction.payload?.preferred_provider_id === "string"
          ? operatorAction.payload.preferred_provider_id
          : null,
    });
    return;
  }
  if (operatorAction.action === "update_autopilot") {
    await updateProjectAutopilot(operatorAction.resource_id, {
      enabled: Boolean(operatorAction.payload?.enabled ?? false),
      interval_seconds: Number(operatorAction.payload?.interval_seconds ?? 20),
      allocate_limit: Number(operatorAction.payload?.allocate_limit ?? 6),
      provider_job_limit: Number(operatorAction.payload?.provider_job_limit ?? 4),
      auto_launch_assigned_work: Boolean(operatorAction.payload?.auto_launch_assigned_work ?? true),
      process_notifications: Boolean(operatorAction.payload?.process_notifications ?? true),
      notification_batch_limit: Number(operatorAction.payload?.notification_batch_limit ?? 5),
      schedule_window_start_hour_utc:
        operatorAction.payload?.schedule_window_start_hour_utc == null
          ? null
          : Number(operatorAction.payload.schedule_window_start_hour_utc),
      schedule_window_end_hour_utc:
        operatorAction.payload?.schedule_window_end_hour_utc == null
          ? null
          : Number(operatorAction.payload.schedule_window_end_hour_utc),
      stop_when_doctor_blocked: Boolean(operatorAction.payload?.stop_when_doctor_blocked ?? true),
      max_review_queue: Number(operatorAction.payload?.max_review_queue ?? 0),
      max_blocked_queue: Number(operatorAction.payload?.max_blocked_queue ?? 0),
      max_idle_cycles_before_alert: Number(operatorAction.payload?.max_idle_cycles_before_alert ?? 6),
      max_stale_runs: Number(operatorAction.payload?.max_stale_runs ?? 0),
      max_repeated_failure_incidents: Number(operatorAction.payload?.max_repeated_failure_incidents ?? 0),
      max_notification_failures: Number(operatorAction.payload?.max_notification_failures ?? 0),
    });
    return;
  }
  if (operatorAction.action === "process_notification") {
    return processNotification(operatorAction.resource_id);
  }
  if (operatorAction.action === "process_next_notification") {
    return processNextNotification(operatorAction.resource_type === "project" ? operatorAction.resource_id : undefined);
  }
  if (operatorAction.action === "recover_task") {
    await recoverTask(operatorAction.resource_id);
    return;
  }
  if (operatorAction.action === "recover_and_requeue_task") {
    await recoverAndRequeueTask(operatorAction.resource_id);
    return;
  }
  if (operatorAction.action === "mark_task_for_replan") {
    await markTaskForReplan(operatorAction.resource_id);
    return;
  }
  if (operatorAction.action === "resolve_repeated_failures") {
    await postJson(`/api/tasks/${operatorAction.resource_id}/actions/resolve-repeated-failures`, {
      actor_id: DEFAULT_ACTOR_ID,
    });
    return;
  }
  if (operatorAction.action === "reset_retry_state") {
    await resetTaskRetryState(operatorAction.resource_id);
    return;
  }
  if (operatorAction.action === "reset_circuit_breaker") {
    await resetTaskCircuitBreaker(operatorAction.resource_id);
    return;
  }
  if (operatorAction.action === "restore_and_requeue_quarantine_entry") {
    await restoreAndRequeueQuarantineEntry(operatorAction.resource_id);
  }
}

export async function runFailureOperatorAction(operatorAction: FailureOperatorAction) {
  if (operatorAction.action === "restore_and_requeue_quarantine_entry") {
    await restoreAndRequeueQuarantineEntry(operatorAction.resource_id);
    return;
  }
  if (operatorAction.action === "restore_quarantine_entry") {
    await restoreQuarantineEntry(operatorAction.resource_id);
    return;
  }
  if (operatorAction.action === "dismiss_quarantine_entry") {
    await dismissQuarantineEntry(operatorAction.resource_id);
    return;
  }
  if (operatorAction.action === "reopen_quarantine_entry") {
    await reopenQuarantineEntry(operatorAction.resource_id);
    return;
  }
  if (operatorAction.action === "restore_failure_artifacts") {
    await restoreFailureArtifacts(operatorAction.resource_id);
    return;
  }
  await recoverAndRequeueTask(operatorAction.resource_id);
}

export async function updateEscalationStatus(escalationId: string, action: "approve" | "reject", resolutionNote = "") {
  await postJson(`/api/escalations/${escalationId}/actions/${action}`, {
    actor_id: "agent_allocator",
    resolution_note: resolutionNote
  });
}

export async function runSupervisorPass(allocateLimit?: number) {
  const payload = await postJson<SupervisorRunResponse>("/api/supervisor/run", {
    allocate_limit: allocateLimit ?? null,
    project_id: getSelectedProjectId()
  });
  return payload as SupervisorRunResponse;
}

export async function runOrchestratorPass(allocateLimit?: number, providerJobLimit = 2, autoLaunchAssignedWork = false) {
  const payload = await postJson<OrchestratorRunResponse>("/api/orchestrator/run", {
    allocate_limit: allocateLimit ?? null,
    provider_job_limit: providerJobLimit,
    auto_launch_assigned_work: autoLaunchAssignedWork,
    project_id: getSelectedProjectId()
  });
  return payload as OrchestratorRunResponse;
}

export async function rescanBrownfieldProject(projectId: string) {
  const payload = await postJson<{
    project_id: string;
    review_status: string;
    drift?: {
      detected?: boolean;
      summary?: string;
      changes?: string[];
    };
  }>(`/api/projects/${projectId}/actions/rescan-brownfield`, {
    actor_id: "agent_allocator"
  });
  return payload as {
    project_id: string;
    review_status: string;
    drift?: {
      detected?: boolean;
      summary?: string;
      changes?: string[];
    };
  };
}

export async function assignNextTask(agentId: string) {
  const payload = await postJson<{ agent_id: string; task_id: string | null; assigned: boolean; task_title?: string }>(
    `/api/agents/${agentId}/actions/assign-next`,
    { actor_id: "agent_allocator" }
  );
  return payload as { agent_id: string; task_id: string | null; assigned: boolean; task_title?: string };
}

export async function recoverAgent(agentId: string) {
  const payload = await postJson<{ agent_id: string; status: string }>(`/api/agents/${agentId}/actions/recover`, {
    actor_id: "agent_allocator"
  });
  return payload as { agent_id: string; status: string };
}
