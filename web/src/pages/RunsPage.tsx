import { useEffect, useMemo, useState } from "react";
import { StatCard } from "../components/StatCard";
import {
  fetchActivity,
  fetchArtifacts,
  fetchProviders,
  processProviderJob,
  queueProviderTask,
  runProviderPreflight,
  runProviderTask,
  runProviderWorkerOnce
} from "../lib/controlRoomApi";
import { useLivePulse } from "../lib/useLivePulse";
import type { ActivityItem, ArtifactsResponse, ProviderJobItem, ProviderRunTarget, ProviderStatusItem, ProvidersResponse } from "../types";
import { ActivityPage } from "./ActivityPage";
import { AgentRosterPage } from "./AgentRosterPage";
import { ArtifactsPage } from "./ArtifactsPage";
import { ProvidersPage } from "./ProvidersPage";

function formatTime(value?: string | null) {
  if (!value) {
    return "Not recorded";
  }
  return new Date(value).toLocaleString();
}

function failureLabel(provider: ProviderStatusItem) {
  const kind = provider.run_summary?.latest_failure_kind;
  if (!kind) {
    return "No recent live failures";
  }
  return kind.replaceAll("_", " ");
}

function providerStatusTone(provider: ProviderStatusItem) {
  if (provider.status === "misconfigured") {
    return "danger";
  }
  if (provider.config_warnings?.length || provider.guardrails?.length) {
    return "warn";
  }
  return "default";
}

function preflightBadge(provider: ProviderStatusItem) {
  const status = provider.latest_preflight?.status ?? null;
  if (status === "passed" || status === "simulation_ready") {
    return {
      label: status === "simulation_ready" ? "Ready in simulation" : "Ready",
      tone: "good" as const,
    };
  }
  if (status === "failed") {
    return {
      label: "Preflight failed",
      tone: "critical" as const,
    };
  }
  return {
    label: "Not checked",
    tone: "default" as const,
  };
}

async function waitForMinimumFeedback(startedAt: number, minimumMs = 700) {
  const remaining = minimumMs - (Date.now() - startedAt);
  if (remaining > 0) {
    await new Promise((resolve) => window.setTimeout(resolve, remaining));
  }
}

