import { useEffect, useState } from "react";
import { StatCard } from "../components/StatCard";
import {
  dismissQuarantineEntry,
  fetchAlerts,
  fetchEscalations,
  fetchFailures,
  fetchIncidentTimeline,
  fetchRecoveryPolicy,
  finishTaskReplan,
  markTaskForReplan,
  recoverAndRequeueTask,
  recoverTask,
  resetTaskCircuitBreaker,
  resetTaskRetryState,
  runAlertOperatorAction,
  runFailureOperatorAction,
  restoreAndRequeueQuarantineEntry,
  restoreQuarantineEntry
} from "../lib/controlRoomApi";
import { useLivePulse } from "../lib/useLivePulse";
import type {
  AlertItem,
  EscalationItem,
  FailureItem,
  RecoveryPolicyResponse,
  RecoveryTaskItem,
  RepeatedFailureItem,
  TimelineEvent
} from "../types";
import { AlertsPage } from "./AlertsPage";
import { EscalationsPage } from "./EscalationsPage";
import { FailuresPage } from "./FailuresPage";
import { RecoveryPage } from "./RecoveryPage";
import { TimelinePage } from "./TimelinePage";

function formatTime(value?: string | null) {
  if (!value) {
    return "Not recorded";
  }
  return new Date(value).toLocaleString();
}

function IncidentTaskList({
  title,
  description,
  items,
  pendingActionKey,
  primaryLabel,
  primaryKeyPrefix,
  onPrimaryAction,
  secondaryLabel,
  secondaryKeyPrefix,
  onSecondaryAction
}: {
  title: string;
  description: string;
  items: RecoveryTaskItem[];
  pendingActionKey: string | null;
  primaryLabel: string;
  primaryKeyPrefix: string;
  onPrimaryAction: (taskId: string) => Promise<void>;
  secondaryLabel?: string;
  secondaryKeyPrefix?: string;
  onSecondaryAction?: (taskId: string) => Promise<void>;
}) {
  return (
    <article className="surface-card">
      <div className="surface-card__header">
        <div>
          <span className="eyebrow">Incident queue</span>
          <h2>{title}</h2>
        </div>
        <span className="status-chip">{items.length}</span>
      </div>
      <p className="surface-card__copy">{description}</p>
      <div className="list-stack">
        {items.length ? (
          items.slice(0, 6).map((item) => (
            <div key={item.task_id} className="list-row">
              <div>
                <strong>{item.title}</strong>
                <p>
                  {item.goal_title ?? "Unlinked goal"}
                  {item.agent_name ? ` · ${item.agent_name}` : ""}
                </p>
                <p>
                  {item.status}
                  {item.review_state ? ` · ${item.review_state}` : ""}
                  {item.next_retry_at ? ` · next retry ${formatTime(item.next_retry_at)}` : ""}
                </p>
              </div>
              <div className="list-row__meta list-row__meta--actions">
                <button
                  type="button"
                  className="hero-button hero-button--compact"
                  disabled={pendingActionKey === `${primaryKeyPrefix}:${item.task_id}`}
                  onClick={() => void onPrimaryAction(item.task_id)}
                >
                  {pendingActionKey === `${primaryKeyPrefix}:${item.task_id}` ? "Working..." : primaryLabel}
                </button>
                {secondaryLabel && secondaryKeyPrefix && onSecondaryAction ? (
                  <button
                    type="button"
                    className="hero-button hero-button--ghost hero-button--compact"
                    disabled={pendingActionKey === `${secondaryKeyPrefix}:${item.task_id}`}
                    onClick={() => void onSecondaryAction(item.task_id)}
                  >
                    {pendingActionKey === `${secondaryKeyPrefix}:${item.task_id}` ? "Working..." : secondaryLabel}
                  </button>
                ) : null}
              </div>
            </div>
          ))
        ) : (
          <div className="empty-state empty-state--compact">
            <strong>No items in this queue.</strong>
            <p>MAAS will surface new incidents here when operator intervention is needed.</p>
          </div>
        )}
      </div>
    </article>
  );
}

