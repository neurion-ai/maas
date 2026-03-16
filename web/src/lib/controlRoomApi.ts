import type {
  ActivityItem,
  AgentRosterResponse,
  AlertOperatorAction,
  AlertsResponse,
  ArtifactsResponse,
  DismissQuarantineEntryResponse,
  EscalationsResponse,
  FailureOperatorAction,
  FailuresResponse,
  GoalTreeResponse,
  LiveSnapshot,
  OverviewResponse,
  ProvidersResponse,
  QuarantineQueueResponse,
  ReopenQuarantineEntryResponse,
  RestoreAndRequeueQuarantineEntryResponse,
  RestoreFailureArtifactsResponse,
  RestoreQuarantineEntryResponse,
  SupervisorRunResponse
} from "../types";

const lastSuccessfulResponses = new Map<string, unknown>();

const OVERVIEW_FALLBACK: OverviewResponse = {
  project: {
    project_id: "proj_fallback",
    name: "MAAS Demo Workspace",
    description: "Fallback overview while the API is unavailable.",
    project_type: "custom"
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
        last_run_at: null
      },
      recent_runs: [],
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
        last_run_at: null
      },
      recent_runs: [],
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
        last_run_at: null
      },
      recent_runs: [],
      notes: "Simulated API-style adapter with normalized runtime phase reporting."
    }
  ],
  run_targets: []
};

async function fetchJson<T>(
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

export function fetchOverview() {
  return fetchJson<OverviewResponse>("/api/overview", OVERVIEW_FALLBACK);
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

export function fetchArtifacts(signal?: AbortSignal, onFallback?: () => void) {
  return fetchJson<ArtifactsResponse>("/api/artifacts", ARTIFACTS_FALLBACK, signal, onFallback);
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

export async function recoverAndRequeueTask(taskId: string) {
  const payload = await postJson(`/api/tasks/${taskId}/actions/recover-and-requeue`, {
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

export async function setProviderMode(providerId: string, mode: string) {
  const payload = await postJson(`/api/providers/${providerId}/actions/set-mode`, {
    actor_id: "agent_allocator",
    mode
  });
  return payload;
}

export async function setProviderSettings(providerId: string, settings: Record<string, string | number>) {
  const payload = await postJson(`/api/providers/${providerId}/actions/set-settings`, {
    actor_id: "agent_allocator",
    settings
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
    allocate_limit: allocateLimit ?? null
  });
  return payload as SupervisorRunResponse;
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
