import { useEffect, useState } from "react";
import { StatCard } from "../components/StatCard";
import { fetchPortfolio, runOrchestratorPass } from "../lib/controlRoomApi";
import { setSelectedProjectId } from "../lib/projectScope";
import { useLivePulse } from "../lib/useLivePulse";
import type { OrchestratorRunResponse, PortfolioResponse } from "../types";

function healthLabel(health: string) {
  if (health === "critical") {
    return "Critical";
  }
  if (health === "warn") {
    return "Needs attention";
  }
  if (health === "archived") {
    return "Archived";
  }
  return "Healthy";
}

export function PortfolioPage() {
  const [portfolio, setPortfolio] = useState<PortfolioResponse | null>(null);
  const [orchestratorResult, setOrchestratorResult] = useState<OrchestratorRunResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [runningOrchestrator, setRunningOrchestrator] = useState(false);
  const livePulse = useLivePulse();

  useEffect(() => {
    let mounted = true;

    async function loadPortfolio() {
      try {
        const payload = await fetchPortfolio();
        if (mounted) {
          setPortfolio(payload);
        }
      } catch {
        if (mounted) {
          setNotice("Portfolio view is unavailable; keeping the last project list snapshot.");
        }
      }
    }

    void loadPortfolio();
    return () => {
      mounted = false;
    };
  }, [livePulse]);

  async function handleRunOrchestrator() {
    setRunningOrchestrator(true);
    setNotice(null);
    try {
      const payload = await runOrchestratorPass(4, 2);
      setOrchestratorResult(payload);
      setPortfolio(await fetchPortfolio());
      setNotice(
        `Orchestrator assigned ${payload.assigned_count} tasks, processed ${payload.provider_jobs_processed} queued jobs, and touched ${payload.project_runs.length} projects.`
      );
    } catch {
      setNotice("Orchestrator pass failed; keeping the current portfolio snapshot.");
    } finally {
      setRunningOrchestrator(false);
    }
  }

  return (
    <section className="control-page">
      <header className="page-hero">
        <div>
          <span className="eyebrow">Portfolio</span>
          <h1>Cross-project portfolio</h1>
          <p>Track which projects are blocked, noisy, or runtime-unready without switching the active scope first.</p>
        </div>
        <div className="page-hero__actions">
          <button
            type="button"
            className="task-action task-action--secondary"
            disabled={runningOrchestrator}
            onClick={() => void handleRunOrchestrator()}
          >
            {runningOrchestrator ? "Running orchestrator..." : "Run orchestrator pass"}
          </button>
          {notice ? <p className="page-hero__notice">{notice}</p> : null}
        </div>
      </header>

      <section className="stats-grid">
        <StatCard label="Active projects" value={portfolio?.summary.active_projects ?? 0} />
        <StatCard label="Projects with issues" value={portfolio?.summary.projects_with_issues ?? 0} tone="warn" />
        <StatCard label="Open alerts" value={portfolio?.summary.open_alerts ?? 0} tone="warn" />
        <StatCard label="Blocked tasks" value={portfolio?.summary.blocked_tasks ?? 0} tone="warn" />
        <StatCard label="Active sessions" value={portfolio?.summary.active_sessions ?? 0} />
        <StatCard label="Recovery pressure" value={portfolio?.summary.recovery_pressure ?? 0} tone="warn" />
      </section>

      <article className="data-panel">
        <header className="data-panel__header">
          <div>
            <h2>Project health</h2>
            <p>Each row rolls up alerts, blocked work, recovery pressure, and provider readiness for that project.</p>
          </div>
          {orchestratorResult ? (
            <span className="status-chip">
              Last pass: {orchestratorResult.provider_jobs_processed} jobs, {orchestratorResult.assigned_count} assignments
            </span>
          ) : null}
        </header>
        <div className="data-list">
          {portfolio?.projects.map((project) => (
            <div key={project.project_id} className="data-list__item">
              <div>
                <strong>{project.name}</strong>
                <p>{project.description || project.project_type}</p>
                <p>
                  {healthLabel(project.health)} · {project.onboarding_mode ?? "greenfield"} · {project.state}
                </p>
                <p>
                  {project.blocked_tasks} blocked · {project.open_alerts} open alerts · {project.active_sessions} active sessions ·{" "}
                  {project.open_quarantine_entries + project.dead_letter_entries + project.repeated_failure_tasks} recovery signals
                </p>
                <p>
                  Providers ready {project.provider_readiness.ready}/{project.provider_readiness.total}
                  {project.provider_readiness.issues ? ` · ${project.provider_readiness.issues} issues` : ""}
                  {project.provider_readiness.unknown ? ` · ${project.provider_readiness.unknown} unknown` : ""}
                </p>
              </div>
              <div className="data-list__meta">
                <span>{project.task_count} tasks</span>
                <span>{project.agent_count} agents</span>
                <button
                  type="button"
                  className="task-action task-action--secondary"
                  disabled={project.state === "archived"}
                  onClick={() => setSelectedProjectId(project.project_id)}
                >
                  Open project
                </button>
              </div>
            </div>
          ))}
        </div>
      </article>
    </section>
  );
}
