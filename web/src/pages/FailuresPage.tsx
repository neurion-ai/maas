import { useEffect, useState } from "react";
import { dismissQuarantineEntry, fetchFailures, fetchQuarantineQueue, restoreQuarantineEntry } from "../lib/controlRoomApi";
import { useLivePulse } from "../lib/useLivePulse";
import type { FailuresResponse, QuarantineQueueResponse } from "../types";
import { StatCard } from "../components/StatCard";

export function FailuresPage() {
  const [failures, setFailures] = useState<FailuresResponse | null>(null);
  const [quarantineQueue, setQuarantineQueue] = useState<QuarantineQueueResponse | null>(null);
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
                  {item.quarantined_artifacts?.[0]?.quarantined_from_path ? (
                    <p>Original path: {item.quarantined_artifacts[0].quarantined_from_path}</p>
                  ) : null}
                </div>
                <div className="data-list__meta">
                  <span>{item.failure_type ?? "quarantine"}</span>
                  <span>{new Date(item.created_at).toLocaleString()}</span>
                  {item.status === "open" ? (
                    <button
                      type="button"
                      className="task-action task-action--secondary"
                      disabled={pendingQueueAction === `restore:${item.queue_id}`}
                      onClick={() => void handleRestore(item.queue_id)}
                    >
                      {pendingQueueAction === `restore:${item.queue_id}` ? "Restoring..." : "Restore"}
                    </button>
                  ) : null}
                  {item.status === "open" ? (
                    <button
                      type="button"
                      className="task-action"
                      disabled={pendingQueueAction === `dismiss:${item.queue_id}`}
                      onClick={() => void handleDismiss(item.queue_id)}
                    >
                      {pendingQueueAction === `dismiss:${item.queue_id}` ? "Dismissing..." : "Dismiss"}
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
                </div>
              </div>
            ))}
          </div>
        </article>
      </section>
    </section>
  );
}
