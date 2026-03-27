import { useEffect, useMemo, useState } from "react";
import { OperatorLoopPanel } from "../components/OperatorLoopPanel";
import { CodexRunDetailCard } from "../components/CodexRunDetailCard";
import { fetchActivity, fetchCodexRunDetail, fetchCodexSystemDiagnostics, fetchIncidentTimeline, fetchProviders, runControlOperatorAction } from "../lib/controlRoomApi";
import { fetchBoard } from "../lib/boardApi";
import { boardCounts, formatTimestamp, openBoardTasks, resolvedBoardTasks } from "../lib/codexMvp";
import type { OperatorLoopItem, OperatorWorkflowState } from "../lib/operatorLoop";
import { getSelectedProjectId, subscribeProjectScope } from "../lib/projectScope";
import { setPendingRunFocus } from "../lib/runFocus";
import { setPendingTaskFocus } from "../lib/taskFocus";
import { useLivePulse } from "../lib/useLivePulse";
import type { ActivityItem, BoardTask, CodexRunDetailResponse, CodexSystemDiagnosticsResponse, ControlOperatorAction, ProvidersResponse, TimelineEvent } from "../types";

type ViewTarget = "work" | "issues" | "agents" | "runs" | "system" | "projects" | "command";

export function CodexSystemPage({
  onNavigate,
  operatorWorkflow,
  operatorWorkflowWarning,
  onOpenOperatorItem,
}: {
  onNavigate: (view: ViewTarget) => void;
  operatorWorkflow: OperatorWorkflowState | null;
  operatorWorkflowWarning?: string | null;
  onOpenOperatorItem: (item: OperatorLoopItem) => void;
}) {
  const [providers, setProviders] = useState<ProvidersResponse | null>(null);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [tasks, setTasks] = useState<BoardTask[]>([]);
  const [resolved, setResolved] = useState<BoardTask[]>([]);
  const [diagnostics, setDiagnostics] = useState<CodexSystemDiagnosticsResponse | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedRunDetail, setSelectedRunDetail] = useState<CodexRunDetailResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingActionKey, setPendingActionKey] = useState<string | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(() => getSelectedProjectId());
  const livePulse = useLivePulse();

  useEffect(() => subscribeProjectScope(setSelectedProjectId), []);

  async function loadSystem(signal?: AbortSignal) {
    const [providersPayload, activityPayload, timelinePayload, boardPayload, diagnosticsPayload] = await Promise.all([
      fetchProviders(signal, undefined, selectedProjectId),
      fetchActivity(signal, undefined, selectedProjectId),
      fetchIncidentTimeline({ limit: 24 }, signal, undefined, selectedProjectId),
      fetchBoard({}, signal),
      fetchCodexSystemDiagnostics(signal),
    ]);
    setProviders(providersPayload);
    setActivity(activityPayload);
    setTimeline(timelinePayload.events);
    setTasks(openBoardTasks(boardPayload.columns));
    setResolved(resolvedBoardTasks(boardPayload.columns));
    setDiagnostics(diagnosticsPayload);
  }

  useEffect(() => {
    const controller = new AbortController();
    void loadSystem(controller.signal).catch(() => setNotice("System refresh failed; showing the latest available machine state."));
    return () => controller.abort();
  }, [livePulse, selectedProjectId]);

  useEffect(() => {
    const firstRunnableJob =
      providers?.job_queue.find((job) => job.session_id && job.status === "running") ??
      providers?.job_queue.find((job) => job.session_id) ??
      null;
    const availableSessionIds = new Set(
      (providers?.job_queue ?? []).map((job) => job.session_id).filter((sessionId): sessionId is string => Boolean(sessionId))
    );
    setSelectedRunId((current) => {
      if (current && availableSessionIds.has(current)) {
        return current;
      }
      return firstRunnableJob?.session_id ?? null;
    });
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
  }, [selectedRunId, livePulse]);

  async function handleControlAction(action: ControlOperatorAction) {
    const key = `${action.action}:${action.resource_id}`;
    setPendingActionKey(key);
    setNotice(null);
    try {
      await runControlOperatorAction(action);
      await loadSystem();
      if (action.related_task_id) {
        setPendingTaskFocus(action.related_task_id);
      }
      setNotice(`${action.label} complete.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : `${action.label} failed.`);
    } finally {
      setPendingActionKey(null);
    }
  }

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
  const runtimeDiagnostics = diagnostics;

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
      {runtimeDiagnostics?.execution_state ? (
        <div className="codex-banner codex-banner--info">
          <strong>{runtimeDiagnostics.execution_state.summary}</strong>
          <span>{runtimeDiagnostics.execution_state.detail}</span>
        </div>
      ) : null}

      <OperatorLoopPanel
        workflow={operatorWorkflow}
        compact
        maxItems={3}
        title="Runtime evidence only"
        description="System is the deep evidence wall. Use Runs for live intervention and Issues for review or recovery actions."
        onSelectItem={onOpenOperatorItem}
        warning={operatorWorkflowWarning}
        footer={
          <div className="codex-detail-actions">
            <button type="button" className="codex-button codex-button--primary" onClick={() => onNavigate("runs")}>
              Open Runs
            </button>
            <button type="button" className="codex-button" onClick={() => onNavigate("issues")}>
              Open Issues
            </button>
            <button type="button" className="codex-button" onClick={() => onNavigate("command")}>
              Open Command
            </button>
          </div>
        }
      />

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
          <strong>{runtimeDiagnostics?.summary.stale_agents ?? 0}</strong>
          <span>Stale agents</span>
          <p>
            {runtimeDiagnostics?.summary.suppressed_items
              ? `${runtimeDiagnostics.summary.suppressed_items} suppressed issue${runtimeDiagnostics.summary.suppressed_items === 1 ? "" : "s"}`
              : runtimeDiagnostics?.summary.oldest_queued_at
                ? `Oldest queued ${formatTimestamp(runtimeDiagnostics.summary.oldest_queued_at)}`
                : "No queued backlog"}
          </p>
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
              <span>{runtimeDiagnostics?.queue_pressure.oldest_queued_at ? formatTimestamp(runtimeDiagnostics.queue_pressure.oldest_queued_at) : "No queued jobs."}</span>
            </div>
            <div className="codex-run-item">
              <div className="codex-run-item__meta">
                <strong>Oldest running job</strong>
                <span>{providers?.job_queue?.filter((job) => job.status === "running").length ?? 0}</span>
              </div>
              <span>{runtimeDiagnostics?.queue_pressure.oldest_running_at ? formatTimestamp(runtimeDiagnostics.queue_pressure.oldest_running_at) : "No active jobs."}</span>
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

        <section className="codex-panel">
          <div className="codex-panel__header">
            <div>
              <span className="codex-kicker">Needs inspection</span>
              <h2>Suspect runs and stale agents</h2>
            </div>
          </div>
          <div className="codex-run-list">
            {(runtimeDiagnostics?.suspect_runs ?? []).map((run) => (
              <button
                key={run.session_id}
                type="button"
                className="codex-run-item codex-run-item--interactive"
                onClick={() => {
                  setSelectedRunId(run.session_id);
                  setPendingRunFocus(run.session_id);
                  onNavigate("runs");
                }}
              >
                <div className="codex-run-item__meta">
                  <strong>{run.issue_key ?? run.task_title ?? run.session_id}</strong>
                  <span>{run.is_stale ? "stale run" : run.status.replaceAll("_", " ")}</span>
                </div>
                <span>{run.diagnostic_summary ?? run.status_message ?? run.provider_type}</span>
                <span>{run.recommended_action ?? "Open the run page for detail."}</span>
              </button>
            ))}
            {(runtimeDiagnostics?.stale_agents ?? []).map((agent) => (
              <button
                key={agent.agent_id}
                type="button"
                className="codex-run-item codex-run-item--interactive"
                onClick={() => onNavigate("agents")}
              >
                <div className="codex-run-item__meta">
                  <strong>{agent.display_name}</strong>
                  <span>stale agent</span>
                </div>
                <span>{agent.diagnostic_summary ?? "Agent heartbeat is stale."}</span>
                <span>{agent.recommended_action ?? "Open the agent page for detail."}</span>
              </button>
            ))}
            {!(runtimeDiagnostics?.suspect_runs.length || runtimeDiagnostics?.stale_agents.length) ? (
              <div className="codex-empty-copy">No suspect runs or stale agents need inspection right now.</div>
            ) : null}
          </div>
        </section>
      </div>

      <div className="codex-two-column">
        <section className="codex-panel">
          <div className="codex-panel__header">
            <div>
              <span className="codex-kicker">Attention now</span>
              <h2>Cross-loop pressure</h2>
            </div>
          </div>
          <div className="codex-history-list">
            {(runtimeDiagnostics?.attention_items ?? []).map((item, index) => (
              <div key={`${item.kind}:${item.session_id ?? item.task_id ?? index}`} className="codex-history-item">
                <div className="codex-history-item__meta">
                  <strong>{item.title}</strong>
                  <span>{item.kind.replaceAll("_", " ")}</span>
                </div>
                <span>{item.summary ?? "Attention item"}</span>
                {item.detail ? <span>{item.detail}</span> : null}
                <div className="codex-detail-actions">
                  {item.session_id ? (
                    <button
                      type="button"
                      className="codex-button"
                      onClick={() => {
                        const sessionId = item.session_id ?? null;
                        if (!sessionId) {
                          return;
                        }
                        setSelectedRunId(sessionId);
                        setPendingRunFocus(sessionId);
                        onNavigate("runs");
                      }}
                    >
                      Open run
                    </button>
                  ) : null}
                  {item.task_id ? (
                    <button
                      type="button"
                      className="codex-button"
                      onClick={() => {
                        setPendingTaskFocus(item.task_id!);
                        onNavigate("issues");
                      }}
                    >
                      Open issue
                    </button>
                  ) : null}
                  {item.operator_action ? (
                    <button
                      type="button"
                      className="codex-button codex-button--primary"
                      disabled={pendingActionKey === `${item.operator_action.action}:${item.operator_action.resource_id}`}
                      onClick={() => void handleControlAction(item.operator_action!)}
                    >
                      {pendingActionKey === `${item.operator_action.action}:${item.operator_action.resource_id}` ? "Running..." : item.operator_action.label}
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
            {!runtimeDiagnostics?.attention_items?.length ? (
              <div className="codex-empty-copy">No cross-loop attention items are active right now.</div>
            ) : null}
          </div>
        </section>

        <section className="codex-panel">
          <div className="codex-panel__header">
            <div>
              <span className="codex-kicker">Suppression</span>
              <h2>Recovery backpressure and automation holds</h2>
            </div>
            <span className="codex-chip">{runtimeDiagnostics?.suppression?.summary.total ?? 0} items</span>
          </div>
          <div className="codex-inline-facts">
            <span className="codex-chip">{runtimeDiagnostics?.suppression?.summary.retry_backoff ?? 0} backoff</span>
            <span className="codex-chip">{runtimeDiagnostics?.suppression?.summary.circuit_breaker ?? 0} breakers</span>
            <span className="codex-chip">{runtimeDiagnostics?.suppression?.summary.quarantine ?? 0} quarantine</span>
            <span className="codex-chip">{runtimeDiagnostics?.suppression?.summary.repeated_failure ?? 0} repeated failures</span>
          </div>
          <div className="codex-run-list">
            {(runtimeDiagnostics?.suppression?.items ?? []).map((item, index) => (
              <div key={`${item.kind}:${item.task_id ?? index}`} className="codex-run-item">
                <div className="codex-run-item__meta">
                  <strong>{item.task_title ?? item.task_id ?? item.kind}</strong>
                  <span>{item.kind.replaceAll("_", " ")}</span>
                </div>
                <span>{item.summary ?? "Suppressed work"}</span>
                <span>{item.since_at ? `Since ${formatTimestamp(item.since_at)}` : item.detail ?? "No further detail recorded."}</span>
                <div className="codex-detail-actions">
                  {item.task_id ? (
                    <button
                      type="button"
                      className="codex-button"
                      onClick={() => {
                        setPendingTaskFocus(item.task_id!);
                        onNavigate("issues");
                      }}
                    >
                      Open issue
                    </button>
                  ) : null}
                  {item.operator_action ? (
                    <button
                      type="button"
                      className="codex-button codex-button--primary"
                      disabled={pendingActionKey === `${item.operator_action.action}:${item.operator_action.resource_id}`}
                      onClick={() => void handleControlAction(item.operator_action!)}
                    >
                      {pendingActionKey === `${item.operator_action.action}:${item.operator_action.resource_id}` ? "Running..." : item.operator_action.label}
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
            {!runtimeDiagnostics?.suppression?.items?.length ? (
              <div className="codex-empty-copy">No automation holds are suppressing work right now.</div>
            ) : null}
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
            <CodexRunDetailCard
              run={selectedRunDetail}
              actions={
                <>
                  {selectedRunDetail.task_id ? (
                    <button
                      type="button"
                      className="codex-button codex-button--primary"
                      onClick={() => {
                        setPendingTaskFocus(selectedRunDetail.task_id!);
                        onNavigate("work");
                      }}
                    >
                      Open issue
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="codex-button"
                    onClick={() => {
                      setPendingRunFocus(selectedRunDetail.session_id);
                      onNavigate("runs");
                    }}
                  >
                    Open run page
                  </button>
                </>
              }
            />
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
