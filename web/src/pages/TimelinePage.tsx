import { useEffect, useMemo, useState } from "react";
import { fetchIncidentTimeline } from "../lib/controlRoomApi";
import { useLivePulse } from "../lib/useLivePulse";
import { StatCard } from "../components/StatCard";
import type { TimelineResponse } from "../types";

export function TimelinePage() {
  const [timeline, setTimeline] = useState<TimelineResponse | null>(null);
  const [taskId, setTaskId] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [agentId, setAgentId] = useState("");
  const [resourceType, setResourceType] = useState("");
  const [resourceId, setResourceId] = useState("");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [notice, setNotice] = useState<string | null>(null);
  const livePulse = useLivePulse();

  const filters = useMemo(
    () => ({
      taskId: taskId.trim() || undefined,
      sessionId: sessionId.trim() || undefined,
      agentId: agentId.trim() || undefined,
      resourceType: resourceType.trim() || undefined,
      resourceId: resourceId.trim() || undefined,
      order,
      limit: 100
    }),
    [agentId, order, resourceId, resourceType, sessionId, taskId]
  );

  useEffect(() => {
    let mounted = true;
    async function loadTimeline() {
      try {
        const payload = await fetchIncidentTimeline(filters);
        if (mounted) {
          setTimeline(payload);
        }
      } catch {
        if (mounted) {
          setNotice("Incident timeline refresh failed; showing the most recent available data.");
        }
      }
    }

    void loadTimeline();
    return () => {
      mounted = false;
    };
  }, [filters, livePulse]);

  return (
    <section className="control-page">
      <header className="page-hero">
        <div>
          <span className="eyebrow">Timeline</span>
          <h1>Incident replay and correlated runtime history</h1>
          <p>Trace task, session, escalation, notification, and recovery events in one ordered feed.</p>
        </div>
      </header>

      <article className="filters-panel">
        <div className="filters-panel__row">
          <label className="filters-panel__field">
            <span>Task ID</span>
            <input value={taskId} onChange={(event) => setTaskId(event.target.value)} placeholder="task_..." />
          </label>
          <label className="filters-panel__field">
            <span>Session ID</span>
            <input value={sessionId} onChange={(event) => setSessionId(event.target.value)} placeholder="sess_..." />
          </label>
          <label className="filters-panel__field">
            <span>Agent ID</span>
            <input value={agentId} onChange={(event) => setAgentId(event.target.value)} placeholder="agent_..." />
          </label>
          <label className="filters-panel__field">
            <span>Resource type</span>
            <input value={resourceType} onChange={(event) => setResourceType(event.target.value)} placeholder="task / agent / ..." />
          </label>
          <label className="filters-panel__field">
            <span>Resource ID</span>
            <input value={resourceId} onChange={(event) => setResourceId(event.target.value)} placeholder="task_..." />
          </label>
          <label className="filters-panel__field">
            <span>Replay order</span>
            <select value={order} onChange={(event) => setOrder(event.target.value as "asc" | "desc")}>
              <option value="desc">Newest first</option>
              <option value="asc">Oldest first</option>
            </select>
          </label>
        </div>
        {notice ? <p className="filters-panel__notice">{notice}</p> : null}
      </article>

      <section className="stats-grid">
        <StatCard label="Events" value={timeline?.summary.total_events ?? 0} />
        <StatCard label="Activity" value={timeline?.summary.sources.activity ?? 0} />
        <StatCard label="Failures" value={timeline?.summary.sources.failure ?? 0} tone="warn" />
        <StatCard label="Escalations" value={timeline?.summary.sources.escalation ?? 0} tone="warn" />
        <StatCard label="Notifications" value={timeline?.summary.sources.notification ?? 0} />
      </section>

      <article className="data-panel">
        <header className="data-panel__header">
          <div>
            <h2>Timeline events</h2>
            <p>Replay the current incident scope in either chronological or newest-first order.</p>
          </div>
        </header>
        <div className="data-list">
          {(timeline?.events ?? []).length ? (
            timeline?.events.map((item) => (
              <div key={`${item.source}:${item.event_id}`} className="data-list__item">
                <div>
                  <strong>{item.title}</strong>
                  <p>{item.description}</p>
                  <p>
                    {item.source} · {item.event_type}
                    {item.task_id ? ` · task ${item.task_id}` : ""}
                    {item.session_id ? ` · session ${item.session_id}` : ""}
                    {item.agent_id ? ` · agent ${item.agent_id}` : ""}
                  </p>
                </div>
                <div className="data-list__meta">
                  <span>{item.severity}</span>
                  <span>{new Date(item.created_at).toLocaleString()}</span>
                </div>
              </div>
            ))
          ) : (
            <div className="data-list__item">
              <div>
                <strong>No events in the current scope.</strong>
                <p>Adjust the filters or wait for new runtime activity to appear.</p>
              </div>
            </div>
          )}
        </div>
      </article>
    </section>
  );
}
