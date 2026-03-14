import { useEffect, useState } from "react";
import { fetchAgentRoster } from "../lib/controlRoomApi";
import type { AgentRosterResponse } from "../types";

function formatHeartbeat(seconds?: number | null) {
  if (seconds == null) {
    return "No recent heartbeat";
  }
  if (seconds < 60) {
    return `${seconds}s ago`;
  }
  return `${Math.round(seconds / 60)}m ago`;
}

export function AgentRosterPage() {
  const [roster, setRoster] = useState<AgentRosterResponse | null>(null);

  useEffect(() => {
    let mounted = true;
    async function loadRoster() {
      const payload = await fetchAgentRoster();
      if (mounted) {
        setRoster(payload);
      }
    }

    void loadRoster();
    const timer = window.setInterval(() => {
      void loadRoster();
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
          <span className="eyebrow">Agent Roster</span>
          <h1>Who is doing what right now</h1>
          <p>Track active ownership, current task context, and heartbeat freshness.</p>
        </div>
      </header>

      <section className="roster-grid">
        {(roster?.agents ?? []).map((agent) => (
          <article key={agent.agent_id} className="roster-card">
            <div className="roster-card__header">
              <div>
                <strong>{agent.display_name}</strong>
                <p>{agent.role}</p>
              </div>
              <span className={`goal-status goal-status--${agent.status}`}>{agent.status}</span>
            </div>
            <dl className="roster-card__details">
              <div>
                <dt>Current task</dt>
                <dd>{agent.current_task_title ?? "Idle"}</dd>
              </div>
              <div>
                <dt>Heartbeat</dt>
                <dd>{formatHeartbeat(agent.heartbeat_age_seconds)}</dd>
              </div>
            </dl>
          </article>
        ))}
      </section>
    </section>
  );
}
