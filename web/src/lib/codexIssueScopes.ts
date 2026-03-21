import { useEffect, useMemo, useState } from "react";
import type { BoardGoal, BoardTask } from "../types";

const SCOPE_STORAGE_PREFIX = "maas:codex-issue-scope:";
const SCOPE_EVENT = "maas:codex-issue-scope-changed";

export type CodexQueueFilter = "all" | "attention" | "review" | "blocked" | "active";

export type CodexIssueScopeState = {
  search: string;
  goalId: string | null;
  agentId: string | null;
  priorityMin: number | null;
  queueFilter: CodexQueueFilter;
};

export type CodexSavedScope = {
  id: string;
  label: string;
  scope: CodexIssueScopeState;
};

type AgentOption = {
  id: string;
  label: string;
};

type GoalOption = BoardGoal & { label: string };

export const DEFAULT_CODEX_ISSUE_SCOPE: CodexIssueScopeState = {
  search: "",
  goalId: null,
  agentId: null,
  priorityMin: null,
  queueFilter: "all",
};

function currentStorageKey(projectId: string | null, namespace: string) {
  return `${SCOPE_STORAGE_PREFIX}current:${namespace}:${projectId ?? "global"}`;
}

function savedStorageKey(projectId: string | null) {
  return `${SCOPE_STORAGE_PREFIX}saved:${projectId ?? "global"}`;
}

function normalizeScope(value?: Partial<CodexIssueScopeState> | null): CodexIssueScopeState {
  const queueFilter = value?.queueFilter;
  return {
    search: typeof value?.search === "string" ? value.search : "",
    goalId: typeof value?.goalId === "string" && value.goalId.trim() ? value.goalId : null,
    agentId: typeof value?.agentId === "string" && value.agentId.trim() ? value.agentId : null,
    priorityMin: typeof value?.priorityMin === "number" ? value.priorityMin : null,
    queueFilter:
      queueFilter === "attention" || queueFilter === "review" || queueFilter === "blocked" || queueFilter === "active"
        ? queueFilter
        : "all",
  };
}

function readCurrentScope(projectId: string | null, namespace: string): CodexIssueScopeState {
  try {
    const raw = window.localStorage.getItem(currentStorageKey(projectId, namespace));
    if (!raw) {
      return { ...DEFAULT_CODEX_ISSUE_SCOPE };
    }
    return normalizeScope(JSON.parse(raw) as Partial<CodexIssueScopeState>);
  } catch {
    return { ...DEFAULT_CODEX_ISSUE_SCOPE };
  }
}

function readSavedScopes(projectId: string | null): CodexSavedScope[] {
  try {
    const raw = window.localStorage.getItem(savedStorageKey(projectId));
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed)
      ? parsed
          .filter((item): item is CodexSavedScope => Boolean(item && typeof item === "object" && typeof (item as CodexSavedScope).id === "string" && typeof (item as CodexSavedScope).label === "string"))
          .map((item) => ({
            id: item.id,
            label: item.label,
            scope: normalizeScope(item.scope),
          }))
      : [];
  } catch {
    return [];
  }
}

function writeCurrentScope(projectId: string | null, namespace: string, value: CodexIssueScopeState) {
  const normalized = normalizeScope(value);
  window.localStorage.setItem(currentStorageKey(projectId, namespace), JSON.stringify(normalized));
  window.dispatchEvent(new CustomEvent(SCOPE_EVENT, { detail: { projectId, namespace, kind: "current", value: normalized } }));
}

function writeSavedScopes(projectId: string | null, saved: CodexSavedScope[]) {
  const normalized = saved.map((item) => ({
    id: item.id,
    label: item.label,
    scope: normalizeScope(item.scope),
  }));
  window.localStorage.setItem(savedStorageKey(projectId), JSON.stringify(normalized));
  window.dispatchEvent(new CustomEvent(SCOPE_EVENT, { detail: { projectId, kind: "saved", value: normalized } }));
}

