import { useEffect, useMemo, useState } from "react";
import { fetchActivity, fetchAgentRoster, fetchCodexRunDetail, fetchIncidentTimeline, fetchProviders } from "../lib/controlRoomApi";
import { fetchBoard } from "../lib/boardApi";
import { boardCounts, formatTimestamp, openBoardTasks, resolvedBoardTasks } from "../lib/codexMvp";
import { setPendingTaskFocus } from "../lib/taskFocus";
import { useLivePulse } from "../lib/useLivePulse";
import type { ActivityItem, AgentRosterResponse, BoardTask, CodexRunDetailResponse, ProvidersResponse, TimelineEvent } from "../types";

type ViewTarget = "work" | "issues" | "agents" | "system" | "projects" | "command";

export function CodexSystemPage({ onNavigate }: { onNavigate: (view: ViewTarget) => void }) {
  const [providers, setProviders] = useState<ProvidersResponse | null>(null);
  const [roster, setRoster] = useState<AgentRosterResponse | null>(null);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [tasks, setTasks] = useState<BoardTask[]>([]);
  const [resolved, setResolved] = useState<BoardTask[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedRunDetail, setSelectedRunDetail] = useState<CodexRunDetailResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const livePulse = useLivePulse();

  async function loadSystem(signal?: AbortSignal) {
    const [providersPayload, rosterPayload, activityPayload, timelinePayload, boardPayload] = await Promise.all([
      fetchProviders(),
      fetchAgentRoster(),
      fetchActivity(),
      fetchIncidentTimeline({ limit: 24 }, signal),
      fetchBoard({}, signal),
    ]);
    setProviders(providersPayload);
    setRoster(rosterPayload);
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

  useEffect(() => {
    const firstRunnableJob =
      providers?.job_queue.find((job) => job.session_id && job.status === "running") ??
      providers?.job_queue.find((job) => job.session_id) ??
      null;
    setSelectedRunId((current) => current ?? firstRunnableJob?.session_id ?? null);
  }, [providers?.job_queue]);

  useEffect(() => {
    if (!selectedRunId) {
      setSelectedRunDetail(null);
      return;
    }
    const controller = new AbortController();
    void fetchCodexRunDetail(selectedRunId, controller.signal)
      .then((payload) => setSelectedRunDetail(payload))
      .catch((error) => {
        if (!(error instanceof Error && error.name === "AbortError")) {
          setSelectedRunDetail(null);
        }
      });
    return () => controller.abort();
  }, [selectedRunId]);

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
  const runtimeDiagnostics = useMemo(() => {
    const queuedJobs = providers?.job_queue?.filter((job) => job.status === "queued") ?? [];
    const runningJobs = providers?.job_queue?.filter((job) => job.status === "running") ?? [];
    const staleAgents = (roster?.agents ?? []).filter((agent) => (agent.heartbeat_age_seconds ?? 0) >= 90);
    const oldestQueued = queuedJobs.reduce<string | null>((oldest, job) => {
      if (!oldest || job.created_at < oldest) {
        return job.created_at;
      }
      return oldest;
    }, null);
    const oldestRunning = runningJobs.reduce<string | null>((oldest, job) => {
      const candidate = job.started_at ?? job.created_at;
      if (!oldest || candidate < oldest) {
        return candidate;
      }
      return oldest;
    }, null);
    return {
      staleAgents: staleAgents.length,
      oldestQueued,
      oldestRunning,
    };
  }, [providers, roster]);

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
        <article className="codex-panel codex-stat">
          <strong>{runtimeDiagnostics.staleAgents}</strong>
          <span>Stale agents</span>
          <p>{runtimeDiagnostics.oldestQueued ? `Oldest queued ${formatTimestamp(runtimeDiagnostics.oldestQueued)}` : "No queued backlog"}</p>
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
            <div className="codex-run-item">
              <div className="codex-run-item__meta">
                <strong>Oldest queued job</strong>
                <span>{providers?.job_queue?.filter((job) => job.status === "queued").length ?? 0}</span>
              </div>
              <span>{runtimeDiagnostics.oldestQueued ? formatTimestamp(runtimeDiagnostics.oldestQueued) : "No queued jobs."}</span>
            </div>
            <div className="codex-run-item">
              <div className="codex-run-item__meta">
                <strong>Oldest running job</strong>
                <span>{providers?.job_queue?.filter((job) => job.status === "running").length ?? 0}</span>
              </div>
              <span>{runtimeDiagnostics.oldestRunning ? formatTimestamp(runtimeDiagnostics.oldestRunning) : "No active jobs."}</span>
            </div>
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
              <span className="codex-kicker">Run surface</span>
              <h2>Queued and active sessions</h2>
            </div>
          </div>
          <div className="codex-run-list">
            {(providers?.job_queue ?? []).length ? (
              (providers?.job_queue ?? []).map((job) => (
                <button
                  key={job.job_id}
                  type="button"
                  className={`codex-run-item codex-run-item--interactive ${job.session_id === selectedRunId ? "is-selected" : ""}`}
                  onClick={() => setSelectedRunId(job.session_id ?? null)}
                  disabled={!job.session_id}
                >
                  <div className="codex-run-item__meta">
                    <strong>{job.title ?? job.task_id}</strong>
                    <span>{job.status.replaceAll("_", " ")}</span>
                  </div>
                  <span>{job.provider_id.replaceAll("_", " ")} · {job.agent_name ?? job.agent_id}</span>
                  <span>{formatTimestamp(job.started_at ?? job.created_at)}</span>
                </button>
              ))
            ) : (
              <div className="codex-empty-copy">No queued or running provider jobs are visible right now.</div>
            )}
          </div>
        </section>

        <section className="codex-panel">
          <div className="codex-panel__header">
            <div>
              <span className="codex-kicker">Selected run</span>
              <h2>Trace and runtime output</h2>
            </div>
          </div>
          {selectedRunDetail ? (
            <div className="codex-detail-stack">
              <div className="codex-review-callout">
                <strong>{selectedRunDetail.status_message ?? "No runtime summary recorded."}</strong>
                <p>
                  {selectedRunDetail.task_title ?? selectedRunDetail.task_id ?? "Unlinked issue"} ·{" "}
                  {selectedRunDetail.provider_type.replaceAll("_", " ")} · {selectedRunDetail.execution_mode?.replaceAll("_", " ") ?? "unknown mode"} ·{" "}
                  started {formatTimestamp(selectedRunDetail.started_at)}
                </p>
                <div className="codex-review-facts">
                  <div className="codex-review-fact">
                    <span>Status</span>
                    <strong>{selectedRunDetail.status.replaceAll("_", " ")}</strong>
                  </div>
                  <div className="codex-review-fact">
                    <span>Progress</span>
                    <strong>{selectedRunDetail.progress_pct ?? 0}%</strong>
                  </div>
                  <div className="codex-review-fact">
                    <span>Artifacts</span>
                    <strong>{selectedRunDetail.artifacts.length}</strong>
                  </div>
                </div>
              </div>
              {selectedRunDetail.output_preview?.content ? (
                <pre className="codex-output-preview__content">{selectedRunDetail.output_preview.content}</pre>
              ) : (
                <div className="codex-empty-copy">No runtime output preview is available for the selected run yet.</div>
              )}
              {selectedRunDetail.task_id ? (
                <div className="codex-detail-actions">
                  <button
                    type="button"
                    className="codex-button"
                    onClick={() => {
                      setPendingTaskFocus(selectedRunDetail.task_id!);
                      onNavigate("work");
                    }}
                  >
                    Open issue
                  </button>
                </div>
              ) : null}
            </div>
          ) : (
            <div className="codex-empty-copy">Select a queued or running session to inspect its trace.</div>
          )}
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
