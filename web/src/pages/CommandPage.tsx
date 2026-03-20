import { useEffect, useMemo, useState } from "react";
import { fetchAlerts, fetchAgentRoster, fetchFailures, fetchIncidentTimeline, fetchOverview, runOrchestratorPass } from "../lib/controlRoomApi";
import { fetchBoard } from "../lib/boardApi";
import { boardCounts, formatTimestamp, issueKeyMap, openBoardTasks, operatorQueueTasks, resolvedBoardTasks } from "../lib/codexMvp";
import { setPendingTaskFocus } from "../lib/taskFocus";
import { useLivePulse } from "../lib/useLivePulse";
import type { AlertItem, BoardTask, FailureItem, OverviewResponse, TimelineEvent } from "../types";

type ViewTarget = "work" | "issues" | "agents" | "system" | "projects";

function issueLabel(task: BoardTask, fallbackKeys: Map<string, string>) {
  return task.issue_key ?? fallbackKeys.get(task.task_id) ?? task.task_id;
}

export function CommandPage({ onNavigate }: { onNavigate: (view: ViewTarget) => void }) {
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [tasks, setTasks] = useState<BoardTask[]>([]);
  const [resolved, setResolved] = useState<BoardTask[]>([]);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [failures, setFailures] = useState<FailureItem[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [runningAgents, setRunningAgents] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const livePulse = useLivePulse();

  async function loadCommand(signal?: AbortSignal) {
    const [boardPayload, overviewPayload, alertsPayload, failuresPayload, timelinePayload, rosterPayload] = await Promise.all([
      fetchBoard({}, signal),
      fetchOverview(),
      fetchAlerts(),
      fetchFailures(),
      fetchIncidentTimeline({ limit: 18 }, signal),
      fetchAgentRoster(),
    ]);
    setOverview(overviewPayload);
    setTasks(openBoardTasks(boardPayload.columns));
    setResolved(resolvedBoardTasks(boardPayload.columns));
    setAlerts(alertsPayload.alerts);
    setFailures(failuresPayload.recent);
    setTimeline(timelinePayload.events);
    setRunningAgents(rosterPayload.agents.filter((agent) => agent.status === "running").length);
  }

  useEffect(() => {
    const controller = new AbortController();
    void loadCommand(controller.signal).catch(() => setNotice("Command refresh failed; showing the latest available state."));
    return () => controller.abort();
  }, [livePulse]);

  const keyMap = useMemo(() => issueKeyMap([{ key: "ready", title: "Ready", tasks }, { key: "done", title: "Done", tasks: resolved }]), [tasks, resolved]);
  const counts = useMemo(() => boardCounts([{ key: "ready", title: "Ready", tasks }, { key: "done", title: "Done", tasks: resolved }]), [tasks, resolved]);

  const queue = useMemo(() => operatorQueueTasks(tasks).slice(0, 6), [tasks]);

  async function handleRun() {
    setPendingKey("run");
    setNotice(null);
    try {
      const result = await runOrchestratorPass(6, 4, true);
      await loadCommand();
      const queued = result.provider_jobs_queued ?? 0;
      const started = result.provider_jobs_processed ?? 0;
      setNotice(
        `Run complete: ${result.assigned_count} assignments, ${started} Codex run${started === 1 ? "" : "s"} started, ${queued} queued for execution.`
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Run failed.");
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
          <button type="button" className="codex-button codex-button--primary" disabled={pendingKey === "run"} onClick={() => void handleRun()}>
            {pendingKey === "run" ? "Running..." : "Run"}
          </button>
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
          <strong>{resolved.length}</strong>
          <span>Resolved</span>
          <p>Finished work remains searchable in Issues.</p>
        </article>
        <article className="codex-panel codex-stat">
          <strong>{queue.length}</strong>
          <span>Needs judgment</span>
          <p>{alerts.filter((alert) => alert.status === "open").length} open alerts · {failures.length} recent failures</p>
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
