import { startTransition, useDeferredValue, useEffect, useState } from "react";
import {
  artifactDownloadUrl,
  fetchArtifactComparison,
  fetchArtifactDetail,
  fetchArtifacts,
  runFailureOperatorAction
} from "../lib/controlRoomApi";
import { useLivePulse } from "../lib/useLivePulse";
import type { ArtifactComparisonResponse, ArtifactDetail, ArtifactsResponse } from "../types";
import { StatCard } from "../components/StatCard";

const PAGE_SIZE = 25;

function formatBytes(value?: number | null) {
  if (value == null) {
    return "Unknown size";
  }
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function formatPreviewReason(reason?: string | null) {
  return (reason ?? "unsupported_file").replaceAll("_", " ");
}

function formatComparisonReason(reason?: string | null) {
  if (reason === "preview_unavailable") {
    return "One or both artifacts do not expose a safe text or JSON preview.";
  }
  return formatPreviewReason(reason);
}

function formatDependencyType(value: string) {
  return value.replaceAll("_", " ");
}

export function ArtifactsPage() {
  const [artifacts, setArtifacts] = useState<ArtifactsResponse | null>(null);
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null);
  const [selectedArtifact, setSelectedArtifact] = useState<ArtifactDetail | null>(null);
  const [selectedCompareArtifactId, setSelectedCompareArtifactId] = useState<string | null>(null);
  const [artifactComparison, setArtifactComparison] = useState<ArtifactComparisonResponse | null>(null);
  const [query, setQuery] = useState("");
  const [stateFilter, setStateFilter] = useState("all");
  const [providerFilter, setProviderFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [taskFilter, setTaskFilter] = useState("");
  const [sessionFilter, setSessionFilter] = useState("");
  const [missingOnly, setMissingOnly] = useState(false);
  const [offset, setOffset] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isDetailRefreshing, setIsDetailRefreshing] = useState(false);
  const [isComparisonRefreshing, setIsComparisonRefreshing] = useState(false);
  const [pendingArtifactAction, setPendingArtifactAction] = useState<string | null>(null);
  const deferredQuery = useDeferredValue(query.trim().toLowerCase());
  const livePulse = useLivePulse();

  async function loadArtifacts(signal?: AbortSignal) {
    setIsRefreshing(true);
    let usedFallback = false;
    try {
      const payload = await fetchArtifacts(
        {
          search: deferredQuery || undefined,
          state: stateFilter,
          providerType: providerFilter,
          artifactType: typeFilter,
          taskId: taskFilter || undefined,
          sessionId: sessionFilter || undefined,
          missingOnly,
          limit: PAGE_SIZE,
          offset
        },
        signal,
        () => {
          usedFallback = true;
        }
      );
      startTransition(() => {
        setArtifacts(payload);
      });
      setNotice(usedFallback ? "Artifact refresh failed; showing the most recent available snapshot." : null);
    } catch (error) {
      if (!(error instanceof Error && error.name === "AbortError")) {
        setNotice("Artifact refresh failed; showing the most recent available snapshot.");
      }
    } finally {
      setIsRefreshing(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void loadArtifacts(controller.signal);

    return () => {
      controller.abort();
    };
  }, [deferredQuery, missingOnly, offset, providerFilter, sessionFilter, stateFilter, taskFilter, typeFilter]);

  useEffect(() => {
    if (livePulse === 0) {
      return;
    }
    void loadArtifacts();
  }, [livePulse]);

  useEffect(() => {
    const visibleIds = (artifacts?.items ?? []).map((item) => item.artifact_id);
    if (visibleIds.length === 0) {
      if (!selectedArtifactId) {
        setSelectedArtifact(null);
      }
      return;
    }
    if (!selectedArtifactId) {
      setSelectedArtifactId(visibleIds[0]);
    }
  }, [artifacts, selectedArtifactId]);

  useEffect(() => {
    if (!selectedArtifactId) {
      setSelectedArtifact(null);
      return;
    }

    const controller = new AbortController();
    async function loadDetail() {
      setIsDetailRefreshing(true);
      try {
        const payload = await fetchArtifactDetail(selectedArtifactId, controller.signal);
        setSelectedArtifact(payload);
      } catch (error) {
        if (!(error instanceof Error && error.name === "AbortError")) {
          setNotice("Artifact detail refresh failed; keep using the latest available registry snapshot.");
        }
      } finally {
        setIsDetailRefreshing(false);
      }
    }

    void loadDetail();
    return () => {
      controller.abort();
    };
  }, [selectedArtifactId, livePulse]);

  useEffect(() => {
    setSelectedCompareArtifactId(null);
    setArtifactComparison(null);
  }, [selectedArtifactId]);

  useEffect(() => {
    if (!selectedArtifactId || !selectedCompareArtifactId) {
      setArtifactComparison(null);
      return;
    }

    const controller = new AbortController();
    async function loadComparison() {
      setIsComparisonRefreshing(true);
      try {
        const payload = await fetchArtifactComparison(selectedArtifactId, selectedCompareArtifactId, controller.signal);
        setArtifactComparison(payload);
      } catch (error) {
        if (!(error instanceof Error && error.name === "AbortError")) {
          setNotice("Artifact comparison failed; keep using the current detail snapshot.");
        }
      } finally {
        setIsComparisonRefreshing(false);
      }
    }

    void loadComparison();
    return () => {
      controller.abort();
    };
  }, [selectedArtifactId, selectedCompareArtifactId, livePulse]);

  async function handleArtifactAction(artifactId: string, actionKind: "primary" | "secondary" = "primary") {
    const artifact = artifacts?.items.find((item) => item.artifact_id === artifactId);
    const operatorAction =
      actionKind === "secondary" ? artifact?.secondary_operator_action : artifact?.operator_action;
    if (!operatorAction) {
      return;
    }

    setPendingArtifactAction(`${artifactId}:${operatorAction.action}`);
    setNotice(null);
    try {
      await runFailureOperatorAction(operatorAction);
      await loadArtifacts();
      setSelectedCompareArtifactId(null);
      setArtifactComparison(null);
      if (selectedArtifactId === artifactId) {
        const payload = await fetchArtifactDetail(artifactId);
        setSelectedArtifact(payload);
      }
      if (operatorAction.action === "restore_and_requeue_quarantine_entry") {
        setNotice(`Restored quarantined artifacts and returned task ${operatorAction.related_task_id} to the queue.`);
      } else if (operatorAction.action === "restore_quarantine_entry") {
        setNotice(`Restored quarantined artifacts for ${operatorAction.resource_id}.`);
      } else if (operatorAction.action === "dismiss_quarantine_entry") {
        setNotice(`Dismissed quarantine entry ${operatorAction.resource_id}; artifacts remain isolated.`);
      } else if (operatorAction.action === "reopen_quarantine_entry") {
        setNotice(`Reopened quarantine entry ${operatorAction.resource_id} for operator review.`);
      } else {
        setNotice(`Recovered and requeued task ${operatorAction.resource_id}.`);
      }
    } catch {
      setNotice("Artifact action failed; keep the quarantine incident under operator review.");
    } finally {
      setPendingArtifactAction(null);
    }
  }

  const visibleItems = artifacts?.items ?? [];
  const hasPreviousPage = (artifacts?.offset ?? 0) > 0;
  const hasNextPage = (artifacts?.offset ?? 0) + visibleItems.length < (artifacts?.filtered_count ?? 0);
  const detailArtifact = selectedArtifact;
  const downloadHref = detailArtifact ? artifactDownloadUrl(detailArtifact.artifact_id) : null;
  const hasLineageFilter = Boolean(taskFilter || sessionFilter);

  function applyTaskFilter(nextTaskId?: string | null) {
    setOffset(0);
    setTaskFilter(nextTaskId ?? "");
    setSessionFilter("");
    setSelectedArtifactId(null);
    setSelectedArtifact(null);
    setSelectedCompareArtifactId(null);
    setArtifactComparison(null);
  }

  function applySessionFilter(nextSessionId?: string | null) {
    setOffset(0);
    setSessionFilter(nextSessionId ?? "");
    setTaskFilter("");
    setSelectedArtifactId(null);
    setSelectedArtifact(null);
    setSelectedCompareArtifactId(null);
    setArtifactComparison(null);
  }

  function renderTaskArtifactLinks(
    heading: string,
    description: string,
    links: ArtifactDetail["upstream_task_artifacts"] | undefined
  ) {
    return (
      <div className="artifact-detail__section">
        <div className="data-panel__header">
          <div>
            <h3>{heading}</h3>
            <p>{description}</p>
          </div>
        </div>
        <div className="data-list">
          {(links ?? []).map((link) => (
            <div key={`${heading}-${link.task_id}-${link.dependency_type}`} className="data-list__item">
              <div>
                <strong>{link.task_title ?? link.task_id}</strong>
                <p>
                  {formatDependencyType(link.dependency_type)} | {link.artifact_count} artifact
                  {link.artifact_count === 1 ? "" : "s"}
                </p>
                {link.recent_artifacts.length > 0 ? (
                  <p>{link.recent_artifacts.map((artifact) => artifact.file_name).join(", ")}</p>
                ) : (
                  <p>No artifacts recorded on this task yet.</p>
                )}
              </div>
              <div className="data-list__meta">
                <button
                  type="button"
                  className="task-action task-action--secondary"
                  onClick={() => applyTaskFilter(link.task_id)}
                >
                  Show task artifacts
                </button>
              </div>
            </div>
          ))}
          {(links ?? []).length === 0 ? (
            <div className="data-list__item">
              <div>
                <strong>No linked task artifacts.</strong>
                <p>No dependency-linked task artifacts are associated with this artifact yet.</p>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <section className="control-page">
      <header className="page-hero">
        <div>
          <span className="eyebrow">Artifacts</span>
          <h1>Artifact registry and file-state view</h1>
          <p>Browse runtime outputs across active work, quarantined incidents, restored artifacts, and any files that have gone missing.</p>
        </div>
        <div className="page-hero__actions">
          <div className="status-chip">
            <span className={`status-chip__dot ${isRefreshing ? "is-live" : ""}`} />
            {isRefreshing ? "Refreshing artifacts" : "Artifact snapshot"}
          </div>
          {notice ? <p className="page-hero__notice">{notice}</p> : null}
        </div>
      </header>

      <section className="stats-grid">
        <StatCard label="Artifacts total" value={artifacts?.summary.total_artifacts ?? 0} />
        <StatCard label="Matching now" value={artifacts?.filtered_count ?? 0} tone="good" />
        <StatCard label="Quarantined" value={artifacts?.summary.quarantined_artifacts ?? 0} tone="warn" />
        <StatCard label="Restored" value={artifacts?.summary.restored_artifacts ?? 0} />
        <StatCard label="External" value={artifacts?.summary.external_artifacts ?? 0} />
        <StatCard label="Missing files" value={artifacts?.summary.missing_files ?? 0} tone="warn" />
      </section>

      <section className="filters-panel">
        <div className="filters-panel__header">
          <div>
            <h2>Artifact filters</h2>
            <p>Search by artifact id, task, provider, path, or quarantine metadata without leaving the control room.</p>
          </div>
        </div>
        <div className="filters-panel__grid">
          <label className="filter-field">
            <span>Search</span>
            <input
              value={query}
              onChange={(event) => {
                setOffset(0);
                setQuery(event.target.value);
              }}
              placeholder="Search id, task, provider, or path"
            />
          </label>
          <label className="filter-field">
            <span>State</span>
            <select
              value={stateFilter}
              onChange={(event) => {
                setOffset(0);
                setStateFilter(event.target.value);
              }}
            >
              <option value="all">All states</option>
              <option value="active">Active</option>
              <option value="quarantined">Quarantined</option>
              <option value="restored">Restored</option>
              <option value="external">External</option>
            </select>
          </label>
          <label className="filter-field">
            <span>Provider</span>
            <select
              value={providerFilter}
              onChange={(event) => {
                setOffset(0);
                setProviderFilter(event.target.value);
              }}
            >
              <option value="all">All providers</option>
              {(artifacts?.provider_types ?? []).map((entry) => (
                <option key={entry.provider_type ?? "unknown"} value={entry.provider_type ?? "unknown"}>
                  {entry.provider_type ?? "unknown"} ({entry.count})
                </option>
              ))}
            </select>
          </label>
          <label className="filter-field">
            <span>Artifact type</span>
            <select
              value={typeFilter}
              onChange={(event) => {
                setOffset(0);
                setTypeFilter(event.target.value);
              }}
            >
              <option value="all">All types</option>
              {(artifacts?.artifact_types ?? []).map((entry) => (
                <option key={entry.artifact_type ?? "unknown"} value={entry.artifact_type ?? "unknown"}>
                  {entry.artifact_type ?? "unknown"} ({entry.count})
                </option>
              ))}
            </select>
          </label>
          <div className="toggle-row">
            <button
              type="button"
              className={`toggle-pill ${missingOnly ? "is-active" : ""}`}
              onClick={() => {
                setOffset(0);
                setMissingOnly((current) => !current);
              }}
            >
              Missing files only
            </button>
          </div>
        </div>
        {hasLineageFilter ? (
          <div className="task-card__actions">
            {taskFilter ? <span className="goal-status goal-status--active">Task filter: {taskFilter}</span> : null}
            {sessionFilter ? <span className="goal-status goal-status--active">Session filter: {sessionFilter}</span> : null}
            <button
              type="button"
              className="task-action task-action--secondary"
              onClick={() => {
                setOffset(0);
                setTaskFilter("");
                setSessionFilter("");
              }}
            >
              Clear lineage filters
            </button>
          </div>
        ) : null}
      </section>

      <section className="overview-grid">
        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Recent artifacts</h2>
              <p>
                Server-filtered artifact results with task, session, and file-state context.
                Showing {visibleItems.length} of {artifacts?.filtered_count ?? 0} matching rows.
              </p>
            </div>
            <div className="task-card__actions">
              <button
                type="button"
                className="task-action task-action--secondary"
                disabled={!hasPreviousPage || isRefreshing}
                onClick={() => setOffset((current) => Math.max(0, current - PAGE_SIZE))}
              >
                Previous
              </button>
              <button
                type="button"
                className="task-action task-action--secondary"
                disabled={!hasNextPage || isRefreshing}
                onClick={() => setOffset((current) => current + PAGE_SIZE)}
              >
                Next
              </button>
            </div>
          </header>
          <div className="data-list">
            {visibleItems.map((item) => (
              <div
                key={item.artifact_id}
                className={`data-list__item ${selectedArtifactId === item.artifact_id ? "is-selected" : ""}`}
              >
                <div>
                  <strong>{item.file_name}</strong>
                  <p>{item.display_path}</p>
                  <p>
                    {item.task_title ?? item.task_id ?? "Unlinked task"}
                    {item.provider_type ? ` | ${item.provider_type}` : ""}
                    {item.agent_name ? ` | ${item.agent_name}` : ""}
                  </p>
                  {item.quarantined_from_path ? <p>Original path: {item.quarantined_from_path}</p> : null}
                  {item.quarantine_reason ? <p>Quarantine reason: {item.quarantine_reason}</p> : null}
                </div>
                <div className="data-list__meta">
                  <span className={`goal-status goal-status--${item.artifact_state}`}>{item.artifact_state}</span>
                  <span>{item.artifact_type}</span>
                  <span>{item.exists ? formatBytes(item.size_bytes) : "Missing file"}</span>
                  <span>{new Date(item.created_at).toLocaleString()}</span>
                  <button
                    type="button"
                    className="task-action task-action--secondary"
                    onClick={() => setSelectedArtifactId(item.artifact_id)}
                  >
                    {selectedArtifactId === item.artifact_id ? "Inspecting" : "Inspect"}
                  </button>
                  {item.operator_action ? (
                    <button
                      type="button"
                      className="task-action task-action--approve"
                      disabled={pendingArtifactAction?.startsWith(`${item.artifact_id}:`) ?? false}
                      onClick={() => void handleArtifactAction(item.artifact_id, "primary")}
                    >
                      {pendingArtifactAction === `${item.artifact_id}:${item.operator_action.action}`
                        ? item.operator_action.action === "restore_and_requeue_quarantine_entry"
                          ? "Restoring..."
                          : item.operator_action.action === "dismiss_quarantine_entry"
                            ? "Dismissing..."
                            : item.operator_action.action === "reopen_quarantine_entry"
                              ? "Reopening..."
                              : "Restoring..."
                        : item.operator_action.label}
                    </button>
                  ) : null}
                  {item.secondary_operator_action ? (
                    <button
                      type="button"
                      className="task-action task-action--secondary"
                      disabled={pendingArtifactAction?.startsWith(`${item.artifact_id}:`) ?? false}
                      onClick={() => void handleArtifactAction(item.artifact_id, "secondary")}
                    >
                      {pendingArtifactAction === `${item.artifact_id}:${item.secondary_operator_action.action}`
                        ? item.secondary_operator_action.action === "dismiss_quarantine_entry"
                          ? "Dismissing..."
                          : item.secondary_operator_action.label
                        : item.secondary_operator_action.label}
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
            {visibleItems.length === 0 ? (
              <div className="data-list__item">
                <div>
                  <strong>No artifacts match the current filters.</strong>
                  <p>Broaden the search or state filters to see more runtime output.</p>
                </div>
              </div>
            ) : null}
          </div>
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Artifact detail</h2>
              <p>Inspect file origin, quarantine history, metadata, and a safe inline preview.</p>
            </div>
            <div className="task-card__actions">
              <div className="status-chip">
                <span className={`status-chip__dot ${isDetailRefreshing ? "is-live" : ""}`} />
                {isDetailRefreshing ? "Refreshing detail" : "Artifact detail"}
              </div>
            </div>
          </header>
          {detailArtifact ? (
            <div className="artifact-detail">
              <div className="artifact-detail__header">
                <div>
                  <strong>{detailArtifact.file_name}</strong>
                  <p>{detailArtifact.display_path}</p>
                </div>
                <div className="artifact-detail__actions">
                  <span className={`goal-status goal-status--${detailArtifact.artifact_state}`}>{detailArtifact.artifact_state}</span>
                  {detailArtifact.download_url ? (
                    <a
                      className="task-action task-action--secondary artifact-download-link"
                      href={downloadHref ?? undefined}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Download
                    </a>
                  ) : null}
                </div>
              </div>

              <div className="artifact-detail__grid">
                <div>
                  <span>Task</span>
                  <strong>{detailArtifact.task_title ?? detailArtifact.task_id ?? "Unlinked task"}</strong>
                </div>
                <div>
                  <span>Provider</span>
                  <strong>{detailArtifact.provider_type ?? "unknown"}</strong>
                </div>
                <div>
                  <span>Agent</span>
                  <strong>{detailArtifact.agent_name ?? detailArtifact.agent_id ?? "Unknown agent"}</strong>
                </div>
                <div>
                  <span>Artifact type</span>
                  <strong>{detailArtifact.artifact_type}</strong>
                </div>
              </div>

              <div className="artifact-detail__grid">
                <div>
                  <span>Workspace path</span>
                  <strong>{detailArtifact.display_path}</strong>
                </div>
                <div>
                  <span>Absolute path</span>
                  <strong>{detailArtifact.absolute_path ?? detailArtifact.path}</strong>
                </div>
                <div>
                  <span>Session</span>
                  <strong>{detailArtifact.session_id ?? "No session"}</strong>
                </div>
                <div>
                  <span>Created</span>
                  <strong>{new Date(detailArtifact.created_at).toLocaleString()}</strong>
                </div>
              </div>

              <div className="artifact-detail__section">
                <div className="data-panel__header">
                  <div>
                    <h3>Lineage</h3>
                    <p>Pivot the registry by this artifact’s task or runtime session.</p>
                  </div>
                  <div className="task-card__actions">
                    {detailArtifact.task_id ? (
                      <button
                        type="button"
                        className="task-action task-action--secondary"
                        onClick={() => applyTaskFilter(detailArtifact.task_id)}
                      >
                        Show task artifacts
                      </button>
                    ) : null}
                    {detailArtifact.session_id ? (
                      <button
                        type="button"
                        className="task-action task-action--secondary"
                        onClick={() => applySessionFilter(detailArtifact.session_id)}
                      >
                        Show session artifacts
                      </button>
                    ) : null}
                  </div>
                </div>
                <div className="artifact-detail__grid">
                  <div>
                    <span>Artifacts on task</span>
                    <strong>{detailArtifact.lineage_summary?.task_artifact_count ?? 0}</strong>
                  </div>
                  <div>
                    <span>Artifacts in session</span>
                    <strong>{detailArtifact.lineage_summary?.session_artifact_count ?? 0}</strong>
                  </div>
                  <div>
                    <span>Task id</span>
                    <strong>{detailArtifact.task_id ?? "No task"}</strong>
                  </div>
                  <div>
                    <span>Session id</span>
                    <strong>{detailArtifact.session_id ?? "No session"}</strong>
                  </div>
                </div>
              </div>

              {detailArtifact.quarantine_entry ? (
                <div className="artifact-detail__section">
                  <h3>Quarantine incident</h3>
                  <div className="artifact-detail__grid">
                    <div>
                      <span>Queue</span>
                      <strong>{detailArtifact.quarantine_entry.queue_id}</strong>
                    </div>
                    <div>
                      <span>Status</span>
                      <strong>{detailArtifact.quarantine_entry.status}</strong>
                    </div>
                    <div>
                      <span>Reason</span>
                      <strong>{detailArtifact.quarantine_entry.reason ?? detailArtifact.quarantine_reason ?? "Not recorded"}</strong>
                    </div>
                    <div>
                      <span>Resolved</span>
                      <strong>
                        {detailArtifact.quarantine_entry.resolved_at
                          ? new Date(detailArtifact.quarantine_entry.resolved_at).toLocaleString()
                          : "Still open"}
                      </strong>
                    </div>
                  </div>
                </div>
              ) : null}

              <div className="artifact-detail__section">
                <h3>Preview</h3>
                {detailArtifact.preview.kind === "unavailable" ? (
                  <p>Preview unavailable: {formatPreviewReason(detailArtifact.preview.reason)}.</p>
                ) : (
                  <>
                    <p>
                      {detailArtifact.preview.kind === "json" ? "JSON preview" : "Text preview"}
                      {detailArtifact.preview.truncated ? " (truncated)" : ""}
                    </p>
                    <pre className="artifact-preview">{detailArtifact.preview.content}</pre>
                  </>
                )}
              </div>

              <div className="artifact-detail__section">
                <h3>Metadata</h3>
                <pre className="artifact-preview">{JSON.stringify(detailArtifact.metadata, null, 2)}</pre>
              </div>

              <div className="artifact-detail__section">
                <div className="data-panel__header">
                  <div>
                    <h3>Other artifacts from this session</h3>
                    <p>Outputs captured during the same runtime attempt.</p>
                  </div>
                </div>
                <div className="data-list">
                  {(detailArtifact.session_artifacts ?? []).map((item) => (
                    <div key={item.artifact_id} className="data-list__item">
                      <div>
                        <strong>{item.file_name}</strong>
                        <p>{item.display_path}</p>
                        <p>
                          {item.artifact_type}
                          {item.provider_type ? ` | ${item.provider_type}` : ""}
                        </p>
                      </div>
                      <div className="data-list__meta">
                        <span className={`goal-status goal-status--${item.artifact_state}`}>{item.artifact_state}</span>
                        <span>{new Date(item.created_at).toLocaleString()}</span>
                        <button
                          type="button"
                          className="task-action task-action--secondary"
                          onClick={() => setSelectedArtifactId(item.artifact_id)}
                        >
                          Inspect
                        </button>
                      </div>
                    </div>
                  ))}
                  {(detailArtifact.session_artifacts ?? []).length === 0 ? (
                    <div className="data-list__item">
                      <div>
                        <strong>No sibling session artifacts.</strong>
                        <p>This runtime session only recorded the currently selected artifact.</p>
                      </div>
                    </div>
                  ) : null}
                </div>
              </div>

              {renderTaskArtifactLinks(
                "Upstream task artifacts",
                "Artifacts from tasks that feed or block this task through dependency links.",
                detailArtifact.upstream_task_artifacts
              )}

              {renderTaskArtifactLinks(
                "Downstream task artifacts",
                "Artifacts from tasks that depend on this task through dependency links.",
                detailArtifact.downstream_task_artifacts
              )}

              <div className="artifact-detail__section">
                <div className="data-panel__header">
                  <div>
                    <h3>Recent artifacts from this task</h3>
                    <p>Task-level artifact history for comparison and provenance review.</p>
                  </div>
                  <div className="status-chip">
                    <span className={`status-chip__dot ${isComparisonRefreshing ? "is-live" : ""}`} />
                    {isComparisonRefreshing ? "Refreshing compare" : "Compare ready"}
                  </div>
                </div>
                <div className="data-list">
                  {(detailArtifact.related_artifacts ?? []).map((item) => (
                    <div key={item.artifact_id} className="data-list__item">
                      <div>
                        <strong>{item.file_name}</strong>
                        <p>{item.display_path}</p>
                        <p>
                          {item.artifact_type}
                          {item.provider_type ? ` | ${item.provider_type}` : ""}
                        </p>
                      </div>
                      <div className="data-list__meta">
                        <span className={`goal-status goal-status--${item.artifact_state}`}>{item.artifact_state}</span>
                        <span>{new Date(item.created_at).toLocaleString()}</span>
                        <button
                          type="button"
                          className="task-action task-action--secondary"
                          onClick={() => setSelectedCompareArtifactId(item.artifact_id)}
                        >
                          {selectedCompareArtifactId === item.artifact_id ? "Comparing" : "Compare"}
                        </button>
                      </div>
                    </div>
                  ))}
                  {(detailArtifact.related_artifacts ?? []).length === 0 ? (
                    <div className="data-list__item">
                      <div>
                        <strong>No related artifacts yet.</strong>
                        <p>This artifact has no recent siblings from the same task to compare against.</p>
                      </div>
                    </div>
                  ) : null}
                </div>
              </div>

              {artifactComparison ? (
                <div className="artifact-detail__section">
                  <h3>Comparison</h3>
                  <div className="artifact-detail__grid">
                    <div>
                      <span>Left</span>
                      <strong>{artifactComparison.left.file_name}</strong>
                    </div>
                    <div>
                      <span>Right</span>
                      <strong>{artifactComparison.right.file_name}</strong>
                    </div>
                    <div>
                      <span>Left state</span>
                      <strong>{artifactComparison.left.artifact_state}</strong>
                    </div>
                    <div>
                      <span>Right state</span>
                      <strong>{artifactComparison.right.artifact_state}</strong>
                    </div>
                  </div>
                  {artifactComparison.comparable ? (
                    <>
                      <p>
                        Unified diff
                        {artifactComparison.truncated ? " (truncated)" : ""}
                      </p>
                      <pre className="artifact-preview">{artifactComparison.unified_diff || "No text differences detected."}</pre>
                    </>
                  ) : (
                    <p>Comparison unavailable: {formatComparisonReason(artifactComparison.reason)}.</p>
                  )}
                </div>
              ) : null}
            </div>
          ) : (
            <div className="data-list__item">
              <div>
                <strong>No artifact selected.</strong>
                <p>Select an artifact row to inspect its metadata and safe file preview.</p>
              </div>
            </div>
          )}
        </article>
      </section>

      <section className="overview-grid">
        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Breakdown</h2>
              <p>Current mix of artifact types and provider sources across the registry.</p>
            </div>
          </header>
          <div className="data-list">
            {(artifacts?.artifact_types ?? []).map((entry) => (
              <div key={`type-${entry.artifact_type}`} className="data-list__item">
                <div>
                  <strong>{entry.artifact_type ?? "unknown"}</strong>
                  <p>Artifact type count</p>
                </div>
                <div className="data-list__meta">
                  <span>{entry.count}</span>
                </div>
              </div>
            ))}
            {(artifacts?.provider_types ?? []).map((entry) => (
              <div key={`provider-${entry.provider_type}`} className="data-list__item">
                <div>
                  <strong>{entry.provider_type ?? "unknown"}</strong>
                  <p>Provider source count</p>
                </div>
                <div className="data-list__meta">
                  <span>{entry.count}</span>
                </div>
              </div>
            ))}
          </div>
        </article>
      </section>
    </section>
  );
}