export function IncidentsPage() {
  const [recovery, setRecovery] = useState<RecoveryPolicyResponse | null>(null);
  const [failures, setFailures] = useState<FailureItem[]>([]);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [escalations, setEscalations] = useState<EscalationItem[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [advancedStudiosOpen, setAdvancedStudiosOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingActionKey, setPendingActionKey] = useState<string | null>(null);
  const livePulse = useLivePulse();

  async function loadIncidents() {
    const [recoveryPayload, failuresPayload, alertsPayload, escalationsPayload, timelinePayload] = await Promise.all([
      fetchRecoveryPolicy(),
      fetchFailures(),
      fetchAlerts(),
      fetchEscalations(),
      fetchIncidentTimeline({ limit: 12 })
    ]);
    setRecovery(recoveryPayload);
    setFailures(failuresPayload.recent);
    setAlerts(alertsPayload.alerts);
    setEscalations(escalationsPayload.escalations);
    setTimeline(timelinePayload.events);
  }

  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        const [recoveryPayload, failuresPayload, alertsPayload, escalationsPayload, timelinePayload] = await Promise.all([
          fetchRecoveryPolicy(),
          fetchFailures(),
          fetchAlerts(),
          fetchEscalations(),
          fetchIncidentTimeline({ limit: 12 })
        ]);
        if (!mounted) {
          return;
        }
        setRecovery(recoveryPayload);
        setFailures(failuresPayload.recent);
        setAlerts(alertsPayload.alerts);
        setEscalations(escalationsPayload.escalations);
        setTimeline(timelinePayload.events);
      } catch {
        if (mounted) {
          setNotice("Incident refresh failed; keeping the most recent available queues.");
        }
      }
    }

    void load();
    return () => {
      mounted = false;
    };
  }, [livePulse]);

  async function runAction(actionKey: string, successMessage: string, action: () => Promise<unknown>, fallback: string) {
    setPendingActionKey(actionKey);
    setNotice(null);
    try {
      await action();
      await loadIncidents();
      setNotice(successMessage);
    } catch {
      setNotice(fallback);
    } finally {
      setPendingActionKey(null);
    }
  }

  const repeatedIncidents = recovery?.repeated_failure_incidents ?? [];
  const deadLetterEntries = recovery?.dead_letter_entries ?? [];
  const openQuarantineEntries = recovery?.open_quarantine_entries ?? [];

  return (
    <section className="dashboard-page">
      <header className="dashboard-hero">
        <div className="dashboard-hero__content">
          <span className="eyebrow">Incidents</span>
          <h1>Failures, alerts, and recovery in one place</h1>
          <p>Stop hunting across multiple admin views. This is the operational workbench for anything broken, blocked, risky, or waiting for operator judgment.</p>
          <div className="hero-meta">
            <span className="hero-meta__pill">{recovery?.summary.open_failure_alerts ?? 0} open failure alerts</span>
            <span className="hero-meta__pill">{recovery?.summary.open_dead_letter_entries ?? 0} DLQ entries</span>
            <span className="hero-meta__pill">{recovery?.summary.open_circuit_breakers ?? 0} circuit breakers</span>
          </div>
        </div>
      </header>

      {notice ? <div className="banner banner--info">{notice}</div> : null}

      <section className="stats-grid stats-grid--dense">
        <StatCard label="Open alerts" value={alerts.filter((item) => item.status === "open").length} tone="warn" />
        <StatCard label="Recent failures" value={failures.length} tone="warn" />
        <StatCard label="Recoverable tasks" value={recovery?.summary.recoverable_blocked_tasks ?? 0} tone="warn" />
        <StatCard label="Retry backoff" value={recovery?.summary.retry_backoff_tasks ?? 0} />
        <StatCard label="Needs replan" value={recovery?.summary.needs_replan_tasks ?? 0} tone="warn" />
        <StatCard label="DLQ entries" value={recovery?.summary.open_dead_letter_entries ?? 0} tone="warn" />
        <StatCard label="Quarantine entries" value={recovery?.summary.open_quarantine_entries ?? 0} tone="warn" />
        <StatCard label="Open escalations" value={escalations.filter((item) => item.status === "open").length} />
      </section>

      <section className="two-column-grid">
        <IncidentTaskList
          title="Blocked tasks you can recover now"
          description="These tasks are blocked for failure-related reasons and can be explicitly recovered or requeued."
          items={recovery?.recoverable_blocked_tasks ?? []}
          pendingActionKey={pendingActionKey}
          primaryLabel="Recover"
          primaryKeyPrefix="recover"
          onPrimaryAction={(taskId) =>
            runAction(
              `recover:${taskId}`,
              `Recovered ${taskId} into planning.`,
              () => recoverTask(taskId),
              `Recovery failed for ${taskId}.`
            )
          }
          secondaryLabel="Recover + requeue"
          secondaryKeyPrefix="recover-and-requeue"
          onSecondaryAction={(taskId) =>
            runAction(
              `recover-and-requeue:${taskId}`,
              `Recovered and requeued ${taskId}.`,
              () => recoverAndRequeueTask(taskId),
              `Recover-and-requeue failed for ${taskId}.`
            )
          }
        />

        <IncidentTaskList
          title="Tasks waiting for replanning"
          description="These tasks should be re-scoped or re-explained before being pushed back into normal execution."
          items={recovery?.needs_replan_tasks ?? []}
          pendingActionKey={pendingActionKey}
          primaryLabel="Finish replan"
          primaryKeyPrefix="finish-replan"
          onPrimaryAction={(taskId) =>
            runAction(
              `finish-replan:${taskId}`,
              `Returned ${taskId} to readiness evaluation.`,
              () => finishTaskReplan(taskId),
              `Finish-replan failed for ${taskId}.`
            )
          }
          secondaryLabel="Mark for replan"
          secondaryKeyPrefix="mark-for-replan"
          onSecondaryAction={(taskId) =>
            runAction(
              `mark-for-replan:${taskId}`,
              `Marked ${taskId} for replanning.`,
              () => markTaskForReplan(taskId),
              `Mark-for-replan failed for ${taskId}.`
            )
          }
        />
      </section>

      <section className="two-column-grid">
        <article className="surface-card">
          <div className="surface-card__header">
            <div>
              <span className="eyebrow">Containment</span>
              <h2>Dead-letter and circuit breakers</h2>
            </div>
          </div>
          <div className="list-stack">
            {deadLetterEntries.slice(0, 6).map((entry) => (
              <div key={entry.dlq_id} className="list-row">
                <div>
                  <strong>{entry.title}</strong>
                  <p>
                    {entry.reason} · {entry.task_status}
                    {entry.review_state ? ` · ${entry.review_state}` : ""}
                  </p>
                  <p>{entry.detail?.failure_type ? `${entry.detail.failure_type} · ` : ""}{formatTime(entry.created_at)}</p>
                </div>
                <div className="list-row__meta list-row__meta--actions">
                  <button
                    type="button"
                    className="hero-button hero-button--compact"
                    disabled={pendingActionKey === `reset-retry:${entry.task_id}`}
                    onClick={() =>
                      void runAction(
                        `reset-retry:${entry.task_id}`,
                        `Reset retry state for ${entry.task_id}.`,
                        () => resetTaskRetryState(entry.task_id),
                        `Retry reset failed for ${entry.task_id}.`
                      )
                    }
                  >
                    {pendingActionKey === `reset-retry:${entry.task_id}` ? "Resetting..." : "Reset retry state"}
                  </button>
                </div>
              </div>
            ))}
            {(recovery?.circuit_breaker_tasks ?? []).slice(0, 6).map((task) => (
              <div key={task.task_id} className="list-row">
                <div>
                  <strong>{task.title}</strong>
                  <p>
                    {task.circuit_breaker_detail?.trigger?.replaceAll("_", " ") ?? "circuit breaker"} · {task.review_state ?? task.status}
                  </p>
                  <p>Opened {formatTime(task.circuit_breaker_opened_at)}</p>
                </div>
                <div className="list-row__meta list-row__meta--actions">
                  <button
                    type="button"
                    className="hero-button hero-button--compact"
                    disabled={pendingActionKey === `reset-circuit:${task.task_id}`}
                    onClick={() =>
                      void runAction(
                        `reset-circuit:${task.task_id}`,
                        `Reset circuit breaker for ${task.task_id}.`,
                        () => resetTaskCircuitBreaker(task.task_id),
                        `Circuit-breaker reset failed for ${task.task_id}.`
                      )
                    }
                  >
                    {pendingActionKey === `reset-circuit:${task.task_id}` ? "Resetting..." : "Reset breaker"}
                  </button>
                </div>
              </div>
            ))}
            {!deadLetterEntries.length && !(recovery?.circuit_breaker_tasks ?? []).length ? (
              <div className="empty-state empty-state--compact">
                <strong>No dead-letter or circuit-breaker pressure.</strong>
                <p>MAAS will surface hard-stop incidents here when it decides not to keep retrying.</p>
              </div>
            ) : null}
          </div>
        </article>

        <article className="surface-card">
          <div className="surface-card__header">
            <div>
              <span className="eyebrow">Quarantine</span>
              <h2>Artifact isolation queue</h2>
            </div>
          </div>
          <div className="list-stack">
            {openQuarantineEntries.slice(0, 6).map((entry) => {
              const recoverable =
                entry.task_status === "blocked" && ["session_failed", "stale_session"].includes(entry.task_review_state ?? "");
              return (
                <div key={entry.queue_id} className="list-row">
                  <div>
                    <strong>{entry.task_title ?? entry.queue_id}</strong>
                    <p>{entry.summary ?? entry.reason ?? "Quarantined artifacts are waiting for review."}</p>
                    <p>{entry.artifact_count} artifacts · {entry.status}</p>
                  </div>
                  <div className="list-row__meta list-row__meta--actions">
                    <button
                      type="button"
                      className="hero-button hero-button--compact"
                      disabled={pendingActionKey === `restore-quarantine:${entry.queue_id}`}
                      onClick={() =>
                        void runAction(
                          `restore-quarantine:${entry.queue_id}`,
                          `Restored artifacts for ${entry.queue_id}.`,
                          () => restoreQuarantineEntry(entry.queue_id),
                          `Artifact restore failed for ${entry.queue_id}.`
                        )
                      }
                    >
                      {pendingActionKey === `restore-quarantine:${entry.queue_id}` ? "Restoring..." : "Restore artifacts"}
                    </button>
                    {recoverable ? (
                      <button
                        type="button"
                        className="hero-button hero-button--ghost hero-button--compact"
                        disabled={pendingActionKey === `restore-requeue:${entry.queue_id}`}
                        onClick={() =>
                          void runAction(
                            `restore-requeue:${entry.queue_id}`,
                            `Restored artifacts and requeued ${entry.task_id}.`,
                            () => restoreAndRequeueQuarantineEntry(entry.queue_id),
                            `Restore-and-requeue failed for ${entry.queue_id}.`
                          )
                        }
                      >
                        {pendingActionKey === `restore-requeue:${entry.queue_id}` ? "Working..." : "Restore + requeue"}
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="hero-button hero-button--ghost hero-button--compact"
                      disabled={pendingActionKey === `dismiss:${entry.queue_id}`}
                      onClick={() =>
                        void runAction(
                          `dismiss:${entry.queue_id}`,
                          `Dismissed quarantine entry ${entry.queue_id}.`,
                          () => dismissQuarantineEntry(entry.queue_id),
                          `Dismiss failed for ${entry.queue_id}.`
                        )
                      }
                    >
                      {pendingActionKey === `dismiss:${entry.queue_id}` ? "Dismissing..." : "Dismiss"}
                    </button>
                  </div>
                </div>
              );
            })}
            {!openQuarantineEntries.length ? (
              <div className="empty-state empty-state--compact">
                <strong>No open quarantine entries.</strong>
                <p>When MAAS isolates runtime artifacts for safety, this queue becomes the operator inbox.</p>
              </div>
            ) : null}
          </div>
        </article>
      </section>

      <section className="two-column-grid">
        <article className="surface-card">
          <div className="surface-card__header">
            <div>
              <span className="eyebrow">Alerts and failures</span>
              <h2>What is actively asking for attention</h2>
            </div>
          </div>
          <div className="list-stack">
            {alerts.slice(0, 6).map((alert) => (
              <div key={alert.alert_id} className="list-row">
                <div>
                  <strong>{alert.title}</strong>
                  <p>{alert.description}</p>
                  <p>{alert.severity} · {formatTime(alert.created_at)}</p>
                </div>
                <div className="list-row__meta list-row__meta--actions">
                  {alert.operator_action ? (
                    <button
                      type="button"
                      className="hero-button hero-button--compact"
                      disabled={pendingActionKey === `alert:${alert.alert_id}`}
                      onClick={() =>
                        void runAction(
                          `alert:${alert.alert_id}`,
                          `Ran operator action for alert ${alert.alert_id}.`,
                          () => runAlertOperatorAction(alert.operator_action!),
                          `Alert action failed for ${alert.alert_id}.`
                        )
                      }
                    >
                      {pendingActionKey === `alert:${alert.alert_id}` ? "Working..." : alert.operator_action.label}
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
            {failures.slice(0, 6).map((failure: FailureItem) => (
              <div key={failure.failure_id ?? `${failure.session_id}:${failure.created_at}`} className="list-row">
                <div>
                  <strong>{failure.task_title ?? failure.failure_type}</strong>
                  <p>{failure.summary}</p>
                  <p>{failure.failure_type} · {formatTime(failure.created_at)}</p>
                </div>
                <div className="list-row__meta list-row__meta--actions">
                  {failure.operator_action ? (
                    <button
                      type="button"
                      className="hero-button hero-button--compact"
                      disabled={pendingActionKey === `failure:${failure.failure_id ?? failure.created_at}`}
                      onClick={() =>
                        void runAction(
                          `failure:${failure.failure_id ?? failure.created_at}`,
                          `Ran operator action for recent failure.`,
                          () => runFailureOperatorAction(failure.operator_action!),
                          "Failure action failed; keep the incident under review."
                        )
                      }
                    >
                      {pendingActionKey === `failure:${failure.failure_id ?? failure.created_at}`
                        ? "Working..."
                        : failure.operator_action.label}
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
            {repeatedIncidents.slice(0, 4).map((item: RepeatedFailureItem) => (
              <div key={item.task_id} className="list-row">
                <div>
                  <strong>{item.task_title ?? item.task_id}</strong>
                  <p>{item.failure_count} repeated failures</p>
                </div>
                <div className="list-row__meta list-row__meta--actions">
                  {item.operator_action ? (
                    <button
                      type="button"
                      className="hero-button hero-button--compact"
                      disabled={pendingActionKey === `repeated:${item.task_id}`}
                      onClick={() =>
                        void runAction(
                          `repeated:${item.task_id}`,
                          `Resolved repeated-failure incident for ${item.task_id}.`,
                          () => runAlertOperatorAction(item.operator_action!),
                          `Repeated-failure action failed for ${item.task_id}.`
                        )
                      }
                    >
                      {pendingActionKey === `repeated:${item.task_id}` ? "Working..." : item.operator_action.label}
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="surface-card">
          <div className="surface-card__header">
            <div>
              <span className="eyebrow">Replay</span>
              <h2>Recent incident timeline</h2>
            </div>
          </div>
          <div className="list-stack">
            {timeline.length ? (
              timeline.map((event) => (
                <div key={`${event.source}:${event.event_id}`} className="list-row">
                  <div>
                    <strong>{event.title}</strong>
                    <p>{event.description}</p>
                    <p>
                      {event.source} · {event.event_type}
                      {event.task_id ? ` · ${event.task_id}` : ""}
                    </p>
                  </div>
                  <div className="list-row__meta">
                    <span className={`status-pill status-pill--${event.severity === "warning" ? "warn" : event.severity === "critical" ? "danger" : "default"}`}>
                      {event.severity}
                    </span>
                    <span>{formatTime(event.created_at)}</span>
                  </div>
                </div>
              ))
            ) : (
              <div className="empty-state empty-state--compact">
                <strong>No recent incident events are visible.</strong>
                <p>As alerts, failures, escalations, or recoveries happen, they will show up here.</p>
              </div>
            )}
            {escalations.slice(0, 4).map((escalation) => (
              <div key={escalation.escalation_id} className="list-row">
                <div>
                  <strong>{escalation.reason}</strong>
                  <p>
                    {escalation.action_type} · {escalation.resource_type} · {escalation.status}
                  </p>
                </div>
                <div className="list-row__meta">
                  <span>{escalation.requester_name ?? escalation.requested_by}</span>
                  <span>{formatTime(escalation.created_at)}</span>
                </div>
              </div>
            ))}
          </div>
        </article>
      </section>

      <details
        className="advanced-pane"
        onToggle={(event) => setAdvancedStudiosOpen((event.currentTarget as HTMLDetailsElement).open)}
      >
        <summary>Advanced incident studios</summary>
        {advancedStudiosOpen ? (
          <div className="advanced-pane__content">
            <div className="embedded-page">
              <RecoveryPage />
            </div>
            <div className="embedded-page">
              <FailuresPage />
            </div>
            <div className="embedded-page">
              <AlertsPage />
            </div>
            <div className="embedded-page">
              <EscalationsPage />
            </div>
            <div className="embedded-page">
              <TimelinePage />
            </div>
          </div>
        ) : null}
      </details>
    </section>
  );
}
