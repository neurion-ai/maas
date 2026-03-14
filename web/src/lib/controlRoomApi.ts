import type {
  ActivityItem,
  AgentRosterResponse,
  AlertsResponse,
  GoalTreeResponse,
  LiveSnapshot,
  OverviewResponse
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
  ]
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

const ALERTS_FALLBACK: AlertsResponse = {
  alerts: [
    {
      alert_id: "alert_provider_pending",
      severity: "warning",
      title: "Provider adapters pending",
      description: "Runtime adapters are still blocked behind lifecycle implementation.",
      status: "open",
      created_at: new Date().toISOString()
    }
  ],
  grouped: { open: [], acknowledged: [], resolved: [] },
  summary: {
    open: 1,
    acknowledged: 0,
    resolved: 0,
    critical_open: 0
  }
};

const LIVE_FALLBACK: LiveSnapshot = {
  generated_at: new Date().toISOString(),
  counts: {
    tasks_in_progress: 2,
    tasks_review: 1,
    alerts_open: 1,
    agents_running: 2
  },
  revision: {}
};

async function fetchJson<T>(path: string, fallback: T): Promise<T> {
  try {
    const response = await fetch(path);
    if (!response.ok) {
      throw new Error(`Unexpected status: ${response.status}`);
    }
    const payload = (await response.json()) as T;
    lastSuccessfulResponses.set(path, payload);
    return payload;
  } catch {
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

export function fetchAlerts() {
  return fetchJson<AlertsResponse>("/api/alerts", ALERTS_FALLBACK);
}

export function fetchLiveSnapshot() {
  return fetchJson<LiveSnapshot>("/api/live", LIVE_FALLBACK);
}

async function postJson(path: string, body: Record<string, string>) {
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
}

export async function updateAlertStatus(alertId: string, action: "acknowledge" | "resolve") {
  await postJson(`/api/alerts/${alertId}/actions/${action}`, { actor_id: "agent_allocator" });
}
