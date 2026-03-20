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

type StoredIssueScopes = {
  current: CodexIssueScopeState;
  saved: CodexSavedScope[];
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

function storageKey(projectId: string | null, namespace: string) {
  return `${SCOPE_STORAGE_PREFIX}${namespace}:${projectId ?? "global"}`;
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

function readStoredScopes(projectId: string | null, namespace: string): StoredIssueScopes {
  try {
    const raw = window.localStorage.getItem(storageKey(projectId, namespace));
    if (!raw) {
      return { current: { ...DEFAULT_CODEX_ISSUE_SCOPE }, saved: [] };
    }
    const parsed = JSON.parse(raw) as Partial<StoredIssueScopes>;
    return {
      current: normalizeScope(parsed.current),
      saved: Array.isArray(parsed.saved)
        ? parsed.saved
            .filter((item): item is CodexSavedScope => Boolean(item && typeof item.id === "string" && typeof item.label === "string"))
            .map((item) => ({
              id: item.id,
              label: item.label,
              scope: normalizeScope(item.scope),
            }))
        : [],
    };
  } catch {
    return { current: { ...DEFAULT_CODEX_ISSUE_SCOPE }, saved: [] };
  }
}

function writeStoredScopes(projectId: string | null, namespace: string, value: StoredIssueScopes) {
  const normalized: StoredIssueScopes = {
    current: normalizeScope(value.current),
    saved: value.saved.map((item) => ({
      id: item.id,
      label: item.label,
      scope: normalizeScope(item.scope),
    })),
  };
  window.localStorage.setItem(storageKey(projectId, namespace), JSON.stringify(normalized));
  window.dispatchEvent(new CustomEvent(SCOPE_EVENT, { detail: { projectId, namespace, value: normalized } }));
}

export function useCodexIssueScope(projectId: string | null, namespace = "shared") {
  const [stored, setStored] = useState<StoredIssueScopes>(() => readStoredScopes(projectId, namespace));

  useEffect(() => {
    setStored(readStoredScopes(projectId, namespace));
  }, [projectId, namespace]);

  useEffect(() => {
    function handleScopeChange(event: Event) {
      const customEvent = event as CustomEvent<{ projectId: string | null; namespace: string; value: StoredIssueScopes }>;
      if ((customEvent.detail?.projectId ?? null) === projectId && customEvent.detail?.namespace === namespace) {
        setStored(customEvent.detail.value);
      }
    }
    function handleStorage(event: StorageEvent) {
      if (event.key === storageKey(projectId, namespace)) {
        setStored(readStoredScopes(projectId, namespace));
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
    const updated = { ...stored, current: normalizeScope({ ...stored.current, ...next }) };
    setStored(updated);
    writeStoredScopes(projectId, namespace, updated);
  };

  const applySavedScope = (scopeId: string) => {
    const selected = stored.saved.find((item) => item.id === scopeId);
    if (!selected) {
      return;
    }
    const updated = { ...stored, current: normalizeScope(selected.scope) };
    setStored(updated);
    writeStoredScopes(projectId, namespace, updated);
  };

  const saveCurrentScope = (label: string) => {
    const cleanedLabel = label.trim();
    if (!cleanedLabel) {
      return;
    }
    const id = cleanedLabel.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || `scope-${Date.now()}`;
    const existing = stored.saved.filter((item) => item.id !== id);
    const updated = {
      ...stored,
      saved: [...existing, { id, label: cleanedLabel, scope: normalizeScope(stored.current) }],
    };
    setStored(updated);
    writeStoredScopes(projectId, namespace, updated);
  };

  const deleteSavedScope = (scopeId: string) => {
    const updated = {
      ...stored,
      saved: stored.saved.filter((item) => item.id !== scopeId),
    };
    setStored(updated);
    writeStoredScopes(projectId, namespace, updated);
  };

  const resetScope = () => {
    const updated = { ...stored, current: { ...DEFAULT_CODEX_ISSUE_SCOPE } };
    setStored(updated);
    writeStoredScopes(projectId, namespace, updated);
  };

  return {
    scope: stored.current,
    savedScopes: stored.saved,
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
