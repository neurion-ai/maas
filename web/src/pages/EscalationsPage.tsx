import { useEffect, useState } from "react";
import { fetchEscalations, updateEscalationStatus } from "../lib/controlRoomApi";
import { useLivePulse } from "../lib/useLivePulse";
import type { EscalationsResponse } from "../types";
import { StatCard } from "../components/StatCard";

export function EscalationsPage() {
  const [escalations, setEscalations] = useState<EscalationsResponse | null>(null);
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const livePulse = useLivePulse();

  useEffect(() => {
    let mounted = true;

    async function loadEscalations() {
      const payload = await fetchEscalations();
      if (mounted) {
        setEscalations(payload);
      }
    }

    void loadEscalations();
    return () => {
      mounted = false;
    };
  }, [livePulse]);

  async function handleAction(escalationId: string, action: "approve" | "reject") {
    setPendingAction(`${escalationId}:${action}`);
    setNotice(null);
    try {
      await updateEscalationStatus(escalationId, action);
      setEscalations(await fetchEscalations());
    } catch {
      setNotice("Escalation action failed; review the queue and try again.");
    } finally {
      setPendingAction(null);
    }
  }

  return (
    <section className="control-page">
      <header className="page-hero">
        <div>
          <span className="eyebrow">Escalations</span>
          <h1>Operator approvals queue</h1>
          <p>Review high-risk requests, then approve or reject them from the control room.</p>
        </div>
      </header>

      <section className="stats-grid">
        <StatCard label="Open" value={escalations?.summary.open ?? 0} tone="warn" />
        <StatCard label="Approved" value={escalations?.summary.approved ?? 0} tone="good" />
        <StatCard label="Rejected" value={escalations?.summary.rejected ?? 0} />
      </section>

      <article className="data-panel">
        <header className="data-panel__header">
          <div>
            <h2>Escalation queue</h2>
            <p>Open items appear first, followed by approved and rejected history.</p>
          </div>
          {notice ? <p className="filters-panel__notice">{notice}</p> : null}
        </header>
        <div className="data-list">
          {(escalations?.escalations ?? []).map((item) => (
            <div key={item.escalation_id} className="alert-item">
              <div>
                <div className="goal-card__header">
                  <strong>{item.action_type}</strong>
                  <span className={`goal-status goal-status--${item.status}`}>{item.status}</span>
                </div>
                <p>{item.reason || "No reason provided."}</p>
                <div className="goal-card__meta">
                  <span>{item.requester_name ?? item.requested_by}</span>
                  <span>{item.resource_type}:{item.resource_id}</span>
                  <span>{new Date(item.created_at).toLocaleString()}</span>
                </div>
              </div>
              <div className="task-card__actions">
                {item.status === "open" ? (
                  <>
                    <button
                      type="button"
                      className="task-action task-action--approve"
                      disabled={pendingAction === `${item.escalation_id}:approve`}
                      onClick={() => handleAction(item.escalation_id, "approve")}
                    >
                      {pendingAction === `${item.escalation_id}:approve` ? "Approving..." : "Approve"}
                    </button>
                    <button
                      type="button"
                      className="task-action task-action--reject"
                      disabled={pendingAction === `${item.escalation_id}:reject`}
                      onClick={() => handleAction(item.escalation_id, "reject")}
                    >
                      {pendingAction === `${item.escalation_id}:reject` ? "Rejecting..." : "Reject"}
                    </button>
                  </>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      </article>
    </section>
  );
}
