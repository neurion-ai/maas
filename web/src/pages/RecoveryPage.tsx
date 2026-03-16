import { useEffect, useState } from "react";
import { StatCard } from "../components/StatCard";
import {
  fetchRecoveryPolicy,
  releaseTaskRetryBackoff,
  resetTaskRetryState,
  setRecoveryPolicy,
  setTaskRetryLimit
} from "../lib/controlRoomApi";
import { useLivePulse } from "../lib/useLivePulse";
import type { RecoveryPolicyResponse, RecoveryPolicySettings, RecoveryTaskItem } from "../types";

type RecoveryDraft = Record<keyof RecoveryPolicySettings, string>;

const BOOLEAN_FIELDS: (keyof RecoveryPolicySettings)[] = [
  "auto_retry_timeout_sessions",
  "auto_retry_failed_sessions"
];

const NUMBER_FIELDS: (keyof RecoveryPolicySettings)[] = [
  "max_timed_out_retries",
  "max_failed_session_retries",
  "timed_out_retry_cooldown_seconds",
  "failed_session_retry_cooldown_seconds",
  "recover_and_requeue_cooldown_seconds",
  "retry_backoff_multiplier",
  "retry_backoff_max_seconds"
];

const RETRY_LIMIT_OPTIONS = [null, 0, 1, 2, 3, 5, 10] as const;

function buildDraft(
  payload: RecoveryPolicyResponse,
  current: RecoveryDraft | null,
  reset = false
): RecoveryDraft {
  const serverDraft: RecoveryDraft = {
    auto_retry_timeout_sessions: payload.policy.auto_retry_timeout_sessions ? "true" : "false",
    auto_retry_failed_sessions: payload.policy.auto_retry_failed_sessions ? "true" : "false",
    max_timed_out_retries: String(payload.policy.max_timed_out_retries),
    max_failed_session_retries: String(payload.policy.max_failed_session_retries),
    timed_out_retry_cooldown_seconds: String(payload.policy.timed_out_retry_cooldown_seconds),
    failed_session_retry_cooldown_seconds: String(payload.policy.failed_session_retry_cooldown_seconds),
    recover_and_requeue_cooldown_seconds: String(payload.policy.recover_and_requeue_cooldown_seconds),
    retry_backoff_multiplier: String(payload.policy.retry_backoff_multiplier),
    retry_backoff_max_seconds: String(payload.policy.retry_backoff_max_seconds)
  };

  if (!current || reset) {
    return serverDraft;
  }

  return Object.fromEntries(
    Object.keys(serverDraft).map((key) => [key, current[key as keyof RecoveryDraft] ?? serverDraft[key as keyof RecoveryDraft]])
  ) as RecoveryDraft;
}

function buildDefaultsDraft(defaults: RecoveryPolicySettings): RecoveryDraft {
  return {
    auto_retry_timeout_sessions: defaults.auto_retry_timeout_sessions ? "true" : "false",
    auto_retry_failed_sessions: defaults.auto_retry_failed_sessions ? "true" : "false",
    max_timed_out_retries: String(defaults.max_timed_out_retries),
    max_failed_session_retries: String(defaults.max_failed_session_retries),
    timed_out_retry_cooldown_seconds: String(defaults.timed_out_retry_cooldown_seconds),
    failed_session_retry_cooldown_seconds: String(defaults.failed_session_retry_cooldown_seconds),
    recover_and_requeue_cooldown_seconds: String(defaults.recover_and_requeue_cooldown_seconds),
    retry_backoff_multiplier: String(defaults.retry_backoff_multiplier),
    retry_backoff_max_seconds: String(defaults.retry_backoff_max_seconds)
  };
}

function previewLabel(items: { attempt: number; delay_seconds: number }[]) {
  if (!items.length) {
    return "Disabled";
  }
  return items.map((item) => `#${item.attempt}: ${item.delay_seconds}s`).join(" | ");
}

function formatRetryLimit(autoRetryLimit?: number | null) {
  return autoRetryLimit == null ? "Project default" : `${autoRetryLimit} max auto retries`;
}

