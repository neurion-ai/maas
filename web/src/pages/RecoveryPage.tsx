import { useEffect, useState } from "react";
import { StatCard } from "../components/StatCard";
import {
  dismissQuarantineEntry,
  finishTaskReplan,
  fetchRecoveryPolicy,
  markTaskForReplan,
  recoverAndRequeueTask,
  recoverTask,
  releaseTaskRetryBackoff,
  resetTaskRetryState,
  runAlertOperatorAction,
  restoreAndRequeueQuarantineEntry,
  restoreQuarantineEntry,
  setRecoveryPolicy,
  setTaskRetryLimit
} from "../lib/controlRoomApi";
import { useLivePulse } from "../lib/useLivePulse";
import type {
  AlertItem,
  QuarantineQueueItem,
  RecoveryPolicyResponse,
  RecoveryPolicySettings,
  RecoveryTaskItem,
  RepeatedFailureItem
} from "../types";

type RecoveryDraft = Record<keyof RecoveryPolicySettings, string>;

const BOOLEAN_FIELDS: (keyof RecoveryPolicySettings)[] = [
  "auto_retry_timeout_sessions",
  "auto_retry_failed_sessions",
  "auto_recover_blocked_tasks"
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
    auto_recover_blocked_tasks: payload.policy.auto_recover_blocked_tasks ? "true" : "false",
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
    auto_recover_blocked_tasks: defaults.auto_recover_blocked_tasks ? "true" : "false",
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
  pendingPrimaryActionLabel,
  onSecondaryAction,
  secondaryActionLabel,
  pendingSecondaryActionLabel
}: {
  items: RecoveryTaskItem[];
  pendingTaskId: string | null;
  onRetryLimitChange: (taskId: string, autoRetryLimit: number | null) => void;
  onPrimaryAction?: (taskId: string) => void;
  primaryActionLabel?: string;
  pendingPrimaryActionLabel?: string;
  onSecondaryAction?: (taskId: string) => void;
  secondaryActionLabel?: string;
  pendingSecondaryActionLabel?: string;
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
            {item.replan_reason ? <p>Replan reason: {item.replan_reason}</p> : null}
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
            {onSecondaryAction ? (
              <button
                type="button"
                className="task-action task-action--secondary"
                disabled={pendingTaskId === item.task_id}
                onClick={() => onSecondaryAction(item.task_id)}
              >
                {pendingTaskId === item.task_id
                  ? (pendingSecondaryActionLabel ?? "Working...")
                  : (secondaryActionLabel ?? "Run action")}
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

function RecoveryQuarantineList({
  entries,
  pendingActionKey,
  onRestore,
  onRestoreAndRequeue,
  onDismiss
}: {
  entries: QuarantineQueueItem[];
  pendingActionKey: string | null;
  onRestore: (queueId: string) => void;
  onRestoreAndRequeue: (queueId: string) => void;
  onDismiss: (queueId: string) => void;
}) {
  return (
    <div className="data-list">
      {entries.map((entry) => {
        const canRestoreAndRequeue =
          entry.task_status === "blocked" && ["session_failed", "stale_session"].includes(entry.task_review_state ?? "");
        return (
          <div key={entry.queue_id} className="data-list__item">
            <div>
              <strong>{entry.task_title ?? entry.task_id ?? entry.queue_id}</strong>
              <p>
                {entry.reason || entry.summary || "Quarantined artifacts awaiting operator review."}
              </p>
              <p>
                Artifacts: {entry.artifact_count}
                {entry.failure_type ? ` | ${entry.failure_type}` : ""}
              </p>
              <p>
                Task state: {entry.task_status ?? "unknown"}
                {entry.task_review_state ? ` | ${entry.task_review_state}` : ""}
                {entry.agent_name ? ` | ${entry.agent_name}` : ""}
              </p>
            </div>
            <div className="data-list__meta">
              <span>{new Date(entry.created_at).toLocaleString()}</span>
              {canRestoreAndRequeue ? (
                <button
                  type="button"
                  className="task-action task-action--approve"
                  disabled={pendingActionKey?.endsWith(`:${entry.queue_id}`) ?? false}
                  onClick={() => onRestoreAndRequeue(entry.queue_id)}
                >
                  {pendingActionKey === `restore-and-requeue:${entry.queue_id}` ? "Restoring..." : "Restore + requeue"}
                </button>
              ) : null}
              <button
                type="button"
                className={canRestoreAndRequeue ? "task-action task-action--secondary" : "task-action task-action--approve"}
                disabled={pendingActionKey?.endsWith(`:${entry.queue_id}`) ?? false}
                onClick={() => onRestore(entry.queue_id)}
              >
                {pendingActionKey === `restore:${entry.queue_id}` ? "Restoring..." : "Restore artifacts"}
              </button>
              <button
                type="button"
                className="task-action task-action--secondary"
                disabled={pendingActionKey?.endsWith(`:${entry.queue_id}`) ?? false}
                onClick={() => onDismiss(entry.queue_id)}
              >
                {pendingActionKey === `dismiss:${entry.queue_id}` ? "Dismissing..." : "Dismiss"}
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function RecoveryAlertList({
  alerts,
  pendingAlertActionId,
  onRunAction
}: {
  alerts: AlertItem[];
  pendingAlertActionId: string | null;
  onRunAction: (alertId: string) => void;
}) {
  return (
    <div className="data-list">
      {alerts.map((alert) => (
        <div key={alert.alert_id} className="data-list__item">
          <div>
            <strong>{alert.title}</strong>
            <p>{alert.description}</p>
          </div>
          <div className="data-list__meta">
            <span>{alert.severity}</span>
            <span>{new Date(alert.created_at).toLocaleString()}</span>
            {alert.operator_action ? (
              <button
                type="button"
                className="task-action task-action--approve"
                disabled={pendingAlertActionId === alert.alert_id}
                onClick={() => onRunAction(alert.alert_id)}
              >
                {pendingAlertActionId === alert.alert_id ? "Running..." : alert.operator_action.label}
              </button>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  );
}

function RecoveryRepeatedFailureList({
  items,
  pendingTaskId,
  onRunAction
}: {
  items: RepeatedFailureItem[];
  pendingTaskId: string | null;
  onRunAction: (taskId: string) => void;
}) {
  return (
    <div className="data-list">
      {items.map((item) => (
        <div key={item.task_id} className="data-list__item">
          <div>
            <strong>{item.task_title ?? item.task_id}</strong>
            <p>
              Failures: {item.failure_count}
              {item.latest_failure_at ? ` | Latest: ${new Date(item.latest_failure_at).toLocaleString()}` : ""}
            </p>
          </div>
          <div className="data-list__meta">
            {item.operator_action ? (
              <button
                type="button"
                className="task-action task-action--approve"
                disabled={pendingTaskId === item.task_id}
                onClick={() => onRunAction(item.task_id)}
              >
                {pendingTaskId === item.task_id ? "Resolving..." : item.operator_action.label}
              </button>
            ) : null}
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
  const [pendingQueueAction, setPendingQueueAction] = useState<string | null>(null);
  const [pendingAlertActionId, setPendingAlertActionId] = useState<string | null>(null);
  const [pendingRepeatedFailureTaskId, setPendingRepeatedFailureTaskId] = useState<string | null>(null);
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

  async function handleRecoverTask(taskId: string) {
    setPendingTaskActionId(taskId);
    setNotice(null);
    try {
      const payload = await recoverTask(taskId);
      await reload();
      setNotice(`Recovered ${taskId}; task is now ${payload.status}.`);
    } catch {
      setNotice("Task recovery failed; keep the blocked task under operator review.");
    } finally {
      setPendingTaskActionId(null);
    }
  }

  async function handleRecoverAndRequeueTask(taskId: string) {
    setPendingTaskActionId(taskId);
    setNotice(null);
    try {
      const payload = await recoverAndRequeueTask(taskId);
      await reload();
      setNotice(`Recovered and requeued ${taskId}; task is now ${payload.status}.`);
    } catch {
      setNotice("Recover and requeue failed; keep the blocked task under operator review.");
    } finally {
      setPendingTaskActionId(null);
    }
  }

  async function handleMarkForReplan(taskId: string) {
    setPendingTaskActionId(taskId);
    setNotice(null);
    try {
      const payload = await markTaskForReplan(taskId);
      await reload();
      setNotice(`Marked ${taskId} for replanning; task is now ${payload.review_state}.`);
    } catch {
      setNotice("Mark-for-replan failed; keep the task under operator review.");
    } finally {
      setPendingTaskActionId(null);
    }
  }

  async function handleFinishReplan(taskId: string) {
    setPendingTaskActionId(taskId);
    setNotice(null);
    try {
      const payload = await finishTaskReplan(taskId);
      await reload();
      setNotice(`Finished replanning for ${taskId}; task is now ${payload.status}.`);
    } catch {
      setNotice("Finish-replan failed; keep the task under operator review.");
    } finally {
      setPendingTaskActionId(null);
    }
  }

  async function handleRestore(queueId: string) {
    setPendingQueueAction(`restore:${queueId}`);
    setNotice(null);
    try {
      const payload = await restoreQuarantineEntry(queueId);
      await reload();
      setNotice(`Restored ${payload.restored_count} quarantined artifact(s) for ${queueId}.`);
    } catch {
      setNotice("Artifact restore failed; keep the quarantined files under review.");
    } finally {
      setPendingQueueAction(null);
    }
  }

  async function handleRestoreAndRequeue(queueId: string) {
    setPendingQueueAction(`restore-and-requeue:${queueId}`);
    setNotice(null);
    try {
      const payload = await restoreAndRequeueQuarantineEntry(queueId);
      await reload();
      setNotice(
        `Restored ${payload.restored_count} quarantined artifact(s) and returned task ${payload.task_id} to ${payload.task_status}.`
      );
    } catch {
      setNotice("Restore and requeue failed; keep the quarantine entry under operator review.");
    } finally {
      setPendingQueueAction(null);
    }
  }

  async function handleDismiss(queueId: string) {
    setPendingQueueAction(`dismiss:${queueId}`);
    setNotice(null);
    try {
      await dismissQuarantineEntry(queueId);
      await reload();
      setNotice(`Dismissed quarantine entry ${queueId}; artifacts remain isolated.`);
    } catch {
      setNotice("Quarantine dismissal failed; leave the entry open for operator review.");
    } finally {
      setPendingQueueAction(null);
    }
  }

  async function handleOpenFailureAlertAction(alertId: string) {
    const alert = [
      ...(recovery?.open_failure_alerts ?? []),
      ...(recovery?.open_stale_agent_alerts ?? [])
    ].find((item) => item.alert_id === alertId);
    if (!alert?.operator_action) {
      return;
    }
    setPendingAlertActionId(alertId);
    setNotice(null);
    try {
      await runAlertOperatorAction(alert.operator_action);
      await reload();
      setNotice(`Ran ${alert.operator_action.label.toLowerCase()} from the recovery queue.`);
    } catch {
      setNotice("Recovery alert action failed; keep the incident under operator review.");
    } finally {
      setPendingAlertActionId(null);
    }
  }

  async function handleRepeatedFailureIncidentAction(taskId: string) {
    const incident = recovery?.repeated_failure_incidents.find((item) => item.task_id === taskId);
    if (!incident?.operator_action) {
      return;
    }
    setPendingRepeatedFailureTaskId(taskId);
    setNotice(null);
    try {
      await runAlertOperatorAction(incident.operator_action);
      await reload();
      setNotice(`Resolved repeated-failure incident for ${taskId}.`);
    } catch {
      setNotice("Repeated-failure resolution failed; keep the task under operator review.");
    } finally {
      setPendingRepeatedFailureTaskId(null);
    }
  }

  const currentDraft = draft;

  return (
    <section className="control-page">
      <header className="page-hero">
        <div>
          <span className="eyebrow">Recovery</span>
          <h1>Retry policy, replanning, and incident controls</h1>
          <p>Inspect retry pressure, move thrashing work into a replanning queue, and preview the actual cooldown schedule operators are creating.</p>
        </div>
        {notice ? <p className="filters-panel__notice">{notice}</p> : null}
      </header>

      <section className="stats-grid">
        <StatCard label="Backoff tasks" value={recovery?.summary.retry_backoff_tasks ?? 0} tone="warn" />
        <StatCard label="Needs replan" value={recovery?.summary.needs_replan_tasks ?? 0} tone="warn" />
        <StatCard label="Replan candidates" value={recovery?.summary.replanning_candidates ?? 0} tone="warn" />
        <StatCard label="Auto-recover candidates" value={recovery?.summary.auto_recovery_candidates ?? 0} tone="warn" />
        <StatCard label="Retry overrides" value={recovery?.summary.tasks_with_retry_overrides ?? 0} />
        <StatCard label="Retry history" value={recovery?.summary.tasks_with_retry_history ?? 0} />
        <StatCard label="Recoverable blocked" value={recovery?.summary.recoverable_blocked_tasks ?? 0} tone="warn" />
        <StatCard label="Open failure alerts" value={recovery?.summary.open_failure_alerts ?? 0} tone="warn" />
        <StatCard label="Repeated incidents" value={recovery?.summary.open_repeated_failure_alerts ?? 0} tone="warn" />
        <StatCard label="Agent incidents" value={recovery?.summary.open_stale_agent_alerts ?? 0} tone="warn" />
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
                  <span>Auto recover safe blocked tasks</span>
                  <select
                    value={currentDraft.auto_recover_blocked_tasks}
                    onChange={(event) => updateDraft("auto_recover_blocked_tasks", event.target.value)}
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
              <h2>Auto-recovery candidates</h2>
              <p>Safe blocked failures the supervisor can recover and requeue automatically when policy is enabled. Open quarantine or repeated-failure incidents keep tasks out of this queue.</p>
            </div>
          </header>
          {(recovery?.auto_recovery_candidates ?? []).length ? (
            <RecoveryTaskList
              items={recovery?.auto_recovery_candidates ?? []}
              pendingTaskId={pendingTaskActionId}
              onRetryLimitChange={handleTaskRetryLimitChange}
              onPrimaryAction={(taskId) => void handleRecoverAndRequeueTask(taskId)}
              primaryActionLabel="Recover + requeue"
              pendingPrimaryActionLabel="Recovering..."
            />
          ) : (
            <div className="data-list">
              <div className="data-list__item">
                <div>
                  <strong>No auto-recovery candidates</strong>
                  <p>No blocked task currently meets the guardrails for hands-off recovery.</p>
                </div>
              </div>
            </div>
          )}
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Recoverable blocked tasks</h2>
              <p>Failure-blocked work that can be returned to the queue immediately from the recovery workbench.</p>
            </div>
          </header>
          {(recovery?.recoverable_blocked_tasks ?? []).length ? (
            <RecoveryTaskList
              items={recovery?.recoverable_blocked_tasks ?? []}
              pendingTaskId={pendingTaskActionId}
              onRetryLimitChange={handleTaskRetryLimitChange}
              onPrimaryAction={(taskId) => void handleRecoverAndRequeueTask(taskId)}
              primaryActionLabel="Recover + requeue"
              pendingPrimaryActionLabel="Recovering..."
              onSecondaryAction={(taskId) => void handleRecoverTask(taskId)}
              secondaryActionLabel="Recover"
              pendingSecondaryActionLabel="Recovering..."
            />
          ) : (
            <div className="data-list">
              <div className="data-list__item">
                <div>
                  <strong>No recoverable blocked tasks</strong>
                  <p>No blocked task currently needs manual failure recovery.</p>
                </div>
              </div>
            </div>
          )}
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Replanning candidates</h2>
              <p>Tasks with retry churn or failure-blocked state that should move out of the recovery loop and into manual replanning.</p>
            </div>
          </header>
          {(recovery?.replanning_candidates ?? []).length ? (
            <RecoveryTaskList
              items={recovery?.replanning_candidates ?? []}
              pendingTaskId={pendingTaskActionId}
              onRetryLimitChange={handleTaskRetryLimitChange}
              onPrimaryAction={(taskId) => void handleMarkForReplan(taskId)}
              primaryActionLabel="Mark for replan"
              pendingPrimaryActionLabel="Marking..."
            />
          ) : (
            <div className="data-list">
              <div className="data-list__item">
                <div>
                  <strong>No replanning candidates</strong>
                  <p>No active task currently looks stuck enough to move into manual replanning.</p>
                </div>
              </div>
            </div>
          )}
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Needs replan</h2>
              <p>Tasks already pulled out of retry/recovery loops and waiting for manual scope or plan changes before they return to the queue.</p>
            </div>
          </header>
          {(recovery?.needs_replan_tasks ?? []).length ? (
            <RecoveryTaskList
              items={recovery?.needs_replan_tasks ?? []}
              pendingTaskId={pendingTaskActionId}
              onRetryLimitChange={handleTaskRetryLimitChange}
              onPrimaryAction={(taskId) => void handleFinishReplan(taskId)}
              primaryActionLabel="Finish replan"
              pendingPrimaryActionLabel="Requeueing..."
            />
          ) : (
            <div className="data-list">
              <div className="data-list__item">
                <div>
                  <strong>No tasks waiting on replan</strong>
                  <p>No task is currently parked in the manual replanning queue.</p>
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
              <h2>Open quarantine queue</h2>
              <p>Artifact incidents that are still open for operator review, with direct restore, requeue, and dismiss controls.</p>
            </div>
          </header>
          {(recovery?.open_quarantine_entries ?? []).length ? (
            <RecoveryQuarantineList
              entries={recovery?.open_quarantine_entries ?? []}
              pendingActionKey={pendingQueueAction}
              onRestore={(queueId) => void handleRestore(queueId)}
              onRestoreAndRequeue={(queueId) => void handleRestoreAndRequeue(queueId)}
              onDismiss={(queueId) => void handleDismiss(queueId)}
            />
          ) : (
            <div className="data-list">
              <div className="data-list__item">
                <div>
                  <strong>No open quarantine incidents</strong>
                  <p>No quarantined artifacts are currently waiting for operator review.</p>
                </div>
              </div>
            </div>
          )}
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Open failure alerts</h2>
              <p>Task-failure incidents that are still open and actionable from the recovery workbench.</p>
            </div>
          </header>
          {(recovery?.open_failure_alerts ?? []).length ? (
            <RecoveryAlertList
              alerts={recovery?.open_failure_alerts ?? []}
              pendingAlertActionId={pendingAlertActionId}
              onRunAction={(alertId) => void handleOpenFailureAlertAction(alertId)}
            />
          ) : (
            <div className="data-list">
              <div className="data-list__item">
                <div>
                  <strong>No open failure alerts</strong>
                  <p>No task-failure alerts are currently waiting for operator action.</p>
                </div>
              </div>
            </div>
          )}
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Stale agent incidents</h2>
              <p>Agent recovery incidents that are still open and can be resolved directly from the recovery workbench.</p>
            </div>
          </header>
          {(recovery?.open_stale_agent_alerts ?? []).length ? (
            <RecoveryAlertList
              alerts={recovery?.open_stale_agent_alerts ?? []}
              pendingAlertActionId={pendingAlertActionId}
              onRunAction={(alertId) => void handleOpenFailureAlertAction(alertId)}
            />
          ) : (
            <div className="data-list">
              <div className="data-list__item">
                <div>
                  <strong>No stale agent incidents</strong>
                  <p>No open stale-agent heartbeat alerts are currently waiting for operator action.</p>
                </div>
              </div>
            </div>
          )}
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Repeated failure incidents</h2>
              <p>Tasks that still have open repeated-failure alerts and can be resolved directly from Recovery.</p>
            </div>
          </header>
          {(recovery?.repeated_failure_incidents ?? []).length ? (
            <RecoveryRepeatedFailureList
              items={recovery?.repeated_failure_incidents ?? []}
              pendingTaskId={pendingRepeatedFailureTaskId}
              onRunAction={(taskId) => void handleRepeatedFailureIncidentAction(taskId)}
            />
          ) : (
            <div className="data-list">
              <div className="data-list__item">
                <div>
                  <strong>No repeated-failure incidents</strong>
                  <p>No task currently has an open repeated-failure alert to resolve.</p>
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
