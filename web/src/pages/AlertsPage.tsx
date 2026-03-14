import { useEffect, useState } from "react";
import { fetchAlerts, runAlertOperatorAction, updateAlertStatus } from "../lib/controlRoomApi";
import { useLivePulse } from "../lib/useLivePulse";
import type { AlertsResponse } from "../types";
import { StatCard } from "../components/StatCard";

export function AlertsPage() {
  const [alerts, setAlerts] = useState<AlertsResponse | null>(null);
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const livePulse = useLivePulse();

  useEffect(() => {
    let mounted = true;

    async function loadAlerts() {
      const payload = await fetchAlerts();
      if (mounted) {
        setAlerts(payload);
      }
    }

    void loadAlerts();
    return () => {
      mounted = false;
    };
  }, [livePulse]);

  async function handleAlertAction(alertId: string, action: "acknowledge" | "resolve") {
    setPendingAction(`${alertId}:${action}`);
    setNotice(null);
    try {
      await updateAlertStatus(alertId, action);
      setAlerts(await fetchAlerts());
    } catch {
      setNotice("Alert action failed; keep the current alert state under review.");
    } finally {
      setPendingAction(null);
    }
  }

  async function handleOperatorAction(alertId: string) {
    const alert = alerts?.alerts.find((item) => item.alert_id === alertId);
    if (!alert?.operator_action) {
      return;
    }

    setPendingAction(`${alertId}:${alert.operator_action.action}`);
    setNotice(null);
    try {
      await runAlertOperatorAction(alert.operator_action);
      setAlerts(await fetchAlerts());
      setNotice(`Recovered ${alert.operator_action.resource_id} from the alert queue.`);
    } catch {
      setNotice("Recovery action failed; keep the alert under review.");
    } finally {
      setPendingAction(null);
    }
  }

  return (
    <section className="control-page">
      <header className="page-hero">
        <div>
          <span className="eyebrow">Alerts</span>
          <h1>Operational alerts and triage</h1>
          <p>Track open system issues and explicitly acknowledge or resolve them from the control room.</p>
        </div>
      </header>

      <section className="stats-grid">
        <StatCard label="Open alerts" value={alerts?.summary.open ?? 0} tone="warn" />
        <StatCard label="Critical open" value={alerts?.summary.critical_open ?? 0} tone="warn" />
        <StatCard label="Repeated failure alerts" value={alerts?.summary.repeated_failure_open ?? 0} tone="warn" />
        <StatCard label="Acknowledged" value={alerts?.summary.acknowledged ?? 0} />
        <StatCard label="Resolved" value={alerts?.summary.resolved ?? 0} tone="good" />
      </section>

      <article className="data-panel">
        <header className="data-panel__header">
          <div>
            <h2>Alert queue</h2>
            <p>Open alerts appear first, followed by acknowledged and resolved items.</p>
          </div>
          {notice ? <p className="filters-panel__notice">{notice}</p> : null}
        </header>
        <div className="data-list">
          {(alerts?.alerts ?? []).map((alert) => (
            <div key={alert.alert_id} className="alert-item">
              <div>
                <div className="goal-card__header">
                  <strong>{alert.title}</strong>
                  <span className={`goal-status goal-status--${alert.status}`}>{alert.status}</span>
                </div>
                <p>{alert.description}</p>
                <div className="goal-card__meta">
                  <span>{alert.severity}</span>
                  <span>{new Date(alert.created_at).toLocaleString()}</span>
                </div>
              </div>
              <div className="task-card__actions">
                {alert.status !== "resolved" && alert.operator_action ? (
                  <button
                    type="button"
                    className="task-action task-action--approve"
                    disabled={pendingAction === `${alert.alert_id}:${alert.operator_action.action}`}
                    onClick={() => void handleOperatorAction(alert.alert_id)}
                  >
                    {pendingAction === `${alert.alert_id}:${alert.operator_action.action}`}
                      ? alert.operator_action.action === "recover_task"
                        ? "Recovering task..."
                        : "Recovering agent..."
                      : alert.operator_action.label}
                  </button>
                ) : null}
                {alert.status === "open" ? (
                  <button
                    type="button"
                    className="task-action task-action--secondary"
                    disabled={pendingAction === `${alert.alert_id}:acknowledge`}
                    onClick={() => handleAlertAction(alert.alert_id, "acknowledge")}
                  >
                    {pendingAction === `${alert.alert_id}:acknowledge` ? "Acknowledging..." : "Acknowledge"}
                  </button>
                ) : null}
                {alert.status !== "resolved" ? (
                  <button
                    type="button"
                    className="task-action task-action--approve"
                    disabled={pendingAction === `${alert.alert_id}:resolve`}
                    onClick={() => handleAlertAction(alert.alert_id, "resolve")}
                  >
                    {pendingAction === `${alert.alert_id}:resolve` ? "Resolving..." : "Resolve"}
                  </button>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      </article>
    </section>
  );
}
