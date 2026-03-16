import { useEffect, useState } from "react";
import {
  dismissQuarantineEntry,
  fetchFailures,
  fetchQuarantineQueue,
  runAlertOperatorAction,
  reopenQuarantineEntry,
  runFailureOperatorAction,
  restoreAndRequeueQuarantineEntry,
  restoreQuarantineEntry
} from "../lib/controlRoomApi";
import { useLivePulse } from "../lib/useLivePulse";
import type { FailuresResponse, QuarantineQueueResponse } from "../types";
import { StatCard } from "../components/StatCard";

export function FailuresPage() {
  const [failures, setFailures] = useState<FailuresResponse | null>(null);
  const [quarantineQueue, setQuarantineQueue] = useState<QuarantineQueueResponse | null>(null);
  const [pendingFailureAction, setPendingFailureAction] = useState<string | null>(null);
  const [pendingRepeatedFailureAction, setPendingRepeatedFailureAction] = useState<string | null>(null);
  const [pendingQueueAction, setPendingQueueAction] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const livePulse = useLivePulse();

  useEffect(() => {
    let mounted = true;

    async function loadFailures() {
      const [failuresPayload, quarantinePayload] = await Promise.all([fetchFailures(), fetchQuarantineQueue()]);
      if (mounted) {
        setFailures(failuresPayload);
        setQuarantineQueue(quarantinePayload);
      }
    }

    void loadFailures();
    return () => {
      mounted = false;
    };
  }, [livePulse]);

  async function reload() {
    const [failuresPayload, quarantinePayload] = await Promise.all([fetchFailures(), fetchQuarantineQueue()]);
    setFailures(failuresPayload);
    setQuarantineQueue(quarantinePayload);
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

  async function handleReopen(queueId: string) {
    setPendingQueueAction(`reopen:${queueId}`);
    setNotice(null);
    try {
      await reopenQuarantineEntry(queueId);
      await reload();
      setNotice(`Reopened quarantine entry ${queueId} for operator review.`);
    } catch {
      setNotice("Quarantine reopen failed; keep the current entry state under review.");
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

  async function handleRecentFailureAction(failureId: string) {
    const failure = failures?.recent.find((item) => item.failure_id === failureId);
    if (!failure?.operator_action) {
      return;
    }

    setPendingFailureAction(`${failureId}:${failure.operator_action.action}`);
    setNotice(null);
    try {
      await runFailureOperatorAction(failure.operator_action);
      await reload();
      if (failure.operator_action.action === "restore_and_requeue_quarantine_entry") {
        setNotice(`Restored quarantined artifacts and returned task ${failure.operator_action.related_task_id} to the queue.`);
      } else if (failure.operator_action.action === "reopen_quarantine_entry") {
        setNotice(`Reopened dismissed quarantine entry for failure ${failureId}.`);
      } else if (failure.operator_action.action === "restore_failure_artifacts") {
        setNotice(`Restored quarantined artifacts for failure ${failureId}.`);
      } else {
        setNotice(`Recovered and requeued task ${failure.operator_action.resource_id}.`);
      }
    } catch {
      setNotice("Failure action failed; keep the incident under operator review.");
    } finally {
      setPendingFailureAction(null);
    }
  }

  async function handleRepeatedFailureAction(taskId: string) {
    const repeatedFailure = failures?.repeated_tasks.find((item) => item.task_id === taskId);
    if (!repeatedFailure?.operator_action) {
      return;
    }

    setPendingRepeatedFailureAction(`${taskId}:${repeatedFailure.operator_action.action}`);
    setNotice(null);
    try {
      await runAlertOperatorAction(repeatedFailure.operator_action);
      await reload();
      setNotice(`Resolved the repeated-failure incident for ${taskId}.`);
    } catch {
      setNotice("Repeated-failure resolution failed; keep the task under operator review.");
    } finally {
      setPendingRepeatedFailureAction(null);
    }
  }

  return (
    <section className="control-page">
      <header className="page-hero">
        <div>
          <span className="eyebrow">Failures</span>
          <h1>Failure memory and quarantine</h1>
          <p>Inspect recent failed or timed-out work, repeated incidents, and any artifacts isolated from normal flow.</p>
        </div>
        {notice ? <p className="filters-panel__notice">{notice}</p> : null}
      </header>

      <section className="stats-grid">
        <StatCard label="Failures logged" value={failures?.summary.total_failures ?? 0} tone="warn" />
        <StatCard label="Tasks hit" value={failures?.summary.tasks_with_failures ?? 0} />
        <StatCard label="Repeated tasks" value={failures?.summary.repeated_tasks ?? 0} tone="warn" />
        <StatCard label="Quarantine open" value={quarantineQueue?.summary.open ?? 0} tone="warn" />
        <StatCard label="Restored" value={quarantineQueue?.summary.restored ?? 0} />
        <StatCard label="Dismissed" value={quarantineQueue?.summary.dismissed ?? 0} />
      </section>

      <section className="overview-grid">
        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Recent failures</h2>
              <p>Latest failed or timed-out sessions, including quarantine details when artifacts were isolated into the queue.</p>
            </div>
          </header>
          <div className="data-list">
            {(failures?.recent ?? []).map((item) => (
              <div key={item.failure_id ?? `${item.task_id}-${item.created_at}`} className="data-list__item">
                <div>
                  <strong>{item.task_title ?? item.task_id ?? "Unlinked failure"}</strong>
                  <p>{item.summary}</p>
                  {item.retry_count ? (
                    <p>
                      Auto retries: {item.retry_count}
                      {item.last_retry_reason ? ` (${item.last_retry_reason})` : ""}
                    </p>
                  ) : null}
                  {item.next_retry_at ? (
                    <p>
                      Next retry window: {new Date(item.next_retry_at).toLocaleString()}
                      {item.next_retry_reason ? ` (${item.next_retry_reason})` : ""}
                    </p>
                  ) : null}
                  {item.quarantined_artifact_count ? (
                    <p>
                      Quarantined artifacts: {item.quarantined_artifact_count}
                      {item.quarantined_artifacts?.[0]?.quarantined_from_path
                        ? ` from ${item.quarantined_artifacts[0].quarantined_from_path}`
                        : ""}
                    </p>
                  ) : null}
                </div>
                <div className="data-list__meta">
                  <span>{item.failure_type}</span>
                  <span>{new Date(item.created_at).toLocaleString()}</span>
                  {item.operator_action ? (
                    <button
                      type="button"
                      className="task-action task-action--approve"
                      disabled={pendingFailureAction === `${item.failure_id}:${item.operator_action.action}`}
                      onClick={() => item.failure_id && void handleRecentFailureAction(item.failure_id)}
                    >
                      {pendingFailureAction === `${item.failure_id}:${item.operator_action.action}`
                        ? item.operator_action.action === "restore_and_requeue_quarantine_entry"
                          ? "Restoring..."
                          : item.operator_action.action === "reopen_quarantine_entry"
                            ? "Reopening..."
                          : item.operator_action.action === "restore_failure_artifacts"
                            ? "Restoring..."
                            : "Recovering..."
                        : item.operator_action.label}
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Quarantine queue</h2>
              <p>Operator workflow for isolated artifacts. Restore returns files to the artifact workspace; dismiss keeps them quarantined.</p>
            </div>
          </header>
          <div className="data-list">
            {(quarantineQueue?.entries ?? []).map((item) => (
              <div key={item.queue_id} className="data-list__item">
                <div>
                  <strong>{item.task_title ?? item.task_id ?? item.session_id}</strong>
                  <p>{item.summary ?? "Quarantined artifacts awaiting review."}</p>
                  <p>
                    Status: {item.status} | Artifacts: {item.artifact_count}
                    {item.reason ? ` | Reason: ${item.reason}` : ""}
                  </p>
                  {item.task_status ? (
                    <p>
                      Task: {item.task_status}
                      {item.task_review_state ? ` | ${item.task_review_state}` : ""}
                    </p>
                  ) : null}
                  {item.quarantined_artifacts?.[0]?.quarantined_from_path ? (
                    <p>Original path: {item.quarantined_artifacts[0].quarantined_from_path}</p>
                  ) : null}
                </div>
                <div className="data-list__meta">
                  <span>{item.failure_type ?? "quarantine"}</span>
                  <span>{new Date(item.created_at).toLocaleString()}</span>
                  {item.status === "open" &&
                  item.task_status === "blocked" &&
                  (item.task_review_state === "session_failed" || item.task_review_state === "stale_session") ? (
                    <button
                      type="button"
                      className="task-action task-action--secondary"
                      disabled={pendingQueueAction === `restore-and-requeue:${item.queue_id}`}
                      onClick={() => void handleRestoreAndRequeue(item.queue_id)}
                    >
                      {pendingQueueAction === `restore-and-requeue:${item.queue_id}`
                        ? "Restoring..."
                        : "Restore + requeue"}
                    </button>
                  ) : null}
                  {item.status === "open" ? (
                    <button
                      type="button"
                      className="task-action task-action--secondary"
                      disabled={
                        pendingQueueAction === `restore:${item.queue_id}` ||
                        pendingQueueAction === `restore-and-requeue:${item.queue_id}`
                      }
                      onClick={() => void handleRestore(item.queue_id)}
                    >
                      {pendingQueueAction === `restore:${item.queue_id}` ? "Restoring..." : "Restore"}
                    </button>
                  ) : null}
                  {item.status === "open" ? (
                    <button
                      type="button"
                      className="task-action"
                      disabled={
                        pendingQueueAction === `dismiss:${item.queue_id}` ||
                        pendingQueueAction === `restore-and-requeue:${item.queue_id}`
                      }
                      onClick={() => void handleDismiss(item.queue_id)}
                    >
                      {pendingQueueAction === `dismiss:${item.queue_id}` ? "Dismissing..." : "Dismiss"}
                    </button>
                  ) : null}
                  {item.status === "dismissed" ? (
                    <button
                      type="button"
                      className="task-action task-action--secondary"
                      disabled={pendingQueueAction === `reopen:${item.queue_id}`}
                      onClick={() => void handleReopen(item.queue_id)}
                    >
                      {pendingQueueAction === `reopen:${item.queue_id}` ? "Reopening..." : "Reopen"}
                    </button>
                  ) : null}
                  {item.resolved_at ? <span>{new Date(item.resolved_at).toLocaleString()}</span> : null}
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Repeated failure tasks</h2>
              <p>Tasks that have crossed the repeated-failure threshold and should stay under explicit operator review.</p>
            </div>
          </header>
          <div className="data-list">
            {(failures?.repeated_tasks ?? []).map((item) => (
              <div key={item.task_id} className="data-list__item">
                <div>
                  <strong>{item.task_title ?? item.task_id}</strong>
                  <p>{item.failure_count} logged failures</p>
                </div>
                <div className="data-list__meta">
                  <span>{item.task_id}</span>
                  <span>
                    {item.latest_failure_at ? new Date(item.latest_failure_at).toLocaleString() : "No timestamp"}
                  </span>
                  {item.operator_action ? (
                    <button
                      type="button"
                      className="task-action task-action--approve"
                      disabled={pendingRepeatedFailureAction === `${item.task_id}:${item.operator_action.action}`}
                      onClick={() => void handleRepeatedFailureAction(item.task_id)}
                    >
                      {pendingRepeatedFailureAction === `${item.task_id}:${item.operator_action.action}`
                        ? "Resolving..."
                        : item.operator_action.label}
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </article>
      </section>
    </section>
  );
}
