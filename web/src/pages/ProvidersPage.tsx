import { useEffect, useState } from "react";
import { StatCard } from "../components/StatCard";
import {
  fetchProviders,
  processProviderJob,
  queueProviderTask,
  runProviderWorkerOnce,
  runProviderPreflight,
  runProviderTask,
  setProviderMode,
  setProviderSettings
} from "../lib/controlRoomApi";
import { useLivePulse } from "../lib/useLivePulse";
import type { ProviderJobItem, ProviderRunTarget, ProviderStatusItem, ProviderWorkerItem, ProvidersResponse } from "../types";

function buildSettingsDrafts(
  providerItems: ProviderStatusItem[],
  existingDrafts: Record<string, Record<string, string>>,
  resetProviderId?: string
) {
  return Object.fromEntries(
    providerItems.map((provider) => {
      const serverDraft = Object.fromEntries(
        Object.entries(provider.configurable_runtime_controls ?? {}).map(([key, value]) => [
          key,
          value == null ? "" : String(value),
        ])
      );
      const currentDraft = existingDrafts[provider.id] ?? {};

      return [
        provider.id,
        provider.id === resetProviderId
          ? serverDraft
          : Object.fromEntries(
              Object.keys(serverDraft).map((key) => [key, currentDraft[key] ?? serverDraft[key]])
            ),
      ];
    })
  );
}

function formatRuntimeControls(provider: ProviderStatusItem) {
  const controls = provider.runtime_controls ?? {};
  const rows = [];

  if (controls.cli_command) {
    rows.push(`CLI: ${controls.cli_command}`);
  }
  if (typeof controls.timeout_seconds === "number") {
    rows.push(`Timeout: ${controls.timeout_seconds}s`);
  }
  if (controls.permission_mode) {
    rows.push(`Permission mode: ${controls.permission_mode}`);
  }
  if (controls.sandbox) {
    rows.push(`Sandbox: ${controls.sandbox}`);
  }
  if (controls.model) {
    rows.push(`Model: ${controls.model}`);
  }
  if (typeof controls.job_limit_per_pass === "number") {
    rows.push(`Jobs/pass: ${controls.job_limit_per_pass}`);
  }
  if (typeof controls.queue_paused === "boolean") {
    rows.push(`Queue: ${controls.queue_paused ? "paused" : "running"}`);
  }
  return rows.join(" | ");
}

function formatFailureKind(kind?: string | null) {
  if (!kind) {
    return null;
  }
  return kind.replace(/_/g, " ");
}

function formatStatusLabel(value?: string | null) {
  if (!value) {
    return "unknown";
  }
  return value.replace(/_/g, " ");
}

async function waitForMinimumFeedback(startedAt: number, minimumMs = 700) {
  const remaining = minimumMs - (Date.now() - startedAt);
  if (remaining > 0) {
    await new Promise((resolve) => window.setTimeout(resolve, remaining));
  }
}

