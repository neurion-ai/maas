import type {
  ActivityItem,
  AgentRosterResponse,
  AlertOperatorAction,
  AlertsResponse,
  ArtifactComparisonResponse,
  ArtifactDetail,
  ArtifactPurgeResponse,
  ArtifactsResponse,
  DismissQuarantineEntryResponse,
  EscalationsResponse,
  FailureOperatorAction,
  FailuresResponse,
  GoalTreeResponse,
  LiveSnapshot,
  OverviewResponse,
  OrchestratorRunResponse,
  PortfolioResponse,
  ProjectActionResponse,
  ProjectCreateRequest,
  ProjectCreateResponse,
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
  SupervisorRunResponse
} from "../types";
import { appendProjectScope, getSelectedProjectId } from "./projectScope";

const lastSuccessfulResponses = new Map<string, unknown>();

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
    queued_provider_jobs: 0
  },
  projects: [],
  command_center: {
    open_escalations: [],
    urgent_alerts: [],
    open_dead_letter_entries: [],
    queued_provider_jobs: []
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
  onFallback?: () => void
): Promise<T> {
  const scopedPath = appendProjectScope(path);
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

export function fetchPortfolio() {
  return fetchGlobalJson<PortfolioResponse>("/api/portfolio", PORTFOLIO_FALLBACK);
}

export async function createProject(payload: ProjectCreateRequest) {
  const response = await postJson<ProjectCreateResponse>("/api/projects", payload);
  return response as ProjectCreateResponse;
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
  payload: { queue_mode: "running" | "draining" | "paused"; max_running_jobs: number }
) {
  return postJson(`/api/projects/${projectId}/actions/update-provider-capacity`, {
    actor_id: "agent_allocator",
    queue_mode: payload.queue_mode,
    max_running_jobs: payload.max_running_jobs
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

export async function refreshRepoPlan(projectId: string) {
  return postJson(`/api/projects/${projectId}/actions/refresh-repo-plan`, {
    actor_id: "agent_allocator"
  });
}

export function fetchOverview() {
  return fetchJson<OverviewResponse>("/api/overview", OVERVIEW_FALLBACK);
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

export function fetchAgentRoster() {
  return fetchJson<AgentRosterResponse>("/api/agents", ROSTER_FALLBACK);
}

export function fetchActivity() {
  return fetchJson<ActivityItem[]>("/api/activity", ACTIVITY_FALLBACK);
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
  const response = await fetch(`/api/artifacts/${artifactId}`, { signal });
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Unexpected status: ${response.status}`);
  }
  return (await response.json()) as ArtifactDetail;
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

export function fetchAlerts() {
  return fetchJson<AlertsResponse>("/api/alerts", ALERTS_FALLBACK);
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

export function fetchProviders() {
  return fetchJson<ProvidersResponse>("/api/providers", PROVIDERS_FALLBACK);
}

export function fetchRecoveryPolicy() {
  return fetchJson<RecoveryPolicyResponse>("/api/recovery-policy", RECOVERY_POLICY_FALLBACK);
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

type JsonPrimitive = string | number | boolean | null;
type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };

async function postJson<T>(path: string, body: Record<string, JsonValue | undefined>): Promise<T | null> {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    throw new Error(`Unexpected status: ${response.status}`);
  }

  if (response.status === 204) {
    return null;
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

export async function runOrchestratorPass(allocateLimit?: number, providerJobLimit = 2) {
  const payload = await postJson<OrchestratorRunResponse>("/api/orchestrator/run", {
    allocate_limit: allocateLimit ?? null,
    provider_job_limit: providerJobLimit,
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
