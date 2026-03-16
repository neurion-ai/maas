import { useEffect, useState } from "react";
import { StatCard } from "../components/StatCard";
import { fetchProviders } from "../lib/controlRoomApi";
import { useLivePulse } from "../lib/useLivePulse";
import type { ProviderStatusItem, ProvidersResponse } from "../types";

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

export function ProvidersPage() {
  const [providers, setProviders] = useState<ProvidersResponse | null>(null);
  const livePulse = useLivePulse();

  useEffect(() => {
    let mounted = true;

    async function loadProviders() {
      const payload = await fetchProviders();
      if (mounted) {
        setProviders(payload);
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

  return (
    <section className="control-page">
      <header className="page-hero">
        <div>
          <span className="eyebrow">Providers</span>
          <h1>Runtime providers and execution modes</h1>
          <p>See which adapters are simulated, which local CLI paths are enabled, and whether any provider config is blocking execution.</p>
        </div>
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
                    {provider.run_summary?.last_run_at ? (
                      <p>Last run: {new Date(provider.run_summary.last_run_at).toLocaleString()}</p>
                    ) : null}
                    <p>Available modes: {(provider.available_execution_modes ?? []).join(", ") || "local_simulation"}</p>
                    {runtimeControls ? <p>{runtimeControls}</p> : null}
                    {provider.config_warnings?.map((warning) => (
                      <p key={warning}>{warning}</p>
                    ))}
                    {(provider.recent_runs ?? []).map((run) => (
                      <p key={run.session_id}>
                        Recent run: {run.task_title ?? run.task_id ?? run.session_id} | {run.status}
                        {run.agent_name ? ` | ${run.agent_name}` : ""}
                        {run.started_at ? ` | ${new Date(run.started_at).toLocaleString()}` : ""}
                      </p>
                    ))}
                  </div>
                  <div className="data-list__meta">
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
