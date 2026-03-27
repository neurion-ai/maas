import { useEffect, useMemo, useState, type ReactNode } from "react";
import { fetchArtifactDetail, fetchCodexRunDetail, prepareTaskPrDraft, promoteArtifactToMemory, syncTaskGithubPr } from "../lib/controlRoomApi";
import type { BoardTask, CodexIssueDetailResponse, CodexRunConsolePreview, CodexRunDetailResponse } from "../types";
import type { ArtifactDetail } from "../types";
import { formatTimestamp, nextActionLabel, priorityLabel, statusLabel } from "../lib/codexMvp";
import { setPendingRunFocus } from "../lib/runFocus";

function formatExecutionModeLabel(value?: string | null) {
  if (!value) {
    return "unknown";
  }
  return value.replaceAll("_", " ");
}

function ageLabel(value?: string | null) {
  if (!value) {
    return "Not recorded";
  }
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) {
    return formatTimestamp(value);
  }
  const deltaSeconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000));
  if (deltaSeconds < 60) {
    return `${deltaSeconds}s ago`;
  }
  if (deltaSeconds < 3600) {
    return `${Math.round(deltaSeconds / 60)}m ago`;
  }
  return `${Math.round(deltaSeconds / 3600)}h ago`;
}

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

function renderConsolePreview(
  title: string,
  preview: CodexRunConsolePreview | null | undefined
) {
  if (!preview?.content) {
    return (
      <div className="codex-empty-copy">
        {title === "Runtime output"
          ? "Codex has not written a runtime output file yet."
          : `${title} has no captured output yet.`}
      </div>
    );
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

export function CodexIssueDetailPanel({
  task,
  detail,
  issueKeyMap,
  actions,
  onSelectTask,
  onNavigate,
}: {
  task: BoardTask | null;
  detail: CodexIssueDetailResponse | null;
  issueKeyMap: Map<string, string>;
  actions?: ReactNode;
  onSelectTask?: (taskId: string) => void;
  onNavigate?: (view: "work" | "issues" | "agents" | "runs" | "system" | "projects" | "command") => void;
}) {
  const latestArtifactSummary = useMemo(() => {
    if (!detail?.artifacts.length) {
      return null;
    }
    return [...detail.artifacts].sort((left, right) => right.created_at.localeCompare(left.created_at))[0] ?? null;
  }, [detail]);
  const latestRun = useMemo(() => {
    if (!detail?.runs?.length) {
      return null;
    }
    return (
      [...detail.runs].sort((left, right) =>
        (right.ended_at ?? right.started_at ?? "").localeCompare(left.ended_at ?? left.started_at ?? "")
      )[0] ?? null
    );
  }, [detail]);
  const latestVerification = useMemo(() => {
    if (!detail?.verification_runs?.length) {
      return null;
    }
    return (
      [...detail.verification_runs].sort((left, right) =>
        (right.finished_at ?? right.started_at ?? "").localeCompare(left.finished_at ?? left.started_at ?? "")
      )[0] ?? null
    );
  }, [detail]);
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [memoryNotice, setMemoryNotice] = useState<string | null>(null);
  const [deliveryNotice, setDeliveryNotice] = useState<string | null>(null);
  const [promotingMemory, setPromotingMemory] = useState(false);
  const [preparingDelivery, setPreparingDelivery] = useState(false);
  const [syncingDelivery, setSyncingDelivery] = useState(false);
  const [artifactLoadFailed, setArtifactLoadFailed] = useState(false);
  const [promotedMemoryItems, setPromotedMemoryItems] = useState<
    NonNullable<CodexIssueDetailResponse["memory_context"]>
  >([]);
  const selectedArtifactSummary = useMemo(() => {
    if (!detail?.artifacts.length) {
      return null;
    }
    return (
      detail.artifacts.find((artifact) => artifact.artifact_id === selectedArtifactId) ??
      latestArtifactSummary
    );
  }, [detail?.artifacts, latestArtifactSummary, selectedArtifactId]);
  const primaryArtifactId = selectedArtifactSummary?.artifact_id ?? null;
  const [primaryArtifact, setPrimaryArtifact] = useState<ArtifactDetail | null>(null);
  const [selectedRunDetail, setSelectedRunDetail] = useState<CodexRunDetailResponse | null>(null);

  useEffect(() => {
    setSelectedArtifactId(latestArtifactSummary?.artifact_id ?? null);
    setSelectedRunId(latestRun?.session_id ?? null);
    setMemoryNotice(null);
    setDeliveryNotice(null);
    setArtifactLoadFailed(false);
    setPromotedMemoryItems([]);
  }, [latestArtifactSummary?.artifact_id, latestRun?.session_id, task?.task_id]);

  useEffect(() => {
    if (!primaryArtifactId) {
      setPrimaryArtifact(null);
      setArtifactLoadFailed(false);
      return;
    }
    setPrimaryArtifact(null);
    setArtifactLoadFailed(false);
    const controller = new AbortController();
    void fetchArtifactDetail(primaryArtifactId, controller.signal)
      .then((payload) => setPrimaryArtifact(payload))
      .catch((error) => {
        if (!(error instanceof Error && error.name === "AbortError")) {
          setPrimaryArtifact(null);
          setArtifactLoadFailed(true);
        }
      });
    return () => controller.abort();
  }, [primaryArtifactId]);

  useEffect(() => {
    if (!selectedRunId) {
      setSelectedRunDetail(null);
      return;
    }
    setSelectedRunDetail(null);
    const controller = new AbortController();
    void fetchCodexRunDetail(selectedRunId, controller.signal)
      .then((payload) => setSelectedRunDetail(payload))
      .catch((error) => {
        if (!(error instanceof Error && error.name === "AbortError")) {
          setSelectedRunDetail(null);
        }
      });
    return () => controller.abort();
  }, [selectedRunId]);

  if (!task) {
    return (
      <aside className="codex-detail-panel codex-panel">
        <div className="codex-empty-copy">Select an issue to inspect its runs, relationships, outputs, and history.</div>
      </aside>
    );
  }
  const detailLoading = Boolean(task && !detail);
  const delivery = detail?.delivery ?? null;
  const runConsole = detail?.run_console ?? null;
  const isReview = task.status === "review";
  const unlockCount = detail?.relationships.unlocks.length ?? 0;
  const outputCount = detail?.artifacts.length ?? 0;
  const hasPreview =
    primaryArtifact?.preview.kind === "text" || primaryArtifact?.preview.kind === "json";
  const previewLabel = primaryArtifact?.preview.kind === "json" ? "JSON preview" : "Text preview";
  const reviewHeadline = isReview
    ? "Decision required"
    : task.status === "blocked"
      ? "Intervention required"
      : "Current task state";
  const reviewSummary = isReview
    ? "Codex finished work on this issue. Review the primary output and checks, then approve or request changes."
    : task.status === "blocked"
      ? "This issue is blocked. Inspect the latest evidence and decide how to recover it."
      : "Inspect the latest output, run state, and linked work before taking action.";
  const consequenceSummary = isReview
    ? unlockCount > 0
      ? `Approving will unblock ${unlockCount} linked issue${unlockCount === 1 ? "" : "s"}.`
      : "Approving will move this issue out of the review queue."
    : task.status === "blocked"
      ? "Recovery or replanning is required before the work can continue."
      : nextActionLabel(task);
  const executionMode = runConsole?.execution_mode ?? latestRun?.execution_mode ?? null;
  const externalRuntime = runConsole?.external_runtime ?? latestRun?.external_runtime ?? null;
  const isSimulationRun = executionMode === "local_simulation";
  const reviewDecision = detail?.review_decision ?? null;
  const reviewPacket = reviewDecision?.grouped_review_packet ?? null;
  const goalExplainability = detail?.goal_explainability ?? null;
  const explainedTask = goalExplainability?.task ?? null;
  const brownfieldGrounding = detail?.brownfield_grounding ?? null;
  const issueActions = actions ? <div className="codex-detail-actions">{actions}</div> : null;
  const checks = detail?.verification_runs ?? [];
  const selectedRunRecord = selectedRunDetail;
  const recoveryPlaybook = detail?.recovery_playbook ?? null;
  const memoryContext = useMemo(() => {
    const base = detail?.memory_context ?? [];
    if (!promotedMemoryItems.length) {
      return base;
    }
    const seen = new Set(base.map((item) => item.artifact_id));
    return [...promotedMemoryItems.filter((item) => !seen.has(item.artifact_id)), ...base];
  }, [detail?.memory_context, promotedMemoryItems]);
  const reviewBundle = (
    <>
      {goalExplainability && explainedTask ? (
        <section className="codex-detail-section">
          <div className="codex-section-heading">
            <strong>Goal explainability</strong>
            <span>
              Step {explainedTask.step_index}/{explainedTask.step_count}
            </span>
          </div>
          <div className="codex-run-list codex-run-list--compact">
            <div className="codex-output-item">
              <strong>
                {explainedTask.stage_label ?? "Planned step"}
                {explainedTask.is_current_focus ? " · current focus" : ""}
                {explainedTask.is_on_critical_path ? ` · critical path #${explainedTask.critical_path_rank}` : ""}
              </strong>
              <span>{explainedTask.why_it_exists}</span>
              <span>{explainedTask.acceptance_summary}</span>
              <span>
                {explainedTask.open_dependency_count > 0
                  ? `${explainedTask.open_dependency_count} open dependency`
                  : "No open dependencies"}
                {explainedTask.open_unlock_count > 0 ? ` · unlocks ${explainedTask.open_unlock_count}` : ""}
              </span>
            </div>
            {goalExplainability.critical_path.items.length ? (
              <div className="codex-output-item">
                <strong>Current critical path</strong>
                <span>
                  {goalExplainability.critical_path.remaining_task_count} remaining step
                  {goalExplainability.critical_path.remaining_task_count === 1 ? "" : "s"}
                </span>
                <span>
                  {goalExplainability.critical_path.items
                    .map((item) => item.issue_key ?? item.title)
                    .join(" -> ")}
                </span>
              </div>
            ) : null}
          </div>
        </section>
      ) : null}
      {brownfieldGrounding ? (
        <section className="codex-detail-section">
          <div className="codex-section-heading">
            <strong>Brownfield grounding</strong>
            <span>{brownfieldGrounding.review_status.replaceAll("_", " ")}</span>
          </div>
          <div className="codex-run-list codex-run-list--compact">
            <div className="codex-output-item">
              <strong>
                {brownfieldGrounding.repo_plan.generated_task_count} repo-plan step
                {brownfieldGrounding.repo_plan.generated_task_count === 1 ? "" : "s"}
                {brownfieldGrounding.repo_plan.stale ? " · stale" : ""}
              </strong>
              <span>
                {brownfieldGrounding.repo_plan.active_task_count} active synthesized task
                {brownfieldGrounding.repo_plan.active_task_count === 1 ? "" : "s"}
              </span>
              <span>
                {brownfieldGrounding.repo_plan.last_refreshed_at
                  ? `Last refreshed ${ageLabel(brownfieldGrounding.repo_plan.last_refreshed_at)} by ${brownfieldGrounding.repo_plan.last_refreshed_by ?? "unknown actor"}`
                  : "Repo-grounded plan has not been refreshed yet."}
              </span>
            </div>
            {brownfieldGrounding.scoped_paths.length ? (
              <div className="codex-output-item">
                <strong>Scoped paths</strong>
                <span>{brownfieldGrounding.scoped_paths.join(", ")}</span>
              </div>
            ) : null}
            {brownfieldGrounding.validation_commands.length ? (
              <div className="codex-output-item">
                <strong>Validation commands</strong>
                <span>{brownfieldGrounding.validation_commands.join(" · ")}</span>
              </div>
            ) : null}
            {brownfieldGrounding.repo_plan_items.map((item) => (
              <div key={item.synthesis_key} className="codex-output-item">
                <strong>
                  {item.title}
                  {item.issue_key ? ` · ${item.issue_key}` : ""}
                  {item.status ? ` · ${statusLabel(item.status, item.review_state)}` : ""}
                </strong>
                <span>
                  {[item.command, ...(item.paths ?? [])].filter(Boolean).join(" · ") || "No explicit repo grounding recorded."}
                </span>
                {(item.linked_items?.length ?? 0) > 0 ? (
                  <span>
                    {item.linked_items
                      ?.map((linked) =>
                        linked.issue_key
                          ? `${linked.direction === "incoming" ? "From" : "To"} ${linked.issue_key}${linked.dependency_type ? ` (${linked.dependency_type})` : ""}`
                          : null
                      )
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                ) : null}
              </div>
            ))}
            {brownfieldGrounding.codebase_areas.map((item) => (
              <div key={`${item.name}-${item.path ?? ""}`} className="codex-output-item">
                <strong>{item.name}</strong>
                <span>
                  {[item.kind.replaceAll("_", " "), item.path, item.primary_language, `${item.file_count} files`]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
                {item.summary ? <span>{item.summary}</span> : null}
              </div>
            ))}
            {brownfieldGrounding.runbook_signals.map((item) => (
              <div key={`${item.label}-${item.command ?? ""}-${item.path ?? ""}`} className="codex-output-item">
                <strong>{item.label}</strong>
                <span>{[item.command, item.path, item.detail].filter(Boolean).join(" · ")}</span>
              </div>
            ))}
            {brownfieldGrounding.workflow_signals.map((item) => (
              <div key={`${item.label}-${item.path ?? ""}`} className="codex-output-item">
                <strong>{item.label}</strong>
                <span>{[item.path, item.detail].filter(Boolean).join(" · ")}</span>
              </div>
            ))}
          </div>
        </section>
      ) : null}
      <section className="codex-detail-section">
        <div className="codex-section-heading">
          <strong>Latest output</strong>
          <span>{detailLoading ? "Loading…" : outputCount}</span>
        </div>
        {detailLoading ? (
          <div className="codex-empty-copy">Loading issue outputs…</div>
        ) : primaryArtifact ? (
          <>
            {(detail?.artifacts.length ?? 0) > 1 ? (
              <div className="codex-chip-row codex-output-selector">
                {detail?.artifacts.map((artifact) => (
                  <button
                    key={artifact.artifact_id}
                    type="button"
                    className={`codex-chip ${artifact.artifact_id === selectedArtifactSummary?.artifact_id ? "codex-chip--active" : ""}`}
                    onClick={() => setSelectedArtifactId(artifact.artifact_id)}
                  >
                    {artifact.file_name}
                  </button>
                ))}
              </div>
            ) : null}
            <div className="codex-output-preview">
              <div className="codex-output-preview__meta">
                <div>
                  <strong>{primaryArtifact.file_name}</strong>
                  <span>
                    {primaryArtifact.artifact_type.replaceAll("_", " ")} · {formatTimestamp(primaryArtifact.created_at)}
                  </span>
                </div>
                {primaryArtifact.download_url ? (
                  <a className="codex-button" href={primaryArtifact.download_url} target="_blank" rel="noreferrer">
                    Download
                  </a>
                ) : null}
              </div>
              {hasPreview ? (
                <>
                  <div className="codex-output-preview__label">
                    {previewLabel}
                    {primaryArtifact.preview.truncated ? " (truncated)" : ""}
                  </div>
                  <pre className="codex-output-preview__content">{primaryArtifact.preview.content}</pre>
                </>
              ) : (
                <div className="codex-empty-copy">
                  Preview unavailable for this output. Use download when you need the full file.
                </div>
              )}
            </div>
          </>
        ) : artifactLoadFailed ? (
          <div className="codex-empty-copy">
            Latest output metadata loaded, but the artifact preview could not be fetched. Try reselecting the output or downloading it directly.
          </div>
        ) : (
          <div className="codex-empty-copy">No outputs have been attached to this issue yet.</div>
        )}
      </section>

      <section className="codex-detail-section">
        <div className="codex-section-heading">
          <strong>Checks</strong>
          <span>{detailLoading ? "Loading…" : checks.length}</span>
        </div>
        {detailLoading ? (
          <div className="codex-empty-copy">Loading verification results…</div>
        ) : checks.length ? (
          <div className="codex-run-list">
            {checks.map((run) => (
              <div key={run.verification_run_id} className="codex-output-item">
                <strong>{run.command}</strong>
                <span>{run.status}</span>
                <span>{run.output_excerpt ?? (run.exit_code != null ? `exit ${run.exit_code}` : "No verification summary recorded.")}</span>
                <span>{formatTimestamp(run.finished_at ?? run.started_at)}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="codex-empty-copy">No automated checks have been recorded for this issue yet.</div>
        )}
      </section>
      <section className="codex-detail-section">
        <div className="codex-section-heading">
          <strong>Reusable memory</strong>
          <span>{detailLoading ? "Loading…" : memoryContext.length}</span>
        </div>
        {memoryNotice ? <div className="codex-review-note">{memoryNotice}</div> : null}
        {detailLoading ? (
          <div className="codex-empty-copy">Loading related memory…</div>
        ) : memoryContext.length ? (
          <div className="codex-run-list">
            {memoryContext.map((item) => (
              <div key={`${item.artifact_id}:${item.task_id ?? "memory"}`} className="codex-output-item">
                <strong>{item.title ?? item.path ?? item.artifact_id}</strong>
                <span>{item.summary ?? "No memory summary recorded."}</span>
                {item.match_summary ? <span>{item.match_summary}</span> : null}
                <span>
                  {(item.tags?.length ?? 0) ? item.tags?.join(", ") : "No tags"}
                  {item.score != null ? ` · score ${item.score}` : ""}
                  {item.freshness ? ` · ${item.freshness}` : ""}
                  {item.age_days != null ? ` · ${item.age_days}d old` : ""}
                  {item.usefulness ? ` · usefulness ${item.usefulness}` : ""}
                  {item.used_count != null ? ` · used ${item.used_count}x` : ""}
                </span>
                {item.usefulness_summary ? <span>{item.usefulness_summary}</span> : null}
              </div>
            ))}
          </div>
        ) : (
          <div className="codex-empty-copy">
            No promoted memory is influencing this issue yet. Promote a useful output when you want future runs to reuse it.
          </div>
        )}
        <div className="codex-detail-actions">
          {primaryArtifactId ? (
            <button
              type="button"
              className="codex-button"
              disabled={promotingMemory}
              onClick={() => {
                setPromotingMemory(true);
                setMemoryNotice(null);
                void promoteArtifactToMemory(primaryArtifactId)
                  .then((payload) => {
                    setPromotedMemoryItems((current) => {
                      const nextItem = {
                        artifact_id: payload.artifact_id,
                        task_id: task.task_id,
                        session_id: latestRun?.session_id ?? null,
                        artifact_type: payload.memory.artifact_type ?? primaryArtifact?.artifact_type ?? "artifact",
                        path: primaryArtifact?.path ?? selectedArtifactSummary?.file_name ?? payload.artifact_id,
                        title: payload.memory.title,
                        summary: payload.memory.summary,
                        tags: payload.memory.tags ?? [],
                        promoted_at: payload.memory.promoted_at,
                        promoted_by: payload.memory.promoted_by,
                        age_days: 0,
                        freshness: "fresh" as const,
                        stale: false,
                        usefulness: "unknown" as const,
                        used_count: 0,
                        success_count: 0,
                        failure_count: 0,
                        success_ratio: null,
                        usefulness_score: 0,
                        preview: payload.preview,
                        score: undefined,
                      };
                      return current.some((item) => item.artifact_id === nextItem.artifact_id) ? current : [nextItem, ...current];
                    });
                    setMemoryNotice("Promoted the selected output into project memory. Future runs can now retrieve it.");
                  })
                  .catch((error) => setMemoryNotice(error instanceof Error ? error.message : "Could not promote artifact to memory."))
                  .finally(() => setPromotingMemory(false));
              }}
            >
              {promotingMemory ? "Promoting..." : "Promote selected output"}
            </button>
          ) : null}
          {task.status === "review" || task.status === "done" ? (
            <>
              <button
                type="button"
                className="codex-button"
                disabled={preparingDelivery || syncingDelivery}
                onClick={() => {
                  setPreparingDelivery(true);
                  setDeliveryNotice(null);
                  void prepareTaskPrDraft(task.task_id)
                    .then((payload) => setDeliveryNotice(`Prepared PR draft "${payload.title}".`))
                    .catch((error) => setDeliveryNotice(error instanceof Error ? error.message : "Could not prepare PR draft."))
                    .finally(() => setPreparingDelivery(false));
                }}
              >
                {preparingDelivery ? "Preparing..." : "Prepare PR draft"}
              </button>
              <button
                type="button"
                className="codex-button"
                disabled={preparingDelivery || syncingDelivery || delivery?.delivery_gate.status === "blocked"}
                onClick={() => {
                  setSyncingDelivery(true);
                  setDeliveryNotice(null);
                  void syncTaskGithubPr(task.task_id)
                    .then((payload) =>
                      setDeliveryNotice(
                        `${payload.mode === "created" ? "Created" : "Updated"} draft PR #${payload.github_pr.number}.`
                      )
                    )
                    .catch((error) => setDeliveryNotice(error instanceof Error ? error.message : "Could not sync GitHub PR."))
                    .finally(() => setSyncingDelivery(false));
                }}
              >
                {syncingDelivery ? "Syncing..." : delivery?.github_pr ? "Sync draft PR" : "Create draft PR"}
              </button>
            </>
          ) : null}
        </div>
        {deliveryNotice ? <div className="codex-review-note">{deliveryNotice}</div> : null}
      </section>
      {issueActions}
    </>
  );

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

      {isSimulationRun ? (
        <div className="codex-banner codex-banner--warn">
          This evidence came from a simulated run, not a live Codex execution. Review it as flow testing, not as production output.
        </div>
      ) : null}

      <section className="codex-detail-section codex-decision-summary">
        <div className="codex-section-heading">
          <strong>{reviewHeadline}</strong>
        </div>
        <div className="codex-review-callout">
          <strong>{reviewSummary}</strong>
          <p>{consequenceSummary}</p>
          {reviewDecision ? (
            <div className="codex-review-note">
              {reviewDecision.summary} {reviewDecision.detail}
            </div>
          ) : null}
          {reviewPacket ? (
            <div className="codex-review-note">
              Review packet: {reviewPacket.title ?? "Grouped review"} ·{" "}
              {reviewPacket.packet_scope_label ?? reviewPacket.packet_scope ?? "shared scope"}
            </div>
          ) : null}
          {reviewDecision?.why_not_auto_approved ? (
            <div className="codex-review-note">Why this did not auto-approve: {reviewDecision.why_not_auto_approved}</div>
          ) : null}
          {!reviewDecision?.batch_review_eligible && reviewDecision?.why_not_batch_reviewed ? (
            <div className="codex-review-note">Why this stayed manual: {reviewDecision.why_not_batch_reviewed}</div>
          ) : null}
          <div className="codex-review-facts">
            <div className="codex-review-fact">
              <span>Priority</span>
              <strong>{priorityLabel(task.priority)}</strong>
            </div>
            <div className="codex-review-fact">
              <span>Owner</span>
              <strong>{task.agent?.name ?? "Unassigned"}</strong>
            </div>
            <div className="codex-review-fact">
              <span>Next step</span>
              <strong>{nextActionLabel(task)}</strong>
            </div>
          </div>
          {latestRun ? (
            <div className="codex-review-note">
              Latest run: {latestRun.agent_name ?? latestRun.agent_id ?? "Unknown agent"} via{" "}
              {latestRun.provider_type.replaceAll("_", " ")} · {formatExecutionModeLabel(latestRun.execution_mode)} at{" "}
              {formatTimestamp(latestRun.ended_at ?? latestRun.started_at)}.
            </div>
          ) : null}
          {externalRuntime && !isSimulationRun ? (
            <div className="codex-review-note">External runtime: {formatExecutionModeLabel(externalRuntime)}</div>
          ) : null}
          {latestVerification ? (
            <div className="codex-review-note">
              Latest check: {latestVerification.command} · {latestVerification.status}
            </div>
          ) : null}
          {detailLoading ? (
            <div className="codex-review-note">Loading outputs, checks, and linked work for this issue…</div>
          ) : null}
        </div>
      </section>

      {recoveryPlaybook ? (
        <section className="codex-detail-section">
          <div className="codex-section-heading">
            <strong>Recovery playbook</strong>
            <span>{recoveryPlaybook.confidence}</span>
          </div>
          <div className="codex-review-callout">
            <strong>{recoveryPlaybook.title}</strong>
            <p>{recoveryPlaybook.summary}</p>
            <div className="codex-review-note">{recoveryPlaybook.detail}</div>
            <div className="codex-review-facts">
              <div className="codex-review-fact">
                <span>Recommended</span>
                <strong>{recoveryPlaybook.recommended_action.replaceAll("_", " ")}</strong>
              </div>
              <div className="codex-review-fact">
                <span>Actions</span>
                <strong>{recoveryPlaybook.actions.join(" · ")}</strong>
              </div>
            </div>
          </div>
        </section>
      ) : null}

      {runConsole?.is_live ? (
        <section className="codex-detail-section">
          <div className="codex-section-heading">
            <strong>{runConsole.is_live ? "Live run" : "Latest run trace"}</strong>
            <span>{runConsole.is_live ? "active" : runConsole.status.replaceAll("_", " ")}</span>
          </div>
          <div className="codex-review-callout">
            <strong>{runConsole.status_message ?? "No live runtime message recorded."}</strong>
            <p>
              {runConsole.agent_name ?? runConsole.agent_id ?? "Unknown agent"} via{" "}
              {runConsole.provider_type.replaceAll("_", " ")} · {formatExecutionModeLabel(runConsole.execution_mode)} · started{" "}
              {formatTimestamp(runConsole.started_at)}
              {runConsole.timeout_seconds ? ` · timeout ${runConsole.timeout_seconds}s` : ""}
            </p>
            <div className="codex-review-facts">
              <div className="codex-review-fact">
                <span>Status</span>
                <strong>{runConsole.status.replaceAll("_", " ")}</strong>
              </div>
              <div className="codex-review-fact">
                <span>Progress</span>
                <strong>{runConsole.progress_pct ?? 0}%</strong>
              </div>
              <div className="codex-review-fact">
                <span>Active for</span>
                <strong>{ageLabel(runConsole.started_at)}</strong>
              </div>
              <div className="codex-review-fact">
                <span>Heartbeat</span>
                <strong>{ageLabel(runConsole.last_heartbeat_at ?? runConsole.started_at)}</strong>
              </div>
            </div>
            {runConsole.command?.length ? (
              <div className="codex-review-note">Command: {runConsole.command.join(" ")}</div>
            ) : null}
          </div>

          <div className="codex-detail-stack">
            {renderConsolePreview("Runtime output", runConsole.output_preview ?? null)}
            {renderConsolePreview("Stderr", runConsole.stderr_preview ?? null)}
            {renderConsolePreview("Stdout", runConsole.stdout_preview ?? null)}
          </div>
          {onNavigate ? (
            <div className="codex-detail-actions">
              <button
                type="button"
                className="codex-button"
                onClick={() => {
                  setPendingRunFocus(runConsole.session_id);
                  onNavigate("runs");
                }}
              >
                Open run page
              </button>
            </div>
          ) : null}

          <div className="codex-section-heading">
            <strong>Session activity</strong>
            <span>{runConsole.activity.length}</span>
          </div>
          <div className="codex-history-list">
            {runConsole.activity.length ? (
              runConsole.activity.map((event) => (
                <div key={`${event.activity_id ?? event.created_at}:${event.action}`} className="codex-history-item">
                  <div className="codex-history-item__meta">
                    <strong>{event.action.replaceAll("_", " ")}</strong>
                    <span>{formatTimestamp(event.created_at)}</span>
                  </div>
                  <span>{event.description}</span>
                </div>
              ))
            ) : (
              <div className="codex-empty-copy">No session-scoped activity has been logged for this run yet.</div>
            )}
          </div>
        </section>
      ) : null}

      {reviewBundle}

      {runConsole && !runConsole.is_live ? (
        <section className="codex-detail-section">
          <div className="codex-section-heading">
            <strong>Latest run trace</strong>
            <span>{runConsole.status.replaceAll("_", " ")}</span>
          </div>
          <div className="codex-review-callout">
            <strong>{runConsole.status_message ?? "No runtime summary recorded."}</strong>
            <p>
              {runConsole.agent_name ?? runConsole.agent_id ?? "Unknown agent"} via{" "}
              {runConsole.provider_type.replaceAll("_", " ")} · {formatExecutionModeLabel(runConsole.execution_mode)} · started{" "}
              {formatTimestamp(runConsole.started_at)}
            </p>
          </div>
          <div className="codex-detail-stack">
            {renderConsolePreview("Runtime output", runConsole.output_preview ?? null)}
            {renderConsolePreview("Stderr", runConsole.stderr_preview ?? null)}
            {renderConsolePreview("Stdout", runConsole.stdout_preview ?? null)}
          </div>
        </section>
      ) : null}

      <details className="codex-detail-foldout">
        <summary>Delivery</summary>
        {detailLoading ? <div className="codex-detail-section codex-empty-copy">Loading delivery state…</div> : null}
        {!detailLoading && delivery ? (
          <>
            <section className="codex-detail-section">
              <div className="codex-section-heading">
                <strong>Delivery gate</strong>
                <span>{delivery.delivery_gate.status}</span>
              </div>
              <div className="codex-review-callout">
                <strong>{delivery.delivery_gate.summary}</strong>
                <p>{delivery.delivery_gate.detail}</p>
              </div>
              <div className="codex-history-list">
                {delivery.delivery_gate.checks.map((check) => (
                  <div key={check.code} className="codex-history-item">
                    <div className="codex-history-item__meta">
                      <strong>{check.label}</strong>
                      <span>{check.status}</span>
                    </div>
                    <span>{check.summary}</span>
                  </div>
                ))}
              </div>
            </section>

            <section className="codex-detail-section">
              <div className="codex-section-heading">
                <strong>GitHub draft PR</strong>
                <span>{delivery.github_pr ? `#${delivery.github_pr.number}` : "Not synced"}</span>
              </div>
              {delivery.github_pr ? (
                <div className="codex-review-callout">
                  <strong>{delivery.github_pr.title ?? "Draft PR synced"}</strong>
                  <p>
                    {delivery.github_pr.is_draft ? "Draft" : "Ready"} · {delivery.github_pr.state ?? "OPEN"} ·{" "}
                    {delivery.github_pr.head_branch ?? "branch?"} to {delivery.github_pr.base_branch ?? "base?"}
                  </p>
                  <p>{delivery.github_pr.url}</p>
                </div>
              ) : (
                <div className="codex-empty-copy">No GitHub draft PR has been synced for this issue yet.</div>
              )}
              {delivery.latest_draft ? (
                <div className="codex-review-note">
                  Latest draft prepared {formatTimestamp(delivery.latest_draft.prepared_at)} at {delivery.latest_draft.body_path}
                </div>
              ) : null}
            </section>
          </>
        ) : null}
      </details>

      <details className="codex-detail-foldout">
        <summary>Decision context</summary>
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
      </details>

      <details className="codex-detail-foldout">
        <summary>Dependencies and related work</summary>
        {detailLoading ? <div className="codex-detail-section codex-empty-copy">Loading linked work…</div> : null}
        {!detailLoading ? (
          <>
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
          </>
        ) : null}
      </details>

      <details className="codex-detail-foldout">
        <summary>Runs and history</summary>
        {detailLoading ? <div className="codex-detail-section codex-empty-copy">Loading runs and history…</div> : null}
        {!detailLoading ? (
          <>
        <section className="codex-detail-section">
          <div className="codex-section-heading">
            <strong>Runs</strong>
            <span>{detail?.runs.length ?? 0}</span>
          </div>
          <div className="codex-run-list">
            {(detail?.runs ?? []).length ? (
              detail?.runs.map((run) => (
                <button
                  key={run.session_id}
                  type="button"
                  className="codex-run-item codex-run-item--interactive"
                  onClick={() => setSelectedRunId(run.session_id)}
                >
                  <div className="codex-run-item__meta">
                    <strong>{run.agent_name ?? run.agent_id ?? "Unknown agent"}</strong>
                    <span>{run.status.replaceAll("_", " ")}</span>
                  </div>
                  <span>{run.status_message || "No run summary recorded."}</span>
                  <span>{formatTimestamp(run.started_at)} · {formatExecutionModeLabel(run.execution_mode)}</span>
                </button>
              ))
            ) : (
              <div className="codex-empty-copy">No runs recorded for this issue yet.</div>
            )}
          </div>
        </section>

        {selectedRunRecord ? (
          <section className="codex-detail-section">
            <div className="codex-section-heading">
              <strong>Selected run record</strong>
              <span>{selectedRunRecord.status.replaceAll("_", " ")}</span>
            </div>
            <div className="codex-review-callout">
              <strong>{selectedRunRecord.status_message ?? "No runtime summary recorded."}</strong>
              <p>
                {selectedRunRecord.agent_name ?? selectedRunRecord.agent_id ?? "Unknown agent"} via{" "}
                {selectedRunRecord.provider_type.replaceAll("_", " ")} · {formatExecutionModeLabel(selectedRunRecord.execution_mode)} · started{" "}
                {formatTimestamp(selectedRunRecord.started_at)}
              </p>
            </div>
            <div className="codex-detail-stack">
              {renderConsolePreview("Runtime output", selectedRunRecord.output_preview ?? null)}
              {renderConsolePreview("Stderr", selectedRunRecord.stderr_preview ?? null)}
              {renderConsolePreview("Stdout", selectedRunRecord.stdout_preview ?? null)}
            </div>
            {onNavigate ? (
              <div className="codex-detail-actions">
                <button
                  type="button"
                  className="codex-button"
                  onClick={() => {
                    setPendingRunFocus(selectedRunRecord.session_id);
                    onNavigate("runs");
                  }}
                >
                  Open run page
                </button>
              </div>
            ) : null}
            <div className="codex-section-heading">
              <strong>Run-scoped artifacts</strong>
              <span>{selectedRunRecord.artifacts.length}</span>
            </div>
            <div className="codex-run-list">
              {selectedRunRecord.artifacts.length ? (
                selectedRunRecord.artifacts.map((artifact) => (
                  <div key={artifact.artifact_id} className="codex-output-item">
                    <strong>{artifact.file_name}</strong>
                    <span>{artifact.artifact_type.replaceAll("_", " ")}</span>
                    <span>{formatTimestamp(artifact.created_at)}</span>
                  </div>
                ))
              ) : (
                <div className="codex-empty-copy">No artifacts were attached directly to this run.</div>
              )}
            </div>
          </section>
        ) : null}

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
          </>
        ) : null}
      </details>
    </aside>
  );
}