export function ProvidersPage() {
  const [providers, setProviders] = useState<ProvidersResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingRun, setPendingRun] = useState<string | null>(null);
  const [pendingQueue, setPendingQueue] = useState<string | null>(null);
  const [pendingJobProcess, setPendingJobProcess] = useState<string | null>(null);
  const [pendingWorkerRun, setPendingWorkerRun] = useState<string | null>(null);
  const [pendingMode, setPendingMode] = useState<string | null>(null);
  const [pendingSettings, setPendingSettings] = useState<string | null>(null);
  const [pendingPreflight, setPendingPreflight] = useState<string | null>(null);
  const [settingsDrafts, setSettingsDrafts] = useState<Record<string, Record<string, string>>>({});
  const livePulse = useLivePulse();

  useEffect(() => {
    let mounted = true;

    async function loadProviders() {
      const payload = await fetchProviders();
      if (mounted) {
        setProviders(payload);
        setSettingsDrafts((current) => buildSettingsDrafts(payload.providers, current));
      }
    }

    void loadProviders();
    return () => {
      mounted = false;
    };
  }, [livePulse]);

  const items = providers?.providers ?? [];
  const configuredLiveCount = items.filter((provider) => provider.status === "configured").length;
  const simulatedCount = items.filter((provider) => provider.configured_execution_mode === "local_simulation").length;
  const misconfiguredCount = items.filter((provider) => provider.status === "misconfigured").length;
  const totalRuns = items.reduce((sum, provider) => sum + (provider.run_summary?.total_runs ?? 0), 0);
  const queuedJobs = items.reduce((sum, provider) => sum + (provider.job_summary?.queued_jobs ?? 0), 0);
  const runningJobs = items.reduce((sum, provider) => sum + (provider.job_summary?.running_jobs ?? 0), 0);
  const runTargets = providers?.run_targets ?? [];
  const queuedProviderJobs = providers?.job_queue ?? [];
  const workerSummary = providers?.worker_summary;
  const workerPool = providers?.worker_pool ?? [];

  async function reloadProviders(resetProviderId?: string) {
    const payload = await fetchProviders();
    setProviders(payload);
    setSettingsDrafts((current) => buildSettingsDrafts(payload.providers, current, resetProviderId));
  }

  async function handleRunTask(providerId: string, target: ProviderRunTarget) {
    const actionKey = `${providerId}:${target.task_id}`;
    setPendingRun(actionKey);
    setNotice(null);
    try {
      const payload = await runProviderTask(providerId, target.project_id, target.agent_id, target.task_id);
      await reloadProviders();
      setNotice(`Started ${providerId} run for ${target.title}. Session ${payload.session_id} completed and recorded a provider artifact.`);
    } catch {
      setNotice(`Provider run failed for ${target.title}; the task remains under operator review.`);
    } finally {
      setPendingRun(null);
    }
  }

  async function handleQueueTask(providerId: string, target: ProviderRunTarget) {
    const actionKey = `${providerId}:${target.task_id}`;
    setPendingQueue(actionKey);
    setNotice(null);
    try {
      const payload = await queueProviderTask(providerId, target.project_id, target.agent_id, target.task_id);
      await reloadProviders();
      setNotice(`Queued ${providerId} run for ${target.title}. Job ${payload.job_id} is ready for processing.`);
    } catch {
      setNotice(`Provider queueing failed for ${target.title}; the task was not added to the job queue.`);
    } finally {
      setPendingQueue(null);
    }
  }

  async function handleProcessJob(job: ProviderJobItem) {
    setPendingJobProcess(job.job_id);
    setNotice(null);
    try {
      const payload = await processProviderJob(job.job_id);
      await reloadProviders();
      if (payload.status === "completed") {
        setNotice(`Processed queued ${job.provider_id} job for ${job.title ?? job.task_id}. Session ${payload.session_id} completed.`);
      } else {
        setNotice(
          `Queued ${job.provider_id} job for ${job.title ?? job.task_id} failed: ${payload.failure_kind ?? "runtime_error"}`
        );
      }
    } catch {
      setNotice(`Provider job processing failed for ${job.title ?? job.task_id}.`);
    } finally {
      setPendingJobProcess(null);
    }
  }

  async function handleRunWorker(workerId: string, providerId?: string) {
    const actionKey = `${workerId}:${providerId ?? "all"}`;
    setPendingWorkerRun(actionKey);
    setNotice(null);
    try {
      const payload = await runProviderWorkerOnce(workerId, providerId);
      await reloadProviders();
      if (payload.processed && payload.job) {
        setNotice(`Worker ${payload.worker_id} processed ${payload.job.provider_id} job ${payload.job.job_id}.`);
      } else {
        setNotice(`Worker ${payload.worker_id} found no queued jobs to process.`);
      }
    } catch {
      setNotice(`Worker run failed for ${workerId}.`);
    } finally {
      setPendingWorkerRun(null);
    }
  }

  async function handleSetMode(providerId: string, mode: string) {
    const actionKey = `${providerId}:${mode}`;
    setPendingMode(actionKey);
    setNotice(null);
    try {
      await setProviderMode(providerId, mode);
      await reloadProviders();
      setNotice(`Updated ${providerId} to ${mode}.`);
    } catch {
      setNotice(`Provider mode update failed for ${providerId}; keeping the previous configuration.`);
    } finally {
      setPendingMode(null);
    }
  }

  async function handleRunPreflight(provider: ProviderStatusItem) {
    const startedAt = Date.now();
    setPendingPreflight(provider.id);
    setNotice(null);
    try {
      const payload = await runProviderPreflight(provider.id);
      await waitForMinimumFeedback(startedAt);
      await reloadProviders();
      setNotice(payload.summary);
    } catch (error) {
      await waitForMinimumFeedback(startedAt);
      setNotice(
        error instanceof Error
          ? error.message
          : `Provider preflight failed for ${provider.name}; keeping the previous readiness state.`
      );
    } finally {
      setPendingPreflight(null);
    }
  }

  function updateDraft(providerId: string, field: string, value: string) {
    setSettingsDrafts((current) => ({
      ...current,
      [providerId]: {
        ...(current[providerId] ?? {}),
        [field]: value,
      },
    }));
  }

  async function handleSaveSettings(provider: ProviderStatusItem) {
    const actionKey = provider.id;
    setPendingSettings(actionKey);
    setNotice(null);
    try {
      const draft = settingsDrafts[provider.id] ?? {};
      const payload: Record<string, string | number | boolean> = {};
      Object.entries(draft).forEach(([key, value]) => {
        if (key === "timeout_seconds" || key === "job_limit_per_pass") {
          payload[key] = Number(value);
        } else if (key === "queue_paused") {
          payload[key] = value === "true";
        } else {
          payload[key] = value;
        }
      });
      await setProviderSettings(provider.id, payload);
      await reloadProviders(provider.id);
      setNotice(`Updated runtime settings for ${provider.name}.`);
    } catch {
      setNotice(`Provider settings update failed for ${provider.name}; keeping the previous values.`);
    } finally {
      setPendingSettings(null);
    }
  }

  return (
    <section className="control-page">
      <header className="page-hero">
        <div>
          <span className="eyebrow">Providers</span>
          <h1>Runtime providers and execution modes</h1>
          <p>See which adapters are simulated, which local CLI paths are enabled, and whether any provider config is blocking execution.</p>
        </div>
        {notice ? <p className="filters-panel__notice">{notice}</p> : null}
      </header>

      <section className="stats-grid">
        <StatCard label="Providers" value={items.length} />
        <StatCard label="Live configured" value={configuredLiveCount} tone="good" />
        <StatCard label="Simulated" value={simulatedCount} />
        <StatCard label="Misconfigured" value={misconfiguredCount} tone="warn" />
        <StatCard label="Provider runs" value={totalRuns} />
        <StatCard label="Queued jobs" value={queuedJobs} />
        <StatCard label="Running jobs" value={runningJobs} />
        <StatCard label="Workers" value={workerSummary?.total_workers ?? 0} />
        <StatCard label="Busy workers" value={workerSummary?.busy_workers ?? 0} tone="good" />
        <StatCard label="Offline workers" value={workerSummary?.offline_workers ?? 0} tone="warn" />
      </section>

      <section className="overview-grid">
        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Manual provider runs</h2>
              <p>Only tasks with an assigned agent, active execute grant, and no retry cooldown are shown here.</p>
            </div>
          </header>
          <div className="data-list">
            {runTargets.map((target) => (
              <div key={target.task_id} className="data-list__item">
                <div>
                  <strong>{target.title}</strong>
                  <p>
                    {target.goal_title ?? "Unlinked goal"} | {target.agent_name ?? target.agent_id}
                  </p>
                  <p>
                    Status: {target.status} | Priority: {target.priority}
                    {target.review_state ? ` | ${target.review_state}` : ""}
                  </p>
                </div>
                <div className="data-list__meta">
                  {items.map((provider) => {
                    const actionKey = `${provider.id}:${target.task_id}`;
                    return (
                      <div key={provider.id} className="task-card__actions">
                        <button
                          type="button"
                          className="task-action task-action--secondary"
                          disabled={!provider.is_runnable || pendingRun === actionKey || pendingMode !== null}
                          onClick={() => void handleRunTask(provider.id, target)}
                        >
                          {pendingRun === actionKey ? "Running..." : `Run ${provider.name}`}
                        </button>
                        <button
                          type="button"
                          className="task-action task-action--secondary"
                          disabled={!provider.is_runnable || pendingQueue === actionKey || pendingMode !== null}
                          onClick={() => void handleQueueTask(provider.id, target)}
                        >
                          {pendingQueue === actionKey ? "Queueing..." : `Queue ${provider.name}`}
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Queued provider jobs</h2>
              <p>Queued jobs persist provider execution intent so runs can be processed explicitly instead of tying execution to the request that created them.</p>
            </div>
          </header>
          <div className="data-list">
            {queuedProviderJobs.length === 0 ? <p>No queued provider jobs.</p> : null}
            {queuedProviderJobs.map((job) => (
              <div key={job.job_id} className="data-list__item">
                <div>
                  <strong>{job.title ?? job.task_id}</strong>
                  <p>
                    {job.provider_id} | {job.agent_name ?? job.agent_id}
                    {job.goal_title ? ` | ${job.goal_title}` : ""}
                  </p>
                  <p>
                    Status: {job.status}
                    {job.execution_mode ? ` | ${job.execution_mode}` : ""}
                    {job.started_at ? ` | Started ${new Date(job.started_at).toLocaleString()}` : ""}
                    {!job.started_at ? ` | Queued ${new Date(job.created_at).toLocaleString()}` : ""}
                  </p>
                  {job.failure_kind ? (
                    <p>
                      Failure: {formatFailureKind(job.failure_kind)}
                      {job.failure_detail ? ` | ${job.failure_detail}` : ""}
                    </p>
                  ) : null}
                  {job.session_id ? <p>Session: {job.session_id}</p> : null}
                </div>
                <div className="data-list__meta">
                  {job.status === "queued" ? (
                    <button
                      type="button"
                      className="task-action task-action--secondary"
                      disabled={pendingJobProcess === job.job_id}
                      onClick={() => void handleProcessJob(job)}
                    >
                      {pendingJobProcess === job.job_id ? "Processing..." : "Process now"}
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Provider worker pool</h2>
              <p>Detached workers claim queued provider jobs and execute them outside the request that queued the run.</p>
            </div>
          </header>
          <div className="data-list">
            <div className="data-list__item">
              <div>
                <strong>Run worker pass</strong>
                <p>Use the API helper to simulate a detached worker, or start `maas provider-worker --once/--interval-seconds` from the CLI.</p>
              </div>
              <div className="data-list__meta">
                {items.map((provider) => {
                  const workerId = `worker:${provider.id}`;
                  const actionKey = `${workerId}:${provider.id}`;
                  return (
                    <button
                      key={provider.id}
                      type="button"
                      className="task-action task-action--secondary"
                      disabled={pendingWorkerRun === actionKey}
                      onClick={() => void handleRunWorker(workerId, provider.id)}
                    >
                      {pendingWorkerRun === actionKey ? "Running..." : `Run ${provider.name} worker`}
                    </button>
                  );
                })}
              </div>
            </div>
            {workerPool.length === 0 ? (
              <div className="empty-state empty-state--compact">
                <strong>No provider workers have checked in yet.</strong>
                <p>Queue a provider job or start a worker process when you want detached execution to appear here.</p>
              </div>
            ) : null}
            {workerPool.map((worker: ProviderWorkerItem) => (
              <div key={worker.worker_id} className="data-list__item">
                <div>
                  <strong>{worker.worker_id}</strong>
                  <p>
                    {worker.provider_id ?? "all providers"}
                    {worker.project_name ? ` | ${worker.project_name}` : ""}
                  </p>
                  <p>
                    Status: {worker.status}
                    {worker.current_job_title ? ` | ${worker.current_job_title}` : ""}
                    {typeof worker.heartbeat_age_seconds === "number"
                      ? ` | heartbeat ${worker.heartbeat_age_seconds}s ago`
                      : ""}
                  </p>
                  {worker.last_job_id ? (
                    <p>
                      Last job: {worker.last_job_id}
                      {worker.last_job_status ? ` | ${worker.last_job_status}` : ""}
                    </p>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Provider runtime status</h2>
              <p>Effective mode shows what MAAS will actually execute. Misconfigured providers are blocked instead of falling back silently.</p>
            </div>
          </header>
          <div className="data-list">
            {items.map((provider) => {
              const runtimeControls = formatRuntimeControls(provider);
              const latestPreflight = provider.latest_preflight
                ? `${formatStatusLabel(provider.latest_preflight.status)}${
                    provider.latest_preflight.checked_at
                      ? ` · ${new Date(provider.latest_preflight.checked_at).toLocaleString()}`
                      : ""
                  }`
                : "No preflight recorded";
              return (
                <div key={provider.id} className="data-list__item">
                  <div>
                    <strong>{provider.name}</strong>
                    <p>{provider.notes}</p>
                    <p>
                      Configured mode: {provider.configured_execution_mode} | Effective mode:{" "}
                      {provider.effective_execution_mode ?? "blocked"} | Preflight: {latestPreflight}
                    </p>
                    <p>
                      Runs: {provider.run_summary?.total_runs ?? 0} total | {provider.run_summary?.completed_runs ?? 0} completed |{" "}
                      {provider.run_summary?.failed_runs ?? 0} failed | {provider.run_summary?.timed_out_runs ?? 0} timed out
                    </p>
                    <p>
                      Jobs: {provider.job_summary?.queued_jobs ?? 0} queued | {provider.job_summary?.running_jobs ?? 0} running |{" "}
                      {provider.job_summary?.completed_jobs ?? 0} completed | {provider.job_summary?.failed_jobs ?? 0} failed
                    </p>
                    <p>
                      Failure breakdown: {provider.run_summary?.timeout_failures ?? 0} timeout |{" "}
                      {provider.run_summary?.nonzero_exit_failures ?? 0} non-zero exit |{" "}
                      {provider.run_summary?.runtime_failures ?? 0} runtime
                    </p>
                    {provider.run_summary?.latest_failure_kind ? (
                      <p>
                        Latest failure: {formatFailureKind(provider.run_summary.latest_failure_kind)}
                        {provider.run_summary.latest_failure_at
                          ? ` | ${new Date(provider.run_summary.latest_failure_at).toLocaleString()}`
                          : ""}
                      </p>
                    ) : null}
                    {runtimeControls ? <p>{runtimeControls}</p> : null}
                    <details className="task-card__advanced">
                      <summary>Runtime details</summary>
                      <div className="detail-stack">
                        <p>Available modes: {(provider.available_execution_modes ?? []).join(", ") || "local_simulation"}</p>
                        {provider.run_summary?.last_run_at ? (
                          <p>Last run: {new Date(provider.run_summary.last_run_at).toLocaleString()}</p>
                        ) : null}
                        {provider.latest_preflight?.summary ? <p>{provider.latest_preflight.summary}</p> : null}
                        {(provider.guardrails ?? []).map((guardrail) => (
                          <p key={guardrail}>Guardrail: {guardrail}</p>
                        ))}
                        {provider.config_warnings?.map((warning) => (
                          <p key={warning}>{warning}</p>
                        ))}
                        {provider.latest_preflight?.issues?.map((issue) => (
                          <p key={issue}>{issue}</p>
                        ))}
                        {Object.keys(provider.configurable_runtime_controls ?? {}).length > 0 ? (
                          <div className="field-grid field-grid--two">
                            {Object.entries(provider.configurable_runtime_controls ?? {}).map(([key]) => (
                              <label key={key} className="field-control">
                                <span>{key}</span>
                                {key === "queue_paused" ? (
                                  <select
                                    value={settingsDrafts[provider.id]?.[key] ?? "false"}
                                    onChange={(event) => updateDraft(provider.id, key, event.target.value)}
                                  >
                                    <option value="false">false</option>
                                    <option value="true">true</option>
                                  </select>
                                ) : (
                                  <input
                                    type={key === "timeout_seconds" || key === "job_limit_per_pass" ? "number" : "text"}
                                    value={settingsDrafts[provider.id]?.[key] ?? ""}
                                    onChange={(event) => updateDraft(provider.id, key, event.target.value)}
                                  />
                                )}
                              </label>
                            ))}
                          </div>
                        ) : null}
                        {(provider.recent_runs ?? []).map((run) => (
                          <p key={run.session_id}>
                            Recent run: {run.task_title ?? run.task_id ?? run.session_id} | {formatStatusLabel(run.status)}
                            {run.agent_name ? ` | ${run.agent_name}` : ""}
                            {run.execution_mode ? ` | ${run.execution_mode}` : ""}
                            {run.failure_kind ? ` | ${formatFailureKind(run.failure_kind)}` : ""}
                            {run.started_at ? ` | ${new Date(run.started_at).toLocaleString()}` : ""}
                            {run.failure_detail ? ` | ${run.failure_detail}` : ""}
                          </p>
                        ))}
                      </div>
                    </details>
                  </div>
                  <div className="data-list__meta">
                    {(provider.available_execution_modes ?? []).map((mode) => {
                      const actionKey = `${provider.id}:${mode}`;
                      const label =
                        mode === "local_simulation"
                          ? "Use simulation"
                          : mode === "claude_cli"
                            ? "Enable Claude CLI"
                            : "Enable Codex CLI";
                      return (
                        <button
                          key={mode}
                          type="button"
                          className="task-action task-action--secondary"
                          disabled={
                            provider.configured_execution_mode === mode || pendingMode === actionKey || pendingSettings !== null
                          }
                          onClick={() => void handleSetMode(provider.id, mode)}
                        >
                          {pendingMode === actionKey ? "Updating..." : label}
                        </button>
                      );
                    })}
                    <button
                      type="button"
                      className="task-action task-action--secondary"
                      disabled={pendingPreflight === provider.id || pendingMode !== null || pendingSettings !== null}
                      onClick={() => void handleRunPreflight(provider)}
                    >
                      {pendingPreflight === provider.id ? "Checking..." : "Run preflight"}
                    </button>
                    {Object.keys(provider.configurable_runtime_controls ?? {}).length > 0 ? (
                      <button
                        type="button"
                        className="task-action task-action--secondary"
                        disabled={pendingSettings === provider.id || pendingMode !== null}
                        onClick={() => void handleSaveSettings(provider)}
                      >
                        {pendingSettings === provider.id ? "Saving..." : "Save settings"}
                      </button>
                    ) : null}
                    <span>{provider.kind}</span>
                    <span>{formatStatusLabel(provider.status)}</span>
                    <span>{provider.is_runnable ? "runnable" : "blocked"}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </article>
      </section>
    </section>
  );
}
