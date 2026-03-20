import type { ReactNode } from "react";
import type { CodexIssueScopeState, CodexQueueFilter, CodexSavedScope } from "../lib/codexIssueScopes";

type Option = {
  id: string;
  label: string;
};

const PRIORITY_OPTIONS = [
  { value: "", label: "Any priority" },
  { value: "50", label: "Medium+" },
  { value: "75", label: "High+" },
  { value: "90", label: "Critical only" },
];

const QUEUE_FILTER_OPTIONS: Array<{ value: CodexQueueFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "attention", label: "Attention" },
  { value: "active", label: "Active" },
  { value: "review", label: "Review" },
  { value: "blocked", label: "Blocked" },
];

export function CodexIssueScopeToolbar({
  leading,
  scope,
  savedScopes,
  agentOptions,
  goalOptions,
  onScopeChange,
  onReset,
  onApplySaved,
  onSaveCurrent,
  onDeleteSaved,
}: {
  leading?: ReactNode;
  scope: CodexIssueScopeState;
  savedScopes: CodexSavedScope[];
  agentOptions: Option[];
  goalOptions: Option[];
  onScopeChange: (next: Partial<CodexIssueScopeState>) => void;
  onReset: () => void;
  onApplySaved: (scopeId: string) => void;
  onSaveCurrent: (label: string) => void;
  onDeleteSaved: (scopeId: string) => void;
}) {
  function handleSave() {
    const label = window.prompt("Save current scope as", "");
    if (!label) {
      return;
    }
    onSaveCurrent(label);
  }

  return (
    <div className="codex-scope-toolbar codex-panel">
      <div className="codex-scope-toolbar__top">
        <div className="codex-scope-toolbar__leading">{leading}</div>
        <div className="codex-chip-row">
          {QUEUE_FILTER_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={`codex-chip ${scope.queueFilter === option.value ? "codex-chip--active" : ""}`}
              onClick={() => onScopeChange({ queueFilter: option.value })}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <div className="codex-scope-toolbar__filters">
        <label className="codex-field">
          <span>Search</span>
          <input
            type="search"
            value={scope.search}
            onChange={(event) => onScopeChange({ search: event.target.value })}
            placeholder="Issue, title, goal, agent, state"
          />
        </label>

        <label className="codex-field">
          <span>Goal</span>
          <select value={scope.goalId ?? ""} onChange={(event) => onScopeChange({ goalId: event.target.value || null })}>
            <option value="">All goals</option>
            {goalOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="codex-field">
          <span>Owner</span>
          <select value={scope.agentId ?? ""} onChange={(event) => onScopeChange({ agentId: event.target.value || null })}>
            <option value="">All agents</option>
            {agentOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="codex-field">
          <span>Priority</span>
          <select
            value={scope.priorityMin != null ? String(scope.priorityMin) : ""}
            onChange={(event) =>
              onScopeChange({ priorityMin: event.target.value ? Number(event.target.value) : null })
            }
          >
            {PRIORITY_OPTIONS.map((option) => (
              <option key={option.value || "all"} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <div className="codex-scope-toolbar__saved">
          <label className="codex-field">
            <span>Saved views</span>
            <select defaultValue="" onChange={(event) => event.target.value && onApplySaved(event.target.value)}>
              <option value="">Load saved view</option>
              {savedScopes.map((scopeItem) => (
                <option key={scopeItem.id} value={scopeItem.id}>
                  {scopeItem.label}
                </option>
              ))}
            </select>
          </label>
          <div className="codex-page__actions">
            <button type="button" className="codex-button" onClick={handleSave}>
              Save current view
            </button>
            {savedScopes.length ? (
              <button
                type="button"
                className="codex-button"
                onClick={() => onDeleteSaved(savedScopes[savedScopes.length - 1].id)}
              >
                Delete latest
              </button>
            ) : null}
            <button type="button" className="codex-button" onClick={onReset}>
              Reset
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
