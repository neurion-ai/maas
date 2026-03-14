import type { BoardColumnKey, BoardFiltersInput, BoardResponse, FilterOption } from "../types";

const DEFAULT_ACTOR_ID = "agent_allocator";

const COLUMN_TITLES: Record<BoardColumnKey, string> = {
  planned: "Planned",
  ready: "Ready",
  in_progress: "In Progress",
  review: "Review",
  blocked: "Blocked",
  done: "Done",
  cancelled: "Cancelled"
};

const FALLBACK_BOARD: BoardResponse = {
  generated_at: new Date().toISOString(),
  summary: {
    total_tasks: 8,
    active_agents: 3,
    blocked_tasks: 1,
    review_tasks: 1
  },
  columns: [
    {
      key: "planned",
      title: COLUMN_TITLES.planned,
      tasks: [
        {
          task_id: "task_planned_dashboard_filters",
          title: "Add board filters for goal and agent focus",
          status: "planned",
          priority: 72,
          age_hours: 5.5,
          progress_pct: 0,
          goal: {
            id: "goal_dashboard_v1",
            title: "Dashboard and Kanban V1"
          }
        }
      ]
    },
    {
      key: "ready",
      title: COLUMN_TITLES.ready,
      tasks: [
        {
          task_id: "task_ready_seed_data",
          title: "Seed a greenfield project backlog into the board",
          status: "ready",
          priority: 81,
          age_hours: 2.2,
          progress_pct: 0,
          goal: {
            id: "goal_onboarding",
            title: "Greenfield onboarding"
          }
        }
      ]
    },
    {
      key: "in_progress",
      title: COLUMN_TITLES.in_progress,
      tasks: [
        {
          task_id: "task_live_runtime_adapter",
          title: "Wire lifecycle events into the runtime adapter layer",
          status: "in_progress",
          priority: 93,
          progress_pct: 68,
          heartbeat_age_seconds: 11,
          age_hours: 1.3,
          goal: {
            id: "goal_runtime",
            title: "Runtime lifecycle"
          },
          agent: {
            id: "agent_runtime",
            name: "Runtime Operator",
            status: "running"
          }
        },
        {
          task_id: "task_live_board_api",
          title: "Expose a task-first Kanban payload at /api/board",
          status: "in_progress",
          priority: 89,
          progress_pct: 44,
          heartbeat_age_seconds: 24,
          age_hours: 0.8,
          goal: {
            id: "goal_board_surface",
            title: "Operational board"
          },
          agent: {
            id: "agent_api",
            name: "API Steward",
            status: "running"
          }
        }
      ]
    },
    {
      key: "review",
      title: COLUMN_TITLES.review,
      tasks: [
        {
          task_id: "task_review_schema",
          title: "Review initial SQLite schema for board-first states",
          status: "review",
          priority: 88,
          progress_pct: 100,
          heartbeat_age_seconds: 54,
          age_hours: 0.6,
          review_state: "awaiting approval",
          goal: {
            id: "goal_core_kernel",
            title: "Core kernel and scaffold"
          },
          agent: {
            id: "agent_schema",
            name: "Schema Architect",
            status: "idle"
          }
        }
      ]
    },
    {
      key: "blocked",
      title: COLUMN_TITLES.blocked,
      tasks: [
        {
          task_id: "task_blocked_provider_keys",
          title: "Validate Codex adapter against live credentials",
          status: "blocked",
          priority: 67,
          progress_pct: 15,
          age_hours: 12.1,
          goal: {
            id: "goal_runtime",
            title: "Runtime lifecycle"
          },
          agent: {
            id: "agent_integrations",
            name: "Integrations Lead",
            status: "blocked"
          },
          review_state: "waiting on secrets"
        }
      ]
    },
    {
      key: "done",
      title: COLUMN_TITLES.done,
      tasks: [
        {
          task_id: "task_done_board_contract",
          title: "Define the board response contract",
          status: "done",
          priority: 75,
          progress_pct: 100,
          heartbeat_age_seconds: 300,
          age_hours: 3.8,
          goal: {
            id: "goal_board_surface",
            title: "Operational board"
          },
          agent: {
            id: "agent_product",
            name: "Product Synthesizer",
            status: "completed"
          }
        }
      ]
    },
    {
      key: "cancelled",
      title: COLUMN_TITLES.cancelled,
      tasks: []
    }
  ],
  filters: ["search", "blocked_only", "review_only", "priority", "agent", "goal"]
};

