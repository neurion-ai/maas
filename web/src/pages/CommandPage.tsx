import { useEffect, useMemo, useState } from "react";
import { OperatorLoopPanel } from "../components/OperatorLoopPanel";
import {
  fetchAlerts,
  fetchAgentRoster,
  fetchAutopilotStatus,
  fetchCodexIssueIndex,
  fetchCodexRetrievalSearch,
  fetchIncidentTimeline,
  fetchOverview,
  fetchPortfolio,
  runOrchestratorPass,
  updateProjectAutopilot,
  updateProjectProviderCapacity,
} from "../lib/controlRoomApi";
import { boardCounts, describeLaunchPosture, formatTimestamp, issueKeyMap } from "../lib/codexMvp";
import { getSelectedProjectId } from "../lib/projectScope";
import { setPendingRunFocus } from "../lib/runFocus";
import { setPendingTaskFocus } from "../lib/taskFocus";
import { useLivePulse } from "../lib/useLivePulse";
import type { AlertItem, AutopilotStatusResponse, BoardTask, CodexRetrievalSearchResponse, OverviewResponse, PortfolioProject, TimelineEvent } from "../types";
import type { OperatorLoopItem, OperatorWorkflowState } from "../lib/operatorLoop";

type ViewTarget = "work" | "issues" | "agents" | "runs" | "system" | "projects";

const RUN_CONTROL_MIN_PENDING_MS = 900;

function issueLabel(task: BoardTask, fallbackKeys: Map<string, string>) {
  return task.issue_key ?? fallbackKeys.get(task.task_id) ?? task.task_id;
}

