import { useEffect, useState } from "react";
import { StatCard } from "../components/StatCard";
import { fetchProviders, runProviderTask, setProviderMode, setProviderSettings } from "../lib/controlRoomApi";
import { useLivePulse } from "../lib/useLivePulse";
import type { ProviderRunTarget, ProviderStatusItem, ProvidersResponse } from "../types";

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
  return rows.join(" | ");
}

function formatFailureKind(kind?: string | null) {
  if (!kind) {
    return null;
  }
  return kind.replace(/_/g, " ");
}

export function ProvidersPage() {
  const [providers, setProviders] = useState<ProvidersResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingRun, setPendingRun] = useState<string | null>(null);
  const [pendingMode, setPendingMode] = useState<string | null>(null);
  const [pendingSettings, setPendingSettings] = useState<string | null>(null);
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
  const runTargets = providers?.run_targets ?? [];

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
      const payload: Record<string, string | number> = {};
      Object.entries(draft).forEach(([key, value]) => {
        payload[key] = key === "timeout_seconds" ? Number(value) : value;
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
                      <button
                        key={provider.id}
                        type="button"
                        className="task-action task-action--secondary"
                        disabled={!provider.is_runnable || pendingRun === actionKey || pendingMode !== null}
                        onClick={() => void handleRunTask(provider.id, target)}
                      >
                        {pendingRun === actionKey ? "Running..." : `Run ${provider.name}`}
                      </button>
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
              <h2>Provider runtime status</h2>
              <p>Effective mode shows what MAAS will actually execute. Misconfigured providers are blocked instead of falling back silently.</p>
            </div>
          </header>
          <div className="data-list">
            {items.map((provider) => {
              const runtimeControls = formatRuntimeControls(provider);
              return (
                <div key={provider.id} className="data-list__item">
                  <div>
                    <strong>{provider.name}</strong>
                    <p>{provider.notes}</p>
                    <p>
                      Configured mode: {provider.configured_execution_mode} | Effective mode:{" "}
                      {provider.effective_execution_mode ?? "blocked"}
                    </p>
                    <p>
                      Runs: {provider.run_summary?.total_runs ?? 0} total | {provider.run_summary?.completed_runs ?? 0} completed |{" "}
                      {provider.run_summary?.failed_runs ?? 0} failed | {provider.run_summary?.timed_out_runs ?? 0} timed out
                    </p>
                    <p>
                      Failure breakdown: {provider.run_summary?.timeout_failures ?? 0} timeout |{" "}
                      {provider.run_summary?.nonzero_exit_failures ?? 0} non-zero exit |{" "}
                      {provider.run_summary?.runtime_failures ?? 0} runtime
                    </p>
                    {provider.run_summary?.last_run_at ? (
                      <p>Last run: {new Date(provider.run_summary.last_run_at).toLocaleString()}</p>
                    ) : null}
                    {provider.run_summary?.latest_failure_kind ? (
                      <p>
                        Latest failure: {formatFailureKind(provider.run_summary.latest_failure_kind)}
                        {provider.run_summary.latest_failure_at
                          ? ` | ${new Date(provider.run_summary.latest_failure_at).toLocaleString()}`
                          : ""}
                      </p>
                    ) : null}
                    <p>Available modes: {(provider.available_execution_modes ?? []).join(", ") || "local_simulation"}</p>
                    {runtimeControls ? <p>{runtimeControls}</p> : null}
                    {(provider.guardrails ?? []).map((guardrail) => (
                      <p key={guardrail}>Guardrail: {guardrail}</p>
                    ))}
                    {provider.config_warnings?.map((warning) => (
                      <p key={warning}>{warning}</p>
                    ))}
                    {Object.keys(provider.configurable_runtime_controls ?? {}).length > 0 ? (
                      <div>
                        {Object.entries(provider.configurable_runtime_controls ?? {}).map(([key]) => (
                          <label key={key}>
                            {key}
                            <input
                              type={key === "timeout_seconds" ? "number" : "text"}
                              value={settingsDrafts[provider.id]?.[key] ?? ""}
                              onChange={(event) => updateDraft(provider.id, key, event.target.value)}
                            />
                          </label>
                        ))}
                      </div>
                    ) : null}
                    {(provider.recent_runs ?? []).map((run) => (
                      <p key={run.session_id}>
                        Recent run: {run.task_title ?? run.task_id ?? run.session_id} | {run.status}
                        {run.agent_name ? ` | ${run.agent_name}` : ""}
                        {run.execution_mode ? ` | ${run.execution_mode}` : ""}
                        {run.failure_kind ? ` | ${formatFailureKind(run.failure_kind)}` : ""}
                        {run.started_at ? ` | ${new Date(run.started_at).toLocaleString()}` : ""}
                        {run.failure_detail ? ` | ${run.failure_detail}` : ""}
                      </p>
                    ))}
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
                    <span>{provider.status}</span>
                    <span>{provider.lifecycle_version}</span>
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
