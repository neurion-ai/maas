import type { ReactNode } from "react";
import type { OperatorLoopItem, OperatorWorkflowState } from "../lib/operatorLoop";

export function OperatorLoopPanel({
  workflow,
  title,
  description,
  onSelectItem,
  footer,
  warning,
  compact = false,
  maxItems,
}: {
  workflow: OperatorWorkflowState | null;
  title: string;
  description: string;
  onSelectItem?: (item: OperatorLoopItem) => void;
  footer?: ReactNode;
  warning?: string | null;
  compact?: boolean;
  maxItems?: number;
}) {
  const items = workflow?.inbox.items.slice(0, maxItems ?? (compact ? 3 : 6)) ?? [];

  return (
    <section className={`codex-panel operator-loop ${compact ? "operator-loop--compact" : ""}`}>
      <div className="codex-panel__header">
        <div>
          <span className="codex-kicker">Operator loop</span>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
      </div>

      <div className="operator-loop__body">
        {warning ? <div className="codex-banner codex-banner--warn">{warning}</div> : null}
        <div className={`operator-loop__posture operator-loop__posture--${workflow?.autopilot.tone ?? "default"}`}>
          <div className="operator-loop__posture-copy">
            <strong>{workflow?.autopilot.label ?? "Loading posture..."}</strong>
            <p>{workflow?.autopilot.summary ?? "Refreshing project execution posture."}</p>
          </div>
          <div className="operator-loop__fact-row">
            {(workflow?.autopilot.facts ?? []).slice(0, compact ? 3 : 4).map((fact) => (
              <span key={fact} className="codex-chip">
                {fact}
              </span>
            ))}
          </div>
          <p className="operator-loop__posture-detail">
            {workflow?.autopilot.detail ?? "The operator loop will appear here once project state loads."}
          </p>
        </div>

        <div className="operator-loop__summary">
          <span className="codex-chip">{workflow?.inbox.reviewCount ?? 0} review</span>
          <span className="codex-chip">{workflow?.inbox.recoveryCount ?? 0} recovery</span>
          <span className="codex-chip">{workflow?.inbox.suspectRunCount ?? 0} suspect runs</span>
          <span className="codex-chip">{workflow?.inbox.policyConflictCount ?? 0} conflicts</span>
          <span className="codex-chip">{workflow?.inbox.failedNotificationCount ?? 0} failed notifications</span>
        </div>

        <div className="operator-loop__inbox">
          <div className="operator-loop__inbox-copy">
            <strong>{workflow?.inbox.headline ?? "Loading operator inbox..."}</strong>
            <p>{workflow?.inbox.detail ?? "Refreshing review, recovery, and suspect-run pressure."}</p>
          </div>
          {items.length ? (
            <div className="operator-loop__items">
              {items.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`operator-loop__item operator-loop__item--${item.tone}`}
                  onClick={() => onSelectItem?.(item)}
                >
                  <div className="operator-loop__item-header">
                    <strong>{item.title}</strong>
                    <span>{item.label}</span>
                  </div>
                  <p>{item.detail}</p>
                </button>
              ))}
            </div>
          ) : (
            <div className="codex-empty-copy">Nothing is currently waiting for manual operator handling.</div>
          )}
        </div>

        {footer ? <div className="operator-loop__footer">{footer}</div> : null}
      </div>
    </section>
  );
}
