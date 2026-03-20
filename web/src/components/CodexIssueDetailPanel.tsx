import type { ReactNode } from "react";
import type { BoardTask, CodexIssueDetailResponse } from "../types";
import { formatTimestamp, nextActionLabel, priorityLabel, statusLabel } from "../lib/codexMvp";

function renderRelationshipList(
  items: CodexIssueDetailResponse["relationships"]["depends_on"],
  emptyLabel: string,
  issueKeyMap: Map<string, string>,
  onSelectTask?: (taskId: string) => void
) {
  if (!items.length) {
    return <div className="codex-empty-copy">{emptyLabel}</div>;
  }
  return (
    <div className="codex-relationship-list">
      {items.map((item) => (
        <button
          key={item.task_id}
          type="button"
          className="codex-related-item"
          onClick={() => onSelectTask?.(item.task_id)}
        >
          <div className="codex-related-item__meta">
            <span>{item.issue_key ?? issueKeyMap.get(item.task_id) ?? item.task_id}</span>
            <span>{statusLabel(item.status, item.review_state)}</span>
          </div>
          <strong>{item.title}</strong>
          <span>{item.goal_title ?? "Unlinked goal"}</span>
        </button>
      ))}
    </div>
  );
}

export function CodexIssueDetailPanel({
  task,
  detail,
  issueKeyMap,
  actions,
  onSelectTask,
}: {
  task: BoardTask | null;
  detail: CodexIssueDetailResponse | null;
  issueKeyMap: Map<string, string>;
  actions?: ReactNode;
  onSelectTask?: (taskId: string) => void;
}) {
  if (!task) {
    return (
      <aside className="codex-detail-panel codex-panel">
        <div className="codex-empty-copy">Select an issue to inspect its runs, relationships, outputs, and history.</div>
      </aside>
    );
  }

  return (
    <aside className="codex-detail-panel codex-panel">
      <div className="codex-panel__header">
        <div>
          <span className="codex-kicker">Issue detail</span>
          <h2>
            {detail?.task.issue_key ?? task.issue_key ?? issueKeyMap.get(task.task_id) ?? task.task_id} · {task.title}
          </h2>
          <p>{task.description || "No description recorded for this issue yet."}</p>
        </div>
        <span className={`codex-status-chip codex-status-chip--${task.status}`}>
          {statusLabel(task.status, task.review_state)}
        </span>
      </div>

      <div className="codex-detail-grid">
        <div className="codex-metric-card">
          <span className="codex-kicker">Priority</span>
          <strong>{priorityLabel(task.priority)}</strong>
          <span>{task.priority}</span>
        </div>
        <div className="codex-metric-card">
          <span className="codex-kicker">Owner</span>
          <strong>{task.agent?.name ?? "Unassigned"}</strong>
          <span>{task.goal?.title ?? "Unlinked goal"}</span>
        </div>
        <div className="codex-metric-card">
          <span className="codex-kicker">Next step</span>
          <strong>{nextActionLabel(task)}</strong>
          <span>{task.scheduler_summary ?? "No scheduler note recorded."}</span>
        </div>
      </div>

      {actions ? <div className="codex-detail-actions">{actions}</div> : null}

      <section className="codex-detail-section">
        <div className="codex-section-heading">
          <strong>Dependencies</strong>
          <span>{detail?.relationships.depends_on.length ?? 0}</span>
        </div>
        {renderRelationshipList(detail?.relationships.depends_on ?? [], "No upstream dependency is linked.", issueKeyMap, onSelectTask)}
      </section>

      <section className="codex-detail-section">
        <div className="codex-section-heading">
          <strong>Unlocks</strong>
          <span>{detail?.relationships.unlocks.length ?? 0}</span>
        </div>
        {renderRelationshipList(detail?.relationships.unlocks ?? [], "No downstream issue is linked.", issueKeyMap, onSelectTask)}
      </section>

      <section className="codex-detail-section">
        <div className="codex-section-heading">
          <strong>Related on the same goal</strong>
          <span>{detail?.relationships.related.length ?? 0}</span>
        </div>
        {renderRelationshipList(detail?.relationships.related ?? [], "No related issue is linked on this goal.", issueKeyMap, onSelectTask)}
      </section>

      <section className="codex-detail-section">
        <div className="codex-section-heading">
          <strong>Runs</strong>
          <span>{detail?.runs.length ?? 0}</span>
        </div>
        <div className="codex-run-list">
          {(detail?.runs ?? []).length ? (
            detail?.runs.map((run) => (
              <div key={run.session_id} className="codex-run-item">
                <div className="codex-run-item__meta">
                  <strong>{run.agent_name ?? run.agent_id ?? "Unknown agent"}</strong>
                  <span>{run.status.replaceAll("_", " ")}</span>
                </div>
                <span>{run.status_message || "No run summary recorded."}</span>
                <span>{formatTimestamp(run.started_at)}</span>
              </div>
            ))
          ) : (
            <div className="codex-empty-copy">No runs recorded for this issue yet.</div>
          )}
        </div>
      </section>

      <section className="codex-detail-section">
        <div className="codex-section-heading">
          <strong>Verification</strong>
          <span>{detail?.verification_runs.length ?? 0}</span>
        </div>
        <div className="codex-run-list">
          {(detail?.verification_runs ?? []).length ? (
            detail?.verification_runs.map((run) => (
              <div key={run.verification_run_id} className="codex-run-item">
                <div className="codex-run-item__meta">
                  <strong>{run.command}</strong>
                  <span>{run.status}</span>
                </div>
                <span>{run.output_excerpt ?? (run.exit_code != null ? `exit ${run.exit_code}` : "No verification summary recorded.")}</span>
                <span>{formatTimestamp(run.finished_at ?? run.started_at)}</span>
              </div>
            ))
          ) : (
            <div className="codex-empty-copy">No verification runs have been recorded for this issue yet.</div>
          )}
        </div>
      </section>

      <section className="codex-detail-section">
        <div className="codex-section-heading">
          <strong>Git workspace</strong>
          <span>{detail?.git_workspace ? "prepared" : "not prepared"}</span>
        </div>
        {detail?.git_workspace ? (
          <div className="codex-output-item">
            <strong>{detail.git_workspace.branch_name}</strong>
            <span>{detail.git_workspace.worktree_path}</span>
            <span>{detail.git_workspace.change_summary ?? "No local changes recorded."}</span>
          </div>
        ) : (
          <div className="codex-empty-copy">No git workspace has been prepared for this issue yet.</div>
        )}
      </section>

      <section className="codex-detail-section">
        <div className="codex-section-heading">
          <strong>Outputs</strong>
          <span>{detail?.artifacts.length ?? 0}</span>
        </div>
        <div className="codex-output-list">
          {(detail?.artifacts ?? []).length ? (
            detail?.artifacts.map((artifact) => (
              <div key={artifact.artifact_id} className="codex-output-item">
                <strong>{artifact.file_name}</strong>
                <span>{artifact.artifact_type.replaceAll("_", " ")}</span>
                <span>{formatTimestamp(artifact.created_at)}</span>
              </div>
            ))
          ) : (
            <div className="codex-empty-copy">No outputs have been attached to this issue yet.</div>
          )}
        </div>
      </section>

      <section className="codex-detail-section">
        <div className="codex-section-heading">
          <strong>History</strong>
          <span>{detail?.history.length ?? 0}</span>
        </div>
        <div className="codex-history-list">
          {(detail?.history ?? []).length ? (
            detail?.history.map((event) => (
              <div key={`${event.source}:${event.event_id}`} className="codex-history-item">
                <div className="codex-history-item__meta">
                  <strong>{event.title}</strong>
                  <span>{formatTimestamp(event.created_at)}</span>
                </div>
                <span>{event.description}</span>
              </div>
            ))
          ) : (
            <div className="codex-empty-copy">No history has been logged for this issue yet.</div>
          )}
        </div>
      </section>
    </aside>
  );
}
