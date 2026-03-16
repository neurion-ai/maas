import { startTransition, useDeferredValue, useEffect, useState } from "react";
import { fetchArtifacts } from "../lib/controlRoomApi";
import { useLivePulse } from "../lib/useLivePulse";
import type { ArtifactsResponse } from "../types";
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

export function ArtifactsPage() {
  const [artifacts, setArtifacts] = useState<ArtifactsResponse | null>(null);
  const [query, setQuery] = useState("");
  const [stateFilter, setStateFilter] = useState("all");
  const [providerFilter, setProviderFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [missingOnly, setMissingOnly] = useState(false);
  const [offset, setOffset] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
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
      setNotice(
        usedFallback ? "Artifact refresh failed; showing the most recent available snapshot." : null
      );
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
  }, [deferredQuery, missingOnly, offset, providerFilter, stateFilter, typeFilter]);

  useEffect(() => {
    if (livePulse === 0) {
      return;
    }
    void loadArtifacts();
  }, [livePulse]);

  const visibleItems = artifacts?.items ?? [];
  const hasPreviousPage = (artifacts?.offset ?? 0) > 0;
  const hasNextPage = (artifacts?.offset ?? 0) + visibleItems.length < (artifacts?.filtered_count ?? 0);

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
              <div key={item.artifact_id} className="data-list__item">
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