export function useCodexIssueScope(projectId: string | null, namespace = "shared") {
  const [current, setCurrent] = useState<CodexIssueScopeState>(() => readCurrentScope(projectId, namespace));
  const [saved, setSaved] = useState<CodexSavedScope[]>(() => readSavedScopes(projectId));

  useEffect(() => {
    setCurrent(readCurrentScope(projectId, namespace));
    setSaved(readSavedScopes(projectId));
  }, [projectId, namespace]);

  useEffect(() => {
    function handleScopeChange(event: Event) {
      const customEvent = event as CustomEvent<{
        projectId: string | null;
        namespace?: string;
        kind: "current" | "saved";
        value: CodexIssueScopeState | CodexSavedScope[];
      }>;
      if ((customEvent.detail?.projectId ?? null) !== projectId) {
        return;
      }
      if (customEvent.detail.kind === "current" && customEvent.detail.namespace === namespace) {
        setCurrent(normalizeScope(customEvent.detail.value as CodexIssueScopeState));
      }
      if (customEvent.detail.kind === "saved") {
        setSaved(readSavedScopes(projectId));
      }
    }
    function handleStorage(event: StorageEvent) {
      if (event.key === currentStorageKey(projectId, namespace)) {
        setCurrent(readCurrentScope(projectId, namespace));
      }
      if (event.key === savedStorageKey(projectId)) {
        setSaved(readSavedScopes(projectId));
      }
    }
    window.addEventListener(SCOPE_EVENT, handleScopeChange);
    window.addEventListener("storage", handleStorage);
    return () => {
      window.removeEventListener(SCOPE_EVENT, handleScopeChange);
      window.removeEventListener("storage", handleStorage);
    };
  }, [projectId, namespace]);

  const setScope = (next: Partial<CodexIssueScopeState>) => {
    const updated = normalizeScope({ ...current, ...next });
    setCurrent(updated);
    writeCurrentScope(projectId, namespace, updated);
  };

  const applySavedScope = (scopeId: string) => {
    const selected = saved.find((item) => item.id === scopeId);
    if (!selected) {
      return;
    }
    const updated = normalizeScope(selected.scope);
    setCurrent(updated);
    writeCurrentScope(projectId, namespace, updated);
  };

  const saveCurrentScope = (label: string) => {
    const cleanedLabel = label.trim();
    if (!cleanedLabel) {
      return;
    }
    const id = cleanedLabel.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || `scope-${Date.now()}`;
    const existing = saved.filter((item) => item.id !== id);
    const updated = [...existing, { id, label: cleanedLabel, scope: normalizeScope(current) }];
    setSaved(updated);
    writeSavedScopes(projectId, updated);
  };

  const deleteSavedScope = (scopeId: string) => {
    const updated = saved.filter((item) => item.id !== scopeId);
    setSaved(updated);
    writeSavedScopes(projectId, updated);
  };

  const resetScope = () => {
    const updated = { ...DEFAULT_CODEX_ISSUE_SCOPE };
    setCurrent(updated);
    writeCurrentScope(projectId, namespace, updated);
  };

  return {
    scope: current,
    savedScopes: saved,
    setScope,
    applySavedScope,
    saveCurrentScope,
    deleteSavedScope,
    resetScope,
  };
}

function matchesQueueFilter(task: BoardTask, queueFilter: CodexQueueFilter) {
  if (queueFilter === "all") {
    return true;
  }
  if (queueFilter === "attention") {
    return task.status === "review" || task.status === "blocked";
  }
  if (queueFilter === "review") {
    return task.status === "review";
  }
  if (queueFilter === "blocked") {
    return task.status === "blocked";
  }
  return task.status === "in_progress" || task.status === "assigned";
}

export function filterCodexTasks(tasks: BoardTask[], scope: CodexIssueScopeState) {
  const search = scope.search.trim().toLowerCase();
  return tasks.filter((task) => {
    if (!matchesQueueFilter(task, scope.queueFilter)) {
      return false;
    }
    if (scope.goalId && task.goal?.id !== scope.goalId) {
      return false;
    }
    if (scope.agentId && task.agent?.id !== scope.agentId) {
      return false;
    }
    if (scope.priorityMin != null && task.priority < scope.priorityMin) {
      return false;
    }
    if (!search) {
      return true;
    }
    const haystack = [
      task.issue_key,
      task.task_id,
      task.title,
      task.description,
      task.goal?.title,
      task.agent?.name,
      task.review_state,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(search);
  });
}

export function deriveCodexScopeOptions(tasks: BoardTask[]): {
  agents: AgentOption[];
  goals: GoalOption[];
} {
  const agentMap = new Map<string, AgentOption>();
  const goalMap = new Map<string, GoalOption>();
  tasks.forEach((task) => {
    if (task.agent?.id) {
      agentMap.set(task.agent.id, { id: task.agent.id, label: task.agent.name });
    }
    if (task.goal?.id) {
      goalMap.set(task.goal.id, { ...task.goal, label: task.goal.title });
    }
  });
  return {
    agents: [...agentMap.values()].sort((left, right) => left.label.localeCompare(right.label)),
    goals: [...goalMap.values()].sort((left, right) => left.label.localeCompare(right.label)),
  };
}

export function useCodexScopeOptions(tasks: BoardTask[]) {
  return useMemo(() => deriveCodexScopeOptions(tasks), [tasks]);
}
