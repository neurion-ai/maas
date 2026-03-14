import { useEffect, useState } from "react";
import { fetchOverview } from "../lib/controlRoomApi";
import type { OverviewResponse } from "../types";
import { StatCard } from "../components/StatCard";

export function OverviewPage() {
  const [overview, setOverview] = useState<OverviewResponse | null>(null);

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
  }, []);

  return (
    <section className="control-page">
      <header className="page-hero">
        <div>
          <span className="eyebrow">Overview</span>
          <h1>{overview?.project?.name ?? "MAAS Control Room"}</h1>
          <p>{overview?.project?.description ?? "High-level system status, active work, and recent movement."}</p>
        </div>
      </header>

      <section className="stats-grid">
        <StatCard label="Tasks total" value={overview?.summary.tasks_total ?? 0} />
        <StatCard label="In progress" value={overview?.summary.tasks_in_progress ?? 0} tone="good" />
        <StatCard label="Review queue" value={overview?.summary.tasks_review ?? 0} />
        <StatCard label="Blocked" value={overview?.summary.tasks_blocked ?? 0} tone="warn" />
      </section>

      <section className="overview-grid">
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
      </section>
    </section>
  );
}
