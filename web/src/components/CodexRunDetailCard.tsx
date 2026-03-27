import type { ReactNode } from "react";
import type { CodexRunDetailResponse } from "../types";
import { formatTimestamp } from "../lib/codexMvp";

function formatExecutionModeLabel(value?: string | null) {
  if (!value) {
    return "unknown";
  }
  return value.replaceAll("_", " ");
}

function ageLabel(seconds?: number | null) {
  if (seconds == null) {
    return "Not recorded";
  }
  if (seconds < 60) {
    return `${seconds}s`;
  }
  if (seconds < 3600) {
    return `${Math.round(seconds / 60)}m`;
  }
  return `${Math.round(seconds / 3600)}h`;
}

function renderPreview(title: string, preview: CodexRunDetailResponse["output_preview"]) {
  if (!preview?.content) {
    return <div className="codex-empty-copy">{title} is not available for this run yet.</div>;
  }
  return (
    <div className="codex-output-preview">
      <div className="codex-output-preview__label">
        {title}
        {preview.truncated ? " (tail)" : ""}
      </div>
      <pre className="codex-output-preview__content">{preview.content}</pre>
    </div>
  );
}

export function CodexRunDetailCard({
  run,
  title = "Selected run",
  subtitle,
  actions,
}: {
  run: CodexRunDetailResponse | null;
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  if (!run) {
    return <div className="codex-empty-copy">Select a run to inspect its trace, output, and current posture.</div>;
  }

  return (
    <div className="codex-detail-stack">
      <div className="codex-panel__header">
        <div>
          <span className="codex-kicker">{title}</span>
          <h2>{run.issue_key ?? run.task_id ?? run.session_id}</h2>
          <p>{subtitle ?? run.task_title ?? "No linked issue"}</p>
        </div>
        <span className={`codex-status-chip codex-status-chip--${run.status === "active" ? "running" : run.status}`}>
          {run.status.replaceAll("_", " ")}
        </span>
      </div>

      {run.execution_mode === "local_simulation" ? (
        <div className="codex-banner codex-banner--warn">
          This run used simulation mode, so its output is workflow evidence rather than real Codex execution.
        </div>
      ) : null}

      <div className="codex-review-callout">
        <strong>{run.status_message ?? "No runtime summary recorded."}</strong>
        {run.current_step ? <p>Current step: {run.current_step}</p> : null}
        <p>
          {run.agent_name ?? run.agent_id ?? "Unknown agent"} via {run.provider_type.replaceAll("_", " ")} ·{" "}
          {formatExecutionModeLabel(run.execution_mode)} · started {formatTimestamp(run.started_at)}
          {run.ended_at ? ` · ended ${formatTimestamp(run.ended_at)}` : ""}
        </p>
        <div className="codex-review-facts">
          <div className="codex-review-fact">
            <span>Progress</span>
            <strong>{run.progress_pct ?? 0}%</strong>
          </div>
          <div className="codex-review-fact">
            <span>Run age</span>
            <strong>{ageLabel(run.run_age_seconds)}</strong>
          </div>
          <div className="codex-review-fact">
            <span>Heartbeat</span>
            <strong>{ageLabel(run.heartbeat_age_seconds)}</strong>
          </div>
          <div className="codex-review-fact">
            <span>Artifacts</span>
            <strong>{run.artifacts.length}</strong>
          </div>
        </div>
        {run.command?.length ? <div className="codex-review-note">Command: {run.command.join(" ")}</div> : null}
        {run.external_runtime && run.external_runtime !== run.execution_mode ? (
          <div className="codex-review-note">External runtime: {formatExecutionModeLabel(run.external_runtime)}</div>
        ) : null}
        {run.is_stale ? (
          <div className="codex-review-note">This run looks stale: the heartbeat has gone quiet while the session still appears active.</div>
        ) : null}
        {run.observability ? (
          <div className="codex-review-note">
            {run.observability.summary}
            {run.observability.last_activity_action
              ? ` Last activity: ${run.observability.last_activity_action.replaceAll("_", " ")}`
              : ""}
            {run.observability.last_activity_at ? ` at ${formatTimestamp(run.observability.last_activity_at)}` : ""}.
          </div>
        ) : null}
        {run.diagnostic_summary ? <div className="codex-review-note">{run.diagnostic_summary}</div> : null}
        {run.recommended_action ? <div className="codex-review-note">Recommended action: {run.recommended_action}</div> : null}
      </div>

      {actions ? <div className="codex-detail-actions">{actions}</div> : null}

      {run.phases?.length ? (
        <section className="codex-detail-section">
          <div className="codex-section-heading">
            <strong>Run phases</strong>
            <span>{run.phases.length}</span>
          </div>
          <div className="codex-history-list">
            {run.phases.map((phase) => (
              <div key={phase.key} className="codex-history-item">
                <div className="codex-history-item__meta">
                  <strong>{phase.label}</strong>
                  <span>{phase.timestamp ? formatTimestamp(phase.timestamp) : phase.status}</span>
                </div>
                <span>{phase.description ?? "No event recorded for this phase yet."}</span>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {run.memory_context?.length ? (
        <section className="codex-detail-section">
          <div className="codex-section-heading">
            <strong>Injected memory</strong>
            <span>{run.memory_context.length}</span>
          </div>
          <div className="codex-relationship-list">
            {run.memory_context.map((entry) => (
              <div key={entry.artifact_id} className="codex-related-item">
                <div className="codex-related-item__meta">
                  <span>{entry.artifact_id}</span>
                  <span>score {entry.score ?? 0}</span>
                </div>
                <strong>{entry.title ?? entry.artifact_id}</strong>
                <span>{entry.summary ?? "No summary recorded."}</span>
                <span>
                  {entry.freshness ?? "unknown"}
                  {entry.age_days != null ? ` · ${entry.age_days}d old` : ""}
                </span>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <div className="codex-detail-stack">
        {renderPreview("Runtime output", run.output_preview)}
        {renderPreview("Stdout", run.stdout_preview)}
        {renderPreview("Stderr", run.stderr_preview)}
      </div>

      <section className="codex-detail-section">
        <div className="codex-section-heading">
          <strong>Run activity</strong>
          <span>{run.activity.length}</span>
        </div>
        <div className="codex-history-list">
          {run.activity.length ? (
            run.activity.map((event) => (
              <div key={`${event.activity_id ?? event.created_at}:${event.action}`} className="codex-history-item">
                <div className="codex-history-item__meta">
                  <strong>{event.action.replaceAll("_", " ")}</strong>
                  <span>{formatTimestamp(event.created_at)}</span>
                </div>
                <span>{event.description}</span>
              </div>
            ))
          ) : (
            <div className="codex-empty-copy">No run-scoped activity has been logged for this session yet.</div>
          )}
        </div>
      </section>
    </div>
  );
}
