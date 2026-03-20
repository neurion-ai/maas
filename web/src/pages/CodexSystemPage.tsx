import { useEffect, useMemo, useState } from "react";
import { fetchActivity, fetchIncidentTimeline, fetchProviders } from "../lib/controlRoomApi";
import { fetchBoard } from "../lib/boardApi";
import { boardCounts, formatTimestamp, openBoardTasks, resolvedBoardTasks } from "../lib/codexMvp";
import { setPendingTaskFocus } from "../lib/taskFocus";
import { useLivePulse } from "../lib/useLivePulse";
import type { ActivityItem, BoardTask, ProvidersResponse, TimelineEvent } from "../types";

type ViewTarget = "work" | "issues" | "agents" | "system" | "projects" | "command";

export function CodexSystemPage({ onNavigate }: { onNavigate: (view: ViewTarget) => void }) {
  const [providers, setProviders] = useState<ProvidersResponse | null>(null);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [tasks, setTasks] = useState<BoardTask[]>([]);
  const [resolved, setResolved] = useState<BoardTask[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const livePulse = useLivePulse();

  async function loadSystem(signal?: AbortSignal) {
    const [providersPayload, activityPayload, timelinePayload, boardPayload] = await Promise.all([
      fetchProviders(),
      fetchActivity(),
      fetchIncidentTimeline({ limit: 24 }, signal),
      fetchBoard({}, signal),
    ]);
    setProviders(providersPayload);
    setActivity(activityPayload);
    setTimeline(timelinePayload.events);
    setTasks(openBoardTasks(boardPayload.columns));
    setResolved(resolvedBoardTasks(boardPayload.columns));
  }

  useEffect(() => {
    const controller = new AbortController();
    void loadSystem(controller.signal).catch(() => setNotice("System refresh failed; showing the latest available machine state."));
    return () => controller.abort();
  }, [livePulse]);

  const counts = useMemo(() => boardCounts([{ key: "ready", title: "Ready", tasks }, { key: "done", title: "Done", tasks: resolved }]), [tasks, resolved]);
  const providerSummary = useMemo(() => {
    return (providers?.providers ?? []).reduce(
      (summary, provider) => {
        summary.total += 1;
        const preflightStatus = provider.latest_preflight?.status ?? null;
        const executionMode = provider.effective_execution_mode ?? provider.execution_mode;
        const isSimulation = executionMode === "local_simulation" || preflightStatus === "simulation_ready";
        const isLiveReady =
          !isSimulation &&
          (provider.status === "configured" ||
            provider.status === "available" ||
            preflightStatus === "passed" ||
            (provider.is_runnable ?? false));
        if (isLiveReady) {
          summary.liveReady += 1;
        } else if (isSimulation) {
          summary.simulation += 1;
        }
        if (provider.status === "misconfigured") {
          summary.issues += 1;
        }
        summary.queued += provider.job_summary?.queued_jobs ?? 0;
        summary.running += provider.job_summary?.running_jobs ?? 0;
        return summary;
      },
      { total: 0, liveReady: 0, simulation: 0, issues: 0, queued: 0, running: 0 }
    );
  }, [providers]);

  return (
    <section className="codex-page">
      <header className="codex-page__header">
        <div>
          <span className="codex-kicker">System</span>
          <h1>Logs, metrics, traces, and machine health</h1>
          <p>This is the deep operational page: queue health, runtime posture, logged actions, and recent system-wide traces.</p>
        </div>
      </header>

      {notice ? <div className="codex-banner">{notice}</div> : null}

      <div className="codex-metric-grid">
        <article className="codex-panel codex-stat">
          <strong>{tasks.length}</strong>
          <span>Open issues</span>
          <p>{counts.in_progress} active · {counts.review} review</p>
        </article>
        <article className="codex-panel codex-stat">
          <strong>{providerSummary.liveReady}</strong>
          <span>Live-ready runtimes</span>
          <p>{providerSummary.simulation} simulation · {providerSummary.issues} with issues</p>
        </article>
        <article className="codex-panel codex-stat">
          <strong>{providerSummary.running}</strong>
          <span>Running jobs</span>
          <p>{providerSummary.queued} queued</p>
        </article>
        <article className="codex-panel codex-stat">
          <strong>{activity.length}</strong>
          <span>Recent log entries</span>
          <p>{timeline.length} timeline events loaded</p>
        </article>
      </div>

      <div className="codex-two-column">
        <section className="codex-panel">
          <div className="codex-panel__header">
            <div>
              <span className="codex-kicker">Runtime posture</span>
              <h2>Codex execution surface</h2>
            </div>
          </div>
          <div className="codex-run-list">
            {(providers?.providers ?? []).map((provider) => (
              <div key={provider.id} className="codex-run-item">
                <div className="codex-run-item__meta">
                  <strong>{provider.name}</strong>
                  <span>{(provider.effective_execution_mode ?? provider.execution_mode).replaceAll("_", " ")}</span>
                </div>
                <span>
                  {(provider.effective_execution_mode ?? provider.execution_mode) === "local_simulation"
                    ? "simulation"
                    : provider.latest_preflight?.status ?? "not checked"}
                </span>
                <span>{formatTimestamp(provider.latest_preflight?.checked_at ?? null)}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="codex-panel">
          <div className="codex-panel__header">
            <div>
              <span className="codex-kicker">Queue health</span>
              <h2>Active flow</h2>
            </div>
          </div>
          <div className="codex-run-list">
            <button
              type="button"
              className="codex-run-item codex-run-item--interactive"
              onClick={() => onNavigate("work")}
            >
              <div className="codex-run-item__meta">
                <strong>Todo</strong>
                <span>{counts.ready + counts.assigned + counts.planned}</span>
              </div>
              <span>{counts.ready} ready · {counts.assigned} assigned · {counts.planned} planned</span>
            </button>
            <button
              type="button"
              className="codex-run-item codex-run-item--interactive"
              onClick={() => onNavigate("work")}
            >
              <div className="codex-run-item__meta">
                <strong>In progress</strong>
                <span>{counts.in_progress}</span>
              </div>
              <span>Actively running work.</span>
            </button>
            <button
              type="button"
              className="codex-run-item codex-run-item--interactive"
              onClick={() => onNavigate("issues")}
            >
              <div className="codex-run-item__meta">
                <strong>Review</strong>
                <span>{counts.review}</span>
              </div>
              <span>Waiting on operator or review desk action.</span>
            </button>
            <button
              type="button"
              className="codex-run-item codex-run-item--interactive"
              onClick={() => onNavigate("issues")}
            >
              <div className="codex-run-item__meta">
                <strong>Blocked</strong>
                <span>{counts.blocked}</span>
              </div>
              <span>Stopped by dependency, failure, or operator decision.</span>
            </button>
          </div>
        </section>
      </div>

      <div className="codex-two-column">
        <section className="codex-panel">
          <div className="codex-panel__header">
            <div>
              <span className="codex-kicker">Logs</span>
              <h2>Recent machine actions</h2>
            </div>
          </div>
          <div className="codex-history-list">
            {activity.map((item, index) => (
              <button
                key={`${item.activity_id ?? index}:${item.created_at}`}
                type="button"
                className={`codex-history-item codex-history-item--interactive ${item.task_id ? "is-clickable" : ""}`}
                onClick={() => {
                  if (!item.task_id) {
                    return;
                  }
                  setPendingTaskFocus(item.task_id);
                  onNavigate("issues");
                }}
                disabled={!item.task_id}
              >
                <div className="codex-history-item__meta">
                  <strong>{item.action.replaceAll("_", " ")}</strong>
                  <span>{formatTimestamp(item.created_at)}</span>
                </div>
                <span>{item.description}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="codex-panel">
          <div className="codex-panel__header">
            <div>
              <span className="codex-kicker">Trace</span>
              <h2>Recent event stream</h2>
            </div>
          </div>
          <div className="codex-history-list">
            {timeline.map((event) => (
              <button
                key={`${event.source}:${event.event_id}`}
                type="button"
                className={`codex-history-item codex-history-item--interactive ${event.task_id ? "is-clickable" : ""}`}
                onClick={() => {
                  if (!event.task_id) {
                    return;
                  }
                  setPendingTaskFocus(event.task_id);
                  onNavigate("issues");
                }}
                disabled={!event.task_id}
              >
                <div className="codex-history-item__meta">
                  <strong>{event.title}</strong>
                  <span>{formatTimestamp(event.created_at)}</span>
                </div>
                <span>{event.description}</span>
              </button>
            ))}
          </div>
        </section>
      </div>
    </section>
  );
}