export function CommandPage({
  onNavigate,
  operatorWorkflow,
  onOpenOperatorItem,
  operatorWorkflowWarning,
}: {
  onNavigate: (view: ViewTarget) => void;
  operatorWorkflow: OperatorWorkflowState | null;
  onOpenOperatorItem: (item: OperatorLoopItem) => void;
  operatorWorkflowWarning?: string | null;
}) {
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [tasks, setTasks] = useState<BoardTask[]>([]);
  const [resolved, setResolved] = useState<BoardTask[]>([]);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [project, setProject] = useState<PortfolioProject | null>(null);
  const [autopilot, setAutopilot] = useState<AutopilotStatusResponse | null>(null);
  const [runningAgents, setRunningAgents] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [recentFailureCount, setRecentFailureCount] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");
  const [retrieval, setRetrieval] = useState<CodexRetrievalSearchResponse | null>(null);
  const [retrievalNotice, setRetrievalNotice] = useState<string | null>(null);
  const livePulse = useLivePulse();

  async function loadCommand(signal?: AbortSignal) {
    const [issueIndexPayload, overviewPayload, alertsPayload, timelinePayload, rosterPayload, portfolioPayload, autopilotPayload] = await Promise.all([
      fetchCodexIssueIndex(signal),
      fetchOverview(),
      fetchAlerts(),
      fetchIncidentTimeline({ limit: 18 }, signal),
      fetchAgentRoster(),
      fetchPortfolio(),
      fetchAutopilotStatus(signal),
    ]);
    setOverview(overviewPayload);
    setTasks([
      ...issueIndexPayload.queue.review.items,
      ...issueIndexPayload.queue.blocked_failures.items,
      ...issueIndexPayload.queue.blocked_dependencies.items,
    ]);
    setResolved(issueIndexPayload.resolved);
    setAlerts(alertsPayload.alerts);
    setRecentFailureCount(issueIndexPayload.summary.recent_failures);
    setTimeline(timelinePayload.events);
    setRunningAgents(rosterPayload.agents.filter((agent) => agent.status === "running").length);
    setAutopilot(autopilotPayload);
    const selectedProjectId = getSelectedProjectId();
    setProject(
      portfolioPayload.projects.find((item) => item.project_id === selectedProjectId) ??
        portfolioPayload.projects[0] ??
        null
    );
  }

  useEffect(() => {
    const controller = new AbortController();
    void loadCommand(controller.signal).catch(() => setNotice("Command refresh failed; showing the latest available state."));
    return () => controller.abort();
  }, [livePulse]);

  useEffect(() => {
    const trimmed = searchQuery.trim();
    if (trimmed.length < 2) {
      setRetrieval(null);
      setRetrievalNotice(null);
      return;
    }
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      void fetchCodexRetrievalSearch({ search: trimmed }, controller.signal)
        .then((payload) => {
          setRetrieval(payload);
          setRetrievalNotice(null);
        })
        .catch((error) => {
          if (!(error instanceof Error && error.name === "AbortError")) {
            setRetrieval(null);
            setRetrievalNotice("Search refresh failed. Retrieval results could not be loaded for this query.");
          }
        });
    }, 180);
    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [searchQuery]);

  const keyMap = useMemo(() => issueKeyMap([{ key: "ready", title: "Ready", tasks }, { key: "done", title: "Done", tasks: resolved }]), [tasks, resolved]);
  const counts = useMemo(() => boardCounts([{ key: "ready", title: "Ready", tasks }, { key: "done", title: "Done", tasks: resolved }]), [tasks, resolved]);

  const queue = useMemo(() => [...tasks].sort((left, right) => right.priority - left.priority).slice(0, 6), [tasks]);
  const launchPosture = useMemo(() => describeLaunchPosture(project), [project]);

  async function holdPendingState(startedAt: number) {
    const remaining = RUN_CONTROL_MIN_PENDING_MS - (Date.now() - startedAt);
    if (remaining > 0) {
      await new Promise((resolve) => window.setTimeout(resolve, remaining));
    }
  }

  async function handleRun() {
    const startedAt = Date.now();
    setPendingKey("run");
    setNotice(null);
    try {
      const result = await runOrchestratorPass(6, 4, true);
      await loadCommand();
      await holdPendingState(startedAt);
      await loadCommand();
      const queued = result.provider_jobs_queued ?? 0;
      const started = (result.provider_jobs_processed ?? 0) + (result.provider_jobs_dispatched ?? 0);
      const launchProvider = result.project_runs.find((item) => item.launch_provider_id)?.launch_provider_id ?? null;
      if (started === 0 && queued === 0 && launchPosture.mode === "running" && tasks.some((task) => task.status === "assigned")) {
        setNotice(
          launchProvider
            ? `Cycle complete: assigned work is waiting on ${launchProvider.replaceAll("_", " ")} capacity or readiness, so no new run started yet.`
            : "Cycle complete: no launch-ready provider is available for the assigned work."
        );
      } else {
        setNotice(
          `Cycle complete: ${result.assigned_count} assignments, ${started} run${started === 1 ? "" : "s"} started, ${queued} queued${launchPosture.mode !== "running" ? " while launches were not fully open" : ""}.`
        );
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Run failed.");
    } finally {
      setPendingKey(null);
    }
  }

  async function handlePause() {
    if (!project) {
      return;
    }
    const startedAt = Date.now();
    setPendingKey("pause");
    setNotice(null);
    try {
      await updateProjectProviderCapacity(project.project_id, {
        queue_mode: "paused",
        max_running_jobs: project.provider_capacity.max_running_jobs,
        preferred_provider_id: project.provider_capacity.preferred_provider_id ?? null,
      });
      await loadCommand();
      await holdPendingState(startedAt);
      await loadCommand();
      setNotice("Paused new Codex launches. Active runs will continue until they finish.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Pause failed.");
    } finally {
      setPendingKey(null);
    }
  }

  async function handleResume() {
    if (!project) {
      return;
    }
    const startedAt = Date.now();
    setPendingKey("resume");
    setNotice(null);
    try {
      await updateProjectProviderCapacity(project.project_id, {
        queue_mode: "running",
        max_running_jobs: project.provider_capacity.max_running_jobs,
        preferred_provider_id: project.provider_capacity.preferred_provider_id ?? null,
      });
      const result = await runOrchestratorPass(6, 4, true);
      await loadCommand();
      await holdPendingState(startedAt);
      await loadCommand();
      const started = (result.provider_jobs_processed ?? 0) + (result.provider_jobs_dispatched ?? 0);
      setNotice(`Resumed execution. ${started} run${started === 1 ? "" : "s"} started.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Resume failed.");
    } finally {
      setPendingKey(null);
    }
  }

  async function handleDrain() {
    if (!project) {
      return;
    }
    const startedAt = Date.now();
    setPendingKey("drain");
    setNotice(null);
    try {
      await updateProjectProviderCapacity(project.project_id, {
        queue_mode: "draining",
        max_running_jobs: project.provider_capacity.max_running_jobs,
        preferred_provider_id: project.provider_capacity.preferred_provider_id ?? null,
      });
      await loadCommand();
      await holdPendingState(startedAt);
      await loadCommand();
      setNotice("Queue is draining. Running and queued work can finish, but new assigned issues will not launch.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Drain failed.");
    } finally {
      setPendingKey(null);
    }
  }

  async function handleAutopilotToggle(enabled: boolean) {
    if (!project || !autopilot) {
      return;
    }
    const startedAt = Date.now();
    setPendingKey(enabled ? "autopilot-enable" : "autopilot-disable");
    setNotice(null);
    try {
      await updateProjectAutopilot(project.project_id, {
        enabled,
        interval_seconds: autopilot.policy.interval_seconds,
        allocate_limit: autopilot.policy.allocate_limit,
        provider_job_limit: autopilot.policy.provider_job_limit,
        auto_launch_assigned_work: autopilot.policy.auto_launch_assigned_work,
        process_notifications: autopilot.policy.process_notifications,
        notification_batch_limit: autopilot.policy.notification_batch_limit,
      });
      await loadCommand();
      await holdPendingState(startedAt);
      await loadCommand();
      setNotice(enabled ? "Autopilot enabled for this project." : "Autopilot disabled for this project.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not update autopilot.");
    } finally {
      setPendingKey(null);
    }
  }

  return (
    <section className="codex-page">
      <header className="codex-page__header">
        <div>
          <span className="codex-kicker">Command</span>
          <h1>What needs judgment, what is moving, and what just landed</h1>
          <p>Use this page to decide what needs intervention now, not to micromanage every task.</p>
        </div>
        <div className="codex-page__actions">
          <button type="button" className="codex-button codex-button--primary" disabled={pendingKey !== null} onClick={() => void handleRun()}>
            {pendingKey === "run" ? "Running..." : "Run next cycle"}
          </button>
          {launchPosture.mode === "running" ? (
            <>
              <button type="button" className="codex-button" disabled={pendingKey !== null || !project} onClick={() => void handleDrain()}>
                {pendingKey === "drain" ? "Draining..." : "Drain queue"}
              </button>
              <button type="button" className="codex-button" disabled={pendingKey !== null || !project} onClick={() => void handlePause()}>
                {pendingKey === "pause" ? "Pausing..." : "Pause launches"}
              </button>
            </>
          ) : launchPosture.mode === "draining" ? (
            <>
              <button type="button" className="codex-button" disabled={pendingKey !== null || !project} onClick={() => void handleResume()}>
                {pendingKey === "resume" ? "Resuming..." : "Resume launches"}
              </button>
              <button type="button" className="codex-button" disabled={pendingKey !== null || !project} onClick={() => void handlePause()}>
                {pendingKey === "pause" ? "Pausing..." : "Pause launches"}
              </button>
            </>
          ) : (
            <button type="button" className="codex-button" disabled={pendingKey !== null || !project} onClick={() => void handleResume()}>
              {pendingKey === "resume" ? "Resuming..." : "Resume launches"}
            </button>
          )}
        </div>
      </header>

      <div className="codex-metric-grid">
        <article className="codex-panel codex-stat">
          <strong>{tasks.length}</strong>
          <span>Open issues</span>
          <p>{counts.in_progress} active · {counts.blocked} blocked</p>
        </article>
        <article className="codex-panel codex-stat">
          <strong>{runningAgents}</strong>
          <span>Active agents</span>
          <p>{overview?.summary.tasks_in_progress ?? 0} tasks currently running</p>
        </article>
        <article className="codex-panel codex-stat">
          <strong>{launchPosture.label}</strong>
          <span>Launch posture</span>
          <p>{launchPosture.summary}</p>
        </article>
        <article className="codex-panel codex-stat">
          <strong>{resolved.length}</strong>
          <span>Resolved</span>
          <p>Finished work remains searchable in Issues.</p>
        </article>
        <article className="codex-panel codex-stat">
          <strong>{queue.length}</strong>
          <span>Needs judgment</span>
          <p>{alerts.filter((alert) => alert.status === "open").length} open alerts · {recentFailureCount} recent failures</p>
        </article>
      </div>

      <OperatorLoopPanel
        workflow={operatorWorkflow}
        title="Shared inbox and execution posture"
        description="Command owns the loop posture. Use Issues for review or recovery decisions and Runs for live-session intervention."
        onSelectItem={onOpenOperatorItem}
        warning={operatorWorkflowWarning}
        footer={
          <div className="codex-detail-actions">
            {autopilot?.policy.enabled ? (
              <button
                type="button"
                className="codex-button"
                disabled={pendingKey !== null || !project}
                onClick={() => void handleAutopilotToggle(false)}
              >
                {pendingKey === "autopilot-disable" ? "Disabling..." : "Disable autopilot"}
              </button>
            ) : (
              <button
                type="button"
                className="codex-button codex-button--primary"
                disabled={pendingKey !== null || !project}
                onClick={() => void handleAutopilotToggle(true)}
              >
                {pendingKey === "autopilot-enable" ? "Enabling..." : "Enable autopilot"}
              </button>
            )}
            <button type="button" className="codex-button" onClick={() => onNavigate("issues")}>
              Open Issues
            </button>
            <button type="button" className="codex-button" onClick={() => onNavigate("runs")}>
              Open Runs
            </button>
          </div>
        }
      />

      {notice ? <div className="codex-banner">{notice}</div> : null}

      <section className="codex-panel">
        <div className="codex-panel__header">
          <div>
            <span className="codex-kicker">Retrieval</span>
            <h2>Search prior work, runs, artifacts, and machine history</h2>
          </div>
        </div>
        <div className="codex-search-panel">
          <label className="field-control field-control--search">
            <span>Search memory</span>
            <input
              type="search"
              value={searchQuery}
              placeholder="Search issues, runs, artifacts, and recent activity"
              onChange={(event) => setSearchQuery(event.target.value)}
            />
          </label>
          <div className="hero-meta">
            <span className="hero-meta__pill">{retrieval?.summary.issue_hits ?? 0} issues</span>
            <span className="hero-meta__pill">{retrieval?.summary.run_hits ?? 0} runs</span>
            <span className="hero-meta__pill">{retrieval?.summary.artifact_hits ?? 0} artifacts</span>
            <span className="hero-meta__pill">{retrieval?.summary.event_hits ?? 0} events</span>
            <span className="hero-meta__pill">{retrieval?.summary.memory_hits ?? 0} memory</span>
          </div>
        </div>
        {retrievalNotice ? <p className="field-hint">{retrievalNotice}</p> : null}
        {searchQuery.trim().length < 2 ? (
          <div className="codex-empty-copy">Type at least two characters to search the wider project memory.</div>
        ) : (
          <div className="codex-three-column codex-three-column--dense">
            <section className="codex-panel codex-panel--nested">
              <div className="codex-panel__header">
                <div>
                  <span className="codex-kicker">Issues</span>
                  <h3>Matching work</h3>
                </div>
              </div>
              <div className="codex-stack-list">
                {(retrieval?.issues ?? []).map((item) => (
                  <button
                    key={item.task_id}
                    type="button"
                    className="codex-stack-item"
                    onClick={() => {
                      setPendingTaskFocus(item.task_id);
                      onNavigate("work");
                    }}
                  >
                    <div className="codex-stack-item__header">
                      <strong>{item.issue_key ?? item.task_id}</strong>
                      <span>{item.status}</span>
                    </div>
                    <span>{item.title}</span>
                    <p>{item.match_context}</p>
                  </button>
                ))}
                {!retrieval?.issues.length ? <div className="codex-empty-copy">No issue matches.</div> : null}
              </div>
            </section>

            <section className="codex-panel codex-panel--nested">
              <div className="codex-panel__header">
                <div>
                  <span className="codex-kicker">Runs + artifacts</span>
                  <h3>Execution evidence</h3>
                </div>
              </div>
              <div className="codex-stack-list">
                {(retrieval?.runs ?? []).map((item) => (
                  <button
                    key={item.session_id}
                    type="button"
                    className="codex-stack-item"
                    onClick={() => {
                      setPendingRunFocus(item.session_id);
                      onNavigate("runs");
                    }}
                  >
                    <div className="codex-stack-item__header">
                      <strong>{item.issue_key ?? item.session_id}</strong>
                      <span>{item.status}</span>
                    </div>
                    <span>{item.task_title ?? item.provider_type}</span>
                    <p>{item.match_context}</p>
                  </button>
                ))}
                {(retrieval?.artifacts ?? []).map((item) => (
                  <button
                    key={item.artifact_id}
                    type="button"
                    className="codex-stack-item"
                    onClick={() => {
                      if (item.task_id) {
                        setPendingTaskFocus(item.task_id);
                        onNavigate("work");
                      } else if (item.session_id) {
                        setPendingRunFocus(item.session_id);
                        onNavigate("runs");
                      }
                    }}
                  >
                    <div className="codex-stack-item__header">
                      <strong>{item.issue_key ?? item.artifact_type}</strong>
                      <span>{item.artifact_state}</span>
                    </div>
                    <span>{item.title}</span>
                    <p>{item.artifact_path}</p>
                  </button>
                ))}
                {!retrieval?.runs.length && !retrieval?.artifacts.length ? (
                  <div className="codex-empty-copy">No run or artifact matches.</div>
                ) : null}
              </div>
            </section>

            <section className="codex-panel codex-panel--nested">
              <div className="codex-panel__header">
                <div>
                  <span className="codex-kicker">Recent events</span>
                  <h3>Machine history</h3>
                </div>
              </div>
              <div className="codex-history-list">
                {(retrieval?.events ?? []).map((item) => (
                  <button
                    key={item.event_id}
                    type="button"
                    className="codex-history-item codex-history-item--button"
                    onClick={() => {
                      if (item.task_id) {
                        setPendingTaskFocus(item.task_id);
                        onNavigate("issues");
                        return;
                      }
                      if (item.session_id) {
                        setPendingRunFocus(item.session_id);
                        onNavigate("runs");
                        return;
                      }
                      onNavigate("system");
                    }}
                  >
                    <div className="codex-history-item__meta">
                      <strong>{item.title}</strong>
                      <span>{formatTimestamp(item.created_at)}</span>
                    </div>
                    <span>{item.description}</span>
                  </button>
                ))}
                {!retrieval?.events.length ? <div className="codex-empty-copy">No event matches.</div> : null}
              </div>
            </section>

            <section className="codex-panel codex-panel--nested">
              <div className="codex-panel__header">
                <div>
                  <span className="codex-kicker">Memory</span>
                  <h3>Promoted guidance</h3>
                </div>
              </div>
              <div className="codex-stack-list">
                {(retrieval?.memory ?? []).map((item) => (
                  <button
                    key={item.artifact_id}
                    type="button"
                    className="codex-stack-item"
                    onClick={() => {
                      if (item.task_id) {
                        setPendingTaskFocus(item.task_id);
                        onNavigate("work");
                        return;
                      }
                      if (item.session_id) {
                        setPendingRunFocus(item.session_id);
                        onNavigate("runs");
                      }
                    }}
                  >
                    <div className="codex-stack-item__header">
                      <strong>{item.title || item.artifact_id}</strong>
                      <span>{item.promoted_at ? formatTimestamp(item.promoted_at) : "memory"}</span>
                    </div>
                    <span>{item.summary || item.path || "Promoted project memory"}</span>
                    <p>{item.preview?.content || item.tags?.join(" · ") || "Reusable context for future Codex runs."}</p>
                  </button>
                ))}
                {!retrieval?.memory.length ? <div className="codex-empty-copy">No memory matches.</div> : null}
              </div>
            </section>
          </div>
        )}
      </section>

      <div className="codex-three-column">
        <section className="codex-panel">
          <div className="codex-panel__header">
            <div>
              <span className="codex-kicker">Decision queue</span>
              <h2>Operator-facing issues</h2>
            </div>
          </div>
          <div className="codex-stack-list">
            {queue.map((task) => (
              <button
                key={task.task_id}
                type="button"
                className="codex-stack-item"
                onClick={() => {
                  setPendingTaskFocus(task.task_id);
                  onNavigate("issues");
                }}
              >
                <div className="codex-stack-item__header">
                  <strong>{issueLabel(task, keyMap)}</strong>
                  <span>{task.status === "review" ? "Review now" : "Open issue"}</span>
                </div>
                <span>{task.title}</span>
                <p>{task.description ?? task.scheduler_summary ?? "No summary recorded."}</p>
              </button>
            ))}
            {!queue.length ? <div className="codex-empty-copy">Nothing currently requires operator judgment.</div> : null}
          </div>
        </section>

        <section className="codex-panel">
          <div className="codex-panel__header">
            <div>
              <span className="codex-kicker">Landed</span>
              <h2>Recently resolved work</h2>
            </div>
          </div>
          <div className="codex-stack-list">
            {resolved.slice(0, 8).map((task) => (
              <button
                key={task.task_id}
                type="button"
                className="codex-stack-item"
                onClick={() => {
                  setPendingTaskFocus(task.task_id);
                  onNavigate("issues");
                }}
              >
                <div className="codex-stack-item__header">
                  <strong>{issueLabel(task, keyMap)}</strong>
                  <span>{formatTimestamp(task.latest_verification_at ?? null)}</span>
                </div>
                <span>{task.title}</span>
                <p>{task.goal?.title ?? "Resolved work"}</p>
              </button>
            ))}
          </div>
        </section>

        <section className="codex-panel">
          <div className="codex-panel__header">
            <div>
              <span className="codex-kicker">History</span>
              <h2>Recent machine activity</h2>
            </div>
          </div>
          <div className="codex-history-list">
            {timeline.slice(0, 12).map((event) => (
              <div key={`${event.source}:${event.event_id}`} className="codex-history-item">
                <div className="codex-history-item__meta">
                  <strong>{event.title}</strong>
                  <span>{formatTimestamp(event.created_at)}</span>
                </div>
                <span>{event.description}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </section>
  );
}
