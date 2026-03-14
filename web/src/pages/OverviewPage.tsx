import { useEffect, useState } from "react";
import { fetchOverview, runSupervisorPass } from "../lib/controlRoomApi";
import { useLivePulse } from "../lib/useLivePulse";
import type { OverviewResponse, SupervisorRunResponse } from "../types";
import { StatCard } from "../components/StatCard";

export function OverviewPage() {
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [supervisorResult, setSupervisorResult] = useState<SupervisorRunResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isRunningSupervisor, setIsRunningSupervisor] = useState(false);
  const livePulse = useLivePulse();

  useEffect(() => {
    let mounted = true;

    async function loadOverview() {
      const payload = await fetchOverview();
      if (mounted) {
        setOverview(payload);
      }
    }

    void loadOverview();
    const timer = window.setInterval(() => {
      void loadOverview();
    }, 15000);

    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, [livePulse]);

  async function handleRunSupervisor() {
    setIsRunningSupervisor(true);
    setNotice(null);
    try {
      const result = await runSupervisorPass(2);
      setSupervisorResult(result);
      setNotice(
        `Supervisor refreshed ${result.ready_changes.length} tasks, assigned ${result.assigned_count}, and found ${result.stale_sessions.length} stale sessions.`
      );
      setOverview(await fetchOverview());
    } catch {
      setNotice("Supervisor run failed; keeping the most recent overview snapshot.");
    } finally {
      setIsRunningSupervisor(false);
    }
  }

  return (
    <section className="control-page">
      <header className="page-hero">
        <div>
          <span className="eyebrow">Overview</span>
          <h1>{overview?.project?.name ?? "MAAS Control Room"}</h1>
          <p>{overview?.project?.description ?? "High-level system status, active work, and recent movement."}</p>
        </div>
        <div className="page-hero__actions">
          <button
            type="button"
            className="task-action task-action--secondary"
            disabled={isRunningSupervisor}
            onClick={() => void handleRunSupervisor()}
          >
            {isRunningSupervisor ? "Running supervisor..." : "Run supervisor pass"}
          </button>
          {notice ? <p className="page-hero__notice">{notice}</p> : null}
        </div>
      </header>

      <section className="stats-grid">
        <StatCard label="Tasks total" value={overview?.summary.tasks_total ?? 0} />
        <StatCard label="In progress" value={overview?.summary.tasks_in_progress ?? 0} tone="good" />
        <StatCard label="Review queue" value={overview?.summary.tasks_review ?? 0} />
        <StatCard label="Blocked" value={overview?.summary.tasks_blocked ?? 0} tone="warn" />
        <StatCard label="Failures logged" value={overview?.summary.failures_total ?? 0} tone="warn" />
        <StatCard label="Repeated failures" value={overview?.summary.repeated_failure_tasks ?? 0} tone="warn" />
      </section>

      <section className="overview-grid">
        <article className="data-panel">
          <header className="data-panel__header">
            <h2>Supervisor pass</h2>
            <p>Manual orchestration trigger for readiness refresh, assignment, and stale-session checks.</p>
          </header>
          <div className="data-list">
            <div className="data-list__item">
              <div>
                <strong>Ready changes</strong>
                <p>{supervisorResult ? supervisorResult.ready_changes.length : 0} tasks updated in the last manual pass</p>
              </div>
              <div className="data-list__meta">
                <span>{supervisorResult ? supervisorResult.assigned_count : 0} assigned</span>
                <span>{supervisorResult ? supervisorResult.stale_sessions.length : 0} stale</span>
              </div>
            </div>
            {(supervisorResult?.allocations ?? []).map((allocation) => (
              <div key={`${allocation.agent_id}-${allocation.task_id}`} className="data-list__item">
                <div>
                  <strong>{allocation.task_title ?? allocation.task_id}</strong>
                  <p>{allocation.agent_id}</p>
                </div>
                <div className="data-list__meta">
                  <span>{allocation.status}</span>
                  <span>{allocation.assigned ? "new assignment" : "existing reservation"}</span>
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <h2>Active work</h2>
            <p>What needs attention right now.</p>
          </header>
          <div className="data-list">
            {(overview?.active_work ?? []).map((item) => (
              <div key={item.task_id} className="data-list__item">
                <div>
                  <strong>{item.title}</strong>
                  <p>{item.goal_title ?? "Unlinked goal"}</p>
                </div>
                <div className="data-list__meta">
                  <span>{item.agent_name ?? "Unassigned"}</span>
                  <span>{item.status}</span>
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <h2>Recent activity</h2>
            <p>Latest system movement from the blackboard.</p>
          </header>
          <div className="data-list">
            {(overview?.recent_activity ?? []).map((item, index) => (
              <div key={`${item.action}-${index}`} className="data-list__item">
                <div>
                  <strong>{item.action}</strong>
                  <p>{item.description}</p>
                </div>
                <div className="data-list__meta">
                  <span>{item.severity}</span>
                  <span>{new Date(item.created_at).toLocaleTimeString()}</span>
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <h2>Recent failures</h2>
            <p>Failure memory for the latest failed or timed-out work.</p>
          </header>
          <div className="data-list">
            {(overview?.recent_failures ?? []).map((item) => (
              <div key={item.failure_id ?? `${item.task_id}-${item.created_at}`} className="data-list__item">
                <div>
                  <strong>{item.task_title ?? item.task_id ?? "Unlinked failure"}</strong>
                  <p>{item.summary}</p>
                </div>
                <div className="data-list__meta">
                  <span>{item.failure_type}</span>
                  <span>{new Date(item.created_at).toLocaleTimeString()}</span>
                </div>
              </div>
            ))}
          </div>
        </article>
      </section>
    </section>
  );
}
