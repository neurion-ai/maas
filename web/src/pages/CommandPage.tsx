import { useEffect, useMemo, useState } from "react";
import { fetchAlerts, fetchAgentRoster, fetchCodexIssueIndex, fetchIncidentTimeline, fetchOverview, fetchPortfolio, runOrchestratorPass, updateProjectProviderCapacity } from "../lib/controlRoomApi";
import { boardCounts, describeLaunchPosture, formatTimestamp, issueKeyMap } from "../lib/codexMvp";
import { getSelectedProjectId } from "../lib/projectScope";
import { setPendingTaskFocus } from "../lib/taskFocus";
import { useLivePulse } from "../lib/useLivePulse";
import type { AlertItem, BoardTask, OverviewResponse, PortfolioProject, TimelineEvent } from "../types";

type ViewTarget = "work" | "issues" | "agents" | "system" | "projects";

const RUN_CONTROL_MIN_PENDING_MS = 900;

function issueLabel(task: BoardTask, fallbackKeys: Map<string, string>) {
  return task.issue_key ?? fallbackKeys.get(task.task_id) ?? task.task_id;
}

export function CommandPage({ onNavigate }: { onNavigate: (view: ViewTarget) => void }) {
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [tasks, setTasks] = useState<BoardTask[]>([]);
  const [resolved, setResolved] = useState<BoardTask[]>([]);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [project, setProject] = useState<PortfolioProject | null>(null);
  const [runningAgents, setRunningAgents] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [recentFailureCount, setRecentFailureCount] = useState(0);
  const livePulse = useLivePulse();

  async function loadCommand(signal?: AbortSignal) {
    const [issueIndexPayload, overviewPayload, alertsPayload, timelinePayload, rosterPayload, portfolioPayload] = await Promise.all([
      fetchCodexIssueIndex(signal),
      fetchOverview(),
      fetchAlerts(),
      fetchIncidentTimeline({ limit: 18 }, signal),
      fetchAgentRoster(),
      fetchPortfolio(),
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

      {notice ? <div className="codex-banner">{notice}</div> : null}

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