export function RunsPage() {
  const [providers, setProviders] = useState<ProvidersResponse | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactsResponse | null>(null);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [advancedStudiosOpen, setAdvancedStudiosOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingActionKey, setPendingActionKey] = useState<string | null>(null);
  const [providerFeedback, setProviderFeedback] = useState<Record<string, string | null>>({});
  const livePulse = useLivePulse();

  async function loadRuns() {
    const [providersPayload, artifactsPayload, activityPayload] = await Promise.all([
      fetchProviders(),
      fetchArtifacts({ limit: 8, offset: 0 }),
      fetchActivity()
    ]);
    setProviders(providersPayload);
    setArtifacts(artifactsPayload);
    setActivity(activityPayload);
  }

  async function refreshProvidersOnly() {
    const providersPayload = await fetchProviders();
    setProviders(providersPayload);
  }

  useEffect(() => {
    let mounted = true;

    async function load() {
      try {
        const [providersPayload, artifactsPayload, activityPayload] = await Promise.all([
          fetchProviders(),
          fetchArtifacts({ limit: 8, offset: 0 }),
          fetchActivity()
        ]);
        if (!mounted) {
          return;
        }
        setProviders(providersPayload);
        setArtifacts(artifactsPayload);
        setActivity(activityPayload);
      } catch {
        if (mounted) {
          setNotice("Runs surface refresh failed; keeping the latest available runtime state.");
        }
      }
    }

    void load();
    return () => {
      mounted = false;
    };
  }, [livePulse]);

  async function runAction(actionKey: string, message: string, action: () => Promise<unknown>, fallback: string) {
    setPendingActionKey(actionKey);
    setNotice(null);
    try {
      await action();
      await loadRuns();
      setNotice(message);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : fallback);
    } finally {
      setPendingActionKey(null);
    }
  }

  async function handleRunPreflight(provider: ProviderStatusItem) {
    const actionKey = `preflight:${provider.id}`;
    const startedAt = Date.now();
    setPendingActionKey(actionKey);
    setProviderFeedback((current) => ({ ...current, [provider.id]: null }));
    try {
      await runProviderPreflight(provider.id);
      await waitForMinimumFeedback(startedAt);
      await refreshProvidersOnly();
    } catch (error) {
      await waitForMinimumFeedback(startedAt);
      setProviderFeedback((current) => ({
        ...current,
        [provider.id]: error instanceof Error ? error.message : `Provider preflight failed for ${provider.name}.`,
      }));
    } finally {
      setPendingActionKey(null);
    }
  }

  const providerItems = providers?.providers ?? [];
  const runTargets = providers?.run_targets ?? [];
  const queuedJobs = providers?.job_queue ?? [];
  const workerPool = providers?.worker_pool ?? [];

  const runSummary = useMemo(() => {
    return providerItems.reduce(
      (acc, provider) => {
        acc.ready += provider.status === "configured" ? 1 : 0;
        acc.issues += provider.status === "misconfigured" ? 1 : 0;
        acc.totalRuns += provider.run_summary?.total_runs ?? 0;
        acc.queued += provider.job_summary?.queued_jobs ?? 0;
        acc.running += provider.job_summary?.running_jobs ?? 0;
        return acc;
      },
      { ready: 0, issues: 0, totalRuns: 0, queued: 0, running: 0 }
    );
  }, [providerItems]);

  return (
    <section className="dashboard-page">
      <header className="dashboard-hero">
        <div className="dashboard-hero__content">
          <span className="eyebrow">Runs</span>
          <h1>Execution, workers, and outputs</h1>
          <p>Supervise provider readiness, launch queued work, watch workers, and inspect the newest outputs from one runtime surface.</p>
          <div className="hero-meta">
            <span className="hero-meta__pill">{runSummary.ready} runnable providers</span>
            <span className="hero-meta__pill">{runSummary.queued} queued jobs</span>
            <span className="hero-meta__pill">{workerPool.length} workers tracked</span>
          </div>
        </div>
      </header>

      {notice ? <div className="banner banner--info">{notice}</div> : null}

      <section className="stats-grid stats-grid--dense">
        <StatCard label="Runnable providers" value={runSummary.ready} tone="good" />
        <StatCard label="Providers with issues" value={runSummary.issues} tone="warn" />
        <StatCard label="Queued jobs" value={runSummary.queued} />
        <StatCard label="Running jobs" value={runSummary.running} />
        <StatCard label="Tracked workers" value={workerPool.length} />
        <StatCard label="Runtime artifacts" value={artifacts?.summary.total_artifacts ?? 0} />
        <StatCard label="Missing files" value={artifacts?.summary.missing_files ?? 0} tone="warn" />
        <StatCard label="Recorded runs" value={runSummary.totalRuns} />
      </section>

      <section className="two-column-grid">
        <article className="surface-card">
          <div className="surface-card__header">
            <div>
              <span className="eyebrow">Provider posture</span>
              <h2>Can MAAS execute safely right now?</h2>
            </div>
          </div>
          <div className="card-grid">
            {providerItems.map((provider) => (
              <div key={provider.id} className={`mini-card mini-card--${providerStatusTone(provider)}`}>
                {(() => {
                  const readiness = preflightBadge(provider);
                  return (
                    <div className="provider-readiness">
                      <span className={`provider-readiness__badge provider-readiness__badge--${readiness.tone}`}>
                        <span className={`status-dot status-dot--${readiness.tone}`} />
                        {readiness.label}
                      </span>
                      {provider.latest_preflight?.checked_at ? (
                        <span className="provider-readiness__meta">{formatTime(provider.latest_preflight.checked_at)}</span>
                      ) : null}
                    </div>
                  );
                })()}
                <div className="mini-card__header">
                  <strong>{provider.name}</strong>
                  <span className="status-pill">{provider.execution_mode}</span>
                </div>
                <p>{provider.notes}</p>
                <div className={`provider-preflight-trace ${provider.latest_preflight ? "" : "provider-preflight-trace--empty"}`}>
                  <span className="provider-preflight-trace__label">Last check</span>
                  {provider.latest_preflight ? (
                    <>
                      <strong>{formatTime(provider.latest_preflight.checked_at)}</strong>
                      <p>{provider.latest_preflight.summary}</p>
                    </>
                  ) : (
                    <p>No preflight recorded yet.</p>
                  )}
                </div>
                {pendingActionKey === `preflight:${provider.id}` ? (
                  <p className="provider-preflight-feedback">Checking runtime readiness…</p>
                ) : null}
                {!pendingActionKey && providerFeedback[provider.id] ? (
                  <p className="provider-preflight-feedback provider-preflight-feedback--error">{providerFeedback[provider.id]}</p>
                ) : null}
                <p>
                  Recent failure: {failureLabel(provider)}
                  {provider.run_summary?.latest_failure_at
                    ? ` · ${formatTime(provider.run_summary.latest_failure_at)}`
                    : ""}
                </p>
                <div className="surface-card__actions">
                  <button
                    type="button"
                    className={`hero-button hero-button--compact ${provider.latest_preflight ? "hero-button--ghost" : ""}`}
                    disabled={pendingActionKey === `preflight:${provider.id}`}
                    onClick={() => void handleRunPreflight(provider)}
                  >
                    {pendingActionKey === `preflight:${provider.id}`
                      ? "Checking..."
                      : provider.latest_preflight
                        ? "Re-check"
                        : "Run preflight"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="surface-card">
          <div className="surface-card__header">
            <div>
              <span className="eyebrow">Launch queue</span>
              <h2>Manual run targets</h2>
            </div>
          </div>
          <div className="list-stack">
            {runTargets.length ? (
              runTargets.slice(0, 8).map((target: ProviderRunTarget) => (
                <div key={`${target.project_id}:${target.task_id}`} className="list-row">
                  <div>
                    <strong>{target.title}</strong>
                    <p>
                      {target.goal_title ?? "Unlinked goal"}
                      {target.agent_name ? ` · ${target.agent_name}` : ""}
                    </p>
                    <p>
                      {target.status} · P{target.priority}
                      {target.review_state ? ` · ${target.review_state}` : ""}
                    </p>
                  </div>
                  <div className="list-row__meta list-row__meta--actions">
                    {providerItems.slice(0, 2).map((provider) => (
                      <button
                        key={`${provider.id}:${target.task_id}:queue`}
                        type="button"
                        className="hero-button hero-button--compact"
                        disabled={pendingActionKey === `queue:${provider.id}:${target.task_id}`}
                        onClick={() =>
                          void runAction(
                            `queue:${provider.id}:${target.task_id}`,
                            `Queued ${provider.name} for ${target.title}.`,
                            () => queueProviderTask(provider.id, target.project_id, target.agent_id, target.task_id),
                            `Failed to queue ${provider.name} for ${target.title}.`
                          )
                        }
                      >
                        {pendingActionKey === `queue:${provider.id}:${target.task_id}` ? "Queueing..." : `Queue ${provider.name}`}
                      </button>
                    ))}
                    {providerItems[0] ? (
                      <button
                        type="button"
                        className="hero-button hero-button--ghost hero-button--compact"
                        disabled={pendingActionKey === `run:${providerItems[0].id}:${target.task_id}`}
                        onClick={() =>
                          void runAction(
                            `run:${providerItems[0].id}:${target.task_id}`,
                            `Started ${providerItems[0].name} for ${target.title}.`,
                            () => runProviderTask(providerItems[0].id, target.project_id, target.agent_id, target.task_id),
                            `Direct run failed for ${target.title}.`
                          )
                        }
                      >
                        {pendingActionKey === `run:${providerItems[0].id}:${target.task_id}` ? "Running..." : `Run ${providerItems[0].name} now`}
                      </button>
                    ) : null}
                  </div>
                </div>
              ))
            ) : (
              <div className="empty-state empty-state--compact">
                <strong>No safe run targets are currently available.</strong>
                <p>Work becomes runnable here when it is assigned, permissioned, and outside retry cooldown.</p>
              </div>
            )}
          </div>
        </article>
      </section>

      <section className="two-column-grid">
        <article className="surface-card">
          <div className="surface-card__header">
            <div>
              <span className="eyebrow">Workers and jobs</span>
              <h2>Queue processing</h2>
            </div>
          </div>
          <div className="list-stack">
            {queuedJobs.slice(0, 6).map((job: ProviderJobItem) => (
              <div key={job.job_id} className="list-row">
                <div>
                  <strong>{job.title ?? job.task_id}</strong>
                  <p>
                    {job.provider_id} · {job.project_name ?? job.project_id}
                  </p>
                  <p>{job.status} · queued {formatTime(job.created_at)}</p>
                </div>
                <div className="list-row__meta list-row__meta--actions">
                  <button
                    type="button"
                    className="hero-button hero-button--compact"
                    disabled={pendingActionKey === `job:${job.job_id}`}
                    onClick={() =>
                      void runAction(
                        `job:${job.job_id}`,
                        `Processed queued job ${job.job_id}.`,
                        () => processProviderJob(job.job_id),
                        `Failed to process queued job ${job.job_id}.`
                      )
                    }
                  >
                    {pendingActionKey === `job:${job.job_id}` ? "Processing..." : "Process now"}
                  </button>
                </div>
              </div>
            ))}
            {workerPool.slice(0, 4).map((worker) => (
              <div key={worker.worker_id} className="list-row">
                <div>
                  <strong>{worker.worker_id}</strong>
                  <p>
                    {worker.project_name ?? "Global"} · {worker.provider_id ?? "any provider"}
                  </p>
                  <p>
                    {worker.status}
                    {worker.current_job_title ? ` · ${worker.current_job_title}` : ""}
                    {worker.heartbeat_age_seconds != null ? ` · heartbeat ${worker.heartbeat_age_seconds}s` : ""}
                  </p>
                </div>
                <div className="list-row__meta list-row__meta--actions">
                  <button
                    type="button"
                    className="hero-button hero-button--compact"
                    disabled={pendingActionKey === `worker:${worker.worker_id}`}
                    onClick={() =>
                      void runAction(
                        `worker:${worker.worker_id}`,
                        `Worker ${worker.worker_id} ran one queue pass.`,
                        () => runProviderWorkerOnce(worker.worker_id, worker.provider_id ?? undefined),
                        `Worker run failed for ${worker.worker_id}.`
                      )
                    }
                  >
                    {pendingActionKey === `worker:${worker.worker_id}` ? "Running..." : "Run worker once"}
                  </button>
                </div>
              </div>
            ))}
            {!queuedJobs.length && !workerPool.length ? (
              <div className="empty-state empty-state--compact">
                <strong>No provider jobs or workers are visible yet.</strong>
                <p>Queue a run target or configure worker execution to populate this view.</p>
              </div>
            ) : null}
          </div>
        </article>

        <article className="surface-card">
          <div className="surface-card__header">
            <div>
              <span className="eyebrow">Recent outputs</span>
              <h2>Latest artifacts and runtime movement</h2>
            </div>
          </div>
          <div className="list-stack">
            {(artifacts?.items ?? []).slice(0, 5).map((artifact) => (
              <div key={artifact.artifact_id} className="list-row">
                <div>
                  <strong>{artifact.file_name}</strong>
                  <p>
                    {artifact.task_title ?? artifact.task_id ?? "Unknown task"}
                    {artifact.agent_name ? ` · ${artifact.agent_name}` : ""}
                  </p>
                  <p>
                    {artifact.artifact_type} · {artifact.provider_type ?? "unknown provider"} · {artifact.artifact_state}
                  </p>
                </div>
                <div className="list-row__meta">
                  <span>{artifact.exists ? "available" : "missing"}</span>
                  <span>{formatTime(artifact.created_at)}</span>
                </div>
              </div>
            ))}
            {activity.slice(0, 5).map((item) => (
              <div key={item.activity_id ?? `${item.action}:${item.created_at}`} className="list-row">
                <div>
                  <strong>{item.description}</strong>
                  <p>{item.action}</p>
                </div>
                <div className="list-row__meta">
                  <span className={`status-pill status-pill--${item.severity === "warning" ? "warn" : item.severity === "critical" ? "danger" : "default"}`}>
                    {item.severity}
                  </span>
                  <span>{formatTime(item.created_at)}</span>
                </div>
              </div>
            ))}
            {!artifacts?.items.length && !activity.length ? (
              <div className="empty-state empty-state--compact">
                <strong>No runtime output has been recorded yet.</strong>
                <p>Once providers run, MAAS will surface both artifacts and activity here.</p>
              </div>
            ) : null}
          </div>
        </article>
      </section>

      <details
        className="advanced-pane"
        onToggle={(event) => setAdvancedStudiosOpen((event.currentTarget as HTMLDetailsElement).open)}
      >
        <summary>Advanced runtime studios</summary>
        {advancedStudiosOpen ? (
          <div className="advanced-pane__content">
            <div className="embedded-page">
              <ProvidersPage />
            </div>
            <div className="embedded-page">
              <ArtifactsPage />
            </div>
            <div className="embedded-page">
              <AgentRosterPage />
            </div>
            <div className="embedded-page">
              <ActivityPage />
            </div>
          </div>
        ) : null}
      </details>
    </section>
  );
}