function deriveFilterOptions(payload: BoardResponse): BoardResponse["filter_options"] {
  const agents = new Map<string, string>();
  const goals = new Map<string, string>();

  payload.columns.forEach((column) => {
    column.tasks.forEach((task) => {
      if (task.agent?.id && task.agent.name) {
        agents.set(task.agent.id, task.agent.name);
      }
      if (task.goal?.id && task.goal.title) {
        goals.set(task.goal.id, task.goal.title);
      }
    });
  });

  const toOptions = (entries: Map<string, string>): FilterOption[] =>
    Array.from(entries.entries()).map(([id, label]) => ({ id, label }));

  return {
    agents: toOptions(agents),
    goals: toOptions(goals)
  };
}

function normalizeBoard(payload: BoardResponse): BoardResponse {
  const columns = payload.columns.map((column) => ({
    ...column,
    title: column.title || COLUMN_TITLES[column.key]
  }));

  return {
    ...payload,
    columns,
    filters: payload.filters ?? FALLBACK_BOARD.filters,
    filter_options: payload.filter_options ?? deriveFilterOptions({ ...payload, columns })
  };
}

function buildBoardQuery(filters: BoardFiltersInput) {
  const query = new URLSearchParams();

  if (filters.search) {
    query.set("search", filters.search);
  }
  if (filters.blockedOnly) {
    query.set("blocked_only", "true");
  }
  if (filters.reviewOnly) {
    query.set("review_only", "true");
  }
  if (filters.priorityMin && filters.priorityMin > 0) {
    query.set("priority_min", String(filters.priorityMin));
  }
  if (filters.agentId) {
    query.set("agent_id", filters.agentId);
  }
  if (filters.goalId) {
    query.set("goal_id", filters.goalId);
  }

  return query.toString();
}

async function postJson(path: string, body: Record<string, string | number>) {
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

export async function fetchBoard(filters: BoardFiltersInput = {}, signal?: AbortSignal): Promise<BoardResponse> {
  try {
    const query = buildBoardQuery(filters);
    const response = await fetch(query ? `/api/board?${query}` : "/api/board", { signal });
    if (!response.ok) {
      throw new Error(`Unexpected status: ${response.status}`);
    }

    const payload = (await response.json()) as BoardResponse;
    return normalizeBoard(payload);
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw error;
    }
    return normalizeBoard(FALLBACK_BOARD);
  }
}

export async function reviewTask(taskId: string, decision: "approve" | "reject") {
  await postJson(`/api/tasks/${taskId}/actions/review`, {
    actor_id: DEFAULT_ACTOR_ID,
    decision
  });
}

export async function setAgentState(agentId: string, action: "pause" | "resume") {
  await postJson(`/api/agents/${agentId}/actions/${action}`, {
    actor_id: DEFAULT_ACTOR_ID
  });
}

export async function reprioritizeTask(taskId: string, priority: number) {
  await postJson(`/api/tasks/${taskId}/actions/reprioritize`, {
    actor_id: DEFAULT_ACTOR_ID,
    priority
  });
}

export async function reassignTask(taskId: string, agentId: string) {
  await postJson(`/api/tasks/${taskId}/actions/reassign`, {
    actor_id: DEFAULT_ACTOR_ID,
    agent_id: agentId
  });
}

export async function haltTask(taskId: string) {
  await postJson(`/api/tasks/${taskId}/actions/halt`, {
    actor_id: DEFAULT_ACTOR_ID
  });
}

export async function recoverTask(taskId: string) {
  await postJson(`/api/tasks/${taskId}/actions/recover`, {
    actor_id: DEFAULT_ACTOR_ID
  });
}
