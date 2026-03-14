import { useEffect, useState } from "react";
import { fetchActivity } from "../lib/controlRoomApi";
import type { ActivityItem } from "../types";

export function ActivityPage() {
  const [items, setItems] = useState<ActivityItem[]>([]);

  useEffect(() => {
    let mounted = true;
    async function loadActivity() {
      const payload = await fetchActivity();
      if (mounted) {
        setItems(payload);
      }
    }

    void loadActivity();
    const timer = window.setInterval(() => {
      void loadActivity();
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
          <span className="eyebrow">Activity</span>
          <h1>Raw activity stream</h1>
          <p>Low-level events for tracing what MAAS has been doing over time.</p>
        </div>
      </header>

      <article className="data-panel">
        <header className="data-panel__header">
          <h2>Recent events</h2>
          <p>Latest audit-style activity from the shared blackboard.</p>
        </header>
        <div className="data-list">
          {items.map((item, index) => (
            <div key={`${item.action}-${index}`} className="data-list__item">
              <div>
                <strong>{item.action}</strong>
                <p>{item.description}</p>
              </div>
              <div className="data-list__meta">
                <span>{item.severity}</span>
                <span>{new Date(item.created_at).toLocaleString()}</span>
              </div>
            </div>
          ))}
        </div>
      </article>
    </section>
  );
}