function RecoveryTaskList({
  items,
  pendingTaskId,
  onRetryLimitChange,
  onPrimaryAction,
  primaryActionLabel,
  pendingPrimaryActionLabel
}: {
  items: RecoveryTaskItem[];
  pendingTaskId: string | null;
  onRetryLimitChange: (taskId: string, autoRetryLimit: number | null) => void;
  onPrimaryAction?: (taskId: string) => void;
  primaryActionLabel?: string;
  pendingPrimaryActionLabel?: string;
}) {
  return (
    <div className="data-list">
      {items.map((item) => (
        <div key={item.task_id} className="data-list__item">
          <div>
            <strong>{item.title}</strong>
            <p>
              {item.goal_title ?? "Unlinked goal"}
              {item.agent_name ? ` | ${item.agent_name}` : ""}
            </p>
            <p>
              Status: {item.status}
              {item.review_state ? ` | ${item.review_state}` : ""}
              {item.failure_count ? ` | ${item.failure_count} failures` : ""}
            </p>
            <p>
              Retry budget: {formatRetryLimit(item.auto_retry_limit)}
              {item.retry_count ? ` | ${item.retry_count} retries used` : ""}
              {item.last_retry_reason ? ` | last: ${item.last_retry_reason}` : ""}
            </p>
            {item.next_retry_at ? (
              <p>
                Next retry: {new Date(item.next_retry_at).toLocaleString()}
                {item.next_retry_reason ? ` (${item.next_retry_reason})` : ""}
              </p>
            ) : null}
          </div>
          <div className="data-list__meta">
            <span>P{item.priority}</span>
            {item.latest_failure_at ? <span>{new Date(item.latest_failure_at).toLocaleString()}</span> : null}
            {onPrimaryAction ? (
              <button
                type="button"
                className="task-action task-action--approve"
                disabled={pendingTaskId === item.task_id}
                onClick={() => onPrimaryAction(item.task_id)}
              >
                {pendingTaskId === item.task_id ? (pendingPrimaryActionLabel ?? "Working...") : (primaryActionLabel ?? "Run action")}
              </button>
            ) : null}
            <label className="task-inline-control">
              <span>Retry limit</span>
              <select
                value={item.auto_retry_limit == null ? "" : String(item.auto_retry_limit)}
                disabled={pendingTaskId === item.task_id}
                onChange={(event) =>
                  onRetryLimitChange(item.task_id, event.target.value === "" ? null : Number(event.target.value))
                }
              >
                {Array.from(new Set([...RETRY_LIMIT_OPTIONS, item.auto_retry_limit ?? null])).map((value) => (
                  <option key={value == null ? "default" : value} value={value == null ? "" : String(value)}>
                    {value == null ? "Project default" : value}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
      ))}
    </div>
  );
}

export function RecoveryPage() {
  const [recovery, setRecovery] = useState<RecoveryPolicyResponse | null>(null);
  const [draft, setDraft] = useState<RecoveryDraft | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingSave, setPendingSave] = useState(false);
  const [pendingTaskActionId, setPendingTaskActionId] = useState<string | null>(null);
  const livePulse = useLivePulse();

  useEffect(() => {
    let mounted = true;

    async function loadRecovery() {
      const payload = await fetchRecoveryPolicy();
      if (mounted) {
        setRecovery(payload);
        setDraft((current) => buildDraft(payload, current));
      }
    }

    void loadRecovery();
    return () => {
      mounted = false;
    };
  }, [livePulse]);

  async function reload(reset = false) {
    const payload = await fetchRecoveryPolicy();
    setRecovery(payload);
    setDraft((current) => buildDraft(payload, current, reset));
  }

  function updateDraft(field: keyof RecoveryPolicySettings, value: string) {
    setDraft((current) => (current ? { ...current, [field]: value } : current));
  }

  async function handleSave(nextDraft?: RecoveryDraft) {
    const currentDraft = nextDraft ?? draft;
    if (!currentDraft) {
      return;
    }

    const payload: Record<string, string | number | boolean> = {};
    BOOLEAN_FIELDS.forEach((field) => {
      payload[field] = currentDraft[field] === "true";
    });
    NUMBER_FIELDS.forEach((field) => {
      payload[field] = Number(currentDraft[field]);
    });

    setPendingSave(true);
    setNotice(null);
    try {
      await setRecoveryPolicy(payload);
      await reload(true);
      setNotice("Updated project recovery policy.");
    } catch {
      setNotice("Recovery policy update failed; keeping the previous policy in effect.");
    } finally {
      setPendingSave(false);
    }
  }

  async function handleResetToDefaults() {
    if (!recovery) {
      return;
    }
    const defaultsDraft = buildDefaultsDraft(recovery.defaults);
    await handleSave(defaultsDraft);
  }

  async function handleTaskRetryLimitChange(taskId: string, autoRetryLimit: number | null) {
    setPendingTaskActionId(taskId);
    setNotice(null);
    try {
      await setTaskRetryLimit(taskId, autoRetryLimit);
      await reload();
      setNotice(
        autoRetryLimit == null
          ? `Task ${taskId} now follows the project retry policy.`
          : `Task ${taskId} retry limit set to ${autoRetryLimit}.`
      );
    } catch {
      setNotice("Task retry limit update failed; keeping the current recovery snapshot under review.");
    } finally {
      setPendingTaskActionId(null);
    }
  }

  async function handleReleaseRetryBackoff(taskId: string) {
    setPendingTaskActionId(taskId);
    setNotice(null);
    try {
      const payload = await releaseTaskRetryBackoff(taskId);
      await reload();
      setNotice(`Released retry backoff for ${taskId}; task is now ${payload.status}.`);
    } catch {
      setNotice("Retry backoff release failed; keep the current recovery snapshot under review.");
    } finally {
      setPendingTaskActionId(null);
    }
  }

  async function handleResetRetryState(taskId: string) {
    setPendingTaskActionId(taskId);
    setNotice(null);
    try {
      const payload = await resetTaskRetryState(taskId);
      await reload();
      setNotice(`Reset retry state for ${taskId}; task is now ${payload.status}.`);
    } catch {
      setNotice("Retry state reset failed; keep the current recovery snapshot under review.");
    } finally {
      setPendingTaskActionId(null);
    }
  }

  const currentDraft = draft;

  return (
    <section className="control-page">
      <header className="page-hero">
        <div>
          <span className="eyebrow">Recovery</span>
          <h1>Retry policy and backoff controls</h1>
          <p>Inspect retry pressure, adjust timeout and failed-session retry policy, and preview the actual cooldown schedule operators are creating.</p>
        </div>
        {notice ? <p className="filters-panel__notice">{notice}</p> : null}
      </header>

      <section className="stats-grid">
        <StatCard label="Backoff tasks" value={recovery?.summary.retry_backoff_tasks ?? 0} tone="warn" />
        <StatCard label="Retry overrides" value={recovery?.summary.tasks_with_retry_overrides ?? 0} />
        <StatCard label="Retry history" value={recovery?.summary.tasks_with_retry_history ?? 0} />
        <StatCard label="Recoverable blocked" value={recovery?.summary.recoverable_blocked_tasks ?? 0} tone="warn" />
        <StatCard label="Open failure alerts" value={recovery?.summary.open_failure_alerts ?? 0} tone="warn" />
        <StatCard label="Repeated incidents" value={recovery?.summary.open_repeated_failure_alerts ?? 0} tone="warn" />
        <StatCard label="Quarantine open" value={recovery?.summary.open_quarantine_entries ?? 0} />
      </section>

      <section className="overview-grid">
        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Recovery policy</h2>
              <p>These settings control automatic timeout retries, failed-session retries, and the cooldown applied when operators recover and requeue blocked work.</p>
            </div>
          </header>
          {currentDraft ? (
            <div className="recovery-settings">
              <div className="filters-panel__grid">
                <label className="filter-field">
                  <span>Auto retry timeout sessions</span>
                  <select
                    value={currentDraft.auto_retry_timeout_sessions}
                    onChange={(event) => updateDraft("auto_retry_timeout_sessions", event.target.value)}
                  >
                    <option value="false">Disabled</option>
                    <option value="true">Enabled</option>
                  </select>
                </label>
                <label className="filter-field">
                  <span>Max timed-out retries</span>
                  <input
                    type="number"
                    min="0"
                    value={currentDraft.max_timed_out_retries}
                    onChange={(event) => updateDraft("max_timed_out_retries", event.target.value)}
                  />
                </label>
                <label className="filter-field">
                  <span>Timed-out cooldown seconds</span>
                  <input
                    type="number"
                    min="0"
                    value={currentDraft.timed_out_retry_cooldown_seconds}
                    onChange={(event) => updateDraft("timed_out_retry_cooldown_seconds", event.target.value)}
                  />
                </label>
                <label className="filter-field">
                  <span>Auto retry failed sessions</span>
                  <select
                    value={currentDraft.auto_retry_failed_sessions}
                    onChange={(event) => updateDraft("auto_retry_failed_sessions", event.target.value)}
                  >
                    <option value="false">Disabled</option>
                    <option value="true">Enabled</option>
                  </select>
                </label>
                <label className="filter-field">
                  <span>Max failed-session retries</span>
                  <input
                    type="number"
                    min="0"
                    value={currentDraft.max_failed_session_retries}
                    onChange={(event) => updateDraft("max_failed_session_retries", event.target.value)}
                  />
                </label>
                <label className="filter-field">
                  <span>Failed-session cooldown seconds</span>
                  <input
                    type="number"
                    min="0"
                    value={currentDraft.failed_session_retry_cooldown_seconds}
                    onChange={(event) => updateDraft("failed_session_retry_cooldown_seconds", event.target.value)}
                  />
                </label>
                <label className="filter-field">
                  <span>Recover + requeue cooldown</span>
                  <input
                    type="number"
                    min="0"
                    value={currentDraft.recover_and_requeue_cooldown_seconds}
                    onChange={(event) => updateDraft("recover_and_requeue_cooldown_seconds", event.target.value)}
                  />
                </label>
                <label className="filter-field">
                  <span>Backoff multiplier</span>
                  <input
                    type="number"
                    min="1"
                    value={currentDraft.retry_backoff_multiplier}
                    onChange={(event) => updateDraft("retry_backoff_multiplier", event.target.value)}
                  />
                </label>
                <label className="filter-field">
                  <span>Backoff max seconds</span>
                  <input
                    type="number"
                    min="0"
                    value={currentDraft.retry_backoff_max_seconds}
                    onChange={(event) => updateDraft("retry_backoff_max_seconds", event.target.value)}
                  />
                </label>
              </div>
              <div className="task-card__actions">
                <button type="button" className="task-action task-action--approve" disabled={pendingSave} onClick={() => void handleSave()}>
                  {pendingSave ? "Saving..." : "Save policy"}
                </button>
                <button
                  type="button"
                  className="task-action task-action--secondary"
                  disabled={pendingSave}
                  onClick={() => void handleResetToDefaults()}
                >
                  Reset to defaults
                </button>
              </div>
            </div>
          ) : null}
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Backoff preview</h2>
              <p>The preview shows the actual delay schedule that the current multiplier and cap will produce.</p>
            </div>
          </header>
          <div className="data-list">
            <div className="data-list__item">
              <div>
                <strong>Timed-out sessions</strong>
                <p>{previewLabel(recovery?.backoff_preview.timed_out_retry_delays ?? [])}</p>
              </div>
            </div>
            <div className="data-list__item">
              <div>
                <strong>Failed sessions</strong>
                <p>{previewLabel(recovery?.backoff_preview.failed_session_retry_delays ?? [])}</p>
              </div>
            </div>
            <div className="data-list__item">
              <div>
                <strong>Recover + requeue</strong>
                <p>{previewLabel(recovery?.backoff_preview.recover_and_requeue_delays ?? [])}</p>
              </div>
            </div>
          </div>
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Task retry overrides</h2>
              <p>Tasks that diverge from project policy. Use this to review and clear one-off retry exceptions without hunting through the board.</p>
            </div>
          </header>
          {(recovery?.task_retry_overrides ?? []).length ? (
            <RecoveryTaskList
              items={recovery?.task_retry_overrides ?? []}
              pendingTaskId={pendingTaskActionId}
              onRetryLimitChange={handleTaskRetryLimitChange}
            />
          ) : (
            <div className="data-list">
              <div className="data-list__item">
                <div>
                  <strong>No task overrides</strong>
                  <p>All tasks currently follow the project recovery policy.</p>
                </div>
              </div>
            </div>
          )}
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Retry history</h2>
              <p>Tasks that have already consumed automatic retries. Reset the task state here after manual intervention to restore the retry budget.</p>
            </div>
          </header>
          {(recovery?.task_retry_history ?? []).length ? (
            <RecoveryTaskList
              items={recovery?.task_retry_history ?? []}
              pendingTaskId={pendingTaskActionId}
              onRetryLimitChange={handleTaskRetryLimitChange}
              onPrimaryAction={(taskId) => void handleResetRetryState(taskId)}
              primaryActionLabel="Reset retry state"
              pendingPrimaryActionLabel="Resetting..."
            />
          ) : (
            <div className="data-list">
              <div className="data-list__item">
                <div>
                  <strong>No retry history</strong>
                  <p>No active tasks currently carry consumed retry budget.</p>
                </div>
              </div>
            </div>
          )}
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Active retry backoff</h2>
              <p>Tasks currently cooling down before another automatic or operator-triggered retry window opens.</p>
            </div>
          </header>
          {(recovery?.active_retry_backoff ?? []).length ? (
            <RecoveryTaskList
              items={recovery?.active_retry_backoff ?? []}
              pendingTaskId={pendingTaskActionId}
              onRetryLimitChange={handleTaskRetryLimitChange}
              onPrimaryAction={(taskId) => void handleReleaseRetryBackoff(taskId)}
              primaryActionLabel="Release backoff"
              pendingPrimaryActionLabel="Releasing..."
            />
          ) : (
            <div className="data-list">
              <div className="data-list__item">
                <div>
                  <strong>No active cooldowns</strong>
                  <p>No tasks are currently waiting on a retry backoff window.</p>
                </div>
              </div>
            </div>
          )}
        </article>

      </section>
    </section>
  );
}
